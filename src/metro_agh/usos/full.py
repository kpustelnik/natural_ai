"""The whole USOS timetable of a term, not only what the campus model uses (``usos/all/``).

``01_fetch_usos.py`` in full mode walks every faculty's catalogue, so these tables cover
every programme and semester (course groups), every course, every class group with its
registered students and limits, and every dated meeting of the term in any room or
building, including weekends, off-campus rooms and one-off dates. The model tables of
``parse.build_tables`` are a filtered view of the same crawl.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import pandas as pd

from ..schemas.tables import CLASS_GROUPS, COURSE_GROUPS, COURSES, MEETINGS
from .fetch import Crawl
from .parse import cohort_id, group_ids, programme_of, semester_of, study_level

log = logging.getLogger(__name__)


@dataclass
class FullTables:
    course_groups: pd.DataFrame
    courses: pd.DataFrame
    class_groups: pd.DataFrame
    meetings: pd.DataFrame

    def write(self, out_dir: Path) -> None:
        out = Path(out_dir)
        COURSE_GROUPS.write(self.course_groups, out / COURSE_GROUPS.path)
        COURSES.write(self.courses, out / COURSES.path)
        CLASS_GROUPS.write(self.class_groups, out / CLASS_GROUPS.path)
        MEETINGS.write(self.meetings, out / MEETINGS.path)


def _int(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("Int64")


def full_tables(crawl: Crawl, rooms: pd.DataFrame) -> FullTables:
    """``rooms``: ``tables.ROOMS`` of the same crawl (canonical building of every room)."""
    # --- course groups: programmes x semesters (+ elective pools), from every faculty
    groups = dict(crawl.course_groups)
    for page in crawl.courses.values():  # groups only named on course pages
        for g in page.groups:
            groups.setdefault(g.code, g)
    members: dict[str, list[str]] = {code: list(cs) for code, cs in crawl.group_courses.items()}
    for course, page in crawl.courses.items():
        for g in page.groups:
            members.setdefault(g.code, [])
            if course not in members[g.code]:
                members[g.code].append(course)
    cg = pd.DataFrame(
        [
            {
                "code": unquote(code),
                "cohort_id": cohort_id(code),
                "label": g.label,
                "faculty_id": crawl.group_faculty.get(code),
                "programme": programme_of(cohort_id(code)),
                "semester": semester_of(g),
                "level": study_level(code),
                "n_courses": len(members.get(code, [])),
            }
            for code, g in sorted(groups.items())
        ],
        columns=COURSE_GROUPS.column_names,
    ).drop_duplicates("code")
    cg["semester"] = _int(cg["semester"])

    # --- class groups
    gids = group_ids(crawl)
    rows = []
    for uid, unit in sorted(crawl.units.items()):
        for g in unit.groups:
            terms = "; ".join(
                f"{m.frequency}, {m.start}-{m.end}" if m.start else m.frequency for m in g.meetings
            )
            rooms_of = "|".join(dict.fromkeys(m.room_usos_id for m in g.meetings if m.room_usos_id))
            rows.append(
                {
                    "group_id": gids.get((uid, g.group_nr)),
                    "unit_id": uid,
                    "course_id": unit.course_code,
                    "class_type": unit.class_type,
                    "class_type_name": unit.class_type_name,
                    "group_nr": g.group_nr,
                    "enrolled": g.enrolled,
                    "limit": g.limit if g.limit is not None else unit.unit_limit,
                    "hours": unit.hours,
                    "terms": terms or None,
                    "rooms": rooms_of or None,
                }
            )
    groups_df = pd.DataFrame(rows, columns=CLASS_GROUPS.column_names)
    for c in ("enrolled", "limit", "hours"):
        groups_df[c] = _int(groups_df[c])
    groups_df = groups_df[groups_df["group_id"].notna()].reset_index(drop=True)

    # --- courses
    by_course = groups_df.groupby("course_id")
    in_groups: dict[str, list[str]] = {}
    for code, cs in members.items():
        for c in cs:
            in_groups.setdefault(c, []).append(unquote(code))
    per_unit = groups_df.groupby(["course_id", "unit_id"])["enrolled"].sum(min_count=1)
    enrolled = per_unit.groupby("course_id").max()
    courses = pd.DataFrame(
        [
            {
                "course_id": code,
                "course_name": page.name,
                "faculty_id": page.faculty,
                "course_groups": "|".join(sorted(set(in_groups.get(code, [])))) or None,
                "n_units": len(page.units.get(crawl.term, [])),
                "n_groups": int(by_course.size().get(code, 0)),
                "enrolled": enrolled.get(code),
            }
            for code, page in sorted(crawl.courses.items())
        ],
        columns=COURSES.column_names,
    )
    courses["enrolled"] = _int(courses["enrolled"])

    # --- dated meetings
    m = crawl.meetings if crawl.meetings is not None else pd.DataFrame()
    if len(m):
        start = pd.to_datetime(m["start_time"])
        end = pd.to_datetime(m["end_time"])
        building = dict(zip(rooms["room_usos_id"], rooms["building_id"], strict=True))
        room_id = m["room_id"].map(lambda r: None if pd.isna(r) else str(int(r)))
        meetings = pd.DataFrame(
            {
                "date": start.dt.strftime("%Y-%m-%d"),
                "weekday": start.dt.weekday + 1,
                "start": start.dt.strftime("%H:%M"),
                "end": end.dt.strftime("%H:%M"),
                "unit_id": _int(m["unit_id"]),
                "group_nr": _int(m["group_number"]),
                "group_id": [
                    gids.get((int(u), int(g))) if pd.notna(u) and pd.notna(g) else None
                    for u, g in zip(m["unit_id"], m["group_number"], strict=True)
                ],
                "course_id": m["course_id"],
                "class_type": m["classtype_id"],
                "kind": m["type"],
                "building_usos_id": m["building_id"],
                "building_id": room_id.map(building),
                "room_usos_id": room_id,
                "room_number": m["room_number"].replace("", None),
                "frequency": m["frequency"],
            }
        )
        meetings = meetings.sort_values(["date", "start", "group_id"], na_position="last")
        meetings = meetings.drop_duplicates().reset_index(drop=True)
    else:
        meetings = pd.DataFrame(columns=MEETINGS.column_names)
    t = FullTables(cg.reset_index(drop=True), courses, groups_df, meetings)
    for df, table in (
        (t.course_groups, COURSE_GROUPS),
        (t.courses, COURSES),
        (t.class_groups, CLASS_GROUPS),
        (t.meetings, MEETINGS),
    ):
        table.validate(df)
    log.info(
        "all of USOS %s: %d course groups, %d courses, %d class groups, %d dated meetings",
        crawl.term, len(cg), len(courses), len(groups_df), len(meetings),
    )  # fmt: skip
    return t

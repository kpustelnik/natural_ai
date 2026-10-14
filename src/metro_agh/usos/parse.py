"""Crawl -> the stage-1 tables (docs/data_contracts.md, section 4).

- **Buildings and rooms.** USOS building ids (``D17``, ``HA1``, ``PA3/A4``) become canonical
  ids (``D-17``, ``H-A1``, ``P-A3-A4``) by the ``aliases`` of the building YAMLs, or by
  inserting a hyphen where that gives a known building. ``usos_room_map.csv`` overrides
  single rooms. Meetings in buildings the campus does not model are dropped (counted).
- **Week parity.** From the group's frequency text: "każdy wtorek" -> ``all``,
  "co drugi wtorek (nieparzyste)" -> ``odd``. "wielokrotnie" (several dates) is kept as
  ``all`` only when the group was on a room plan of the crawled week, on that day.
  Weekends and one-off meetings are not part of a teaching week and are dropped.
- **Group size** (``size_source``): the USOS count of registered students when it is
  positive (``usos``); else the group / unit limit (``estimate``); else 60 % of the
  smallest room the group meets in (``room_capacity``); else the median of the class type.
- **Cohorts** are USOS course groups ("grupy przedmiotów", e.g. ``240-INF-1S-1R-Z`` =
  Informatyka, 1st cycle, semester 1) that name a semester. A specialisation
  (``ELT_1S_sem_5_A``) also attends the courses of its parent (``ELT_1S_sem_5``). A
  cohort's size is the 75th percentile, over its courses, of the course's registered
  students split evenly between the cohorts that share it: lectures everyone attends
  dominate the upper quantiles, electives do not. Two course groups of the same students
  (``GNR_1S-s1_ALL`` / ``GNR_1S-s1_PP``, or a year and its elective list) are merged first
  (``duplicate_cohorts``), so nobody is counted twice. A course in no cohort (languages, PE,
  humanities) is linked to a pool, ``pool:1S`` = every first-cycle full-time cohort (or
  ``pool:all``): its students are regular students of those cohorts, not extra people.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from urllib.parse import unquote

import numpy as np
import pandas as pd

from ..schemas.common import BUILDING_ID_PATTERN
from ..schemas.tables import COHORTS, GROUP_COHORTS, GROUPS, ROOMS, TIMETABLE
from .fetch import Crawl
from .pages import CourseGroup, Tile

log = logging.getLogger(__name__)

ROOM_FILL = 0.6  # share of a room's seats taken when nothing else is known
COHORT_QUANTILE = 0.75
DUP_SHARE = 0.8  # a course group inside another one by this share is the same students
DUP_MIN = 3  # ... when it has at least this many running courses
POOL = "pool:"  # group_cohorts.cohort_id of a course in no cohort: pool:1S, pool:2S, pool:all


# --- ids ---------------------------------------------------------------------------------


def building_resolver(known: set[str], aliases: dict[str, str]):
    """USOS building id -> canonical building id (or None)."""
    by_lower = {k.lower(): k for k in known}
    alias_lower = {a.lower(): b for a, b in aliases.items()}

    def resolve(usos_id: str | None) -> str | None:
        if not usos_id:
            return None
        s = usos_id.strip()
        if s.lower() in alias_lower:
            return alias_lower[s.lower()]
        flat = s.replace("/", "-")
        if flat.lower() in by_lower:
            return by_lower[flat.lower()]
        letters = re.match(r"^[A-Za-z]+", flat)
        for i in range(1, len(letters.group(0)) + 1 if letters else 0):
            cand = f"{flat[:i]}-{flat[i:]}".lower()
            if cand in by_lower:
                return by_lower[cand]
        return None

    return resolve


def room_key(number: str | None) -> str | None:
    """USOS room number -> a room id matching ``ROOM_ID_PATTERN`` (``-1.15c`` -> ``m1.15c``)."""
    if not number:
        return None
    s = re.sub(r"^-", "m", number.strip())
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_.-")
    return s or None


def semester_of(group: CourseGroup) -> int | None:
    label, code = group.label, unquote(group.code)
    for rx in (r"(\d+)\s*semestr", r"semestr\s*(\d+)", r"(\d+)\s*sem\b"):
        m = re.search(rx, label, re.I)
        if m:
            return int(m.group(1))
    m = re.search(r"(?:^|[_,-])s(?:em)?_?(\d+)(?=$|[_,ZL])|(\d+)sem", code, re.I)
    if m:
        return int(m.group(1) or m.group(2))
    m = re.search(r"-(\d+)R-([ZL])$", code)
    if m:
        return max(0, 2 * int(m.group(1)) - (1 if m.group(2) == "Z" else 0))
    return None


def study_level(code: str) -> str | None:
    """Cycle and mode in a course or course-group code: ``240-INF-1S-436`` -> ``1S``,
    ``ELT_2N_sem_1`` -> ``2N``."""
    m = re.search(r"(?:^|[-_])([123][SN])(?=$|[-_,])", unquote(code))
    return m.group(1) if m else None


def pool_members(pool: str, cohort_ids) -> list[str]:
    """Semester cohorts a ``pool:<level>`` stands for (``pool:all``: every one)."""
    level = pool.removeprefix(POOL)
    return [c for c in cohort_ids if level == "all" or study_level(c) == level]


def programme_stem(code: str) -> str | None:
    """The programme letters of a course-group code: ``240-INF-1S-4R-Z`` and
    ``240_INF-1S,7sem,po`` -> ``INF``; ``GNR_1S-s1_ALL`` -> ``GNR``."""
    for t in re.split(r"[-_,.\s]+", unquote(code)):
        if re.fullmatch(r"[A-Za-z]{3,}", t) and not re.fullmatch(r"(?i)sem|all|pp|po\w*", t):
            return t.upper()
    return None


def duplicate_cohorts(
    courses: dict[str, set[str]], semester: dict[str, int | None], share: float = DUP_SHARE
) -> dict[str, str]:
    """Course groups that are the same students under another code -> the group they merge
    into. USOS often lists one year twice (``GNR_1S-s1_ALL`` and ``GNR_1S-s1_PP``) or adds
    its electives as a group (``240_INF-1S,7sem,po`` in ``240-INF-1S-4R-Z``): same semester,
    level and programme letters, at least ``DUP_MIN`` running courses, and ``share`` of the
    smaller group's courses in the larger one. Different programmes that share a joint course
    never merge (their codes differ in the programme letters)."""
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for c, cs in courses.items():
        stem = programme_stem(c)
        if stem and len(cs) >= DUP_MIN:
            buckets[(semester.get(c), study_level(c), stem)].append(c)
    out: dict[str, str] = {}
    for members in buckets.values():
        kept: list[str] = []
        for c in sorted(members, key=lambda c: (-len(courses[c]), c)):
            into = next(
                (k for k in kept if len(courses[c] & courses[k]) >= share * len(courses[c])),
                None,
            )
            if into is None:
                kept.append(c)
            else:
                out[c] = into
    return out


def cohort_id(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", unquote(code)).strip("_") or "cohort"


def programme_of(cid: str) -> str:
    p = re.sub(r"(?i)[-_]*(\d+R-[ZL]|s(em)?_?\d+.*|\d+sem.*)$", "", cid)
    return p or cid


# --- build -------------------------------------------------------------------------------


@dataclass
class UsosTables:
    timetable: pd.DataFrame
    groups: pd.DataFrame
    cohorts: pd.DataFrame
    group_cohorts: pd.DataFrame
    rooms: pd.DataFrame
    report: dict = field(default_factory=dict)

    def write(self, out_dir) -> None:
        from pathlib import Path

        out = Path(out_dir)
        TIMETABLE.write(self.timetable, out / TIMETABLE.path)
        GROUPS.write(self.groups, out / GROUPS.path)
        COHORTS.write(self.cohorts, out / COHORTS.path)
        GROUP_COHORTS.write(self.group_cohorts, out / GROUP_COHORTS.path)
        ROOMS.write(self.rooms, out / ROOMS.path)


def group_ids(crawl: Crawl) -> dict[tuple[int, int], str]:
    """(unit id, group number) -> ``<course>:<class type>:<nr>`` (``@<unit>`` on a clash)."""
    out: dict[tuple[int, int], str] = {}
    used: set[str] = set()
    for uid, unit in sorted(crawl.units.items()):
        if not unit.course_code:
            continue
        for g in unit.groups:
            gid = f"{unit.course_code}:{unit.class_type or '?'}:{g.group_nr}"
            if gid in used:
                gid = f"{gid}@{uid}"
            used.add(gid)
            out[(uid, g.group_nr)] = gid
    return out


def rooms_table(crawl: Crawl, resolve, room_map: pd.DataFrame | None) -> pd.DataFrame:
    r = crawl.rooms.copy()
    r["building_id"] = r["building_usos_id"].map(resolve)
    r["room_id"] = r["number"].map(room_key)
    if room_map is not None and len(room_map):
        fix = room_map.set_index("usos_room")
        key = r["building_usos_id"].fillna("") + "/" + r["number"].fillna("")
        hit = key.isin(fix.index)
        r.loc[hit, "building_id"] = key[hit].map(fix["building_id"])
        r.loc[hit, "room_id"] = key[hit].map(fix["room_id"])
    ok = r["building_id"].fillna("").str.match(BUILDING_ID_PATTERN)
    r.loc[~ok, ["building_id", "room_id"]] = None
    r = r.drop_duplicates("room_usos_id")
    return r[ROOMS.column_names].reset_index(drop=True)


def build_tables(
    crawl: Crawl,
    known_buildings: set[str],
    aliases: dict[str, str],
    room_map: pd.DataFrame | None = None,
) -> UsosTables:
    resolve = building_resolver(known_buildings, aliases)
    rooms = rooms_table(crawl, resolve, room_map)
    ids = rooms["room_usos_id"]
    room_building = dict(zip(ids, rooms["building_id"], strict=True))
    room_id = dict(zip(ids, rooms["room_id"], strict=True))
    room_seats = dict(zip(ids, rooms["capacity"], strict=True))
    report: Counter = Counter()

    tiles: dict[tuple[int, int], list[Tile]] = defaultdict(list)
    for t in crawl.tiles:
        tiles[(t.unit_id, t.group_nr)].append(t)

    # --- groups and their meetings
    group_rows, slot_rows = [], []
    gids = group_ids(crawl)
    for uid, unit in sorted(crawl.units.items()):
        code = unit.course_code
        if not code:
            report["units without a course code"] += 1
            continue
        ctype = unit.class_type or "?"
        for g in unit.groups:
            gid = gids[(uid, g.group_nr)]
            caps = []
            n_slots = 0
            for m in g.meetings:
                rows = _slots(m, tiles.get((uid, g.group_nr), []), report)
                for weekday, start, end, parity, rid in rows:
                    b = room_building.get(rid)
                    if pd.notna(room_seats.get(rid, pd.NA)):
                        caps.append(int(room_seats[rid]))
                    if b is None or pd.isna(b):
                        report["meetings outside the modelled campus"] += 1
                        continue
                    room = room_id.get(rid)
                    slot_rows.append(
                        (gid, weekday, start, end, parity, b, None if pd.isna(room) else room)
                    )
                    n_slots += 1
            group_rows.append(
                {
                    "group_id": gid,
                    "unit_id": uid,
                    "course_id": code,
                    "course_name": unit.course_name,
                    "class_type": ctype,
                    "enrolled": g.enrolled,
                    "limit": g.limit if g.limit is not None else unit.unit_limit,
                    "room_capacity": min(caps) if caps else None,
                    "n_slots": n_slots,
                }
            )
    groups = pd.DataFrame(group_rows)
    if groups.empty:
        raise ValueError("no class groups in the crawl (no room plans / empty week?)")
    _sizes(groups)

    timetable = pd.DataFrame(
        slot_rows,
        columns=["group_id", "weekday", "start", "end", "week_parity", "building_id", "room_id"],
    ).drop_duplicates()
    timetable = timetable.sort_values(["group_id", "weekday", "start"]).reset_index(drop=True)
    timetable.insert(0, "activity_id", [f"a{i:06d}" for i in range(len(timetable))])

    # groups that never meet on campus carry no demand; a group with dated campus meetings
    # only ("wielokrotnie") stays, the calendar week of the demand stage uses those dates
    dated = set()
    m = crawl.meetings
    if m is not None and len(m):
        rid = m["room_id"].map(lambda r: None if pd.isna(r) else str(int(r)))
        here = rid.map(room_building).notna()
        dated = {
            gids.get((int(u), int(g)))
            for u, g in zip(m.loc[here, "unit_id"], m.loc[here, "group_number"], strict=True)
            if pd.notna(u) and pd.notna(g)
        }
    on_campus = groups["group_id"].isin(timetable["group_id"]) | groups["group_id"].isin(dated)
    report["groups never meeting on campus"] += int((~on_campus).sum())
    groups = groups[on_campus].reset_index(drop=True)

    cohorts, group_cohorts = _cohorts(crawl, groups, report)
    out_groups = groups[GROUPS.column_names].copy()
    for c in ("size", "enrolled", "limit", "room_capacity"):
        out_groups[c] = out_groups[c].astype("Int64")
    for df, table in ((timetable, TIMETABLE), (out_groups, GROUPS)):
        table.validate(df)
    log.info(
        "USOS: %d groups (%s), %d weekly slots, %d cohorts",
        len(out_groups), dict(Counter(out_groups["size_source"])), len(timetable), len(cohorts),
    )  # fmt: skip
    for k, v in sorted(report.items()):
        log.info("  %s: %d", k, v)
    return UsosTables(timetable, out_groups, cohorts, group_cohorts, rooms, dict(report))


def _slots(meeting, tiles: list[Tile], report: Counter) -> list[tuple]:
    """(weekday, start, end, parity, room_usos_id) of one meeting line in a teaching week."""
    if meeting.parity is None:
        # "wielokrotnie": several dates; keep it if the crawled week shows it
        found = [
            (t.weekday, t.start, t.end, "all", t.room_usos_id)
            for t in tiles
            if t.weekday <= 5 and (meeting.start is None or t.start == meeting.start)
        ]
        report[
            "irregular meetings kept from the crawled week"
            if found
            else "irregular meetings dropped"
        ] += 1  # noqa: E501
        return found
    if meeting.weekday is None or meeting.start is None or meeting.end is None:
        report["meetings without a day or time"] += 1
        return []
    if meeting.weekday > 5:
        report["weekend meetings dropped"] += 1
        return []
    return [(meeting.weekday, meeting.start, meeting.end, meeting.parity, meeting.room_usos_id)]


def _sizes(groups: pd.DataFrame) -> None:
    """``size`` and ``size_source`` in place (see the module docstring)."""
    size = pd.Series(np.nan, index=groups.index)
    source = pd.Series("estimate", index=groups.index, dtype=object)
    enrolled = pd.to_numeric(groups["enrolled"], errors="coerce")
    limit = pd.to_numeric(groups["limit"], errors="coerce")
    cap = pd.to_numeric(groups["room_capacity"], errors="coerce")
    has = enrolled > 0
    size[has], source[has] = enrolled[has], "usos"
    use = size.isna() & (limit > 0)
    size[use] = limit[use]
    use = size.isna() & (cap > 0)
    size[use], source[use] = np.ceil(cap[use] * ROOM_FILL), "room_capacity"
    med = size.groupby(groups["class_type"]).transform("median")
    use = size.isna()
    size[use] = med[use].fillna(size.median() if size.notna().any() else 15)
    groups["size"] = size.clip(lower=1).round().astype(int)
    groups["size_source"] = source


def _cohorts(crawl: Crawl, groups: pd.DataFrame, report: Counter):
    """COHORTS and GROUP_COHORTS (see the module docstring)."""
    course_cohorts: dict[str, set[str]] = defaultdict(set)
    semester: dict[str, int | None] = {}
    for code, page in crawl.courses.items():
        for g in page.groups:
            sem = semester_of(g)
            if sem is None:
                continue  # elective pools, "grupa pościgowa", international catalogue
            cid = cohort_id(g.code)
            semester[cid] = sem
            course_cohorts[code].add(cid)
    active = set(groups["course_id"])
    merged = duplicate_cohorts(
        {c: {k for k, cs in course_cohorts.items() if c in cs and k in active} for c in semester},
        semester,
    )
    if merged:
        report["duplicate course groups merged"] += len(merged)
        for code in course_cohorts:
            course_cohorts[code] = {merged.get(c, c) for c in course_cohorts[code]}
        for c in merged:
            semester.pop(c, None)
    # specialisations attend the parent's courses
    parents = {
        c: p
        for c in semester
        for p in semester
        if c != p and semester[c] == semester[p] and re.match(re.escape(p) + r"[_-]", c)
    }
    for cs in course_cohorts.values():
        for c, p in parents.items():
            if p in cs:
                cs.add(c)

    totals = groups.groupby(["course_id", "unit_id"])["size"].sum().groupby("course_id").max()
    pools: dict[str, str] = {}
    levels = {c: study_level(c) for c in semester}
    for code in totals.index:
        if not course_cohorts.get(code):
            # languages, PE, humanities: taken by students of every programme of that level
            level = study_level(code)
            pools[code] = POOL + (level if level and level in levels.values() else "all")
            report["courses in no cohort (pooled)"] += 1
    per_cohort: dict[str, list[float]] = defaultdict(list)
    for code, total in totals.items():
        cs = course_cohorts.get(code, ())
        for c in cs:
            per_cohort[c].append(total / len(cs))
    src = groups.groupby("course_id")["size_source"].agg(lambda s: (s == "usos").mean())
    cohort_rows = []
    for c, vals in sorted(per_cohort.items()):
        own = [code for code, cs in course_cohorts.items() if c in cs and code in src.index]
        cohort_rows.append(
            {
                "cohort_id": c,
                "programme": programme_of(c),
                "semester": semester[c],
                "n_students": max(1, round(float(np.quantile(vals, COHORT_QUANTILE)))),
                "size_source": "usos" if own and src[own].mean() >= 0.5 else "estimate",
            }
        )
    cohorts = pd.DataFrame(cohort_rows, columns=COHORTS.column_names)
    cohorts["semester"] = cohorts["semester"].astype("Int64")
    gc = [
        (gid, c)
        for gid, code in zip(groups["group_id"], groups["course_id"], strict=True)
        for c in (sorted(course_cohorts[code]) if code in course_cohorts else [pools[code]])
        if c in per_cohort or c.startswith(POOL)
    ]
    group_cohorts = pd.DataFrame(gc, columns=GROUP_COHORTS.column_names).drop_duplicates()
    COHORTS.validate(cohorts)
    GROUP_COHORTS.validate(group_cohorts)
    return cohorts, group_cohorts

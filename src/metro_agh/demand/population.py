"""Synthetic students from the USOS tables (docs/data_contracts.md, sections 5.1-5.2).

Nobody's real timetable is known, only the groups and how many students each has. The
population reproduces those counts:

- **Students.** Each cohort gets ``n_students`` students (scaled when
  ``population.n_students`` is a number, not ``auto``). A share of them live in a dorm,
  chosen in proportion to its beds (``population/dorms.csv``), the rest arrive at a stop,
  chosen in proportion to the stop ``weight`` in campus.yaml.
- **Who takes a course.** A course of a pool (``pool:1S``: languages, PE) is shared by every
  cohort of that level. A course shared by cohorts S with ``total`` registered students
  (largest class type) is taken by each student of S with probability
  ``min(1, total / sum of n_students over S)``: 1 for a compulsory course, less for an
  elective, so the expected attendance equals the USOS count.
- **Which group.** Each student draws one number q in [0, 1), the place in the year's list
  (a dean's group): within every class type with several groups the student goes to the
  group where q falls on the cumulative group sizes. Students who share a lab group thus
  also share their other groups, as in a real dean's group, and group sizes hold. If that
  group collides with a class already taken, the nearest group that fits is used instead.
- **Order.** Compulsory classes first, those with one group (they cannot move) before the
  ones with a choice; then electives and pool courses (languages, PE), each taken whole in
  groups that fit or not at all. A seat freed that way goes to the next student of the same
  cohorts who fits it, so the elective's USOS count still holds.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..schemas.tables import ENROLLMENTS, STUDENTS
from ..simulation.schedule import hhmm
from ..usos.parse import POOL, pool_members

log = logging.getLogger(__name__)

DAY_S = 24 * 3600


@dataclass
class Homes:
    dorms: list[str]
    dorm_beds: np.ndarray
    stops: list[str]
    stop_weights: np.ndarray


def modelled_slots(timetable: pd.DataFrame, parity: str) -> pd.DataFrame:
    """Slots of the modelled week: ``week_parity`` is ``all`` or ``parity``; times in week
    seconds (``start_wt``, ``end_wt``)."""
    t = timetable[timetable["week_parity"].isin(["all", parity])].copy()
    base = (t["weekday"].astype(int) - 1) * DAY_S
    t["start_wt"] = base + t["start"].map(hhmm)
    t["end_wt"] = base + t["end"].map(hhmm)
    return t.reset_index(drop=True)


def busiest_week(meetings: pd.DataFrame) -> dt.date:
    """Monday of the week with the most weekday meetings (a full teaching week)."""
    d = pd.to_datetime(meetings["date"])
    d = d[d.dt.weekday < 5]
    monday = (d - pd.to_timedelta(d.dt.weekday, unit="D")).dt.date
    return monday.value_counts().idxmax()


def calendar_slots(
    meetings: pd.DataFrame, rooms: pd.DataFrame, monday: dt.date | None = None
) -> tuple[pd.DataFrame, dt.date]:
    """Slots of a real calendar week, from the dated meetings (``tables.MEETINGS``): every
    meeting on Monday..Friday of the week starting ``monday`` (default: ``busiest_week``) in
    a building of the campus model. Same columns as ``modelled_slots``; holidays, moved and
    one-off classes are as USOS has them, so there is no week parity to choose."""
    monday = monday or busiest_week(meetings)
    days = {(monday + dt.timedelta(days=i)).isoformat(): i + 1 for i in range(5)}
    m = meetings[meetings["date"].isin(days) & meetings["building_id"].notna()]
    m = m[m["group_id"].notna()]
    room = dict(zip(rooms["room_usos_id"], rooms["room_id"], strict=True))
    t = pd.DataFrame(
        {
            "group_id": m["group_id"].to_numpy(),
            "weekday": m["date"].map(days).to_numpy(),
            "start": m["start"].to_numpy(),
            "end": m["end"].to_numpy(),
            "week_parity": "all",
            "building_id": m["building_id"].to_numpy(),
            "room_id": m["room_usos_id"].map(room).to_numpy(),
        }
    ).drop_duplicates(["group_id", "weekday", "start"])
    base = (t["weekday"].astype(int) - 1) * DAY_S
    t["start_wt"] = base + t["start"].map(hhmm)
    t["end_wt"] = base + t["end"].map(hhmm)
    t = t[t["end_wt"] > t["start_wt"]]
    return t.sort_values(["group_id", "start_wt"]).reset_index(drop=True), monday


def _group_nr(group_id: str) -> int:
    m = re.search(r":(\d+)(?:@\d+)?$", group_id)
    return int(m.group(1)) if m else 0


def _scaled_sizes(cohorts: pd.DataFrame, cfg: dict) -> tuple[pd.Series, float]:
    want = cfg["population"].get("n_students", "auto")
    n = cohorts.set_index("cohort_id")["n_students"].astype(float)
    scale = 1.0 if want in (None, "auto") else float(want) / n.sum()
    return (n * scale).round().clip(lower=1).astype(int), scale


def synthesize(
    cohorts: pd.DataFrame,
    group_cohorts: pd.DataFrame,
    groups: pd.DataFrame,
    slots: pd.DataFrame,
    homes: Homes,
    cfg: dict,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """``tables.STUDENTS``, ``tables.ENROLLMENTS`` and a report."""
    sizes, scale = _scaled_sizes(cohorts, cfg)
    n_total = int(sizes.sum())
    report: Counter = Counter()

    # --- homes
    share = cfg["population"].get("dorm_share", "auto")
    beds = float(homes.dorm_beds.sum())
    if share in (None, "auto"):
        share = min(1.0, beds / n_total) if n_total else 0.0
    share = float(share) if homes.dorms else 0.0
    if not homes.stops:
        share = 1.0 if homes.dorms else 0.0
    if not homes.dorms and not homes.stops:
        raise ValueError("no dorms and no stops: students have nowhere to live")

    cohort_of = np.repeat(sizes.index.to_numpy(), sizes.to_numpy())
    in_dorm = rng.random(n_total) < share
    home = np.empty(n_total, dtype=object)
    if homes.dorms:
        p = homes.dorm_beds / homes.dorm_beds.sum()
        home[in_dorm] = np.asarray(homes.dorms, object)[rng.choice(len(p), in_dorm.sum(), p=p)]
    if homes.stops:
        p = homes.stop_weights / homes.stop_weights.sum()
        n_out = int((~in_dorm).sum())
        home[~in_dorm] = np.asarray(homes.stops, object)[rng.choice(len(p), n_out, p=p)]
    students = pd.DataFrame(
        {
            "student_id": np.arange(n_total),
            "cohort_id": cohort_of,
            "home_kind": np.where(in_dorm, "dorm", "stop"),
            "home_key": home,
        }
    )
    STUDENTS.validate(students)

    # --- courses: class types -> groups (by number), with their slots
    g = groups.assign(nr=groups["group_id"].map(_group_nr)).sort_values(
        ["course_id", "class_type", "nr"]
    )
    busy_of: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for gid, s, e in zip(slots["group_id"], slots["start_wt"], slots["end_wt"], strict=True):
        busy_of[gid].append((int(s), int(e)))
    g = g[g["group_id"].isin(busy_of)]  # groups that meet in the modelled week
    types: dict[str, list[tuple[list[str], np.ndarray]]] = defaultdict(list)
    total: dict[str, float] = {}
    for (course, _), sub in g.groupby(["course_id", "class_type"], sort=False):
        size = sub["size"].to_numpy(float) * scale
        types[course].append((sub["group_id"].tolist(), np.cumsum(size) / size.sum()))
        total[course] = max(total.get(course, 0.0), float(size.sum()))
    for course in types:  # single-group types (lectures) first: they cannot move
        types[course].sort(key=lambda t: len(t[0]))

    gc = group_cohorts.merge(groups[["group_id", "course_id"]], on="group_id")
    known = list(sizes.index)

    def expand(ids) -> list[str]:
        out: set[str] = set()
        for c in ids:
            out.update(pool_members(c, known) if c.startswith(POOL) else [c])
        return sorted(out)

    course_cohorts = gc.groupby("course_id")["cohort_id"].agg(expand)
    p_take = {
        c: min(1.0, total[c] / max(1, sum(int(sizes.get(k, 0)) for k in ks)))
        for c, ks in course_cohorts.items()
        if c in total
    }
    by_cohort: dict[str, list[str]] = defaultdict(list)
    for c, ks in course_cohorts.items():
        if c in total:
            for k in ks:
                by_cohort[k].append(c)

    # --- enrolment, student by student
    rows: list[tuple[int, str]] = []
    debt: Counter = Counter()  # elective seats freed by a clash, for the next student
    first = 0
    for cohort, n in sizes.items():
        ids = np.arange(first, first + n)
        first += n
        courses = sorted(by_cohort.get(cohort, []))
        if not courses:
            report["cohorts without a course meeting this week"] += 1
            continue
        take = rng.random((n, len(courses))) < np.array([p_take[c] for c in courses])
        q = rng.random(n)
        compulsory = [c for c in courses if p_take[c] >= 1.0]
        fixed_first = sorted(
            ((len(gids), j, gids, cum) for j, c in enumerate(compulsory) for gids, cum in types[c]),
            key=lambda t: (t[0], t[1]),
        )
        electives = [(j, c) for j, c in enumerate(courses) if p_take[c] < 1.0]
        for i, sid in enumerate(ids):
            busy: list[tuple[int, int]] = []
            # compulsory classes: the ones that cannot move (one group) first
            for _, _, gids, cum in fixed_first:
                gid = _pick(gids, cum, float(q[i]), busy, busy_of, report)
                rows.append((int(sid), gid))
                busy += busy_of[gid]
            # electives and pools: the whole course in groups that fit, or not at all
            for j, course in electives:
                if not take[i, j] and debt[course] <= 0:
                    continue
                picks, before = [], busy
                for gids, cum in types[course]:
                    gid = _pick(gids, cum, float(q[i]), busy, busy_of, report, strict=True)
                    if gid is None:
                        picks = None
                        break
                    picks.append(gid)
                    busy = busy + busy_of[gid]
                if picks is None:  # clashes: this student does not take it, another one will
                    busy = before
                    if take[i, j]:
                        debt[course] += 1
                        report["electives given to another student (clash)"] += 1
                    continue
                if not take[i, j]:
                    debt[course] -= 1
                rows += [(int(sid), gid) for gid in picks]
    enrollments = pd.DataFrame(rows, columns=ENROLLMENTS.column_names).drop_duplicates()
    ENROLLMENTS.validate(enrollments)

    # fit to USOS, over the groups that meet in the modelled week
    want = g.set_index("group_id")["size"] * scale
    got = enrollments["group_id"].value_counts().reindex(want.index, fill_value=0)
    if want.sum() > 0:
        course = g.set_index("group_id")["course_id"]
        per_course = pd.DataFrame({"want": want, "got": got}).groupby(course).sum()
        report["students / USOS registrations (%)"] = round(100 * got.sum() / want.sum())
        report["course size error, sum |model - USOS| / USOS (%)"] = round(
            100 * (per_course["got"] - per_course["want"]).abs().sum() / want.sum()
        )
        report["group size error, sum |model - USOS| / USOS (%)"] = round(
            100 * (got - want).abs().sum() / want.sum()
        )
    log.info(
        "population: %d students in %d cohorts (%.0f%% in dorms), %d enrolments",
        n_total, len(sizes), 100 * in_dorm.mean(), len(enrollments),
    )  # fmt: skip
    return students, enrollments, dict(report)


def _overlaps(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    return any(s1 < e2 and s2 < e1 for s1, e1 in a for s2, e2 in b)


def _pick(gids, cum, q, busy, busy_of, report: Counter, strict: bool = False) -> str | None:
    """The group where q falls, or the nearest one that does not collide with ``busy``;
    with none free: that group anyway, or None when ``strict``."""
    i0 = min(int(np.searchsorted(cum, q, side="right")), len(gids) - 1)
    if not _overlaps(busy_of[gids[i0]], busy):
        return gids[i0]
    for d in range(1, len(gids)):
        for i in (i0 + d, i0 - d):
            if 0 <= i < len(gids) and not _overlaps(busy_of[gids[i]], busy):
                report["moved to another group to avoid a clash"] += 1
                return gids[i]
    if strict:
        return None
    report["no clash-free group"] += 1
    return gids[i0]

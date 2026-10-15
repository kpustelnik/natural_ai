"""Students' weeks -> legs, OD and the building-to-building flows (sections 5.4-5.6).

Each student's classes of a day, in time order, become legs: home -> first class, class ->
class, last class -> home. Rules of section 5.4: no leg between two classes in the same room;
a break longer than ``demand.max_break_s`` sends a dorm student home and back, while a
commuter stays on campus. A class that overlaps the previous one (a clash the population
could not avoid) is skipped.

Endpoint keys are the most specific ones the walk graph has: ``D-17/1.38`` when the room is
modelled, else ``D-17``. Without a graph, buildings are used.
"""

from __future__ import annotations

import logging
from collections import Counter

import numpy as np
import pandas as pd

from ..schemas.common import endpoint_key
from ..schemas.tables import LEGS, MIGRATIONS, OD

log = logging.getLogger(__name__)


def resolve_keys(slots: pd.DataFrame, endpoints: set[str] | None) -> tuple[pd.Series, int]:
    """Endpoint key of every slot (None where the building is not in the graph)."""
    room = [
        endpoint_key(b, r) if isinstance(r, str) else b
        for b, r in zip(slots["building_id"], slots["room_id"], strict=True)
    ]
    if endpoints is None:
        return slots["building_id"].copy(), 0
    keys = [
        r if r in endpoints else (b if b in endpoints else None)
        for r, b in zip(room, slots["building_id"], strict=True)
    ]
    out = pd.Series(keys, index=slots.index, dtype=object)
    return out, int(out.isna().sum())


def build_legs(
    students: pd.DataFrame,
    enrollments: pd.DataFrame,
    slots: pd.DataFrame,
    endpoints: set[str] | None,
    cfg: dict,
) -> tuple[pd.DataFrame, dict]:
    """``tables.LEGS`` for the modelled week and a report."""
    max_break = int(cfg["demand"]["max_break_s"])
    report: Counter = Counter()
    s = slots.copy()
    s["key"], missing = resolve_keys(s, endpoints)
    if missing:
        report["slots in buildings missing from the graph"] = missing
    s = s[s["key"].notna()]

    week = enrollments.merge(s[["group_id", "weekday", "start_wt", "end_wt", "key"]], on="group_id")
    week = week.sort_values(["student_id", "start_wt", "end_wt"], kind="stable")
    home = students.set_index("student_id")
    dorm = (home["home_kind"] == "dorm").to_dict()
    home_key = home["home_key"].to_dict()

    rows: list[tuple] = []
    sid_a = week["student_id"].to_numpy()
    day_a = week["weekday"].to_numpy()
    st_a = week["start_wt"].to_numpy()
    en_a = week["end_wt"].to_numpy()
    key_a = week["key"].to_numpy()
    bounds = np.flatnonzero((np.diff(sid_a) != 0) | (np.diff(day_a) != 0)) + 1
    for lo, hi in zip(np.r_[0, bounds], np.r_[bounds, len(week)], strict=True):
        if lo == hi:
            continue
        sid, day = int(sid_a[lo]), int(day_a[lo])
        h, is_dorm = home_key[sid], dorm[sid]
        out = [("home_to_class", h, key_a[lo], None, int(st_a[lo]))]
        prev = lo
        for i in range(lo + 1, hi):
            if st_a[i] < en_a[prev]:
                report["clashing classes skipped"] += 1
                continue
            a, b = key_a[prev], key_a[i]
            if a != b:
                gap = int(st_a[i] - en_a[prev])
                if is_dorm and gap > max_break:
                    out.append(("class_to_home", a, h, int(en_a[prev]), None))
                    out.append(("home_to_class", h, b, None, int(st_a[i])))
                else:
                    out.append(("class_to_class", a, b, int(en_a[prev]), int(st_a[i])))
            prev = i
        out.append(("class_to_home", key_a[prev], h, int(en_a[prev]), None))
        rows += [(sid, day, *x) for x in out]

    legs = pd.DataFrame(
        rows,
        columns=["student_id", "weekday", "kind", "from_key", "to_key",
                 "earliest_depart_wt", "deadline_wt"],
    )  # fmt: skip
    legs = legs[legs["from_key"] != legs["to_key"]].reset_index(drop=True)
    legs.insert(0, "leg_id", np.arange(len(legs)))
    legs.insert(3, "seq", legs.groupby(["student_id", "weekday"]).cumcount())
    for c in ("earliest_depart_wt", "deadline_wt"):
        legs[c] = legs[c].astype("Int64")
    legs["break_s"] = (legs["deadline_wt"] - legs["earliest_depart_wt"]).astype("Int64")
    legs = legs[LEGS.column_names]
    LEGS.validate(legs)
    log.info("legs: %d (%s)", len(legs), dict(Counter(legs["kind"])))
    return legs, dict(report)


def od_matrix(legs: pd.DataFrame) -> pd.DataFrame:
    od = legs.groupby(["from_key", "to_key"]).size().rename("n_legs").reset_index()
    OD.validate(od)
    return od


def place_of(key: str) -> str:
    """Building (or stop) of an endpoint key: ``D-17/1.38`` -> ``D-17``."""
    return key.split("/", 1)[0]


def migrations(legs: pd.DataFrame) -> pd.DataFrame:
    """``tables.MIGRATIONS``: legs between places per weekday and departure hour. The
    departure is the end of the previous class, or the deadline for legs from home."""
    t = legs["earliest_depart_wt"].fillna(legs["deadline_wt"]).astype(int)
    df = pd.DataFrame(
        {
            "weekday": legs["weekday"],
            "hour": (t % (24 * 3600)) // 3600,
            "kind": legs["kind"],
            "from_place": legs["from_key"].map(place_of),
            "to_place": legs["to_key"].map(place_of),
            "break_s": legs["break_s"],
        }
    )
    df = df[df["from_place"] != df["to_place"]]
    out = (
        df.groupby(["weekday", "hour", "kind", "from_place", "to_place"])
        .agg(n_legs=("break_s", "size"), median_break_s=("break_s", "median"))
        .reset_index()
    )
    out["median_break_s"] = out["median_break_s"].round().astype("Int64")
    out = out.sort_values(["weekday", "hour", "n_legs"], ascending=[True, True, False])
    out = out.reset_index(drop=True)
    MIGRATIONS.validate(out)
    return out

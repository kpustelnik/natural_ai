"""Stage 3: USOS tables -> population, legs, OD and building-to-building migrations.

    uv run scripts/03_build_demand.py                     # busiest real week (meetings.csv)
    uv run scripts/03_build_demand.py --week 2026-10-26   # another calendar week (a Monday)
    uv run scripts/03_build_demand.py --typical --parity even   # typical week from timetable.csv

Reads usos/*.csv (01_fetch_usos.py), the dorms and stops of the campus, and the walk graph
(network/nodes.parquet, 02_build_campus.py) when it exists, so legs end in modelled rooms.
Writes population/dorms.csv, students.parquet, enrollments.parquet, demand/legs.parquet,
od.parquet and migrations.csv. Formats: docs/data_contracts.md, section 5.
"""

import argparse
import datetime as dt
import logging
import sys

import numpy as np
import pandas as pd
import yaml

from metro_agh.config import load_config, path
from metro_agh.demand.dorms import estimate_dorms
from metro_agh.demand.legs import build_legs, migrations, od_matrix
from metro_agh.demand.population import Homes, calendar_slots, modelled_slots, synthesize
from metro_agh.schemas.campus import Campus
from metro_agh.schemas.tables import (
    COHORTS,
    DORMS,
    ENROLLMENTS,
    GRAPH_NODES,
    GROUP_COHORTS,
    GROUPS,
    LEGS,
    MEETINGS,
    MIGRATIONS,
    OD,
    ROOMS,
    STUDENTS,
    TIMETABLE,
)

log = logging.getLogger("03_build_demand")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--week", default=None, help="Monday of the calendar week")
    parser.add_argument("--typical", action="store_true", help="typical week (timetable.csv)")
    parser.add_argument("--parity", choices=["odd", "even"], default=None, help="with --typical")
    parser.add_argument("--sample", action="store_true", help="campus from data/sample/campus")
    parser.add_argument("--config", default=None, help="experiment config overriding keys")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    out = path(cfg, "processed")
    campus_dir = path(cfg, "sample") / "campus" if args.sample else path(cfg, "campus")

    timetable = TIMETABLE.read(out / TIMETABLE.path)
    groups = GROUPS.read(out / GROUPS.path)
    cohorts = COHORTS.read(out / COHORTS.path)
    group_cohorts = GROUP_COHORTS.read(out / GROUP_COHORTS.path)

    endpoints = None
    nodes_file = out / GRAPH_NODES.path
    if nodes_file.exists():
        nodes = GRAPH_NODES.read(nodes_file)
        endpoints = set(nodes["endpoint_key"].dropna())
    else:
        log.warning("%s missing: legs end in buildings, not rooms", nodes_file)

    dorms = estimate_dorms(campus_dir, cfg)
    DORMS.write(dorms, out / DORMS.path)
    campus = Campus.model_validate(
        yaml.safe_load((campus_dir / "campus.yaml").read_text(encoding="utf-8"))
    )
    stops = [s for s in campus.stops if endpoints is None or s.id in endpoints]
    in_graph = dorms if endpoints is None else dorms[dorms["building_id"].isin(endpoints)]
    homes = Homes(
        dorms=in_graph["building_id"].tolist(),
        dorm_beds=in_graph["residents"].to_numpy(float),
        stops=[s.id for s in stops],
        stop_weights=np.array([s.weight for s in stops], float),
    )

    week_cfg = args.week or str(cfg["demand"].get("week", "auto"))
    meetings_file = out / MEETINGS.path
    if not args.typical and week_cfg != "typical" and meetings_file.exists():
        monday = None if week_cfg == "auto" else dt.date.fromisoformat(week_cfg)
        if monday is not None and monday.weekday() != 0:
            log.error("--week %s is not a Monday", monday)
            return 1
        meetings = MEETINGS.read(meetings_file)
        slots, monday = calendar_slots(meetings, ROOMS.read(out / ROOMS.path), monday)
        week = f"calendar week {monday}"
    else:
        if not args.typical and week_cfg != "typical":
            log.warning("%s missing (01_fetch_usos.py, scope all): typical week", meetings_file)
        parity = args.parity or cfg["demand"]["week_parity"]
        slots = modelled_slots(timetable, parity)
        week = f"typical {parity} week"
    log.info("%s: %d class slots", week, len(slots))
    rng = np.random.default_rng(int(cfg["seed"]))
    students, enrollments, rep_pop = synthesize(
        cohorts, group_cohorts, groups, slots, homes, cfg, rng
    )
    legs, rep_legs = build_legs(students, enrollments, slots, endpoints, cfg)
    od = od_matrix(legs)
    flows = migrations(legs)

    STUDENTS.write(students, out / STUDENTS.path)
    ENROLLMENTS.write(enrollments, out / ENROLLMENTS.path)
    LEGS.write(legs, out / LEGS.path)
    OD.write(od, out / OD.path)
    MIGRATIONS.write(flows, out / MIGRATIONS.path)
    for k, v in sorted({**rep_pop, **rep_legs}.items()):
        log.info("  %s: %s", k, v)

    between = flows[flows["kind"] == "class_to_class"]
    top = (
        between.groupby(["from_place", "to_place"])["n_legs"]
        .sum()
        .sort_values(ascending=False)
        .head(15)
    )
    with pd.option_context("display.width", 120):
        log.info("busiest moves between buildings (student-legs a week):\n%s", top.to_string())
    log.info(
        "demand (%s): %d students, %d legs, %d OD pairs, %d flows -> %s",
        week, len(students), len(legs), len(od), len(flows), out,
    )  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The report's metrics of the simulated week (README, "Metryki raportowane").

    uv run scripts/report_metrics.py              # after 05_simulate.py

Reads data/processed/demand/legs.parquet and simulation/{no_metro,metro}/legs.parquet,
writes docs/figures/simulation_metrics.csv: per scenario the student-hours per week, mean
leg, legs longer than their break, late legs, late classes (a class = weekday, room, start;
late when any student arrives after the start), metro and bus / tram shares; and the saving
of the metro in student-minutes per week and per student.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from metro_agh.config import ROOT, load_config, path
from metro_agh.schemas.common import Scenario
from metro_agh.schemas.results import BestLine, load_json
from metro_agh.schemas.tables import LEGS, SIM_LEGS
from metro_agh.simulation.metrics import scenario_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processed", default=None, help="processed dir (default: config)")
    args = parser.parse_args()
    cfg = load_config()
    processed = ROOT / args.processed if args.processed else path(cfg, "processed")
    legs = LEGS.read(processed / LEGS.path)
    rows = {}
    for sc in Scenario:
        f = processed / SIM_LEGS.path.format(scenario=sc.value)
        if f.exists():
            rows[sc.value] = scenario_metrics(SIM_LEGS.read(f), legs)
    if not rows:
        print(f"no {processed}/simulation/*/legs.parquet: run 05_simulate.py", file=sys.stderr)
        return 1
    df = pd.DataFrame(rows).T.astype(float)
    df.insert(0, "student_hours", (df["total_travel_s"] / 3600).round(0))
    for c in ("late_share", "longer_than_break_share", "metro_share", "transit_share"):
        df[c] = (100 * df[c].astype(float)).round(2)
    df = df.rename(columns={c: c.replace("_share", "_pct") for c in df.columns})
    if {"no_metro", "metro"} <= set(rows):
        saved_s = rows["no_metro"]["total_travel_s"] - rows["metro"]["total_travel_s"]
        students = legs.student_id.nunique()
        df.loc["metro", "saved_student_min_per_week"] = round(saved_s / 60, 0)
        df.loc["metro", "saved_min_per_student"] = round(saved_s / 60 / students, 1)
    line = path(cfg, "results") / "best_line.json"
    note = ""
    if line.exists():
        best: BestLine = load_json(BestLine, line)
        note = f"line {' - '.join(best.stations)} ({best.run_id})"
    out = ROOT / "docs" / "figures" / "simulation_metrics.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.rename_axis("scenario").to_csv(out, lineterminator="\n")
    print(note)
    print(df.T.to_string(float_format=lambda x: f"{x:,.2f}"))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

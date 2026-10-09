"""Stage 5: every leg of every student, without and with the metro (data_contracts.md, 9).

    uv run scripts/05_simulate.py                       # the line in results/best_line.json
    uv run scripts/05_simulate.py --line path/to/best_line.json

Reads network/*.parquet, demand/legs.parquet (data/processed) and the line; writes
simulation/metro/schedule.parquet and simulation/{no_metro,metro}/legs.parquet.
Then `06_export_web.py --sim` turns them into a replay for the viewer.
"""

import argparse
import logging
from pathlib import Path

from metro_agh.config import load_config, path
from metro_agh.simulation.simulate import run_simulation

log = logging.getLogger("05_simulate")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--line", default=None, help="best_line.json (default: results/)")
    parser.add_argument("--config", default=None, help="experiment config overriding keys")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    line = Path(args.line) if args.line else path(cfg, "results") / "best_line.json"
    sims = run_simulation(path(cfg, "processed"), line, cfg)
    for sc, df in sims.items():
        travel = (df.arrive_wt - df.depart_wt).sum() / 3600
        log.info("%s: %d legs, %.0f student-hours of travel a week", sc, len(df), travel)


if __name__ == "__main__":
    main()

"""Stage 5: every leg of every student, without and with the metro (data_contracts.md, 9).

    uv run scripts/05_simulate.py                       # the line in results/best_line.json
    uv run scripts/05_simulate.py --line path/to/best_line.json
    uv run scripts/05_simulate.py --showcase            # + the lines of showcase.yaml

Reads network/*.parquet, demand/legs.parquet (data/processed) and the line; writes
simulation/metro/schedule.parquet and simulation/{no_metro,metro}/legs.parquet.
--showcase simulates only the best lines of the runs listed under `simulate:` in
experiments/configs/showcase.yaml, each into data/processed/showcase/<run_id>/ (~15 s a line,
not committed). Then `06_export_web.py --sim` (or `--showcase`) turns them into replays.
"""

import argparse
import logging
from pathlib import Path

import yaml

from metro_agh.config import ROOT, load_config, path
from metro_agh.schemas.results import RunMeta, load_json
from metro_agh.simulation.simulate import run_simulation

log = logging.getLogger("05_simulate")
SHOWCASE = ROOT / "experiments" / "configs" / "showcase.yaml"


def showcase_runs() -> list[str]:
    """Run ids under `simulate:` in experiments/configs/showcase.yaml."""
    raw = yaml.safe_load(SHOWCASE.read_text(encoding="utf-8")) or {}
    return [str(r) for r in raw.get("simulate") or []]


def simulate_showcase(cfg: dict) -> None:
    processed, results = path(cfg, "processed"), path(cfg, "results")
    for run_id in showcase_runs():
        run = results / run_id / "run.json"
        if not run.exists():
            log.error("%s missing: run its experiment first", run)
            continue
        out = processed / "showcase" / run_id
        out.mkdir(parents=True, exist_ok=True)
        line = out / "best_line.json"
        line.write_text(load_json(RunMeta, run).best.model_dump_json(indent=2), encoding="utf-8")
        report(run_simulation(processed, line, cfg, out=out), run_id)


def report(sims: dict, label: str) -> None:
    for sc, df in sims.items():
        travel = (df.arrive_wt - df.depart_wt).sum() / 3600
        log.info("%s %s: %d legs, %.0f student-hours of travel a week", label, sc, len(df), travel)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--line", default=None, help="best_line.json (default: results/)")
    parser.add_argument(
        "--showcase", action="store_true", help="the lines of showcase.yaml, not best_line.json"
    )
    parser.add_argument("--config", default=None, help="YAML of config.yaml keys merged over it")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    if args.showcase:
        simulate_showcase(cfg)
        return
    line = Path(args.line) if args.line else path(cfg, "results") / "best_line.json"
    report(run_simulation(path(cfg, "processed"), line, cfg), line.stem)


if __name__ == "__main__":
    main()

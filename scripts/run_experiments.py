"""Run a parameter sweep / ablation over ``config.yaml``.

    uv run scripts/run_experiments.py --config experiments/configs/aco_ablation.yaml
    uv run scripts/run_experiments.py --config experiments/configs/aco_ablation.yaml --dry-run
    uv run scripts/run_experiments.py \\
        --config experiments/configs/aco_grid.yaml --processed data/processed/fake

Each job writes ``experiments/results/<run_id>/`` (run.json, convergence.csv, optional
trace.npz) and appends a row to ``experiments/results/runs.csv``. A per-experiment
``summary_<name>.csv`` compares mean objective by variant tag vs ``base``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from metro_agh.config import ROOT, load_config, path
from metro_agh.experiments import (
    apply_overrides,
    execute_job,
    expand_jobs,
    load_experiment,
    resolve_instance,
    summarise,
)

log = logging.getLogger("run_experiments")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--config",
        required=True,
        help="experiment YAML under experiments/configs/ (overrides + sweep)",
    )
    parser.add_argument(
        "--processed",
        default=None,
        help="processed dir with network/ + demand/ (overrides experiment.processed)",
    )
    parser.add_argument(
        "--rebuild-instance",
        action="store_true",
        help="rebuild instance.npz before the sweep",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the expanded jobs and exit",
    )
    parser.add_argument("--limit", type=int, default=None, help="run only the first N jobs")
    parser.add_argument(
        "--update-best",
        action="store_true",
        help="write best_line.json after each run (default: leave it alone)",
    )
    parser.add_argument(
        "--save-trace",
        action="store_true",
        help="force saving trace.npz (overrides experiment.save_trace)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    spec_path = Path(args.config)
    if not spec_path.is_absolute():
        spec_path = ROOT / spec_path
    spec = load_experiment(spec_path)
    base_cfg = load_config()
    baseline = apply_overrides(base_cfg, spec.defaults) if spec.defaults else base_cfg
    jobs = expand_jobs(spec, baseline_cfg=baseline)
    if args.limit is not None:
        jobs = jobs[: max(0, args.limit)]

    log.info(
        "experiment %s (%s): %d jobs, mode=%s%s",
        spec.name,
        spec.description or "no description",
        len(jobs),
        spec.mode,
        f", sweep keys={list(spec.sweep)}" if spec.sweep else "",
    )
    if args.dry_run:
        for j in jobs:
            log.info("  %s seed=%d overrides=%s", j.tag, j.seed, j.overrides or "{}")
        return 0

    processed = (
        Path(args.processed)
        if args.processed
        else (Path(spec.processed) if spec.processed else None)
    )
    if processed is not None and not processed.is_absolute():
        processed = ROOT / processed

    inst, inst_path = resolve_instance(baseline, processed, args.rebuild_instance)
    results_dir = path(base_cfg, "results")
    results_dir.mkdir(parents=True, exist_ok=True)
    save_trace = args.save_trace or spec.save_trace

    for i, job in enumerate(jobs, 1):
        log.info("[%d/%d] %s seed=%d %s", i, len(jobs), job.tag, job.seed, job.overrides or "")
        execute_job(
            job,
            base_cfg=base_cfg,
            defaults=spec.defaults,
            inst=inst,
            inst_path=inst_path,
            results_dir=results_dir,
            save_trace=save_trace,
            update_best_line=args.update_best,
        )

    summary = summarise(results_dir, spec.name)
    if summary is not None:
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.4g}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

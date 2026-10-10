"""Stage 4: MAX-MIN Ant System — choose a k-station metro line.

    uv run scripts/04_optimize.py
    uv run scripts/04_optimize.py --processed data/processed/fake
    uv run scripts/04_optimize.py --instance path/to/instance.npz

Reads ``instance/instance.npz`` (builds it from network + demand if missing),
writes ``experiments/results/<run_id>/`` and ``experiments/results/best_line.json``.

Does not export to the viewer; use ``06_export_web.py --aco`` / ``--metro`` later.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import numpy as np

from metro_agh.aco import run_mmas
from metro_agh.config import load_config, path, provenance
from metro_agh.network.instance import build_instance, write_instance
from metro_agh.schemas.instance import Instance
from metro_agh.schemas.results import BestLine, RunMeta
from metro_agh.schemas.tables import CONVERGENCE

log = logging.getLogger("04_optimize")
GENERATOR = "04_optimize.py"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--processed",
        default=None,
        help="processed dir with network/ and demand/ (default: paths.processed)",
    )
    parser.add_argument(
        "--instance",
        default=None,
        help="instance.npz to use (default: <processed>/instance/instance.npz)",
    )
    parser.add_argument(
        "--rebuild-instance",
        action="store_true",
        help="rebuild instance.npz from network + demand even if it exists",
    )
    parser.add_argument("--seed", type=int, default=None, help="override config seed")
    parser.add_argument("--config", default=None, help="experiment config overriding keys")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    if args.seed is not None:
        cfg = {**cfg, "seed": args.seed}

    processed = Path(args.processed) if args.processed else path(cfg, "processed")
    inst_path = Path(args.instance) if args.instance else processed / "instance" / "instance.npz"

    if args.rebuild_instance or not inst_path.exists():
        name = "fake" if processed.name == "fake" else "campus"
        inst = build_instance(processed, cfg, name=name)
        write_instance(inst, inst_path)
    else:
        inst = Instance.load(inst_path)
        log.info("loaded %s (%d candidates, k=%d)", inst_path, inst.n_candidates, inst.meta.k)

    t0 = time.perf_counter()
    result = run_mmas(inst, cfg, rng=np.random.default_rng(int(cfg["seed"])))
    wall = time.perf_counter() - t0

    stations = [str(inst.candidate_ids[i]) for i in result.best_line]
    run_id = f"{result.params['variant']}-k{inst.meta.k}-s{cfg['seed']}"
    results_dir = path(cfg, "results")
    run_dir = results_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    prov = provenance(GENERATOR, cfg)
    best = BestLine(
        provenance=prov,
        run_id=run_id,
        topology=inst.meta.topology,
        stations=stations,
        objective_s=round(result.best_cost, 1),
        baseline_s=round(result.objective.baseline, 1),
    )
    meta = RunMeta(
        provenance=prov,
        run_id=run_id,
        experiment="default",
        algorithm="mmas",
        instance=str(inst_path.as_posix()),
        instance_hash=inst.meta.source_hash or "",
        seed=int(cfg["seed"]),
        params=result.params,
        eval_budget=int(result.params["n_ants"]) * int(result.params["n_iterations"]),
        evaluations=max(1, result.objective.evaluations),
        wall_time_s=round(wall, 2),
        best=best,
    )
    (run_dir / "run.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    CONVERGENCE.write(result.convergence, run_dir / "convergence.csv")
    result.trace.save(run_dir / "trace.npz")
    (results_dir / "best_line.json").write_text(best.model_dump_json(indent=2), encoding="utf-8")

    saving = 100 * (1 - result.best_cost / result.objective.baseline)
    log.info(
        "done %s: %s, objective %.1f (%.1f%% below no metro), %d evals, %.1f s",
        run_id,
        "-".join(stations),
        result.best_cost,
        saving,
        result.objective.evaluations,
        wall,
    )
    log.info("wrote %s and %s", run_dir, results_dir / "best_line.json")


if __name__ == "__main__":
    main()

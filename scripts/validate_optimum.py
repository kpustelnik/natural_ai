"""Validation tests 1 and 6: gap to the exact optimum on small instances, and the bounds.

    uv run scripts/validate_optimum.py                   # 5 sub-instances, 12 candidates, k = 4
    uv run scripts/validate_optimum.py --n 14 --k 4 --budget 300 --seeds 20

The campus has too many lines for brute force (about 2·10^8 at k = 5), so this draws
sub-instances: ``--n`` candidates from the ``--pool`` with the most demand nearby (the
colonies' heuristic), the same OD pairs. On each, brute force gives the optimum, and every
algorithm gets ``--budget`` distinct lines (a few % of all lines) and ``--seeds`` seeds.

Writes docs/figures/gap_to_optimum.png and .csv: per variant the runs, how many found the
optimum, and the gap = share of the optimal saving it missed (0 = optimum). Also prints,
per sub-instance, the bounds of test 6: no metro >= optimum >= teleport bound.
"""

from __future__ import annotations

import argparse
import logging
import sys

import numpy as np
import pandas as pd

from metro_agh import figures as fg
from metro_agh.aco.common import heuristic
from metro_agh.aco.objective import teleport_bound
from metro_agh.config import ROOT, load_config, path
from metro_agh.experiments import resolve_instance
from metro_agh.network.instance import with_config
from metro_agh.optimize import run_algorithm

VARIANTS = [(a, ls) for ls in (True, False) for a in ("mmas", "acs", "random", "greedy")]
NAMES = {"mmas": "MMAS", "acs": "ACS", "random": "random", "greedy": "greedy"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subsets", type=int, default=5, help="sub-instances")
    parser.add_argument("--n", type=int, default=12, help="candidates per sub-instance")
    parser.add_argument("--k", type=int, default=4, help="stations")
    parser.add_argument("--pool", type=int, default=30, help="draw from the N best by demand")
    parser.add_argument("--budget", type=int, default=200, help="distinct lines per run")
    parser.add_argument("--seeds", type=int, default=10, help="seeds per algorithm")
    parser.add_argument("--processed", default=None, help="processed dir (default: config)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    cfg = load_config()
    cfg = {**cfg, "metro": {**cfg["metro"], "n_stations": args.k}}
    full, _ = resolve_instance(cfg, path(cfg, "processed") if not args.processed else
                               ROOT / args.processed, rebuild=False)  # fmt: skip
    full = with_config(full, cfg)
    demand, _ = heuristic(full)
    pool = np.argsort(-demand)[: args.pool]

    rows, bounds = [], []
    for sub in range(args.subsets):
        keep = sorted(np.random.default_rng(sub).choice(pool, args.n, replace=False).tolist())
        inst = full.subset(keep)
        exact = run_algorithm(inst, {**cfg, "optimize": {"algorithm": "brute_force"}})
        opt, base = exact.best_cost, exact.objective.baseline
        bound = teleport_bound(inst)
        bounds.append({"subset": sub, "candidates": "|".join(map(str, inst.candidate_ids)),
                       "lines": exact.params["n_lines"], "no_metro_s": round(base, 1),
                       "optimum_s": round(opt, 1), "teleport_bound_s": round(bound, 1),
                       "optimal_saving": round(100 * (1 - opt / base), 2)})  # fmt: skip
        assert base + 1e-6 >= opt >= bound - 1e-6, "bounds violated"
        for alg, ls in VARIANTS:
            seeds = [0] if alg == "greedy" else range(args.seeds)  # greedy: one result
            for seed in seeds:
                c = {**cfg, "optimize": {"algorithm": alg, "local_search": ls,
                                         "max_evaluations": args.budget},
                     "aco": {**cfg["aco"], "n_ants": 10, "n_iterations": 1000}}  # fmt: skip
                r = run_algorithm(inst, c, np.random.default_rng(seed))
                gap = 100 * (r.best_cost - opt) / (base - opt) if base > opt else 0.0
                rows.append({"variant": NAMES[alg] + (" + LS" if ls else ""), "subset": sub,
                             "seed": seed, "gap": max(0.0, gap),
                             "optimal": r.best_cost <= opt + 1e-6,
                             "evaluations": r.objective.evaluations})  # fmt: skip
        print(
            f"sub-instance {sub}: {bounds[-1]['lines']} lines, optimum saves "
            f"{bounds[-1]['optimal_saving']}%",
            flush=True,
        )

    df = pd.DataFrame(rows)
    order = list(dict.fromkeys(df["variant"]))
    table = df.groupby("variant", sort=False).agg(
        runs=("gap", "size"), optimal=("optimal", "sum"), mean_gap=("gap", "mean"),
        max_gap=("gap", "max"), evaluations=("evaluations", "mean"),
    ).loc[order].round(2).reset_index()  # fmt: skip
    table["optimal_share"] = (100 * table["optimal"] / table["runs"]).round(1)

    figures = ROOT / "docs" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    fig, (ax,) = fg.axes(width=9.5)
    groups = [(v, df.loc[df.variant == v, "gap"].to_numpy()) for v in order]
    texts = [f"{s:.0f}% opt." for s in table["optimal_share"]]
    fg.dots(ax, groups, texts)
    ax.set_ylim(bottom=-1)
    fg.finish(ax, "Gap to the exact optimum", ylabel="optimal saving missed (%)")
    fg.save(fig, figures / "gap_to_optimum.png",
            f"{args.subsets} sub-instances of {args.n} candidates, k = {args.k}; "
            f"{args.budget} lines per run (~{100 * args.budget / bounds[0]['lines']:.0f}% of "
            f"all), {args.seeds} seeds; label = runs that found the optimum")  # fmt: skip
    table.to_csv(figures / "gap_to_optimum.csv", index=False, lineterminator="\n")
    pd.DataFrame(bounds).to_csv(figures / "bounds.csv", index=False, lineterminator="\n")
    print(table.to_string(index=False))
    print(pd.DataFrame(bounds).drop(columns="candidates").to_string(index=False))
    print(f"wrote {figures / 'gap_to_optimum'}.png / .csv and bounds.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())

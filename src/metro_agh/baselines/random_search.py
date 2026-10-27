"""Random search: as many random k-station lines as the ants build (``aco.n_ants`` per
iteration for ``aco.n_iterations``, or until ``optimize.max_evaluations``), the best one
wins. The floor any colony must beat at the same evaluation budget."""

from __future__ import annotations

import logging
import math

import numpy as np

from ..aco.common import (
    RunResult,
    check_k,
    convergence_frame,
    max_evaluations,
    uses_local_search,
)
from ..aco.local_search import improve
from ..aco.objective import Objective
from ..schemas.instance import Instance

log = logging.getLogger(__name__)


def run_random(inst: Instance, cfg: dict, rng: np.random.Generator | None = None) -> RunResult:
    aco = cfg["aco"]
    if rng is None:
        rng = np.random.default_rng(int(cfg.get("seed", 42)))
    n, k = check_k(inst)
    n_lines, n_iter = int(aco["n_ants"]), int(aco["n_iterations"])
    budget = max_evaluations(cfg)
    f = Objective(inst, budget)
    best: list[int] = []
    best_cost = math.inf
    local_search = uses_local_search(cfg)
    rows = []
    for it in range(n_iter):
        if f.spent:
            break
        lines = [[int(i) for i in rng.choice(n, k, replace=False)] for _ in range(n_lines)]
        costs = [f(line) for line in lines]
        ib = int(np.argmin(costs))
        if local_search:  # multi-start local search: polish the iteration best
            lines[ib], costs[ib] = improve(f, lines[ib], costs[ib], n)
        if costs[ib] < best_cost:
            best, best_cost = lines[ib], costs[ib]
        rows.append((it, f.evaluations, best_cost, costs[ib], float(np.mean(costs))))
    log.info(
        "random search: %d lines, best %.3e (%.1f%% below no metro)",
        n_lines * n_iter, best_cost, 100 * (1 - best_cost / f.baseline),
    )  # fmt: skip
    return RunResult(
        algorithm="random",
        best_line=best,
        best_cost=float(best_cost),
        objective=f,
        convergence=convergence_frame(rows),
        trace=None,
        params={
            "n_ants": n_lines,
            "n_iterations": n_iter,
            "k": k,
            "topology": inst.meta.topology,
            "n_candidates": n,
            "local_search": local_search,
        },
        eval_budget=budget or n_lines * n_iter,
    )

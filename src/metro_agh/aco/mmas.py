"""MAX-MIN Ant System for an ordered k-station metro line.

Parameters come from ``config.yaml`` → ``aco`` (and ``Instance.meta.k`` / topology).
"""

from __future__ import annotations

import logging
import math

import numpy as np

from ..schemas.instance import Instance
from .common import (
    RunResult,
    TraceSampler,
    check_k,
    convergence_frame,
    entropy,
    heuristic,
    max_evaluations,
    pick,
    uses_local_search,
)
from .local_search import improve
from .objective import Objective

log = logging.getLogger(__name__)


def run_mmas(inst: Instance, cfg: dict, rng: np.random.Generator | None = None) -> RunResult:
    """Run MMAS for ``aco.n_iterations`` with ``aco.n_ants`` ants per iteration."""
    aco = cfg["aco"]
    if rng is None:
        rng = np.random.default_rng(int(cfg.get("seed", 42)))

    n, k = check_k(inst)
    n_ants = int(aco["n_ants"])
    n_iter = int(aco["n_iterations"])
    alpha = float(aco["alpha"])
    beta = float(aco["beta"])
    rho = float(aco["rho"])
    tau_min_ratio = float(aco["tau_min_ratio"])
    local_search = uses_local_search(cfg)

    budget = max_evaluations(cfg)
    f = Objective(inst, budget)
    kind = aco.get("heuristic", "demand_distance")
    demand, eta = heuristic(inst, kind)

    # initialise τ at τ_max; update τ_max from the best cost once we have one
    tau_max = 1.0 / rho
    tau = np.full((n, n), tau_max, dtype=np.float64)
    start = np.full(n, tau_max, dtype=np.float64)  # bias for the first station
    best: list[int] | None = None
    best_cost = math.inf
    rows: list[tuple] = []
    sampler = TraceSampler(aco, n_ants, n_iter)

    log.info(
        "MMAS: N=%d k=%d ants=%d iterations=%d α=%.2f β=%.2f ρ=%.3f",
        n,
        k,
        n_ants,
        n_iter,
        alpha,
        beta,
        rho,
    )

    for it in range(n_iter):
        tours: list[list[int]] = []
        costs: list[float] = []
        for _ in range(n_ants):
            line = [pick(rng, start**alpha * demand**beta, [])]
            while len(line) < k:
                line.append(pick(rng, tau[line[-1]] ** alpha * eta[line[-1]] ** beta, line))
            tours.append(line)
            costs.append(f(line))

        ib = int(np.argmin(costs))
        if local_search:  # polish the iteration best (it deposits, it may become the best)
            tours[ib], costs[ib] = improve(f, tours[ib], costs[ib], n)
        improved = costs[ib] < best_cost
        if improved:
            best, best_cost = tours[ib], costs[ib]

        # deposit: iteration-best, or global-best every 3rd iteration (classic MMAS mix)
        assert best is not None
        dep_line, dep_cost = (best, best_cost) if it % 3 == 2 else (tours[ib], costs[ib])
        tau_max = 1.0 / (rho * best_cost / f.baseline)
        tau_min = tau_max * tau_min_ratio
        tau *= 1.0 - rho
        start *= 1.0 - rho
        q = f.baseline / dep_cost
        for a, b in zip(dep_line, dep_line[1:], strict=False):
            tau[a, b] += q
            tau[b, a] += q
        if inst.meta.topology == "loop" and len(dep_line) > 2:  # k = 2: the same pair
            a, b = dep_line[-1], dep_line[0]
            tau[a, b] += q
            tau[b, a] += q
        start[dep_line[0]] += q
        start[dep_line[-1]] += q
        np.clip(tau, tau_min, tau_max, out=tau)
        np.clip(start, tau_min, tau_max, out=start)

        h = entropy(tau)
        iter_best, iter_mean = costs[ib], float(np.mean(costs))
        rows.append((it, f.evaluations, best_cost, iter_best, iter_mean, tau_min, tau_max, h))
        log.info(
            "it %d/%d | best=%.3e | iter_best=%.3e | iter_mean=%.3e | "
            "improvement=%.1f%%%s | paths=%d | H=%.3f",
            it + 1,
            n_iter,
            best_cost,
            iter_best,
            iter_mean,
            100 * (1.0 - best_cost / f.baseline),
            " *" if improved else "",
            f.evaluations,
            h,
        )
        sampler.add(it, tours, costs, best, tau)
        if f.spent:
            break
    sampler.close(it, tours, costs, best, tau)

    params = {
        "n_ants": n_ants,
        "n_iterations": n_iter,
        "alpha": alpha,
        "beta": beta,
        "rho": rho,
        "tau_min_ratio": tau_min_ratio,
        "local_search": local_search,
        "heuristic": kind,
        "k": k,
        "topology": inst.meta.topology,
        "n_candidates": n,
    }
    return RunResult(
        algorithm="mmas",
        best_line=list(best),
        best_cost=float(best_cost),
        objective=f,
        convergence=convergence_frame(rows),
        trace=sampler.trace(inst.candidate_ids),
        params=params,
        eval_budget=budget or n_ants * n_iter,
    )

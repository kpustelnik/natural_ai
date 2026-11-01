"""Ant Colony System (Dorigo & Gambardella 1997) for an ordered k-station metro line.

Differs from MMAS (``mmas.py``) in three rules:

- **next station**: with probability ``aco.q0`` the best one (max τ^α η^β), else drawn in
  proportion to it, as in MMAS (the first station is always drawn);
- **local update**: every step an ant takes wears its pair back towards τ0,
  ``τ = (1 - ξ) τ + ξ τ0`` (``aco.xi``), so the ants of one iteration spread out;
- **global update**: only the best line so far deposits, ``τ = (1 - ρ) τ + ρ Δ`` on its
  pairs alone (no evaporation elsewhere), with ``Δ = baseline / best cost``.

Costs are taken relative to the no-metro baseline, so τ0 = 1 / N (a line as good as no metro,
spread over N candidates). Same heuristic, trace and convergence columns as MMAS.
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


def _pairs(line: list[int], loop: bool) -> list[tuple[int, int]]:
    pairs = list(zip(line, line[1:], strict=False))
    return pairs + [(line[-1], line[0])] if loop and len(line) > 2 else pairs


def run_acs(inst: Instance, cfg: dict, rng: np.random.Generator | None = None) -> RunResult:
    """Run ACS for ``aco.n_iterations`` with ``aco.n_ants`` ants per iteration."""
    aco = cfg["aco"]
    if rng is None:
        rng = np.random.default_rng(int(cfg.get("seed", 42)))

    n, k = check_k(inst)
    n_ants = int(aco["n_ants"])
    n_iter = int(aco["n_iterations"])
    alpha = float(aco["alpha"])
    beta = float(aco["beta"])
    rho = float(aco["rho"])
    q0 = float(aco["q0"])
    xi = float(aco["xi"])
    local_search = uses_local_search(cfg)
    loop = inst.meta.topology == "loop"

    budget = max_evaluations(cfg)
    f = Objective(inst, budget)
    kind = aco.get("heuristic", "demand_distance")
    demand, eta = heuristic(inst, kind)
    tau0 = 1.0 / n
    tau = np.full((n, n), tau0, dtype=np.float64)
    start = np.full(n, tau0, dtype=np.float64)  # bias for the first station
    best: list[int] | None = None
    best_cost = math.inf
    rows: list[tuple] = []
    sampler = TraceSampler(aco, n_ants, n_iter)
    log.info(
        "ACS: N=%d k=%d ants=%d iterations=%d α=%.2f β=%.2f ρ=%.3f q0=%.2f ξ=%.2f",
        n, k, n_ants, n_iter, alpha, beta, rho, q0, xi,
    )  # fmt: skip

    for it in range(n_iter):
        tours: list[list[int]] = []
        costs: list[float] = []
        for _ in range(n_ants):
            # the first station is drawn, as ACS places its ants on random cities: with q0
            # every ant would start at the same one, and τ = τ0 gives the local update nothing
            line = [pick(rng, start**alpha * demand**beta, [])]
            start[line[0]] = (1 - xi) * start[line[0]] + xi * tau0
            while len(line) < k:
                a = line[-1]
                b = pick(rng, tau[a] ** alpha * eta[a] ** beta, line, q0)
                tau[a, b] = tau[b, a] = (1 - xi) * tau[a, b] + xi * tau0
                line.append(b)
            tours.append(line)
            costs.append(f(line))

        ib = int(np.argmin(costs))
        if local_search:  # polish the iteration best (it deposits, it may become the best)
            tours[ib], costs[ib] = improve(f, tours[ib], costs[ib], n)
        improved = costs[ib] < best_cost
        if improved:
            best, best_cost = tours[ib], costs[ib]
        assert best is not None

        delta = f.baseline / best_cost
        for a, b in _pairs(best, loop):
            tau[a, b] = tau[b, a] = (1 - rho) * tau[a, b] + rho * delta
        for s in {best[0], best[-1]}:
            start[s] = (1 - rho) * start[s] + rho * delta

        h = entropy(tau)
        iter_best, iter_mean = costs[ib], float(np.mean(costs))
        rows.append(
            (it, f.evaluations, best_cost, iter_best, iter_mean, float(tau.min()),
             float(tau.max()), h)
        )  # fmt: skip
        log.info(
            "it %d/%d | best=%.3e | iter_best=%.3e | improvement=%.1f%%%s | paths=%d | H=%.3f",
            it + 1, n_iter, best_cost, iter_best, 100 * (1.0 - best_cost / f.baseline),
            " *" if improved else "", f.evaluations, h,
        )  # fmt: skip
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
        "q0": q0,
        "xi": xi,
        "local_search": local_search,
        "heuristic": kind,
        "tau0": tau0,
        "k": k,
        "topology": inst.meta.topology,
        "n_candidates": n,
    }
    return RunResult(
        algorithm="acs",
        best_line=list(best),
        best_cost=float(best_cost),
        objective=f,
        convergence=convergence_frame(rows),
        trace=sampler.trace(inst.candidate_ids),
        params=params,
        eval_budget=budget or n_ants * n_iter,
    )

"""MAX-MIN Ant System for an ordered k-station metro line.

Parameters come from ``config.yaml`` → ``aco`` (and ``Instance.meta.k`` / topology).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..schemas.instance import Instance
from ..schemas.results import AcoTrace
from ..schemas.tables import CONVERGENCE
from .objective import Objective

log = logging.getLogger(__name__)


@dataclass
class MmasResult:
    best_line: list[int]  # candidate indices
    best_cost: float
    objective: Objective
    convergence: pd.DataFrame
    trace: AcoTrace
    params: dict


def _heuristic(inst: Instance) -> tuple[np.ndarray, np.ndarray]:
    """η[u,v] ∝ demand near v / tunnel(u,v); demand[v] for the first-station bias."""
    n = inst.n_candidates
    access = np.where(np.isfinite(inst.access_s), inst.access_s, np.inf)
    near = np.argmin(access, axis=1)
    fr, to = near[inst.od_from], near[inst.od_to]
    fr_ok = np.isfinite(inst.access_s[inst.od_from, fr])
    to_ok = np.isfinite(inst.access_s[inst.od_to, to])
    demand = np.bincount(fr[fr_ok], inst.od_weight[fr_ok], n) + np.bincount(
        to[to_ok], inst.od_weight[to_ok], n
    )
    if demand.max() <= 0:
        demand = np.ones(n)
    demand = demand / demand.max() + 0.05
    eta = demand[None, :] / (inst.tunnel_m + 100.0) * 100.0
    np.fill_diagonal(eta, 0.0)
    return demand, eta


def run_mmas(inst: Instance, cfg: dict, rng: np.random.Generator | None = None) -> MmasResult:
    """Run MMAS for ``aco.n_iterations`` with ``aco.n_ants`` ants per iteration."""
    aco = cfg["aco"]
    if rng is None:
        rng = np.random.default_rng(int(cfg.get("seed", 42)))

    n, k = inst.n_candidates, int(inst.meta.k)
    if k > n:
        raise ValueError(f"k={k} > N={n} candidates")
    n_ants = int(aco["n_ants"])
    n_iter = int(aco["n_iterations"])
    alpha = float(aco["alpha"])
    beta = float(aco["beta"])
    rho = float(aco["rho"])
    tau_min_ratio = float(aco["tau_min_ratio"])
    every = max(1, int(aco["trace"]["every"]))
    max_ants = min(int(aco["trace"]["max_ants"]), n_ants)

    f = Objective(inst)
    demand, eta = _heuristic(inst)

    # initialise τ at τ_max; update τ_max from the best cost once we have one
    tau_max = 1.0 / rho
    tau = np.full((n, n), tau_max, dtype=np.float64)
    start = np.full(n, tau_max, dtype=np.float64)  # bias for the first station
    best: list[int] | None = None
    best_cost = math.inf
    rows: list[tuple] = []
    sampled: dict[str, list] = {"it": [], "tours": [], "cost": [], "best": [], "tau": []}

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
            p = start**alpha * demand**beta
            p = np.maximum(p, 0.0)
            if p.sum() <= 0:
                p = np.ones(n)
            line = [int(rng.choice(n, p=p / p.sum()))]
            while len(line) < k:
                w = tau[line[-1]] ** alpha * eta[line[-1]] ** beta
                w = np.asarray(w, dtype=np.float64)
                w[line] = 0.0
                if w.sum() <= 0:
                    rest = [i for i in range(n) if i not in line]
                    line.append(int(rng.choice(rest)))
                else:
                    line.append(int(rng.choice(n, p=w / w.sum())))
            tours.append(line)
            costs.append(f(line))

        ib = int(np.argmin(costs))
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
        if inst.meta.topology == "loop":
            a, b = dep_line[-1], dep_line[0]
            tau[a, b] += q
            tau[b, a] += q
        start[dep_line[0]] += q
        start[dep_line[-1]] += q
        np.clip(tau, tau_min, tau_max, out=tau)
        np.clip(start, tau_min, tau_max, out=start)

        upper = tau[np.triu_indices(n, 1)]
        if upper.sum() > 0 and len(upper) > 1:
            pr = upper / upper.sum()
            entropy = float(-(pr * np.log(pr + 1e-30)).sum() / math.log(len(upper)))
        else:
            entropy = 0.0
        iter_best, iter_mean = costs[ib], float(np.mean(costs))
        rows.append((it, f.evaluations, best_cost, iter_best, iter_mean, tau_min, tau_max, entropy))
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
            entropy,
        )

        if it % every == 0 or it == n_iter - 1:
            sampled["it"].append(it)
            sampled["tours"].append(tours[:max_ants])
            sampled["cost"].append(costs[:max_ants])
            sampled["best"].append(list(best))
            sampled["tau"].append(tau.astype(np.float32))

    # pad ant dimension if some iterations had fewer than max_ants (always n_ants here)
    tours_arr = np.array(sampled["tours"], dtype=np.int16)
    cost_arr = np.array(sampled["cost"], dtype=np.float32)
    trace = AcoTrace(
        iterations=np.array(sampled["it"], np.int32),
        tours=tours_arr,
        tour_cost_s=cost_arr,
        best_tour=np.array(sampled["best"], np.int16),
        pheromone=np.array(sampled["tau"], np.float32),
        candidate_ids=inst.candidate_ids,
    )
    conv = pd.DataFrame(rows, columns=CONVERGENCE.column_names)
    params = {
        "variant": "mmas",
        "n_ants": n_ants,
        "n_iterations": n_iter,
        "alpha": alpha,
        "beta": beta,
        "rho": rho,
        "tau_min_ratio": tau_min_ratio,
        "k": k,
        "topology": inst.meta.topology,
        "n_candidates": n,
    }
    return MmasResult(
        best_line=list(best),
        best_cost=float(best_cost),
        objective=f,
        convergence=conv,
        trace=trace,
        params=params,
    )

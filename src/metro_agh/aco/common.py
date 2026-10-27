"""What every optimiser shares: the run result, and for the ant colonies the heuristic, the
choice of the next station, the pheromone entropy and the sampled trace."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..schemas.instance import Instance
from ..schemas.results import AcoTrace
from ..schemas.tables import CONVERGENCE
from .objective import Objective


@dataclass
class RunResult:
    algorithm: str  # mmas | acs | random | greedy | brute_force
    best_line: list[int]  # candidate indices
    best_cost: float
    objective: Objective
    convergence: pd.DataFrame  # tables.CONVERGENCE
    trace: AcoTrace | None  # ant colonies only
    params: dict
    eval_budget: int  # evaluations the algorithm may use (runs.csv: compare at equal budget)


def convergence_frame(rows: list[tuple]) -> pd.DataFrame:
    """Rows of (iteration, evaluations, best, iter_best, iter_mean[, tau_min, tau_max,
    entropy]); the pheromone columns stay null for the baselines."""
    rows = [tuple(r) + (math.nan,) * (8 - len(r)) for r in rows]
    return pd.DataFrame(rows, columns=CONVERGENCE.column_names)


def max_evaluations(cfg: dict) -> int | None:
    """``optimize.max_evaluations``: the same budget of distinct lines for every stochastic
    algorithm (iterations become an upper bound); None = run all iterations."""
    v = cfg.get("optimize", {}).get("max_evaluations")
    return int(v) if v else None


def uses_local_search(cfg: dict) -> bool:
    """``optimize.local_search``: polish lines with ``local_search.improve`` (every algorithm
    but brute force, so the comparison isolates what the search strategy adds)."""
    return bool(cfg.get("optimize", {}).get("local_search", False))


def check_k(inst: Instance) -> tuple[int, int]:
    n, k = inst.n_candidates, int(inst.meta.k)
    if k > n:
        raise ValueError(f"k={k} > N={n} candidates")
    return n, k


def heuristic(inst: Instance) -> tuple[np.ndarray, np.ndarray]:
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


def pick(rng: np.random.Generator, w: np.ndarray, line: list[int], q0: float = 0.0) -> int:
    """Next station from weights ``w`` (stations already on ``line`` excluded): with
    probability ``q0`` the best one (ACS), else in proportion to ``w``."""
    w = np.asarray(w, dtype=np.float64).copy()
    w[line] = 0.0
    if w.sum() <= 0:
        rest = [i for i in range(len(w)) if i not in line]
        return int(rng.choice(rest))
    if q0 > 0 and rng.random() < q0:
        return int(np.argmax(w))
    return int(rng.choice(len(w), p=w / w.sum()))


def entropy(tau: np.ndarray) -> float:
    """Pheromone entropy over the station pairs, normalised to 0..1 (1 = uniform)."""
    upper = tau[np.triu_indices(len(tau), 1)]
    if upper.sum() <= 0 or len(upper) <= 1:
        return 0.0
    pr = upper / upper.sum()
    return float(-(pr * np.log(pr + 1e-30)).sum() / math.log(len(upper)))


class TraceSampler:
    """Every ``every``-th iteration (and the last): the first ``max_ants`` tours, the best
    so far and the pheromone, for ``trace.npz``."""

    def __init__(self, aco: dict, n_ants: int, n_iter: int):
        self.every = max(1, int(aco["trace"]["every"]))
        self.max_ants = min(int(aco["trace"]["max_ants"]), n_ants)
        self.n_iter = n_iter
        self.s: dict[str, list] = {"it": [], "tours": [], "cost": [], "best": [], "tau": []}

    def add(self, it: int, tours: list, costs: list, best: list[int], tau: np.ndarray) -> None:
        if it % self.every and it != self.n_iter - 1:
            return
        self.s["it"].append(it)
        self.s["tours"].append(tours[: self.max_ants])
        self.s["cost"].append(costs[: self.max_ants])
        self.s["best"].append(list(best))
        self.s["tau"].append(tau.astype(np.float32))

    def close(self, it: int, tours: list, costs: list, best: list[int], tau: np.ndarray) -> None:
        """The last iteration, when the budget ended the run early."""
        if not self.s["it"] or self.s["it"][-1] != it:
            self.n_iter = it + 1
            self.add(it, tours, costs, best, tau)

    def trace(self, candidate_ids: np.ndarray) -> AcoTrace:
        s = self.s
        return AcoTrace(
            iterations=np.array(s["it"], np.int32),
            tours=np.array(s["tours"], dtype=np.int16),
            tour_cost_s=np.array(s["cost"], dtype=np.float32),
            best_tour=np.array(s["best"], np.int16),
            pheromone=np.array(s["tau"], np.float32),
            candidate_ids=candidate_ids,
        )

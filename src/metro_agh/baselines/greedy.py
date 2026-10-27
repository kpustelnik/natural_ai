"""Greedy construction: the best 2-station line, then k - 2 times the station and the place
in the line (either end or between two stations) that lower the objective most; with
``optimize.local_search`` the final line is then polished.
Deterministic: ties go to the lower candidate index, the seed is not used."""

from __future__ import annotations

import itertools
import logging

import numpy as np

from ..aco.common import RunResult, check_k, convergence_frame, uses_local_search
from ..aco.local_search import improve
from ..aco.objective import Objective
from ..schemas.instance import Instance

log = logging.getLogger(__name__)


def run_greedy(inst: Instance, cfg: dict, rng: np.random.Generator | None = None) -> RunResult:
    n, k = check_k(inst)
    f = Objective(inst)
    lines = [[a, b] for a, b in itertools.combinations(range(n), 2)]
    rows = []
    for step in range(k - 1):
        costs = [f(line) for line in lines]
        ib = int(np.argmin(costs))
        line, cost = lines[ib], costs[ib]
        rows.append((step, f.evaluations, cost, cost, float(np.mean(costs))))
        if len(line) == k:
            break
        lines = [
            line[:p] + [c] + line[p:]
            for c in range(n)
            if c not in line
            for p in range(len(line) + 1)
        ]
    if uses_local_search(cfg):
        line, cost = improve(f, line, cost, n)
        rows.append((len(rows), f.evaluations, cost, cost, cost))
    log.info(
        "greedy: %s, %.3e (%.1f%% below no metro), %d evaluations",
        line, cost, 100 * (1 - cost / f.baseline), f.evaluations,
    )  # fmt: skip
    return RunResult(
        algorithm="greedy",
        best_line=line,
        best_cost=float(cost),
        objective=f,
        convergence=convergence_frame(rows),  # one row per station added
        trace=None,
        params={
            "k": k,
            "topology": inst.meta.topology,
            "n_candidates": n,
            "local_search": uses_local_search(cfg),
        },
        eval_budget=max(1, f.evaluations),
    )

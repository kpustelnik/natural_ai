"""Brute force: every distinct k-station line, for the exact optimum on small instances
(validation: the gap of the colonies to it). A line and its reverse are one line, and a loop
is the same from any station in either direction, so each is evaluated once.

Refuses instances with more than ``optimize.brute_force_max_lines`` lines: the campus
(55 candidates, k = 5) has about 2·10^8.
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Iterator

import numpy as np

from ..aco.common import RunResult, check_k, convergence_frame
from ..aco.objective import Objective
from ..schemas.instance import Instance

log = logging.getLogger(__name__)

N_ROWS = 100  # convergence rows over the whole enumeration


def count_lines(n: int, k: int, topology: str) -> int:
    if topology == "loop" and k >= 3:
        return math.comb(n, k) * math.factorial(k - 1) // 2
    return math.perm(n, k) // 2


def all_lines(n: int, k: int, topology: str) -> Iterator[list[int]]:
    """Each distinct line once: first < last (a reversed line is the same); a loop also
    starts at its lowest station."""
    for comb in itertools.combinations(range(n), k):
        if topology == "loop" and k >= 3:
            for rest in itertools.permutations(comb[1:]):
                if rest[0] < rest[-1]:
                    yield [comb[0], *rest]
        else:
            for perm in itertools.permutations(comb):
                if perm[0] < perm[-1]:
                    yield list(perm)


def run_brute_force(inst: Instance, cfg: dict, rng: np.random.Generator | None = None) -> RunResult:
    n, k = check_k(inst)
    topology = inst.meta.topology
    total = count_lines(n, k, topology)
    limit = int(cfg.get("optimize", {}).get("brute_force_max_lines", 200_000))
    if total > limit:
        raise ValueError(
            f"brute force: {total:,} lines for N={n}, k={k} ({topology}), more than "
            f"optimize.brute_force_max_lines={limit:,}: lower k or list fewer metro.candidates"
        )
    f = Objective(inst)
    best: list[int] = []
    best_cost = math.inf
    rows = []
    chunk = max(1, math.ceil(total / N_ROWS))
    lines = all_lines(n, k, topology)
    for it in itertools.count():
        costs = [(f(line), line) for line in itertools.islice(lines, chunk)]
        if not costs:
            break
        cost, line = min(costs, key=lambda c: c[0])
        if cost < best_cost:
            best, best_cost = line, cost
        rows.append((it, f.evaluations, best_cost, cost, float(np.mean([c for c, _ in costs]))))
    log.info(
        "brute force: %d lines, optimum %s %.3e (%.1f%% below no metro)",
        total, best, best_cost, 100 * (1 - best_cost / f.baseline),
    )  # fmt: skip
    return RunResult(
        algorithm="brute_force",
        best_line=best,
        best_cost=float(best_cost),
        objective=f,
        convergence=convergence_frame(rows),
        trace=None,
        params={"k": k, "topology": topology, "n_candidates": n, "n_lines": total},
        eval_budget=total,
    )

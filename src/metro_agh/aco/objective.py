"""Objective for a metro line: weighted sum of min(walk, metro) over OD pairs.

Contract: docs/data_contracts.md, section 7.
"""

from __future__ import annotations

import numpy as np

from ..schemas.instance import Instance


def canonical(line: list[int], topology: str) -> tuple[int, ...]:
    """One key per physical line: A-B-C = C-B-A, and a loop is the same from any station
    in either direction."""
    t = tuple(line)
    if topology == "loop":
        turns = [t[i:] + t[:i] for i in range(len(t))]
        return min(turns + [r[::-1] for r in turns])
    return min(t, t[::-1])


class Objective:
    """Vectorised over OD pairs; caches distinct lines (a reversed line is the same line)."""

    def __init__(self, inst: Instance, budget: int | None = None):
        self.i = inst
        self.cache: dict[tuple[int, ...], float] = {}
        self.evaluations = 0
        self.budget = budget  # distinct lines an algorithm may evaluate (None: no limit)
        self.baseline = float((inst.od_weight * inst.od_walk_s).sum())
        # walk times of every OD pair to / from every candidate, gathered once: (M, N)
        self._access = np.ascontiguousarray(inst.access_s[inst.od_from].T)  # (N, M)
        self._egress = np.ascontiguousarray(inst.egress_s[:, inst.od_to])  # (N, M)

    @property
    def spent(self) -> bool:
        """The evaluation budget is used up: the algorithm stops at its next check."""
        return self.budget is not None and self.evaluations >= self.budget

    def ride(self, line: list[int]) -> np.ndarray:
        """(k, k) ride time between stations on the line (incl. intermediate dwell)."""
        meta, tun = self.i.meta, self.i.tunnel_m
        steps = [tun[a, b] for a, b in zip(line, line[1:], strict=False)]
        pos = np.concatenate([[0.0], np.cumsum(steps)])
        gap = np.abs(pos[:, None] - pos[None])
        hops = np.abs(np.arange(len(line))[:, None] - np.arange(len(line))[None])
        v, dwell = meta.metro_speed_mps, meta.dwell_s
        ride = gap / v + dwell * np.maximum(hops - 1, 0)
        if meta.topology == "loop":
            # the other way round: its own distance and its own stops (not mixed with this way)
            total = pos[-1] + tun[line[-1], line[0]]
            other = (total - gap) / v + dwell * np.maximum(len(line) - hops - 1, 0)
            ride = np.minimum(ride, other)
        return ride

    def __call__(self, line: list[int]) -> float:
        key = canonical(line, self.i.meta.topology)
        if key in self.cache:
            return self.cache[key]
        self.evaluations += 1
        # the key's order: a line and its reverse (or a rotated loop) cost exactly the same,
        # not two values a float rounding apart
        line = list(key)
        i, meta = self.i, self.i.meta
        a, e = self._access[line], self._egress[line]  # (k, M) each
        fixed = meta.shaft_down_s + meta.wait_s + meta.shaft_up_s
        ride = self.ride(line) + fixed
        np.fill_diagonal(ride, np.inf)  # board and alight at different stations
        # min over (board i, alight j); the k x k loop keeps the arrays (M,), not (M, k, k)
        metro = np.full(a.shape[1], np.inf, dtype=np.float64)
        for b in range(len(line)):
            via = e + ride[b][:, None]  # (k, M): alight j after boarding at b
            np.minimum(metro, a[b] + via.min(axis=0), out=metro)
        cost = float((i.od_weight * np.minimum(i.od_walk_s, metro)).sum())
        self.cache[key] = cost
        return cost


def teleport_bound(inst: Instance) -> float:
    """Lower bound of the objective over every line: the metro ride takes 0 s and every OD
    pair has the two best different candidates as its stations (still with the shafts and
    the wait). No line of any k can beat it (validation test 6)."""
    meta = inst.meta
    a = inst.access_s[inst.od_from].astype(np.float64)  # (M, N)
    e = inst.egress_s[:, inst.od_to].T.astype(np.float64)  # (M, N)
    rows = np.arange(len(a))

    def two_best(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        order = np.argsort(x, axis=1)[:, :2]
        return order[:, 0], x[rows, order[:, 0]], x[rows, order[:, 1]]

    ia, a1, a2 = two_best(a)
    ie, e1, e2 = two_best(e)
    best = np.where(ia != ie, a1 + e1, np.minimum(a1 + e2, a2 + e1))  # board != alight
    metro = best + meta.shaft_down_s + meta.wait_s + meta.shaft_up_s
    return float((inst.od_weight * np.minimum(inst.od_walk_s, metro)).sum())

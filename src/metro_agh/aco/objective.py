"""Objective for a metro line: weighted sum of min(walk, metro) over OD pairs.

Contract: docs/data_contracts.md, section 7.
"""

from __future__ import annotations

import numpy as np

from ..schemas.instance import Instance


class Objective:
    """Vectorised over OD pairs; caches distinct lines."""

    def __init__(self, inst: Instance):
        self.i = inst
        self.cache: dict[tuple[int, ...], float] = {}
        self.evaluations = 0
        self.baseline = float((inst.od_weight * inst.od_walk_s).sum())

    def ride(self, line: list[int]) -> np.ndarray:
        """(k, k) ride time between stations on the line (incl. intermediate dwell)."""
        meta, tun = self.i.meta, self.i.tunnel_m
        steps = [tun[a, b] for a, b in zip(line, line[1:], strict=False)]
        pos = np.concatenate([[0.0], np.cumsum(steps)])
        gap = np.abs(pos[:, None] - pos[None])
        hops = np.abs(np.arange(len(line))[:, None] - np.arange(len(line))[None])
        if meta.topology == "loop":
            total = pos[-1] + tun[line[-1], line[0]]
            gap = np.minimum(gap, total - gap)
            hops = np.minimum(hops, len(line) - hops)
        return gap / meta.metro_speed_mps + meta.dwell_s * np.maximum(hops - 1, 0)

    def __call__(self, line: list[int]) -> float:
        key = tuple(line)
        if key in self.cache:
            return self.cache[key]
        self.evaluations += 1
        i, meta = self.i, self.i.meta
        a = i.access_s[i.od_from][:, line]  # (M, k)
        e = i.egress_s[line][:, i.od_to].T  # (M, k)
        fixed = meta.shaft_down_s + meta.wait_s + meta.shaft_up_s
        total = a[:, :, None] + (self.ride(line) + fixed)[None] + e[:, None, :]
        k = len(line)
        total[:, np.arange(k), np.arange(k)] = np.inf
        metro = total.reshape(len(a), -1).min(axis=1)
        cost = float((i.od_weight * np.minimum(i.od_walk_s, metro)).sum())
        self.cache[key] = cost
        return cost

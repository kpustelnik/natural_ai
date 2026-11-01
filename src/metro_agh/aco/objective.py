"""Objective for a metro line: weighted sum of min(walk, metro) over OD pairs.

Contract: docs/data_contracts.md, section 7. How it is used: docs/aco.md.
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
    """Vectorised over OD pairs; caches distinct lines (a reversed line is the same line).

    The inner loop runs compiled (numba, ``_batch_loop``) when available, else in NumPy
    (``travel_numpy``, the reference). With ``tunnel_penalty_per_km`` > 0 the value adds that
    share of the no-metro baseline per km of tunnel (``travel`` leaves it out).
    """

    def __init__(
        self, inst: Instance, budget: int | None = None, tunnel_penalty_per_km: float = 0.0
    ):
        self.i = inst
        self.cache: dict[tuple[int, ...], float] = {}
        self.evaluations = 0
        self.budget = budget  # distinct lines an algorithm may evaluate (None: no limit)
        self.baseline = float((inst.od_weight * inst.od_walk_s).sum())
        self.penalty_per_m = float(tunnel_penalty_per_km) * self.baseline / 1000.0
        # walk times of every candidate to / from every OD pair, gathered once: (N, M)
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
        cost = self.travel(line)
        if self.penalty_per_m:
            cost += self.penalty_per_m * self.tunnel_m(line)
        return cost

    def travel(self, line: list[int]) -> float:
        """Weighted total travel time with this line (no tunnel penalty); cached."""
        key = canonical(line, self.i.meta.topology)
        if key in self.cache:
            return self.cache[key]
        self.evaluations += 1
        # the key's order: a line and its reverse (or a rotated loop) cost exactly the same,
        # not two values a float rounding apart
        line = list(key)
        if _PARALLEL is not None:
            cost = float(self._compiled(np.asarray([line], dtype=np.int64))[0])
        else:
            cost = self.travel_numpy(line)
        self.cache[key] = cost
        return cost

    def tunnel_m(self, line: list[int]) -> float:
        """Tunnel length of the line: neighbours, plus the closing edge of a loop."""
        tun = self.i.tunnel_m
        total = float(sum(tun[a, b] for a, b in zip(line, line[1:], strict=False)))
        if self.i.meta.topology == "loop" and len(line) > 2:
            total += float(tun[line[-1], line[0]])
        return total

    def many(self, lines: np.ndarray) -> np.ndarray:
        """The objective of B lines at once, (B, k) candidate indices -> (B,): no cache, and
        ``evaluations`` += B (for brute force and greedy, which see every line once)."""
        lines = np.asarray(lines, dtype=np.int64)
        if _PARALLEL is not None:
            out = self._compiled(lines)
        else:
            out = np.array([self.travel_numpy(list(ln)) for ln in lines])
        if self.penalty_per_m:
            tun = self.i.tunnel_m
            km = tun[lines[:, :-1], lines[:, 1:]].sum(axis=1).astype(np.float64)
            if self.i.meta.topology == "loop" and lines.shape[1] > 2:
                km += tun[lines[:, -1], lines[:, 0]]
            out = out + self.penalty_per_m * km
        self.evaluations += len(lines)
        return out

    def _compiled(self, lines: np.ndarray) -> np.ndarray:
        if not hasattr(self, "_k_args"):
            i = self.i
            self._k_args = (
                np.ascontiguousarray(self._access.T, dtype=np.float64),  # (M, N)
                np.ascontiguousarray(self._egress.T, dtype=np.float64),  # (M, N)
                i.od_walk_s.astype(np.float64),
                i.od_weight.astype(np.float64),
            )
        ride = np.stack([self.ride(list(ln)) for ln in lines]) + self.fixed_s
        kernel = _PARALLEL if len(lines) >= 64 else _SERIAL
        return kernel(*self._k_args, lines, ride)

    @property
    def fixed_s(self) -> float:
        """Shaft down + platform wait + shaft up: paid once by every metro trip."""
        m = self.i.meta
        return m.shaft_down_s + m.wait_s + m.shaft_up_s

    def travel_numpy(self, line: list[int]) -> float:
        """The reference implementation of contracts §7 in NumPy (no cache, no count)."""
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
        return float((i.od_weight * np.minimum(i.od_walk_s, metro)).sum())


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


def objective_for(inst: Instance, cfg: dict, budget: int | None = None) -> Objective:
    """The objective with ``metro.tunnel_penalty_per_km`` (default 0) from ``cfg``."""
    share = float((cfg.get("metro") or {}).get("tunnel_penalty_per_km") or 0.0)
    return Objective(inst, budget, tunnel_penalty_per_km=share)


try:
    from numba import njit, prange
except ImportError:  # pragma: no cover
    njit, prange = None, range


def _batch_loop(acc, egr, walk, weight, lines, ride):  # pragma: no cover (compiled)
    """For each line and OD pair the best (board i, alight j) pair of its stations, or the
    no-metro time. A boarding station whose walk alone is already slower is skipped: rides
    and egress are ≥ 0, so this is exact."""
    b_all, k = lines.shape
    m_all = acc.shape[0]
    out = np.empty(b_all)
    for b in prange(b_all):
        s = 0.0
        for m in range(m_all):
            best = walk[m]
            for i in range(k):
                ai = acc[m, lines[b, i]]
                if ai >= best:
                    continue
                for j in range(k):
                    if i != j:
                        t = ai + ride[b, i, j] + egr[m, lines[b, j]]
                        if t < best:
                            best = t
            s += weight[m] * best
        out[b] = s
    return out


if njit is not None:
    _PARALLEL = njit(parallel=True, cache=True)(_batch_loop)
    _SERIAL = njit(cache=True)(_batch_loop)  # prange is range here: no thread start-up
else:  # pragma: no cover
    _PARALLEL = _SERIAL = None

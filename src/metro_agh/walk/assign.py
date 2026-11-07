"""ACO level 1: the peak walking flows assigned on the walk graph with congestion.

The metro model (level 2) walks everybody on the free-flow shortest path. Here the peak
quarter hour of the week (``walk_aco.window_*``, by default Wednesday 9:30, when 5 381
students leave their classes, 81 % of them in the first minute) is routed again, and a
walk gets slower when many people use the same path segment:

    t(x) = t0 * (1 + a * (x / C)^b)          (BPR form; Lam, Cheung 2000 for walkways)
    C    = capacity [ped/min/m] * width [m] * period [min]

``x`` is the number of people on the segment in both directions during ``period_s`` (the
wave after a class ends passes a segment in about five minutes). With a = 0.73 the speed at
capacity is 1.3 / 1.73 = 0.75 m/s (FHWA-RD-98-107). OSM has no width tags on campus, so
the width comes from the way type (``walk_aco.widths_m``).

Three assignments of the same demand:

- ``aon``: all-or-nothing on free-flow times: what level 2 and the simulation assume;
- ``run_walk_aco``: the ant colony. Each (origin, destination) pair sends ``n_ants`` ants.
  An ant at node u heading to d picks the next segment u -> v with probability

      tau[d, uv]^alpha * exp(-beta * (c_uv + h_d(v) - h_d(u)) / detour_scale_s)

  where c is the current congested time and h_d the congested shortest time to d (so the
  heuristic is the detour the step costs, 0 on a shortest path; Dial-style). The pair's
  people are split equally over its ants' paths, and the flows are averaged over
  iterations with step 1 / n (method of successive averages, as D'Acierno et al. 2012
  turn their ant flows into an equilibrium). The pheromone is kept per destination,
  evaporates with ``rho``, every ant deposits (its pair's shortest time / its path time)
  / n_ants, and it is clipped to [tau_min, tau_max] like MMAS;
- ``run_msa``: the classic deterministic reference, all-or-nothing on the current
  congested times averaged with step 1 / n (user equilibrium, Wardrop).

Reported: total and mean time per person, the relative gap to equilibrium
(Σ x c − Σ n · shortest) / Σ x c, the most loaded segment (x / C) and how many are over
capacity. The metro instance is not changed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

INF = 1e18


@dataclass
class WalkNet:
    """The walk graph as arcs (edge e = arcs 2e: u -> v and 2e + 1: v -> u)."""

    n_nodes: int
    edge_u: np.ndarray  # int32 (E,) node ids of the parquet graph
    edge_v: np.ndarray
    edge_kind: np.ndarray  # str (E,): GRAPH_EDGES kind, outdoor ones as their OSM highway
    width_m: np.ndarray  # float (E,)
    cap: np.ndarray  # float (E,): people per period at capacity
    arc_v: np.ndarray  # int32 (2E,) head node
    arc_t0: np.ndarray  # float (2E,) free-flow time
    out_ptr: np.ndarray  # int32 (n+1,) arcs leaving each node (CSR)
    out_arc: np.ndarray  # int32

    @property
    def n_edges(self) -> int:
        return len(self.edge_u)


@dataclass
class PeakDemand:
    origin: np.ndarray  # int32 node ids
    dest: np.ndarray
    n: np.ndarray  # float people
    dest_nodes: np.ndarray  # int32 distinct destinations
    dest_index: np.ndarray  # int32 into dest_nodes, per pair
    n_legs: int = 0

    @property
    def people(self) -> float:
        return float(self.n.sum())


@dataclass
class Assignment:
    """Result of one assignment: arc flows and costs plus the curve per iteration."""

    name: str
    x_arc: np.ndarray
    cost: np.ndarray
    total_s: float
    gap: float
    curve: list[dict] = field(default_factory=list)
    trace: dict | None = None


# ---------------------------------------------------------------- inputs


def highway_of_ways(gpkg: Path) -> dict[str, str]:
    """OSM way id -> highway tag, from the walk edges of ``osm/campus.gpkg``."""
    import geopandas as gpd

    g = gpd.read_file(gpkg, layer="walk_edges", columns=["osm_ways", "highway"])
    out: dict[str, str] = {}
    for ways, hw in zip(g["osm_ways"].astype(str), g["highway"].astype(str), strict=True):
        for w in ways.split("|"):
            out.setdefault(w, hw)
    return out


def build_net(
    nodes: pd.DataFrame, edges: pd.DataFrame, cfg: dict, highway: dict[str, str]
) -> WalkNet:
    """Arcs, widths and capacities of every edge but the metro shafts."""
    wc = cfg["walk_aco"]
    e = edges[edges["kind"] != "shaft"].reset_index(drop=True)
    kinds = []
    for kind, src in zip(e["kind"], e["source"].astype(str), strict=True):
        if kind == "outdoor":
            way = src.split("|")[0].removeprefix("way/")
            kinds.append(highway.get(way, "footway"))
        else:
            kinds.append(kind)
    kinds = np.array(kinds, dtype=object)
    widths = wc["widths_m"]
    width = np.array([float(widths.get(k, widths["footway"])) for k in kinds])
    per_min = np.where(
        np.isin(kinds, ["steps", "stairs"]),
        float(wc["stairs_capacity_ped_min_m"]),
        float(wc["capacity_ped_min_m"]),
    )
    cap = per_min * width * float(wc["period_s"]) / 60.0

    u = e["u"].to_numpy(np.int32)
    v = e["v"].to_numpy(np.int32)
    n_e = len(e)
    arc_u = np.empty(2 * n_e, np.int32)
    arc_v = np.empty(2 * n_e, np.int32)
    arc_u[0::2], arc_v[0::2] = u, v
    arc_u[1::2], arc_v[1::2] = v, u
    t0 = np.empty(2 * n_e)
    t0[0::2] = e["time_uv_s"].to_numpy(float)
    t0[1::2] = e["time_vu_s"].to_numpy(float)
    t0 = np.maximum(t0, 1e-3)
    n = int(len(nodes))
    order = np.argsort(arc_u, kind="stable").astype(np.int32)
    ptr = np.zeros(n + 1, np.int32)
    np.add.at(ptr, arc_u + 1, 1)
    ptr = np.cumsum(ptr).astype(np.int32)
    return WalkNet(n, u, v, kinds, width, cap, arc_v, t0, ptr, order)


def peak_demand(sim_legs: pd.DataFrame, cfg: dict) -> PeakDemand:
    """Walking legs of the no-metro simulation leaving in the window, as node pairs."""
    wc = cfg["walk_aco"]
    t0 = int(wc["window_start_wt"])
    t1 = t0 + int(wc["window_s"])
    legs = sim_legs[
        (sim_legs["mode"] == "walk") & (sim_legs["depart_wt"] >= t0) & (sim_legs["depart_wt"] < t1)
    ]
    o = legs["path_nodes"].map(lambda p: int(p[0]))
    d = legs["path_nodes"].map(lambda p: int(p[-1]))
    od = pd.DataFrame({"o": o, "d": d})
    od = od[od.o != od.d].value_counts().rename("n").reset_index().sort_values(["d", "o"])
    dests, dest_index = np.unique(od["d"].to_numpy(np.int32), return_inverse=True)
    return PeakDemand(
        od["o"].to_numpy(np.int32),
        od["d"].to_numpy(np.int32),
        od["n"].to_numpy(float),
        dests.astype(np.int32),
        dest_index.astype(np.int32),
        n_legs=len(legs),
    )


# ---------------------------------------------------------------- costs


def edge_flow(x_arc: np.ndarray) -> np.ndarray:
    """People on each edge, both directions together (they share the width)."""
    return x_arc[0::2] + x_arc[1::2]


def arc_costs(net: WalkNet, x_arc: np.ndarray, cfg: dict) -> np.ndarray:
    wc = cfg["walk_aco"]
    ratio = edge_flow(x_arc) / net.cap
    factor = 1.0 + float(wc["bpr_a"]) * ratio ** float(wc["bpr_b"])
    return net.arc_t0 * np.repeat(factor, 2)


def dest_times(net: WalkNet, cost: np.ndarray, dests: np.ndarray) -> np.ndarray:
    """h[d, node]: shortest time from every node to each destination (reverse Dijkstra)."""
    tails = np.repeat(np.arange(net.n_nodes, dtype=np.int32), np.diff(net.out_ptr))
    arcs = net.out_arc
    df = pd.DataFrame({"r": net.arc_v[arcs], "c": tails, "w": cost[arcs]})
    df = df.groupby(["r", "c"], as_index=False).w.min()
    rev = csr_matrix(
        (df.w.to_numpy(), (df.r.to_numpy(), df.c.to_numpy())), shape=(net.n_nodes,) * 2
    )
    h = dijkstra(rev, directed=True, indices=dests)
    return np.where(np.isfinite(h), h, INF)


def total_time(x_arc: np.ndarray, cost: np.ndarray) -> float:
    return float((x_arc * cost).sum())


def shortest_total(demand: PeakDemand, h: np.ndarray) -> float:
    return float((demand.n * h[demand.dest_index, demand.origin]).sum())


def free_flow_total(net: WalkNet, demand: PeakDemand) -> float:
    """Σ n · free-flow shortest time: the time without any congestion (a lower bound)."""
    return shortest_total(demand, dest_times(net, net.arc_t0, demand.dest_nodes))


# ---------------------------------------------------------------- compiled kernels


@njit(cache=True)
def _greedy(u0, di, out_ptr, out_arc, arc_v, cost, h, stamp, mark, path, max_steps):
    """Shortest path by following the arc that keeps cost + h smallest."""
    u = u0
    steps = 0
    total = 0.0
    while h[di, u] > 1e-9 and steps < max_steps:
        best = -1
        bestv = INF
        for q in range(out_ptr[u], out_ptr[u + 1]):
            a = out_arc[q]
            v = arc_v[a]
            if mark[v] == stamp:
                continue
            val = cost[a] + h[di, v]
            if val < bestv:
                bestv = val
                best = a
        if best < 0:
            return -1, total
        path[steps] = best
        steps += 1
        total += cost[best]
        u = arc_v[best]
        mark[u] = stamp
    return steps, total


@njit(cache=True)
def _ants(
    origin, dest_index, n_people, out_ptr, out_arc, arc_v, cost, h, tau,
    n_ants, alpha, beta, scale, max_steps, seed, record, rec_nodes, rec_len,
):  # fmt: skip
    """One iteration of the colony: returns arc flows y, pheromone deposits, failures."""
    np.random.seed(seed)  # noqa: NPY002 (numba has no Generator; this seeds its own RNG)
    n_arcs = len(cost)
    n_nodes = len(out_ptr) - 1
    y = np.zeros(n_arcs)
    deposit = np.zeros(tau.shape)
    mark = np.zeros(n_nodes, np.int64)
    stamp = 0
    path = np.empty(max_steps, np.int32)
    weights = np.empty(64)
    arcs = np.empty(64, np.int32)
    fails = 0
    ant_id = 0
    for p in range(len(origin)):
        o = origin[p]
        di = dest_index[p]
        share = n_people[p] / n_ants
        sp = h[di, o]
        for _ in range(n_ants):
            stamp += 1
            mark[o] = stamp
            u = o
            steps = 0
            total = 0.0
            ok = True
            while h[di, u] > 1e-9:
                if steps >= max_steps:
                    ok = False
                    break
                m = 0
                wsum = 0.0
                for q in range(out_ptr[u], out_ptr[u + 1]):
                    a = out_arc[q]
                    v = arc_v[a]
                    # efficient steps only (Dial 1971): each one gets closer to d, so an
                    # ant can neither loop nor end in a dead end
                    if mark[v] == stamp or h[di, v] >= h[di, u] - 1e-9 or m >= 64:
                        continue
                    excess = cost[a] + h[di, v] - h[di, u]
                    w = tau[di, a] ** alpha * np.exp(-beta * max(excess, 0.0) / scale)
                    weights[m] = w
                    arcs[m] = a
                    wsum += w
                    m += 1
                if m == 0 or wsum <= 0.0:
                    ok = False
                    break
                r = np.random.random() * wsum  # noqa: NPY002
                k = 0
                acc = weights[0]
                while acc < r and k < m - 1:
                    k += 1
                    acc += weights[k]
                a = arcs[k]
                path[steps] = a
                steps += 1
                total += cost[a]
                u = arc_v[a]
                mark[u] = stamp
            if not ok:
                fails += 1
                stamp += 1
                mark[o] = stamp
                steps, total = _greedy(
                    o, di, out_ptr, out_arc, arc_v, cost, h, stamp, mark, path, max_steps
                )
                if steps < 0:
                    ant_id += 1
                    continue
            dep = (sp / total if total > 0 else 1.0) / n_ants
            for s in range(steps):
                a = path[s]
                y[a] += share
                deposit[di, a] += dep
            slot = record[ant_id] if ant_id < len(record) else -1
            if slot >= 0:
                rec_nodes[slot, 0] = o
                for s in range(steps):
                    rec_nodes[slot, s + 1] = arc_v[path[s]]
                rec_len[slot] = steps + 1
            ant_id += 1
    return y, deposit, fails


@njit(cache=True)
def _aon(origin, dest_index, n_people, out_ptr, out_arc, arc_v, cost, h, max_steps):
    """All-or-nothing: every pair on its shortest path under ``cost``."""
    n_nodes = len(out_ptr) - 1
    y = np.zeros(len(cost))
    mark = np.zeros(n_nodes, np.int64)
    path = np.empty(max_steps, np.int32)
    for p in range(len(origin)):
        mark[origin[p]] = p + 1
        steps, _ = _greedy(
            origin[p], dest_index[p], out_ptr, out_arc, arc_v, cost, h, p + 1, mark, path, max_steps
        )
        for s in range(max(steps, 0)):
            y[path[s]] += n_people[p]
    return y


# ---------------------------------------------------------------- assignments


def _max_steps(net: WalkNet) -> int:
    return min(4000, net.n_nodes)


def _row(it: int, net: WalkNet, demand: PeakDemand, x: np.ndarray, y_total: float, cfg: dict):
    cost = arc_costs(net, x, cfg)
    h = dest_times(net, cost, demand.dest_nodes)
    tt = total_time(x, cost)
    sp = shortest_total(demand, h)
    ratio = edge_flow(x) / net.cap
    row = {
        "iteration": it,
        "total_s": tt,
        "mean_s": tt / demand.people,
        "iter_total_s": y_total,
        "gap": (tt - sp) / tt if tt > 0 else 0.0,
        "max_ratio": float(ratio.max()),
        "n_over": int((ratio > 1).sum()),
    }
    return row, cost, h


def aon(net: WalkNet, demand: PeakDemand, cfg: dict, cost: np.ndarray | None = None) -> Assignment:
    """Everybody on the free-flow shortest path (or the shortest under ``cost``)."""
    c = net.arc_t0 if cost is None else cost
    h = dest_times(net, c, demand.dest_nodes)
    x = _aon(
        demand.origin,
        demand.dest_index,
        demand.n,
        net.out_ptr,
        net.out_arc,
        net.arc_v,
        c,
        h,
        _max_steps(net),
    )
    row, cost_x, _ = _row(0, net, demand, x, 0.0, cfg)
    return Assignment("aon", x, cost_x, row["total_s"], row["gap"], [row])


def run_msa(
    net: WalkNet, demand: PeakDemand, cfg: dict, n_iterations: int | None = None
) -> Assignment:
    """Method of successive averages with all-or-nothing loading (equilibrium reference)."""
    n_it = int(n_iterations or cfg["walk_aco"]["n_iterations"])
    x = aon(net, demand, cfg).x_arc
    curve = []
    cost = arc_costs(net, x, cfg)
    for it in range(1, n_it + 1):
        h = dest_times(net, cost, demand.dest_nodes)
        y = _aon(
            demand.origin,
            demand.dest_index,
            demand.n,
            net.out_ptr,
            net.out_arc,
            net.arc_v,
            cost,
            h,
            _max_steps(net),
        )
        x = x + (y - x) / (it + 1)
        row, cost, _ = _row(it, net, demand, x, total_time(y, cost), cfg)
        curve.append(row)
    return Assignment("msa", x, cost, curve[-1]["total_s"], curve[-1]["gap"], curve)


def run_walk_aco(
    net: WalkNet, demand: PeakDemand, cfg: dict, seed: int = 42, trace: bool = True
) -> Assignment:
    """The colony (module docstring). ``trace``: flows, pheromone and some ants per sample."""
    wc = cfg["walk_aco"]
    n_it = int(wc["n_iterations"])
    n_ants = int(wc["n_ants"])
    rho = float(wc["rho"])
    tmin, tmax = float(wc["tau_min"]), float(wc["tau_max"])
    every = int(wc["trace"]["every"])
    keep = int(wc["trace"]["max_ants"])
    rng = np.random.default_rng(seed)
    max_steps = _max_steps(net)
    n_total_ants = len(demand.origin) * n_ants

    tau = np.ones((len(demand.dest_nodes), 2 * net.n_edges))
    cost = net.arc_t0.copy()
    h = dest_times(net, cost, demand.dest_nodes)
    x = np.zeros_like(cost)
    curve: list[dict] = []
    samples: dict[str, list] = {
        "iterations": [],
        "flow": [],
        "ratio": [],
        "pheromone": [],
        "ants": [],
    }
    dest_w = np.bincount(demand.dest_index, weights=demand.n, minlength=len(demand.dest_nodes))
    dest_w = dest_w / dest_w.sum()

    for it in range(n_it):
        sampled = trace and (it % every == 0 or it == n_it - 1)
        record = np.full(n_total_ants, -1, np.int32)
        if sampled:
            chosen = rng.choice(n_total_ants, size=min(keep, n_total_ants), replace=False)
            record[chosen] = np.arange(len(chosen), dtype=np.int32)
        rec_nodes = np.zeros((keep, max_steps + 1), np.int32)
        rec_len = np.zeros(keep, np.int32)
        y, deposit, fails = _ants(
            demand.origin, demand.dest_index, demand.n, net.out_ptr, net.out_arc, net.arc_v,
            cost, h, tau, n_ants, float(wc["alpha"]), float(wc["beta"]),
            float(wc["detour_scale_s"]), max_steps, int(rng.integers(2**31)),
            record, rec_nodes, rec_len,
        )  # fmt: skip
        y_total = total_time(y, cost)
        x = y if it == 0 else x + (y - x) / (it + 1)
        tau = np.clip((1 - rho) * tau + deposit, tmin, tmax)
        row, cost, h = _row(it, net, demand, x, y_total, cfg)
        row["fails"] = int(fails)
        curve.append(row)
        if sampled:
            samples["iterations"].append(it)
            samples["flow"].append(edge_flow(x).astype(np.float32))
            samples["ratio"].append((edge_flow(x) / net.cap).astype(np.float32))
            vis = np.tensordot(dest_w, (tau - tmin) / (tmax - tmin), axes=1)
            samples["pheromone"].append(np.maximum(vis[0::2], vis[1::2]).astype(np.float32))
            samples["ants"].append(
                [rec_nodes[s, : rec_len[s]].copy() for s in range(keep) if rec_len[s] > 0]
            )
    out = Assignment("aco", x, cost, curve[-1]["total_s"], curve[-1]["gap"], curve)
    out.trace = samples if trace else None
    return out


def summary(net: WalkNet, demand: PeakDemand, a: Assignment) -> dict:
    ratio = edge_flow(a.x_arc) / net.cap
    return {
        "assignment": a.name,
        "total_s": a.total_s,
        "mean_s": a.total_s / demand.people,
        "gap": a.gap,
        "max_ratio": float(ratio.max()),
        "n_over": int((ratio > 1).sum()),
        "n_loaded": int((ratio > 0).sum()),
    }

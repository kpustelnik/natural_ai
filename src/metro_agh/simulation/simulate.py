"""Every leg of every student, without and with the metro (docs/data_contracts.md, section 9).

Deterministic shortest walks on the walk graph (``network/*.parquet``, times per direction);
in the ``metro`` scenario a leg takes the train only when the real timetable
(``schedule.parquet``) gets the student there earlier than walking. With ``transit``
(GTFS rides between campus stops) both scenarios may also take a bus or tram the same
way, so ``no_metro`` is "walk or public transport", the fair baseline. No congestion, no
vehicle capacity.

Departure rule (9.2): ``class_to_class`` and ``class_to_home`` legs leave at
``earliest_depart_wt`` and arrive as early as they can; ``home_to_class`` legs aim at
``deadline - arrival_buffer_s`` and leave as late as they can (so the metro is taken when it
lets the student leave later). A metro leg walks to the platform of station i (through the
shaft, which is in the graph), waits for the first train that reaches station j, rides, and
walks from platform j. Its ``path_nodes`` are the walk in, then platform i -> platform j,
then the walk out.

Dijkstra runs once per distinct origin, in batches, so the predecessor arrays of a large
indoor graph never have to be in memory all at once.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from ..schemas.tables import SIM_LEGS

log = logging.getLogger(__name__)

BATCH = 256  # origins per Dijkstra call
DAY_S = 24 * 3600
EPS_S = 1e-3  # scipy drops explicit zeros: every edge costs at least this


def walk_matrix(nodes: pd.DataFrame, edges: pd.DataFrame) -> csr_matrix:
    """Directed graph: u -> v costs time_uv_s, v -> u costs time_vu_s."""
    return csr_walk(len(nodes), edges.u.to_numpy(), edges.v.to_numpy(),
                    edges.time_uv_s.to_numpy(), edges.time_vu_s.to_numpy())  # fmt: skip


def csr_walk(n: int, u, v, time_uv, time_vu) -> csr_matrix:
    """``walk_matrix`` from plain arrays (also the exported network.bin)."""
    rows = np.concatenate([u, v])
    cols = np.concatenate([v, u])
    w = np.concatenate([np.asarray(time_uv, float), np.asarray(time_vu, float)]) + EPS_S
    keep = rows != cols
    # parallel edges were merged by the builder; keep the shorter one if any slipped through
    df = pd.DataFrame({"r": rows[keep], "c": cols[keep], "w": w[keep]})
    df = df.groupby(["r", "c"], as_index=False).w.min()
    return csr_matrix((df.w.to_numpy(), (df.r.to_numpy(), df.c.to_numpy())), shape=(n, n))


def _path(pred: np.ndarray, src: int, dst: int) -> np.ndarray:
    out = [dst]
    while out[-1] != src:
        p = int(pred[out[-1]])
        if p < 0:
            raise ValueError(f"no path {src} -> {dst}")
        out.append(p)
    return np.array(out[::-1], np.int32)


class PathPool:
    """Distinct node sequences, stored once; legs refer to them by index."""

    def __init__(self) -> None:
        self.index: dict[tuple[int, int], int] = {}
        self.paths: list[np.ndarray] = []

    def get(self, key: tuple[int, int], make) -> int:
        i = self.index.get(key)
        if i is None:
            i = self.index[key] = len(self.paths)
            self.paths.append(make())
        return i


@dataclass
class Connections:
    """Train connections station i -> station j of one timetable, for both queries."""

    dep: np.ndarray  # departures from i, sorted
    best_arr: np.ndarray  # earliest arrival at j among trains leaving at dep[n:] (suffix min)
    best_dep: np.ndarray  # departure of that train
    arr_sorted: np.ndarray  # arrivals at j, sorted
    late_dep: np.ndarray  # latest departure among trains arriving by arr_sorted[:n+1]
    late_arr: np.ndarray  # arrival of that train

    @classmethod
    def build(cls, dep: np.ndarray, arr: np.ndarray) -> "Connections":
        o = np.argsort(dep, kind="stable")
        d, a = dep[o], arr[o]
        # suffix minimum of the arrival, with the departure that achieves it
        best_i = np.arange(len(a))
        for n in range(len(a) - 2, -1, -1):
            if a[best_i[n + 1]] < a[n]:
                best_i[n] = best_i[n + 1]
        o2 = np.argsort(arr, kind="stable")
        d2, a2 = dep[o2], arr[o2]
        late_i = np.arange(len(a2))
        for n in range(1, len(a2)):
            if d2[late_i[n - 1]] >= d2[n]:  # a tie: the earlier arrival, already kept
                late_i[n] = late_i[n - 1]
        return cls(d, a[best_i], d[best_i], a2, d2[late_i], a2[late_i])

    def earliest(self, ready: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(departure, arrival) of the first useful train for students ready at ``ready``."""
        n = np.searchsorted(self.dep, ready, side="left")
        ok = n < len(self.dep)
        n = np.minimum(n, len(self.dep) - 1)
        return np.where(ok, self.best_dep[n], np.inf), np.where(ok, self.best_arr[n], np.inf)

    def latest(self, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(departure, arrival) of the latest-leaving train arriving by ``target``."""
        n = np.searchsorted(self.arr_sorted, target, side="right") - 1
        ok = n >= 0
        n = np.maximum(n, 0)
        return np.where(ok, self.late_dep[n], -np.inf), np.where(ok, self.late_arr[n], -np.inf)


def loop_successors(schedule: pd.DataFrame) -> dict[int, int]:
    """Loop runs: run_id -> the next run of the same direction and weekday leaving station 0
    once this one is back there. A rider passing station 0 stays on (or changes on the
    platform) into it, so the loop serves every pair the short way round, as the objective
    assumes."""
    first = schedule[schedule.stop_seq == 0].set_index("run_id").depart_wt
    last = schedule.sort_values("stop_seq").groupby("run_id").arrive_wt.last()
    runs = schedule.drop_duplicates("run_id").set_index("run_id")[["weekday", "direction"]]
    runs = runs.assign(dep=first, back=last).sort_values("dep")
    out = {}
    for _, g in runs.groupby(["weekday", "direction"]):
        n = np.searchsorted(g.dep.to_numpy(), g.back.to_numpy(), side="left")
        out.update({int(r): int(g.index[i]) for r, i in zip(g.index, n, strict=True) if i < len(g)})
    return out


def connections(
    schedule: pd.DataFrame, stations: list[str], topology: str = "line"
) -> dict[tuple[int, int], Connections]:
    """Every (board, alight) pair any run serves, over the whole week; on a loop also the
    rides through station 0 into the next run (``loop_successors``)."""
    idx = {s: i for i, s in enumerate(stations)}
    pairs: dict[tuple[int, int], tuple[list, list]] = {}
    s = schedule.sort_values(["run_id", "stop_seq"])
    st = s.station.map(idx).to_numpy()
    arr, dep = s.arrive_wt.to_numpy(float), s.depart_wt.to_numpy(float)
    run_ids = s.run_id.to_numpy()
    bounds = np.flatnonzero(np.diff(run_ids)) + 1
    starts, ends = np.r_[0, bounds], np.r_[bounds, len(s)]
    spans = dict(zip(run_ids[starts], zip(starts, ends, strict=True), strict=True))
    succ = loop_successors(schedule) if topology == "loop" else {}

    def add(a: int, b: int) -> None:
        p = pairs.setdefault((int(st[a]), int(st[b])), ([], []))
        p[0].append(dep[a])
        p[1].append(arr[b])

    for run, (lo, hi) in spans.items():
        for a in range(lo, hi):
            for b in range(a + 1, hi):
                if st[a] != st[b]:
                    add(a, b)
        if run in succ:
            # board at stop i of this run (not station 0), alight at stop j < i of the next
            lo2 = spans[succ[run]][0]
            for a in range(lo + 1, hi - 1):
                for b in range(lo2 + 1, lo2 + (a - lo)):
                    add(a, b)
    return {k: Connections.build(np.array(d), np.array(a)) for k, (d, a) in pairs.items()}


@dataclass
class Line:
    stations: list[str]
    topology: str
    schedule: pd.DataFrame  # tables.METRO_SCHEDULE


@dataclass
class Transit:
    """Buses and trams between campus stops: every direct ride of one GTFS weekday
    (``tables.TRANSIT_TRIPS``), repeated on every simulated weekday."""

    stops: list[str]
    trips: pd.DataFrame

    def connections(self, weekdays: list[int]) -> dict[tuple[int, int], "Connections"]:
        idx = {s: i for i, s in enumerate(self.stops)}
        t = self.trips[self.trips.from_stop.isin(idx) & self.trips.to_stop.isin(idx)]
        out = {}
        for (a, b), g in t.groupby(["from_stop", "to_stop"]):
            dep = np.concatenate([(d - 1) * DAY_S + g.dep_s.to_numpy(float) for d in weekdays])
            arr = np.concatenate([(d - 1) * DAY_S + g.arr_s.to_numpy(float) for d in weekdays])
            out[(idx[a], idx[b])] = Connections.build(dep, arr)
        return out


@dataclass
class _Net:
    """A timetabled network the simulation can board: the metro line or the buses."""

    mode: str
    names: list[str]  # station building ids / stop ids
    nodes: np.ndarray  # graph node of each (platform / stop)
    conns: dict[tuple[int, int], Connections]
    egress_t: np.ndarray  # (k, n_nodes) walk from each station
    egress_pred: np.ndarray


FIELDS = ("depart", "arrive", "board", "alight", "access", "egress", "dep", "arr")


def _best_rides(net: _Net, acc, egr, earliest, target, bw) -> dict[str, np.ndarray]:
    """For each leg of a batch, the best (board i, alight j) of ``net``: earliest arrival,
    or for legs from home (``bw``) the latest departure that is still on time."""
    n = len(bw)
    r = {f: np.full(n, np.nan) for f in FIELDS}
    r["board"], r["alight"] = np.full(n, -1), np.full(n, -1)
    best = np.where(bw, -np.inf, np.inf)
    for (i, j), c in net.conns.items():
        fwd_dep, fwd_arr = c.earliest(earliest + acc[:, i])
        bwd_dep, bwd_arr = c.latest(target - egr[:, j])
        dep = np.where(bw, bwd_dep, fwd_dep)
        arr = np.where(bw, bwd_arr, fwd_arr)
        depart = np.where(bw, dep - acc[:, i], earliest)
        arrive = arr + egr[:, j]
        better = np.where(bw, depart > best, arrive < best)
        better &= np.isfinite(depart) & np.isfinite(arrive)
        if not better.any():
            continue
        best = np.where(better, np.where(bw, depart, arrive), best)
        r["depart"][better], r["arrive"][better] = depart[better], arrive[better]
        r["board"][better], r["alight"][better] = i, j
        r["access"][better], r["egress"][better] = acc[better, i], egr[better, j]
        r["dep"][better], r["arr"][better] = dep[better], arr[better]
    return r


def _net(mode, names, nodes, conns, graph) -> _Net:
    egress_t, egress_pred = dijkstra(graph, indices=nodes, return_predecessors=True)
    return _Net(mode, names, np.asarray(nodes), conns, egress_t, egress_pred)


def simulate(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    legs: pd.DataFrame,
    line: Line | None,
    cfg: dict,
    transit: Transit | None = None,
) -> dict[str, pd.DataFrame]:
    """``tables.SIM_LEGS`` for ``no_metro`` and, with a line, ``metro``. With ``transit``
    both scenarios may also ride a bus or tram between campus stops."""
    buffer = float(cfg["demand"]["arrival_buffer_s"])
    graph = walk_matrix(nodes, edges)
    node_of = {
        str(k): int(i)
        for k, i in zip(nodes.endpoint_key, nodes.node_id, strict=True)
        if isinstance(k, str)
    }
    unknown = sorted((set(legs.from_key) | set(legs.to_key)) - set(node_of))
    if unknown:
        raise ValueError(f"{len(unknown)} endpoint keys not in the graph, e.g. {unknown[:5]}")
    legs = legs.sort_values("leg_id").reset_index(drop=True)
    src = legs.from_key.map(node_of).to_numpy()
    dst = legs.to_key.map(node_of).to_numpy()
    backward = (legs.kind == "home_to_class").to_numpy()
    deadline = legs.deadline_wt.to_numpy(float, na_value=np.nan)
    earliest = legs.earliest_depart_wt.to_numpy(float, na_value=np.nan)
    target = deadline - buffer  # home_to_class only

    key_to_id = dict(zip(nodes.key, nodes.node_id, strict=True))
    nets: list[_Net] = []
    if transit is not None:
        stops = [s for s in transit.stops if s in key_to_id]
        weekdays = sorted({int(d) for d in legs.weekday.unique()}) or [1, 2, 3, 4, 5]
        conns = Transit(stops, transit.trips).connections(weekdays)
        if conns:
            nodes_ = [key_to_id[s] for s in stops]
            nets.append(_net("transit", stops, nodes_, conns, graph))
    if line:
        missing = [s for s in line.stations if f"{s}:platform" not in key_to_id]
        if missing:
            raise ValueError(f"stations without a metro shaft in the graph: {missing}")
        platforms = [key_to_id[f"{s}:platform"] for s in line.stations]
        conns = connections(line.schedule, line.stations, line.topology)
        nets.append(_net("metro", line.stations, platforms, conns, graph))
    scenarios = {"no_metro": [n for n in nets if n.mode != "metro"]}
    if line:
        scenarios["metro"] = nets

    n = len(legs)
    walk_s = np.full(n, np.nan)
    ride = {net.mode: {f: np.full(n, np.nan) for f in FIELDS} for net in nets}
    choice = {sc: np.full(n, "walk", dtype=object) for sc in scenarios}
    in_path = {sc: np.full(n, -1) for sc in scenarios}
    out_path = {sc: np.full(n, -1) for sc in scenarios}
    pool = PathPool()
    walk_path = np.full(n, -1)

    origins = np.unique(src)
    for b0 in range(0, len(origins), BATCH):
        batch = origins[b0 : b0 + BATCH]
        dist, pred = dijkstra(graph, indices=batch, return_predecessors=True)
        row_of = {int(o): r for r, o in enumerate(batch)}
        sel = np.flatnonzero(np.isin(src, batch))
        rows = np.array([row_of[int(o)] for o in src[sel]])
        w = dist[rows, dst[sel]]
        if not np.isfinite(w).all():
            bad = legs.iloc[sel[~np.isfinite(w)][0]]
            raise ValueError(f"no walk path {bad.from_key} -> {bad.to_key}")
        walk_s[sel] = w
        for leg, r in zip(sel, rows, strict=True):
            o, d = int(src[leg]), int(dst[leg])
            walk_path[leg] = pool.get((o, d), lambda p=pred[r], o=o, d=d: _path(p, o, d))
        if not nets:
            continue

        bw = backward[sel]
        options = {}
        for net in nets:
            acc = dist[:, net.nodes][rows]  # (L, k)
            egr = net.egress_t[:, dst[sel]].T  # (L, k)
            options[net.mode] = _best_rides(net, acc, egr, earliest[sel], target[sel], bw)
            for f in FIELDS:
                ride[net.mode][f][sel] = options[net.mode][f]
        walk_dep = np.where(bw, target[sel] - walk_s[sel], earliest[sel])
        walk_arr = walk_dep + walk_s[sel]
        by_mode = {net.mode: net for net in nets}
        for sc, usable in scenarios.items():
            # walking, then each network in turn when it is strictly better
            best_dep, best_arr = walk_dep.copy(), walk_arr.copy()
            mode = np.full(len(sel), "walk", dtype=object)
            for net in usable:
                o_ = options[net.mode]
                ok = np.isfinite(o_["depart"]) & np.isfinite(o_["arrive"])
                wins = ok & np.where(bw, o_["depart"] > best_dep, o_["arrive"] < best_arr)
                mode[wins] = net.mode
                best_dep[wins], best_arr[wins] = o_["depart"][wins], o_["arrive"][wins]
            choice[sc][sel] = mode
            for k in np.flatnonzero(mode != "walk"):
                leg, r, net = sel[k], rows[k], by_mode[mode[k]]
                i, j = int(options[net.mode]["board"][k]), int(options[net.mode]["alight"][k])
                o, p_i, p_j, d = int(src[leg]), int(net.nodes[i]), int(net.nodes[j]), int(dst[leg])
                in_path[sc][leg] = pool.get(
                    (o, p_i), lambda p=pred[r], o=o, p_i=p_i: _path(p, o, p_i)
                )
                out_path[sc][leg] = pool.get(
                    (p_j, d), lambda e=net.egress_pred[j], p_j=p_j, d=d: _path(e, p_j, d)
                )
        del dist, pred

    base = legs[["leg_id", "student_id"]].copy()
    walk_dep = np.where(backward, target - walk_s, earliest)
    by_mode = {net.mode: net for net in nets}
    out = {}
    for sc in scenarios:
        df = _walk_legs(base, walk_dep, walk_s, deadline, walk_path, pool, scenario=sc)
        paths = list(df.path_nodes)
        for mode, net in by_mode.items():
            on = choice[sc] == mode
            if not on.any():
                continue
            r = {f: ride[mode][f][on] for f in FIELDS}
            df.loc[on, "mode"] = mode
            df.loc[on, "depart_wt"] = np.round(r["depart"]).astype(np.int64)
            df.loc[on, "arrive_wt"] = np.round(r["arrive"]).astype(np.int64)
            df.loc[on, "walk_s"] = r["access"] + r["egress"]
            df.loc[on, "wait_s"] = r["dep"] - (r["depart"] + r["access"])
            df.loc[on, "ride_s"] = r["arr"] - r["dep"]
            df.loc[on, "board_station"] = [net.names[int(i)] for i in r["board"]]
            df.loc[on, "alight_station"] = [net.names[int(j)] for j in r["alight"]]
            for leg in np.flatnonzero(on):
                paths[leg] = np.concatenate(
                    [pool.paths[in_path[sc][leg]], pool.paths[out_path[sc][leg]]]
                )
        df["path_nodes"] = paths
        arrive_wt = df.arrive_wt.to_numpy(float)
        df["late_s"] = np.where(np.isnan(deadline), 0.0, np.maximum(0.0, arrive_wt - deadline))
        out[sc] = df
        shares = {m: float((choice[sc] == m).mean()) for m in ("walk", *by_mode)}
        log.info(
            "%s: %s of %d legs", sc, ", ".join(f"{m} {100 * v:.1f}%" for m, v in shares.items()), n
        )
    for df in out.values():
        SIM_LEGS.validate(df)
    return out


def _walk_legs(
    base: pd.DataFrame,
    depart: np.ndarray,
    walk_s: np.ndarray,
    deadline: np.ndarray,
    walk_path: np.ndarray,
    pool: PathPool,
    scenario: str = "no_metro",
) -> pd.DataFrame:
    arrive = depart + walk_s
    df = base.copy()
    df["scenario"] = scenario
    df["mode"] = "walk"
    df["depart_wt"] = np.round(depart).astype(np.int64)
    df["arrive_wt"] = np.round(arrive).astype(np.int64)
    df["walk_s"] = walk_s
    df["wait_s"] = 0.0
    df["ride_s"] = 0.0
    df["board_station"] = pd.Series([None] * len(df), dtype=object)
    df["alight_station"] = pd.Series([None] * len(df), dtype=object)
    df["late_s"] = np.where(np.isnan(deadline), 0.0, np.maximum(0.0, arrive - deadline))
    df["path_nodes"] = [pool.paths[p] for p in walk_path]
    return df


def run_simulation(processed: Path, best_line: Path, cfg: dict) -> dict[str, pd.DataFrame]:
    """Stage 5 on the files of one ``processed`` dir: network/, demand/legs.parquet and the
    line in ``best_line`` (and transit/trips.parquet when ``simulation.transit``). Writes
    simulation/metro/schedule.parquet and simulation/<scenario>/legs.parquet."""
    from ..schemas.results import BestLine, load_json
    from ..schemas.tables import GRAPH_EDGES, GRAPH_NODES, LEGS, METRO_SCHEDULE
    from .schedule import build_schedule

    processed = Path(processed)
    nodes = GRAPH_NODES.read(processed / GRAPH_NODES.path)
    edges = GRAPH_EDGES.read(processed / GRAPH_EDGES.path)
    legs = LEGS.read(processed / LEGS.path)
    best: BestLine = load_json(BestLine, best_line)
    at = nodes.set_index("key")
    missing = [s for s in best.stations if f"{s}:platform" not in at.index]
    if missing:
        raise ValueError(f"stations without a metro shaft in the graph: {missing}")
    xy = np.array([[at.x[f"{s}:platform"], at.y[f"{s}:platform"]] for s in best.stations])
    schedule = build_schedule(best.stations, xy, best.topology, cfg)
    METRO_SCHEDULE.write(schedule, processed / METRO_SCHEDULE.path)
    transit = load_transit(processed, nodes, cfg)
    line = Line(best.stations, best.topology, schedule)
    sims = simulate(nodes, edges, legs, line, cfg, transit=transit)
    for sc, df in sims.items():
        SIM_LEGS.write(df, processed / SIM_LEGS.path.format(scenario=sc))
    return sims


def load_transit(processed: Path, nodes: pd.DataFrame, cfg: dict) -> Transit | None:
    """Buses and trams of ``transit/trips.parquet`` between the stops of the graph, when
    ``simulation.transit`` is on and the file exists (``01_fetch_transit.py``)."""
    from ..schemas.tables import TRANSIT_TRIPS

    if not cfg.get("simulation", {}).get("transit", True):
        return None
    f = Path(processed) / TRANSIT_TRIPS.path
    if not f.exists():
        log.warning("%s missing: no buses or trams in the simulation", f)
        return None
    stops = sorted(k for k in nodes.key if isinstance(k, str) and k.startswith("stop:"))
    return Transit(stops, TRANSIT_TRIPS.read(f))

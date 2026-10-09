"""Every leg of every student, without and with the metro (docs/data_contracts.md, section 9).

Deterministic shortest walks on the walk graph (``network/*.parquet``, times per direction);
in the ``metro`` scenario a leg takes the train only when the real timetable
(``schedule.parquet``) gets the student there earlier than walking. No congestion, no
train capacity.

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
EPS_S = 1e-3  # scipy drops explicit zeros: every edge costs at least this


def walk_matrix(nodes: pd.DataFrame, edges: pd.DataFrame) -> csr_matrix:
    """Directed graph: u -> v costs time_uv_s, v -> u costs time_vu_s."""
    n = len(nodes)
    u, v = edges.u.to_numpy(), edges.v.to_numpy()
    rows = np.concatenate([u, v])
    cols = np.concatenate([v, u])
    w = np.concatenate([edges.time_uv_s.to_numpy(), edges.time_vu_s.to_numpy()]) + EPS_S
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
            if d2[late_i[n - 1]] > d2[n]:
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


def connections(schedule: pd.DataFrame, stations: list[str]) -> dict[tuple[int, int], Connections]:
    """Every (board, alight) pair any run serves, over the whole week."""
    idx = {s: i for i, s in enumerate(stations)}
    pairs: dict[tuple[int, int], tuple[list, list]] = {}
    s = schedule.sort_values(["run_id", "stop_seq"])
    st = s.station.map(idx).to_numpy()
    arr, dep = s.arrive_wt.to_numpy(float), s.depart_wt.to_numpy(float)
    bounds = np.flatnonzero(np.diff(s.run_id.to_numpy())) + 1
    for lo, hi in zip(np.r_[0, bounds], np.r_[bounds, len(s)], strict=True):
        for a in range(lo, hi):
            for b in range(a + 1, hi):
                if st[a] != st[b]:
                    p = pairs.setdefault((int(st[a]), int(st[b])), ([], []))
                    p[0].append(dep[a])
                    p[1].append(arr[b])
    return {k: Connections.build(np.array(d), np.array(a)) for k, (d, a) in pairs.items()}


@dataclass
class Line:
    stations: list[str]
    topology: str
    schedule: pd.DataFrame  # tables.METRO_SCHEDULE


def simulate(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    legs: pd.DataFrame,
    line: Line | None,
    cfg: dict,
) -> dict[str, pd.DataFrame]:
    """``tables.SIM_LEGS`` for ``no_metro`` and, with a line, ``metro``."""
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

    # stations: platform nodes, and the walk from every platform (egress) once
    if line:
        key_to_id = dict(zip(nodes.key, nodes.node_id, strict=True))
        missing = [s for s in line.stations if f"{s}:platform" not in key_to_id]
        if missing:
            raise ValueError(f"stations without a metro shaft in the graph: {missing}")
        platforms = np.array([key_to_id[f"{s}:platform"] for s in line.stations])
        egress_t, egress_pred = dijkstra(graph, indices=platforms, return_predecessors=True)
        conns = connections(line.schedule, line.stations)
    n = len(legs)
    walk_s = np.full(n, np.nan)
    m = {  # metro option per leg (the best pair)
        "depart": np.full(n, np.nan), "arrive": np.full(n, np.nan), "board": np.full(n, -1),
        "alight": np.full(n, -1), "access": np.zeros(n), "egress": np.zeros(n),
        "dep": np.zeros(n), "arr": np.zeros(n),
    }  # fmt: skip
    pool = PathPool()
    walk_path = np.full(n, -1)
    in_path, out_path = np.full(n, -1), np.full(n, -1)

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
        if not line:
            continue

        # metro: the best (board i, alight j) pair for every leg of this batch
        acc = dist[:, platforms][rows]  # (L, k)
        egr = egress_t[:, dst[sel]].T  # (L, k)
        bw = backward[sel]
        best = np.where(bw, -np.inf, np.inf)
        for (i, j), c in conns.items():
            fwd_dep, fwd_arr = c.earliest(earliest[sel] + acc[:, i])
            bwd_dep, bwd_arr = c.latest(target[sel] - egr[:, j])
            dep = np.where(bw, bwd_dep, fwd_dep)
            arr = np.where(bw, bwd_arr, fwd_arr)
            depart = np.where(bw, dep - acc[:, i], earliest[sel])
            arrive = arr + egr[:, j]
            better = np.where(bw, depart > best, arrive < best)
            better &= np.isfinite(depart) & np.isfinite(arrive)
            if not better.any():
                continue
            best = np.where(better, np.where(bw, depart, arrive), best)
            ix = sel[better]
            m["depart"][ix], m["arrive"][ix] = depart[better], arrive[better]
            m["board"][ix], m["alight"][ix] = i, j
            m["access"][ix], m["egress"][ix] = acc[better, i], egr[better, j]
            m["dep"][ix], m["arr"][ix] = dep[better], arr[better]

        # paths only for the legs where the metro beats walking
        walk_dep = np.where(bw, target[sel] - walk_s[sel], earliest[sel])
        walk_arr = walk_dep + walk_s[sel]
        md, ma = m["depart"][sel], m["arrive"][sel]
        wins = np.where(bw, md > walk_dep, ma < walk_arr) & np.isfinite(md)
        for leg, r in zip(sel[wins], rows[wins], strict=True):
            o, i, j = int(src[leg]), int(m["board"][leg]), int(m["alight"][leg])
            p_i, d = int(platforms[i]), int(dst[leg])
            in_path[leg] = pool.get((o, p_i), lambda p=pred[r], o=o, p_i=p_i: _path(p, o, p_i))
            out_path[leg] = pool.get(
                (int(platforms[j]), d),
                lambda j=j, d=d: _path(egress_pred[j], int(platforms[j]), d),
            )
        del dist, pred

    base = legs[["leg_id", "student_id"]].copy()
    walk_dep = np.where(backward, target - walk_s, earliest)
    out = {"no_metro": _walk_legs(base, walk_dep, walk_s, deadline, walk_path, pool)}
    if line:
        metro = in_path >= 0
        df = _walk_legs(base, walk_dep, walk_s, deadline, walk_path, pool, scenario="metro")
        depart, arrive = m["depart"][metro], m["arrive"][metro]
        df.loc[metro, "mode"] = "metro"
        df.loc[metro, "depart_wt"] = np.round(depart).astype(np.int64)
        df.loc[metro, "arrive_wt"] = np.round(arrive).astype(np.int64)
        df.loc[metro, "walk_s"] = m["access"][metro] + m["egress"][metro]
        df.loc[metro, "wait_s"] = m["dep"][metro] - (depart + m["access"][metro])
        df.loc[metro, "ride_s"] = m["arr"][metro] - m["dep"][metro]
        df.loc[metro, "board_station"] = [line.stations[i] for i in m["board"][metro]]
        df.loc[metro, "alight_station"] = [line.stations[j] for j in m["alight"][metro]]
        arrive_wt = df.arrive_wt.to_numpy(float)
        df["late_s"] = np.where(np.isnan(deadline), 0.0, np.maximum(0.0, arrive_wt - deadline))
        paths = list(df.path_nodes)
        for leg in np.flatnonzero(metro):
            paths[leg] = np.concatenate([pool.paths[in_path[leg]], pool.paths[out_path[leg]]])
        df["path_nodes"] = paths
        out["metro"] = df
        log.info(
            "metro scenario: %d of %d legs (%.1f%%) take the train",
            metro.sum(), n, 100 * metro.mean(),
        )  # fmt: skip
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
    line in ``best_line``. Writes simulation/metro/schedule.parquet and
    simulation/<scenario>/legs.parquet."""
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
    sims = simulate(nodes, edges, legs, Line(best.stations, best.topology, schedule), cfg)
    for sc, df in sims.items():
        SIM_LEGS.write(df, processed / SIM_LEGS.path.format(scenario=sc))
    return sims

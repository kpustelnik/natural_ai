"""Weekly demand heatmap for the viewer: ``demand/od.parquet`` -> ``demand.json``.

Each OD pair is routed on the walk graph in ``web/public/data/network.json`` (same
polylines the viewer draws). ``n_legs`` is added to every undirected edge on that
shortest path. Indices match ``NetworkHeader`` edge order.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from ..config import provenance
from ..schemas.tables import OD
from ..schemas.web import Demand, EdgeLoad, NetworkHeader
from ..simulation.simulate import BATCH, EPS_S, _path
from .export_campus import GENERATOR

log = logging.getLogger(__name__)


def _buf(header: NetworkHeader, raw: bytes, name: str) -> np.ndarray:
    v = header.buffers[name]
    return np.frombuffer(raw, dtype=v.dtype, count=v.count, offset=v.offset).reshape(v.shape)


def load_web_graph(out_dir: Path) -> tuple[NetworkHeader, csr_matrix, dict[tuple[int, int], int]]:
    """CSR walk times + undirected (u,v)->edge index from the exported network files."""
    out_dir = Path(out_dir)
    header = NetworkHeader.model_validate_json(
        (out_dir / "network.json").read_text(encoding="utf-8")
    )
    raw = (out_dir / header.bin).read_bytes()
    pairs = _buf(header, raw, "edge_nodes").astype(np.int32)
    time_uv = _buf(header, raw, "time_uv_s").astype(np.float64)
    time_vu = _buf(header, raw, "time_vu_s").astype(np.float64)
    n = header.n_nodes
    u, v = pairs[:, 0], pairs[:, 1]
    rows = np.concatenate([u, v])
    cols = np.concatenate([v, u])
    w = np.concatenate([time_uv, time_vu]) + EPS_S
    keep = rows != cols
    df = pd.DataFrame({"r": rows[keep], "c": cols[keep], "w": w[keep]})
    df = df.groupby(["r", "c"], as_index=False).w.min()
    mat = csr_matrix((df.w.to_numpy(), (df.r.to_numpy(), df.c.to_numpy())), shape=(n, n))
    edge_of: dict[tuple[int, int], int] = {}
    for i, (a, b) in enumerate(pairs):
        edge_of[(int(a), int(b))] = i
        edge_of[(int(b), int(a))] = i
    return header, mat, edge_of


def edge_loads_from_od(
    header: NetworkHeader,
    mat: csr_matrix,
    edge_of: dict[tuple[int, int], int],
    od: pd.DataFrame,
) -> np.ndarray:
    """Accumulate ``n_legs`` on every undirected edge of each OD shortest walk."""
    loads = np.zeros(header.n_edges, dtype=np.int64)
    endpoints = header.endpoints
    # resolve OD keys → node indices; drop pairs with unknown endpoints
    rows = []
    for row in od.itertuples(index=False):
        a, b = endpoints.get(row.from_key), endpoints.get(row.to_key)
        if a is None or b is None or a == b:
            continue
        rows.append((int(a), int(b), int(row.n_legs)))
    if not rows:
        return loads
    origins = sorted({r[0] for r in rows})
    by_origin: dict[int, list[tuple[int, int]]] = {o: [] for o in origins}
    for a, b, n in rows:
        by_origin[a].append((b, n))

    for start in range(0, len(origins), BATCH):
        batch = origins[start : start + BATCH]
        _dist, pred = dijkstra(mat, directed=True, indices=batch, return_predecessors=True)
        for bi, src in enumerate(batch):
            pred_row = pred[bi]
            for dst, n_legs in by_origin[src]:
                if pred_row[dst] < 0 and src != dst:
                    continue
                try:
                    path = _path(pred_row, src, dst)
                except ValueError:
                    continue
                for u, v in zip(path[:-1], path[1:], strict=True):
                    e = edge_of.get((int(u), int(v)))
                    if e is not None:
                        loads[e] += n_legs
    return loads


def export_demand(
    cfg: dict,
    processed: Path,
    out_dir: Path,
    changed: list[str],
    *,
    note: str | None = None,
) -> str | None:
    """Write ``demand.json`` from OD routed on ``out_dir/network.json``. Returns relative path."""
    out_dir = Path(out_dir)
    od_path = Path(processed) / OD.path
    if not od_path.exists():
        log.info("no %s: skip demand.json", od_path)
        return None
    if not (out_dir / "network.json").exists():
        log.warning("no %s/network.json: skip demand.json (export --campus first)", out_dir)
        return None

    od = OD.read(od_path)
    header, mat, edge_of = load_web_graph(out_dir)
    loads = edge_loads_from_od(header, mat, edge_of, od)
    edges = [
        EdgeLoad(edge=i, n_legs=int(n))
        for i, n in sorted(enumerate(loads), key=lambda x: (-x[1], x[0]))
        if n > 0
    ]
    demand = Demand(
        provenance=provenance(GENERATOR, cfg),
        note=note,
        n_edges=header.n_edges,
        max_n_legs=int(loads.max()) if len(loads) else 0,
        edges=edges,
    )
    rel = "demand.json"
    (out_dir / rel).write_text(demand.model_dump_json(indent=2), encoding="utf-8")
    changed.append(rel)
    log.info(
        "demand.json: %d / %d edges with load (max %d), %d OD pairs",
        len(edges),
        header.n_edges,
        demand.max_n_legs,
        len(od),
    )
    return rel

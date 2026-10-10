"""Build ``instance/instance.npz`` from the walk graph and demand OD matrix.

The optimiser only reads the instance file (docs/data_contracts.md §7).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from ..config import config_hash
from ..schemas.instance import Instance, InstanceMeta
from ..schemas.tables import GRAPH_EDGES, GRAPH_NODES, OD
from ..simulation.simulate import BATCH, walk_matrix

log = logging.getLogger(__name__)


def build_instance(
    processed: Path,
    cfg: dict,
    *,
    name: str = "campus",
) -> Instance:
    """Assemble an Instance from ``processed/network`` + ``processed/demand/od.parquet``."""
    processed = Path(processed)
    nodes = GRAPH_NODES.read(processed / GRAPH_NODES.path)
    edges = GRAPH_EDGES.read(processed / GRAPH_EDGES.path)
    od = OD.read(processed / OD.path)

    wanted = cfg["metro"].get("candidates", "all")
    shafts = nodes[nodes.kind == "shaft_top"].copy()
    if wanted != "all":
        shafts = shafts[shafts.building_id.isin(wanted)]
    shafts = shafts.sort_values("building_id").reset_index(drop=True)
    if len(shafts) < 2:
        raise ValueError(f"need ≥2 metro candidates (shaft_top), got {len(shafts)}")

    platforms = nodes[nodes.kind == "platform"].set_index("building_id")
    missing = [b for b in shafts.building_id if b not in platforms.index]
    if missing:
        raise ValueError(f"shaft without platform: {missing[:5]}")

    candidate_ids = shafts.building_id.to_numpy(dtype=object)
    candidate_xyz = shafts[["x", "y", "z"]].to_numpy(np.float64)
    plat_xy = platforms.loc[list(candidate_ids)][["x", "y"]].to_numpy(np.float64)
    tunnel_m = np.linalg.norm(plat_xy[:, None] - plat_xy[None], axis=2).astype(np.float32)

    ep = nodes[nodes.endpoint_key.notna()].copy()
    endpoint_keys = ep.endpoint_key.to_numpy(dtype=object)
    key_to_ep = {k: i for i, k in enumerate(endpoint_keys)}
    ep_node = ep.node_id.to_numpy(np.int32)
    shaft_node = shafts.node_id.to_numpy(np.int32)

    mat = walk_matrix(nodes, edges)
    # access: endpoint → each shaft; egress = transpose of shaft → endpoint
    access = _times_to(mat, ep_node, shaft_node)  # (E, N)
    egress = _times_to(mat, shaft_node, ep_node)  # (N, E)

    # OD pairs that resolve to known endpoints
    rows = []
    for row in od.itertuples(index=False):
        a, b = key_to_ep.get(row.from_key), key_to_ep.get(row.to_key)
        if a is None or b is None or a == b:
            continue
        rows.append((a, b, float(row.n_legs)))
    if not rows:
        raise ValueError("no OD pairs map to graph endpoints")
    od_from = np.array([r[0] for r in rows], np.int32)
    od_to = np.array([r[1] for r in rows], np.int32)
    od_weight = np.array([r[2] for r in rows], np.float32)

    # walk times between OD endpoints (batch Dijkstra from unique origins)
    od_walk = np.empty(len(rows), np.float32)
    origins = sorted(set(od_from.tolist()))
    by_origin: dict[int, list[int]] = {o: [] for o in origins}
    for i, o in enumerate(od_from):
        by_origin[int(o)].append(i)
    for start in range(0, len(origins), BATCH):
        batch = origins[start : start + BATCH]
        src_nodes = ep_node[batch]
        dist = dijkstra(mat, directed=True, indices=src_nodes, return_predecessors=False)
        for bi, o in enumerate(batch):
            for idx in by_origin[o]:
                d = dist[bi, ep_node[od_to[idx]]]
                if not np.isfinite(d):
                    raise ValueError(
                        f"no walk path {endpoint_keys[o]} → {endpoint_keys[od_to[idx]]}"
                    )
                od_walk[idx] = d

    m = cfg["metro"]
    tm = cfg["time_model"]
    depth = float(m["station_depth_m"])
    k = max(2, min(int(m["n_stations"]), len(candidate_ids)))
    meta = InstanceMeta(
        name=name,
        topology=m["topology"],
        k=k,
        metro_speed_mps=float(m["speed_mps"]),
        dwell_s=float(m["dwell_s"]),
        wait_s=float(m["headway_s"]) / 2.0,
        shaft_down_s=depth / float(tm["stairs_down_mps"]),
        shaft_up_s=depth / float(tm["stairs_up_mps"]),
        source_hash=hashlib.sha256(
            (config_hash(cfg) + str(len(nodes)) + str(len(od))).encode()
        ).hexdigest()[:16],
    )
    inst = Instance(
        meta=meta,
        candidate_ids=candidate_ids,
        candidate_xyz=candidate_xyz,
        tunnel_m=tunnel_m,
        endpoint_keys=endpoint_keys,
        access_s=access.astype(np.float32),
        egress_s=egress.astype(np.float32),
        od_from=od_from,
        od_to=od_to,
        od_weight=od_weight,
        od_walk_s=od_walk,
    )
    inst.validate()
    log.info(
        "instance %s: %d candidates, %d endpoints, %d OD pairs, k=%d",
        name, inst.n_candidates, len(endpoint_keys), len(od_from), k,
    )
    return inst


def _times_to(mat, from_nodes: np.ndarray, to_nodes: np.ndarray) -> np.ndarray:
    """Shortest-path times from each ``from_nodes[i]`` to every ``to_nodes[j]`` → (F, T)."""
    out = np.full((len(from_nodes), len(to_nodes)), np.inf, np.float64)
    for start in range(0, len(from_nodes), BATCH):
        batch = from_nodes[start : start + BATCH]
        dist = dijkstra(mat, directed=True, indices=batch, return_predecessors=False)
        out[start : start + len(batch)] = dist[:, to_nodes]
    return out


def write_instance(inst: Instance, path: Path) -> Path:
    path = Path(path)
    inst.save(path)
    log.info("wrote %s", path)
    return path

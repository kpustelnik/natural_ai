"""Build ``instance/instance.npz`` from the walk graph and demand OD matrix.

The optimiser only reads the instance file (docs/data_contracts.md §7).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from ..schemas.instance import Instance, InstanceMeta
from ..schemas.tables import GRAPH_EDGES, GRAPH_NODES, OD, TRANSIT_RIDES
from ..simulation.simulate import BATCH, walk_matrix

log = logging.getLogger(__name__)

DAY_HEADWAY = 3600.0  # a pair served once a day: assume an hourly service (30 min wait)


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
        # the same check as with_config, so a cached instance and a fresh build agree
        missing = sorted(set(wanted) - set(shafts.building_id))
        if missing:
            raise ValueError(f"metro.candidates not in the instance: {missing}")
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
    lost = 0.0
    for row in od.itertuples(index=False):
        a, b = key_to_ep.get(row.from_key), key_to_ep.get(row.to_key)
        if a is None or b is None:
            lost += float(row.n_legs)
            continue
        if a == b:
            continue
        rows.append((a, b, float(row.n_legs)))
    if not rows:
        raise ValueError("no OD pairs map to graph endpoints")
    if lost:
        log.warning(
            "%.0f of %.0f student-legs (%.1f%%) have an endpoint missing from the graph: "
            "left out of the instance (rebuild demand after the network)",
            lost, od.n_legs.sum(), 100 * lost / od.n_legs.sum(),
        )  # fmt: skip
    od_from = np.array([r[0] for r in rows], np.int32)
    od_to = np.array([r[1] for r in rows], np.int32)
    od_weight = np.array([r[2] for r in rows], np.float32)

    # walk times between OD endpoints (E x E is small: every endpoint to every endpoint)
    walk = _times_to(mat, ep_node, ep_node)[od_from, od_to]
    if not np.isfinite(walk).all():
        i = int(np.argmin(np.isfinite(walk)))
        raise ValueError(f"no walk path {endpoint_keys[od_from[i]]} → {endpoint_keys[od_to[i]]}")
    od_walk = walk.astype(np.float32)

    # the no-metro time is the faster of walking and the bus / tram (when it is simulated too)
    rides = transit_rides(processed, cfg)
    if rides is not None and len(rides):
        stop_ids = sorted(set(rides.from_stop) | set(rides.to_stop))
        key_to_node = dict(zip(nodes.key, nodes.node_id, strict=True))
        stop_ids = [s for s in stop_ids if s in key_to_node]
        stop_node = np.array([key_to_node[s] for s in stop_ids], np.int32)
        if len(stop_node):
            to_stop = _times_to(mat, ep_node, stop_node)  # (E, S)
            from_stop = _times_to(mat, stop_node, ep_node)  # (S, E)
            col = {s: i for i, s in enumerate(stop_ids)}
            by_transit = np.full(len(rows), np.inf)
            for r in rides.itertuples(index=False):
                if r.from_stop not in col or r.to_stop not in col:
                    continue
                wait = (r.median_headway_s if pd.notna(r.median_headway_s) else DAY_HEADWAY) / 2
                t = (
                    to_stop[od_from, col[r.from_stop]]
                    + wait + r.median_ride_s
                    + from_stop[col[r.to_stop], od_to]
                )  # fmt: skip
                by_transit = np.minimum(by_transit, t)
            faster = by_transit < od_walk
            share = 100 * od_weight[faster].sum() / od_weight.sum()
            log.info("bus / tram faster than walking for %d of %d OD pairs (%.0f%% of legs)",
                     faster.sum(), len(rows), share)  # fmt: skip
            od_walk = np.minimum(od_walk, by_transit).astype(np.float32)

    meta = metro_meta(cfg, len(candidate_ids), name=name, source_hash=inputs_hash(processed, cfg))
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
        name,
        inst.n_candidates,
        len(endpoint_keys),
        len(od_from),
        meta.k,
    )
    return inst


def metro_meta(
    cfg: dict, n_candidates: int, *, name: str, source_hash: str | None = None
) -> InstanceMeta:
    """Line and train parameters of ``config.yaml`` -> ``metro``: they change no array, so a
    cached instance takes them from the current config (``with_config``)."""
    m, tm = cfg["metro"], cfg["time_model"]
    depth = float(m["station_depth_m"])
    return InstanceMeta(
        name=name,
        topology=m["topology"],
        k=max(2, min(int(m["n_stations"]), n_candidates)),
        metro_speed_mps=float(m["speed_mps"]),
        dwell_s=float(m["dwell_s"]),
        wait_s=float(m["headway_s"]) / 2.0,
        shaft_down_s=depth / float(tm["stairs_down_mps"]),
        shaft_up_s=depth / float(tm["stairs_up_mps"]),
        source_hash=source_hash,
    )


def with_config(inst: Instance, cfg: dict) -> Instance:
    """The same arrays with k, topology, speed, dwell, headway and shaft times from ``cfg``;
    a ``metro.candidates`` list keeps only those candidates (``Instance.subset``)."""
    wanted = cfg["metro"].get("candidates", "all")
    if wanted != "all":
        ids = [str(c) for c in inst.candidate_ids]
        missing = sorted(set(wanted) - set(ids))
        if missing:
            raise ValueError(f"metro.candidates not in the instance: {missing}")
        if sorted(wanted) != sorted(ids):
            inst = inst.subset([ids.index(c) for c in sorted(set(wanted))])
    meta = metro_meta(
        cfg, inst.n_candidates, name=inst.meta.name, source_hash=inst.meta.source_hash
    )
    if meta.k != int(cfg["metro"]["n_stations"]):
        log.warning("metro.n_stations=%s clamped to k=%d (%d candidates)",
                    cfg["metro"]["n_stations"], meta.k, inst.n_candidates)  # fmt: skip
    return dataclasses.replace(inst, meta=meta)


def transit_rides(processed: Path, cfg: dict) -> pd.DataFrame | None:
    """``transit/rides.csv`` when buses and trams are simulated (``simulation.transit``)."""
    f = Path(processed) / TRANSIT_RIDES.path
    if not cfg.get("simulation", {}).get("transit", True) or not f.exists():
        return None
    return TRANSIT_RIDES.read(f)


def inputs_hash(processed: Path, cfg: dict) -> str | None:
    """Hash of what the arrays are computed from: graph, OD, buses, time model, candidates."""
    files = [processed / GRAPH_NODES.path, processed / GRAPH_EDGES.path, processed / OD.path]
    if not all(f.exists() for f in files):
        return None
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    rides = processed / TRANSIT_RIDES.path
    if cfg.get("simulation", {}).get("transit", True) and rides.exists():
        h.update(rides.read_bytes())
    h.update(json.dumps([cfg["time_model"], cfg["metro"].get("candidates", "all"),
                         cfg["metro"]["station_depth_m"]], sort_keys=True).encode())  # fmt: skip
    return h.hexdigest()[:16]


def load_or_build(
    processed: Path, cfg: dict, inst_path: Path, *, rebuild: bool = False, name: str = "campus"
) -> Instance:
    """``inst_path`` if it was built from the current inputs, else a fresh build (written
    there); either way with the line parameters of ``cfg``."""
    processed, inst_path = Path(processed), Path(inst_path)
    want = inputs_hash(processed, cfg)
    if not rebuild and inst_path.exists():
        inst = Instance.load(inst_path)
        if want is None or inst.meta.source_hash == want:
            log.info("loaded %s (%d candidates)", inst_path, inst.n_candidates)
            return with_config(inst, cfg)
        log.info("%s is stale (network, demand or time model changed): rebuilding", inst_path)
    inst = build_instance(processed, cfg, name=name)
    write_instance(inst, inst_path)
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

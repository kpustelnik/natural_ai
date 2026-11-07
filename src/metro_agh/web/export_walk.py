"""ACO level 1 for the viewer: ``results/walk-aco-*/walk_trace.npz`` -> ``replays/walk-*/``.

The run is on the parquet walk graph; the viewer draws ``network.json``, built from the same
inputs. Edges and nodes are matched by node keys (``osm:…``, ``D-17:main:out`` …), as
``export_demand`` does, so the flows land on the polylines the viewer draws.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import provenance
from ..schemas.web import Replay, ReplayFiles, WalkTraceHeader
from .binary import write_binary
from .export_campus import GENERATOR
from .export_demand import load_web_graph

log = logging.getLogger(__name__)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _window(params: dict) -> str:
    t0 = int(params["window_start_wt"])
    t1 = t0 + int(params["window_s"])
    day, s0 = divmod(t0, 86400)
    s1 = t1 - day * 86400

    def hm(t: int) -> str:
        return f"{t // 3600:02d}:{t % 3600 // 60:02d}"

    return f"{WEEKDAYS[day]} {hm(s0)}-{hm(s1)}"


def export_walk_run(cfg: dict, run_dir: Path, out_dir: Path, changed: list[str]) -> Replay:
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    z = np.load(run_dir / "walk_trace.npz")
    conv = pd.read_csv(run_dir / "convergence.csv")
    header, _mat, edge_of = load_web_graph(out_dir)
    web_node = {k: i for i, k in enumerate(header.node_keys)}

    # run edge -> web edge (or -1 when the web graph has no such edge)
    eu = [web_node.get(str(k), -1) for k in z["edge_u_key"]]
    ev = [web_node.get(str(k), -1) for k in z["edge_v_key"]]
    to_web = np.array(
        [edge_of.get((a, b), -1) if a >= 0 and b >= 0 else -1 for a, b in zip(eu, ev, strict=True)]
    )
    ok = to_web >= 0
    missing = int((~ok).sum())
    if missing:
        log.warning(
            "walk replay: %d of %d edges not in network.json (campus changed?)", missing, len(ok)
        )

    def per_web(a: np.ndarray) -> np.ndarray:
        out = np.zeros(a.shape[:-1] + (header.n_edges,), np.float32)
        out[..., to_web[ok]] = a[..., ok]
        return out

    # sampled ant paths: run node ids -> keys -> web node ids; a path with an unknown node
    # is cut there (only happens if the campus changed after the run)
    node_keys = z["node_keys"]
    nodes = np.array([web_node.get(str(k), -1) for k in node_keys])[z["ant_nodes"]]
    offsets = z["ant_offsets"]
    paths = [nodes[offsets[i] : offsets[i + 1]] for i in range(len(offsets) - 1)]
    paths = [p[: np.argmax(p < 0)] if (p < 0).any() else p for p in paths]
    ant_offsets = np.concatenate([[0], np.cumsum([len(p) for p in paths])]).astype(np.uint32)
    sample_offsets = np.concatenate([[0], np.cumsum(z["ants_per_sample"])]).astype(np.uint32)

    people = float(run["people"])
    params = run["params"]
    rid = run["run_id"].replace("walk-aco", "walk", 1)
    rel_dir = f"replays/{rid}"
    write_binary(
        out_dir / rel_dir / "walk.json",
        WalkTraceHeader,
        {
            "iterations": z["iterations"].astype(np.int32),
            "flow": per_web(z["flow"]),
            "ratio": per_web(z["ratio"]),
            "pheromone": per_web(z["pheromone"]),
            "ratio_aon": per_web(z["ratio_aon"]),
            "ant_sample_offsets": sample_offsets,
            "ant_offsets": ant_offsets,
            "ant_nodes": (np.concatenate(paths) if paths else np.zeros(0)).astype(np.uint32),
            "curve_iteration": conv["iteration"].to_numpy(np.int32),
            "curve_mean_s": conv["mean_s"].to_numpy(np.float32),
            "curve_iter_mean_s": (conv["iter_total_s"] / people).to_numpy(np.float32),
            "curve_gap": conv["gap"].to_numpy(np.float32),
        },
        provenance=provenance(GENERATOR, cfg),
        run_id=run["run_id"],
        n_iterations=int(run["n_iterations"]),
        window=_window(params),
        period_s=float(params["period_s"]),
        n_legs=int(run["n_legs"]),
        people=people,
        free_flow_mean_s=run["free_flow_s"] / people,
        aon_mean_s=run["aon_s"] / people,
        msa_mean_s=run["msa_s"] / people,
        aco_mean_s=run["aco_s"] / people,
    )
    changed += [f"{rel_dir}/walk.json", f"{rel_dir}/walk.bin"]
    saving = 100 * (1 - run["aco_s"] / run["aon_s"])
    replay = Replay(
        id=rid,
        kind="walk",
        title=f"Walk ACO (level 1), peak with congestion: −{saving:.1f} %",
        description=f"{_window(params)}, {run['n_legs']} walking legs",
        created_at=run["provenance"]["generated_at"],
        run_id=run["run_id"],
        files=ReplayFiles(walk_trace=f"{rel_dir}/walk.json"),
    )
    p = out_dir / rel_dir / "replay.json"
    p.write_text(replay.model_dump_json(), encoding="utf-8")
    changed.append(f"{rel_dir}/replay.json")
    log.info("replay %s: %d samples, %d ant paths", rid, len(z["iterations"]), len(paths))
    return replay

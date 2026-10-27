"""Validation test 5: walking times measured on campus vs the walk graph.

``data/validation/field_measurements.csv`` (``tables.FIELD_MEASUREMENTS``): a route between
two endpoint keys (a building, a room, a stop) timed with a stopwatch. The model time is the
shortest walk on ``network/*.parquet`` (the same graph the simulation walks).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from .simulation.simulate import walk_matrix


def compare_field(measured: pd.DataFrame, nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    """Per measurement: the model's shortest walk (``model_s``) and the error
    (``error_s`` = model - measured, ``error_pct`` of the measured time). Keys missing from
    the graph give NaN."""
    node_of = {str(k): int(i) for k, i in zip(nodes.endpoint_key, nodes.node_id, strict=True)
               if isinstance(k, str)}  # fmt: skip
    out = measured.copy()
    src = sorted({node_of[k] for k in out.from_key if k in node_of})
    model = np.full(len(out), np.nan)
    if src:
        times = dijkstra(walk_matrix(nodes, edges), indices=src)
        row = {s: i for i, s in enumerate(src)}
        for n, (a, b) in enumerate(zip(out.from_key, out.to_key, strict=True)):
            if a in node_of and b in node_of:
                model[n] = times[row[node_of[a]], node_of[b]]
    out["model_s"] = np.round(model, 1)
    out["error_s"] = (out["model_s"] - out["measured_s"]).round(1)
    out["error_pct"] = (100 * out["error_s"] / out["measured_s"]).round(1)
    return out


def summary(cmp: pd.DataFrame) -> dict[str, float]:
    """MAE (s), mean error (bias: + = the model is slower), MAPE (%) over the routes the
    graph knows."""
    ok = cmp.dropna(subset=["model_s"])
    return {
        "routes": int(ok.route_id.nunique()),
        "measurements": len(ok),
        "unknown_keys": int(cmp["model_s"].isna().sum()),
        "mae_s": round(float(ok.error_s.abs().mean()), 1) if len(ok) else float("nan"),
        "bias_s": round(float(ok.error_s.mean()), 1) if len(ok) else float("nan"),
        "mape_pct": round(float(ok.error_pct.abs().mean()), 1) if len(ok) else float("nan"),
    }

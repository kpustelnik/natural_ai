"""The report's metrics of one simulated scenario (README, "Metryki raportowane"):
student time per week, late legs and late classes, how many legs ride the metro or a bus /
tram. ``longer_than_break_share`` is the late share of the between-class legs: only they
have a break, and they leave when the class ends, so a leg longer than its break arrives
late. Used by the viewer's stats.json (``web/export_sim``) and by
``scripts/report_metrics.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def scenario_metrics(sim: pd.DataFrame, legs: pd.DataFrame) -> dict[str, float | int]:
    """``sim``: ``tables.SIM_LEGS`` of one scenario; ``legs``: ``tables.LEGS`` (breaks,
    deadlines). A class is one (endpoint, start) pair, the week-time start carrying the
    weekday; the endpoint is the room in buildings with LOD3 rooms, else the building (all
    of them today). It is late when any of its students arrives after the start."""
    travel = (sim.arrive_wt - sim.depart_wt).to_numpy(float)
    by_leg = legs.set_index("leg_id")
    brk = by_leg.break_s.reindex(sim.leg_id).to_numpy(float, na_value=np.nan)
    known = ~np.isnan(brk)
    n = len(sim)
    late = sim.late_s.to_numpy(float) > 0
    deadline = by_leg.deadline_wt.reindex(sim.leg_id).to_numpy(float, na_value=np.nan)
    classes = pd.DataFrame({
        "endpoint": by_leg.to_key.reindex(sim.leg_id).to_numpy(),
        "start": deadline,
        "late": late,
    }).dropna(subset=["start"])  # fmt: skip
    per_class = classes.groupby(["endpoint", "start"])["late"].any()
    return {
        "n_legs": n,
        "total_travel_s": round(float(travel.sum()), 1),
        "mean_leg_s": round(float(travel.mean()) if n else 0.0, 1),
        "n_late": int(late.sum()),
        "late_share": float(late.mean()) if n else 0.0,
        "longer_than_break_share": float((travel[known] > brk[known]).mean())
        if known.any()
        else 0.0,
        "metro_share": float((sim["mode"] == "metro").mean()) if n else 0.0,
        "transit_share": float((sim["mode"] == "transit").mean()) if n else 0.0,
        "n_classes": int(len(per_class)),
        "n_late_classes": int(per_class.sum()),
    }

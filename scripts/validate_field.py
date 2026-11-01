"""Validation test 5: measured walking times vs the walk graph.

    uv run scripts/validate_field.py      # after 02_build_campus.py

Reads data/validation/field_measurements.csv (route_id, from_key, to_key, measured_s,
date, who, notes; keys like D-17, D-17/1.38, stop:czarnowiejska) and network/*.parquet.
Writes docs/figures/field_validation.csv (every measurement with the model time and the
error) and field_validation.png (model vs measured, the diagonal = a perfect model), and
prints MAE, bias and MAPE.
"""

from __future__ import annotations

import sys

import numpy as np

from metro_agh import figures as fg
from metro_agh.config import ROOT, load_config, path
from metro_agh.schemas.tables import FIELD_MEASUREMENTS, GRAPH_EDGES, GRAPH_NODES
from metro_agh.validation import compare_field, summary


def main() -> int:
    cfg = load_config()
    measured = FIELD_MEASUREMENTS.read(ROOT / FIELD_MEASUREMENTS.path)
    if measured.empty:
        print(f"no rows in {FIELD_MEASUREMENTS.path} yet: time ~10 routes on campus "
              "(README, Walidacja) and run this again", file=sys.stderr)  # fmt: skip
        return 1
    processed = path(cfg, "processed")
    nodes = GRAPH_NODES.read(processed / GRAPH_NODES.path)
    edges = GRAPH_EDGES.read(processed / GRAPH_EDGES.path)
    cmp = compare_field(measured, nodes, edges)
    s = summary(cmp)
    figures = ROOT / "docs" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    cmp.to_csv(figures / "field_validation.csv", index=False, lineterminator="\n")

    ok = cmp.dropna(subset=["model_s"])
    fig, (ax,) = fg.axes(width=5.6, height=5.0)
    top = float(np.nanmax([ok.measured_s.max(), ok.model_s.max()])) * 1.08 if len(ok) else 1
    ax.plot([0, top], [0, top], color=fg.GRID, linewidth=1.5)
    ax.scatter(ok.measured_s, ok.model_s, s=30, color=fg.SERIES[0], edgecolors=fg.SURFACE,
               linewidths=1.5, zorder=3)  # fmt: skip
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    fg.finish(ax, "Walk graph vs stopwatch", "measured (s)", "model: shortest walk (s)")
    fg.save(fig, figures / "field_validation.png",
            f"{s['measurements']} measurements, {s['routes']} routes; MAE {s['mae_s']} s, "
            f"bias {s['bias_s']:+} s, MAPE {s['mape_pct']}%")  # fmt: skip
    print(cmp.to_string(index=False))
    print(s)
    if s["unknown_keys"]:
        print(f"{s['unknown_keys']} measurements: keys missing from the graph or not connected",
              file=sys.stderr)  # fmt: skip
    print(f"wrote {figures / 'field_validation'}.png and .csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())

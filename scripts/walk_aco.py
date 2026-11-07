"""ACO level 1: the peak walking flows with congestion (``metro_agh.walk.assign``).

    uv run scripts/walk_aco.py            # after 05_simulate.py (reads the no-metro legs)

Assigns the peak quarter hour (``walk_aco`` in config.yaml) four ways: free flow (no
congestion, a lower bound), all-or-nothing on free-flow paths (what the metro model and the
simulation assume, evaluated with congestion), the ant colony (5 seeds; seed 42 with a
trace for the viewer) and the method of successive averages (equilibrium reference), plus a
small ablation (alpha = 0 / 1 / 2: does the pheromone help?).

Writes experiments/results/walk-aco-s42/ (run.json, convergence.csv, trace.npz) and
docs/figures/walk_aco.png + .csv (summary), walk_aco_convergence.csv, walk_aco_ablation.csv.
Then ``06_export_web.py --walk`` makes the viewer replay.
"""

from __future__ import annotations

import copy
import json
import time

import numpy as np
import pandas as pd

from metro_agh import figures as fg
from metro_agh.config import ROOT, load_config, path, provenance
from metro_agh.schemas.tables import GRAPH_EDGES, GRAPH_NODES
from metro_agh.walk.assign import (
    aon,
    build_net,
    edge_flow,
    free_flow_total,
    highway_of_ways,
    peak_demand,
    run_msa,
    run_walk_aco,
    summary,
)

SEEDS = [42, 43, 44, 45, 46]
RUN_ID = "walk-aco-s42"


def main() -> int:
    cfg = load_config()
    processed = path(cfg, "processed")
    nodes = GRAPH_NODES.read(processed / GRAPH_NODES.path)
    edges = GRAPH_EDGES.read(processed / GRAPH_EDGES.path)
    net = build_net(nodes, edges, cfg, highway_of_ways(processed / "osm" / "campus.gpkg"))
    sim = pd.read_parquet(processed / "simulation" / "no_metro" / "legs.parquet",
                          columns=["mode", "depart_wt", "path_nodes"])  # fmt: skip
    demand = peak_demand(sim, cfg)
    people = demand.people
    print(f"{demand.n_legs} walking legs in the window, {len(demand.origin)} pairs, "
          f"{len(demand.dest_nodes)} destinations, {net.n_edges} edges")  # fmt: skip

    rows = []
    ff = free_flow_total(net, demand)
    rows.append({"assignment": "free_flow", "total_s": ff, "mean_s": ff / people, "gap": np.nan,
                 "max_ratio": np.nan, "n_over": np.nan, "n_loaded": np.nan})  # fmt: skip
    a = aon(net, demand, cfg)
    rows.append(summary(net, demand, a))
    t = time.time()
    msa = run_msa(net, demand, cfg)
    rows.append(summary(net, demand, msa))
    print(f"msa {time.time() - t:.1f} s")
    runs = []
    for seed in SEEDS:
        t = time.time()
        r = run_walk_aco(net, demand, cfg, seed=seed, trace=seed == SEEDS[0])
        runs.append(r)
        s = summary(net, demand, r) | {"seed": seed, "wall_s": round(time.time() - t, 2)}
        rows.append(s | {"assignment": "aco"})
        print(s)
    table = pd.DataFrame(rows)
    aon_mean = a.total_s / people
    table["vs_aon_pct"] = 100 * (1 - table["mean_s"] / aon_mean)
    table["vs_free_flow_pct"] = 100 * (table["mean_s"] / (ff / people) - 1)

    ablation = []
    for alpha in (0.0, 1.0, 2.0):
        c = copy.deepcopy(cfg)
        c["walk_aco"]["alpha"] = alpha
        for seed in SEEDS:
            r = run_walk_aco(net, demand, c, seed=seed, trace=False)
            ablation.append(
                {"alpha": alpha, "seed": seed, "mean_s": r.total_s / people, "gap": r.gap}
            )
    ablation = pd.DataFrame(ablation)

    figures = ROOT / "docs" / "figures"
    table.to_csv(figures / "walk_aco.csv", index=False, float_format="%.4f", lineterminator="\n")
    ablation.to_csv(figures / "walk_aco_ablation.csv", index=False, float_format="%.4f",
                    lineterminator="\n")  # fmt: skip
    best = runs[0]
    conv = pd.DataFrame(best.curve).assign(algorithm="aco")
    conv = pd.concat([conv, pd.DataFrame(msa.curve).assign(algorithm="msa")], ignore_index=True)
    conv.to_csv(figures / "walk_aco_convergence.csv", index=False, float_format="%.4f",
                lineterminator="\n")  # fmt: skip
    _plot(figures, best, msa, a.total_s / people, ff / people, ablation, demand)

    out = path(cfg, "results") / RUN_ID
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(best.curve).to_csv(out / "convergence.csv", index=False, lineterminator="\n")
    tr = best.trace
    ants = [p for sample in tr["ants"] for p in sample]
    per_sample = np.array([len(s) for s in tr["ants"]], np.int32)
    offsets = np.concatenate([[0], np.cumsum([len(p) for p in ants])]).astype(np.int64)
    keys = nodes.set_index("node_id")["key"]
    np.savez_compressed(
        out / "walk_trace.npz",
        iterations=np.array(tr["iterations"], np.int32),
        flow=np.stack(tr["flow"]),
        ratio=np.stack(tr["ratio"]),
        pheromone=np.stack(tr["pheromone"]),
        ants_per_sample=per_sample,
        ant_offsets=offsets,
        ant_nodes=np.concatenate(ants).astype(np.int32) if ants else np.zeros(0, np.int32),
        edge_u_key=keys.loc[net.edge_u].to_numpy(str),
        edge_v_key=keys.loc[net.edge_v].to_numpy(str),
        node_keys=keys.sort_index().to_numpy(str),
        flow_aon=edge_flow(a.x_arc).astype(np.float32),
        ratio_aon=(edge_flow(a.x_arc) / net.cap).astype(np.float32),
        flow_msa=edge_flow(msa.x_arc).astype(np.float32),
        capacity=net.cap.astype(np.float32),
    )
    run = {
        "provenance": provenance("walk_aco.py", cfg).model_dump(),
        "run_id": RUN_ID,
        "seed": SEEDS[0],
        "params": cfg["walk_aco"],
        "n_legs": demand.n_legs,
        "n_pairs": int(len(demand.origin)),
        "n_destinations": int(len(demand.dest_nodes)),
        "people": people,
        "n_iterations": int(cfg["walk_aco"]["n_iterations"]),
        "free_flow_s": ff,
        "aon_s": a.total_s,
        "msa_s": msa.total_s,
        "aco_s": best.total_s,
        "summary": json.loads(table.to_json(orient="records")),
    }
    (out / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    print(table.to_string(index=False))
    print(ablation.groupby("alpha")[["mean_s", "gap"]].agg(["mean", "min", "max"]).to_string())
    print(f"wrote {out} and {figures / 'walk_aco'}.png / .csv")
    return 0


def _plot(figures, aco, msa, aon_mean, ff_mean, ablation, demand) -> None:
    fig, (ax, ax2) = fg.axes(2, width=9.6, height=4.2, sharey=False)
    it = np.array([r["iteration"] for r in aco.curve]) + 1
    fg.lines(ax, [
        ("ant colony", it, np.array([r["mean_s"] for r in aco.curve])),
        ("MSA (equilibrium)", np.array([r["iteration"] for r in msa.curve]),
         np.array([r["mean_s"] for r in msa.curve])),
    ])  # fmt: skip
    for y, text in ((aon_mean, "shortest path, congested"), (ff_mean, "free flow (no congestion)")):
        ax.axhline(y, color=fg.TEXT_2, linewidth=1, linestyle="--")
        ax.annotate(text, (it[-1], y), xytext=(0, 4), textcoords="offset points", ha="right",
                    fontsize=8, color=fg.TEXT_2)  # fmt: skip
    fg.finish(ax, "Peak walk with congestion", "iteration", "mean walk per person (s)")
    groups = [(f"α = {a:g}", g["mean_s"].to_numpy()) for a, g in ablation.groupby("alpha")]
    fg.dots(ax2, groups, texts=[f"{v.mean():.1f} s" for _, v in groups])
    fg.finish(ax2, "Does the pheromone help? (5 seeds)", None, "mean walk per person (s)")
    fg.save(fig, figures / "walk_aco.png",
            f"Wednesday 9:30-9:45: {demand.n_legs} walking legs, {len(demand.origin)} pairs; "
            "BPR travel time, capacity 75 ped/min/m, 5-min period")  # fmt: skip


if __name__ == "__main__":
    raise SystemExit(main())

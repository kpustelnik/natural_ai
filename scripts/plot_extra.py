"""Figures and tables of the extra experiments (docs/roadmap.md P1), from runs.csv.

    uv run scripts/plot_extra.py exact_full     # exact optimum of the whole campus, k = 2, 3, 4
    uv run scripts/plot_extra.py heuristic      # η: ours vs distance only vs demand only vs none
    uv run scripts/plot_extra.py topology       # line vs loop, k = 5 and 7
    uv run scripts/plot_extra.py sensitivity    # dwell, headway, speed; stability of the stations
    uv run scripts/plot_extra.py tunnel         # tunnel length of the best line for each k
    uv run scripts/plot_extra.py all

Writes docs/figures/<name>.png and .csv in the style of ``plot_experiments.py``
(``metro_agh.figures``). Comparisons use ``metro_agh.stats``: Mann–Whitney U against the
reference, Holm correction, A12 = P(reference saves more). docs/aco.md §9.7.
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd

from metro_agh import figures as fg
from metro_agh.config import ROOT, load_config, path
from metro_agh.schemas.tables import RUNS
from metro_agh.stats import a12, effect, holm, rank_sum

FIG = ROOT / "docs" / "figures"
NAMES = {"mmas": "MMAS", "acs": "ACS", "random": "random", "greedy": "greedy"}


def _dotted(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        out.update(_dotted(v, f"{prefix}{k}.") if isinstance(v, dict) else {f"{prefix}{k}": v})
    return out


def runs_of(experiment: str) -> pd.DataFrame:
    """The experiment's runs with ``saving`` (%), ``params`` and ``ov`` (dotted overrides)."""
    runs = RUNS.read(path(load_config(), "results") / "runs.csv")
    r = runs[runs["experiment"] == experiment].reset_index(drop=True)
    if r.empty:
        raise SystemExit(f"no runs of {experiment!r}: run experiments/configs/{experiment}.yaml")
    r["saving"] = 100 * (1 - r["best_s"] / r["baseline_s"])
    r["params"] = r["params_json"].map(json.loads)
    r["ov"] = r["params"].map(lambda p: _dotted(p.get("overrides") or {}))
    return r


def tests(r: pd.DataFrame, by: str, ref, group: str | None = None) -> pd.DataFrame:
    """Per value of ``by`` (within each ``group``): runs, mean / min / max saving, and against
    ``ref`` the Mann–Whitney p, Holm-corrected p, A12 and its size."""
    rows = []
    for g, d in [(None, r)] if group is None else r.groupby(group):
        x = d.loc[d[by] == ref, "saving"].to_numpy()
        block = []
        for v, dv in d.groupby(by, sort=False):
            y = dv["saving"].to_numpy()
            row = {by: v, "runs": len(y), "mean": y.mean(), "min": y.min(), "max": y.max()}
            if group is not None:
                row = {group: g, **row}
            if v != ref:
                row["p_mw"], row["a12"] = rank_sum(x, y), a12(x, y)
            block.append(row)
        ps = [b.get("p_mw", np.nan) for b in block]
        for b, p in zip(block, holm(ps), strict=True):
            b["p_holm"] = p
            b["effect"] = effect(b.get("a12", np.nan))
        rows += block
    return pd.DataFrame(rows).round({"mean": 2, "min": 2, "max": 2, "a12": 3})


def _write(t: pd.DataFrame, name: str) -> None:
    t.to_csv(FIG / f"{name}.csv", index=False, lineterminator="\n")
    print(t.to_string(index=False))
    print(f"wrote {FIG / name}.png and .csv")


# --- exact optimum of the whole campus ---------------------------------------------------------


def exact_full() -> None:
    exact = runs_of("exact_full_brute").groupby("k")["best_s"].min()
    r = runs_of("exact_full")
    r["variant"] = r["ov"].map(
        lambda o: o["optimize.algorithm"] + ("-ls" if o.get("optimize.local_search") else "")
    )
    r = r[r["k"].isin(exact.index)].copy()
    r["opt"] = r["k"].map(exact)
    # share of the optimal saving missed (as gap_to_optimum.py): 0 = the optimum
    r["gap"] = 100 * (r["best_s"] - r["opt"]) / (r["baseline_s"] - r["opt"])
    r["hit"] = r["best_s"] <= r["opt"] * (1 + 1e-9)
    order = [v for a in NAMES for v in (f"{a}-ls", a) if v in set(r["variant"])]
    t = (
        r.groupby(["k", "variant"])
        .agg(
            runs=("hit", "size"),
            hit_rate=("hit", "mean"),
            mean_gap=("gap", "mean"),
            max_gap=("gap", "max"),
            evaluations=("evaluations", "mean"),
        )  # fmt: skip
        .reset_index()
    )
    t["optimum_saving"] = t["k"].map(100 * (1 - exact / r["baseline_s"].iloc[0]))
    t["_o"] = t["variant"].map(order.index)
    t = t.sort_values(["k", "_o"]).drop(columns="_o").round(3)

    ks = sorted(t["k"].unique())
    fig, (ax,) = fg.axes(width=8.4)
    width = 0.8 / len(order)
    for j, v in enumerate(order):
        d = t[t["variant"] == v].set_index("k").reindex(ks)
        x = np.arange(len(ks)) + (j - (len(order) - 1) / 2) * width
        base = v.removesuffix("-ls")
        color = {"mmas": fg.SERIES[0], "acs": fg.SERIES[1]}.get(base, fg.SERIES[2])
        ax.bar(x, 100 * d["hit_rate"], width, color=color,
               alpha=1.0 if v.endswith("-ls") else 0.45,
               label=NAMES[base] + (" + LS" if v.endswith("-ls") else ""))  # fmt: skip
    ax.set_xticks(range(len(ks)), [f"k = {k}" for k in ks])
    ax.set_ylim(0, 128)
    ax.set_yticks(range(0, 101, 20))
    ax.legend(fontsize=8, frameon=False, ncols=6, loc="upper center")
    fg.finish(ax, "Exact optimum of the whole campus found", None, "runs that found it (%)")
    fg.save(fig, FIG / "exact_full.png",
            f"N = 55; optimum by brute force (1,485 / 78,705 / 4.1 M lines); "
            f"{int(t['runs'].max())} seeds, 5,000 lines per run; LS = local search")  # fmt: skip
    _write(t, "exact_full")


# --- heuristic, topology, sensitivity ----------------------------------------------------------


HEUR = {"demand_distance": "demand / distance\n(ours)", "distance": "1 / distance\n(classic)",
        "demand": "demand only", "none": "none\n(β = 0)"}  # fmt: skip


def heuristic() -> None:
    r = runs_of("heuristic")
    r["heuristic"] = r["params"].map(lambda p: p.get("heuristic", "demand_distance"))
    t = tests(r, "heuristic", "demand_distance")
    fig, (ax,) = fg.axes()
    fg.dots(ax, [(HEUR[h], r.loc[r.heuristic == h, "saving"].to_numpy()) for h in HEUR
                 if h in set(r.heuristic)])  # fmt: skip
    fg.finish(ax, "MMAS with four heuristics η", ylabel=fg.SAVING)
    fg.save(fig, FIG / "heuristic.png", f"MMAS without local search, k = 5, 5,000 lines, "
            f"{int(t['runs'].max())} seeds; a dot per seed, tick = mean")  # fmt: skip
    _write(t, "heuristic")


def topology() -> None:
    r = runs_of("topology")
    ks = sorted(r["k"].unique())
    fig, axs = fg.axes(len(ks), width=4.0 * len(ks), sharey=False)
    for ax, k in zip(axs, ks, strict=True):
        d = r[r["k"] == k]
        fg.dots(ax, [(t, d.loc[d.topology == t, "saving"].to_numpy()) for t in ("line", "loop")])
        fg.finish(ax, f"k = {k}", ylabel=fg.SAVING if ax is axs[0] else None)
    fg.save(fig, FIG / "topology.png", "MMAS + local search, 5,000 lines, 10 seeds; line = "
            "trains shuttle, loop = trains go round")  # fmt: skip
    t = tests(r, "topology", "line", group="k")
    best = r.loc[r.groupby(["k", "topology"])["best_s"].idxmin()].set_index(["k", "topology"])
    t["best_line"] = [best.loc[(row.k, row.topology), "stations"] for row in t.itertuples()]
    _write(t, "topology")


def sensitivity() -> None:
    r = runs_of("sensitivity")
    base = r[r["ov"].map(len) == 0]
    base_line = set(base.loc[base["best_s"].idxmin(), "stations"].split("|"))
    keys = sorted({k for o in r["ov"] for k in o})
    cfg = load_config()
    rows = []
    fig, axs = fg.axes(len(keys), width=3.6 * len(keys), sharey=False)
    for ax, key in zip(axs, keys, strict=True):
        name = key.split(".")[-1]
        d = r[r["ov"].map(lambda o, key=key: key in o or not o)].copy()
        d["value"] = [o.get(key, cfg["metro"][name]) for o in d["ov"]]
        groups = []
        for v, dv in sorted(d.groupby("value"), key=lambda g: g[0]):
            jac = [len(set(s.split("|")) & base_line) / len(set(s.split("|")) | base_line)
                   for s in dv["stations"]]  # fmt: skip
            best = dv.loc[dv["best_s"].idxmin(), "stations"]
            rows.append({"parameter": key, "value": v, "runs": len(dv),
                         "mean": dv["saving"].mean(), "min": dv["saving"].min(),
                         "max": dv["saving"].max(), "jaccard_with_base": np.mean(jac),
                         "best_line": best})  # fmt: skip
            label = f"{v:g}" + (" (base)" if v == cfg["metro"][name] else "")
            groups.append((label, dv["saving"].to_numpy()))
        fg.dots(ax, groups)
        fg.finish(ax, key, ylabel=fg.SAVING if ax is axs[0] else None)
    fg.save(fig, FIG / "sensitivity.png", f"MMAS + local search, k = 5, 10 seeds; base line "
            f"{base.loc[base['best_s'].idxmin(), 'stations'].replace('|', '-')}")  # fmt: skip
    _write(pd.DataFrame(rows).round(3), "sensitivity")


# --- tunnel length ------------------------------------------------------------------------------


def tunnel() -> None:
    """Tunnel length of the best line for each k (docs/figures/k_sweep.csv) and the saving
    per km of tunnel."""
    from metro_agh.aco.objective import Objective
    from metro_agh.experiments import resolve_instance

    cfg = load_config()
    inst, _ = resolve_instance(cfg, None, False)
    ids = {str(c): i for i, c in enumerate(inst.candidate_ids)}
    f = Objective(inst)
    hours = f.baseline / 3600
    k = pd.read_csv(FIG / "k_sweep.csv")
    k["tunnel_km"] = [f.tunnel_m([ids[s] for s in line.split("|")]) / 1000 for line in k.best_line]
    k["saving_h_week"] = k["max"] / 100 * hours
    k["h_per_km"] = k["saving_h_week"] / k["tunnel_km"]
    t = (
        k[["k", "max", "tunnel_km", "saving_h_week", "h_per_km", "best_line"]]
        .rename(columns={"max": "saving"})
        .round(2)
    )
    fig, (ax,) = fg.axes()
    ax.plot(t["tunnel_km"], t["saving"], color=fg.SERIES[0], linewidth=2, marker="o",
            markersize=6, markeredgecolor=fg.SURFACE, markeredgewidth=2)  # fmt: skip
    for row in t.itertuples():
        fg.label(ax, row.tunnel_km, row.saving, f"k = {row.k}")
    fg.finish(ax, "Saving vs tunnel length of the best line", "tunnel (km)", fg.SAVING)
    fg.save(fig, FIG / "tunnel.png", "best line of the k sweep for each k (k_sweep.csv); "
            "tunnel = straight lines between neighbouring platforms")  # fmt: skip
    _write(t, "tunnel")


COMMANDS = {"exact_full": exact_full, "heuristic": heuristic, "topology": topology,
            "sensitivity": sensitivity, "tunnel": tunnel}  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("figure", choices=[*COMMANDS, "all"])
    args = parser.parse_args()
    FIG.mkdir(parents=True, exist_ok=True)
    for name in COMMANDS if args.figure == "all" else [args.figure]:
        try:
            COMMANDS[name]()
        except SystemExit as e:
            if args.figure != "all":
                raise
            print(f"{name}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

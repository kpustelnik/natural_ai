"""Figures for the report, from experiments/results/runs.csv.

    uv run scripts/plot_experiments.py k_sweep             # saving vs number of stations k
    uv run scripts/plot_experiments.py compare_algorithms  # one experiment, several algorithms
    uv run scripts/plot_experiments.py aco_ablation        # one parameter at a time

Writes docs/figures/<experiment>.png and .csv (the table). Saving = % of the no-metro
objective. Which figure follows from what the experiment's runs vary:

- only ``metro.n_stations`` (k sweep): k, runs, mean / min / max saving and the best line of
  the best run. One series: the mean over seeds as a line, the spread as a band.
- only ``optimize.*`` (algorithms): per variant (algorithm, with or without local search)
  the runs, mean / median / min / max saving, mean evaluations, the best line, and the
  Wilcoxon signed-rank p-value against the first variant (paired by seed); one dot per
  seed, the mean as a tick. Also <experiment>_convergence.png / .csv: the mean best saving
  so far against evaluations, MMAS vs ACS vs random, without and with local search.
- anything else (ablation): one panel per parameter, one column per value (the base run at
  its config value), one dot per seed.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from metro_agh import figures as fg
from metro_agh.config import ROOT, load_config, path
from metro_agh.schemas.tables import CONVERGENCE, RUNS

NAMES = {"mmas": "MMAS", "acs": "ACS", "random": "random", "greedy": "greedy",
         "brute_force": "brute force"}  # fmt: skip
ORDER = [f"{a}-ls" for a in NAMES] + list(NAMES)  # with local search first


def label(variant: str) -> str:
    base = variant.removesuffix("-ls")
    return NAMES.get(base, base) + (" + LS" if variant.endswith("-ls") else "")


def _params(runs: pd.DataFrame) -> pd.Series:
    return runs["params_json"].map(json.loads)


def _dotted(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        out.update(_dotted(v, f"{prefix}{k}.") if isinstance(v, dict) else {f"{prefix}{k}": v})
    return out


def overrides(runs: pd.DataFrame) -> pd.Series:
    """The dotted config overrides of each run's job."""
    return _params(runs).map(lambda p: _dotted(p.get("overrides") or {}))


def variants(runs: pd.DataFrame) -> pd.Series:
    """The variant tag of each run, or its algorithm when the tag is ``base``."""
    tags = _params(runs).map(lambda p: p.get("tag", "base"))
    return tags.where(tags != "base", runs["algorithm"])


def _saving(runs: pd.DataFrame) -> pd.DataFrame:
    return runs.assign(saving=100 * (1 - runs["best_s"] / runs["baseline_s"]))


# --- k sweep ---------------------------------------------------------------------------------


def curve(runs: pd.DataFrame) -> pd.DataFrame:
    r = _saving(runs)
    best = r.loc[r.groupby("k")["best_s"].idxmin(), ["k", "stations"]].set_index("k")
    out = r.groupby("k")["saving"].agg(runs="size", mean="mean", min="min", max="max")
    out = out.join(best.rename(columns={"stations": "best_line"}))
    return out.round(2).reset_index()


def plot_k(c: pd.DataFrame, out: Path) -> None:
    fig, (ax,) = fg.axes()
    best = c.loc[c["mean"].idxmax(), "k"]
    fg.band_line(ax, c["k"], c["mean"], c["min"], c["max"],
                 labelled=(c["k"].min(), c["k"].max(), best))  # fmt: skip
    ax.set_xticks(c["k"])
    ax.set_ylim(bottom=0)
    fg.finish(ax, "Metro saving by number of stations", "stations on the line (k)", fg.SAVING)
    fg.save(fig, out, f"USOS demand; no metro = walk or bus / tram (GTFS); "
                      f"mean of {int(c['runs'].max())} seeds, band = min-max")  # fmt: skip


# --- algorithms ------------------------------------------------------------------------------


def check_budget(runs: pd.DataFrame) -> str | None:
    """A warning when the runs do not share one budget: the randomised algorithms with
    different ``eval_budget``, or greedy (which cannot stop halfway) using more than it."""
    rand = runs[runs.algorithm != "greedy"]
    budgets = set(rand["eval_budget"])
    if len(budgets) > 1:
        return f"different budgets: {sorted(budgets)} (stale runs? rerun the experiment)"
    over = runs[(runs.algorithm == "greedy") & (runs.evaluations > max(budgets, default=0))]
    if budgets and len(over):
        return (f"greedy used {int(over.evaluations.max())} evaluations, over the budget "
                f"{max(budgets)}: raise optimize.max_evaluations")  # fmt: skip
    return None


def by_algorithm(runs: pd.DataFrame) -> pd.DataFrame:
    r = _saving(runs).assign(variant=variants(runs))
    g = r.groupby("variant")
    out = g["saving"].agg(runs="size", mean="mean", median="median", min="min", max="max")
    out["evaluations"] = g["evaluations"].mean().round()
    out["best_line"] = r.loc[g["best_s"].idxmin(), ["variant", "stations"]].set_index("variant")
    order = [a for a in ORDER if a in out.index] + sorted(set(out.index) - set(ORDER))
    ref_name = order[0]
    ref = r[r.variant == ref_name].set_index("seed")["saving"]
    p = {}
    for name, grp in g:
        both = pd.concat([ref, grp.set_index("seed")["saving"]], axis=1, join="inner").dropna()
        diff = both.iloc[:, 0] - both.iloc[:, 1]
        p[name] = wilcoxon(diff).pvalue if name != ref_name and (diff != 0).any() else np.nan
    out[f"p_vs_{ref_name}"] = pd.Series(p)
    out = out.loc[order].round({"mean": 2, "median": 2, "min": 2, "max": 2})
    return out.rename_axis("variant").reset_index()


def plot_algorithms(t: pd.DataFrame, runs: pd.DataFrame, out: Path) -> None:
    r = _saving(runs).assign(variant=variants(runs))
    fig, (ax,) = fg.axes(width=max(7.2, len(t) + 1.5))
    fg.dots(ax, [(label(v), r.loc[r.variant == v, "saving"].to_numpy()) for v in t["variant"]])
    fg.finish(ax, "Metro saving by algorithm", ylabel=fg.SAVING)
    k = int(runs["k"].iloc[0])
    budget = int(runs.loc[runs.algorithm != "greedy", "eval_budget"].max())
    fg.save(
        fig,
        out,
        f"USOS demand, k = {k}; {int(t['runs'].max())} seeds, a dot per seed, "
        f"tick = mean; {budget} lines evaluated per run; LS = local search",
    )


def convergence(runs: pd.DataFrame, results: Path, points: int = 120) -> pd.DataFrame:
    """Mean best saving so far at evaluation counts 0..budget, per variant (the colonies
    and random search; greedy is not iterative)."""
    r = runs.assign(variant=variants(runs))
    r = r[r.algorithm.isin(["mmas", "acs", "random"])]
    loaded = {}
    for run in r.itertuples():
        f = results / run.run_id / "convergence.csv"
        if f.exists():
            loaded[run.Index] = CONVERGENCE.read(f)
    if not loaded:
        return pd.DataFrame()
    budget = float(r["eval_budget"].max())
    rows = []
    for v, g in r.groupby("variant"):
        runs_v = [run for run in g.itertuples() if run.Index in loaded]
        if not runs_v:
            continue
        # from the count where every run of the variant has a best line
        start = max(float(loaded[run.Index]["evaluations"].iloc[0]) for run in runs_v)
        grid = np.linspace(start, budget, points)
        curves = []
        for run in runs_v:
            c = loaded[run.Index]
            saving = 100 * (1 - c["best_s"].to_numpy() / run.baseline_s)
            n = np.searchsorted(c["evaluations"].to_numpy(), grid, side="right") - 1
            curves.append(saving[np.maximum(n, 0)])  # best so far at that count
        if curves:
            mean = np.array(curves).mean(axis=0)
            rows += [{"variant": v, "evaluations": e, "mean_saving": m}
                     for e, m in zip(grid, mean, strict=True)]  # fmt: skip
    return pd.DataFrame(rows)


def plot_convergence(c: pd.DataFrame, out: Path) -> None:
    panels = [("without local search", ""), ("with local search", "-ls")]
    fig, axs = fg.axes(2, width=9.6, sharex=True)
    for ax, (title, suffix) in zip(axs, panels, strict=True):
        series = []
        for a in ("mmas", "acs", "random"):
            d = c[c.variant == a + suffix].dropna()
            if len(d):
                series.append((NAMES[a], d.evaluations.to_numpy(), d.mean_saving.to_numpy()))
        if series:
            fg.lines(ax, series)
        fg.finish(ax, title, "distinct lines evaluated", fg.SAVING if not suffix else None)
    fg.save(fig, out, "USOS demand; best saving so far, mean over the seeds (local search: "
                      "from the end of its first descent)")  # fmt: skip


# --- one parameter at a time -------------------------------------------------------------------


def by_parameter(runs: pd.DataFrame) -> pd.DataFrame:
    """(parameter, value) -> savings: the runs that vary it, plus the base runs at its
    config value (read from the run's params)."""
    r = _saving(runs).assign(ov=overrides(runs), params=_params(runs))
    keys = sorted({k for ov in r.ov for k in ov})
    rows = []
    for key in keys:
        name = key.split(".")[-1]
        for run in r.itertuples():
            if run.ov and key not in run.ov:
                continue
            value = run.ov.get(key, run.params.get(name))
            rows.append({"parameter": key, "value": value, "seed": run.seed,
                         "saving": run.saving, "base": not run.ov})  # fmt: skip
    return pd.DataFrame(rows)


def plot_parameters(t: pd.DataFrame, out: Path) -> None:
    keys = list(dict.fromkeys(t["parameter"]))
    cols = min(3, len(keys))
    fig, axs = fg.axes(len(keys), width=3.4 * cols, height=3.2 * -(-len(keys) // cols), cols=cols)
    for ax, key in zip(axs, keys, strict=True):
        d = t[t.parameter == key]
        values = sorted(d["value"].unique())
        groups = []
        for v in values:
            dv = d[d.value == v]
            base = " (base)" if dv["base"].any() else ""
            groups.append((f"{v:g}{base}", dv["saving"].to_numpy()))
        fg.dots(ax, groups)
        fg.finish(ax, key, ylabel=fg.SAVING if ax is axs[0] else None)
    fg.save(fig, out, "MMAS without local search, USOS demand; one parameter changed at a time "
                      "from the base; one dot per seed, tick = mean")  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("experiment", help="experiment name in runs.csv, e.g. k_sweep")
    args = parser.parse_args()
    cfg = load_config()
    results = path(cfg, "results")
    runs = RUNS.read(results / "runs.csv")
    runs = runs[runs["experiment"] == args.experiment].reset_index(drop=True)
    if runs.empty:
        print(f"no runs of {args.experiment!r} in runs.csv", file=sys.stderr)
        return 1
    figures = ROOT / "docs" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    out = figures / args.experiment
    keys = {k for ov in overrides(runs) for k in ov}
    if keys == {"metro.n_stations"}:
        t = curve(runs)
        plot_k(t, out.with_suffix(".png"))
    elif all(k.startswith("optimize.") for k in keys):
        warning = check_budget(runs)
        if warning:
            print(f"WARNING: {warning}", file=sys.stderr)
        t = by_algorithm(runs)
        plot_algorithms(t, runs, out.with_suffix(".png"))
        c = convergence(runs, results)
        if len(c):
            conv = figures / f"{args.experiment}_convergence"
            plot_convergence(c, conv.with_suffix(".png"))
            c.round(3).to_csv(conv.with_suffix(".csv"), index=False, lineterminator="\n")
    else:
        t = by_parameter(runs)
        plot_parameters(t, out.with_suffix(".png"))
        t = t.groupby(["parameter", "value"])["saving"].agg(["size", "mean", "min", "max"])
        t = t.round(2).reset_index()
    t.to_csv(out.with_suffix(".csv"), index=False, lineterminator="\n")
    print(t.to_string(index=False))
    print(f"wrote {out}.png and .csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())

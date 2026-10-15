"""Figure for the report: saving vs number of stations k, from experiments/results/runs.csv.

    uv run scripts/plot_experiments.py k_sweep

Writes docs/figures/<experiment>.png and <experiment>.csv (k, runs, mean / min / max saving
in % of the no-metro objective, and the best line of the best run). One series: the mean
over seeds as a line, the spread over seeds as a band; the gain of each extra station is
the slope.
"""

import argparse
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from metro_agh.config import ROOT, load_config, path  # noqa: E402
from metro_agh.schemas.tables import RUNS  # noqa: E402

# reference palette (dataviz skill): series slot 1, surface and text tokens, light mode
SERIES = "#2a78d6"
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"


def curve(runs: pd.DataFrame) -> pd.DataFrame:
    r = runs.assign(saving=100 * (1 - runs["best_s"] / runs["baseline_s"]))
    best = r.loc[r.groupby("k")["best_s"].idxmin(), ["k", "stations"]].set_index("k")
    out = r.groupby("k")["saving"].agg(runs="size", mean="mean", min="min", max="max")
    out = out.join(best.rename(columns={"stations": "best_line"}))
    return out.round(2).reset_index()


def plot(c: pd.DataFrame, title: str, out) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.fill_between(c["k"], c["min"], c["max"], color=SERIES, alpha=0.18, linewidth=0)
    ax.plot(
        c["k"],
        c["mean"],
        color=SERIES,
        linewidth=2,
        marker="o",
        markersize=6,
        markeredgecolor=SURFACE,
        markeredgewidth=2,
    )
    best = c.loc[c["mean"].idxmax()]
    for _, row in c.iterrows():  # selective labels: ends and the best k
        if row["k"] in (c["k"].min(), c["k"].max(), best["k"]):
            ax.annotate(
                f"{row['mean']:.1f}%",
                (row["k"], row["mean"]),
                xytext=(0, 9),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                color=TEXT,
            )
    ax.set_xticks(c["k"])
    ax.set_xlabel("stations on the line (k)", color=TEXT_2)
    ax.set_ylabel("saving vs no metro (% of student time)", color=TEXT_2)  # walk or bus / tram
    ax.set_title(title, loc="left", color=TEXT, fontsize=11)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_2, length=0)
    ax.set_ylim(bottom=0)
    n = int(c["runs"].max())
    fig.text(
        0.01,
        0.01,
        f"MMAS, USOS demand; no metro = walk or bus / tram (GTFS); "
        f"mean of {n} seeds, band = min-max",
        fontsize=8,
        color=TEXT_2,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("experiment", help="experiment name in runs.csv, e.g. k_sweep")
    args = parser.parse_args()
    cfg = load_config()
    runs = RUNS.read(path(cfg, "results") / "runs.csv")
    runs = runs[runs["experiment"] == args.experiment]
    if runs.empty:
        print(f"no runs of {args.experiment!r} in runs.csv", file=sys.stderr)
        return 1
    c = curve(runs)
    figures = ROOT / "docs" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    c.to_csv(figures / f"{args.experiment}.csv", index=False, lineterminator="\n")
    plot(c, "Metro saving by number of stations", figures / f"{args.experiment}.png")
    print(c.to_string(index=False))
    print(f"wrote {figures / args.experiment}.png and .csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())

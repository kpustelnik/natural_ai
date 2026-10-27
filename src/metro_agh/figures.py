"""Report figures in one style: the dataviz reference palette, light mode, thin marks,
recessive grid, selective direct labels, a footnote saying what is plotted.

Used by ``scripts/plot_experiments.py`` and ``scripts/validate_optimum.py``; each figure
also gets a CSV next to it (the table view).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
# categorical slots 1-3 (blue, orange, aqua), validated all-pairs for light mode with the
# dataviz validator; aqua is below 3:1 on the surface, so lines are always labelled directly
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
SAVING = "saving vs no metro (% of student time)"


def axes(n: int = 1, width: float = 7.2, height: float = 4.2, sharey: bool = True,
         sharex: bool = False, cols=None):  # fmt: skip
    """A figure of ``n`` panels (``cols`` per row, default all in one row)."""
    cols = cols or n
    rows = -(-n // cols)
    fig, axs = plt.subplots(rows, cols, figsize=(width, height), dpi=200, facecolor=SURFACE,
                            sharey=sharey, sharex=sharex, squeeze=False)  # fmt: skip
    flat = list(axs.flat)
    for ax in flat[n:]:
        ax.set_visible(False)
    for ax in flat[:n]:
        ax.set_facecolor(SURFACE)
    return fig, flat[:n]


def finish(ax, title: str | None = None, xlabel: str | None = None, ylabel: str | None = None):
    """Recessive grid and axes: horizontal grid lines only, no frame but the baseline."""
    if title:
        panels = sum(a.get_visible() for a in ax.figure.axes)
        ax.set_title(title, loc="left", color=TEXT, fontsize=11 if panels == 1 else 10)
    if xlabel:
        ax.set_xlabel(xlabel, color=TEXT_2)
    if ylabel:
        ax.set_ylabel(ylabel, color=TEXT_2)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_2, length=0)


def save(fig, out: Path, note: str) -> None:
    fig.text(0.01, 0.01, note, fontsize=8, color=TEXT_2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def label(ax, x: float, y: float, text: str, dy: float = 8) -> None:
    ax.annotate(text, (x, y), xytext=(0, dy), textcoords="offset points", ha="center",
                fontsize=9, color=TEXT)  # fmt: skip


def band_line(ax, x, mean, lo, hi, labelled: Sequence = ()) -> None:
    """One series: the mean as a line with markers, the spread (min-max) as a band, labels
    on the points ``labelled`` only."""
    ax.fill_between(x, lo, hi, color=SERIES[0], alpha=0.18, linewidth=0)
    ax.plot(x, mean, color=SERIES[0], linewidth=2, marker="o", markersize=6,
            markeredgecolor=SURFACE, markeredgewidth=2)  # fmt: skip
    for xi, yi in zip(x, mean, strict=True):
        if xi in labelled:
            label(ax, xi, yi, f"{yi:.1f}%", dy=9)


def dots(ax, groups: Sequence[tuple[str, np.ndarray]], texts: Sequence[str] | None = None):
    """One column per group: a dot per run (jittered when they differ), the mean as a tick,
    and a label above the column (default: the mean in %)."""
    jitter = np.random.default_rng(0)  # fixed, so a figure does not change between runs
    for x, (_, v) in enumerate(groups):
        v = np.asarray(v, dtype=float)
        xs = x + jitter.uniform(-0.18, 0.18, len(v)) if np.ptp(v) > 0 else np.full(len(v), x)
        ax.scatter(xs, v, s=22, color=SERIES[0], alpha=0.55, edgecolors=SURFACE, linewidths=1)
        mean = float(v.mean())
        ax.plot([x - 0.3, x + 0.3], [mean, mean], color=TEXT, linewidth=2)
        text = texts[x] if texts is not None else f"{mean:.1f}%"
        label(ax, x, max(float(v.max()), mean), text)  # above the dots: labels never meet
    ax.margins(y=0.14)
    ax.set_xticks(range(len(groups)), [g for g, _ in groups])
    ax.set_xlim(-0.6, len(groups) - 0.4)


def lines(ax, series: Sequence[tuple[str, np.ndarray, np.ndarray]]) -> None:
    """Up to three series in categorical order, each labelled at its end (no legend box
    needed, and the low-contrast slot is never colour-alone)."""
    if len(series) > len(SERIES):
        raise ValueError(f"at most {len(SERIES)} series, got {len(series)}: facet instead")
    for (_, x, y), color in zip(series, SERIES, strict=False):
        ax.plot(x, y, color=color, linewidth=2)
    # end labels, pushed apart where the lines end close together (in axis units, which
    # with shared axes span the other panels too)
    lo, hi = ax.get_ylim()
    gap = 0.05 * (hi - lo)
    ends = sorted(((float(y[-1]), i) for i, (_, _, y) in enumerate(series)), reverse=True)
    placed: list[float] = []
    for y_end, i in ends:
        y_text = min(y_end, placed[-1] - gap) if placed else y_end
        placed.append(y_text)
        name, x, _ = series[i]
        x_text = x[-1] + 0.015 * (x[-1] - x[0])
        ax.annotate(name, (x[-1], y_end), xytext=(x_text, y_text), textcoords="data",
                    ha="left", va="center", fontsize=9, color=TEXT)  # fmt: skip
    ax.margins(x=0.12)

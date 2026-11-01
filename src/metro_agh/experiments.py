"""Parameter sweeps / ablations over ``config.yaml``.

An experiment YAML (``experiments/configs/*.yaml``) names the study, lists seeds, and
declares either explicit ``variants`` or a ``sweep`` of dotted keys. Each expanded job
runs the configured algorithm (``optimize.algorithm``) once, writes
``experiments/results/<run_id>/``, and appends ``runs.csv``.
"""

from __future__ import annotations

import itertools
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import yaml

from .aco.common import RunResult
from .aco.objective import teleport_bound
from .config import merge_config, path, provenance
from .optimize import run_algorithm
from .schemas.instance import Instance
from .schemas.results import BestLine, RunMeta
from .schemas.tables import CONVERGENCE, RUNS

log = logging.getLogger("experiments")
GENERATOR = "run_experiments.py"

Mode = Literal["ablation", "grid", "variants"]

# short tags in run_id when these keys are the only ones that differ
_SHORT = {
    "aco.alpha": "a",
    "aco.beta": "b",
    "aco.rho": "r",
    "aco.n_ants": "ants",
    "aco.n_iterations": "it",
    "aco.tau_min_ratio": "tmin",
    "metro.n_stations": "k",
    "optimize.algorithm": "",
}


@dataclass(frozen=True)
class Job:
    """One optimiser run: experiment name, variant tag, seed, config overrides."""

    experiment: str
    tag: str
    seed: int
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    seeds: tuple[int, ...]
    mode: Mode
    defaults: dict[str, Any]
    sweep: dict[str, list[Any]]
    variants: tuple[tuple[str, dict[str, Any]], ...]
    processed: str | None
    save_trace: bool
    description: str = ""


def get_path(cfg: dict, dotted: str) -> Any:
    cur: Any = cfg
    for part in dotted.split("."):
        cur = cur[part]
    return cur


def set_path(cfg: dict, dotted: str, value: Any) -> dict:
    """A copy of ``cfg`` with ``dotted`` set to ``value``: the dicts along the path are
    copied, the rest is shared with ``cfg`` (nothing here mutates it)."""
    parts = dotted.split(".")
    out = dict(cfg)
    node = out
    for part in parts[:-1]:
        child = dict(node.get(part, {}))
        node[part] = child
        node = child
    node[parts[-1]] = value
    return out


def apply_overrides(cfg: dict, overrides: dict[str, Any]) -> dict:
    """``overrides`` may be nested dicts or dotted keys (``aco.alpha``)."""
    out = cfg
    dotted: dict[str, Any] = {}
    nested: dict[str, Any] = {}
    for key, value in overrides.items():
        if "." in key:
            dotted[key] = value
        else:
            nested[key] = value
    if nested:
        out = merge_config(out, nested)
    for key, value in dotted.items():
        if isinstance(value, dict):  # aco.trace: {every: 1} merges into aco.trace
            try:
                current = get_path(out, key)
            except (KeyError, TypeError):
                current = None
            if isinstance(current, dict):
                value = merge_config(current, value)
        out = set_path(out, key, value)
    return out


def _slug(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = str(value).replace(".", "p")
    s = re.sub(r"[^A-Za-z0-9p_-]+", "", s)
    return s or "x"


def _tag_for(changes: dict[str, Any]) -> str:
    if not changes:
        return "base"
    parts = []
    for key in sorted(changes):
        short = _SHORT.get(key, key.split(".")[-1])
        parts.append(f"{short}{_slug(changes[key])}")
    return "-".join(parts)


def load_experiment(path: str | Path) -> ExperimentSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or "name" not in raw:
        raise ValueError(f"{path}: experiment YAML needs a 'name'")
    seeds = raw.get("seeds") or [raw.get("seed")]
    if not seeds or seeds == [None]:
        raise ValueError(f"{path}: set seeds: [42, …] (or seed: 42)")
    mode = raw.get("mode", "variants" if raw.get("variants") else "ablation")
    if mode not in ("ablation", "grid", "variants"):
        raise ValueError(f"{path}: mode must be ablation|grid|variants, got {mode!r}")
    sweep = {str(k): list(v) for k, v in (raw.get("sweep") or {}).items()}
    variants_raw = raw.get("variants") or []
    variants = []
    for v in variants_raw:
        body = v.get("overrides") or {k: val for k, val in v.items() if k != "name"}
        variants.append((str(v["name"]), dict(body)))
    variants = tuple(variants)
    return ExperimentSpec(
        name=str(raw["name"]),
        seeds=tuple(int(s) for s in seeds),
        mode=mode,  # type: ignore[arg-type]
        defaults=dict(raw.get("defaults") or {}),
        sweep=sweep,
        variants=variants,
        processed=raw.get("processed"),
        save_trace=bool(raw.get("save_trace", False)),
        description=str(raw.get("description") or ""),
    )


def expand_jobs(spec: ExperimentSpec, baseline_cfg: dict | None = None) -> list[Job]:
    """Expand an experiment into concrete (tag, overrides, seed) jobs.

    When ``baseline_cfg`` is given (config + defaults), ablation points that equal the
    baseline value are skipped so they do not duplicate ``base``.
    """
    combos: list[tuple[str, dict[str, Any]]] = []
    if spec.mode == "variants":
        if not spec.variants:
            combos.append(("base", {}))
        else:
            combos.extend(spec.variants)
    elif spec.mode == "ablation":
        combos.append(("base", {}))
        for key, values in spec.sweep.items():
            base_val = None
            if baseline_cfg is not None:
                try:
                    base_val = get_path(baseline_cfg, key)
                except (KeyError, TypeError):
                    base_val = None
            for value in values:
                if base_val is not None and value == base_val:
                    continue
                changes = {key: value}
                combos.append((_tag_for(changes), changes))
    elif spec.mode == "grid":
        if not spec.sweep:
            combos.append(("base", {}))
        else:
            keys = list(spec.sweep)
            for values in itertools.product(*(spec.sweep[k] for k in keys)):
                changes = dict(zip(keys, values, strict=True))
                combos.append((_tag_for(changes), changes))
    else:
        raise ValueError(spec.mode)

    jobs: list[Job] = []
    for tag, overrides in combos:
        for seed in spec.seeds:
            jobs.append(Job(spec.name, tag, seed, overrides))
    return jobs


def evaluations_to_best(convergence: pd.DataFrame) -> int:
    if convergence.empty:
        return 0
    best = float(convergence["best_s"].iloc[-1])
    # exact: best_s carries best_cost unchanged, and isclose's rtol would match a best ~100 s
    # above the final one at these magnitudes (1e7 s)
    hit = convergence.loc[convergence["best_s"] == best, "evaluations"]
    return int(hit.iloc[0]) if len(hit) else int(convergence["evaluations"].iloc[-1])


def run_id_for(job: Job, algorithm: str, k: int) -> str:
    return f"{job.experiment}-{job.tag}-{algorithm}-k{k}-s{job.seed}"


def append_runs_csv(results_dir: Path, row: dict[str, Any]) -> None:
    """Append (or replace same ``run_id``) one row in ``runs.csv``."""
    path = results_dir / "runs.csv"
    new = pd.DataFrame([row], columns=RUNS.column_names)
    if path.exists():
        old = RUNS.read(path)
        old = old[old["run_id"] != row["run_id"]]
        df = pd.concat([old, new], ignore_index=True)
    else:
        df = new
    # enforce dtypes the contract expects
    df["stations"] = df["stations"].astype("string")
    df["params_json"] = df["params_json"].astype("string")
    df["experiment"] = df["experiment"].astype("string")
    df["algorithm"] = df["algorithm"].astype("string")
    df["topology"] = df["topology"].astype("string")
    df["run_id"] = df["run_id"].astype("string")
    write_runs_csv(df, results_dir)


def write_runs_csv(df: pd.DataFrame, results_dir: Path) -> None:
    """``runs.csv``, written next to it and then swapped in: a sweep of hundreds of runs must
    not die (or leave a half-written file) because another program briefly holds it
    (seen on Windows as EINVAL), so the swap is retried."""
    path = Path(results_dir) / "runs.csv"
    tmp = path.with_name("runs.part.csv")  # the suffix picks the format
    RUNS.write(df, tmp)
    for attempt in range(20):
        try:
            tmp.replace(path)
            return
        except OSError:  # a lock shows up as PermissionError or EINVAL
            if attempt == 19:
                raise
            time.sleep(0.5)


def save_run(
    *,
    cfg: dict,
    inst: Instance,
    inst_path: Path,
    result: RunResult,
    job: Job,
    wall_s: float,
    results_dir: Path,
    save_trace: bool,
    update_best_line: bool,
) -> RunMeta:
    stations = [str(inst.candidate_ids[i]) for i in result.best_line]
    algorithm = result.algorithm
    rid = run_id_for(job, algorithm, int(inst.meta.k))
    run_dir = results_dir / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    prov = provenance(GENERATOR, cfg)
    best = BestLine(
        provenance=prov,
        run_id=rid,
        topology=inst.meta.topology,
        stations=stations,
        objective_s=round(result.best_cost, 1),
        baseline_s=round(result.objective.baseline, 1),
        lower_bound_s=round(teleport_bound(inst), 1),
    )
    meta = RunMeta(
        provenance=prov,
        run_id=rid,
        experiment=job.experiment,
        algorithm=algorithm,
        instance=str(inst_path.as_posix()),
        instance_hash=inst.meta.source_hash or "",
        seed=job.seed,
        params={**result.params, "overrides": job.overrides, "tag": job.tag},
        eval_budget=result.eval_budget,
        evaluations=max(1, result.objective.evaluations),
        wall_time_s=round(wall_s, 2),
        best=best,
    )
    (run_dir / "run.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    CONVERGENCE.write(result.convergence, run_dir / "convergence.csv")
    if save_trace and result.trace is not None:
        result.trace.save(run_dir / "trace.npz")
    if update_best_line:
        best_path = results_dir / "best_line.json"
        best_path.write_text(best.model_dump_json(indent=2), encoding="utf-8")

    append_runs_csv(
        results_dir,
        {
            "run_id": rid,
            "experiment": job.experiment,
            "algorithm": algorithm,
            "topology": inst.meta.topology,
            "k": int(inst.meta.k),
            "n_candidates": int(inst.n_candidates),
            "seed": job.seed,
            "eval_budget": meta.eval_budget,
            "evaluations": meta.evaluations,
            "evaluations_to_best": evaluations_to_best(result.convergence),
            "best_s": float(best.objective_s),
            "baseline_s": float(best.baseline_s),
            "optimum_s": float(best.objective_s) if algorithm == "brute_force" else math.nan,
            "wall_time_s": float(meta.wall_time_s),
            "stations": "|".join(stations),
            "params_json": json.dumps(meta.params, sort_keys=True),
        },
    )
    return meta


# config keys the instance arrays are computed from (network.instance.inputs_hash): a job
# cannot change them, since every job of an experiment shares one instance
ARRAY_KEYS = ("time_model", "demand", "population", "simulation.transit", "metro.station_depth_m")


def _dotted(d: dict[str, Any], prefix: str = "") -> list[str]:
    out = []
    for k, v in d.items():
        key = f"{prefix}{k}"
        out += _dotted(v, key + ".") if isinstance(v, dict) else [key]
    return out


def check_overrides(overrides: dict[str, Any]) -> None:
    """Raise for overrides an experiment cannot apply (they need another instance: run them
    as separate experiments with their own ``processed`` dir)."""
    bad = [
        k for k in _dotted(overrides) if any(k == a or k.startswith(a + ".") for a in ARRAY_KEYS)
    ]
    if bad:
        raise ValueError(
            f"{bad} change the instance arrays, which every job shares; metro.* (k, speed, "
            "dwell, headway, topology, candidates), aco.* and optimize.* can vary"
        )


def execute_job(
    job: Job,
    *,
    base_cfg: dict,
    defaults: dict[str, Any],
    inst: Instance,
    inst_path: Path,
    results_dir: Path,
    save_trace: bool,
    update_best_line: bool = False,
) -> RunMeta:
    check_overrides(defaults)
    check_overrides(job.overrides)
    cfg = apply_overrides(apply_overrides(base_cfg, defaults), job.overrides)
    cfg = {**cfg, "seed": job.seed}
    # metro.* (k, speed, dwell, headway, topology) only change the instance's meta, a
    # candidate list takes a subset of its columns
    from .network.instance import with_config

    inst = with_config(inst, cfg)
    t0 = time.perf_counter()
    result = run_algorithm(inst, cfg, rng=np.random.default_rng(job.seed))
    wall = time.perf_counter() - t0
    meta = save_run(
        cfg=cfg,
        inst=inst,
        inst_path=inst_path,
        result=result,
        job=job,
        wall_s=wall,
        results_dir=results_dir,
        save_trace=save_trace,
        update_best_line=update_best_line,
    )
    saving = 100 * (1 - result.best_cost / result.objective.baseline)
    log.info(
        "done %s: %.1f (%.1f%% below baseline), %.1f s",
        meta.run_id,
        result.best_cost,
        saving,
        wall,
    )
    return meta


def summarise(results_dir: Path, experiment: str) -> pd.DataFrame | None:
    """Per-tag means for one experiment; improvement vs that experiment's ``base`` tag."""
    csv_path = results_dir / "runs.csv"
    if not csv_path.exists():
        return None
    df = RUNS.read(csv_path)
    df = df[df["experiment"] == experiment].copy()
    if df.empty:
        return None

    def _tag(s: str) -> str:
        try:
            return str(json.loads(s).get("tag", "?"))
        except (TypeError, json.JSONDecodeError):
            return "?"

    df["tag"] = df["params_json"].map(_tag)
    df["improvement"] = 1.0 - df["best_s"] / df["baseline_s"]
    g = (
        df.groupby("tag", sort=False)
        .agg(
            n=("run_id", "count"),
            mean_best_s=("best_s", "mean"),
            std_best_s=("best_s", "std"),
            mean_improvement=("improvement", "mean"),
            mean_wall_s=("wall_time_s", "mean"),
        )
        .reset_index()
    )
    base = g.loc[g["tag"] == "base", "mean_best_s"]
    base_v = float(base.iloc[0]) if len(base) else math.nan
    g["delta_vs_base_s"] = g["mean_best_s"] - base_v
    g["delta_vs_base_pct"] = g["mean_best_s"] / base_v - 1.0 if base_v else math.nan
    out = results_dir / f"summary_{experiment}.csv"
    g.to_csv(out, index=False, lineterminator="\n")
    log.info("wrote %s", out)
    return g


def resolve_instance(cfg: dict, processed: Path | None, rebuild: bool) -> tuple[Instance, Path]:
    from .network.instance import load_or_build

    root = Path(processed) if processed else path(cfg, "processed")
    inst_path = root / "instance" / "instance.npz"
    name = "fake" if root.name == "fake" else "campus"
    return load_or_build(root, cfg, inst_path, rebuild=rebuild, name=name), inst_path

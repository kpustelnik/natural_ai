"""Experiment YAML expansion and runs.csv append."""

import json
from pathlib import Path

import numpy as np
import pytest

from metro_agh.aco import run_mmas
from metro_agh.experiments import (
    Job,
    append_runs_csv,
    apply_overrides,
    expand_jobs,
    load_experiment,
    save_run,
)
from metro_agh.schemas.instance import Instance, InstanceMeta
from metro_agh.schemas.tables import RUNS


def _toy() -> Instance:
    ids = np.array(["A", "B", "C", "D"], dtype=object)
    xyz = np.array([[0, 0, 0], [400, 0, 0], [800, 0, 0], [1200, 0, 0]], float)
    tunnel = np.array(
        [
            [0, 400, 800, 1200],
            [400, 0, 400, 800],
            [800, 400, 0, 400],
            [1200, 800, 400, 0],
        ],
        np.float32,
    )
    access = np.full((4, 4), np.inf, np.float32)
    np.fill_diagonal(access, 0.0)
    return Instance(
        meta=InstanceMeta(
            name="toy",
            topology="line",
            k=3,
            metro_speed_mps=10.0,
            dwell_s=30.0,
            wait_s=90.0,
            shaft_down_s=40.0,
            shaft_up_s=35.0,
        ),
        candidate_ids=ids,
        candidate_xyz=xyz,
        tunnel_m=tunnel,
        endpoint_keys=ids,
        access_s=access,
        egress_s=access.copy(),
        od_from=np.array([0, 3], np.int32),
        od_to=np.array([3, 0], np.int32),
        od_weight=np.array([100.0, 100.0], np.float32),
        od_walk_s=np.array([900, 900], np.float32),
    )


def test_ablation_skips_baseline_values(tmp_path: Path):
    path = tmp_path / "ablation.yaml"
    path.write_text(
        """
name: demo
mode: ablation
seeds: [1, 2]
sweep:
  aco.alpha: [0.5, 1.0, 2.0]
  aco.beta: [1.0, 3.0]
""",
        encoding="utf-8",
    )
    spec = load_experiment(path)
    baseline = {"aco": {"alpha": 1.0, "beta": 3.0}}
    jobs = expand_jobs(spec, baseline_cfg=baseline)
    tags = sorted({j.tag for j in jobs})
    assert "base" in tags
    assert "a0p5" in tags and "a2" in tags
    assert "a1" not in tags  # equals baseline alpha
    assert "b1" in tags
    assert "b3" not in tags  # equals baseline beta
    assert len(jobs) == 4 * 2  # base + 3 variants × 2 seeds


def test_grid_cartesian():
    path = Path("experiments/configs/aco_grid.yaml")
    spec = load_experiment(path)
    jobs = expand_jobs(spec)
    assert len(jobs) == 3 * 3 * len(spec.seeds)
    assert all(j.experiment == "aco_grid" for j in jobs)


def test_apply_overrides_dotted_and_nested():
    cfg = {"aco": {"alpha": 1.0, "beta": 3.0}, "seed": 1}
    out = apply_overrides(cfg, {"aco.alpha": 2.0, "aco": {"rho": 0.2}})
    assert out["aco"]["alpha"] == 2.0
    assert out["aco"]["beta"] == 3.0
    assert out["aco"]["rho"] == 0.2
    # a dotted key with a dict value merges into that sub-dict
    cfg = {"aco": {"trace": {"every": 5, "max_ants": 50}}}
    out = apply_overrides(cfg, {"aco.trace": {"every": 1}})
    assert out["aco"]["trace"] == {"every": 1, "max_ants": 50}


def test_brute_force_run_records_the_optimum(tmp_path: Path):
    from metro_agh.optimize import run_algorithm

    inst = _toy()
    cfg = {"seed": 0, "optimize": {"algorithm": "brute_force"}}
    result = run_algorithm(inst, cfg)
    meta = save_run(
        cfg=cfg,
        inst=inst,
        inst_path=tmp_path / "instance.npz",
        result=result,
        job=Job("gap", "base", 0, {}),
        wall_s=0.01,
        results_dir=tmp_path,
        save_trace=True,  # nothing to save: no pheromone
        update_best_line=False,
    )
    assert meta.algorithm == "brute_force" and "brute_force" in meta.run_id
    assert not (tmp_path / meta.run_id / "trace.npz").exists()
    row = RUNS.read(tmp_path / "runs.csv").iloc[0]
    assert row["optimum_s"] == row["best_s"]
    assert row["eval_budget"] == row["evaluations"] == result.params["n_lines"]


def test_save_run_appends_runs_csv(tmp_path: Path):
    inst = _toy()
    cfg = {
        "seed": 0,
        "aco": {
            "variant": "mmas",
            "n_ants": 5,
            "n_iterations": 5,
            "alpha": 1.0,
            "beta": 2.0,
            "rho": 0.1,
            "tau_min_ratio": 0.01,
            "trace": {"every": 5, "max_ants": 5},
        },
    }
    result = run_mmas(inst, cfg, rng=np.random.default_rng(0))
    job = Job("unit", "base", 0, {})
    meta = save_run(
        cfg=cfg,
        inst=inst,
        inst_path=tmp_path / "instance.npz",
        result=result,
        job=job,
        wall_s=0.01,
        results_dir=tmp_path,
        save_trace=False,
        update_best_line=False,
    )
    assert (tmp_path / meta.run_id / "run.json").exists()
    assert (tmp_path / meta.run_id / "convergence.csv").exists()
    assert not (tmp_path / meta.run_id / "trace.npz").exists()
    df = RUNS.read(tmp_path / "runs.csv")
    assert len(df) == 1
    assert df.iloc[0]["experiment"] == "unit"
    params = json.loads(df.iloc[0]["params_json"])
    assert params["tag"] == "base"

    # replace same run_id
    append_runs_csv(
        tmp_path,
        {c: df.iloc[0][c] for c in RUNS.column_names} | {"wall_time_s": 1.5},
    )
    df2 = RUNS.read(tmp_path / "runs.csv")
    assert len(df2) == 1
    assert float(df2.iloc[0]["wall_time_s"]) == 1.5


def test_metro_overrides_reach_the_run(tmp_path: Path):
    """metro.* of a job (k, dwell, ...) apply to a cached instance: a k sweep is real."""
    from metro_agh.config import load_config
    from metro_agh.experiments import execute_job

    base = load_config()
    defaults = {"aco": {"n_ants": 4, "n_iterations": 3, "trace": {"every": 1, "max_ants": 4}}}
    metas = {
        k: execute_job(
            Job("unit", f"k{k}", 0, {"metro.n_stations": k, "metro.dwell_s": 5.0 * k}),
            base_cfg=base,
            defaults=defaults,
            inst=_toy(),
            inst_path=tmp_path / "instance.npz",
            results_dir=tmp_path,
            save_trace=False,
        )
        for k in (2, 4)
    }
    assert [len(m.best.stations) for m in metas.values()] == [2, 4]
    runs = RUNS.read(tmp_path / "runs.csv").set_index("run_id")
    assert sorted(runs["k"]) == [2, 4]
    # the dwell of each job is in its objective: the best line costs what it costs with it
    from metro_agh.aco.objective import Objective
    from metro_agh.network.instance import with_config

    for k, m in metas.items():
        cfg = {**base, "metro": {**base["metro"], "n_stations": k, "dwell_s": 5.0 * k}}
        inst = with_config(_toy(), cfg)
        ids = [str(c) for c in inst.candidate_ids]
        line = [ids.index(s) for s in m.best.stations]
        assert m.best.objective_s == pytest.approx(Objective(inst)(line), abs=0.1)
        assert inst.meta.dwell_s == 5.0 * k


def test_overrides_that_change_the_instance_are_refused():
    from metro_agh.experiments import check_overrides

    check_overrides({"aco.alpha": 2.0, "metro": {"n_stations": 6, "candidates": ["A", "B"]}})
    with pytest.raises(ValueError, match="time_model.walk_mps"):
        check_overrides({"time_model": {"walk_mps": 1.0}})
    with pytest.raises(ValueError, match="simulation.transit"):
        check_overrides({"simulation.transit": False})

"""Train timetable and the metro / ACO replays (synthetic run from --fake)."""

import json

import numpy as np
import pytest

from metro_agh.config import load_config
from metro_agh.schemas.results import AcoTrace, BestLine, load_json
from metro_agh.schemas.tables import METRO_SCHEDULE
from metro_agh.schemas.web import AcoTraceHeader, Metro, Replay, ReplayCatalog
from metro_agh.simulation.schedule import build_schedule as schedule
from metro_agh.simulation.schedule import hhmm, station_order
from metro_agh.web.export_campus import write_replay_catalog
from metro_agh.web.export_metro import export_aco_run, export_best_line, load_scene
from metro_agh.web.fake import write_fake_results
from test_web_export import exported  # noqa: F401  (fixture: the sample campus export)

CFG = load_config()


def test_station_order():
    assert station_order(3, "line", 1) == [0, 1, 2]
    assert station_order(3, "line", -1) == [2, 1, 0]
    assert station_order(4, "loop", 1) == [0, 1, 2, 3, 0]
    assert station_order(4, "loop", -1) == [0, 3, 2, 1, 0]


def test_line_schedule():
    platforms = np.array([[0.0, 0.0], [500.0, 0.0], [500.0, 300.0]])
    df = schedule(["A-0", "B-1", "C-2"], platforms, "line", CFG, weekdays=[2])
    METRO_SCHEDULE.validate(df)
    m = CFG["metro"]
    start, end = hhmm(m["service"]["start"]), hhmm(m["service"]["end"])
    runs = df.groupby("run_id")
    assert runs.ngroups == 2 * (int((end - start) // m["headway_s"]) + 1)  # both directions
    first = df[df.run_id == 0].sort_values("stop_seq")
    assert first.station.tolist() == ["A-0", "B-1", "C-2"]
    base = 86400 + start  # Tuesday
    assert first.depart_wt.iloc[0] == base
    assert first.arrive_wt.iloc[1] == base + round(500 / m["speed_mps"])
    assert first.depart_wt.iloc[1] - first.arrive_wt.iloc[1] == m["dwell_s"]
    assert first.arrive_wt.iloc[2] == first.depart_wt.iloc[2]  # no dwell at the terminus
    # trains are reused after a run: far fewer physical trains than runs
    assert df.train_id.nunique() < runs.ngroups / 10


@pytest.fixture(scope="module")
def replays(exported, tmp_path_factory):  # noqa: F811
    out, _ = exported
    root = tmp_path_factory.mktemp("fake")
    run_dir = write_fake_results(load_scene(out), CFG, root, seed=3)
    changed: list[str] = []
    aco = export_aco_run(CFG, run_dir, out, changed, note="test")
    line = export_best_line(CFG, root / "results" / "best_line.json", out, changed)
    write_replay_catalog(out, CFG)
    return out, run_dir, aco, line, changed


def test_fake_results_follow_contracts(replays):
    _, run_dir, *_ = replays
    trace = AcoTrace.load(run_dir / "trace.npz")
    best = load_json(BestLine, run_dir.parent / "best_line.json")
    assert best.objective_s < best.baseline_s  # the metro helps somebody
    assert trace.iterations[0] == 0 and (np.diff(trace.iterations) > 0).all()


def test_aco_replay(replays):
    out, run_dir, aco, _, changed = replays
    assert aco.kind == "aco" and aco.id.startswith("aco-")
    header = AcoTraceHeader.model_validate_json((out / aco.files.aco_trace).read_text("utf-8"))
    n = len(header.candidate_ids)
    i, a, k = header.buffers["tours"].shape
    assert header.buffers["pheromone"].shape == [i, n, n] and k == header.k
    assert len(header.candidate_tops) == len(header.candidate_platforms) == n
    depth = CFG["metro"]["station_depth_m"]
    assert header.candidate_tops[0][1] - header.candidate_platforms[0][1] == pytest.approx(depth)
    c = header.buffers["curve_iteration"].count
    assert c == header.n_iterations  # convergence.csv has every iteration
    assert f"{aco.files.aco_trace[:-5]}.bin" in changed
    metro = Metro.model_validate_json((out / aco.files.metro).read_text("utf-8"))
    assert [s.building_id for s in metro.stations] == header.stations == aco.stations


def test_line_replay_and_catalog(replays):
    out, _, aco, line, _ = replays
    assert line.kind == "simulation" and line.files.metro and not line.files.trips
    metro = Metro.model_validate_json((out / line.files.metro).read_text("utf-8"))
    assert len(metro.tunnel) == len(metro.stations) + (metro.topology == "loop")
    assert {r.weekday for r in metro.runs} == set(CFG["simulation"]["weekdays"])
    run = metro.runs[0]
    assert all(a.depart_t <= b.arrive_t for a, b in zip(run.stops, run.stops[1:], strict=False))
    cat = ReplayCatalog.model_validate_json((out / "replays/index.json").read_text("utf-8"))
    assert {aco.id, line.id} <= {r.id for r in cat.replays}
    Replay.model_validate(json.loads((out / f"replays/{line.id}/replay.json").read_text("utf-8")))


def test_acs_run_replays_too(replays, tmp_path):
    """The viewer's ACO replay takes any colony's trace: an ACS run exports the same way."""
    from metro_agh.experiments import Job, save_run
    from metro_agh.optimize import run_algorithm
    from metro_agh.web.fake import fake_instance

    out = replays[0]
    rng = np.random.default_rng(0)
    inst = fake_instance(load_scene(out), CFG, rng)
    cfg = {**CFG, "optimize": {"algorithm": "acs", "local_search": True},
           "aco": {**CFG["aco"], "n_ants": 8, "n_iterations": 6}}  # fmt: skip
    result = run_algorithm(inst, cfg, rng)
    meta = save_run(cfg=cfg, inst=inst, inst_path=tmp_path / "i.npz", result=result,
                    job=Job("t", "base", 0), wall_s=0.1, results_dir=tmp_path,
                    save_trace=True, update_best_line=False)  # fmt: skip
    replay = export_aco_run(CFG, tmp_path / meta.run_id, out, [])
    assert replay.title.startswith("ACS")
    header = AcoTraceHeader.model_validate_json((out / replay.files.aco_trace).read_text("utf-8"))
    assert header.algorithm == "acs" and header.n_iterations == 6

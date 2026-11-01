"""Metro and ACO replays (docs/data_contracts.md, sections 10.6 and 10.10).

    --aco     every ``results/<run_id>/`` with a trace.npz -> ``replays/aco-<run_id>/``:
              trace.json + .bin (AcoTraceHeader), metro.json (its best line), replay.json
    --metro   ``results/best_line.json`` -> ``replays/sim-<run_id>/``: metro.json and a
              replay.json of kind ``simulation`` (``--sim`` adds the students later)

Station positions come from scene.json (the main entrance with ``metro_shaft``), so the
campus export must run first. The trains follow ``simulation/metro/schedule.parquet`` when
it exists for the same line, else a timetable built from the config (``schedule.py``).
"""

import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import provenance
from ..schemas.results import AcoTrace, BestLine, RunMeta, load_json
from ..schemas.tables import CONVERGENCE, METRO_SCHEDULE
from ..schemas.web import (
    AcoTraceHeader,
    Metro,
    MetroStation,
    Replay,
    ReplayFiles,
    RunStop,
    Scene,
    TrainRun,
)
from ..simulation.schedule import DAY_S, build_schedule, station_order
from .binary import write_binary
from .export_campus import GENERATOR, _vec3

log = logging.getLogger(__name__)


def replay_id(prefix: str, run_id: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", f"{prefix}-{run_id}".lower()).strip("-")


def load_scene(out_dir: Path) -> Scene:
    f = Path(out_dir) / "scene.json"
    if not f.exists():
        raise FileNotFoundError(f"{f} missing: run 06_export_web.py --campus first")
    return Scene.model_validate_json(f.read_text(encoding="utf-8"))


def shafts(scene: Scene, ids: list[str], depth: float) -> tuple[list, list]:
    """Shaft tops (metro_shaft entrance, else the main one) and platforms, web frame."""
    by_id = {b.id: b for b in scene.buildings}
    tops, platforms = [], []
    for bid in ids:
        b = by_id.get(bid)
        if b is None or not b.entrances:
            raise ValueError(f"station {bid}: no such building with entrances in scene.json")
        e = next((e for e in b.entrances if e.metro_shaft), None) or next(
            (e for e in b.entrances if e.main), b.entrances[0]
        )
        x, y, z = e.position
        tops.append(_vec3((x, y, z)))
        platforms.append(_vec3((x, y - depth, z)))
    return tops, platforms


def metro_model(
    scene: Scene,
    cfg: dict,
    topology: str,
    stations: list[str],
    schedule: pd.DataFrame | None = None,
) -> Metro:
    m = cfg["metro"]
    tops, platforms = shafts(scene, stations, float(m["station_depth_m"]))
    if schedule is None:
        xz = np.asarray(platforms)[:, [0, 2]]
        schedule = build_schedule(stations, xz, topology, cfg)
    index = {s: i for i, s in enumerate(stations)}
    runs = []
    for (run, train, day, direction), g in schedule.groupby(
        ["run_id", "train_id", "weekday", "direction"], sort=True
    ):
        g = g.sort_values("stop_seq")
        base = (int(day) - 1) * DAY_S
        runs.append(
            TrainRun(
                run_id=int(run),
                train_id=int(train),
                weekday=int(day),
                direction=int(direction),
                stops=[
                    RunStop(station=index[s], arrive_t=float(a - base), depart_t=float(d - base))
                    for s, a, d in zip(g.station, g.arrive_wt, g.depart_wt, strict=True)
                ],
            )
        )
    tunnel = [*platforms, platforms[0]] if topology == "loop" else list(platforms)
    return Metro(
        provenance=provenance(GENERATOR, cfg),
        topology=topology,
        stations=[
            MetroStation(building_id=s, top=t, platform=p)
            for s, t, p in zip(stations, tops, platforms, strict=True)
        ],
        tunnel=tunnel,
        headway_s=float(m["headway_s"]),
        dwell_s=float(m["dwell_s"]),
        speed_mps=float(m["speed_mps"]),
        runs=runs,
    )


def _write(out_dir: Path, rel: str, model, changed: list[str]) -> str:
    p = out_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(model.model_dump_json(), encoding="utf-8")
    changed.append(rel)
    return rel


def _curve(trace: AcoTrace, conv: pd.DataFrame | None) -> dict[str, np.ndarray]:
    if conv is not None and len(conv):
        c = conv.sort_values("iteration")
        it, best = c.iteration.to_numpy(), c.best_s.to_numpy()
        ib, im = c.iter_best_s.to_numpy(), c.iter_mean_s.to_numpy()
    else:  # only the sampled ants are known
        it = trace.iterations
        ib = trace.tour_cost_s.min(axis=1)
        im = trace.tour_cost_s.mean(axis=1)
        best = np.minimum.accumulate(ib)
    return {
        "curve_iteration": it.astype(np.int32),
        "curve_best_s": best.astype(np.float32),
        "curve_iter_best_s": ib.astype(np.float32),
        "curve_iter_mean_s": im.astype(np.float32),
    }


def export_aco_run(
    cfg: dict, run_dir: Path, out_dir: Path, changed: list[str], note: str | None = None
) -> Replay:
    """One optimisation run with a trace -> replays/aco-<run_id>/."""
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    meta: RunMeta = load_json(RunMeta, run_dir / "run.json")
    trace = AcoTrace.load(run_dir / "trace.npz")
    conv_file = run_dir / "convergence.csv"
    conv = CONVERGENCE.read(conv_file) if conv_file.exists() else None
    scene = load_scene(out_dir)
    rid = replay_id("aco", meta.run_id)
    rel_dir = f"replays/{rid}"

    ids = [str(c) for c in trace.candidate_ids]
    tops, platforms = shafts(scene, ids, float(cfg["metro"]["station_depth_m"]))
    curve = _curve(trace, conv)
    n_iter = int(max(curve["curve_iteration"].max(), trace.iterations.max())) + 1
    write_binary(
        out_dir / rel_dir / "trace.json",
        AcoTraceHeader,
        {
            "iterations": trace.iterations.astype(np.int32),
            "tours": trace.tours.astype(np.int16),
            "tour_cost_s": trace.tour_cost_s.astype(np.float32),
            "best_tour": trace.best_tour.astype(np.int16),
            "pheromone": trace.pheromone.astype(np.float32),
            **curve,
        },
        provenance=provenance(GENERATOR, cfg),
        run_id=meta.run_id,
        algorithm=meta.algorithm,
        topology=meta.best.topology,
        k=int(trace.tours.shape[2]),
        n_iterations=n_iter,
        best_s=meta.best.objective_s,
        baseline_s=meta.best.baseline_s,
        stations=meta.best.stations,
        candidate_ids=ids,
        candidate_tops=tops,
        candidate_platforms=platforms,
    )
    changed += [f"{rel_dir}/trace.json", f"{rel_dir}/trace.bin"]

    metro = metro_model(scene, cfg, meta.best.topology, meta.best.stations)
    metro_rel = _write(out_dir, f"{rel_dir}/metro.json", metro, changed)
    replay = Replay(
        id=rid,
        kind="aco",
        title=f"{meta.algorithm.upper()} k={len(meta.best.stations)}, seed {meta.seed}",
        description=note,
        created_at=meta.provenance.generated_at,
        run_id=meta.run_id,
        topology=meta.best.topology,
        stations=meta.best.stations,
        weekdays=sorted({r.weekday for r in metro.runs}),
        files=ReplayFiles(metro=metro_rel, aco_trace=f"{rel_dir}/trace.json"),
    )
    _write(out_dir, f"{rel_dir}/replay.json", replay, changed)
    log.info(
        "replay %s: %d sampled iterations, %d candidates", rid, len(trace.iterations), len(ids)
    )
    return replay


def export_best_line(
    cfg: dict,
    best_line: Path,
    out_dir: Path,
    changed: list[str],
    schedule_file: Path | None = None,
    note: str | None = None,
    strict: bool = False,
) -> Replay:
    """The chosen line -> replays/sim-<run_id>/ with metro.json. Students (trips, stats)
    are added by the simulation export; files it wrote before are kept while the line is
    the same. ``strict`` (the simulation export): a schedule of another line is an error,
    since the simulated legs ride it, not a reason to build a timetable from the config."""
    out_dir = Path(out_dir)
    line: BestLine = load_json(BestLine, best_line)
    scene = load_scene(out_dir)
    schedule = None
    if schedule_file is not None and Path(schedule_file).exists():
        schedule = METRO_SCHEDULE.read(schedule_file)
        ahead = schedule[schedule.direction == 1]
        first = ahead[ahead.run_id == ahead.run_id.min()].sort_values("stop_seq")
        order = station_order(len(line.stations), line.topology, 1)
        if first.station.tolist() != [line.stations[i] for i in order]:
            if strict:
                raise ValueError(
                    f"{schedule_file} is for another line than {best_line}: rerun 05_simulate.py"
                )
            log.warning(
                "%s is for another line: building a timetable from the config", schedule_file
            )
            schedule = None
    rid = replay_id("sim", line.run_id)
    rel_dir = f"replays/{rid}"
    metro = metro_model(scene, cfg, line.topology, line.stations, schedule)
    metro_rel = _write(out_dir, f"{rel_dir}/metro.json", metro, changed)

    old_file = out_dir / rel_dir / "replay.json"
    old = Replay.model_validate_json(old_file.read_text("utf-8")) if old_file.exists() else None
    if old and (old.stations != line.stations or old.topology != line.topology):
        old = None  # same run id, another line (04_optimize again): its students do not apply
    replay = Replay(
        id=rid,
        kind="simulation",
        title=f"Line {' – '.join(line.stations)}",
        description=note if note is not None else (old.description if old else None),
        created_at=line.provenance.generated_at,
        run_id=line.run_id,
        topology=line.topology,
        stations=line.stations,
        scenarios=old.scenarios if old else [],
        weekdays=sorted({r.weekday for r in metro.runs}),
        files=ReplayFiles(
            metro=metro_rel,
            trips=old.files.trips if old else {},
            stats=old.files.stats if old else None,
        ),
    )
    _write(out_dir, f"{rel_dir}/replay.json", replay, changed)
    log.info("replay %s: %d stations, %d train runs", rid, len(line.stations), len(metro.runs))
    return replay

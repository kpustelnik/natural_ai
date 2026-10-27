"""``06_export_web.py --fake``: synthetic optimisation results for developing the viewer
before the real pipeline (demand, instance, ACO) exists. NOT the project's optimiser.

Writes, following the real contracts (sections 7 and 8), into ``data/processed/fake/``:

    results/<run_id>/run.json, convergence.csv, trace.npz
    results/best_line.json

which the normal ``--aco`` / ``--metro`` exports then turn into replays. The instance is
built from scene.json: every building with a ``metro_shaft`` entrance is a candidate, every
building and stop an endpoint; the demand is a gravity model on straight-line distances.
The optimiser is ``aco.run_mmas`` on a short run with a weak heuristic (``weak_aco``),
enough to give the player a real-looking run: pheromone that concentrates and a best line
that improves.
"""

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..aco import run_mmas
from ..aco.objective import teleport_bound
from ..config import config_hash, provenance
from ..schemas.instance import Instance, InstanceMeta
from ..schemas.results import BestLine, RunMeta
from ..schemas.tables import CONVERGENCE
from ..schemas.web import Scene

log = logging.getLogger(__name__)

GENERATOR = "06_export_web.py --fake"
DETOUR = 1.3  # walking distance / straight distance
MAX_OD = 2500  # largest OD pairs kept, so the objective stays fast
NOTE = (
    "Synthetic run from 06_export_web.py --fake: gravity-model demand on straight-line "
    "distances, not USOS. For developing the viewer only."
)


def fake_instance(scene: Scene, cfg: dict, rng: np.random.Generator) -> Instance:
    m, tm = cfg["metro"], cfg["time_model"]
    wanted = m.get("candidates", "all")
    places = []  # (key, x, z, size, candidate)
    for b in scene.buildings:
        if not b.entrances:
            continue
        e = next((e for e in b.entrances if e.metro_shaft), None) or next(
            (e for e in b.entrances if e.main), b.entrances[0]
        )
        dx, dz = b.bbox_max[0] - b.bbox_min[0], b.bbox_max[2] - b.bbox_min[2]
        size = max(1.0, dx * dz * len(b.levels) / 1000) * (2.0 if b.kind == "dorm" else 1.0)
        cand = any(x.metro_shaft for x in b.entrances) and (wanted == "all" or b.id in wanted)
        places.append((b.id, e.position[0], e.position[2], size, cand))
    for s in scene.stops:
        places.append((s.id, s.position[0], s.position[2], 40.0, False))
    keys = np.array([p[0] for p in places])
    xz = np.array([[p[1], p[2]] for p in places])
    size = np.array([p[3] for p in places])
    cand = np.flatnonzero([p[4] for p in places])
    if len(cand) < 2:
        raise ValueError(f"{len(cand)} buildings with metro_shaft entrances: need at least 2")

    d = np.linalg.norm(xz[:, None] - xz[None], axis=2)
    walk = d * DETOUR / tm["walk_speed_mps"]
    w = size[:, None] * size[None] / (d + 150.0) ** 1.5 * rng.lognormal(0, 0.5, d.shape)
    np.fill_diagonal(w, 0)
    od = np.argsort(w, axis=None)[::-1][:MAX_OD]
    od = od[w.flat[od] > 0]
    od_from, od_to = np.unravel_index(od, w.shape)
    weight = w[od_from, od_to]
    weight = weight / weight.sum() * 150_000  # student-legs per week, roughly the real scale

    depth = float(m["station_depth_m"])
    fr = scene.frame  # web -> EPSG:2180 + absolute height (the campus is flat)
    xyz = np.column_stack(
        [xz[cand, 0] + fr.origin_x, -xz[cand, 1] + fr.origin_y, np.full(len(cand), fr.origin_z)]
    )
    meta = InstanceMeta(
        name="fake",
        topology=m["topology"],
        k=max(2, min(int(m["n_stations"]), len(cand))),
        metro_speed_mps=float(m["speed_mps"]),
        dwell_s=float(m["dwell_s"]),
        wait_s=float(m["headway_s"]) / 2,
        shaft_down_s=depth / tm["stairs_down_mps"],
        shaft_up_s=depth / tm["stairs_up_mps"],
    )
    inst = Instance(
        meta=meta,
        candidate_ids=keys[cand],
        candidate_xyz=xyz,
        tunnel_m=d[np.ix_(cand, cand)].astype(np.float32),
        endpoint_keys=keys,
        access_s=walk[:, cand].astype(np.float32),
        egress_s=walk[cand, :].astype(np.float32),
        od_from=od_from.astype(np.int32),
        od_to=od_to.astype(np.int32),
        od_weight=weight.astype(np.float32),
        od_walk_s=walk[od_from, od_to].astype(np.float32),
    )
    inst.validate()
    return inst


def weak_aco(cfg: dict) -> dict:
    """``cfg`` with a short MMAS run and a weak heuristic, so the run takes a while to
    converge and the player has more to show."""
    aco = cfg["aco"]
    n_ants = min(int(aco["n_ants"]), 30)
    return {
        **cfg,
        # no local search, no budget: the ants alone, every iteration
        "optimize": {**cfg.get("optimize", {}), "local_search": False, "max_evaluations": None},
        "aco": {
            **aco,
            "n_ants": n_ants,
            "n_iterations": min(int(aco["n_iterations"]), 120),
            "beta": min(float(aco["beta"]), 1.0),
            "rho": float(aco["rho"]) / 2,
            "trace": {
                "every": max(1, min(int(aco["trace"]["every"]), 3)),
                "max_ants": min(int(aco["trace"]["max_ants"]), n_ants),
            },
        },
    }


def write_fake_results(scene: Scene, cfg: dict, out_root: Path, seed: int = 42) -> Path:
    """Synthetic run + best line under ``out_root`` (results/<run_id>/, best_line.json)."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    inst = fake_instance(scene, cfg, rng)
    result = run_mmas(inst, weak_aco(cfg), rng)
    best, cost, f, params = result.best_line, result.best_cost, result.objective, result.params
    run_id = f"fake-mmas-k{inst.meta.k}-s{seed}"
    run_dir = Path(out_root) / "results" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    prov = provenance(GENERATOR, cfg)
    line = BestLine(
        provenance=prov,
        run_id=run_id,
        topology=inst.meta.topology,
        stations=[str(inst.candidate_ids[i]) for i in best],
        objective_s=round(cost, 1),
        baseline_s=round(f.baseline, 1),
        lower_bound_s=round(teleport_bound(inst), 1),
    )
    meta = RunMeta(
        provenance=prov,
        run_id=run_id,
        experiment="fake",
        algorithm="mmas",
        instance="(synthetic, built from scene.json)",
        instance_hash=config_hash({"seed": seed, "n": inst.n_candidates}),
        seed=seed,
        params=params,
        eval_budget=params["n_ants"] * params["n_iterations"],
        evaluations=max(1, f.evaluations),
        wall_time_s=round(time.perf_counter() - t0, 2),
        best=line,
    )
    (run_dir / "run.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    CONVERGENCE.write(result.convergence, run_dir / "convergence.csv")
    result.trace.save(run_dir / "trace.npz")
    (Path(out_root) / "results" / "best_line.json").write_text(
        line.model_dump_json(indent=2), encoding="utf-8"
    )
    log.info(
        "fake run %s: %d candidates, best %s, %.1f%% below no metro, %.1f s",
        run_id, inst.n_candidates, "-".join(line.stations), 100 * (1 - cost / f.baseline),
        time.perf_counter() - t0,
    )  # fmt: skip
    return run_dir


# --- synthetic week of students (phase 6 of the viewer) ------------------------------------

SLOT_STARTS = [8 * 3600 + i * 105 * 60 for i in range(7)]  # AGH: 8:00, 9:45, ... 18:30
CLASS_S = 90 * 60
N_CLASSES_P = [0.08, 0.12, 0.25, 0.3, 0.18, 0.07]  # 0..5 classes a day
FIRST_SLOT_P = [0.3, 0.25, 0.18, 0.12, 0.08, 0.05, 0.02]
GAP_P = [0.7, 0.18, 0.12]  # free slots between two classes: 0, 1, 2
SAME_ROOM_P = 0.2
FAKE_STUDENTS = 20_000  # population.n_students: auto (a USOS count) means this here
FAKE_DORM_SHARE = 0.35
OWN_FACULTY_P = 0.6
SIM_NOTE = (
    "Synthetic week from 06_export_web.py --fake: random students and timetables (not USOS) "
    "on the real walk graph, simulated with metro_agh.simulation. For developing the viewer."
)


def fake_population(
    nodes: pd.DataFrame,
    scene: Scene,
    stop_weights: dict[str, float],
    cfg: dict,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``tables.STUDENTS`` and ``tables.LEGS`` (sections 5.1 and 5.3) for random students:
    a home (dorm or stop), a faculty building, and 0-5 classes a day in the AGH slots."""
    from ..schemas.tables import LEGS, STUDENTS

    keys = set(nodes.endpoint_key.dropna())
    by_id = {b.id: b for b in scene.buildings if b.id in keys}

    def size(b) -> float:
        return max(1.0, (b.bbox_max[0] - b.bbox_min[0]) * (b.bbox_max[2] - b.bbox_min[2]))

    # where classes are: the rooms of LOD3 buildings, else the building itself
    rooms: dict[str, list[str]] = {}
    for k in keys:
        if "/" in k:
            rooms.setdefault(k.split("/")[0], []).append(k)
    academic = [b for b in by_id.values() if b.category == "academic"]
    dorms = [b for b in by_id.values() if b.kind == "dorm"]
    stops = [s for s in stop_weights if s in keys]
    if not academic:
        raise ValueError("no academic building in the walk graph")
    places = [sorted(rooms.get(b.id, [b.id])) for b in academic]
    xz = np.array([[b.frame.anchor[0], b.frame.anchor[2]] for b in academic])
    w_size = np.array([size(b) for b in academic])

    n = cfg["population"].get("n_students", "auto")
    n = FAKE_STUDENTS if n in (None, "auto") else int(n)
    share = cfg["population"].get("dorm_share", "auto")
    share = FAKE_DORM_SHARE if share in (None, "auto") else float(share)
    dorm_share = share if dorms and stops else float(bool(dorms))
    max_break = float(cfg["demand"]["max_break_s"])
    weekdays = list(cfg.get("simulation", {}).get("weekdays", [1, 2, 3, 4, 5]))

    in_dorm = rng.random(n) < dorm_share
    dorm_w = np.array([size(b) for b in dorms]) if dorms else np.ones(1)
    stop_w = np.array([stop_weights[s] for s in stops]) if stops else np.ones(1)
    home = np.where(
        in_dorm,
        np.array([b.id for b in dorms] or [""])[
            rng.choice(len(dorm_w), n, p=dorm_w / dorm_w.sum())
        ],
        np.array(stops or [""])[rng.choice(len(stop_w), n, p=stop_w / stop_w.sum())],
    )
    faculty = rng.choice(len(academic), n, p=w_size / w_size.sum())
    students = pd.DataFrame(
        {
            "student_id": np.arange(n),
            "cohort_id": [f"FAKE-{academic[f].id}" for f in faculty],
            "home_kind": np.where(in_dorm, "dorm", "stop"),
            "home_key": home,
        }
    )
    STUDENTS.validate(students)

    # classes elsewhere: bigger and closer buildings are likelier
    d = np.linalg.norm(xz[:, None] - xz[None], axis=2)
    elsewhere = w_size[None] / (d + 200.0)
    elsewhere /= elsewhere.sum(axis=1, keepdims=True)

    rows = []
    for s in range(n):
        f, h, dorm = int(faculty[s]), str(home[s]), bool(in_dorm[s])
        for day in weekdays:
            base = (day - 1) * 86400
            n_cls = int(rng.choice(len(N_CLASSES_P), p=N_CLASSES_P))
            if n_cls == 0:
                continue
            slots = [int(rng.choice(len(FIRST_SLOT_P), p=FIRST_SLOT_P))]
            while len(slots) < n_cls:
                nxt = slots[-1] + 1 + int(rng.choice(len(GAP_P), p=GAP_P))
                if nxt >= len(SLOT_STARTS):
                    break
                slots.append(nxt)
            where: list[str] = []
            for _ in slots:
                if where and rng.random() < SAME_ROOM_P:
                    where.append(where[-1])
                    continue
                b = (
                    f
                    if rng.random() < OWN_FACULTY_P
                    else int(rng.choice(len(academic), p=elsewhere[f]))
                )
                where.append(places[b][int(rng.integers(len(places[b])))])

            def leg(kind, a, b, dep, dl):
                brk = dl - dep if dep is not None and dl is not None else None
                rows.append((s, day, kind, a, b, dep, dl, brk))  # noqa: B023

            start = [base + SLOT_STARTS[x] for x in slots]
            leg("home_to_class", h, where[0], None, start[0])
            for c in range(1, len(slots)):
                end_prev = start[c - 1] + CLASS_S
                if where[c] == where[c - 1]:
                    continue
                if dorm and start[c] - end_prev > max_break:
                    leg("class_to_home", where[c - 1], h, end_prev, None)
                    leg("home_to_class", h, where[c], None, start[c])
                else:
                    leg("class_to_class", where[c - 1], where[c], end_prev, start[c])
            leg("class_to_home", where[-1], h, start[-1] + CLASS_S, None)
    legs = pd.DataFrame(
        rows,
        columns=["student_id", "weekday", "kind", "from_key", "to_key", "earliest_depart_wt",
                 "deadline_wt", "break_s"],
    )  # fmt: skip
    legs = legs[legs.from_key != legs.to_key].reset_index(drop=True)
    legs.insert(0, "leg_id", np.arange(len(legs)))
    legs.insert(3, "seq", legs.groupby(["student_id", "weekday"]).cumcount())
    for c in ("earliest_depart_wt", "deadline_wt", "break_s"):
        legs[c] = legs[c].astype("Int64")
    legs = legs[LEGS.column_names]
    LEGS.validate(legs)
    return students, legs


def write_fake_simulation(
    scene: Scene, cfg: dict, campus_dir: Path, out_root: Path, seed: int = 42
) -> Path:
    """A synthetic week under ``out_root`` (the fake processed dir): network/ (built from
    campus_dir and campus.gpkg, like stage 2), population/, demand/, and simulation/ for
    the line in ``out_root/results/best_line.json``. Returns ``out_root``."""
    import yaml

    from ..config import path
    from ..network.graph import build_campus_graph
    from ..schemas.campus import Campus
    from ..schemas.tables import LEGS, OD, OSM_BUILDINGS, OSM_WALK_EDGES, OSM_WALK_NODES, STUDENTS
    from ..simulation.simulate import run_simulation

    t0 = time.perf_counter()
    out_root = Path(out_root)
    gpkg = path(cfg, "processed") / "osm" / "campus.gpkg"
    layers = {
        "walk_nodes": OSM_WALK_NODES.read(gpkg),
        "walk_edges": OSM_WALK_EDGES.read(gpkg),
        "buildings": OSM_BUILDINGS.read(gpkg),
    }
    graph = build_campus_graph(cfg, campus_dir, layers)
    graph.write(out_root / "network")
    in_scene = {b.id for b in scene.buildings}
    in_graph = set(graph.nodes.building_id.dropna())
    if in_graph != in_scene:
        log.warning(
            "scene.json and %s differ (%d buildings only in one of them): export --campus "
            "from the same campus (--sample?)", campus_dir, len(in_graph ^ in_scene),
        )  # fmt: skip

    campus = Campus.model_validate(
        yaml.safe_load((Path(campus_dir) / "campus.yaml").read_text(encoding="utf-8"))
    )
    rng = np.random.default_rng(seed + 1)
    students, legs = fake_population(
        graph.nodes, scene, {s.id: s.weight for s in campus.stops}, cfg, rng
    )
    STUDENTS.write(students, out_root / STUDENTS.path)
    LEGS.write(legs, out_root / LEGS.path)
    od = legs.groupby(["from_key", "to_key"]).size().rename("n_legs").reset_index()
    OD.write(od, out_root / OD.path)
    log.info("fake week: %d students, %d legs", len(students), len(legs))
    run_simulation(out_root, out_root / "results" / "best_line.json", cfg)
    log.info("fake simulation written in %.1f s", time.perf_counter() - t0)
    return out_root

"""``06_export_web.py --fake``: synthetic optimisation results for developing the viewer
before the real pipeline (demand, instance, ACO) exists. NOT the project's optimiser.

Writes, following the real contracts (sections 7 and 8), into ``data/processed/fake/``:

    results/<run_id>/run.json, convergence.csv, trace.npz
    results/best_line.json

which the normal ``--aco`` / ``--metro`` exports then turn into replays. The instance is
built from scene.json: every building with a ``metro_shaft`` entrance is a candidate, every
building and stop an endpoint; the demand is a gravity model on straight-line distances.
The optimiser is a compact MAX-MIN Ant System, enough to give the player a real-looking
run: pheromone that concentrates and a best line that improves.
"""

import logging
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import config_hash, provenance
from ..schemas.instance import Instance, InstanceMeta
from ..schemas.results import AcoTrace, BestLine, RunMeta
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


class Objective:
    """docs/data_contracts.md, section 7, vectorised over the OD pairs."""

    def __init__(self, inst: Instance):
        self.i = inst
        self.cache: dict[tuple[int, ...], float] = {}
        self.evaluations = 0
        self.baseline = float((inst.od_weight * inst.od_walk_s).sum())

    def ride(self, line: list[int]) -> np.ndarray:
        meta, tun = self.i.meta, self.i.tunnel_m
        steps = [tun[a, b] for a, b in zip(line, line[1:], strict=False)]
        pos = np.concatenate([[0.0], np.cumsum(steps)])
        gap = np.abs(pos[:, None] - pos[None])
        hops = np.abs(np.arange(len(line))[:, None] - np.arange(len(line))[None])
        if meta.topology == "loop":
            total = pos[-1] + tun[line[-1], line[0]]
            gap = np.minimum(gap, total - gap)
            hops = np.minimum(hops, len(line) - hops)
        return gap / meta.metro_speed_mps + meta.dwell_s * np.maximum(hops - 1, 0)

    def __call__(self, line: list[int]) -> float:
        key = tuple(line)
        if key in self.cache:
            return self.cache[key]
        self.evaluations += 1
        i, meta = self.i, self.i.meta
        a = i.access_s[i.od_from][:, line]  # (M, k)
        e = i.egress_s[line][:, i.od_to].T  # (M, k)
        fixed = meta.shaft_down_s + meta.wait_s + meta.shaft_up_s
        total = a[:, :, None] + (self.ride(line) + fixed)[None] + e[:, None, :]
        k = len(line)
        total[:, np.arange(k), np.arange(k)] = np.inf
        metro = total.reshape(len(a), -1).min(axis=1)
        cost = float((i.od_weight * np.minimum(i.od_walk_s, metro)).sum())
        self.cache[key] = cost
        return cost


def mmas(inst: Instance, cfg: dict, rng: np.random.Generator):
    """Compact MAX-MIN Ant System; returns (best line, convergence rows, trace)."""
    aco = cfg["aco"]
    n, k = inst.n_candidates, inst.meta.k
    n_ants = min(int(aco["n_ants"]), 30)
    n_iter = min(int(aco["n_iterations"]), 120)
    every = max(1, min(int(aco["trace"]["every"]), 3))
    max_ants = min(int(aco["trace"]["max_ants"]), n_ants)
    # a weak heuristic, so the run takes a while to converge and the player has more to show
    alpha, beta, rho = float(aco["alpha"]), min(float(aco["beta"]), 1.0), float(aco["rho"]) / 2
    f = Objective(inst)

    # heuristic: demand served near a candidate, divided by the distance from the previous one
    near = np.argmin(inst.access_s, axis=1)
    demand = np.bincount(near[inst.od_from], inst.od_weight, n) + np.bincount(
        near[inst.od_to], inst.od_weight, n
    )
    demand = demand / demand.max() + 0.05
    eta = demand[None, :] / (inst.tunnel_m + 100.0) * 100.0
    np.fill_diagonal(eta, 0)

    tau_max = 1.0 / rho
    tau = np.full((n, n), tau_max)
    start = np.full(n, tau_max)
    best, best_cost = None, math.inf
    rows, sampled = [], {"it": [], "tours": [], "cost": [], "best": [], "tau": []}
    for it in range(n_iter):
        tours, costs = [], []
        for _ in range(n_ants):
            p = start**alpha * demand**beta
            line = [int(rng.choice(n, p=p / p.sum()))]
            while len(line) < k:
                w = tau[line[-1]] ** alpha * eta[line[-1]] ** beta
                w[line] = 0
                line.append(int(rng.choice(n, p=w / w.sum())))
            tours.append(line)
            costs.append(f(line))
        ib = int(np.argmin(costs))
        if costs[ib] < best_cost:
            best, best_cost = tours[ib], costs[ib]
        # MMAS: evaporate, deposit by the iteration best (every 3rd time the global best)
        dep_line, dep_cost = (best, best_cost) if it % 3 == 2 else (tours[ib], costs[ib])
        tau_max = 1.0 / (rho * best_cost / f.baseline)
        tau_min = tau_max * float(aco["tau_min_ratio"])
        tau *= 1 - rho
        start *= 1 - rho
        q = f.baseline / dep_cost
        for a, b in zip(dep_line, dep_line[1:], strict=False):
            tau[a, b] += q
            tau[b, a] += q
        start[dep_line[0]] += q
        start[dep_line[-1]] += q
        np.clip(tau, tau_min, tau_max, out=tau)
        np.clip(start, tau_min, tau_max, out=start)
        upper = tau[np.triu_indices(n, 1)]
        pr = upper / upper.sum()
        entropy = float(-(pr * np.log(pr)).sum() / math.log(len(pr)))
        rows.append(
            (it, f.evaluations, best_cost, costs[ib], float(np.mean(costs)), tau_min, tau_max,
             entropy)
        )  # fmt: skip
        if it % every == 0 or it == n_iter - 1:
            sampled["it"].append(it)
            sampled["tours"].append(tours[:max_ants])
            sampled["cost"].append(costs[:max_ants])
            sampled["best"].append(list(best))
            sampled["tau"].append(tau.copy())
    trace = AcoTrace(
        iterations=np.array(sampled["it"], np.int32),
        tours=np.array(sampled["tours"], np.int16),
        tour_cost_s=np.array(sampled["cost"], np.float32),
        best_tour=np.array(sampled["best"], np.int16),
        pheromone=np.array(sampled["tau"], np.float32),
        candidate_ids=inst.candidate_ids,
    )
    conv = pd.DataFrame(rows, columns=CONVERGENCE.column_names)
    params = {"n_ants": n_ants, "n_iterations": n_iter, "alpha": alpha, "beta": beta, "rho": rho}
    return best, best_cost, f, conv, trace, params


def write_fake_results(scene: Scene, cfg: dict, out_root: Path, seed: int = 42) -> Path:
    """Synthetic run + best line under ``out_root`` (results/<run_id>/, best_line.json)."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    inst = fake_instance(scene, cfg, rng)
    best, cost, f, conv, trace, params = mmas(inst, cfg, rng)
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
    CONVERGENCE.write(conv, run_dir / "convergence.csv")
    trace.save(run_dir / "trace.npz")
    (Path(out_root) / "results" / "best_line.json").write_text(
        line.model_dump_json(indent=2), encoding="utf-8"
    )
    log.info(
        "fake run %s: %d candidates, best %s, %.1f%% below no metro, %.1f s",
        run_id, inst.n_candidates, "-".join(line.stations), 100 * (1 - cost / f.baseline),
        time.perf_counter() - t0,
    )  # fmt: skip
    return run_dir

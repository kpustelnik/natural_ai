"""Simulation replays: the students of every scenario (docs/data_contracts.md, 10.6).

    --sim     ``simulation/<scenario>/legs.parquet`` + ``demand/legs.parquet`` +
              ``network/*.parquet`` -> ``replays/sim-<run_id>/``:
              trips/<scenario>/paths.{json,bin}, trips/<scenario>/day-<weekday>.{json,bin},
              stats.json, and metro.json + replay.json (as ``--metro``)

Paths are stored once per scenario and referenced by time-shifted segments: a walking leg is
one segment, a metro leg three (walk to the platform, ride, walk out). Walks follow the
edges' real polylines from network.json (matched by node key, so the simulation's graph
build and the web export's need not number nodes alike); a ride follows the platforms of
the stations it passes, with the timetable's arrival and departure times.
"""

import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..campus.geo import to_metric
from ..config import provenance
from ..geometry.mesh import web
from ..schemas.common import Scenario
from ..schemas.results import BestLine, load_json
from ..schemas.tables import GRAPH_EDGES, GRAPH_NODES, LEGS, SIM_LEGS
from ..schemas.web import (
    MODE_CODES,
    DayHeader,
    HourStats,
    Metro,
    NetworkHeader,
    OdStats,
    PathsHeader,
    Replay,
    ReplayFiles,
    ScenarioStats,
    StationStats,
    Stats,
)
from ..simulation.metrics import scenario_metrics
from ..simulation.schedule import DAY_S
from .binary import write_binary
from .export_campus import GENERATOR
from .export_metro import export_best_line

log = logging.getLogger(__name__)

TOP_OD = 50


def _web_polylines(out_dir: Path) -> dict[tuple[str, str], np.ndarray]:
    """(key u, key v) -> polyline u -> v (web frame) of every network.json edge."""
    hf = out_dir / "network.json"
    if not hf.exists():
        return {}
    h = NetworkHeader.model_validate_json(hf.read_text(encoding="utf-8"))
    raw = (out_dir / h.bin).read_bytes()

    def buf(name: str) -> np.ndarray:
        v = h.buffers[name]
        return np.frombuffer(raw, dtype=v.dtype, count=v.count, offset=v.offset).reshape(v.shape)

    pairs, segs, seg_edge = buf("edge_nodes"), buf("segment_xyz"), buf("segment_edge")
    starts = np.r_[0, np.flatnonzero(np.diff(seg_edge)) + 1]
    ends = np.r_[starts[1:], len(seg_edge)]
    keys = h.node_keys
    out = {}
    for s, e in zip(starts, ends, strict=True):
        u, v = pairs[seg_edge[s]]
        out[(keys[u], keys[v])] = np.vstack([segs[s:e, 0], segs[e - 1, 1][None]])
    return out


class PathBuilder:
    """Distinct paths of one scenario: positions with the time since the path start."""

    def __init__(self, keys: np.ndarray, xyz: np.ndarray, edges: pd.DataFrame, polylines: dict):
        self.keys = keys  # node id -> key
        self.xyz = xyz  # node id -> web position
        self.time: dict[tuple[int, int], float] = {}
        for u, v, a, b in zip(edges.u, edges.v, edges.time_uv_s, edges.time_vu_s, strict=True):
            self.time[(int(u), int(v))] = float(a)
            self.time[(int(v), int(u))] = float(b)
        self.polylines = polylines
        self.index: dict[object, int] = {}
        self.offsets = [0]
        self.verts: list[np.ndarray] = []
        self.times: list[np.ndarray] = []
        self.modes: list[int] = []
        self.duration: list[float] = []

    def _add(self, key, xyz: np.ndarray, t: np.ndarray, mode: int) -> int:
        self.index[key] = len(self.modes)
        self.verts.append(xyz.astype(np.float32))
        self.times.append(t.astype(np.float32))
        self.offsets.append(self.offsets[-1] + len(xyz))
        self.modes.append(mode)
        self.duration.append(float(t[-1]))
        return self.index[key]

    def walk(self, path: np.ndarray) -> int:
        key = path.tobytes()
        p = self.index.get(key)
        if p is not None:
            return p
        pts, ts = [self.xyz[path[0]]], [0.0]
        t = 0.0
        for a, b in zip(path[:-1], path[1:], strict=True):
            dt = self.time[(int(a), int(b))]
            line = self.polylines.get((self.keys[a], self.keys[b]))
            if (
                line is None
                and (rev := self.polylines.get((self.keys[b], self.keys[a]))) is not None
            ):
                line = rev[::-1]
            if line is None or len(line) < 2:
                line = np.stack([self.xyz[a], self.xyz[b]])
            seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
            frac = np.cumsum(seg) / seg.sum() if seg.sum() > 0 else np.ones(len(seg))
            for q, f in zip(line[1:], frac, strict=True):
                pts.append(q)
                ts.append(t + dt * f)
            t += dt
        return self._add(key, np.array(pts), np.array(ts), MODE_CODES["walk"])

    def ride(self, key, xyz: list, t: list, mode: str = "metro") -> int:
        p = self.index.get(key)
        return p if p is not None else self._add(key, np.array(xyz), np.array(t), MODE_CODES[mode])

    def arrays(self) -> dict[str, np.ndarray]:
        return {
            "path_offsets": np.array(self.offsets, np.uint32),
            "xyz": np.concatenate(self.verts).astype(np.float32),
            "t": np.concatenate(self.times).astype(np.float32),
            "mode": np.array(self.modes, np.uint8),
        }


def _ride_templates(metro: Metro) -> dict[tuple[int, int], list[tuple[list[int], list]]]:
    """(board, alight) -> one (stations, times) per direction, from the first runs. On a loop
    the run goes on into the next one of its direction (simulate.loop_successors), so the
    rides through station 0 have a template too."""
    out: dict[tuple[int, int], list] = {}
    seen = set()
    k = len(metro.stations)
    for r in metro.runs:
        if r.direction in seen:
            continue
        seen.add(r.direction)
        st = [(s.station, s.arrive_t, s.depart_t) for s in r.stops]
        if metro.topology == "loop":
            back = st[-1][1]
            nxt = [
                q for q in metro.runs
                if q.direction == r.direction and q.weekday == r.weekday
                and q.stops[0].depart_t >= back
            ]  # fmt: skip
            if nxt:
                q = min(nxt, key=lambda q: q.stops[0].depart_t)
                st[-1] = (st[-1][0], back, q.stops[0].depart_t)  # wait at station 0
                st += [(s.station, s.arrive_t, s.depart_t) for s in q.stops[1:]]
        for a in range(len(r.stops) - 1):  # board on this run (the next one has its own)
            for b in range(a + 1, min(len(st), a + k)):  # less than once round
                i, j = st[a][0], st[b][0]
                if i == j:
                    continue
                t0 = st[a][2]
                stops = [(st[c][0], st[c][1] - t0, st[c][2] - t0) for c in range(a, b + 1)]
                stops[0] = (i, 0.0, 0.0)
                stops[-1] = (j, stops[-1][1], stops[-1][1])
                out.setdefault((i, j), []).append(stops)
    return out


def _ride_path(
    pb: PathBuilder, tmpl: list, platform_xyz: np.ndarray, i: int, j: int, ride_s: float
) -> int:
    stops = min(tmpl, key=lambda s: abs(s[-1][1] - ride_s))  # the direction actually taken
    xyz, t = [], []
    for st, arr, dep in stops:
        xyz.append(platform_xyz[st])
        t.append(arr)
        if dep > arr:
            xyz.append(platform_xyz[st])
            t.append(dep)
    return pb.ride((i, j, round(stops[-1][1])), xyz, t)


def export_scenario(
    out_dir: Path,
    rel_dir: str,
    scenario: str,
    sim: pd.DataFrame,
    legs: pd.DataFrame,
    pb: PathBuilder,
    metro: Metro | None,
    platform_nodes: dict[str, int],
    cfg: dict,
    changed: list[str],
    stop_nodes: dict[str, int] | None = None,
) -> list[int]:
    """trips/<scenario>/paths.* and day-<weekday>.*; returns the weekdays written."""
    station_ix = {s.building_id: i for i, s in enumerate(metro.stations)} if metro else {}
    templates = _ride_templates(metro) if metro else {}
    platform_xyz = (
        np.array([pb.xyz[platform_nodes[s.building_id]] for s in metro.stations]) if metro else None
    )
    df = sim.merge(legs[["leg_id", "weekday"]], on="leg_id", how="left", validate="one_to_one")
    segs = {"student_id": [], "leg_id": [], "path_id": [], "t": [], "weekday": []}

    def seg(r, path_id: int, t_wt: float) -> None:
        base = (r.weekday - 1) * DAY_S
        segs["student_id"].append(r.student_id)
        segs["leg_id"].append(r.leg_id)
        segs["path_id"].append(path_id)
        segs["t"].append(t_wt - base)
        segs["weekday"].append(r.weekday)

    for r in df.itertuples(index=False):
        nodes = np.asarray(r.path_nodes, np.int64)
        if r.mode == "transit":  # a bus or tram: straight from stop to stop, at street level
            a, b = stop_nodes[r.board_station], stop_nodes[r.alight_station]
            cut = np.flatnonzero((nodes[:-1] == a) & (nodes[1:] == b))
            if not len(cut):
                raise ValueError(f"leg {r.leg_id}: path_nodes has no {a} -> {b} ride")
            c = int(cut[0])
            walk_in, walk_out = pb.walk(nodes[: c + 1]), pb.walk(nodes[c + 1 :])
            ride = pb.ride(
                ("transit", a, b, round(r.ride_s)),
                [pb.xyz[a], pb.xyz[b]],
                [0.0, float(r.ride_s)],
                mode="transit",
            )
            t_ride = r.depart_wt + pb.duration[walk_in] + r.wait_s
            seg(r, walk_in, r.depart_wt)
            seg(r, ride, t_ride)
            seg(r, walk_out, t_ride + r.ride_s)
            continue
        if r.mode != "metro":
            seg(r, pb.walk(nodes), r.depart_wt)
            continue
        board, alight = platform_nodes[r.board_station], platform_nodes[r.alight_station]
        cut = np.flatnonzero((nodes[:-1] == board) & (nodes[1:] == alight))
        if not len(cut):
            raise ValueError(
                f"leg {r.leg_id}: path_nodes has no {r.board_station} -> {r.alight_station} ride"
            )
        c = int(cut[0])
        walk_in = pb.walk(nodes[: c + 1])
        i, j = station_ix[r.board_station], station_ix[r.alight_station]
        ride = _ride_path(pb, templates[(i, j)], platform_xyz, i, j, r.ride_s)
        walk_out = pb.walk(nodes[c + 1 :])
        t_ride = r.depart_wt + pb.duration[walk_in] + r.wait_s
        seg(r, walk_in, r.depart_wt)
        seg(r, ride, t_ride)
        seg(r, walk_out, t_ride + r.ride_s)

    trips = f"{rel_dir}/trips/{scenario}"
    prov = provenance(GENERATOR, cfg)
    write_binary(out_dir / trips / "paths.json", PathsHeader, pb.arrays(), provenance=prov,
                 scenario=scenario, n_paths=len(pb.modes))  # fmt: skip
    changed += [f"{trips}/paths.json", f"{trips}/paths.bin"]
    s = pd.DataFrame(segs)
    days = sorted(int(d) for d in s.weekday.unique())
    for day, g in s.groupby("weekday"):
        g = g.sort_values("t", kind="stable")
        write_binary(
            out_dir / trips / f"day-{day}.json",
            DayHeader,
            {
                "student_id": g.student_id.to_numpy(np.uint32),
                "leg_id": g.leg_id.to_numpy(np.uint32),
                "path_id": g.path_id.to_numpy(np.uint32),
                "t_start": g.t.to_numpy(np.float32),
            },
            provenance=prov,
            scenario=scenario,
            weekday=int(day),
            n_students=int(g.student_id.nunique()),
            t_min=float(max(0.0, g.t.min())),
            t_max=float(min(DAY_S, g.t.max() + max(pb.duration))),
        )
        changed += [f"{trips}/day-{day}.json", f"{trips}/day-{day}.bin"]
    log.info(
        "%s: %d legs, %d segments, %d distinct paths, %d vertices",
        scenario, len(df), len(s), len(pb.modes), pb.offsets[-1],
    )  # fmt: skip
    return days


def _scenario_stats(sim: pd.DataFrame, legs: pd.DataFrame) -> ScenarioStats:
    m = scenario_metrics(sim, legs)
    return ScenarioStats(**{k: v for k, v in m.items() if k in ScenarioStats.model_fields})


def stats(
    sims: dict[str, pd.DataFrame], legs: pd.DataFrame, stations: list[str], cfg: dict
) -> Stats:
    """stats.json: totals, the time-of-day chart, station use, the largest OD savings."""
    scenarios = {sc: _scenario_stats(df, legs) for sc, df in sims.items()}
    total = {sc: s.total_travel_s for sc, s in scenarios.items()}
    lg = legs.set_index("leg_id")
    # a leg belongs to the hour it leaves in when walking, so the chart follows the clock
    first = sims.get("no_metro", next(iter(sims.values()))).set_index("leg_id").depart_wt
    depart = first.reindex(lg.index).astype(float)
    hours = pd.DataFrame({"weekday": lg.weekday, "hour": ((depart % DAY_S) // 3600).astype(int)})
    travel = {
        sc: (df.set_index("leg_id").arrive_wt - df.set_index("leg_id").depart_wt).astype(float)
        for sc, df in sims.items()
    }
    for sc, t in travel.items():
        hours[sc] = t
    hours = hours.fillna(0.0)
    per_hour = [
        HourStats(
            weekday=int(day),
            hour=int(hour),
            n_legs=len(g),
            no_metro_s=round(float(g.get("no_metro", pd.Series(dtype=float)).sum()), 1),
            metro_s=round(float(g.get("metro", pd.Series(dtype=float)).sum()), 1),
        )
        for (day, hour), g in hours.groupby(["weekday", "hour"])
    ]
    station_stats = []
    top = []
    if "metro" in sims:
        m = sims["metro"]
        board, alight = m.board_station.value_counts(), m.alight_station.value_counts()
        station_stats = [
            StationStats(
                building_id=s, boardings=int(board.get(s, 0)), alightings=int(alight.get(s, 0))
            )
            for s in stations
        ]
        if "no_metro" in sims:
            od = lg[["from_key", "to_key"]].copy()
            od["saving"] = travel["no_metro"] - travel["metro"]
            g = od.groupby(["from_key", "to_key"]).saving.agg(["size", "sum"]).reset_index()
            g = g[g["sum"] > 0].nlargest(TOP_OD, "sum")
            top = [
                OdStats(
                    from_key=r.from_key,
                    to_key=r.to_key,
                    n_legs=int(r.size),
                    saving_s=round(float(r.sum), 1),
                )
                for r in g.itertuples(index=False)
            ]
    saving = total.get("no_metro", 0.0) - total.get("metro", total.get("no_metro", 0.0))
    return Stats(
        provenance=provenance(GENERATOR, cfg),
        scenarios=scenarios,
        saving_s=round(saving, 1),
        per_hour=per_hour,
        stations=station_stats,
        top_od=top,
    )


def export_simulation(
    cfg: dict,
    processed: Path,
    best_line: Path,
    out_dir: Path,
    changed: list[str],
    note: str | None = None,
) -> Replay:
    """``processed`` holds network/, demand/ and simulation/ of one simulation run."""
    processed, out_dir = Path(processed), Path(out_dir)
    nodes = GRAPH_NODES.read(processed / GRAPH_NODES.path)
    edges = GRAPH_EDGES.read(processed / GRAPH_EDGES.path)
    legs = LEGS.read(processed / LEGS.path)
    sims = {}
    for sc in Scenario:
        f = processed / SIM_LEGS.path.format(scenario=sc.value)
        if f.exists():
            sims[sc.value] = SIM_LEGS.read(f)
    if not sims:
        raise FileNotFoundError(
            f"no {processed}/simulation/*/legs.parquet: run 05_simulate.py first"
        )
    line: BestLine = load_json(BestLine, best_line)

    schedule = processed / "simulation" / "metro" / "schedule.parquet"
    if "metro" in sims and not schedule.exists():
        raise FileNotFoundError(f"{schedule} missing: rerun 05_simulate.py")
    replay = export_best_line(
        cfg, best_line, out_dir, changed, schedule_file=schedule, note=note, strict=True
    )
    rel_dir = f"replays/{replay.id}"
    metro = Metro.model_validate_json((out_dir / replay.files.metro).read_text(encoding="utf-8"))

    o = cfg["campus"]["web_origin"]
    origin = tuple(float(v) for v in to_metric(o["lon"], o["lat"]))
    polylines = _web_polylines(out_dir)
    if not polylines:
        log.warning("%s/network.json missing: students walk straight from node to node", out_dir)
    key_to_id = dict(zip(nodes.key, nodes.node_id, strict=True))
    platform_nodes = {
        s: int(key_to_id[f"{s}:platform"]) for s in line.stations if f"{s}:platform" in key_to_id
    }
    stop_nodes = {k: int(i) for k, i in key_to_id.items() if str(k).startswith("stop:")}
    xyz = web(nodes.x.to_numpy(), nodes.y.to_numpy(), nodes.z.to_numpy() - float(o["z"]), origin)

    trips: dict[str, str] = {}
    weekdays: set[int] = set()
    for sc, sim in sims.items():
        pb = PathBuilder(nodes.key.to_numpy(), xyz, edges, polylines)
        weekdays |= set(
            export_scenario(out_dir, rel_dir, sc, sim, legs, pb, metro if sc == "metro" else None,
                            platform_nodes, cfg, changed, stop_nodes)
        )  # fmt: skip
        trips[sc] = f"{rel_dir}/trips/{sc}"
    st = stats(sims, legs, line.stations, cfg)
    (out_dir / rel_dir / "stats.json").write_text(st.model_dump_json(), encoding="utf-8")
    changed.append(f"{rel_dir}/stats.json")

    replay = replay.model_copy(
        update={
            "scenarios": [sc.value for sc in Scenario if sc.value in sims],
            "weekdays": sorted(weekdays),
            "files": ReplayFiles(
                metro=replay.files.metro, trips=trips, stats=f"{rel_dir}/stats.json"
            ),
            "title": f"Week simulation, line {' – '.join(line.stations)}",
        }
    )
    Replay.model_validate(replay.model_dump())
    (out_dir / rel_dir / "replay.json").write_text(replay.model_dump_json(), encoding="utf-8")
    changed.append(f"{rel_dir}/replay.json")
    base = st.scenarios.get("no_metro")
    share = 100 * st.saving_s / max(1.0, base.total_travel_s) if base else math.nan
    log.info(
        "replay %s: %d scenarios, saving %.0f student-hours a week (%.1f%%)",
        replay.id, len(sims), st.saving_s / 3600, share,
    )  # fmt: skip
    return replay

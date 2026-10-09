"""Graph pieces of one building (docs/data_contracts.md, sections 3.1 and 6.4).

Nodes are planned in the building's local frame and returned in EPSG:2180 with absolute
heights. Keys follow the contract, so ``graph.py`` joins buildings, passages and the outdoor
network by key alone.

- LOD2/3: corridor nodes every ``network.corridor_node_step_m`` along each centreline and
  at every door, stairwell, entrance, junction and passage end; a door node and a
  room-centre node per room; one landing per stairwell and level, joined level to level;
  an entrance node inside (``:in``) and one outside (``:out``).
- LOD1: one ``place`` node at the main entrance, joined to every entrance.
- Candidate stations: the shaft top at the ``metro_shaft`` entrance and the platform
  ``metro.station_depth_m`` below it.

``Part.links`` lists the nodes that ``graph.py`` connects to the nearest outdoor node.
"""

import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from ..geometry.building import PlacedBuilding, point_along
from ..geometry.interior import plan_levels
from ..schemas.building import Corridor

JUNCTION_M = 0.5  # a corridor end this close to another centreline joins it (section 3.1)
OUTSIDE_M = 1.0  # the outside entrance node lies this far from the door
STAIR_SLOPE = 0.6  # rise per horizontal metre; only for the reported 3D length of stairs


@dataclass(frozen=True)
class TimeModel:
    walk_mps: float
    up_mps: float  # vertical speed on stairs
    down_mps: float
    door_s: float
    steps_factor: float  # OSM steps without heights

    @classmethod
    def from_config(cls, cfg: dict) -> "TimeModel":
        t = cfg["time_model"]
        return cls(
            float(t["walk_speed_mps"]),
            float(t["stairs_up_mps"]),
            float(t["stairs_down_mps"]),
            float(t["door_s"]),
            float(t.get("outdoor_steps_factor", 1.0)),
        )

    def walk(self, length_m: float) -> float:
        return length_m / self.walk_mps


@dataclass
class GNode:
    key: str
    kind: str
    x: float  # EPSG:2180
    y: float
    z: float  # absolute height
    building_id: str | None = None
    level: int | None = None
    endpoint_key: str | None = None


@dataclass
class GEdge:
    u: str  # node keys
    v: str
    kind: str
    length_m: float
    time_uv_s: float
    time_vu_s: float
    source: str | None
    cls: str  # drawing class in the viewer: footway / road / steps, else the kind
    geometry: np.ndarray | None = None  # (k, 3) EPSG:2180 + height; None = straight


@dataclass
class GraphIssue:
    section: str
    message: str
    building_id: str | None = None
    position: tuple[float, float, float] | None = None  # EPSG:2180 + height


@dataclass
class Part:
    nodes: list[GNode] = field(default_factory=list)
    edges: list[GEdge] = field(default_factory=list)
    issues: list[GraphIssue] = field(default_factory=list)
    links: list[tuple[str, int | None]] = field(default_factory=list)  # key, forced OSM node


def corridor_at(c: Corridor, at: float) -> float:
    """Position along a corridor as used in node keys: clamped, 2 decimals."""
    return round(min(max(float(at), 0.0), c.length), 2)


def corridor_key(building_id: str, c: Corridor, at: float) -> str:
    return f"{building_id}:{c.id}@{corridor_at(c, at):.2f}"


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.hypot(*v))
    return v / n if n > 0 else np.array([1.0, 0.0])


def _left(t: np.ndarray) -> np.ndarray:
    return np.array([-t[1], t[0]])


def _outward(poly: Polygon, pt) -> np.ndarray:
    """Outward normal of the outline edge nearest to ``pt``. With the exterior
    counter-clockwise and holes clockwise, the inside is always on the left."""
    q = Point(pt)
    best = None
    for ring in [poly.exterior, *poly.interiors]:
        c = np.asarray(ring.coords)
        for a, b in zip(c[:-1], c[1:], strict=True):
            d = LineString([a, b]).distance(q)
            if best is None or d < best[0]:
                best = (d, a, b)
    t = _unit(best[2] - best[1])
    return np.array([t[1], -t[0]])


class _Builder:
    def __init__(self, p: PlacedBuilding, cfg: dict, tm: TimeModel, origin_z: float):
        self.p = p
        self.bid = p.building.id
        self.cfg = cfg
        self.tm = tm
        self.ground = origin_z + p.ground_y  # absolute height of the local z = 0
        self.part = Part()
        self.nodes: dict[str, GNode] = {}
        candidates = cfg["metro"].get("candidates", "all")
        self.candidate = candidates == "all" or self.bid in candidates

    def node(self, key, kind, local, elevation, level=None, endpoint=None, inside=True) -> str:
        if key not in self.nodes:
            m = self.p.frame.to_metric(np.asarray([local], float))[0]
            n = GNode(
                key, kind, float(m[0]), float(m[1]), self.ground + elevation,
                self.bid if inside else None, level if inside else None, endpoint,
            )  # fmt: skip
            self.nodes[key] = n
            self.part.nodes.append(n)
        return key

    def dist(self, u: str, v: str) -> float:
        a, b = self.nodes[u], self.nodes[v]
        return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))

    def edge(self, u, v, kind, length=None, extra_s=0.0, times=None, geometry=None) -> None:
        length = self.dist(u, v) if length is None else length
        t_uv, t_vu = times or (self.tm.walk(length) + extra_s,) * 2
        self.part.edges.append(GEdge(u, v, kind, length, t_uv, t_vu, self.bid, kind, geometry))

    def issue(self, section: str, message: str, local=(0.0, 0.0), elevation=0.0) -> None:
        m = self.p.frame.to_metric(np.asarray([local], float))[0]
        self.part.issues.append(
            GraphIssue(
                section, message, self.bid, (float(m[0]), float(m[1]), self.ground + elevation)
            )
        )

    def outside(self, in_key: str, local, out_dir, elevation, osm_node) -> None:
        """The ``:out`` node in front of a door, linked to the walk network later."""
        out_key = in_key[: -len(":in")] + ":out"
        pt = np.asarray(local, float) + out_dir * OUTSIDE_M
        self.node(out_key, "entrance", pt, elevation, inside=False)
        self.edge(in_key, out_key, "entrance", OUTSIDE_M, extra_s=self.tm.door_s)
        self.part.links.append((out_key, osm_node))

    def shaft(self, in_key: str, local, elevation, level) -> None:
        if not self.candidate:
            return
        depth = float(self.cfg["metro"]["station_depth_m"])
        top = self.node(f"{self.bid}:shaft", "shaft_top", local, elevation, level)
        self.edge(in_key, top, "link", 0.0)
        platform = self.node(f"{self.bid}:platform", "platform", local, -depth)
        drop = elevation + depth
        self.edge(
            top, platform, "shaft", math.hypot(drop / STAIR_SLOPE, drop),
            times=(drop / self.tm.down_mps, drop / self.tm.up_mps),
        )  # fmt: skip


def building_part(
    p: PlacedBuilding,
    cfg: dict,
    tm: TimeModel,
    origin_z: float,
    passage_ats: dict[str, list[float]] | None = None,
) -> Part:
    """The graph of one placed building. ``passage_ats``: corridor id -> positions where
    passages from campus.yaml attach (they need a node there)."""
    bld = _Builder(p, cfg, tm, origin_z)
    if p.building.levels:
        _interior(bld, passage_ats or {})
    else:
        _lod1(bld)
    return bld.part


def _lod1(bld: _Builder) -> None:
    p, bid = bld.p, bld.bid
    level = 0 if any(lv.id == 0 for lv in p.levels) else p.levels[0].id
    main = next((e for e in p.entrances if e.main), None)
    centre = p.footprint_local.representative_point().coords[0]
    place = bld.node(bid, "place", main.local if main else centre, 0.0, level, endpoint=bid)
    if not p.entrances:
        bld.part.links.append((place, None))
        bld.issue(
            "Network: buildings without entrances",
            f"{bid}: linked from inside its outline to the nearest path",
            centre,
        )
        return
    for e in p.entrances:
        in_key = bld.node(f"{bid}:{e.id}:in", "door", e.local, 0.0, level)
        bld.edge(place, in_key, "corridor")
        bld.outside(in_key, e.local, _outward(p.footprint_local, e.local), 0.0, e.osm_node)
        if e.metro_shaft:
            bld.shaft(in_key, e.local, 0.0, level)


def _interior(bld: _Builder, passage_ats: dict[str, list[float]]) -> None:
    p, bid = bld.p, bld.bid
    b = p.building
    step = float(bld.cfg.get("network", {}).get("corridor_node_step_m", 5.0))
    corridors = b.corridors()  # id -> (level, corridor)
    spaces = {(s.level, s.kind, s.id): s for pl in plan_levels(p) for s in pl.spaces}
    attach: dict[str, set[float]] = {cid: set() for cid in corridors}

    def mark(cid: str, at: float) -> None:
        attach[cid].add(corridor_at(corridors[cid][1], at))

    # 1. every position that needs a corridor node
    junctions = []
    for lvl in b.levels:
        for space in [*lvl.rooms, *lvl.stairs]:
            for cid, at in space.door_positions():
                mark(cid, at)
        for a in lvl.corridors:
            for end in (0.0, a.length):
                pt = Point(point_along(a.path, end)[0])
                for c in lvl.corridors:
                    line = LineString(c.path)
                    if c.id != a.id and line.distance(pt) <= JUNCTION_M:
                        mark(a.id, end)
                        mark(c.id, line.project(pt))
                        junctions.append((a, end, c, line.project(pt)))
    for e in b.entrances:
        if e.corridor is not None:
            c = corridors[e.corridor][1]
            mark(c.id, {"start": 0.0, "end": c.length}.get(e.side, e.at or 0.0))
    for cid, ats in passage_ats.items():
        for at in ats:
            if cid in corridors:
                mark(cid, at)

    # 2. corridor chains
    for cid, (lvl, c) in corridors.items():
        seg = np.diff(np.asarray(c.path, float), axis=0)
        vertex_ats = np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))[:-1]
        fixed = {corridor_at(c, a) for a in [0.0, c.length, *vertex_ats]} | attach[cid]
        grid = [
            corridor_at(c, s)
            for s in np.arange(step, c.length, step)
            if min(abs(s - f) for f in fixed) > 1.0
        ]
        ats = sorted(fixed | set(grid))
        keys = []
        for at in ats:
            pt, _ = point_along(c.path, at)
            keys.append(bld.node(corridor_key(bid, c, at), "corridor", pt, lvl.elevation, lvl.id))
        for i in range(len(ats) - 1):
            bld.edge(keys[i], keys[i + 1], "corridor", ats[i + 1] - ats[i])
    for a, end, c, at in junctions:
        bld.edge(corridor_key(bid, a, end), corridor_key(bid, c, at), "corridor")

    # 3. rooms: corridor -> door -> room centre
    for lvl in b.levels:
        for room in lvl.rooms:
            space = spaces[(lvl.id, "room", room.id)]
            room_key = f"{bid}/{room.id}"
            centre = space.polygon.representative_point().coords[0]
            bld.node(room_key, "room", centre, lvl.elevation, lvl.id, endpoint=room_key)
            for n, ((cid, at), door) in enumerate(
                zip(room.door_positions(), space.doors, strict=True), start=1
            ):
                door_key = bld.node(f"{room_key}#{n}", "door", door, lvl.elevation, lvl.id)
                bld.edge(corridor_key(bid, corridors[cid][1], at), door_key, "door")
                bld.edge(door_key, room_key, "door", extra_s=bld.tm.door_s)

    # 4. stairs: a landing in front of each stairwell, joined to the next level up
    landings: dict[str, list[tuple[float, str, object]]] = {}
    for lvl in b.levels:
        for s in lvl.stairs:
            space = spaces[(lvl.id, "stairs", s.id)]
            cid, at = s.door_positions()[0]
            key = bld.node(
                f"{bid}:{s.id}:L{lvl.id}", "stairs", space.doors[0], lvl.elevation, lvl.id
            )
            bld.edge(corridor_key(bid, corridors[cid][1], at), key, "corridor")
            landings.setdefault(s.id, []).append((lvl.elevation, key, space.polygon))
    for flights in landings.values():
        flights.sort(key=lambda f: f[0])
        for (z0, k0, poly), (z1, k1, _) in zip(flights, flights[1:], strict=False):
            rise = z1 - z0
            lo, hi = bld.nodes[k0], bld.nodes[k1]
            c = bld.p.frame.to_metric(np.asarray([poly.centroid.coords[0]]))[0]
            geometry = np.array(
                [[lo.x, lo.y, lo.z], [c[0], c[1], (lo.z + hi.z) / 2], [hi.x, hi.y, hi.z]]
            )
            bld.edge(
                k0, k1, "stairs", math.hypot(rise / STAIR_SLOPE, rise),
                times=(rise / bld.tm.up_mps, rise / bld.tm.down_mps), geometry=geometry,
            )  # fmt: skip

    # 5. entrances: corridor -> inside -> outside; the main one is the building endpoint
    if not p.entrances:
        bld.issue(
            "Network: buildings without entrances",
            f"{bid}: has corridors but no entrance, so nothing inside can be reached",
        )
    yaml_entrances = {e.id: e for e in b.entrances}
    for e in p.entrances:
        ye = yaml_entrances[e.id]
        lvl, c = corridors[ye.corridor]
        if ye.side == "start":
            at, out = 0.0, -point_along(c.path, 0.0)[1]
        elif ye.side == "end":
            at, out = c.length, point_along(c.path, c.length)[1]
        else:
            at = ye.at or 0.0
            out = _left(point_along(c.path, at)[1]) * (1 if ye.side == "left" else -1)
        in_key = bld.node(
            f"{bid}:{e.id}:in", "door", e.local, lvl.elevation, lvl.id,
            endpoint=bid if e.main else None,
        )  # fmt: skip
        bld.edge(corridor_key(bid, c, at), in_key, "corridor")
        bld.outside(in_key, e.local, _unit(out), lvl.elevation, e.osm_node)
        if e.metro_shaft:
            bld.shaft(in_key, e.local, lvl.elevation, lvl.id)

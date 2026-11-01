"""LOD2/3 interiors: spaces, walls with door gaps, stair flights and floor plates.

Everything is planned in the building's local frame (metres, +x along the bearing) and only
turned into web meshes at the end; the same plan feeds the indoor graph (network/indoor.py).

- **Spaces**: corridors are their centreline buffered by half the width; rooms and stairs
  are boxes on one side of a corridor (or explicit polygons).
- **Walls**: the outlines of every space, the corridors' union and the footprint, merged
  into one linework, thickened to ``WALL_T`` and cut by door gaps. Above each gap a lintel
  closes the wall from ``DOOR_H`` up.
- **Stairs**: a stairwell that appears on consecutive levels gets a dog-leg flight on the
  lower one: up away from the corridor to a landing at half height, then back. You arrive
  next to the corridor, where you started one level lower.
- **Slabs**: the level outline minus the stairwell openings.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

from ..campus.geo import LocalFrame
from ..schemas.building import Building, Corridor, Level, Room, Stairs
from .building import SLAB_LIFT_M, LevelSpan, PlacedBuilding, point_along
from .mesh import Lines, Origin, TriMesh, flat, outline, polygons, prism

WALL_T = 0.2  # wall thickness
DOOR_W = 0.9
ENTRANCE_W = 1.8
DOOR_H = 2.1
RISER_M = 0.17  # target step height
LANDING_M = 1.2  # depth of the half-way landing
STEP_T = 0.35  # thickness of a step block (the flight is open underneath)
SPACE_LIFT_M = SLAB_LIFT_M + 0.02  # space floors sit just above the slab
SHAFT_SIDE_M = 6.0

Vec = np.ndarray


@dataclass
class Gap:
    """An opening in a wall: centre and direction along the wall, local metres."""

    centre: Vec
    along: Vec
    width: float


@dataclass
class Space:
    id: str
    kind: str  # corridor | room | stairs
    level: int
    polygon: Polygon  # local, counter-clockwise
    name: str | None = None
    capacity: int | None = None
    doors: list[Vec] = field(default_factory=list)


@dataclass
class Flight:
    """Stairs from ``level`` up to the next level, in the stair box's own frame:
    ``origin`` = a corner on the corridor side, ``u`` along that side, ``n`` away from it."""

    stairs_id: str
    level: int
    rise: float
    origin: Vec
    u: Vec
    n: Vec
    width: float
    depth: float

    def rect(self, u0: float, u1: float, n0: float, n1: float) -> Polygon:
        o, u, n = self.origin, self.u, self.n
        corners = [(u0, n0), (u1, n0), (u1, n1), (u0, n1)]
        return Polygon([o + u * a + n * b for a, b in corners])

    @property
    def run(self) -> float:
        """Length of one flight; the rest of the depth is the landing."""
        return max(1.0, self.depth - LANDING_M)

    def first_half(self) -> Polygon:
        """Where the next flight up starts (on the level above the landing)."""
        return self.rect(0, self.width / 2, 0, self.run)


@dataclass
class LevelPlan:
    span: LevelSpan
    outline: Polygon  # level footprint, local
    spaces: list[Space]
    gaps: list[Gap]
    flights: list[Flight]  # going up from this level
    openings: list[Polygon]  # holes in this level's slab


def _left(t: Vec) -> Vec:
    return np.array([-t[1], t[0]])


def _unit(v: Vec) -> Vec:
    n = float(np.hypot(*v))
    return v / n if n > 0 else np.array([1.0, 0.0])


def corridor_polygon(c: Corridor) -> Polygon:
    poly = LineString(c.path).buffer(c.width / 2, cap_style="flat", join_style="mitre")
    return orient(poly, 1.0)


def _wall_point(c: Corridor, at: float, side: str) -> tuple[Vec, Vec]:
    """Point on a corridor side wall ``at`` metres along it, and the wall direction."""
    p, t = point_along(c.path, at)
    sign = 1.0 if side == "left" else -1.0
    return p + _left(t) * sign * c.width / 2, t


def _box(c: Corridor, space: Room | Stairs) -> Polygon:
    sign = 1.0 if space.side == "left" else -1.0
    p0, t0 = point_along(c.path, space.at)
    p1, t1 = point_along(c.path, space.at + space.width)
    n0, n1 = _left(t0) * sign, _left(t1) * sign
    inner0, inner1 = p0 + n0 * c.width / 2, p1 + n1 * c.width / 2
    outer0, outer1 = inner0 + n0 * space.depth, inner1 + n1 * space.depth
    return orient(Polygon([inner0, inner1, outer1, outer0]), 1.0)


def _space_doors(
    space: Room | Stairs, polygon: Polygon, corridors: dict[str, Corridor]
) -> list[tuple[Vec, Vec]]:
    """(point, wall direction) of every door of a room or stairwell."""
    out = []
    for corridor_id, at in space.door_positions():
        c = corridors[corridor_id]
        if space.polygon is None:
            out.append(_wall_point(c, at, space.side))
        else:  # explicit polygon: the door is on the corridor wall facing it
            cands = [_wall_point(c, at, s) for s in ("left", "right")]
            out.append(min(cands, key=lambda pt: polygon.distance(Point(pt[0]))))
    return out


def _flight(stairs_id: str, level: int, rise: float, polygon: Polygon, front: Vec) -> Flight:
    """Fit a flight into a stair box: its corridor side is the rectangle edge nearest to
    the door ``front``."""
    rect = shapely.oriented_envelope(polygon)
    c = np.asarray(rect.exterior.coords)[:4]
    centre = c.mean(axis=0)
    edges = [(c[i], c[(i + 1) % 4]) for i in range(4)]
    a, b = min(edges, key=lambda e: float(np.hypot(*((e[0] + e[1]) / 2 - front))))
    u = _unit(b - a)
    n = _left(u)
    if float(np.dot(centre - a, n)) < 0:
        n = -n
    return Flight(
        stairs_id, level, rise, a, u, n, float(np.hypot(*(b - a))), 2 * float(np.dot(centre - a, n))
    )


def plan_levels(p: PlacedBuilding) -> list[LevelPlan]:
    """Spaces, gaps, flights and slab openings of every level (LOD2/3 only)."""
    b: Building = p.building
    if not b.levels:
        return []
    corridors = {c.id: c for lvl in b.levels for c in lvl.corridors}
    levels: list[Level] = sorted(b.levels, key=lambda x: x.id)
    spans = {s.id: s for s in p.levels}

    plans: list[LevelPlan] = []
    for lvl in levels:
        outline = p.footprint_local
        if lvl.footprint is not None:
            outline = orient(Polygon(lvl.footprint).buffer(0), 1.0)
        spaces: list[Space] = []
        gaps: list[Gap] = []
        taken = Polygon()
        for c in lvl.corridors:
            poly = corridor_polygon(c)
            # meeting corridors: the first one owns the overlap. When that would cut this one
            # in two (a corridor crossing another in the middle), it keeps its whole shape
            # and both draw the crossing, rather than one arm losing its floor
            own = polygons(poly.difference(taken))
            taken = taken.union(poly)
            if own:
                spaces.append(Space(c.id, "corridor", lvl.id, own[0] if len(own) == 1 else poly))
        for kind, items in (("room", lvl.rooms), ("stairs", lvl.stairs)):
            for s in items:
                if s.polygon is not None:
                    poly = orient(Polygon(s.polygon).buffer(0), 1.0)
                else:
                    poly = _box(corridors[s.corridor], s)
                doors = _space_doors(s, poly, corridors)
                spaces.append(
                    Space(
                        s.id, kind, lvl.id, poly,
                        name=getattr(s, "name", None), capacity=getattr(s, "capacity", None),
                        doors=[d[0] for d in doors],
                    )
                )  # fmt: skip
                if kind == "stairs":  # stairwells are open to the corridor
                    front, along = doors[0]
                    gaps.append(Gap(front, along, max(DOOR_W, _front_width(poly, front) - WALL_T)))
                else:
                    gaps += [Gap(pt, t, DOOR_W) for pt, t in doors]
        plans.append(LevelPlan(spans[lvl.id], outline, spaces, gaps, [], []))

    for e in b.entrances:
        if e.corridor is None:
            continue
        c = corridors[e.corridor]
        level = next(lv for lv in levels if any(x.id == c.id for x in lv.corridors))
        if e.side in ("start", "end"):
            end = 0 if e.side == "start" else -1
            pt = np.asarray(c.path[end], float)
            _, t = point_along(c.path, 0.0 if e.side == "start" else c.length)
            gap = Gap(pt, _left(t), ENTRANCE_W)
        else:
            pt, t = _wall_point(c, e.at or 0.0, e.side)
            gap = Gap(pt, t, ENTRANCE_W)
        next(pl for pl in plans if pl.span.id == level.id).gaps.append(gap)

    # stairwells: a flight from each level to the next one where the same id appears
    for lower, upper in zip(plans, plans[1:], strict=False):
        upper_ids = {s.id for s in upper.spaces if s.kind == "stairs"}
        rise = upper.span.elevation - lower.span.elevation
        for s in lower.spaces:
            if s.kind != "stairs" or s.id not in upper_ids:
                continue
            f = _flight(s.id, lower.span.id, rise, s.polygon, s.doors[0])
            lower.flights.append(f)
    for i, pl in enumerate(plans):
        arriving = plans[i - 1].flights if i > 0 else []
        going = {f.stairs_id for f in pl.flights}
        for f in arriving:
            box = f.rect(0, f.width, 0, f.depth)
            # top of a stairwell: keep the floor where the next flight would start
            pl.openings.append(box if f.stairs_id in going else box.difference(f.first_half()))
    return plans


def _front_width(poly: Polygon, front: Vec) -> float:
    rect = shapely.oriented_envelope(poly)
    c = np.asarray(rect.exterior.coords)[:4]
    edges = [(c[i], c[(i + 1) % 4]) for i in range(4)]
    a, b = min(edges, key=lambda e: float(np.hypot(*((e[0] + e[1]) / 2 - front))))
    return float(np.hypot(*(b - a)))


# --- meshes --------------------------------------------------------------------------


@dataclass
class LevelMeshes:
    slab: TriMesh
    walls: TriMesh
    spaces: dict[str, TriMesh]  # space id -> floor patch
    stairs: dict[str, TriMesh]  # stairwell id -> the flight up from this level


def _metric(geom, frame: LocalFrame):
    return shapely.transform(geom, lambda xy: frame.to_metric(np.asarray(xy, float)))


def wall_polygons(pl: LevelPlan):
    """(wall area without the door gaps, lintel area above the gaps), local."""
    corridors = shapely.union_all([s.polygon for s in pl.spaces if s.kind == "corridor"])
    rings = [r for poly in polygons(pl.outline) for r in [poly.exterior, *poly.interiors]]
    rings += [r for poly in polygons(corridors) for r in [poly.exterior, *poly.interiors]]
    rings += [s.polygon.exterior for s in pl.spaces if s.kind != "corridor"]
    lines = shapely.union_all([LineString(r.coords) for r in rings])
    area = lines.buffer(WALL_T / 2, cap_style="square", join_style="mitre")
    area = area.intersection(pl.outline.buffer(WALL_T / 2, join_style="mitre"))
    cuts = shapely.union_all(
        [
            Polygon(
                [
                    g.centre + g.along * sx * g.width / 2 + _left(g.along) * sy * 0.3
                    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
                ]
            )
            for g in pl.gaps
        ]
    )
    return area.difference(cuts), area.intersection(cuts)


def _step_block(geom, y0: float, y1: float, origin: Origin) -> TriMesh:
    """Closed box (also the bottom face)."""
    return TriMesh.concat([prism(geom, y0, y1, origin), flat(geom, y0, origin, up=False)])


def flight_mesh(f: Flight, floor_y: float, frame: LocalFrame, origin: Origin) -> TriMesh:
    """Dog-leg flight as step blocks: up along the first half, landing, back along the
    second half."""
    half = f.rise / 2
    n_steps = max(2, round(half / RISER_M))
    rise = half / n_steps
    tread = f.run / n_steps
    parts = []
    for j in range(n_steps):
        top_a = floor_y + (j + 1) * rise
        rect_a = f.rect(0, f.width / 2, j * tread, (j + 1) * tread)
        parts.append(_step_block(_metric(rect_a, frame), top_a - STEP_T, top_a, origin))
        top_b = floor_y + half + (j + 1) * rise
        rect_b = f.rect(f.width / 2, f.width, f.run - (j + 1) * tread, f.run - j * tread)
        parts.append(_step_block(_metric(rect_b, frame), top_b - STEP_T, top_b, origin))
    landing = f.rect(0, f.width, f.run, f.depth)
    top = floor_y + half
    parts.append(_step_block(_metric(landing, frame), top - STEP_T, top, origin))
    return TriMesh.concat(parts)


def interior_meshes(
    p: PlacedBuilding, plans: list[LevelPlan], origin: Origin
) -> dict[int, LevelMeshes]:
    out = {}
    for pl in plans:
        y0 = p.ground_y + pl.span.elevation
        y1 = y0 + pl.span.height
        slab = pl.outline
        for hole in pl.openings:
            slab = slab.difference(hole)
        low, lintel = wall_polygons(pl)
        # walls are closed solids (also the bottom, just above the floor patches), so a
        # wall cut by the section plane shows its inside, drawn as the dark poche, even
        # when seen straight from above
        w0 = y0 + SPACE_LIFT_M + 0.01
        wall_mesh = TriMesh.concat(
            [
                prism(_metric(low, p.frame), w0, y1, origin),
                flat(_metric(low, p.frame), w0, origin, up=False),
                prism(_metric(lintel, p.frame), y0 + DOOR_H, y1, origin),
                flat(_metric(lintel, p.frame), y0 + DOOR_H, origin, up=False),
            ]
        )
        spaces = {}
        for s in pl.spaces:
            patch = s.polygon
            for hole in pl.openings:
                patch = patch.difference(hole)
            spaces[s.id] = flat(_metric(patch, p.frame), y0 + SPACE_LIFT_M, origin)
        stairs = {f.stairs_id: flight_mesh(f, y0, p.frame, origin) for f in pl.flights}
        out[pl.span.id] = LevelMeshes(
            flat(_metric(slab, p.frame), y0 + SLAB_LIFT_M, origin), wall_mesh, spaces, stairs
        )
    return out


def shaft_lines(p: PlacedBuilding, depth_m: float, origin: Origin) -> Lines:
    """Outline of the metro shaft under the entrance marked ``metro_shaft``."""
    e = next((e for e in p.entrances if e.metro_shaft), None)
    if e is None or depth_m <= 0:
        return Lines()
    h = SHAFT_SIDE_M / 2
    x, y = e.local
    sq = Polygon([(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)])
    return outline(_metric(sq, p.frame), [p.ground_y - depth_m, p.ground_y], origin, corner_deg=1)


def space_size(poly: Polygon) -> tuple[float, float]:
    """Side lengths of the minimum rotated rectangle, longer first."""
    env = shapely.oriented_envelope(poly)
    if env.geom_type != "Polygon":  # a degenerate space: a line or a point has no sides
        return (0.0, 0.0)
    c = np.asarray(env.exterior.coords)
    a = math.dist(c[0], c[1])
    b = math.dist(c[1], c[2])
    return (max(a, b), min(a, b))

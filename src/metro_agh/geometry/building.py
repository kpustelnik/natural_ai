"""Building YAML -> placed geometry (footprint, levels, entrances) and LOD1 meshes.

LOD2/3 interiors (slabs with openings, walls, rooms, stairs) come in phase 3; until then
every building is drawn as its shell, split by levels so the viewer can isolate floors.
"""

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from ..campus.geo import LocalFrame, to_metric
from ..schemas.building import Building, Entrance
from .mesh import Lines, Origin, TriMesh, flat, outline, walls

# slabs float above their floor, so the L0 slab stays above the ground and the path
# ribbons (up to 0.12 m, campus/ground.glb)
SLAB_LIFT_M = 0.15


@dataclass
class LevelSpan:
    id: int
    elevation: float  # relative to the building's ground
    height: float


@dataclass
class PlacedEntrance:
    id: str
    local: tuple[float, float]
    metric: tuple[float, float]
    level: int
    main: bool
    metro_shaft: bool
    osm_node: int | None


@dataclass
class PlacedBuilding:
    building: Building
    frame: LocalFrame
    ground_y: float  # web y of the building's ground (z = 0 in the local frame)
    footprint_local: Polygon  # oriented counter-clockwise
    footprint: Polygon  # EPSG:2180
    levels: list[LevelSpan]
    entrances: list[PlacedEntrance]

    @property
    def top_y(self) -> float:
        top = self.levels[-1]
        return self.ground_y + top.elevation + top.height

    @property
    def base_y(self) -> float:
        return self.ground_y + self.levels[0].elevation

    @property
    def height_m(self) -> float:
        return self.top_y - self.ground_y


def point_along(path: list[tuple[float, float]], at: float) -> tuple[np.ndarray, np.ndarray]:
    """Point ``at`` metres along a polyline and the unit tangent there (clamped to the ends)."""
    pts = np.asarray(path, float)
    seg = np.diff(pts, axis=0)
    lengths = np.hypot(seg[:, 0], seg[:, 1])
    rest = max(0.0, at)
    for i, length in enumerate(lengths):
        if rest <= length or i == len(lengths) - 1:
            t = seg[i] / length if length > 0 else np.array([1.0, 0.0])
            return pts[i] + t * min(rest, length), t
        rest -= length
    raise ValueError("empty path")


def _levels(b: Building, cfg: dict) -> list[LevelSpan]:
    if b.levels:
        return [
            LevelSpan(lvl.id, lvl.elevation, lvl.height)
            for lvl in sorted(b.levels, key=lambda x: x.id)
        ]
    floor_h = cfg["campus"]["floor_height_m"]
    n = b.n_levels
    if n is None:
        n = max(1, round(b.height_m / floor_h)) if b.height_m else cfg["campus"]["default_levels"]
    height = b.height_m if b.height_m else n * floor_h
    return [LevelSpan(i, i * height / n, height / n) for i in range(n)]


def _entrance_local(b: Building, e: Entrance) -> tuple[tuple[float, float], int]:
    if e.point is not None:
        return (float(e.point[0]), float(e.point[1])), 0
    level, corridor = b.corridors()[e.corridor]
    if e.side == "start":
        p = np.asarray(corridor.path[0], float)
    elif e.side == "end":
        p = np.asarray(corridor.path[-1], float)
    else:
        p, t = point_along(corridor.path, e.at or 0.0)
        left = np.array([-t[1], t[0]])
        p = p + left * (corridor.width / 2) * (1 if e.side == "left" else -1)
    return (float(p[0]), float(p[1])), level.id


def osm_index(osm_buildings) -> dict[str, int]:
    """Every OSM element id of the buildings layer (also merged parts) -> row position."""
    index = {}
    for pos, ids in enumerate(osm_buildings.osm_ids):
        for i in ids.split("|"):
            index[i] = pos
    return index


def match_osm(b: Building, osm_buildings, index: dict[str, int]):
    """(row, geometry) of the OSM building a YAML describes: by ``osm_id``, else by code."""
    if b.osm_id and b.osm_id in index:
        row = index[b.osm_id]
    else:  # bootstrapped files always carry osm_id; hand-made ones may match by code
        match = np.flatnonzero((osm_buildings.building_id == b.id).to_numpy())
        row = int(match[0]) if len(match) else None
    return row, (osm_buildings.geometry.iloc[row] if row is not None else None)


def largest_polygon(geom) -> Polygon | None:
    if geom is None:
        return None
    parts = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
    parts = [p for p in parts if p.geom_type == "Polygon"]
    return max(parts, key=lambda p: p.area) if parts else None


def place(b: Building, cfg: dict, origin_z: float, osm_outline: Polygon | None) -> PlacedBuilding:
    """Put a building into the world. ``osm_outline`` (EPSG:2180) is used when the YAML has
    no footprint."""
    frame = LocalFrame(tuple(to_metric(*b.placement.anchor)), b.placement.bearing_deg)
    if b.footprint is not None:
        local = Polygon(b.footprint, b.footprint_holes)
    elif osm_outline is not None:
        ext = frame.to_local(np.asarray(osm_outline.exterior.coords))
        holes = [frame.to_local(np.asarray(r.coords)) for r in osm_outline.interiors]
        local = Polygon(ext, holes)
    else:
        raise ValueError(f"{b.id}: no footprint and no OSM outline")
    local = orient(local.buffer(0) if not local.is_valid else local, 1.0)
    if local.geom_type != "Polygon":  # buffer(0) of a bow-tie can split it
        local = max(local.geoms, key=lambda p: p.area)
    metric = Polygon(
        frame.to_metric(np.asarray(local.exterior.coords)),
        [frame.to_metric(np.asarray(r.coords)) for r in local.interiors],
    )
    ground = b.placement.ground_elevation_m
    ground_y = 0.0 if ground is None else ground - origin_z

    main_id = next((e.id for e in b.entrances if e.metro_shaft), None)
    if main_id is None and b.entrances:
        main_id = b.entrances[0].id
    entrances = []
    for e in b.entrances:
        loc, level = _entrance_local(b, e)
        m = frame.to_metric(np.asarray([loc]))[0]
        entrances.append(
            PlacedEntrance(
                e.id, loc, (float(m[0]), float(m[1])), level, e.id == main_id, e.metro_shaft,
                e.osm_node,
            )
        )  # fmt: skip
    return PlacedBuilding(
        b, frame, ground_y, local, orient(metric, 1.0), _levels(b, cfg), entrances
    )


@dataclass
class BuildingMeshes:
    shell: TriMesh  # outer walls, all levels
    roof: TriMesh
    slabs: dict[int, TriMesh]  # level id -> floor plate (shown when the building is opened)
    edges: Lines  # outline at every floor + corners


def lod1_meshes(p: PlacedBuilding, origin: Origin) -> BuildingMeshes:
    floors = [p.ground_y + lv.elevation for lv in p.levels]
    return BuildingMeshes(
        shell=walls(p.footprint, p.base_y, p.top_y, origin),
        roof=flat(p.footprint, p.top_y, origin),
        slabs={
            lv.id: flat(p.footprint, y + SLAB_LIFT_M, origin)
            for lv, y in zip(p.levels, floors, strict=True)
        },
        edges=outline(p.footprint, [*floors, p.top_y], origin),
    )


def frame_axes_web(bearing_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Unit vectors of local +x and +y in the web frame (y component 0)."""
    b = math.radians(bearing_deg)
    return (
        np.array([math.sin(b), 0.0, -math.cos(b)]),
        np.array([-math.cos(b), 0.0, -math.sin(b)]),
    )

"""Hand-written building description: ``data/campus/buildings/<id>.yaml``.

A building is modelled in its own local frame (metres): origin at ``placement.anchor``
(usually the main entrance), +x along ``placement.bearing_deg``, +y 90 degrees to the left
of +x, +z up from the ground at the anchor.

Interiors are parametric: each level has corridors (centrelines with a width), and rooms and
stairs are boxes attached to one side of a corridor at a distance ``at`` along it. Walls,
slabs, doors and the indoor walking graph are generated from that; nothing is drawn by hand.

Level of detail is implied by what is filled in:
    LOD1  no levels           -> extruded footprint, one trip endpoint for the whole building
    LOD2  levels + corridors  -> floors, corridors, stairs, entrances
    LOD3  + rooms             -> room-to-room routing
"""

import math
from typing import Literal, Self

from pydantic import Field, PositiveFloat, model_validator

from .common import (
    SCHEMA_VERSION,
    BuildingId,
    LevelId,
    LocalId,
    LonLat,
    PlaceKind,
    RoomId,
    StrictModel,
    Vec2,
)

Side = Literal["left", "right"]  # relative to the corridor's direction (first -> last point)

# tolerance for "a position lies on a corridor" checks, in metres
_EPS_M = 0.05


def polyline_length(path: list[Vec2]) -> float:
    return sum(math.dist(a, b) for a, b in zip(path, path[1:], strict=False))


class Placement(StrictModel):
    anchor: LonLat = Field(description="lon, lat of the local origin (take it from any web map)")
    bearing_deg: float = Field(
        default=90.0,
        ge=0,
        lt=360,
        description="grid bearing (EPSG:2180) of local +x: 0 = north, 90 = east (default)",
    )
    ground_elevation_m: float | None = Field(
        default=None, description="absolute ground height at the anchor; None = from DEM or 0"
    )


class Corridor(StrictModel):
    id: LocalId = Field(description="unique within the whole building")
    path: list[Vec2] = Field(min_length=2, description="centreline, local metres")
    width: PositiveFloat = 2.5

    @property
    def length(self) -> float:
        return polyline_length(self.path)


class Door(StrictModel):
    """Door from an explicitly drawn space into a corridor."""

    corridor: LocalId
    at: float = Field(ge=0, description="metres along the corridor centreline")


class _AttachedBox(StrictModel):
    """A box on one side of a corridor, or an explicit polygon with doors."""

    corridor: LocalId | None = None
    side: Side | None = None
    at: float | None = Field(default=None, ge=0, description="start of the box along corridor")
    width: PositiveFloat | None = Field(default=None, description="extent along the corridor")
    depth: PositiveFloat | None = Field(default=None, description="extent away from corridor")
    door_at: float | None = Field(
        default=None, ge=0, description="door offset from the box start; default = middle"
    )
    polygon: list[Vec2] | None = Field(
        default=None, min_length=3, description="explicit outline instead of a box"
    )
    doors: list[Door] | None = None

    @model_validator(mode="after")
    def _box_or_polygon(self) -> Self:
        box = (self.corridor, self.side, self.at, self.width, self.depth)
        if self.polygon is None:
            if any(v is None for v in box):
                raise ValueError("give either corridor+side+at+width+depth, or polygon+doors")
            if self.doors is not None:
                raise ValueError("doors are only for polygon spaces; use door_at for boxes")
            if self.door_at is not None and self.door_at > self.width:
                raise ValueError("door_at must lie within the box width")
        else:
            if any(v is not None for v in box) or self.door_at is not None:
                raise ValueError("polygon spaces cannot also use corridor/side/at/width/depth")
            if not self.doors:
                raise ValueError("polygon spaces need at least one door")
        return self

    def door_positions(self) -> list[tuple[str, float]]:
        """(corridor id, position along it) of every door."""
        if self.polygon is not None:
            return [(d.corridor, d.at) for d in self.doors or []]
        offset = self.door_at if self.door_at is not None else self.width / 2
        return [(self.corridor, self.at + offset)]


class Room(_AttachedBox):
    id: RoomId = Field(description="room number as in USOS, without the building prefix")
    name: str | None = None
    capacity: int | None = Field(default=None, ge=0)


class Stairs(_AttachedBox):
    """Stairwell landing on one level. Same id on several levels = one stairwell;
    consecutive levels where it appears are connected."""

    id: LocalId


class Level(StrictModel):
    id: LevelId
    elevation: float = Field(description="floor height above the anchor ground, metres")
    height: PositiveFloat = Field(default=3.5, description="floor-to-floor height")
    footprint: list[Vec2] | None = Field(
        default=None, min_length=3, description="outline override for this level"
    )
    corridors: list[Corridor] = []
    rooms: list[Room] = []
    stairs: list[Stairs] = []


class Entrance(StrictModel):
    id: LocalId
    # interior building: door in a corridor side wall (left/right + at)
    # or in the wall closing the corridor at its first/last point (start/end, no at)
    corridor: LocalId | None = None
    side: Literal["left", "right", "start", "end"] | None = None
    at: float | None = Field(default=None, ge=0)
    # LOD1 building: just a point on the outline
    point: Vec2 | None = None
    metro_shaft: bool = Field(
        default=False, description="candidate metro station lies under this entrance"
    )
    osm_node: int | None = Field(
        default=None, description="force the outdoor link to this OSM node; default = nearest"
    )

    @model_validator(mode="after")
    def _corridor_or_point(self) -> Self:
        if self.point is not None:
            if any(v is not None for v in (self.corridor, self.side, self.at)):
                raise ValueError("entrance takes either point or corridor+side, not both")
            return self
        if self.corridor is None or self.side is None:
            raise ValueError("entrance needs corridor+side(+at), or point")
        if self.side in ("left", "right") and self.at is None:
            raise ValueError("entrance on a side wall needs at")
        if self.side in ("start", "end") and self.at is not None:
            raise ValueError("entrance at the corridor start/end takes no at")
        return self


class Building(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    id: BuildingId = Field(description="canonical code; must match the file name")
    name: str | None = None
    kind: PlaceKind = PlaceKind.ACADEMIC
    aliases: list[str] = Field(default=[], description="other spellings used by USOS")
    osm_id: str | None = Field(
        default=None, pattern=r"^(way|relation)/\d+$", description="OSM baseline footprint"
    )
    residents: int | None = Field(
        default=None, ge=0, description="dorms only: beds, used to distribute dorm students"
    )
    placement: Placement
    footprint: list[Vec2] | None = Field(
        default=None, min_length=3, description="local outline; None = take OSM footprint"
    )
    footprint_holes: list[list[Vec2]] = Field(
        default=[], description="courtyards inside the footprint (local outlines)"
    )
    # LOD1 only (ignored when levels are given)
    n_levels: int | None = Field(default=None, ge=1)
    height_m: PositiveFloat | None = None

    levels: list[Level] = []
    entrances: list[Entrance] = []

    @property
    def lod(self) -> int:
        if not self.levels:
            return 1
        return 3 if any(lvl.rooms for lvl in self.levels) else 2

    def corridors(self) -> dict[str, tuple[Level, Corridor]]:
        return {c.id: (lvl, c) for lvl in self.levels for c in lvl.corridors}

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        errors: list[str] = []

        ids = [lvl.id for lvl in self.levels]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate level ids: {ids}")
        ordered = sorted(self.levels, key=lambda lvl: lvl.id)
        for lower, upper in zip(ordered, ordered[1:], strict=False):
            if upper.elevation <= lower.elevation:
                errors.append(f"level {upper.id} must be higher than level {lower.id}")

        corridor_ids = [c.id for lvl in self.levels for c in lvl.corridors]
        if len(corridor_ids) != len(set(corridor_ids)):
            errors.append("corridor ids must be unique within the building")
        corridors = self.corridors()

        room_ids = [r.id for lvl in self.levels for r in lvl.rooms]
        if len(room_ids) != len(set(room_ids)):
            errors.append("room ids must be unique within the building")

        def check_on(where: str, level: Level | None, corridor_id: str, at: float) -> None:
            if corridor_id not in corridors:
                errors.append(f"{where}: unknown corridor {corridor_id!r}")
                return
            lvl, corridor = corridors[corridor_id]
            if level is not None and lvl.id != level.id:
                errors.append(f"{where}: corridor {corridor_id!r} is on level {lvl.id}")
            if at > corridor.length + _EPS_M:
                errors.append(
                    f"{where}: at={at} beyond corridor {corridor_id!r} "
                    f"(length {corridor.length:.2f})"
                )

        stairs_levels: dict[str, list[int]] = {}
        for lvl in self.levels:
            for space in [*lvl.rooms, *lvl.stairs]:
                where = f"level {lvl.id} {type(space).__name__.lower()} {space.id!r}"
                if space.polygon is None:
                    check_on(where, lvl, space.corridor, space.at + space.width)
                for corridor_id, at in space.door_positions():
                    check_on(where + " door", lvl, corridor_id, at)
            for s in lvl.stairs:
                stairs_levels.setdefault(s.id, []).append(lvl.id)
        order = sorted(lvl.id for lvl in self.levels)
        for stairs_id, lvls in stairs_levels.items():
            if len(lvls) < 2:
                errors.append(f"stairs {stairs_id!r} appear only on level {lvls[0]}")
            at = sorted({order.index(i) for i in lvls})
            if at[-1] - at[0] != len(at) - 1:  # the flights are drawn between neighbours only
                errors.append(f"stairs {stairs_id!r} skip a level (on levels {sorted(lvls)})")

        entrance_ids = [e.id for e in self.entrances]
        if len(entrance_ids) != len(set(entrance_ids)):
            errors.append("entrance ids must be unique")
        for e in self.entrances:
            if e.corridor is not None:
                check_on(f"entrance {e.id!r}", None, e.corridor, e.at or 0.0)
            elif self.levels:
                errors.append(f"entrance {e.id!r}: buildings with levels need corridor entrances")
        if sum(e.metro_shaft for e in self.entrances) > 1:
            errors.append("at most one entrance can have metro_shaft: true")

        if self.footprint_holes and self.footprint is None:
            errors.append("footprint_holes need an explicit footprint")
        if any(len(h) < 3 for h in self.footprint_holes):
            errors.append("every hole needs at least 3 points")

        if self.kind != PlaceKind.DORM and self.residents is not None:
            errors.append("residents is only for kind: dorm")

        if errors:
            raise ValueError(f"building {self.id}: " + "; ".join(errors))
        return self

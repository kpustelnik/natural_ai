"""Hand-written campus-level data: ``data/campus/campus.yaml``.

Everything that is not inside one building: passages between buildings, corrections of the
OSM walk network, and the bus/tram stops students arrive at.
"""

from typing import Literal, Self

from pydantic import Field, PositiveFloat, model_validator

from .common import SCHEMA_VERSION, BuildingId, LocalId, LonLat, StopId, StrictModel


class PassageEnd(StrictModel):
    building: BuildingId
    corridor: LocalId = Field(description="corridor id in that building (implies the level)")
    at: float = Field(ge=0)


class Passage(StrictModel):
    """Connection between two buildings that does not go through the OSM walk network."""

    id: LocalId
    a: PassageEnd
    b: PassageEnd
    kind: Literal["indoor", "bridge", "tunnel", "covered"] = "indoor"
    width: PositiveFloat = 3.0
    waypoints: list[LonLat] = Field(default=[], description="intermediate points for geometry")
    length_m: PositiveFloat | None = Field(
        default=None, description="override; default = length through waypoints"
    )


class ExtraPath(StrictModel):
    """Outdoor walkway missing from OSM. Its ends snap to the nearest walk-network nodes."""

    id: LocalId
    path: list[LonLat] = Field(min_length=2)
    note: str | None = None


class RemovedWay(StrictModel):
    """OSM way that students cannot use (fenced, closed gate, construction)."""

    osm_way_id: int
    reason: str


class Stop(StrictModel):
    id: StopId
    name: str
    location: LonLat
    weight: PositiveFloat = Field(
        default=1.0, description="relative share of commuting students arriving here"
    )


class Campus(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    passages: list[Passage] = []
    extra_paths: list[ExtraPath] = []
    removed_ways: list[RemovedWay] = []
    stops: list[Stop] = []

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        for name in ("passages", "extra_paths", "stops"):
            ids = [item.id for item in getattr(self, name)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate ids in {name}")
        return self

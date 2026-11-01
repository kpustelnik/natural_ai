"""Shared conventions for every data contract: IDs, units, time, coordinate frames.

Units: metres and seconds everywhere. Column/field suffixes:
    *_s   duration in seconds
    *_wt  "week time": seconds since Monday 00:00 of the modelled week
    *_m   length in metres
See docs/data_contracts.md for the full description.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SCHEMA_VERSION = 1

# --- identifiers ---------------------------------------------------------

BUILDING_ID_PATTERN = r"^[A-Z][A-Z0-9]*(-[A-Za-z0-9]+)*$"  # D-17, A-0, DS-7, DS-Alfa, P-A0-A1
ROOM_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"  # 1.38, 0.12, aula_1
STOP_ID_PATTERN = r"^stop:[a-z0-9_]+$"  # stop:czarnowiejska
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"  # corridor / stairs / entrance ids
# endpoint key = where a student is: a building, a room in it, or a bus stop
ENDPOINT_KEY_PATTERN = (
    r"^(stop:[a-z0-9_]+|[A-Z][A-Z0-9]*(-[A-Za-z0-9]+)*(/[A-Za-z0-9][A-Za-z0-9._-]*)?)$"
)

BuildingId = Annotated[str, StringConstraints(pattern=BUILDING_ID_PATTERN)]
RoomId = Annotated[str, StringConstraints(pattern=ROOM_ID_PATTERN)]
StopId = Annotated[str, StringConstraints(pattern=STOP_ID_PATTERN)]
LocalId = Annotated[str, StringConstraints(pattern=LOCAL_ID_PATTERN)]

Weekday = Annotated[int, Field(ge=1, le=5)]  # 1 = Monday ... 5 = Friday
LevelId = int  # 0 = ground floor, -1 = first basement, 1 = first floor

# --- geometry ------------------------------------------------------------

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
LonLat = tuple[
    Annotated[float, Field(ge=-180, le=180)],
    Annotated[float, Field(ge=-90, le=90)],
]

METRIC_CRS = "EPSG:2180"  # PL-1992, used for every computation in metres
GEO_CRS = "EPSG:4326"  # lon/lat, used in GeoJSON and hand-written anchors


def endpoint_key(building_id: str, room_id: str | None = None) -> str:
    """Build an endpoint key: ``D-17`` or ``D-17/1.38``."""
    return building_id if room_id is None else f"{building_id}/{room_id}"


# --- enums ---------------------------------------------------------------


class PlaceKind(StrEnum):
    ACADEMIC = "academic"
    DORM = "dorm"
    OTHER = "other"


class HomeKind(StrEnum):
    DORM = "dorm"
    STOP = "stop"


class WeekParity(StrEnum):
    ALL = "all"
    ODD = "odd"
    EVEN = "even"


class SizeSource(StrEnum):
    USOS = "usos"
    ROOM_CAPACITY = "room_capacity"
    ESTIMATE = "estimate"


class LegKind(StrEnum):
    HOME_TO_CLASS = "home_to_class"
    CLASS_TO_CLASS = "class_to_class"
    CLASS_TO_HOME = "class_to_home"


class Scenario(StrEnum):
    NO_METRO = "no_metro"
    METRO = "metro"


class Mode(StrEnum):
    WALK = "walk"
    METRO = "metro"
    TRANSIT = "transit"  # bus / tram between campus stops (GTFS)


class MetroTopology(StrEnum):
    LINE = "line"  # trains shuttle A-B-C-D-C-B-A
    LOOP = "loop"  # A-B-C-D-A, trains run in both directions


class NodeKind(StrEnum):
    OSM = "osm"  # outdoor walk network node
    CORRIDOR = "corridor"  # point on a corridor centreline
    ROOM = "room"  # centre of a room (trip endpoint)
    DOOR = "door"  # room door / entrance door
    STAIRS = "stairs"  # stair landing on one level
    ENTRANCE = "entrance"  # outside side of a building entrance
    SHAFT_TOP = "shaft_top"  # metro station access at ground level (main entrance)
    PLATFORM = "platform"  # metro platform, station_depth_m below shaft top
    STOP = "stop"  # bus/tram stop (external origin)
    PLACE = "place"  # LOD1 building without interior (trip endpoint)


class EdgeKind(StrEnum):
    OUTDOOR = "outdoor"
    CORRIDOR = "corridor"
    DOOR = "door"
    STAIRS = "stairs"
    ENTRANCE = "entrance"
    PASSAGE = "passage"
    SHAFT = "shaft"  # stairs from shaft top down to the platform
    LINK = "link"  # generated connector: stop/place/entrance to the walk graph, entrance to shaft


class StrictModel(BaseModel):
    """Base for every contract model. Unknown keys are errors, which catches YAML typos."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        use_enum_values=True,
        # in "serialization" schemas (what readers receive) fields with defaults are present
        json_schema_serialization_defaults_required=True,
    )


class Provenance(StrictModel):
    """Attached to every generated JSON file, so stale outputs can be detected."""

    schema_version: int = SCHEMA_VERSION
    generated_at: str = Field(description="ISO 8601 timestamp")
    generator: str = Field(description="script that produced the file, e.g. 04_optimize.py")
    config_hash: str | None = Field(default=None, description="sha256 of the resolved config")
    git_commit: str | None = None

"""Files read by the three.js viewer (``web/public/data/``). Written only by ``06_export_web.py``.

All positions are already in the **web frame** (three.js, Y up, metres):
    x =  easting  - origin easting   (EPSG:2180)
    y =  height   - origin height
    z = -(northing - origin northing)
All web times ``t`` are seconds since 00:00 of that weekday (float).

Large arrays travel as binary: ``<name>.json`` (a BinaryHeader) + ``<name>.bin`` (raw,
little-endian buffers). In TypeScript: ``new Float32Array(bin, view.offset, view.count)``.
"""

from typing import ClassVar, Literal, Self

from pydantic import Field, model_validator

from .common import (
    BuildingId,
    LevelId,
    LonLat,
    MetroTopology,
    PlaceKind,
    Provenance,
    Scenario,
    StopId,
    StrictModel,
    Vec3,
    Weekday,
)

DayTime = float  # seconds since 00:00 of the weekday

MODE_CODES = {"walk": 0, "metro": 1}  # uint8 codes used in binary buffers


class WebFrame(StrictModel):
    origin_lonlat: LonLat
    origin_x: float = Field(description="EPSG:2180 easting of the origin")
    origin_y: float = Field(description="EPSG:2180 northing of the origin")
    origin_z: float = Field(description="absolute height mapped to web y = 0")
    axes: Literal["x=east,y=up,z=-north"] = "x=east,y=up,z=-north"


# --- scene.json ------------------------------------------------------------


class SceneLevel(StrictModel):
    id: LevelId
    floor_y: float = Field(description="web y of the floor")
    height: float


class SceneBuilding(StrictModel):
    id: BuildingId
    name: str | None
    kind: PlaceKind
    lod: Literal[1, 2, 3]
    glb: str = Field(description="path relative to the data dir, e.g. buildings/D-17.glb")
    levels: list[SceneLevel]
    bbox_min: Vec3
    bbox_max: Vec3


class SceneStop(StrictModel):
    id: StopId
    name: str
    position: Vec3


class Scene(StrictModel):
    provenance: Provenance
    frame: WebFrame
    buildings: list[SceneBuilding]
    stops: list[SceneStop]
    ground_glb: str | None = Field(default=None, description="terrain / paths mesh")


# --- metro.json ------------------------------------------------------------


class MetroStation(StrictModel):
    building_id: BuildingId
    top: Vec3 = Field(description="shaft top at the main entrance")
    platform: Vec3


class RunStop(StrictModel):
    station: int = Field(ge=0, description="index into stations")
    arrive_t: DayTime
    depart_t: DayTime


class TrainRun(StrictModel):
    run_id: int
    train_id: int
    weekday: Weekday
    direction: Literal[1, -1]
    stops: list[RunStop] = Field(min_length=2)


class Metro(StrictModel):
    provenance: Provenance
    topology: MetroTopology
    stations: list[MetroStation] = Field(min_length=2, description="in line order")
    tunnel: list[Vec3] = Field(
        description="platform-level polyline through stations in order (closed for loop)"
    )
    headway_s: float
    dwell_s: float
    speed_mps: float
    runs: list[TrainRun]


# --- binary containers ------------------------------------------------------


class BufferView(StrictModel):
    dtype: Literal["uint8", "int16", "uint16", "int32", "uint32", "float32"]
    offset: int = Field(ge=0, multiple_of=4, description="byte offset in the .bin file")
    count: int = Field(ge=0, description="number of elements (not bytes)")
    shape: list[int] = Field(description="logical shape; product == count")

    @model_validator(mode="after")
    def _shape(self) -> Self:
        prod = 1
        for d in self.shape:
            prod *= d
        if prod != self.count:
            raise ValueError(f"shape {self.shape} does not match count {self.count}")
        return self


class _BinaryHeader(StrictModel):
    provenance: Provenance
    bin: str = Field(description="file name of the .bin next to this header")
    buffers: dict[str, BufferView]

    REQUIRED: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _required(self) -> Self:
        missing = [b for b in self.REQUIRED if b not in self.buffers]
        if missing:
            raise ValueError(f"missing buffers {missing}")
        return self


class PathsHeader(_BinaryHeader):
    """``trips/<scenario>/paths.{json,bin}``: every distinct path, shared by all days.

    Path p has vertices ``path_offsets[p] .. path_offsets[p+1]-1``.
    ``t`` is the time from the start of the path, so one path is reused by many students.
    """

    kind: Literal["paths"] = "paths"
    scenario: Scenario
    n_paths: int
    REQUIRED = ("path_offsets", "xyz", "t", "mode")
    # path_offsets uint32 (P+1)   xyz float32 (V, 3)   t float32 (V)   mode uint8 (P)


class DayHeader(_BinaryHeader):
    """``trips/<scenario>/day-<weekday>.{json,bin}``: who walks which path when.

    One row = one segment: student ``student_id`` starts path ``path_id`` at ``t_start``.
    A metro leg is three segments (walk to platform, ride, walk out); between segments of
    one leg the student stands at the end of the previous path (waiting). Between legs the
    student is inside a room and not drawn. Rows are sorted by t_start.
    """

    kind: Literal["day"] = "day"
    scenario: Scenario
    weekday: Weekday
    n_students: int
    t_min: DayTime
    t_max: DayTime
    REQUIRED = ("student_id", "leg_id", "path_id", "t_start")
    # student_id uint32 (S)   leg_id uint32 (S)   path_id uint32 (S)   t_start float32 (S)


class AcoTraceHeader(_BinaryHeader):
    """``aco/trace.{json,bin}``: AcoTrace with candidate positions for the animation."""

    kind: Literal["aco_trace"] = "aco_trace"
    run_id: str
    algorithm: str
    topology: MetroTopology
    candidate_ids: list[BuildingId]
    candidate_platforms: list[Vec3]
    REQUIRED = ("iterations", "tours", "tour_cost_s", "best_tour", "pheromone")


# --- stats.json --------------------------------------------------------------


class ScenarioStats(StrictModel):
    n_legs: int
    total_travel_s: float
    mean_leg_s: float
    n_late: int = Field(description="legs arriving after the class start")
    late_share: float = Field(ge=0, le=1)
    longer_than_break_share: float = Field(ge=0, le=1)
    metro_share: float = Field(ge=0, le=1, description="0 for no_metro")


class HourStats(StrictModel):
    weekday: Weekday
    hour: int = Field(ge=0, le=23)
    n_legs: int
    no_metro_s: float
    metro_s: float


class StationStats(StrictModel):
    building_id: BuildingId
    boardings: int
    alightings: int


class OdStats(StrictModel):
    from_key: str
    to_key: str
    n_legs: int
    saving_s: float


class Stats(StrictModel):
    provenance: Provenance
    scenarios: dict[Scenario, ScenarioStats]
    saving_s: float = Field(description="no_metro total - metro total")
    per_hour: list[HourStats]
    stations: list[StationStats]
    top_od: list[OdStats] = Field(description="largest savings first, at most 50")


WEB_MODELS = {
    "scene": Scene,
    "metro": Metro,
    "stats": Stats,
    "paths_header": PathsHeader,
    "day_header": DayHeader,
    "aco_trace_header": AcoTraceHeader,
}

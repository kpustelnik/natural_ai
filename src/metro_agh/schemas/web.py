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
    Vec2,
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


# --- issues.json -----------------------------------------------------------


class Issue(StrictModel):
    severity: Literal["info", "warning", "error"] = "warning"
    section: str = Field(description="group heading, e.g. 'AGH buildings without entrances'")
    message: str
    building_id: BuildingId | None = None
    osm_id: str | None = Field(default=None, description="e.g. way/123456")
    position: Vec3 | None = Field(default=None, description="web position to jump to")


class IssueList(StrictModel):
    """``issues.json`` (viewer) and ``data/processed/osm/issues.json`` (OSM stage)."""

    provenance: Provenance
    issues: list[Issue]


# --- scene.json ------------------------------------------------------------


class BuildingFrame(StrictModel):
    """The building's local frame in web coordinates. local -> web:
    ``web = anchor + x * (sin b, 0, -cos b) + y * (-cos b, 0, -sin b)`` with b = bearing."""

    anchor: Vec3 = Field(description="web position of the local origin (ground level)")
    bearing_deg: float = Field(description="grid bearing of local +x (EPSG:2180 = web grid)")


class SceneLevel(StrictModel):
    id: LevelId
    floor_y: float = Field(description="web y of the floor")
    height: float


class SceneEntrance(StrictModel):
    id: str
    position: Vec3
    main: bool
    metro_shaft: bool


class SceneBuilding(StrictModel):
    id: BuildingId
    name: str | None
    kind: PlaceKind
    category: Literal["academic", "dorm", "other", "connector"] = Field(
        description="kind, with connectors (P-…) told apart"
    )
    lod: Literal[1, 2, 3]
    glb: str = Field(description="path relative to the data dir, e.g. buildings/D-17.glb")
    info: str = Field(description="BuildingInfo path, e.g. buildings/D-17.json")
    yaml: str = Field(description="source file relative to the repo root")
    osm_id: str | None
    height_m: float
    frame: BuildingFrame
    levels: list[SceneLevel]
    entrances: list[SceneEntrance]
    bbox_min: Vec3
    bbox_max: Vec3
    rooms: list[str] = Field(default=[], description="room ids (LOD3), for the search")
    n_issues: int = 0
    stale: bool = Field(
        default=False, description="the YAML fails validation; these files are the last good ones"
    )


class SceneStop(StrictModel):
    id: StopId
    name: str
    position: Vec3


class SceneContext(StrictModel):
    glb: str = Field(description="all context buildings merged, e.g. campus/context.glb")
    features: str = Field(description="ContextFeatures path, e.g. campus/context.json")


class Extent(StrictModel):
    min: Vec3
    max: Vec3


class SceneAerial(StrictModel):
    """Orthophoto draped on the ground: an axis-aligned rectangle in the web frame."""

    image: str = Field(description="path relative to the data dir, e.g. campus/aerial.jpg")
    min: Vec3 = Field(description="web corner with the smallest x and z")
    max: Vec3
    attribution: str


class Scene(StrictModel):
    provenance: Provenance
    frame: WebFrame
    extent: Extent = Field(description="downloaded area (bbox), for the camera and the ground")
    source_root: str | None = Field(
        default=None, description="absolute repo path on the machine that exported (dev links)"
    )
    buildings: list[SceneBuilding]
    stops: list[SceneStop] = Field(description="stops used by the simulation (campus.yaml)")
    other_stops: list[SceneStop] = Field(default=[], description="OSM stops not in campus.yaml")
    ground_glb: str | None = Field(default=None, description="ground, paths, boundary, fences")
    context: SceneContext | None = None
    network: str | None = Field(default=None, description="NetworkHeader path")
    issues: str | None = Field(default=None, description="IssueList path")
    replays: str | None = Field(default=None, description="ReplayCatalog path")
    aerial: SceneAerial | None = None


# --- buildings/<id>.json -------------------------------------------------------


class InfoSpace(StrictModel):
    id: str
    kind: Literal["corridor", "room", "stairs"]
    polygon: list[Vec2] = Field(description="outline, local metres")
    centre: Vec2 = Field(description="label point inside the polygon, local metres")
    size: Vec2 = Field(description="sides of the minimum rotated rectangle, longer first")
    area_m2: float
    doors: list[Vec2] = Field(default=[], description="door positions, local metres")
    name: str | None = None
    capacity: int | None = None
    bbox_min: Vec3 = Field(description="web bounding box, for framing")
    bbox_max: Vec3


class InfoLevel(StrictModel):
    id: LevelId
    elevation: float
    height: float
    floor_y: float
    spaces: list[InfoSpace] = Field(default=[], description="LOD2/3 only")


class InfoEntrance(StrictModel):
    id: str
    local: Vec2
    position: Vec3
    main: bool
    metro_shaft: bool
    osm_node: int | None = None


class BuildingInfo(StrictModel):
    """Everything the inspector shows about one building, without parsing its glb."""

    provenance: Provenance
    id: BuildingId
    lod: Literal[1, 2, 3]
    frame: BuildingFrame
    footprint: list[Vec2] = Field(description="local metres, counter-clockwise")
    footprint_holes: list[list[Vec2]] = []
    area_m2: float
    height_m: float
    levels: list[InfoLevel]
    entrances: list[InfoEntrance]
    osm_outline: list[list[Vec2]] = Field(
        default=[], description="OSM outline rings in local metres, exterior first"
    )
    osm_hausdorff_m: float | None = Field(
        default=None, description="distance between the footprint and the OSM outline"
    )
    issues: list[Issue] = []


# --- campus/context.json ---------------------------------------------------------


class ContextFeature(StrictModel):
    osm_id: str
    name: str | None
    building: str = Field(description="OSM building tag")
    height_m: float
    height_source: Literal["tag", "levels", "default"]
    index_start: int = Field(ge=0, description="first index of its triangles in the glb mesh")
    index_count: int = Field(ge=0)


class ContextFeatures(StrictModel):
    """Feature id = position in ``features``; the glb mesh carries it as ``_FEATURE_ID``."""

    provenance: Provenance
    features: list[ContextFeature]


# --- status.json ---------------------------------------------------------------


class BuildError(StrictModel):
    file: str = Field(description="relative to the repo root")
    line: int | None = Field(default=None, description="1-based line in the file")
    loc: str | None = Field(default=None, description="pydantic location, e.g. levels.1.rooms.3")
    message: str
    building_id: BuildingId | None = None
    element: str | None = Field(
        default=None, description="id of the room, corridor, stairs or entrance it is about"
    )


class BuildStatus(StrictModel):
    """``status.json``: written last by every export, polled by the dev server."""

    version: int = Field(ge=0, description="increases on every export")
    built_at: str
    changed: list[str] = Field(description="data files (re)written by this export")
    errors: list[BuildError] = []


# --- replays -------------------------------------------------------------------


REPLAY_ID_PATTERN = r"^[a-z0-9][a-z0-9_.-]*$"


class ReplayFiles(StrictModel):
    """Paths relative to the data dir; all of them live under ``replays/<id>/``."""

    metro: str | None = Field(default=None, description="Metro (metro.json)")
    aco_trace: str | None = Field(default=None, description="AcoTraceHeader")
    trips: dict[Scenario, str] = Field(
        default={}, description="scenario -> dir with paths.json and day-<weekday>.json"
    )
    stats: str | None = Field(default=None, description="Stats")


class Replay(StrictModel):
    """``replays/<id>/replay.json``: one thing the viewer can play back."""

    id: str = Field(pattern=REPLAY_ID_PATTERN)
    kind: Literal["aco", "simulation"]
    title: str
    description: str | None = None
    created_at: str
    run_id: str | None = Field(default=None, description="optimisation run it comes from")
    topology: MetroTopology | None = None
    stations: list[BuildingId] = []
    scenarios: list[Scenario] = []
    weekdays: list[Weekday] = []
    files: ReplayFiles


class ReplayCatalog(StrictModel):
    """``replays/index.json``: every replay.json found, newest first."""

    provenance: Provenance
    replays: list[Replay]


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


# drawing classes of network edges: outdoor edges by OSM highway, the rest by GRAPH_EDGES kind
NETWORK_EDGE_KINDS = (
    "footway",
    "road",
    "steps",
    "corridor",
    "door",
    "stairs",
    "entrance",
    "passage",
    "shaft",
    "link",
)


class NetworkBarrier(StrictModel):
    osm_id: str
    barrier: str = Field(description="OSM barrier tag: gate, bollard, ...")
    access: str | None
    position: Vec3


class FieldMeasurement(StrictModel):
    """A row of data/validation/field_measurements.csv, for the route tool."""

    route_id: str
    from_key: str
    to_key: str
    measured_s: float
    date: str
    who: str
    notes: str | None


class NetworkHeader(_BinaryHeader):
    """``network.{json,bin}``: the walk graph (network/*.parquet) for drawing and routing.

    Codes in ``node_kind`` / ``edge_kind`` index into ``node_kind_names`` /
    ``edge_kind_names``; ``node_keys`` / ``edge_sources`` hold what does not fit a typed
    array (OSM ids exceed uint32).
    """

    kind: Literal["network"] = "network"
    n_nodes: int
    n_edges: int
    node_kind_names: list[str] = Field(description="GRAPH_NODES kinds")
    edge_kind_names: list[str] = Field(description="footway, road, steps, then GRAPH_EDGES kinds")
    node_keys: list[str] = Field(description="per node, e.g. 'osm:123', 'D-17/1.38'")
    endpoints: dict[str, int] = Field(
        description="endpoint key (room, building, stop) -> node index"
    )
    edge_sources: list[str | None] = Field(description="per edge, e.g. 'way/1|way/2', 'D-17'")
    barriers: list[NetworkBarrier] = Field(default=[], description="OSM point barriers")
    measurements: list[FieldMeasurement] = Field(
        default=[], description="measured walking times to compare routes with"
    )
    REQUIRED = (
        "node_xyz",
        "node_kind",
        "edge_nodes",
        "edge_kind",
        "length_m",
        "time_uv_s",
        "time_vu_s",
        "segment_xyz",
        "segment_edge",
    )
    # node_xyz float32 (N, 3)   node_kind uint8 (N)
    # edge_nodes uint32 (E, 2)  edge_kind uint8 (E)   length_m, time_uv_s, time_vu_s float32 (E)
    # segment_xyz float32 (S, 2, 3)   segment_edge uint32 (S)
    # segments = the edges' real polylines, for drawing; segment_edge = edge index


class AcoTraceHeader(_BinaryHeader):
    """``replays/<id>/trace.{json,bin}``: AcoTrace (results/<run_id>/trace.npz) with the
    candidate positions and the convergence curve, for the ACO player.

    Buffers (I sampled iterations, A sampled ants, k stations, N candidates, C iterations):
        iterations int32 (I)   tours int16 (I, A, k)   tour_cost_s float32 (I, A)
        best_tour int16 (I, k)   pheromone float32 (I, N, N)
        curve_iteration int32 (C)   curve_best_s, curve_iter_best_s, curve_iter_mean_s float32 (C)
    The curve is convergence.csv (every iteration); without it, the sampled iterations.
    """

    kind: Literal["aco_trace"] = "aco_trace"
    run_id: str
    algorithm: str
    topology: MetroTopology
    k: int = Field(ge=2)
    n_iterations: int = Field(ge=1, description="iterations of the whole run")
    best_s: float = Field(description="objective of the final best line")
    baseline_s: float = Field(description="objective without metro")
    stations: list[BuildingId] = Field(description="the final best line, in line order")
    candidate_ids: list[BuildingId]
    candidate_tops: list[Vec3] = Field(description="shaft tops (main entrances), web")
    candidate_platforms: list[Vec3]
    REQUIRED = (
        "iterations",
        "tours",
        "tour_cost_s",
        "best_tour",
        "pheromone",
        "curve_iteration",
        "curve_best_s",
        "curve_iter_best_s",
        "curve_iter_mean_s",
    )


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
    "building_info": BuildingInfo,
    "context_features": ContextFeatures,
    "network_header": NetworkHeader,
    "issues": IssueList,
    "status": BuildStatus,
    "replay": Replay,
    "replays": ReplayCatalog,
    "metro": Metro,
    "stats": Stats,
    "paths_header": PathsHeader,
    "day_header": DayHeader,
    "aco_trace_header": AcoTraceHeader,
}

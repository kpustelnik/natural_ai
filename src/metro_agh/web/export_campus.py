"""Campus part of the web export: everything the viewer needs before any simulation exists.

Inputs:  data/campus/** (buildings YAML, campus.yaml), data/processed/osm/campus.gpkg,
         data/processed/osm/issues.json
Outputs (web/public/data/, docs/data_contracts.md section 10):
    scene.json                    Scene, the entry point
    buildings/<id>.glb|.json      one per building YAML (glb + BuildingInfo)
    campus/context.glb|.json      every other OSM building, merged (ContextFeatures)
    campus/ground.glb             ground, paths, campus boundary, fences
    campus/aerial.jpg             orthophoto underlay (optional)
    network.json|.bin             the walk graph: outdoor, indoor, passages (NetworkHeader)
    issues.json                   IssueList: OSM stage + export checks
    replays/index.json            ReplayCatalog of replays/*/replay.json
    status.json                   BuildStatus, written last

``CampusExport`` keeps what it loaded, so the watcher (``watch.py``) can rebuild a single
building after a save: ``full()`` once, then ``update(paths)``.
"""

import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pydantic
import shapely
import yaml
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from ..campus.geo import to_metric
from ..config import ROOT, path, provenance
from ..geometry.building import (
    PlacedBuilding,
    largest_polygon,
    lod1_meshes,
    match_osm,
    osm_index,
    place,
)
from ..geometry.interior import interior_meshes, plan_levels, shaft_lines, space_size
from ..geometry.mesh import Lines, Origin, TriMesh, flat, outline, polygons, polyline, prism, web
from ..network.graph import (
    Graph,
    assemble,
    edge_class,
    outdoor_part,
    passage_ats,
    passage_part,
    stop_part,
)
from ..network.indoor import GraphIssue, Part, TimeModel, building_part
from ..schemas.campus import Campus
from ..schemas.common import NodeKind
from ..schemas.tables import (
    FIELD_MEASUREMENTS,
    OSM_BARRIERS,
    OSM_BOUNDARY,
    OSM_BUILDINGS,
    OSM_FENCES,
    OSM_STOPS,
    OSM_WALK_EDGES,
    OSM_WALK_NODES,
)
from ..schemas.web import (
    NETWORK_EDGE_KINDS,
    BuildError,
    BuildingFrame,
    BuildingInfo,
    BuildStatus,
    ContextFeature,
    ContextFeatures,
    Extent,
    FieldMeasurement,
    InfoEntrance,
    InfoLevel,
    InfoSpace,
    Issue,
    IssueList,
    NetworkBarrier,
    NetworkHeader,
    Replay,
    ReplayCatalog,
    Scene,
    SceneAerial,
    SceneBuilding,
    SceneContext,
    SceneEntrance,
    SceneLevel,
    SceneStop,
    WebFrame,
)
from . import aerial
from .binary import write_binary
from .gltf import Node, write_glb
from .yaml_errors import load_with_errors

log = logging.getLogger(__name__)

GENERATOR = "06_export_web.py"
HAUSDORFF_WARN_M = 1.0
PATH_STYLE = {  # class -> (ribbon width m, web y)
    "road": (5.0, 0.03),
    "footway": (2.0, 0.06),
    "steps": (2.2, 0.09),
}
LINE_Y = 0.12  # boundary and fence lines
AERIAL_Y = 0.015  # between the ground (0) and the roads (0.03)
SPACE_MATERIAL = {"corridor": "mat:corridor", "room": "mat:room", "stairs": "mat:stairs"}


def _vec3(a) -> tuple[float, float, float]:
    return (round(float(a[0]), 3), round(float(a[1]), 3), round(float(a[2]), 3))


def _vec2(a) -> tuple[float, float]:
    return (round(float(a[0]), 2), round(float(a[1]), 2))


def _ring_local(coords) -> list[tuple[float, float]]:
    return [_vec2(c) for c in np.asarray(coords)[:-1]]


def _repo_rel(p: Path) -> str:
    p = Path(p).resolve()
    return p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix()


def _bbox(meshes: list[TriMesh]) -> tuple[tuple, tuple]:
    pos = np.concatenate([m.positions for m in meshes if m.n_vertices])
    return _vec3(pos.min(axis=0)), _vec3(pos.max(axis=0))


class CampusExport:
    """The campus export with its inputs kept in memory between runs."""

    def __init__(self, cfg: dict, campus_dir: Path | None = None, out_dir: Path | None = None):
        self.cfg = cfg
        self.campus_dir = Path(campus_dir or path(cfg, "campus"))
        self.out_dir = Path(out_dir or path(cfg, "web_data"))
        self.osm_dir = path(cfg, "processed") / "osm"
        o = cfg["campus"]["web_origin"]
        ox, oy = to_metric(o["lon"], o["lat"])
        self.origin: Origin = (float(ox), float(oy))
        self.origin_z = float(o["z"])
        self.download_aerial = False

        self.changed: list[str] = []
        self.osm_issues: list[Issue] = []
        self.buildings: dict[str, SceneBuilding] = {}  # id -> scene entry (YAML order)
        self.building_issues: dict[str, list[Issue]] = {}  # export checks per building
        self.covered: dict[str, int | None] = {}  # id -> OSM row it replaces
        self.errors: dict[str, list[BuildError]] = {}  # YAML (repo-relative) -> errors
        self.previous: dict[str, SceneBuilding] = {}  # last scene.json, for stale entries
        self.context: SceneContext | None = None
        self.ground: str | None = None
        self.network: str | None = None
        self.stops: list[SceneStop] = []
        self.other_stops: list[SceneStop] = []
        self.extent: Polygon | None = None
        self.aerial: SceneAerial | None = None
        # walk graph: the OSM part and one part per building, joined on every export
        self.tm = TimeModel.from_config(cfg)
        self.campus: Campus | None = None
        self.outdoor = None
        self.placed: dict[str, PlacedBuilding] = {}
        self.indoor: dict[str, Part] = {}  # id -> graph of the last good build
        self.graph: Graph | None = None

    # --- small helpers ---

    def rel(self, p: Path) -> str:
        return p.relative_to(self.out_dir).as_posix()

    def write_json(self, rel: str, model: pydantic.BaseModel) -> None:
        p = self.out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(model.model_dump_json(), encoding="utf-8")
        self.changed.append(rel)

    def write_glb(self, rel: str, roots: list[Node]) -> None:
        write_glb(self.out_dir / rel, roots)
        self.changed.append(rel)

    # --- runs ---

    def full(self) -> BuildStatus:
        """Everything: OSM layers, all buildings, context, ground, network, stops."""
        t0 = time.perf_counter()
        self.changed = []
        gpkg = self.osm_dir / "campus.gpkg"
        if not gpkg.exists():
            raise FileNotFoundError(f"{gpkg} missing: run scripts/02_build_campus.py first")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._read_previous_scene()

        self.osm_buildings = OSM_BUILDINGS.read(gpkg)
        self.osm_index = osm_index(self.osm_buildings)
        self.osm_issues = load_osm_issues(self, self.osm_dir, self.osm_buildings)
        self.campus = Campus.model_validate(
            yaml.safe_load((self.campus_dir / "campus.yaml").read_text(encoding="utf-8"))
        )

        self.buildings, self.building_issues, self.covered, self.errors = {}, {}, {}, {}
        self.placed, self.indoor = {}, {}
        files = sorted((self.campus_dir / "buildings").glob("*.yaml"))
        for f in files:
            self._building(f)
        self._prune({f.stem for f in files})

        self.context = export_context(self, self.osm_buildings, self._covered_rows())
        self.extent = extent_polygon(self.cfg)
        edges = OSM_WALK_EDGES.read(gpkg)
        self.ground = export_ground(
            self, self.extent, edges, OSM_BOUNDARY.read(gpkg), OSM_FENCES.read(gpkg)
        )
        self.outdoor = outdoor_part(
            OSM_WALK_NODES.read(gpkg), edges, self.campus, self.cfg, self.tm
        )
        self.barriers = OSM_BARRIERS.read(gpkg)
        self.network = self._network()
        self.stops, self.other_stops = export_stops(self, self.campus, OSM_STOPS.read(gpkg))
        self.aerial = export_aerial(self, self.extent)
        return self._finish(t0)

    def update(self, paths: list[Path]) -> BuildStatus:
        """Rebuild the given building YAMLs (also new or deleted ones)."""
        t0 = time.perf_counter()
        self.changed = []
        before = self._covered_rows()
        for f in paths:
            f = Path(f)
            if f.exists():
                self._building(f)
            else:
                bid = f.stem
                self.buildings.pop(bid, None)
                self.building_issues.pop(bid, None)
                self.covered.pop(bid, None)
                self.placed.pop(bid, None)
                self.indoor.pop(bid, None)
                self.errors.pop(_repo_rel(f), None)
                self._prune({p.stem for p in (self.campus_dir / "buildings").glob("*.yaml")})
        if self._covered_rows() != before:  # a building took over (or released) an OSM outline
            self.context = export_context(self, self.osm_buildings, self._covered_rows())
        self.network = self._network()
        return self._finish(t0)

    # --- parts ---

    def _network(self) -> str:
        """Join the walk graph (outdoor + every building's last good part) and export it."""
        parts = [
            *self.indoor.values(),
            passage_part(self.campus, self.placed, self.tm, self.origin_z),
            stop_part(self.campus, self.outdoor.z),
        ]
        self.graph = assemble(self.outdoor, parts, self.cfg, self.tm)
        return export_network(self, self.graph, self.barriers)

    def _covered_rows(self) -> set[int]:
        return {r for r in self.covered.values() if r is not None}

    def _read_previous_scene(self) -> None:
        f = self.out_dir / "scene.json"
        self.previous = {}
        if f.exists():
            try:
                old = Scene.model_validate_json(f.read_text(encoding="utf-8"))
                self.previous = {b.id: b for b in old.buildings}
            except (pydantic.ValidationError, ValueError):
                pass

    def _building(self, src: Path) -> None:
        bid, rel = src.stem, _repo_rel(src)
        b, errors = load_with_errors(src, rel)
        place_error = None
        placed = osm_geom = row = None
        if b is not None:
            row, osm_geom = match_osm(b, self.osm_buildings, self.osm_index)
            outline_geom = largest_polygon(osm_geom)
            try:
                placed = place(b, self.cfg, self.origin_z, outline_geom)
            except ValueError as err:
                place_error = BuildError(file=rel, message=str(err), building_id=bid)
        if placed is None:
            self.errors[rel] = errors or [place_error]
            # keep showing the last good build of this building
            last = self.buildings.get(bid) or self.previous.get(bid)
            if last is not None and (self.out_dir / last.glb).exists():
                self.buildings[bid] = last.model_copy(update={"stale": True})
            return
        self.errors.pop(rel, None)
        self.covered[bid] = row
        category = "connector" if bid.startswith("P-") else b.kind
        entry, issues = _building_files(self, src, placed, osm_geom, category)
        self.buildings[bid] = entry
        self.building_issues[bid] = issues
        self.placed[bid] = placed
        ats = passage_ats(self.campus).get(bid) if self.campus else None
        self.indoor[bid] = building_part(placed, self.cfg, self.tm, self.origin_z, ats)

    def _graph_issue(self, i: GraphIssue) -> Issue:
        pos = None
        if i.position is not None:
            x, y, z = i.position
            pos = _vec3(web([x], [y], z - self.origin_z, self.origin)[0])
        known = i.building_id if i.building_id in self.buildings else None
        return Issue(section=i.section, message=i.message, building_id=known, position=pos)

    def _prune(self, stems: set[str]) -> None:
        """Drop files of buildings whose YAML is gone (files of failing YAMLs are kept)."""
        for f in (self.out_dir / "buildings").glob("*.*"):
            if f.stem not in stems:
                f.unlink()
                self.changed.append(self.rel(f))

    def _finish(self, t0: float) -> BuildStatus:
        errors = [e for errs in self.errors.values() for e in errs]
        error_issues = [
            Issue(
                severity="error",
                section="Building files that fail validation",
                message=f"{e.file}{f':{e.line}' if e.line else ''}: {e.message}",
                building_id=e.building_id if e.building_id in self.buildings else None,
            )
            for e in errors
        ]
        issues = [
            *self.osm_issues,
            *(i for b in self.buildings for i in self.building_issues.get(b, [])),
            *error_issues,
            *(self._graph_issue(i) for i in (self.graph.issues if self.graph else [])),
        ]
        counts: dict[str, int] = {}
        for i in issues:
            if i.building_id:
                counts[i.building_id] = counts.get(i.building_id, 0) + 1
        buildings = [
            b.model_copy(update={"n_issues": counts.get(b.id, 0)}) for b in self.buildings.values()
        ]
        self.write_json(
            "issues.json", IssueList(provenance=provenance(GENERATOR, self.cfg), issues=issues)
        )
        replays = export_replays(self)

        o = self.cfg["campus"]["web_origin"]
        ext = web(*np.asarray(self.extent.exterior.coords).T, 0.0, self.origin)
        top = max((b.bbox_max[1] for b in buildings), default=0.0)
        scene = Scene(
            provenance=provenance(GENERATOR, self.cfg),
            frame=WebFrame(
                origin_lonlat=(o["lon"], o["lat"]),
                origin_x=self.origin[0],
                origin_y=self.origin[1],
                origin_z=self.origin_z,
            ),
            extent=Extent(
                min=_vec3([ext[:, 0].min(), 0.0, ext[:, 2].min()]),
                max=_vec3([ext[:, 0].max(), top, ext[:, 2].max()]),
            ),
            source_root=ROOT.as_posix(),
            buildings=buildings,
            stops=self.stops,
            other_stops=self.other_stops,
            ground_glb=self.ground,
            context=self.context,
            network=self.network,
            issues="issues.json",
            replays=replays,
            aerial=self.aerial,
        )
        self.write_json("scene.json", scene)
        status = write_status(self, errors)
        log.info(
            "web export: %d buildings, %d issues, %d errors, %d files in %.2f s",
            len(buildings), len(issues), len(errors), len(self.changed), time.perf_counter() - t0,
        )  # fmt: skip
        return status


# --- buildings -----------------------------------------------------------------------


def _level_nodes(ex: CampusExport, placed: PlacedBuilding, slabs: dict, plans, interiors):
    nodes = []
    for lv in placed.levels:
        children = [Node("slab", slabs[lv.id], "mat:slab", extras={"part": "slab", "level": lv.id})]
        im = interiors.get(lv.id)
        if im is not None:
            plan = next(p for p in plans if p.span.id == lv.id)
            children.append(
                Node("walls", im.walls, "mat:iwall", extras={"part": "walls", "level": lv.id})
            )
            for s in plan.spaces:
                children.append(
                    Node(
                        f"space:{s.id}",
                        im.spaces[s.id],
                        SPACE_MATERIAL[s.kind],
                        extras={
                            "part": "space",
                            "kind": s.kind,
                            "id": s.id,
                            "level": lv.id,
                            **({"capacity": s.capacity} if s.capacity is not None else {}),
                        },
                    )
                )
            for sid, mesh in im.stairs.items():
                children.append(
                    Node(
                        f"flight:{sid}",
                        mesh,
                        "mat:flight",
                        extras={"part": "flight", "kind": "stairs", "id": sid, "level": lv.id},
                    )
                )
        nodes.append(Node(f"L{lv.id}", extras={"level": lv.id}, children=children))
    return nodes


def _info_levels(placed: PlacedBuilding, plans, interiors, origin: Origin) -> list[InfoLevel]:
    out = []
    for lv in placed.levels:
        spaces = []
        plan = next((p for p in plans if p.span.id == lv.id), None)
        for s in plan.spaces if plan else []:
            mesh = interiors[lv.id].spaces[s.id]
            if mesh.n_vertices:
                lo, hi = _bbox([mesh])
                hi = (hi[0], round(hi[1] + lv.height, 3), hi[2])
            else:
                lo = hi = _vec3(web(*np.asarray(placed.frame.anchor)[:, None], 0, origin)[0])
            spaces.append(
                InfoSpace(
                    id=s.id,
                    kind=s.kind,
                    polygon=_ring_local(s.polygon.exterior.coords),
                    centre=_vec2(np.asarray(s.polygon.representative_point().coords[0])),
                    size=_vec2(space_size(s.polygon)),
                    area_m2=round(s.polygon.area, 1),
                    doors=[_vec2(d) for d in s.doors],
                    name=s.name,
                    capacity=s.capacity,
                    bbox_min=lo,
                    bbox_max=hi,
                )
            )
        out.append(
            InfoLevel(
                id=lv.id,
                elevation=lv.elevation,
                height=lv.height,
                floor_y=round(placed.ground_y + lv.elevation, 3),
                spaces=spaces,
            )
        )
    return out


def _building_files(
    ex: CampusExport, src: Path, placed: PlacedBuilding, osm_geom, category: str
) -> tuple[SceneBuilding, list[Issue]]:
    b = placed.building
    origin = ex.origin
    meshes = lod1_meshes(placed, origin)
    plans = plan_levels(placed)
    interiors = interior_meshes(placed, plans, origin)
    slabs = {lv: (interiors[lv].slab if lv in interiors else m) for lv, m in meshes.slabs.items()}

    entrance_nodes = []
    for e in placed.entrances:
        pos = web([e.metric[0]], [e.metric[1]], placed.ground_y, origin)[0]
        entrance_nodes.append(
            Node(
                f"entrance:{e.id}",
                translation=_vec3(pos),
                extras={
                    "kind": "entrance",
                    "id": e.id,
                    "main": e.main,
                    "metro_shaft": e.metro_shaft,
                },
            )
        )
    shaft = shaft_lines(placed, float(ex.cfg["metro"]["station_depth_m"]), origin)
    shaft_nodes = [Node("shaft", shaft, "mat:shaft", extras={"part": "shaft"})]
    root = Node(
        b.id,
        extras={"building": b.id, "lod": b.lod},
        children=[
            Node("shell", meshes.shell, "mat:wall", extras={"part": "shell"}),
            Node("roof", meshes.roof, "mat:roof", extras={"part": "roof"}),
            Node("edges", meshes.edges, "mat:edge", extras={"part": "edges"}),
            *_level_nodes(ex, placed, slabs, plans, interiors),
            *(shaft_nodes if len(shaft.positions) else []),
            *entrance_nodes,
        ],
    )
    glb_rel = f"buildings/{b.id}.glb"
    ex.write_glb(glb_rel, [root])

    anchor = web([placed.frame.anchor[0]], [placed.frame.anchor[1]], placed.ground_y, origin)[0]
    frame = BuildingFrame(anchor=_vec3(anchor), bearing_deg=b.placement.bearing_deg)
    levels = _info_levels(placed, plans, interiors, origin)
    entrances = [
        InfoEntrance(
            id=e.id,
            local=_vec2(e.local),
            position=_vec3(web([e.metric[0]], [e.metric[1]], placed.ground_y, origin)[0]),
            main=e.main,
            metro_shaft=e.metro_shaft,
            osm_node=e.osm_node,
        )
        for e in placed.entrances
    ]

    # checks shown in the inspector and the issues panel
    issues: list[Issue] = []
    centre = web(
        [placed.footprint.centroid.x], [placed.footprint.centroid.y], placed.top_y, origin
    )[0]
    osm_rings: list[list[tuple[float, float]]] = []
    hausdorff = None
    if osm_geom is not None:
        for poly in polygons(osm_geom):
            for ring in [poly.exterior, *poly.interiors]:
                osm_rings.append(_ring_local(placed.frame.to_local(np.asarray(ring.coords))))
        hausdorff = round(float(placed.footprint.hausdorff_distance(osm_geom)), 2)
        if hausdorff > HAUSDORFF_WARN_M:
            issues.append(
                Issue(
                    section="Footprint differs from the OSM outline",
                    message=f"{b.id}: {hausdorff:.1f} m",
                    building_id=b.id,
                    position=_vec3(centre),
                )
            )
    elif b.osm_id:
        issues.append(
            Issue(
                severity="info",
                section="osm_id not found in campus.gpkg",
                message=f"{b.id}: {b.osm_id}",
                building_id=b.id,
                position=_vec3(centre),
            )
        )
    if not placed.entrances:
        issues.append(
            Issue(
                section="Buildings without entrances in the YAML",
                message=b.id,
                building_id=b.id,
                position=_vec3(centre),
            )
        )
    inherited = [i for i in ex.osm_issues if i.building_id == b.id]  # from the OSM stage
    for i in inherited:
        if i.position is None:
            i.position = _vec3(centre)

    info = BuildingInfo(
        provenance=provenance(GENERATOR, ex.cfg),
        id=b.id,
        lod=b.lod,
        frame=frame,
        footprint=_ring_local(placed.footprint_local.exterior.coords),
        footprint_holes=[_ring_local(r.coords) for r in placed.footprint_local.interiors],
        area_m2=round(placed.footprint.area, 1),
        height_m=round(placed.height_m, 2),
        levels=levels,
        entrances=entrances,
        osm_outline=osm_rings,
        osm_hausdorff_m=hausdorff,
        issues=inherited + issues,
    )
    info_rel = f"buildings/{b.id}.json"
    ex.write_json(info_rel, info)

    lo, hi = _bbox([meshes.shell, meshes.roof])
    entry = SceneBuilding(
        id=b.id,
        name=b.name,
        kind=b.kind,
        category=category,
        lod=b.lod,
        glb=glb_rel,
        info=info_rel,
        yaml=_repo_rel(src),
        osm_id=b.osm_id,
        height_m=round(placed.height_m, 2),
        frame=frame,
        levels=[SceneLevel(id=lv.id, floor_y=lv.floor_y, height=lv.height) for lv in levels],
        entrances=[
            SceneEntrance(id=e.id, position=e.position, main=e.main, metro_shaft=e.metro_shaft)
            for e in entrances
        ],
        bbox_min=lo,
        bbox_max=hi,
        rooms=[s.id for lv in levels for s in lv.spaces if s.kind == "room"],
    )
    return entry, issues


# --- context buildings ---------------------------------------------------------------


def export_context(
    ex: CampusExport, osm_buildings: gpd.GeoDataFrame, covered: set[int]
) -> SceneContext:
    meshes: list[TriMesh] = []
    edges: list[Lines] = []
    ids: list[np.ndarray] = []
    features: list[ContextFeature] = []
    n_index = n_vertex = 0
    for pos, row in enumerate(osm_buildings.itertuples()):
        if pos in covered:
            continue
        m = prism(row.geometry, 0.0, float(row.height_m), ex.origin)
        if not m.n_vertices:
            continue
        fid = len(features)
        meshes.append(TriMesh(m.positions, m.normals, m.indices + n_vertex))
        ids.append(np.full(m.n_vertices, fid, np.float32))
        edges.append(outline(row.geometry, [0.0, float(row.height_m)], ex.origin))
        features.append(
            ContextFeature(
                osm_id=row.osm_id,
                name=row.name if isinstance(row.name, str) else None,
                building=row.building,
                height_m=round(float(row.height_m), 2),
                height_source=row.height_source,
                index_start=n_index,
                index_count=len(m.indices),
            )
        )
        n_index += len(m.indices)
        n_vertex += m.n_vertices
    merged = TriMesh(
        np.concatenate([m.positions for m in meshes]),
        np.concatenate([m.normals for m in meshes]),
        np.concatenate([m.indices for m in meshes]).astype(np.uint32),
    )
    ex.write_glb(
        "campus/context.glb",
        [
            Node(
                "context",
                extras={"part": "context"},
                children=[
                    Node(
                        "buildings",
                        merged,
                        "mat:context",
                        extras={"part": "context"},
                        attributes={"_FEATURE_ID": np.concatenate(ids)},
                    ),
                    Node("edges", Lines.concat(edges), "mat:edge", extras={"part": "edges"}),
                ],
            )
        ],
    )
    ex.write_json(
        "campus/context.json",
        ContextFeatures(provenance=provenance(GENERATOR, ex.cfg), features=features),
    )
    log.info("context: %d buildings, %d triangles", len(features), merged.n_triangles)
    return SceneContext(glb="campus/context.glb", features="campus/context.json")


# --- ground --------------------------------------------------------------------------


def extent_polygon(cfg: dict) -> Polygon:
    """The bbox in EPSG:2180 (not axis-aligned there, so densified before projecting)."""
    b = cfg["campus"]["bbox"]
    ring = np.asarray(
        box(b["west"], b["south"], b["east"], b["north"]).segmentize(0.0005).exterior.coords
    )
    x, y = to_metric(ring[:, 0], ring[:, 1])
    return Polygon(np.column_stack([x, y]))


def export_ground(
    ex: CampusExport,
    extent: Polygon,
    edges: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    fences: gpd.GeoDataFrame,
) -> str:
    children = [
        Node("ground", flat(extent, 0.0, ex.origin), "mat:ground", extras={"layer": "ground"})
    ]

    classes = [edge_class(h, s) for h, s in zip(edges.highway, edges.is_steps, strict=True)]
    for cls, (width, y) in PATH_STYLE.items():
        lines = edges.geometry[[c == cls for c in classes]]
        if lines.empty:
            continue
        ribbons = shapely.buffer(
            lines.to_numpy(), width / 2, cap_style="flat", join_style="round", quad_segs=2
        )
        area = shapely.union_all(ribbons).intersection(extent).simplify(0.05)
        mesh = flat(area, y, ex.origin)
        children.append(Node(f"paths:{cls}", mesh, f"mat:{cls}", extras={"layer": f"paths:{cls}"}))

    for row in boundary.itertuples():
        if row.kind == "bbox":
            continue
        rings = [Lines()]
        for poly in polygons(row.geometry):
            rings.append(polyline(LineString(poly.exterior.coords), LINE_Y, ex.origin))
        children.append(
            Node(
                f"boundary:{row.kind}",
                Lines.concat(rings),
                "mat:boundary",
                extras={"layer": "boundary", "kind": row.kind, "name": row.name},
            )
        )

    fence_lines = []
    for geom in fences.geometry:
        if isinstance(geom, Polygon | MultiPolygon):
            parts = [LineString(p.exterior.coords) for p in polygons(geom)]
        else:
            parts = list(getattr(geom, "geoms", [geom]))
        fence_lines += [polyline(p, LINE_Y, ex.origin) for p in parts]
    children.append(
        Node("fences", Lines.concat(fence_lines), "mat:fence", extras={"layer": "fences"})
    )

    ex.write_glb(
        "campus/ground.glb", [Node("ground", extras={"part": "ground"}, children=children)]
    )
    return "campus/ground.glb"


# --- network -------------------------------------------------------------------------


def export_network(ex: CampusExport, graph: Graph, barriers: gpd.GeoDataFrame) -> str:
    """network.json + .bin: the whole walk graph, with times per direction for routing."""
    nodes, edges = graph.nodes, graph.edges
    xyz = web(nodes.x.to_numpy(), nodes.y.to_numpy(), nodes.z.to_numpy() - ex.origin_z, ex.origin)
    node_kinds = [k.value for k in NodeKind]
    pairs = edges[["u", "v"]].to_numpy(np.uint32).reshape(-1, 2)

    # every edge's polyline as segments (straight edges: node to node), converted at once
    node_xyz = nodes[["x", "y", "z"]].to_numpy()
    starts, ends, seg_edge = [], [], []
    for i, geom in enumerate(graph.edge_geometry):
        geom = node_xyz[pairs[i]] if geom is None else geom
        starts.append(geom[:-1])
        ends.append(geom[1:])
        seg_edge.append(np.full(len(geom) - 1, i, np.uint32))
    a, b = np.concatenate(starts), np.concatenate(ends)
    segs = np.stack(
        [
            web(a[:, 0], a[:, 1], a[:, 2] - ex.origin_z, ex.origin),
            web(b[:, 0], b[:, 1], b[:, 2] - ex.origin_z, ex.origin),
        ],
        axis=1,
    )

    endpoints = {
        str(k): int(i)
        for k, i in zip(nodes.endpoint_key, nodes.node_id, strict=True)
        if isinstance(k, str)
    }
    write_binary(
        ex.out_dir / "network.json",
        NetworkHeader,
        {
            "node_xyz": xyz.astype(np.float32),
            "node_kind": np.array([node_kinds.index(k) for k in nodes.kind], np.uint8),
            "edge_nodes": pairs,
            "edge_kind": np.array(
                [NETWORK_EDGE_KINDS.index(c) for c in graph.edge_class], np.uint8
            ),
            "length_m": edges.length_m.to_numpy(np.float32),
            "time_uv_s": edges.time_uv_s.to_numpy(np.float32),
            "time_vu_s": edges.time_vu_s.to_numpy(np.float32),
            "segment_xyz": segs.astype(np.float32),
            "segment_edge": np.concatenate(seg_edge).astype(np.uint32),
        },
        provenance=provenance(GENERATOR, ex.cfg),
        n_nodes=len(nodes),
        n_edges=len(edges),
        node_kind_names=node_kinds,
        edge_kind_names=list(NETWORK_EDGE_KINDS),
        node_keys=nodes.key.tolist(),
        endpoints=endpoints,
        edge_sources=[s if isinstance(s, str) else None for s in edges.source],
        barriers=[
            NetworkBarrier(
                osm_id=r.osm_id,
                barrier=r.barrier,
                access=r.access if isinstance(r.access, str) else None,
                position=_vec3(web([r.geometry.x], [r.geometry.y], 0.0, ex.origin)[0]),
            )
            for r in barriers.itertuples()
        ],
        measurements=load_measurements(),
    )
    ex.changed += ["network.json", "network.bin"]
    return "network.json"


def load_measurements() -> list[FieldMeasurement]:
    """Walking times measured on campus (data/validation), for the route tool."""
    f = ROOT / FIELD_MEASUREMENTS.path
    if not f.exists():
        return []
    df = FIELD_MEASUREMENTS.read(f)
    return [
        FieldMeasurement(
            route_id=r.route_id,
            from_key=r.from_key,
            to_key=r.to_key,
            measured_s=float(r.measured_s),
            date=r.date,
            who=r.who,
            notes=r.notes if isinstance(r.notes, str) else None,
        )
        for r in df.itertuples()
    ]


# --- stops, issues, replays ----------------------------------------------------------


def export_stops(ex: CampusExport, campus: Campus, osm_stops: gpd.GeoDataFrame):
    def stop(sid, name, x, y):
        return SceneStop(id=sid, name=name, position=_vec3(web([x], [y], 0.0, ex.origin)[0]))

    used = []
    for s in campus.stops:
        x, y = to_metric(*s.location)
        used.append(stop(s.id, s.name, x, y))
    ids = {s.id for s in campus.stops}
    other = [
        stop(r.stop_id, r.name, r.geometry.x, r.geometry.y)
        for r in osm_stops.itertuples()
        if r.stop_id not in ids
    ]
    return used, other


# --- replays, aerial, status --------------------------------------------------------


def export_replays(ex: CampusExport) -> str:
    rel = write_replay_catalog(ex.out_dir, ex.cfg)
    ex.changed.append(rel)
    return rel


def write_replay_catalog(out_dir: Path, cfg: dict) -> str:
    """replays/index.json from every replays/*/replay.json, newest first."""
    replays = []
    for f in sorted((out_dir / "replays").glob("*/replay.json")):
        try:
            replays.append(Replay.model_validate_json(f.read_text(encoding="utf-8")))
        except pydantic.ValidationError as err:
            log.error("%s: %s", _repo_rel(f), err)
    # newest first, synthetic runs (06_export_web.py --fake) after every real one
    replays.sort(key=lambda r: r.created_at, reverse=True)
    replays.sort(key=lambda r: (r.run_id or "").startswith("fake-"))
    catalog = ReplayCatalog(provenance=provenance(GENERATOR, cfg), replays=replays)
    (out_dir / "replays").mkdir(parents=True, exist_ok=True)
    (out_dir / "replays/index.json").write_text(catalog.model_dump_json(), encoding="utf-8")
    return "replays/index.json"


def export_aerial(ex: CampusExport, extent: Polygon) -> SceneAerial | None:
    minx, miny, maxx, maxy = extent.bounds
    if not aerial.aerial_image(
        ex.cfg, (minx, miny, maxx, maxy), ex.out_dir / "campus/aerial.jpg", ex.download_aerial
    ):
        return None
    ex.changed.append("campus/aerial.jpg")
    lo = web([minx], [maxy], AERIAL_Y, ex.origin)[0]  # smallest x and z (z = -north)
    hi = web([maxx], [miny], AERIAL_Y, ex.origin)[0]
    return SceneAerial(
        image="campus/aerial.jpg", min=_vec3(lo), max=_vec3(hi), attribution=aerial.ATTRIBUTION
    )


def load_osm_issues(ex: CampusExport, osm_dir: Path, osm_buildings: gpd.GeoDataFrame) -> list:
    f = osm_dir / "issues.json"
    if not f.exists():
        log.warning("%s missing: rerun 02_build_campus.py to get OSM issues in the viewer", f)
        return []
    index = osm_index(osm_buildings)
    out = []
    for issue in IssueList.model_validate_json(f.read_text(encoding="utf-8")).issues:
        if issue.osm_id in index and issue.position is None:
            geom = osm_buildings.geometry.iloc[index[issue.osm_id]]
            c = geom.centroid
            h = float(osm_buildings.height_m.iloc[index[issue.osm_id]])
            issue.position = _vec3(web([c.x], [c.y], h, ex.origin)[0])
        out.append(issue)
    return out


def write_status(ex: CampusExport, errors: list[BuildError]) -> BuildStatus:
    return write_status_file(ex.out_dir, ex.changed, errors)


def write_status_file(
    out_dir: Path, changed: list[str], errors: list[BuildError] | None = None
) -> BuildStatus:
    """status.json, written last by every export. ``errors=None`` keeps the previous
    ones (an export that does not read building files cannot fix or break them)."""
    f = out_dir / "status.json"
    version = 0
    previous: list[BuildError] = []
    if f.exists():
        try:
            old = BuildStatus.model_validate_json(f.read_text(encoding="utf-8"))
            version, previous = old.version + 1, old.errors
        except (pydantic.ValidationError, ValueError):
            version = 0
    status = BuildStatus(
        version=version,
        built_at=provenance(GENERATOR).generated_at,
        changed=sorted(set(changed)),
        errors=previous if errors is None else errors,
    )
    f.write_text(status.model_dump_json(), encoding="utf-8")
    return status


# --- entry point ---------------------------------------------------------------------


def export_campus(
    cfg: dict,
    campus_dir: Path | None = None,
    out_dir: Path | None = None,
    download_aerial: bool = False,
) -> BuildStatus:
    ex = CampusExport(cfg, campus_dir, out_dir)
    ex.download_aerial = download_aerial
    return ex.full()

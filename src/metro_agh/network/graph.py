"""Stage 2b: one walk graph for everything (docs/data_contracts.md, section 6.4).

    outdoor   OSM walk network (campus.gpkg) minus ``removed_ways``, plus ``extra_paths``
    indoor    every building YAML (``indoor.py``): corridors, rooms, stairs, entrances, shafts
    passages  building-to-building links from campus.yaml
    stops     the stops of campus.yaml
    links     entrances, stops and entrance-less buildings -> nearest outdoor node

Written by ``02_build_campus.py`` to ``network/nodes.parquet`` + ``edges.parquet``. The web
export builds the same graph in memory (``Graph``), so the viewer also follows live edits of
the building YAMLs. Train rides are not edges: the objective adds them analytically.
"""

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely.geometry import LineString

from ..campus.geo import to_metric
from ..geometry.building import PlacedBuilding, point_along
from ..schemas.campus import Campus
from ..schemas.tables import GRAPH_EDGES, GRAPH_NODES
from .indoor import GEdge, GNode, GraphIssue, Part, TimeModel, corridor_key

log = logging.getLogger(__name__)

FOOTWAY = {"footway", "path", "pedestrian", "steps", "corridor", "track", "bridleway", "cycleway"}


def edge_class(highway: str, is_steps: bool) -> str:
    """Drawing class of an OSM edge: steps, footway or road."""
    if is_steps:
        return "steps"
    return "footway" if set(highway.split("|")) & FOOTWAY else "road"


@dataclass
class Outdoor:
    """The OSM part, kept between rebuilds (it changes only with campus.gpkg / campus.yaml)."""

    nodes: list[GNode]
    edges: list[GEdge]
    issues: list[GraphIssue]
    tree: cKDTree  # over the nodes of the largest connected component
    tree_keys: list[str]
    z: float

    def nearest(self, x: float, y: float) -> tuple[str, float]:
        d, i = self.tree.query([x, y])
        return self.tree_keys[int(i)], float(d)


@dataclass
class Graph:
    nodes: pd.DataFrame  # tables.GRAPH_NODES
    edges: pd.DataFrame  # tables.GRAPH_EDGES
    edge_class: list[str]  # per edge: footway / road / steps or the edge kind
    edge_geometry: list[np.ndarray | None]  # per edge (k, 3) EPSG:2180 + height, None = straight
    issues: list[GraphIssue]

    def write(self, out_dir: Path) -> None:
        GRAPH_NODES.write(self.nodes, Path(out_dir) / "nodes.parquet")
        GRAPH_EDGES.write(self.edges, Path(out_dir) / "edges.parquet")


def _main_component(n: int, pairs: np.ndarray) -> np.ndarray:
    """Boolean mask of the nodes in the largest connected component."""
    if n == 0:
        return np.zeros(0, bool)
    m = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    _, labels = connected_components(m, directed=False)
    return labels == np.bincount(labels).argmax()


def outdoor_part(
    walk_nodes: gpd.GeoDataFrame,
    walk_edges: gpd.GeoDataFrame,
    campus: Campus,
    cfg: dict,
    tm: TimeModel,
) -> Outdoor:
    z = float(cfg["campus"]["web_origin"]["z"])  # flat campus: the ground is at the origin height
    removed = {str(r.osm_way_id) for r in campus.removed_ways}
    nodes = [
        GNode(f"osm:{int(n)}", "osm", float(g.x), float(g.y), z)
        for n, g in zip(walk_nodes.osm_node, walk_nodes.geometry, strict=True)
    ]
    index = {n.key: i for i, n in enumerate(nodes)}
    edges = []
    for row in walk_edges.itertuples():
        ways = [w for w in str(row.osm_ways).split("|") if w]
        if removed & set(ways) or row.u == row.v:
            continue
        coords = np.asarray(row.geometry.coords)
        # osmnx's undirected edges keep the way's drawing direction, not u -> v: the export
        # (segments, the route tool, the students' paths) needs the geometry from u to v
        nu, nv = nodes[index[f"osm:{int(row.u)}"]], nodes[index[f"osm:{int(row.v)}"]]
        if math.dist(coords[0][:2], (nv.x, nv.y)) < math.dist(coords[0][:2], (nu.x, nu.y)):
            coords = coords[::-1]
        geom = np.column_stack([coords[:, :2], np.full(len(coords), z)])
        length = float(row.length_m)
        t = tm.walk(length) * (tm.steps_factor if row.is_steps else 1.0)
        edges.append(
            GEdge(
                f"osm:{int(row.u)}", f"osm:{int(row.v)}", "outdoor", length, t, t,
                "|".join(f"way/{w}" for w in ways) or None,
                edge_class(row.highway, bool(row.is_steps)), geom,
            )
        )  # fmt: skip

    pairs = np.array([[index[e.u], index[e.v]] for e in edges], int).reshape(-1, 2)
    main = _main_component(len(nodes), pairs)
    keep = np.flatnonzero(main)
    tree = cKDTree(np.array([[nodes[i].x, nodes[i].y] for i in keep]).reshape(-1, 2))
    out = Outdoor(nodes, edges, [], tree, [nodes[i].key for i in keep], z)

    warn = float(cfg.get("network", {}).get("link_warn_m", 40.0))
    for p in campus.extra_paths:
        x, y = to_metric(*np.asarray(p.path, float).T)
        (a, da), (b, db) = out.nearest(x[0], y[0]), out.nearest(x[-1], y[-1])
        na, nb = nodes[index[a]], nodes[index[b]]
        pts = np.column_stack([[na.x, *x, nb.x], [na.y, *y, nb.y], np.full(len(x) + 2, z)])
        length = float(LineString(pts[:, :2]).length)
        t = tm.walk(length)
        out.edges.append(GEdge(a, b, "outdoor", length, t, t, f"extra:{p.id}", "footway", pts))
        if max(da, db) > warn:
            out.issues.append(
                GraphIssue(
                    "Network: extra paths far from the walk network",
                    f"extra path {p.id}: an end is {max(da, db):.0f} m from the nearest path",
                    position=(float(x[0]), float(y[0]), z),
                )
            )
    return out


def passage_ats(campus: Campus) -> dict[str, dict[str, list[float]]]:
    """building -> corridor -> positions where passages attach."""
    out: dict[str, dict[str, list[float]]] = {}
    for p in campus.passages:
        for end in (p.a, p.b):
            out.setdefault(end.building, {}).setdefault(end.corridor, []).append(end.at)
    return out


def passage_part(
    campus: Campus, placed: dict[str, PlacedBuilding], tm: TimeModel, origin_z: float
) -> Part:
    part = Part()
    for p in campus.passages:
        ends = []
        for end in (p.a, p.b):
            pb = placed.get(end.building)
            corridor = pb.building.corridors().get(end.corridor) if pb else None
            if corridor is None:
                part.issues.append(
                    GraphIssue(
                        "Network: passages that cannot be connected",
                        f"passage {p.id}: no corridor {end.corridor} in {end.building}",
                        building_id=end.building if pb else None,
                    )
                )
                break
            level, c = corridor
            local, _ = point_along(c.path, end.at)
            m = pb.frame.to_metric(np.asarray([local]))[0]
            z = origin_z + pb.ground_y + level.elevation
            ends.append((corridor_key(pb.building.id, c, end.at), (m[0], m[1], z)))
        if len(ends) < 2:
            continue
        (ka, a), (kb, b) = ends
        mid = [(*to_metric(*w), (a[2] + b[2]) / 2) for w in p.waypoints]
        geom = np.array([a, *mid, b], float)
        length = p.length_m or float(np.linalg.norm(np.diff(geom, axis=0), axis=1).sum())
        t = tm.walk(length)
        part.edges.append(GEdge(ka, kb, "passage", length, t, t, p.id, "passage", geom))
    return part


def stop_part(campus: Campus, z: float) -> Part:
    part = Part()
    for s in campus.stops:
        x, y = to_metric(*s.location)
        part.nodes.append(GNode(s.id, "stop", float(x), float(y), z, endpoint_key=s.id))
        part.links.append((s.id, None))
    return part


def assemble(outdoor: Outdoor, parts: list[Part], cfg: dict, tm: TimeModel) -> Graph:
    """Join the pieces by key, link them to the outdoor network and number the nodes."""
    warn = float(cfg.get("network", {}).get("link_warn_m", 40.0))
    issues = list(outdoor.issues)
    nodes: list[GNode] = list(outdoor.nodes)
    index = {n.key: i for i, n in enumerate(nodes)}
    for part in parts:
        issues += part.issues
        for n in part.nodes:
            if n.key in index:
                issues.append(
                    GraphIssue(
                        "Network: duplicate node keys", n.key, n.building_id, (n.x, n.y, n.z)
                    )
                )
                continue
            index[n.key] = len(nodes)
            nodes.append(n)

    edges: list[GEdge] = list(outdoor.edges)
    for part in parts:
        edges += part.edges
        for key, forced in part.links:
            n = nodes[index[key]]
            # an entrance's outside node ("D-17:main:out") has no building_id: take it from
            # the key; stops ("stop:x") belong to no building
            bid = n.building_id or (key.split(":")[0] if n.kind == "entrance" else None)
            target = f"osm:{forced}" if forced is not None else None
            if target in index:
                o = nodes[index[target]]
                d = math.hypot(o.x - n.x, o.y - n.y)
            else:
                if target is not None:  # a pinned osm_node gone from the walk graph
                    issues.append(
                        GraphIssue(
                            "Network: entrance osm_node not in the walk graph (nearest node used)",
                            f"{key}: {target}",
                            bid,
                            (n.x, n.y, n.z),
                        )
                    )
                target, d = outdoor.nearest(n.x, n.y)
            if d > warn:
                issues.append(
                    GraphIssue(
                        "Network: entrances and stops far from the walk network",
                        f"{key}: {d:.0f} m to the nearest path",
                        bid,
                        (n.x, n.y, n.z),
                    )
                )
            o = nodes[index[target]]
            length = math.dist((n.x, n.y, n.z), (o.x, o.y, o.z))
            t = tm.walk(length)
            edges.append(GEdge(key, target, "link", length, t, t, None, "link"))

    # one edge per node pair (the shortest), no loops, both ends known
    best: dict[tuple[int, int], GEdge] = {}
    for e in edges:
        u, v = index.get(e.u), index.get(e.v)
        if u is None or v is None:
            issues.append(GraphIssue("Network: edges to unknown nodes", f"{e.u} - {e.v}"))
            continue
        if u == v:
            continue
        pair = (min(u, v), max(u, v))
        if pair not in best or e.length_m < best[pair].length_m:
            best[pair] = e
    kept = sorted(best.items())

    nodes_df = pd.DataFrame(
        {
            "node_id": np.arange(len(nodes)),
            "key": [n.key for n in nodes],
            "kind": [n.kind for n in nodes],
            "x": [n.x for n in nodes],
            "y": [n.y for n in nodes],
            "z": [n.z for n in nodes],
            "building_id": pd.array([n.building_id for n in nodes], dtype=object),
            "level": pd.array([n.level for n in nodes], dtype="Int64"),
            "endpoint_key": pd.array([n.endpoint_key for n in nodes], dtype=object),
        }
    )
    edges_df = pd.DataFrame(
        {
            "u": [index[e.u] for _, e in kept],
            "v": [index[e.v] for _, e in kept],
            "kind": [e.kind for _, e in kept],
            "length_m": [e.length_m for _, e in kept],
            "time_uv_s": [e.time_uv_s for _, e in kept],
            "time_vu_s": [e.time_vu_s for _, e in kept],
            "source": pd.array([e.source for _, e in kept], dtype=object),
        }
    )

    # endpoints that cannot reach the main network
    pairs = edges_df[["u", "v"]].to_numpy(int).reshape(-1, 2)
    main = _main_component(len(nodes), pairs)
    for i in np.flatnonzero(~main & nodes_df.endpoint_key.notna().to_numpy()):
        n = nodes[i]
        issues.append(
            GraphIssue(
                "Network: endpoints cut off from the walk network",
                n.endpoint_key, n.building_id, (n.x, n.y, n.z),
            )
        )  # fmt: skip
    return Graph(
        nodes_df,
        edges_df,
        [e.cls for _, e in kept],
        [e.geometry for _, e in kept],
        issues,
    )


def build_campus_graph(cfg: dict, campus_dir: Path, layers: dict[str, gpd.GeoDataFrame]) -> Graph:
    """The whole graph from the OSM layers (campus.gpkg) and the hand-written campus.

    Building files that fail validation are left out and reported as issues; the web
    export shows the same problems with line numbers.
    """
    import yaml

    from ..geometry.building import largest_polygon, match_osm, osm_index, place
    from ..schemas import load_building
    from .indoor import building_part

    tm = TimeModel.from_config(cfg)
    origin_z = float(cfg["campus"]["web_origin"]["z"])
    campus = Campus.model_validate(
        yaml.safe_load((Path(campus_dir) / "campus.yaml").read_text(encoding="utf-8"))
    )
    outdoor = outdoor_part(layers["walk_nodes"], layers["walk_edges"], campus, cfg, tm)
    osm_buildings = layers["buildings"]
    index = osm_index(osm_buildings)
    ats = passage_ats(campus)
    placed: dict[str, PlacedBuilding] = {}
    parts: list[Part] = []
    skipped = Part()
    for f in sorted((Path(campus_dir) / "buildings").glob("*.yaml")):
        try:
            b = load_building(f)
            _, geom = match_osm(b, osm_buildings, index)
            p = place(b, cfg, origin_z, largest_polygon(geom))
        except (ValueError, yaml.YAMLError) as err:  # pydantic errors are ValueErrors too
            first = str(err).splitlines()[0]
            skipped.issues.append(
                GraphIssue("Network: building files left out", f"{f.name}: {first}", f.stem)
            )
            continue
        placed[b.id] = p
        parts.append(building_part(p, cfg, tm, origin_z, ats.get(b.id)))
    parts += [skipped, passage_part(campus, placed, tm, origin_z), stop_part(campus, outdoor.z)]
    graph = assemble(outdoor, parts, cfg, tm)
    log.info(
        "graph: %d nodes, %d edges, %d buildings, %d issues",
        len(graph.nodes), len(graph.edges), len(placed), len(graph.issues),
    )  # fmt: skip
    return graph

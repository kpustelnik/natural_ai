"""Raw OSM -> the layers of ``osm/campus.gpkg`` (contracts: ``schemas.tables.OSM_*``).

Everything here is offline and deterministic, so it is unit-tested on small inputs.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from ..schemas.common import METRIC_CRS

log = logging.getLogger(__name__)

# AGH building codes: A-0, B-1, D-17, DS-7, DS-Alfa, H-A1, U-2, Z-15, S-1, P-A0-A1 (connector)
AGH_CODE = re.compile(r"^(A|B|C|D|H|S|U|Z|DS|P)-[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")
_NO_DASH = re.compile(r"^([A-Z]{1,2})(\d+[A-Za-z]?)$")  # Z15 -> Z-15
_CONNECTOR_END = re.compile(r"[A-Z]{1,2}-?\d+[A-Za-z]?")

ACADEMIC_TAGS = {"university", "college", "school", "library", "yes", "office", "public"}
POINT_BARRIERS = {
    "gate", "lift_gate", "swing_gate", "sliding_gate", "kissing_gate", "turnstile",
    "bollard", "block", "chain", "entrance", "cycle_barrier", "stile", "full-height_turnstile",
}  # fmt: skip
STOP_TAGS = {"highway": "bus_stop", "railway": "tram_stop", "public_transport": "platform"}


@dataclass
class Issue:
    section: str
    text: str
    building_id: str | None = None
    osm_id: str | None = None


@dataclass
class Issues:
    """Things a human should look at; rendered into report.md and osm/issues.json."""

    records: list[Issue] = field(default_factory=list)

    def add(
        self, section: str, text: str, building_id: str | None = None, osm_id: str | None = None
    ) -> None:
        self.records.append(Issue(section, text, building_id, osm_id))

    @property
    def items(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for r in self.records:
            out.setdefault(r.section, []).append(r.text)
        return out


# --- tag helpers ------------------------------------------------------------


def _tag(row: pd.Series, key: str) -> str | None:
    v = row.get(key)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return str(v).strip() or None


def parse_number(value) -> float | None:
    """'5', '24.9 m', '1;12' -> largest number, None if nothing parses."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    nums = [float(m) for m in re.findall(r"\d+(?:[.,]\d+)?", str(value).replace(",", "."))]
    return max(nums) if nums else None


def normalize_ref(raw: str | None) -> str | None:
    """Raw OSM ref -> AGH building code, or None if it is not one."""
    if not raw:
        return None
    for token in str(raw).split(";"):
        t = token.strip().replace(" ", "")
        m = _NO_DASH.fullmatch(t)
        if m:
            t = f"{m[1]}-{m[2]}"
        if AGH_CODE.fullmatch(t):
            return t
    return None


def connector_ends(code: str) -> tuple[str, str] | None:
    """'P-A0-A1' -> ('A-0', 'A-1'); 'P-D2-S-1' -> ('D-2', 'S-1')."""
    if not code.startswith("P-"):
        return None
    ends = [normalize_ref(t) for t in _CONNECTOR_END.findall(code[2:])]
    if len(ends) != 2 or None in ends:
        return None
    return ends[0], ends[1]


def classify(code: str | None, building_tag: str | None) -> str:
    if code is None:
        return "context"
    if code.startswith("P-"):
        return "connector"
    if code.startswith("DS-") or building_tag == "dormitory":
        return "dorm"
    return "academic" if (building_tag or "yes") in ACADEMIC_TAGS else "other"


def slug(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _osm_id(index_value) -> str:
    element, osmid = index_value
    return f"{element}/{osmid}"


def _join(values) -> str | None:
    """osmnx attributes may be lists after simplification -> 'a|b'."""
    if values is None or (isinstance(values, float) and np.isnan(values)):
        return None
    if isinstance(values, list | tuple | set):
        return "|".join(str(v) for v in values) or None
    return str(values)


# --- buildings ----------------------------------------------------------------


def has_value(v) -> bool:
    """Not None / NaN / 0 (NaN is truthy in Python, so `if v:` is wrong for tags)."""
    return v is not None and not pd.isna(v) and v != 0


def _height(levels: float | None, height: float | None, cfg: dict) -> tuple[float, str]:
    floor = cfg["campus"]["floor_height_m"]
    if has_value(height):
        return float(height), "tag"
    if has_value(levels):
        return float(levels) * floor, "levels"
    return cfg["campus"]["default_levels"] * floor, "default"


def buildings_layer(
    features: gpd.GeoDataFrame, overrides: pd.DataFrame, cfg: dict, issues: Issues
) -> gpd.GeoDataFrame:
    """One row per AGH building (parts merged) + one row per context building."""
    b = features[features.get("building").notna()].copy() if "building" in features else None
    if b is None or b.empty:
        raise ValueError("no buildings in the OSM features")
    b = b[b.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].to_crs(METRIC_CRS)

    rows = []
    override = overrides.set_index("osm_id") if len(overrides) else None
    for idx, row in b.iterrows():
        osm_id = _osm_id(idx)
        ref = _tag(row, "ref")
        building_tag = _tag(row, "building") or "yes"
        code = normalize_ref(ref)
        category = classify(code, building_tag)
        if override is not None and osm_id in override.index:
            o = override.loc[osm_id]
            code = o["building_id"] if pd.notna(o["building_id"]) else None
            category = o["category"] if pd.notna(o["category"]) else classify(code, building_tag)
        looks_agh = ref and re.match(r"^(DS|[ABCDHSUZ])-?\d", ref)
        if looks_agh and code is None:
            issues.add(
                "Refs that look like AGH codes but did not parse",
                f"{osm_id}: {ref!r}",
                osm_id=osm_id,
            )
        if code is None and building_tag == "dormitory":
            issues.add(
                "Dorms without an AGH code (context; add to osm_building_map.csv if AGH)",
                f"{osm_id}: {_tag(row, 'name')}",
                osm_id=osm_id,
            )
        rows.append(
            {
                "osm_id": osm_id,
                "building_id": code,
                "category": category if code else "context",
                "ref": ref,
                "name": _tag(row, "name"),
                "building": building_tag,
                "levels": parse_number(row.get("building:levels")),
                "levels_underground": parse_number(row.get("building:levels:underground")),
                "roof_levels": parse_number(row.get("roof:levels")),
                "height_tag": parse_number(row.get("height")),
                "geometry": row.geometry,
            }
        )
    df = gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)

    places = df[df.building_id.notna()]
    merged = []
    for code, group in places.groupby("building_id", sort=True):
        group = group.assign(area=group.geometry.area).sort_values("area", ascending=False)
        main = group.iloc[0]
        geom = unary_union(list(group.geometry))
        if len(group) > 1:
            kind = "disjoint" if isinstance(geom, MultiPolygon) else "touching"
            issues.add(
                "Buildings merged from several OSM elements",
                f"{code}: {', '.join(group.osm_id)} ({kind})",
                building_id=code,
            )
        if len(set(group.category)) > 1:
            issues.add(
                "Merged parts with different categories",
                f"{code}: {set(group.category)}",
                building_id=code,
            )
        rec = main.drop(labels=["area"]).to_dict()
        rec.update(
            osm_ids="|".join(group.osm_id),
            geometry=geom,
            levels=group.levels.max(),
            levels_underground=group.levels_underground.max(),
            roof_levels=group.roof_levels.max(),
            height_tag=group.height_tag.max(),
            name=next((n for n in group.name if n), None),
        )
        merged.append(rec)

    context = df[df.building_id.isna()].assign(osm_ids=lambda d: d.osm_id)
    out = gpd.GeoDataFrame(
        pd.concat([pd.DataFrame(merged), pd.DataFrame(context)], ignore_index=True),
        geometry="geometry",
        crs=METRIC_CRS,
    )
    heights = [_height(lv, h, cfg) for lv, h in zip(out.levels, out.height_tag, strict=True)]
    out["height_m"] = [h for h, _ in heights]
    out["height_source"] = [s for _, s in heights]
    out["connects"] = [
        "|".join(ends) if (c == "connector" and (ends := connector_ends(code))) else None
        for c, code in zip(out.category, out.building_id, strict=True)
    ]
    for code in out.loc[(out.category == "connector") & out.connects.isna(), "building_id"]:
        issues.add("Connectors whose building pair could not be parsed", code, building_id=code)
    known = set(out.building_id.dropna())
    for code, connects in out.loc[out.connects.notna(), ["building_id", "connects"]].to_numpy():
        missing = [e for e in connects.split("|") if e not in known]
        if missing:
            issues.add(
                "Connectors to buildings missing from OSM",
                f"{code}: {missing}",
                building_id=code,
            )
    for code in out.loc[(out.category != "context") & out.levels.isna(), "building_id"]:
        issues.add(
            "AGH buildings without building:levels (default height used)",
            code,
            building_id=code,
        )
    return out.drop(columns=["height_tag"])


# --- entrances --------------------------------------------------------------------


def entrances_layer(
    features: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, cfg: dict, issues: Issues
) -> gpd.GeoDataFrame:
    if "entrance" not in features:
        e = features.iloc[0:0]
    else:
        e = features[features.entrance.notna() & (features.geometry.geom_type == "Point")]
    e = e.to_crs(METRIC_CRS)
    ent = gpd.GeoDataFrame(
        {
            "osm_node": [int(i[1]) for i in e.index],
            "entrance": [_tag(r, "entrance") for _, r in e.iterrows()],
            "name": [_tag(r, "name") for _, r in e.iterrows()],
            "ref": [_tag(r, "ref") for _, r in e.iterrows()],
            "level": [_tag(r, "level") for _, r in e.iterrows()],
            "access": [_tag(r, "access") for _, r in e.iterrows()],
            "wheelchair": [_tag(r, "wheelchair") for _, r in e.iterrows()],
        },
        geometry=list(e.geometry),
        crs=METRIC_CRS,
    )

    # nearest building outline within entrance_snap_m (AGH buildings win over context)
    snap = cfg["osm"]["entrance_snap_m"]
    outlines = buildings[["osm_id", "building_id", "category", "geometry"]].copy()
    outlines["geometry"] = outlines.geometry.boundary
    joined = gpd.sjoin_nearest(
        ent, outlines, how="left", max_distance=snap, distance_col="dist"
    ).reset_index(names="_row")
    joined["_rank"] = joined.building_id.isna().astype(int)
    joined = joined.sort_values(["_row", "_rank", "dist"]).drop_duplicates("_row")
    joined = joined.sort_values("_row").set_index("_row")
    ent["building_id"] = joined.building_id.to_numpy()
    ent["building_osm_id"] = joined.osm_id.to_numpy()

    # main entrance per AGH building: entrance=main, then yes, then anything usable
    priority = {"main": 0, "yes": 1, "entrance": 1, "home": 2, "staircase": 2, "service": 3}
    ent["is_main"] = False
    usable = ent[ent.building_id.notna() & (ent.entrance != "emergency")]
    for code, group in usable.groupby("building_id"):
        ranked = group.assign(
            p=group.entrance.map(lambda t: priority.get(t, 4)),
            private=group.access.isin(["private", "no"]).astype(int),
        ).sort_values(["private", "p", "osm_node"])
        if (group.entrance == "main").sum() > 1:
            issues.add(
                "Buildings with several entrance=main (first by node id used)",
                code,
                building_id=code,
            )
        ent.loc[ranked.index[0], "is_main"] = True
    return ent


# --- stops, barriers, boundary ------------------------------------------------------------


def stops_layer(features: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mask = pd.Series(False, index=features.index)
    for key, value in STOP_TAGS.items():
        if key in features:
            mask |= features[key] == value
    s = features[mask].to_crs(METRIC_CRS)
    rows = []
    for idx, row in s.iterrows():
        name = _tag(row, "name")
        if not name:
            continue
        base = re.sub(r"\s+\d{1,2}$", "", name)
        tram = _tag(row, "railway") == "tram_stop" or _tag(row, "tram") == "yes"
        bus = _tag(row, "highway") == "bus_stop" or _tag(row, "bus") == "yes"
        rows.append(
            {
                "name": base,
                "osm_id": _osm_id(idx),
                "mode": "|".join(m for m, on in (("bus", bus), ("tram", tram)) if on) or "bus",
                "geometry": row.geometry.centroid,
            }
        )
    if not rows:
        return gpd.GeoDataFrame(
            columns=["stop_id", "name", "modes", "n_platforms", "platform_ids", "geometry"],
            geometry="geometry",
            crs=METRIC_CRS,
        )
    df = gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)
    df["slug"] = df.name.map(slug)
    out = []
    # group by slug: "AGH / UR" and "AGH/UR" are the same stop
    for key, group in df.groupby("slug", sort=True):
        modes = sorted({m for ms in group["mode"] for m in ms.split("|")})
        out.append(
            {
                "stop_id": f"stop:{key}",
                "name": group.name.mode().iloc[0],
                "modes": "|".join(modes),
                "n_platforms": len(group),
                "platform_ids": "|".join(sorted(group.osm_id)),
                "geometry": Point(group.geometry.x.mean(), group.geometry.y.mean()),
            }
        )
    return gpd.GeoDataFrame(out, geometry="geometry", crs=METRIC_CRS)


def barriers_layers(features: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    if "barrier" not in features:
        empty = features.iloc[0:0].to_crs(METRIC_CRS)
        return empty, empty
    b = features[features.barrier.notna()].to_crs(METRIC_CRS)
    base = pd.DataFrame(
        {
            "osm_id": [_osm_id(i) for i in b.index],
            "barrier": [_tag(r, "barrier") for _, r in b.iterrows()],
            "access": [_tag(r, "access") for _, r in b.iterrows()],
            "name": [_tag(r, "name") for _, r in b.iterrows()],
        }
    )
    g = gpd.GeoDataFrame(base, geometry=list(b.geometry), crs=METRIC_CRS)
    points = g[(g.geom_type == "Point") & g.barrier.isin(POINT_BARRIERS)].reset_index(drop=True)
    lines = g[g.geom_type != "Point"].drop(columns=["name"]).reset_index(drop=True)
    return points, lines


def boundary_layer(
    features: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, bbox: Polygon, cfg: dict
) -> gpd.GeoDataFrame:
    rows = []
    rel = ("relation", cfg["campus"]["agh_relation"])
    if rel in features.index:
        geom = gpd.GeoSeries([features.loc[rel].geometry], crs=features.crs).to_crs(METRIC_CRS)
        rows.append(
            {
                "kind": "agh_campus",
                "name": "Akademia Górniczo-Hutnicza",
                "osm_id": _osm_id(rel),
                "geometry": geom.iloc[0],
            }  # fmt: skip
        )
    dorms = buildings[buildings.category == "dorm"]
    if len(dorms):
        hull = unary_union(list(dorms.geometry)).convex_hull.buffer(30)
        rows.append(
            {
                "kind": "miasteczko",
                "name": "Miasteczko Studenckie AGH (from dorms)",
                "osm_id": None,
                "geometry": hull,
            }  # fmt: skip
        )
    bbox_m = gpd.GeoSeries([bbox], crs="EPSG:4326").to_crs(METRIC_CRS).iloc[0]
    rows.append({"kind": "bbox", "name": "download area", "osm_id": None, "geometry": bbox_m})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


# --- walk graph -----------------------------------------------------------------------


def walk_layers(graph: nx.MultiDiGraph) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    g = ox.projection.project_graph(ox.convert.to_undirected(graph), to_crs=METRIC_CRS)
    nodes, edges = ox.convert.graph_to_gdfs(g)

    def col(df, name):
        return df[name].map(_join) if name in df else pd.Series(None, index=df.index, dtype=object)

    n = gpd.GeoDataFrame(
        {
            "osm_node": nodes.index.astype("int64"),
            "street_count": nodes.get("street_count", pd.Series(0, index=nodes.index))
            .fillna(0)
            .astype("int64"),
            "highway": col(nodes, "highway"),
            "barrier": col(nodes, "barrier"),
            "access": col(nodes, "access"),
            "entrance": col(nodes, "entrance"),
        },
        geometry=nodes.geometry.to_numpy(),
        crs=METRIC_CRS,
    ).reset_index(drop=True)

    edges = edges.reset_index()
    highway = col(edges, "highway").fillna("unknown")
    e = gpd.GeoDataFrame(
        {
            "u": edges.u.astype("int64"),
            "v": edges.v.astype("int64"),
            "key": edges.key.astype("int64"),
            "osm_ways": col(edges, "osmid"),
            "highway": highway,
            "name": col(edges, "name"),
            "length_m": edges.length.astype(float) if "length" in edges else edges.geometry.length,
            "is_steps": highway.str.contains("steps"),
            "step_count": col(edges, "step_count").map(parse_number),
            **{
                k: col(edges, k)
                for k in (
                    "incline",
                    "access",
                    "foot",
                    "covered",
                    "tunnel",
                    "bridge",
                    "indoor",
                    "level",
                    "surface",
                )  # fmt: skip
            },
        },
        geometry=edges.geometry.to_numpy(),
        crs=METRIC_CRS,
    )
    e["length_m"] = e.geometry.length  # metric 2D length (osmnx length is geodesic, equal here)
    return n, e


# --- all layers ---------------------------------------------------------------------------


def build_layers(
    features: gpd.GeoDataFrame,
    graph: nx.MultiDiGraph,
    bbox: Polygon,
    overrides: pd.DataFrame,
    cfg: dict,
) -> tuple[dict[str, gpd.GeoDataFrame], Issues]:
    """Every layer of osm/campus.gpkg, keyed by layer name."""
    issues = Issues()
    buildings = buildings_layer(features, overrides, cfg, issues)
    entrances = entrances_layer(features, buildings, cfg, issues)

    on_agh = entrances[entrances.building_id.notna()]
    counts = on_agh.groupby("building_id").size()
    mains = on_agh[on_agh.is_main].set_index("building_id").osm_node
    buildings["n_entrances"] = buildings.building_id.map(counts).fillna(0).astype("int64")
    buildings["main_entrance_node"] = buildings.building_id.map(mains).astype("Int64")

    barriers, fences = barriers_layers(features)
    walk_nodes, walk_edges = walk_layers(graph)
    layers = {
        "boundary": boundary_layer(features, buildings, bbox, cfg),
        "buildings": buildings,
        "entrances": entrances,
        "stops": stops_layer(features),
        "barriers": barriers,
        "fences": fences,
        "walk_nodes": walk_nodes,
        "walk_edges": walk_edges,
    }

    if "boundary" in layers:
        campus = layers["boundary"]
        area = unary_union(list(campus[campus.kind != "bbox"].geometry))
        if not area.is_empty:
            outside = buildings[buildings.building_id.notna() & ~buildings.intersects(area)]
            for code in outside.building_id:
                issues.add(
                    "AGH codes outside the campus area (check they are AGH)",
                    code,
                    building_id=code,
                )
    return layers, issues

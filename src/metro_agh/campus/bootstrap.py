"""Write LOD1 ``buildings/<id>.yaml`` stubs from the OSM layers.

Existing files are never touched: once a file exists it belongs to whoever models it.
The local frame is chosen to make hand modelling easy: origin at the main entrance,
+x along the building's long axis, pointing into the building.
"""

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import yaml
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

from ..schemas import load_building
from .geo import LocalFrame, long_axis_bearing, to_geo
from .osm_process import Issues, has_value

log = logging.getLogger(__name__)

KIND = {"academic": "academic", "dorm": "dorm", "other": "other", "connector": "other"}
HEADER = """\
# yaml-language-server: $schema=../../../schemas/building.schema.json
# Bootstrapped from OpenStreetMap ({osm_ids}) on {date}. LOD1.
# Edit freely: the OSM bootstrap never overwrites this file.
# Format: docs/data_contracts.md, section 3.1
"""


class _Flow(list):
    pass


class _FlowMap(dict):
    pass


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(
    _Flow, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True)
)
_Dumper.add_representer(
    _FlowMap, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v, flow_style=True)
)


@dataclass
class BootstrapResult:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _r(v: float, nd: int = 1) -> float:
    return round(float(v), nd) + 0.0  # + 0.0 turns -0.0 into 0.0


def _ring(coords: np.ndarray) -> list:
    pts = [_Flow([_r(x), _r(y)]) for x, y in coords[:-1]]
    # drop points that collapsed onto their predecessor after rounding
    out = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    return out[:-1] if len(out) > 1 and out[-1] == out[0] else out


def building_document(
    row, entrances: gpd.GeoDataFrame, walk_nodes: set[int], cfg: dict, issues: Issues
) -> dict:
    """One row of the buildings layer (EPSG:2180) -> YAML-ready dict."""
    geom = row.geometry
    if isinstance(geom, MultiPolygon):
        parts = sorted(geom.geoms, key=lambda p: p.area, reverse=True)
        issues.add(
            "Disjoint footprints: only the largest part was bootstrapped",
            f"{row.building_id}: {len(parts)} parts",
            building_id=row.building_id,
        )
        geom = parts[0]
    poly: Polygon = orient(geom.simplify(cfg["osm"]["footprint_simplify_m"]), sign=1.0)

    ents = entrances[
        (entrances.building_id == row.building_id) & (entrances.entrance != "emergency")
    ]
    main = ents[ents.is_main]
    if len(main):
        anchor = (main.geometry.iloc[0].x, main.geometry.iloc[0].y)
    else:
        p = poly.representative_point()
        anchor = (p.x, p.y)
        issues.add(
            "AGH buildings without entrances (anchor = inside point)",
            row.building_id,
            building_id=row.building_id,
        )

    # +x along the long axis; flip it so the building centre is on the positive side of
    # whichever axis it is further along (in front of an end entrance, left of a side one)
    bearing = long_axis_bearing(poly)
    frame = LocalFrame(anchor, bearing)
    cx, cy = frame.to_local(np.array([poly.centroid.coords[0]]))[0]
    if (cx if abs(cx) >= abs(cy) else cy) < 0:
        frame = LocalFrame(anchor, (bearing + 180.0) % 360.0)

    lon, lat = to_geo(*anchor)
    doc: dict = {
        "schema_version": 1,
        "id": row.building_id,
    }
    if row.category == "connector":
        a, b = row.connects.split("|") if has_value(row.connects) else ("?", "?")
        doc["name"] = row.name if has_value(row.name) else f"Łącznik {a} – {b}"
    elif has_value(row.name):
        doc["name"] = row.name
    doc["kind"] = KIND[row.category]
    if has_value(row.ref) and row.ref.strip() != row.building_id:
        doc["aliases"] = _Flow([row.ref.strip()])
    doc["osm_id"] = row.osm_id
    doc["placement"] = {
        "anchor": _Flow([round(float(lon), 7), round(float(lat), 7)]),
        "bearing_deg": round(float(frame.bearing_deg), 1),
    }
    doc["footprint"] = _ring(frame.to_local(np.asarray(poly.exterior.coords)))
    holes = [_ring(frame.to_local(np.asarray(h.coords))) for h in poly.interiors]
    if holes:
        doc["footprint_holes"] = holes
    if has_value(row.levels):
        doc["n_levels"] = max(1, round(row.levels))
    doc["height_m"] = round(float(row.height_m), 1)

    entrances_doc = []
    others = ents[~ents.is_main].sort_values("osm_node")
    for i, (_, e) in enumerate([*main.iterrows(), *others.iterrows()]):
        x, y = frame.to_local(np.array([[e.geometry.x, e.geometry.y]]))[0]
        item = _FlowMap(
            id="main" if e.is_main else f"e{i}",
            point=_Flow([_r(x), _r(y)]),
        )
        if e.is_main and row.category == "academic":
            item["metro_shaft"] = True
        if int(e.osm_node) in walk_nodes:
            item["osm_node"] = int(e.osm_node)
        entrances_doc.append(item)
    if not entrances_doc:  # schema allows none, but a point keeps the building reachable
        entrances_doc.append(
            _FlowMap(
                id="main",
                point=_Flow([0.0, 0.0]),
                **({"metro_shaft": True} if row.category == "academic" else {}),
            )
        )
    doc["entrances"] = entrances_doc
    return doc


def bootstrap(
    buildings: gpd.GeoDataFrame,
    entrances: gpd.GeoDataFrame,
    walk_nodes: set[int],
    out_dir: Path,
    cfg: dict,
    issues: Issues,
) -> BootstrapResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = BootstrapResult()
    places = buildings[buildings.building_id.notna()].sort_values("building_id")
    today = dt.date.today().isoformat()
    for row in places.itertuples():
        path = out_dir / f"{row.building_id}.yaml"
        if path.exists():
            result.skipped.append(row.building_id)
            continue
        doc = building_document(row, entrances, walk_nodes, cfg, issues)
        text = HEADER.format(osm_ids=row.osm_ids.replace("|", ", "), date=today)
        text += yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
        path.write_text(text, encoding="utf-8", newline="\n")
        try:
            load_building(path)
        except Exception as err:  # noqa: BLE001 - report and keep going
            path.unlink()
            result.failed.append(f"{row.building_id}: {err}")
            issues.add(
                "Bootstrap failed validation (file not written)",
                f"{row.building_id}: {err}",
                building_id=row.building_id,
            )
            continue
        result.written.append(row.building_id)
    return result

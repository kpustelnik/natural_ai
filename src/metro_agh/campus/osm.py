"""Download of OSM data for the campus bbox.

Two Overpass queries, saved as raw OSM XML (open them in JOSM to inspect):
    data/raw/osm/features.osm   buildings, entrances, stops, barriers, university areas
    data/raw/osm/walk.osm       the walk network (osmnx "walk" filter)
Existing files are reused, so re-runs work offline; ``refresh=True`` downloads again.
osmnx then only parses the files (``features_from_xml`` / ``graph_from_xml``).

Overpass is often overloaded and rate-limits by IP (HTTP 429), so every query retries with
backoff over the servers in ``osm.overpass_urls``.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import requests
from shapely.geometry import Polygon, box

log = logging.getLogger(__name__)

FEATURE_TAGS: dict[str, bool | str | list[str]] = {
    "building": True,
    "entrance": True,
    "highway": "bus_stop",
    "railway": "tram_stop",
    "public_transport": "platform",
    "barrier": True,
    "amenity": "university",
}

# osmnx network_type="walk" (osmnx 2.1), kept here so the query does not depend on internals
WALK_FILTER = (
    '["highway"]["area"!~"yes"]["access"!~"private"]'
    '["highway"!~"abandoned|bus_guideway|construction|cycleway|motor|no|planned|platform|'
    'proposed|raceway|razed|rest_area|services"]'
    '["foot"!~"no"]["service"!~"private"]'
    '["sidewalk"!~"separate"]["sidewalk:both"!~"separate"]'
    '["sidewalk:left"!~"separate"]["sidewalk:right"!~"separate"]'
)

WAY_TAGS = [
    "highway", "name", "footway", "step_count", "incline", "access", "foot", "level",
    "layer", "bridge", "tunnel", "covered", "indoor", "surface", "width", "lit",
]  # fmt: skip
NODE_TAGS = ["highway", "barrier", "access", "entrance", "ref", "name", "level"]


@dataclass
class OsmRaw:
    bbox: Polygon  # EPSG:4326
    features: gpd.GeoDataFrame  # EPSG:4326, index (element, id)
    graph: nx.MultiDiGraph  # walk graph, unprojected


def bbox_polygon(cfg: dict) -> Polygon:
    b = cfg["campus"]["bbox"]
    return box(b["west"], b["south"], b["east"], b["north"])


def _bbox_clause(cfg: dict) -> str:
    b = cfg["campus"]["bbox"]
    return f"{b['south']},{b['west']},{b['north']},{b['east']}"


def features_query(cfg: dict) -> str:
    t = cfg["osm"]["timeout_s"]
    selectors = "".join(
        f'nwr["{k}"];' if v is True else f'nwr["{k}"="{v}"];' for k, v in FEATURE_TAGS.items()
    )
    return f"[out:xml][timeout:{t}][bbox:{_bbox_clause(cfg)}];({selectors});(._;>;);out body;"


def walk_query(cfg: dict) -> str:
    t = cfg["osm"]["timeout_s"]
    return f"[out:xml][timeout:{t}][bbox:{_bbox_clause(cfg)}];way{WALK_FILTER};(._;>;);out body;"


def overpass(query: str, cfg: dict, what: str) -> bytes:
    """POST a query, retrying over servers; returns the raw XML."""
    osm = cfg["osm"]
    urls, attempts = osm["overpass_urls"], osm["retries"]
    headers = {"User-Agent": osm["user_agent"]}
    for attempt in range(attempts):
        url = urls[attempt % len(urls)]
        log.info("%s: %s (attempt %d/%d)", what, url, attempt + 1, attempts)
        try:
            r = requests.post(
                url, data={"data": query}, headers=headers, timeout=osm["timeout_s"] + 30
            )
            body = r.content
            if r.status_code == 200 and body.lstrip().startswith(b"<?xml"):
                if b"<remark>" in body and b"runtime error" in body:
                    log.warning("%s: server error remark: %s", what, body[-300:])
                else:
                    return body
            else:
                log.warning("%s: HTTP %s from %s", what, r.status_code, url)
        except requests.RequestException as err:
            log.warning("%s: %s on %s", what, err, url)
        time.sleep(min(120, 10 * 2**attempt))
    raise RuntimeError(f"{what}: all {attempts} Overpass attempts failed; try again later")


def download(cfg: dict, raw_dir: Path, refresh: bool = False) -> tuple[Path, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, query in (("features", features_query(cfg)), ("walk", walk_query(cfg))):
        path = raw_dir / f"{name}.osm"
        if refresh or not path.exists():
            path.write_bytes(overpass(query, cfg, name))
            log.info("saved %s (%.1f MB)", path, path.stat().st_size / 1e6)
        else:
            log.info("using cached %s (--refresh to download again)", path)
        out[name] = path
    return out["features"], out["walk"]


def fetch(cfg: dict, raw_dir: Path, refresh: bool = False) -> OsmRaw:
    features_file, walk_file = download(cfg, raw_dir, refresh)
    ox.settings.log_console = False
    ox.settings.useful_tags_way = WAY_TAGS
    ox.settings.useful_tags_node = NODE_TAGS
    features = ox.features.features_from_xml(features_file, tags=FEATURE_TAGS)
    graph = ox.graph.graph_from_xml(walk_file, bidirectional=True, simplify=True, retain_all=True)
    return OsmRaw(bbox=bbox_polygon(cfg), features=features, graph=graph)

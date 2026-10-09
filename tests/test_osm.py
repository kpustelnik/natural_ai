"""OSM stage on small hand-built inputs (no network)."""

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
import yaml
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box

from metro_agh.campus.bootstrap import bootstrap
from metro_agh.campus.geo import LocalFrame, long_axis_bearing, to_geo, to_metric
from metro_agh.campus.osm_process import (
    build_layers,
    classify,
    connector_ends,
    normalize_ref,
    parse_number,
    slug,
)
from metro_agh.config import load_config
from metro_agh.schemas import load_building
from metro_agh.schemas.tables import OSM_TABLES

CFG = load_config()
X0, Y0 = to_metric(19.912, 50.068)  # somewhere on the campus


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("D-17", "D-17"),
        ("Z15", "Z-15"),
        ("DS-Alfa", "DS-Alfa"),
        ("P-A0-A1", "P-A0-A1"),
        ("H-B3B4", "H-B3B4"),
        ("AGHK;KRK 44099", None),
        ("KRK 4389", None),
        ("AGH3", None),
        (None, None),
    ],
)
def test_normalize_ref(raw, code):
    assert normalize_ref(raw) == code


def test_connector_ends():
    assert connector_ends("P-A0-A1") == ("A-0", "A-1")
    assert connector_ends("P-D2-S-1") == ("D-2", "S-1")
    assert connector_ends("P-A4-C4") == ("A-4", "C-4")
    assert connector_ends("D-17") is None


def test_classify_and_helpers():
    assert classify("D-17", "university") == "academic"
    assert classify("DS-7", "dormitory") == "dorm"
    assert classify("U-10", "hospital") == "other"
    assert classify("P-A0-A1", "university") == "connector"
    assert classify(None, "university") == "context"
    assert parse_number("1;12") == 12
    assert parse_number("24.9 m") == 24.9
    assert parse_number(None) is None
    assert slug("Miasteczko Studenckie AGH") == "miasteczko_studenckie_agh"
    assert slug("Łobzów Pętla") == "lobzow_petla"


def test_local_frame_roundtrip_and_bearing():
    frame = LocalFrame((X0, Y0), 75.0)
    pts = np.array([[X0 + 10, Y0 - 3], [X0, Y0], [X0 - 40, Y0 + 25]])
    np.testing.assert_allclose(frame.to_metric(frame.to_local(pts)), pts, atol=1e-6)
    # +x along bearing 90 = east
    np.testing.assert_allclose(
        LocalFrame((X0, Y0), 90).to_local([[X0 + 5, Y0]]), [[5, 0]], atol=1e-9
    )
    rect = rotate(box(0, 0, 60, 10), -30, origin=(0, 0))  # long side rotated 30 deg clockwise
    assert long_axis_bearing(rect) == pytest.approx(120.0)


# --- synthetic OSM ------------------------------------------------------------------


def _geo(geom):
    """Metric shapely geometry -> lon/lat."""
    from shapely.ops import transform

    return transform(lambda x, y, z=None: to_geo(x, y), geom)


def _features() -> gpd.GeoDataFrame:
    rows = [
        # D-17 as two touching parts (like D-1 in real OSM)
        (("way", 1), {"building": "university", "ref": "D-17", "building:levels": "4"},
         box(X0, Y0, X0 + 40, Y0 + 15)),
        (("way", 2), {"building": "university", "ref": "D-17"},
         box(X0 + 40, Y0, X0 + 50, Y0 + 15)),
        (("way", 3), {"building": "university", "ref": "A-0", "height": "20"},
         box(X0 + 100, Y0, X0 + 160, Y0 + 40)
         .difference(box(X0 + 115, Y0 + 10, X0 + 145, Y0 + 30))),
        (("way", 4), {"building": "university", "ref": "P-A0-D17"},
         box(X0 + 50, Y0 + 5, X0 + 100, Y0 + 10)),
        (("way", 5), {"building": "dormitory", "ref": "DS-7", "name": "Zaścianek"},
         box(X0, Y0 + 200, X0 + 60, Y0 + 214)),
        (("way", 6), {"building": "apartments"}, box(X0 + 300, Y0, X0 + 320, Y0 + 20)),
        (("node", 10), {"entrance": "main"}, Point(X0, Y0 + 7.5)),
        (("node", 11), {"entrance": "yes"}, Point(X0 + 50, Y0 + 2)),
        (("node", 12), {"entrance": "emergency"}, Point(X0 + 20, Y0 + 15)),
        (("node", 13), {"entrance": "yes"}, Point(X0 + 310, Y0)),
        (("node", 20), {"highway": "bus_stop", "name": "Kawiory 01", "bus": "yes"},
         Point(X0 + 5, Y0 - 30)),
        (("node", 21), {"highway": "bus_stop", "name": "Kawiory 02", "bus": "yes"},
         Point(X0 + 25, Y0 - 34)),
        (("node", 30), {"barrier": "gate", "access": "private"}, Point(X0 + 70, Y0 - 20)),
        (("way", 31), {"barrier": "fence"}, LineString([(X0, Y0 - 50), (X0 + 90, Y0 - 50)])),
    ]  # fmt: skip
    index = pd.MultiIndex.from_tuples([r[0] for r in rows], names=["element", "id"])
    tags = pd.DataFrame([r[1] for r in rows], index=index)
    return gpd.GeoDataFrame(tags, geometry=[_geo(r[2]) for r in rows], crs="EPSG:4326")


def _graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph(crs="epsg:4326")
    pts = {10: (X0, Y0 + 7.5), 100: (X0 - 20, Y0 + 7.5), 101: (X0 - 20, Y0 - 30)}
    for n, (x, y) in pts.items():
        lon, lat = to_geo(x, y)
        g.add_node(n, x=lon, y=lat, street_count=1)
    for u, v, hw in [(10, 100, "footway"), (100, 101, "steps")]:
        for a, b in [(u, v), (v, u)]:
            g.add_edge(a, b, osmid=500 + u, highway=hw, length=1.0)
    return g


@pytest.fixture(scope="module")
def layers():
    bbox = _geo(box(X0 - 100, Y0 - 100, X0 + 400, Y0 + 300))
    layers, issues = build_layers(_features(), _graph(), bbox, pd.DataFrame(), CFG)
    return layers, issues


def test_layers_match_contracts(layers):
    layers, _ = layers
    for table in OSM_TABLES:
        table.validate(layers[table.layer])


def test_buildings_merged_and_classified(layers):
    layers, issues = layers
    b = layers["buildings"].set_index("osm_id")
    assert b.loc["way/1", "osm_ids"] == "way/1|way/2"
    assert b.loc["way/1", "height_m"] == pytest.approx(4 * CFG["campus"]["floor_height_m"])
    assert b.loc["way/3", "height_source"] == "tag"
    assert b.loc["way/4", "category"] == "connector"
    assert b.loc["way/4", "connects"] == "A-0|D-17"
    assert b.loc["way/5", "category"] == "dorm"
    assert b.loc["way/6", "category"] == "context"
    assert "Buildings merged from several OSM elements" in issues.items


def test_entrances_and_stops(layers):
    layers, _ = layers
    e = layers["entrances"].set_index("osm_node")
    assert e.loc[10, "building_id"] == "D-17" and e.loc[10, "is_main"]
    assert e.loc[11, "building_id"] == "D-17" and not e.loc[11, "is_main"]
    assert pd.isna(e.loc[13, "building_id"]) and e.loc[13, "building_osm_id"] == "way/6"
    b = layers["buildings"].set_index("osm_id")
    assert b.loc["way/1", "main_entrance_node"] == 10
    s = layers["stops"]
    assert list(s.stop_id) == ["stop:kawiory"] and s.n_platforms.iloc[0] == 2
    assert layers["walk_edges"].is_steps.sum() == 1


def test_bootstrap_writes_valid_yaml_and_never_overwrites(layers, tmp_path):
    layers, issues = layers
    walk_nodes = set(layers["walk_nodes"].osm_node)
    res = bootstrap(layers["buildings"], layers["entrances"], walk_nodes, tmp_path, CFG, issues)
    assert sorted(res.written) == ["A-0", "D-17", "DS-7", "P-A0-D17"] and not res.failed

    d17 = load_building(tmp_path / "D-17.yaml")
    assert d17.lod == 1 and d17.n_levels == 4
    main = next(e for e in d17.entrances if e.id == "main")
    assert main.point == (0.0, 0.0) and main.metro_shaft and main.osm_node == 10
    assert all(x >= -0.05 for x, _ in d17.footprint)  # building lies in +x
    assert load_building(tmp_path / "A-0.yaml").footprint_holes  # courtyard kept
    assert not any(e.metro_shaft for e in load_building(tmp_path / "DS-7.yaml").entrances)

    (tmp_path / "D-17.yaml").write_text("hand edited", encoding="utf-8")
    again = bootstrap(layers["buildings"], layers["entrances"], walk_nodes, tmp_path, CFG, issues)
    assert "D-17" in again.skipped and not again.written
    assert (tmp_path / "D-17.yaml").read_text(encoding="utf-8") == "hand edited"


def test_bootstrap_yaml_is_readable(layers, tmp_path):
    layers, issues = layers
    bootstrap(layers["buildings"], layers["entrances"], set(), tmp_path, CFG, issues)
    text = (tmp_path / "D-17.yaml").read_text(encoding="utf-8")
    assert text.startswith("# yaml-language-server")
    assert "- [0.0, 0.0]" in text or "[0.0, 0.0]" in text  # flow-style coordinates
    assert yaml.safe_load(text)["placement"]["bearing_deg"] in (90.0, 270.0)


def test_unused_polygon_import_guard():
    assert Polygon  # keeps the import used for readers extending these fixtures

"""Web export (phase 0): meshes, glb writer, binaries and the campus export end to end."""

import json
import shutil

import numpy as np
import pandas as pd
import pytest
from shapely import contains_xy
from shapely.geometry import box

from metro_agh.campus.geo import LocalFrame
from metro_agh.campus.osm_process import build_layers
from metro_agh.campus.osm_report import write_issues
from metro_agh.config import ROOT, load_config, provenance
from metro_agh.geometry.building import frame_axes_web
from metro_agh.geometry.mesh import flat, outline, prism, walls, web
from metro_agh.schemas.tables import OSM_TABLES
from metro_agh.schemas.web import (
    BuildingInfo,
    BuildStatus,
    ContextFeatures,
    IssueList,
    NetworkHeader,
    ReplayCatalog,
    Scene,
)
from metro_agh.web.binary import pack
from metro_agh.web.export_campus import edge_class, export_campus
from metro_agh.web.gltf import Node, read_glb_json, write_glb
from test_osm import X0, Y0, _features, _geo, _graph

CFG = load_config()
ORIGIN = (X0, Y0)


def _tri_normals(m):
    tri = m.indices.reshape(-1, 3)
    a, b, c = (m.positions[tri[:, i]].astype(float) for i in range(3))
    return np.cross(b - a, c - a), tri


def test_flat_area_and_winding():
    poly = box(X0, Y0, X0 + 30, Y0 + 20).difference(box(X0 + 10, Y0 + 5, X0 + 20, Y0 + 15))
    m = flat(poly, 3.0, ORIGIN)
    face, _ = _tri_normals(m)
    assert np.all(face[:, 1] > 0)  # counter-clockwise seen from above
    assert 0.5 * np.linalg.norm(face, axis=1).sum() == pytest.approx(poly.area)
    assert np.allclose(m.positions[:, 1], 3.0)


def test_walls_point_outwards():
    poly = box(X0, Y0, X0 + 30, Y0 + 20).difference(box(X0 + 10, Y0 + 5, X0 + 20, Y0 + 15))
    m = walls(poly, 0.0, 7.0, ORIGIN)
    face, tri = _tri_normals(m)
    assert np.all((face * m.normals[tri[:, 0]]).sum(axis=1) > 0)  # winding agrees with normals
    # wall centres moved along their normal leave the solid (outer walls and courtyard walls)
    centre = m.positions[tri].mean(axis=1)
    probe = centre + 0.5 * m.normals[tri[:, 0]]
    east, north = probe[:, 0] + X0, -probe[:, 2] + Y0
    assert not contains_xy(poly, east, north).any()
    assert len(m.positions) == 4 * 8  # 4 outer + 4 courtyard walls


def test_prism_and_outline():
    poly = box(X0, Y0, X0 + 10, Y0 + 10)
    m = prism(poly, 0.0, 6.0, ORIGIN)
    assert m.n_triangles == 4 * 2 + 2
    lines = outline(poly, [0.0, 3.0, 6.0], ORIGIN)
    assert len(lines.positions) == 2 * (3 * 4 + 4)  # rings at 3 heights + 4 corners


def test_frame_formula_matches_local_frame():
    frame = LocalFrame((X0 + 3, Y0 - 7), 63.0)
    local = np.array([[12.0, -4.0], [0.0, 9.5]])
    expect = web(*frame.to_metric(local).T, 0.0, ORIGIN)
    anchor = web([frame.anchor[0]], [frame.anchor[1]], 0.0, ORIGIN)[0]
    ex, ey = frame_axes_web(63.0)
    got = anchor + local[:, :1] * ex + local[:, 1:] * ey
    np.testing.assert_allclose(got, expect, atol=1e-3)


def test_glb_structure(tmp_path):
    m = prism(box(X0, Y0, X0 + 10, Y0 + 10), 0.0, 6.0, ORIGIN)
    ids = np.zeros(m.n_vertices, np.float32)
    root = Node(
        "X-1",
        extras={"building": "X-1"},
        children=[
            Node("shell", m, "mat:wall", attributes={"_FEATURE_ID": ids}),
            Node("L0", extras={"level": 0}),
            Node("edges", outline(box(X0, Y0, X0 + 1, Y0 + 1), [0.0], ORIGIN), "mat:edge"),
        ],
    )
    size = write_glb(tmp_path / "x.glb", [root])
    assert size % 4 == 0
    doc = read_glb_json(tmp_path / "x.glb")
    names = [n["name"] for n in doc["nodes"]]
    assert names == ["X-1", "shell", "L0", "edges"]
    assert doc["nodes"][0]["extras"] == {"building": "X-1"}
    prims = [mesh["primitives"][0] for mesh in doc["meshes"]]
    assert prims[0]["mode"] == 4 and "_FEATURE_ID" in prims[0]["attributes"]
    assert prims[1]["mode"] == 1
    assert {m["name"] for m in doc["materials"]} == {"mat:wall", "mat:edge"}


def test_pack_alignment():
    data, views = pack({"a": np.arange(3, dtype=np.uint8), "b": np.ones((2, 3), np.float32)})
    assert views["b"].offset % 4 == 0 and views["b"].shape == [2, 3]
    assert len(data) == views["b"].offset + 24


def test_edge_class():
    assert edge_class("footway", False) == "footway"
    assert edge_class("service|footway", False) == "footway"
    assert edge_class("residential", False) == "road"
    assert edge_class("footway", True) == "steps"


# --- end to end on the sample campus + synthetic OSM ----------------------------------


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web")
    bbox = _geo(box(X0 - 100, Y0 - 100, X0 + 400, Y0 + 300))
    layers, issues = build_layers(_features(), _graph(), bbox, pd.DataFrame(), CFG)
    osm_dir = tmp / "processed" / "osm"
    osm_dir.mkdir(parents=True)
    for table in OSM_TABLES:
        table.write(layers[table.layer], osm_dir / "campus.gpkg")
    issues.add("Test section", "D-17 test issue", building_id="D-17")
    write_issues(osm_dir / "issues.json", issues, provenance("test"))

    campus = tmp / "campus"
    shutil.copytree(ROOT / "data" / "sample" / "campus", campus)
    cfg = json.loads(json.dumps(CFG))
    cfg["paths"]["processed"] = str(tmp / "processed")
    out = tmp / "data"
    # a replay published by a later stage shows up in the catalog
    (out / "replays" / "run-1").mkdir(parents=True)
    (out / "replays" / "run-1" / "replay.json").write_text(
        json.dumps(
            {
                "id": "run-1",
                "kind": "aco",
                "title": "MMAS k=5",
                "created_at": "2026-10-09T10:00:00+02:00",
                "files": {"aco_trace": "replays/run-1/trace.json"},
            }
        ),
        encoding="utf-8",
    )
    status = export_campus(cfg, campus_dir=campus, out_dir=out)
    return out, status


def test_export_files_follow_contracts(exported):
    out, status = exported
    assert status.errors == []
    scene = Scene.model_validate_json((out / "scene.json").read_text(encoding="utf-8"))
    assert {b.id for b in scene.buildings} == {"A-0", "B-1", "C-2", "D-17", "DS-7"}
    for b in scene.buildings:
        doc = read_glb_json(out / b.glb)
        assert doc["nodes"][0]["extras"]["building"] == b.id
        level_nodes = [
            n for n in doc["nodes"] if "level" in n.get("extras", {}) and "part" not in n["extras"]
        ]
        assert [n["extras"]["level"] for n in level_nodes] == [lv.id for lv in b.levels]
        info = BuildingInfo.model_validate_json((out / b.info).read_text(encoding="utf-8"))
        assert info.lod == b.lod
        assert b.bbox_max[1] == pytest.approx(b.levels[-1].floor_y + b.levels[-1].height, abs=0.01)
    d17 = next(b for b in scene.buildings if b.id == "D-17")
    assert d17.n_issues >= 1 and any(e.main for e in d17.entrances)
    # the main entrance of D-17 is the corridor start = the anchor
    main = next(e for e in d17.entrances if e.main)
    np.testing.assert_allclose(main.position, d17.frame.anchor, atol=0.01)

    ContextFeatures.model_validate_json((out / "campus/context.json").read_text(encoding="utf-8"))
    net = NetworkHeader.model_validate_json((out / "network.json").read_text(encoding="utf-8"))
    assert net.n_edges == 2 and (out / net.bin).stat().st_size > 0
    IssueList.model_validate_json((out / "issues.json").read_text(encoding="utf-8"))
    cat = ReplayCatalog.model_validate_json(
        (out / "replays/index.json").read_text(encoding="utf-8")
    )
    assert [r.id for r in cat.replays] == ["run-1"]
    st = BuildStatus.model_validate_json((out / "status.json").read_text(encoding="utf-8"))
    assert "scene.json" in st.changed


def test_context_excludes_modelled_buildings(exported):
    out, _ = exported
    ctx = ContextFeatures.model_validate_json(
        (out / "campus/context.json").read_text(encoding="utf-8")
    )
    # synthetic OSM has D-17 (2 parts), A-0, the connector, DS-7 and one apartment block;
    # the sample models D-17, A-0 and DS-7, so the connector and the block stay context
    assert sorted(f.osm_id for f in ctx.features) == ["way/4", "way/6"]


def test_broken_yaml_is_reported(exported, tmp_path):
    out, _ = exported
    campus = tmp_path / "campus"
    shutil.copytree(ROOT / "data" / "sample" / "campus", campus)
    (campus / "buildings" / "C-2.yaml").write_text(
        (campus / "buildings" / "C-2.yaml").read_text(encoding="utf-8") + "bogus_key: 1\n",
        encoding="utf-8",
    )
    cfg = json.loads(json.dumps(CFG))
    cfg["paths"]["processed"] = str(out.parent / "processed")
    status = export_campus(cfg, campus_dir=campus, out_dir=tmp_path / "data")
    assert [e.loc for e in status.errors] == ["bogus_key"]
    scene = Scene.model_validate_json((tmp_path / "data/scene.json").read_text(encoding="utf-8"))
    assert "C-2" not in {b.id for b in scene.buildings}

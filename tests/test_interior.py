"""Phases 2 and 3: interior geometry, YAML error lines, incremental export and the watcher."""

import json
import shutil
import threading
import time

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from metro_agh.campus.osm_process import build_layers
from metro_agh.config import ROOT, load_config
from metro_agh.geometry.building import largest_polygon, place
from metro_agh.geometry.interior import (
    DOOR_W,
    ENTRANCE_W,
    WALL_T,
    interior_meshes,
    plan_levels,
    wall_polygons,
)
from metro_agh.schemas import load_building
from metro_agh.schemas.tables import OSM_TABLES
from metro_agh.schemas.web import BuildingInfo, BuildStatus, Scene
from metro_agh.web.export_campus import CampusExport
from metro_agh.web.gltf import read_glb_json
from metro_agh.web.watch import watch
from metro_agh.web.yaml_errors import line_index, load_with_errors
from test_osm import X0, Y0, _features, _geo, _graph

CFG = load_config()
SAMPLE = ROOT / "data" / "sample" / "campus" / "buildings"


def _placed(bid: str):
    return place(load_building(SAMPLE / f"{bid}.yaml"), CFG, 200.0, None)


def _origin(p):
    return (float(p.frame.anchor[0]), float(p.frame.anchor[1]))


# --- geometry ------------------------------------------------------------------------


def test_d17_spaces_doors_and_gaps():
    plans = {pl.span.id: pl for pl in plan_levels(_placed("D-17"))}
    l0, l1 = plans[0], plans[1]
    assert {(s.id, s.kind) for s in l0.spaces} == {
        ("c0", "corridor"), ("0.10", "room"), ("0.12", "room"), ("0.11", "room"), ("s1", "stairs")
    }  # fmt: skip
    room = next(s for s in l0.spaces if s.id == "0.10")
    assert room.polygon.area == pytest.approx(8 * 7)
    # the door of a box room is in the middle of its corridor side, on the corridor wall
    np.testing.assert_allclose(room.doors[0], [2 + 4, 1.25], atol=1e-6)
    # 3 room doors + the stairwell + 2 entrances on level 0; 1.40 has two doors on level 1
    assert len(l0.gaps) == 6
    assert len(next(s for s in l1.spaces if s.id == "1.40").doors) == 2
    widths = [g.width for g in l0.gaps]
    assert widths.count(DOOR_W) == 3 and widths.count(ENTRANCE_W) == 2
    assert max(widths) == pytest.approx(4 - WALL_T)  # the stairwell is open to the corridor


def test_walls_have_door_gaps_and_lintels():
    pl = next(p for p in plan_levels(_placed("D-17")) if p.span.id == 0)
    low, lintel = wall_polygons(pl)
    # nothing is solid at a door, the lintel above it is
    door = next(s for s in pl.spaces if s.id == "0.10").doors[0]
    assert not low.contains(Point(door))
    assert lintel.buffer(1e-6).contains(Point(door))
    # walls are WALL_T thick: the corridor's wall at y = 1.25 spans 1.15 .. 1.35
    assert low.contains(Point(20, 1.25 + WALL_T / 2 - 0.01))
    assert not low.contains(Point(20, 1.25 + WALL_T / 2 + 0.05))


def test_stairs_climb_one_level_and_open_the_slab():
    p = _placed("D-17")
    plans = plan_levels(p)
    (flight,) = plans[0].flights
    assert flight.stairs_id == "s1" and flight.rise == pytest.approx(3.6)
    assert flight.width == pytest.approx(4) and flight.depth == pytest.approx(6)
    meshes = interior_meshes(p, plans, _origin(p))
    steps = meshes[0].stairs["s1"]
    y = steps.positions[:, 1]
    assert y.max() == pytest.approx(p.ground_y + 3.6, abs=1e-4)  # the top step is level 1's floor
    # level 1 is the top of the stairwell: an opening where the flight arrives
    assert len(plans[1].openings) == 1 and plans[0].openings == []
    slab1 = meshes[1].slab
    tri = slab1.positions[slab1.indices.reshape(-1, 3)].astype(float)
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = 0.5 * np.linalg.norm(cross, axis=1).sum()
    assert area == pytest.approx(40 * 16.5 - plans[1].openings[0].area, rel=1e-3)


def test_a0_basement_and_two_stairwells():
    plans = plan_levels(_placed("A-0"))
    assert [pl.span.id for pl in plans] == [-1, 0, 1]
    assert [f.stairs_id for f in plans[0].flights] == ["s_main"]
    assert sorted(f.stairs_id for f in plans[1].flights) == ["s_east", "s_main"]
    assert plans[2].flights == []


# --- YAML errors ---------------------------------------------------------------------


def test_line_index():
    lines = line_index("a: 1\nlevels:\n  - id: 0\n    rooms:\n      - {id: x, width: 2}\n")
    assert lines[("levels", 0, "rooms", 0, "width")] == 5
    assert lines[("levels", 0, "id")] == 3


def test_errors_carry_line_and_element(tmp_path):
    src = (SAMPLE / "D-17.yaml").read_text(encoding="utf-8")
    f = tmp_path / "D-17.yaml"
    f.write_text(src.replace("width: 8, depth: 7 }", "width: -8, depth: 7 }", 1), encoding="utf-8")
    b, errors = load_with_errors(f, "D-17.yaml")
    assert b is None
    (e,) = errors
    assert e.loc == "levels.0.rooms.0.width" and e.element == "0.10" and e.building_id == "D-17"
    assert src.splitlines()[e.line - 1].lstrip().startswith('- { id: "0.10"')

    # a whole-building check names the room; the error is placed on its line
    f.write_text(
        src.replace("corridor: c1, side: left, at: 4", "corridor: c9, side: left, at: 4"),
        encoding="utf-8",
    )
    _, errors = load_with_errors(f, "D-17.yaml")
    e = next(x for x in errors if "c9" in x.message)
    assert e.element == "1.38" and "1.38" in src.splitlines()[e.line - 1]

    f.write_text(src + "  - {id: broken\n", encoding="utf-8")
    _, (e,) = load_with_errors(f, "D-17.yaml")
    assert e.line is not None and e.loc is None


# --- incremental export and watch ----------------------------------------------------


@pytest.fixture()
def campus(tmp_path):
    bbox = _geo(box(X0 - 100, Y0 - 100, X0 + 400, Y0 + 300))
    layers, _ = build_layers(_features(), _graph(), bbox, pd.DataFrame(), CFG)
    osm_dir = tmp_path / "processed" / "osm"
    osm_dir.mkdir(parents=True)
    for table in OSM_TABLES:
        table.write(layers[table.layer], osm_dir / "campus.gpkg")
    shutil.copytree(ROOT / "data" / "sample" / "campus", tmp_path / "campus")
    cfg = json.loads(json.dumps(CFG))
    cfg["paths"]["processed"] = str(tmp_path / "processed")
    ex = CampusExport(cfg, tmp_path / "campus", tmp_path / "data")
    return ex


def test_interiors_in_glb_and_info(campus):
    campus.full()
    doc = read_glb_json(campus.out_dir / "buildings/D-17.glb")
    spaces = [n["extras"] for n in doc["nodes"] if n.get("extras", {}).get("part") == "space"]
    room = next(x for x in spaces if x["id"] == "1.40")
    assert room == {"part": "space", "kind": "room", "id": "1.40", "level": 1, "capacity": 120}
    parts = {n["extras"]["part"] for n in doc["nodes"] if "part" in n.get("extras", {})}
    assert {"walls", "flight", "slab", "space", "shaft"} <= parts
    info = BuildingInfo.model_validate_json(
        (campus.out_dir / "buildings/D-17.json").read_text(encoding="utf-8")
    )
    assert sum(len(lv.spaces) for lv in info.levels) == 9
    scene = Scene.model_validate_json((campus.out_dir / "scene.json").read_text(encoding="utf-8"))
    d17 = next(b for b in scene.buildings if b.id == "D-17")
    assert sorted(d17.rooms) == ["0.10", "0.11", "0.12", "1.38", "1.40"]


def test_update_rebuilds_one_building_and_keeps_the_last_good(campus):
    campus.full()
    f = campus.campus_dir / "buildings" / "B-1.yaml"
    src = f.read_text(encoding="utf-8")
    f.write_text(src.replace("width: 12, depth: 7.5", "width: 10, depth: 7.5", 1), encoding="utf-8")
    status = campus.update([f])
    assert set(status.changed) == {
        "buildings/B-1.glb", "buildings/B-1.json", "scene.json", "issues.json",
        "replays/index.json", "network.json", "network.bin",  # the indoor graph changed too
    }  # fmt: skip
    assert status.errors == []

    f.write_text(src.replace("id: B-1", "id: B-1\nbogus: 1"), encoding="utf-8")
    status = campus.update([f])
    assert [e.loc for e in status.errors] == ["bogus"]
    scene = Scene.model_validate_json((campus.out_dir / "scene.json").read_text(encoding="utf-8"))
    b1 = next(b for b in scene.buildings if b.id == "B-1")
    assert b1.stale and (campus.out_dir / b1.glb).exists()

    f.unlink()
    campus.update([f])
    scene = Scene.model_validate_json((campus.out_dir / "scene.json").read_text(encoding="utf-8"))
    assert "B-1" not in {b.id for b in scene.buildings}
    assert not (campus.out_dir / "buildings/B-1.glb").exists()


def test_watch_rebuilds_after_a_save(campus):
    t = threading.Thread(target=watch, args=(campus, 0.05, 1), daemon=True)
    t.start()
    status_file = campus.out_dir / "status.json"
    for _ in range(200):  # the full export runs first
        if status_file.exists():
            break
        time.sleep(0.05)
    v0 = BuildStatus.model_validate_json(status_file.read_text(encoding="utf-8")).version
    time.sleep(0.2)
    f = campus.campus_dir / "buildings" / "C-2.yaml"
    f.write_text(
        f.read_text(encoding="utf-8").replace("n_levels: 4", "n_levels: 5"), encoding="utf-8"
    )
    t.join(timeout=20)
    assert not t.is_alive()
    status = BuildStatus.model_validate_json(status_file.read_text(encoding="utf-8"))
    assert status.version == v0 + 1 and "buildings/C-2.glb" in status.changed
    assert "campus/context.glb" not in status.changed


def test_crossing_corridor_keeps_both_arms(tmp_path):
    src = (SAMPLE / "D-17.yaml").read_text(encoding="utf-8")
    cross = "      - id: cx\n        path: [[20, -6], [20, 6]]\n        width: 2.0\n"
    old = "        width: 2.5\n    rooms:"
    assert old in src
    src = src.replace(old, "        width: 2.5\n" + cross + "    rooms:", 1)
    f = tmp_path / "D-17.yaml"
    f.write_text(src, encoding="utf-8")
    p = place(load_building(f), CFG, 200.0, None)
    l0 = next(pl for pl in plan_levels(p) if pl.span.id == 0)
    cx = next(s for s in l0.spaces if s.id == "cx")
    assert cx.polygon.area == pytest.approx(12 * 2.0, rel=0.05)  # both arms, not one
    assert cx.polygon.bounds[1] < -5 and cx.polygon.bounds[3] > 5


def test_invalid_footprint_keeps_its_largest_part():
    import shapely
    from shapely.geometry import Polygon

    # a bow-tie with a spike: make_valid nests the MultiPolygon in a GeometryCollection
    spiky = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (-5, 5), (-10, 5), (-5, 5)])
    fixed = shapely.make_valid(spiky)
    assert fixed.geom_type == "GeometryCollection"
    assert largest_polygon(fixed).area == pytest.approx(50)

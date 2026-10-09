"""Data contracts: sample data must conform, invalid input must be rejected."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from metro_agh.schemas import (
    Building,
    Instance,
    InstanceMeta,
    SchemaError,
    load_buildings,
    load_campus,
)
from metro_agh.schemas.export import SCHEMA_DIR, render_all
from metro_agh.schemas.tables import COHORTS, GROUP_COHORTS, GROUPS, LEGS, TIMETABLE
from metro_agh.schemas.web import DayHeader

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


# --- hand-written campus data -------------------------------------------------


def test_sample_buildings_load():
    buildings = load_buildings(SAMPLE / "campus")
    assert {b.lod for b in buildings.values()} == {1, 2, 3}
    assert buildings["D-17"].lod == 3


def test_sample_campus_loads():
    campus = load_campus(SAMPLE / "campus")
    assert len(campus.stops) == 3


def _d17() -> dict:
    return yaml.safe_load((SAMPLE / "campus" / "buildings" / "D-17.yaml").read_text("utf-8"))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["levels"][0].update(colour="red"), "Extra inputs"),
        (lambda d: d["levels"][0]["rooms"][0].update(corridor="nope"), "unknown corridor"),
        (lambda d: d["levels"][0]["rooms"][0].update(at=39), "beyond corridor"),
        (lambda d: d["levels"][1]["rooms"][0].update(id="0.10"), "room ids must be unique"),
        (lambda d: d["levels"][1].pop("stairs"), "appear only on level"),
        (lambda d: d["levels"][1].update(elevation=0.0), "must be higher"),
        (lambda d: d["levels"][0]["rooms"][0].pop("depth"), "give either corridor"),
        (lambda d: d["entrances"][1].update(metro_shaft=True), "at most one"),
        (lambda d: d["entrances"][0].update(at=3), "takes no at"),
        (lambda d: d.update(id="d17"), "id"),
    ],
)
def test_building_rejects(mutate, message):
    data = _d17()
    mutate(data)
    with pytest.raises(ValidationError, match=message):
        Building.model_validate(data)


# --- tables ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "file"),
    [
        (TIMETABLE, "timetable.csv"),
        (GROUPS, "groups.csv"),
        (COHORTS, "cohorts.csv"),
        (GROUP_COHORTS, "group_cohorts.csv"),
    ],
)
def test_sample_usos_tables(table, file):
    df = table.read(SAMPLE / "usos" / file)
    assert len(df) > 0


def test_room_ids_stay_strings():
    df = TIMETABLE.read(SAMPLE / "usos" / "timetable.csv")
    assert "0.10" in set(df["room_id"].dropna())


def test_sample_references_are_consistent():
    buildings = load_buildings(SAMPLE / "campus")
    tt = TIMETABLE.read(SAMPLE / "usos" / "timetable.csv")
    groups = GROUPS.read(SAMPLE / "usos" / "groups.csv")
    rooms = {(b.id, r.id) for b in buildings.values() for lvl in b.levels for r in lvl.rooms}
    assert set(tt["group_id"]) <= set(groups["group_id"])
    assert set(tt["building_id"]) <= set(buildings)
    with_room = tt.dropna(subset=["room_id"])
    assert set(zip(with_room["building_id"], with_room["room_id"], strict=True)) <= rooms


def test_table_rejects_bad_frame():
    df = pd.DataFrame(
        {
            "leg_id": [0, 0],
            "student_id": [1, 2],
            "weekday": [1, 6],
            "seq": [0, 0],
            "kind": ["class_to_class", "teleport"],
            "from_key": ["D-17/1.38", "D-17"],
            "to_key": ["A-0", "stop:miasteczko_studenckie_agh"],
            "earliest_depart_wt": [100, None],
            "deadline_wt": [200, 300],
            "break_s": [100, None],
        }
    )
    with pytest.raises(SchemaError) as err:
        LEGS.validate(df)
    text = str(err.value)
    assert "duplicate rows" in text
    assert "weekday: values above 5" in text
    assert "teleport" in text


# --- instance ----------------------------------------------------------------


def _tiny_instance() -> Instance:
    rng = np.random.default_rng(0)
    n, e, m = 4, 3, 5
    xyz = rng.uniform(0, 500, (n, 3))
    d = np.linalg.norm(xyz[:, None, :2] - xyz[None, :, :2], axis=-1).astype(np.float32)
    return Instance(
        meta=InstanceMeta(
            name="tiny",
            topology="line",
            k=3,
            metro_speed_mps=10,
            dwell_s=30,
            wait_s=90,
            shaft_down_s=40,
            shaft_up_s=50,
        ),
        candidate_ids=np.array(["A-0", "B-1", "C-2", "D-17"]),
        candidate_xyz=xyz,
        tunnel_m=d,
        endpoint_keys=np.array(["A-0", "D-17/1.38", "stop:miasteczko_studenckie_agh"]),
        access_s=rng.uniform(0, 300, (e, n)).astype(np.float32),
        egress_s=rng.uniform(0, 300, (n, e)).astype(np.float32),
        od_from=rng.integers(0, e, m).astype(np.int32),
        od_to=rng.integers(0, e, m).astype(np.int32),
        od_weight=np.ones(m, np.float32),
        od_walk_s=rng.uniform(60, 900, m).astype(np.float32),
    )


def test_instance_roundtrip(tmp_path):
    inst = _tiny_instance()
    inst.save(tmp_path / "instance.npz")
    loaded = Instance.load(tmp_path / "instance.npz")
    assert loaded.meta == inst.meta
    np.testing.assert_array_equal(loaded.candidate_ids, inst.candidate_ids)


def test_instance_rejects_wrong_shape():
    inst = _tiny_instance()
    inst.access_s = inst.access_s.T
    with pytest.raises(ValueError, match="access_s"):
        inst.validate()


# --- web / generated schemas ----------------------------------------------------


def test_binary_header_requires_buffers():
    with pytest.raises(ValidationError, match="missing buffers"):
        DayHeader.model_validate(
            {
                "provenance": {"generated_at": "2026-10-09T12:00:00", "generator": "test"},
                "bin": "day-1.bin",
                "buffers": {"t_start": {"dtype": "float32", "offset": 0, "count": 2, "shape": [2]}},
                "scenario": "metro",
                "weekday": 1,
                "n_students": 2,
                "t_min": 0,
                "t_max": 10,
            }
        )


def test_generated_json_schemas_are_up_to_date():
    stale = [
        rel
        for rel, content in render_all().items()
        if not (SCHEMA_DIR / rel).exists()
        or (SCHEMA_DIR / rel).read_text(encoding="utf-8") != content
    ]
    assert not stale, f"run `uv run python -m metro_agh.schemas.export`; stale: {stale}"

"""Stage 3 on the sample USOS tables: dorm beds, population, legs, OD and migrations."""

import copy

import numpy as np
import pandas as pd
import pytest

from metro_agh.config import ROOT, load_config
from metro_agh.demand.dorms import estimate_dorms
from metro_agh.demand.legs import build_legs, migrations, od_matrix
from metro_agh.demand.population import Homes, modelled_slots, synthesize
from metro_agh.schemas.tables import COHORTS, GROUP_COHORTS, GROUPS, TIMETABLE

SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def usos():
    d = SAMPLE / "usos"
    return (
        TIMETABLE.read(d / "timetable.csv"),
        GROUPS.read(d / "groups.csv"),
        COHORTS.read(d / "cohorts.csv"),
        GROUP_COHORTS.read(d / "group_cohorts.csv"),
    )


@pytest.fixture(scope="module")
def cfg():
    c = copy.deepcopy(load_config())
    c["population"].update(n_students="auto", dorm_share=0.5)
    return c


def homes() -> Homes:
    return Homes(["DS-7"], np.array([100.0]), ["stop:a", "stop:b"], np.array([3.0, 1.0]))


def test_dorm_beds_from_yaml_or_floor_area(cfg, tmp_path):
    d = estimate_dorms(SAMPLE / "campus", cfg)
    assert d.set_index("building_id").loc["DS-7", "residents"] == 400  # given in the YAML
    assert d["source"].tolist() == ["yaml"]

    src = (SAMPLE / "campus" / "buildings" / "DS-7.yaml").read_text(encoding="utf-8")
    src = src.replace("residents: 400\n", "")
    (tmp_path / "buildings").mkdir()
    (tmp_path / "buildings" / "DS-7.yaml").write_text(src, encoding="utf-8")
    big = src.replace("id: DS-7", "id: DS-8").replace("n_levels: 11", "n_levels: 22")
    (tmp_path / "buildings" / "DS-8.yaml").write_text(big, encoding="utf-8")
    c = copy.deepcopy(cfg)
    c["population"]["dorm_beds"] = 900
    d = estimate_dorms(tmp_path, c).set_index("building_id")
    assert d["residents"].sum() == 900
    assert d.loc["DS-8", "residents"] == 2 * d.loc["DS-7", "residents"]  # twice the floors
    assert set(d["source"]) == {"estimate"}

    # the YAML beds already fill dorm_beds: nothing left for the others
    (tmp_path / "buildings" / "DS-7.yaml").write_text(src + "residents: 900\n", encoding="utf-8")
    d = estimate_dorms(tmp_path, c).set_index("building_id")
    assert d["residents"].sum() == 900 and d.loc["DS-8", "residents"] == 0


def test_population_respects_cohorts_and_groups(usos, cfg):
    timetable, groups, cohorts, gc = usos
    slots = modelled_slots(timetable, "odd")
    assert "even" not in set(slots["week_parity"])
    students, enr, _ = synthesize(
        cohorts, gc, groups, slots, homes(), cfg, np.random.default_rng(1)
    )
    assert len(students) == cohorts["n_students"].sum() == 100
    assert students.groupby("cohort_id").size().to_dict() == {"EA-AIR-5": 40, "IS-ISI-3": 60}
    per_group = enr["group_id"].value_counts()
    # compulsory single groups: everybody of the cohort
    assert per_group["ALG:WYK:1"] == 60 and per_group["ROB:WYK:1"] == 40
    # two lab groups of 30: every IS-ISI-3 student in exactly one, sizes about equal
    alg = enr[enr["group_id"].str.startswith("ALG:LAB")]
    assert alg["student_id"].is_unique and len(alg) == 60
    assert abs(per_group["ALG:LAB:1"] - 30) <= 12
    assert per_group["ROB:LAB:1"] + per_group["ROB:LAB:2"] == 40


def test_dean_group_is_consistent(usos, cfg):
    """A student's place q decides the group in every class type with several groups."""
    timetable, groups, cohorts, gc = usos
    slots = modelled_slots(timetable, "odd")
    _, enr, _ = synthesize(cohorts, gc, groups, slots, homes(), cfg, np.random.default_rng(2))
    lab = enr[enr["group_id"].str.startswith("ALG:LAB")].set_index("student_id")["group_id"]
    first, second = lab[lab == "ALG:LAB:1"].index, lab[lab == "ALG:LAB:2"].index
    assert len(first) and len(second)


def test_legs_follow_the_rules(usos, cfg):
    timetable, groups, cohorts, gc = usos
    slots = modelled_slots(timetable, "odd")
    students, enr, _ = synthesize(
        cohorts, gc, groups, slots, homes(), cfg, np.random.default_rng(3)
    )
    legs, _ = build_legs(students, enr, slots, None, cfg)
    assert (legs["from_key"] != legs["to_key"]).all()
    assert (legs["break_s"].dropna() >= 0).all()
    home = students.set_index("student_id")["home_key"]
    for sid, day in legs.groupby(["student_id", "weekday"]):
        day = day.sort_values("seq")
        assert day["kind"].iloc[0] == "home_to_class"
        assert day["kind"].iloc[-1] == "class_to_home"
        assert day["from_key"].iloc[0] == home[sid[0]] == day["to_key"].iloc[-1]
    # an IS-ISI-3 Monday: A-0 lecture 8:00, lab in D-17 9:45, exercises in B-1 11:30
    isi = students.loc[students["cohort_id"] == "IS-ISI-3", "student_id"].iloc[0]
    mon = legs[(legs["student_id"] == isi) & (legs["weekday"] == 1)].sort_values("seq")
    assert list(mon["to_key"])[:3] == ["A-0", "D-17", "B-1"]
    assert mon["break_s"].iloc[1] == 15 * 60

    od = od_matrix(legs)
    assert od["n_legs"].sum() == len(legs)
    flows = migrations(legs)
    assert flows["n_legs"].sum() == len(legs)  # buildings only: no leg stays in a building
    a0_d17 = flows[(flows["from_place"] == "A-0") & (flows["to_place"] == "D-17")]
    assert a0_d17["n_legs"].sum() == 60 and set(a0_d17["hour"]) == {9}


def test_room_endpoints_when_the_graph_has_rooms(usos, cfg):
    timetable, groups, cohorts, gc = usos
    slots = modelled_slots(timetable, "odd")
    students, enr, _ = synthesize(
        cohorts, gc, groups, slots, homes(), cfg, np.random.default_rng(4)
    )
    endpoints = {"A-0", "D-17", "D-17/0.10", "B-1", "C-2", "DS-7", "stop:a", "stop:b"}
    legs, report = build_legs(students, enr, slots, endpoints, cfg)
    keys = set(legs["from_key"]) | set(legs["to_key"])
    assert "D-17/0.10" in keys and "D-17/0.12" not in keys  # unmodelled room -> building
    assert keys <= endpoints
    assert isinstance(report, dict)


def test_long_break_sends_dorm_students_home(cfg):
    slots = pd.DataFrame(
        {
            "group_id": ["G:W:1", "G:W:2"],
            "weekday": [2, 2],
            "start_wt": [86400 + 8 * 3600, 86400 + 15 * 3600],
            "end_wt": [86400 + 9 * 3600 + 1800, 86400 + 16 * 3600 + 1800],
            "building_id": ["A-0", "B-1"],
            "room_id": [None, None],
        }
    )
    students = pd.DataFrame(
        {
            "student_id": [0, 1],
            "cohort_id": ["X", "X"],
            "home_kind": ["dorm", "stop"],
            "home_key": ["DS-7", "stop:a"],
        }
    )
    enr = pd.DataFrame({"student_id": [0, 0, 1, 1], "group_id": ["G:W:1", "G:W:2"] * 2})
    legs, _ = build_legs(students, enr, slots, None, cfg)
    kinds = legs.groupby("student_id")["kind"].apply(list).to_dict()
    assert kinds[0] == ["home_to_class", "class_to_home", "home_to_class", "class_to_home"]
    assert kinds[1] == ["home_to_class", "class_to_class", "class_to_home"]


def test_pooled_course_is_taken_by_existing_students(usos, cfg):
    """A pool course (languages, PE) adds classes to students, never extra students."""
    timetable, groups, cohorts, gc = usos
    gc = pd.concat(
        [
            gc[gc["group_id"] != "MAT:CW:1"],
            pd.DataFrame({"group_id": ["MAT:CW:1"], "cohort_id": ["pool:all"]}),
        ]
    )
    slots = modelled_slots(timetable, "odd")
    students, enr, _ = synthesize(
        cohorts, gc, groups, slots, homes(), cfg, np.random.default_rng(5)
    )
    assert len(students) == 100
    takers = students.set_index("student_id").loc[
        enr.loc[enr["group_id"] == "MAT:CW:1", "student_id"]
    ]
    assert set(takers["cohort_id"]) == {"IS-ISI-3", "EA-AIR-5"}
    assert 40 <= len(takers) <= 80  # 60 registered among 100 students


def test_calendar_week_from_dated_meetings():
    import datetime as dt

    from metro_agh.demand.population import busiest_week, calendar_slots

    meetings = pd.DataFrame(
        {
            "date": ["2026-11-16", "2026-11-18", "2026-11-21", "2026-11-23", "2026-11-17"],
            "start": ["08:00", "09:45", "10:00", "08:00", "12:00"],
            "end": ["09:30", "11:15", "11:30", "09:30", "13:30"],
            "group_id": ["A:W:1", "A:W:1", "A:W:1", "A:W:1", "B:W:1"],
            "building_id": ["D-17", "B-1", "D-17", "D-17", None],  # B:W:1 off campus
            "room_usos_id": ["316", "900", "316", "316", "1"],
        }
    )
    rooms = pd.DataFrame({"room_usos_id": ["316", "900"], "room_id": ["1.38", None]})
    assert busiest_week(meetings) == dt.date(2026, 11, 16)
    slots, monday = calendar_slots(meetings, rooms)
    assert monday == dt.date(2026, 11, 16)
    # Saturday, the next week and the off-campus meeting are not in the week
    assert list(zip(slots["weekday"], slots["start"], strict=True)) == [(1, "08:00"), (3, "09:45")]
    assert slots["room_id"].iloc[0] == "1.38" and pd.isna(slots["room_id"].iloc[1])
    assert list(slots["start_wt"]) == [8 * 3600, 2 * 86400 + 9 * 3600 + 45 * 60]
    other, _ = calendar_slots(meetings, rooms, dt.date(2026, 11, 23))
    assert len(other) == 1


def test_clashing_elective_goes_to_another_student(cfg):
    """An elective whose only group clashes with a compulsory class is taken by a student
    for whom it fits, so its USOS count holds."""
    groups = pd.DataFrame(
        {
            "group_id": ["C:W:1", "E:W:1", "F:W:1"],
            "course_id": ["C", "E", "F"],
            "class_type": ["W", "W", "W"],
            "size": [10, 5, 5],
        }
    )
    slots = pd.DataFrame(
        {
            "group_id": ["C:W:1", "E:W:1", "F:W:1"],
            "start_wt": [8 * 3600, 8 * 3600, 12 * 3600],  # E clashes with C for cohort K1
            "end_wt": [9 * 3600, 9 * 3600, 13 * 3600],
        }
    )
    cohorts = pd.DataFrame(
        {"cohort_id": ["K1", "K2"], "programme": ["P", "P"], "semester": [1, 1],
         "n_students": [10, 10], "size_source": ["usos", "usos"]}
    )  # fmt: skip
    gc = pd.DataFrame(
        {"group_id": ["C:W:1", "E:W:1", "E:W:1", "F:W:1"], "cohort_id": ["K1", "K1", "K2", "K2"]}
    )
    students, enr, report = synthesize(
        cohorts, gc, groups, slots, homes(), cfg, np.random.default_rng(0)
    )
    takers = students.set_index("student_id").loc[enr.loc[enr.group_id == "E:W:1", "student_id"]]
    assert set(takers["cohort_id"]) == {"K2"}  # never a K1 student: it clashes with C
    assert len(takers) == 5  # the seats K1 students drew went to K2 students
    assert enr[enr.group_id == "C:W:1"].shape[0] == 10

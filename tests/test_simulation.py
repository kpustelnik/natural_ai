"""Stage 5 (simulation of every leg) and the simulation replay (--sim, --fake)."""

import json

import numpy as np
import pandas as pd
import pytest

from metro_agh.config import load_config
from metro_agh.schemas.results import BestLine, load_json
from metro_agh.schemas.tables import LEGS, SIM_LEGS
from metro_agh.schemas.web import DayHeader, PathsHeader, Replay, Stats
from metro_agh.simulation.schedule import build_schedule, hhmm
from metro_agh.simulation.simulate import Line, simulate
from metro_agh.web.export_metro import load_scene
from metro_agh.web.export_sim import export_simulation
from metro_agh.web.fake import write_fake_results, write_fake_simulation
from test_web_export import exported  # noqa: F401  (fixture: the sample campus export)

CFG = load_config()


def _graph():
    """A-0 ... 1 km ... B-1 with a shaft at both, and C-2 50 m from A-0."""
    nodes = pd.DataFrame(
        [
            (0, "A-0", "place", 0.0, 0.0, 200.0, "A-0", 0, "A-0"),
            (1, "osm:1", "osm", 500.0, 0.0, 200.0, None, None, None),
            (2, "B-1", "place", 1000.0, 0.0, 200.0, "B-1", 0, "B-1"),
            (3, "A-0:platform", "platform", 0.0, 0.0, 185.0, "A-0", None, None),
            (4, "B-1:platform", "platform", 1000.0, 0.0, 185.0, "B-1", None, None),
            (5, "C-2", "place", 0.0, 50.0, 200.0, "C-2", 0, "C-2"),
        ],
        columns=["node_id", "key", "kind", "x", "y", "z", "building_id", "level", "endpoint_key"],
    )
    walk = 500 / 1.3
    edges = pd.DataFrame(
        [
            (0, 1, "outdoor", 500.0, walk, walk, "way/1"),
            (1, 2, "outdoor", 500.0, walk, walk, "way/1"),
            (0, 3, "shaft", 15.0, 40.0, 35.0, "A-0"),  # down 40 s, up 35 s
            (2, 4, "shaft", 15.0, 40.0, 35.0, "B-1"),
            (0, 5, "outdoor", 50.0, 50 / 1.3, 50 / 1.3, "way/2"),
        ],
        columns=["u", "v", "kind", "length_m", "time_uv_s", "time_vu_s", "source"],
    )
    return nodes, edges


def _legs():
    rows = [  # leg, student, day, seq, kind, from, to, earliest, deadline
        (0, 0, 1, 0, "class_to_class", "A-0", "B-1", hhmm("09:30"), hhmm("09:45")),
        (1, 1, 1, 0, "home_to_class", "A-0", "B-1", None, hhmm("09:45")),
        (2, 2, 1, 0, "class_to_home", "A-0", "C-2", hhmm("09:30"), None),
    ]
    df = pd.DataFrame(rows, columns=[c for c in LEGS.column_names if c != "break_s"])
    df["break_s"] = df.deadline_wt - df.earliest_depart_wt
    for c in ("earliest_depart_wt", "deadline_wt", "break_s"):
        df[c] = df[c].astype("Int64")
    LEGS.validate(df[LEGS.column_names])
    return df[LEGS.column_names]


@pytest.fixture(scope="module")
def simulated():
    nodes, edges = _graph()
    schedule = build_schedule(["A-0", "B-1"], np.array([[0, 0], [1000, 0]]), "line", CFG, [1])
    out = simulate(nodes, edges, _legs(), Line(["A-0", "B-1"], "line", schedule), CFG)
    return out, schedule


def test_no_metro_walks_every_leg(simulated):
    out, _ = simulated
    nm = out["no_metro"].set_index("leg_id")
    SIM_LEGS.validate(out["no_metro"])
    assert (nm["mode"] == "walk").all()
    assert nm.walk_s[0] == pytest.approx(1000 / 1.3, abs=0.1)
    assert list(nm.path_nodes[0]) == [0, 1, 2]
    # home_to_class arrives exactly at the deadline minus the buffer
    buffer = CFG["demand"]["arrival_buffer_s"]
    assert nm.arrive_wt[1] == pytest.approx(hhmm("09:45") - buffer, abs=1)


def test_metro_when_it_is_earlier(simulated):
    out, schedule = simulated
    m = out["metro"].set_index("leg_id")
    nm = out["no_metro"].set_index("leg_id")
    speed, headway = CFG["metro"]["speed_mps"], CFG["metro"]["headway_s"]
    # leg 0: shaft down 40 s, wait for a train, 100 s ride, shaft up 35 s: beats 769 s
    assert m["mode"][0] == "metro" and m.board_station[0] == "A-0" and m.alight_station[0] == "B-1"
    assert m.walk_s[0] == pytest.approx(75, abs=0.1)
    assert m.ride_s[0] == pytest.approx(1000 / speed, abs=1)
    assert 0 <= m.wait_s[0] <= headway
    assert m.arrive_wt[0] < nm.arrive_wt[0]
    # the ride is platform -> platform inside the walked nodes
    assert list(m.path_nodes[0]) == [0, 3, 4, 2]
    # the train left A-0 at a departure of the timetable (walk in: the 40 s shaft)
    deps = schedule[(schedule.station == "A-0") & (schedule.direction == 1)].depart_wt
    assert np.min(np.abs(deps - (m.depart_wt[0] + 40 + m.wait_s[0]))) <= 1
    # leg 1 (to class): leaves later than walking would, still on time
    assert m["mode"][1] == "metro" and m.depart_wt[1] > nm.depart_wt[1]
    assert m.late_s[1] == 0
    # leg 2: 50 m, walking wins
    assert m["mode"][2] == "walk"


def test_unknown_endpoint_is_an_error():
    nodes, edges = _graph()
    legs = _legs()
    legs.loc[0, "to_key"] = "Z-9"
    with pytest.raises(ValueError, match="Z-9"):
        simulate(nodes, edges, legs, None, CFG)


# --- the synthetic week on the sample campus, exported as a replay --------------------


@pytest.fixture(scope="module")
def sim_replay(exported, tmp_path_factory):  # noqa: F811
    out, _ = exported
    tmp = out.parent
    cfg = json.loads(json.dumps(CFG))
    cfg["paths"]["processed"] = str(tmp / "processed")
    cfg["population"]["n_students"] = 400
    root = tmp_path_factory.mktemp("fake-sim")
    scene = load_scene(out)
    write_fake_results(scene, cfg, root, seed=5)
    write_fake_simulation(scene, cfg, tmp / "campus", root, seed=5)
    changed: list[str] = []
    replay = export_simulation(cfg, root, root / "results" / "best_line.json", out, changed)
    return out, root, replay, changed


def test_sim_replay_files(sim_replay):
    out, root, replay, changed = sim_replay
    line = load_json(BestLine, root / "results" / "best_line.json")
    assert replay.kind == "simulation" and replay.stations == line.stations
    assert set(replay.scenarios) == {"no_metro", "metro"}
    Replay.model_validate(json.loads((out / f"replays/{replay.id}/replay.json").read_text("utf-8")))
    for sc, d in replay.files.trips.items():
        ph = PathsHeader.model_validate_json((out / d / "paths.json").read_text("utf-8"))
        assert ph.scenario == sc and ph.buffers["mode"].count == ph.n_paths
        assert ph.buffers["path_offsets"].count == ph.n_paths + 1
        sim = SIM_LEGS.read(root / SIM_LEGS.path.format(scenario=sc))
        n_metro = int((sim["mode"] == "metro").sum())
        rows = 0
        for day in replay.weekdays:
            dh = DayHeader.model_validate_json((out / d / f"day-{day}.json").read_text("utf-8"))
            assert dh.weekday == day and f"{d}/day-{day}.bin" in changed
            raw = (out / d / dh.bin).read_bytes()
            v = dh.buffers["t_start"]
            t = np.frombuffer(raw, np.float32, v.count, v.offset)
            assert (np.diff(t) >= 0).all()  # sorted by start
            rows += v.count
        assert rows == len(sim) + 2 * n_metro  # a metro leg is three segments
        if sc == "no_metro":
            assert n_metro == 0


def test_sim_stats(sim_replay):
    out, root, replay, _ = sim_replay
    st = Stats.model_validate_json((out / replay.files.stats).read_text("utf-8"))
    nm, m = st.scenarios["no_metro"], st.scenarios["metro"]
    assert nm.n_legs == m.n_legs > 0
    assert st.saving_s == pytest.approx(nm.total_travel_s - m.total_travel_s, abs=1)
    assert m.total_travel_s <= nm.total_travel_s  # the metro is only taken when faster
    assert sum(h.n_legs for h in st.per_hour) == nm.n_legs
    sim = SIM_LEGS.read(root / SIM_LEGS.path.format(scenario="metro"))
    assert sum(s.boardings for s in st.stations) == int((sim["mode"] == "metro").sum())
    assert all(o.saving_s > 0 for o in st.top_od)


def test_buses_are_part_of_both_scenarios():
    """A bus between stops next to A-0 and B-1 beats the 13-minute walk: the no-metro
    scenario takes it, so the metro is compared with walking *or* public transport."""
    from metro_agh.simulation.simulate import Transit

    nodes, edges = _graph()
    stops = pd.DataFrame(
        [
            (6, "stop:a", "stop", 0.0, -20.0, 200.0, None, None, "stop:a"),
            (7, "stop:b", "stop", 1000.0, -20.0, 200.0, None, None, "stop:b"),
        ],
        columns=nodes.columns,
    )
    nodes = pd.concat([nodes, stops], ignore_index=True)
    links = pd.DataFrame(
        [
            (0, 6, "link", 20.0, 20 / 1.3, 20 / 1.3, None),
            (2, 7, "link", 20.0, 20 / 1.3, 20 / 1.3, None),
        ],
        columns=edges.columns,
    )
    edges = pd.concat([edges, links], ignore_index=True)
    trips = pd.DataFrame(
        {"from_stop": ["stop:a"], "to_stop": ["stop:b"], "line": ["164"],
         "dep_s": [hhmm("09:31")], "arr_s": [hhmm("09:33")]}
    )  # fmt: skip
    schedule = build_schedule(["A-0", "B-1"], np.array([[0, 0], [1000, 0]]), "line", CFG, [1])
    out = simulate(
        nodes, edges, _legs(), Line(["A-0", "B-1"], "line", schedule), CFG,
        transit=Transit(["stop:a", "stop:b"], trips),
    )  # fmt: skip
    nm = out["no_metro"].set_index("leg_id")
    SIM_LEGS.validate(out["no_metro"])
    assert nm.loc[0, "mode"] == "transit"
    assert (nm.loc[0, "board_station"], nm.loc[0, "alight_station"]) == ("stop:a", "stop:b")
    assert nm.loc[0, "ride_s"] == 120
    assert nm.loc[0, "arrive_wt"] == pytest.approx(hhmm("09:33") + 20 / 1.3, abs=1)
    path = list(nm.loc[0, "path_nodes"])
    assert path[0] == 0 and path[-1] == 2 and path[path.index(6) : path.index(6) + 2] == [6, 7]
    assert nm.loc[2, "mode"] == "walk"  # A-0 -> C-2: no bus there
    # the metro scenario keeps the bus where the train is not faster
    m = out["metro"].set_index("leg_id")
    assert m.loc[0, "arrive_wt"] <= nm.loc[0, "arrive_wt"]

"""Walk graph (stage 2b): indoor graphs of the sample buildings joined to a synthetic OSM."""

import math

import numpy as np
import pandas as pd
import pytest
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import box

from metro_agh.campus.osm_process import build_layers
from metro_agh.config import ROOT, load_config
from metro_agh.network.graph import build_campus_graph
from metro_agh.schemas.tables import GRAPH_EDGES, GRAPH_NODES
from test_osm import X0, Y0, _features, _geo, _graph

CFG = load_config()
SAMPLE = ROOT / "data" / "sample" / "campus"


@pytest.fixture(scope="module")
def graph():
    bbox = _geo(box(X0 - 100, Y0 - 100, X0 + 400, Y0 + 300))
    layers, _ = build_layers(_features(), _graph(), bbox, pd.DataFrame(), CFG)
    return build_campus_graph(CFG, SAMPLE, layers)


def _route(graph, a: str, b: str) -> tuple[float, list[str]]:
    nodes, edges = graph.nodes, graph.edges
    n = len(nodes)
    u, v = edges.u.to_numpy(), edges.v.to_numpy()
    w = np.r_[edges.time_uv_s, edges.time_vu_s] + 1e-9
    m = coo_matrix((w, (np.r_[u, v], np.r_[v, u])), shape=(n, n)).tocsr()
    keys = nodes.key.tolist()
    s, t = keys.index(a), keys.index(b)
    dist, pred = dijkstra(m, indices=s, return_predecessors=True)
    path = [t]
    while path[-1] != s:
        path.append(pred[path[-1]])
    return float(dist[t]), [keys[i] for i in reversed(path)]


def test_graph_follows_the_contract(graph):
    GRAPH_NODES.validate(graph.nodes)
    GRAPH_EDGES.validate(graph.edges)
    assert len(graph.edge_class) == len(graph.edges) == len(graph.edge_geometry)
    pairs = {tuple(sorted(p)) for p in graph.edges[["u", "v"]].itertuples(index=False)}
    assert len(pairs) == len(graph.edges)  # one edge per node pair


def test_keys_and_endpoints(graph):
    keys = set(graph.nodes.key)
    for key in [
        "D-17/1.38",
        "D-17/1.40#1",
        "D-17/1.40#2",
        "D-17:c0@0.00",
        "D-17:s1:L0",
        "D-17:s1:L1",
        "D-17:main:in",
        "D-17:main:out",
        "D-17:shaft",
        "D-17:platform",
        "A-0:s_main:L-1",
        "C-2",  # LOD1 place
        "stop:czarnowiejska",
    ]:
        assert key in keys, key
    ends = graph.nodes.dropna(subset=["endpoint_key"]).set_index("endpoint_key").key
    assert ends["D-17"] == "D-17:main:in"  # a LOD3 building resolves to its main entrance
    assert ends["C-2"] == "C-2"
    assert ends["D-17/1.38"] == "D-17/1.38"


def test_stairs_and_shaft_are_slower_up(graph):
    n = graph.nodes.set_index("key").node_id
    e = graph.edges
    stairs = e[(e.u == n["D-17:s1:L0"]) & (e.v == n["D-17:s1:L1"])].iloc[0]
    tm = CFG["time_model"]
    assert stairs.time_uv_s == pytest.approx(3.6 / tm["stairs_up_mps"])
    assert stairs.time_vu_s == pytest.approx(3.6 / tm["stairs_down_mps"])
    shaft = e[(e.u == n["D-17:shaft"]) & (e.v == n["D-17:platform"])].iloc[0]
    depth = CFG["metro"]["station_depth_m"]
    assert shaft.time_uv_s == pytest.approx(depth / tm["stairs_down_mps"])  # going down
    assert shaft.time_uv_s < shaft.time_vu_s


def test_route_inside_d17(graph):
    """Main entrance -> 1.38: 32 m of c0, stairs up, 23 m of c1, door. Checked by hand."""
    t, path = _route(graph, "D-17:main:in", "D-17/1.38")
    assert "D-17:s1:L1" in path
    nodes = graph.nodes.set_index("key")
    room, door = nodes.loc["D-17/1.38"], nodes.loc["D-17/1.38#1"]
    walk = 32 + 1.25 + 1.25 + 23 + 1.25 + math.dist((room.x, room.y), (door.x, door.y))
    tm = CFG["time_model"]
    expect = walk / tm["walk_speed_mps"] + 3.6 / tm["stairs_up_mps"] + tm["door_s"]
    assert t == pytest.approx(expect, abs=0.05)


def test_passage_joins_a0_and_b1(graph):
    _, path = _route(graph, "A-0:c0@70.00", "B-1/0.17")
    assert path[1] == "B-1:c0@30.00"  # straight through the passage, not outside


def test_every_endpoint_is_reachable_from_a_stop(graph):
    ends = graph.nodes.endpoint_key.dropna().tolist()
    for key in ends:
        t, _ = _route(
            graph, "stop:czarnowiejska", graph.nodes.key[graph.nodes.endpoint_key == key].iloc[0]
        )
        assert np.isfinite(t), key

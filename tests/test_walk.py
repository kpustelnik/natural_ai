"""ACO level 1 (``metro_agh.walk.assign``) on a toy graph with two routes."""

import copy

import numpy as np
import pandas as pd

from metro_agh.config import load_config
from metro_agh.walk.assign import (
    PeakDemand,
    aon,
    build_net,
    edge_flow,
    free_flow_total,
    run_msa,
    run_walk_aco,
)

# 0 -> 1 -> 3 (short, narrow footway) and 0 -> 2 -> 3 (20 % longer, also a footway)
NODES = pd.DataFrame({"node_id": range(4), "key": [f"osm:{i}" for i in range(4)]})
EDGES = pd.DataFrame(
    {
        "u": [0, 1, 0, 2],
        "v": [1, 3, 2, 3],
        "kind": ["outdoor"] * 4,
        "length_m": [65.0, 65.0, 78.0, 78.0],
        "time_uv_s": [50.0, 50.0, 60.0, 60.0],
        "time_vu_s": [50.0, 50.0, 60.0, 60.0],
        "source": ["way/1", "way/1", "way/2", "way/2"],
    }
)


def _setup(people: float = 1500.0):
    cfg = copy.deepcopy(load_config())
    cfg["walk_aco"].update(n_iterations=30, n_ants=10)
    net = build_net(NODES, EDGES, cfg, {"1": "footway", "2": "footway"})
    demand = PeakDemand(
        origin=np.array([0], np.int32),
        dest=np.array([3], np.int32),
        n=np.array([people]),
        dest_nodes=np.array([3], np.int32),
        dest_index=np.array([0], np.int32),
        n_legs=int(people),
    )
    return cfg, net, demand


def test_aon_puts_everybody_on_the_short_route():
    cfg, net, demand = _setup()
    a = aon(net, demand, cfg)
    flow = edge_flow(a.x_arc)
    assert flow[0] == flow[1] == 1500 and flow[2] == flow[3] == 0
    assert free_flow_total(net, demand) == 1500 * 100


def test_congestion_spreads_people_over_both_routes():
    cfg, net, demand = _setup()
    a = aon(net, demand, cfg)
    msa = run_msa(net, demand, cfg)
    aco = run_walk_aco(net, demand, cfg, seed=1)
    for r in (msa, aco):
        flow = edge_flow(r.x_arc)
        assert flow[2] > 100  # the longer route is used once the short one is crowded
        assert abs(flow[0] + flow[2] - 1500) < 1e-6  # nobody is lost
        assert r.total_s < a.total_s
    assert msa.gap < 0.05  # MSA approaches equilibrium slowly with step 1 / n


def test_no_congestion_no_spread():
    cfg, net, demand = _setup(people=10.0)
    aco = run_walk_aco(net, demand, cfg, seed=1, trace=True)
    flow = edge_flow(aco.x_arc)
    assert flow[0] > 9  # the 10 s detour is not worth it at free flow (mostly)
    assert aco.trace is not None and len(aco.trace["iterations"]) > 1

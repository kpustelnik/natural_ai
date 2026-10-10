"""MMAS finds a sensible line on a tiny hand-made instance."""

import numpy as np

from metro_agh.aco import Objective, run_mmas
from metro_agh.schemas.instance import Instance, InstanceMeta


def _toy_instance() -> Instance:
    # 4 candidates on a line; demand only between ends A↔D → metro should include A and D
    ids = np.array(["A", "B", "C", "D"], dtype=object)
    xyz = np.array([[0, 0, 0], [400, 0, 0], [800, 0, 0], [1200, 0, 0]], float)
    tunnel = np.array(
        [
            [0, 400, 800, 1200],
            [400, 0, 400, 800],
            [800, 400, 0, 400],
            [1200, 800, 400, 0],
        ],
        np.float32,
    )
    # endpoints = candidates; walk only to own shaft (others unreachable by access)
    access = np.full((4, 4), np.inf, np.float32)
    np.fill_diagonal(access, 0.0)
    egress = access.copy()
    walk = np.array([900, 900], np.float32)  # A→D and D→A
    return Instance(
        meta=InstanceMeta(
            name="toy",
            topology="line",
            k=3,
            metro_speed_mps=10.0,
            dwell_s=30.0,
            wait_s=90.0,
            shaft_down_s=40.0,
            shaft_up_s=35.0,
        ),
        candidate_ids=ids,
        candidate_xyz=xyz,
        tunnel_m=tunnel,
        endpoint_keys=ids,
        access_s=access,
        egress_s=egress,
        od_from=np.array([0, 3], np.int32),
        od_to=np.array([3, 0], np.int32),
        od_weight=np.array([100.0, 100.0], np.float32),
        od_walk_s=walk,
    )


def test_objective_baseline_and_metro_helps():
    inst = _toy_instance()
    f = Objective(inst)
    assert f.baseline == 100 * 900 * 2
    # any 3-station line covering A and D beats walking
    cost = f([0, 1, 3])
    assert cost < f.baseline


def test_mmas_improves_on_baseline():
    inst = _toy_instance()
    cfg = {
        "seed": 0,
        "aco": {
            "variant": "mmas",
            "n_ants": 10,
            "n_iterations": 20,
            "alpha": 1.0,
            "beta": 2.0,
            "rho": 0.1,
            "tau_min_ratio": 0.01,
            "trace": {"every": 5, "max_ants": 10},
        },
    }
    result = run_mmas(inst, cfg, rng=np.random.default_rng(0))
    assert result.best_cost < result.objective.baseline
    assert len(result.best_line) == 3
    assert len(set(result.best_line)) == 3
    assert 0 in result.best_line and 3 in result.best_line  # ends of the corridor
    assert len(result.convergence) == 20
    result.trace.validate()

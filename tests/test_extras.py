"""Additions on top of the optimiser: compiled objective, batches, tunnel, heuristic variants,
and the statistics of ``metro_agh.stats`` (docs/roadmap.md P1)."""

import math

import numpy as np
import pytest

from metro_agh.aco import Objective, run_mmas
from metro_agh.aco.common import HEURISTICS, heuristic
from metro_agh.aco.objective import objective_for
from metro_agh.baselines.brute_force import all_lines
from metro_agh.schemas.instance import Instance, InstanceMeta
from metro_agh.stats import a12, effect, holm, rank_sum


def _campus(n: int = 9, e: int = 14, m: int = 40, k: int = 4, seed: int = 0,
            topology: str = "line") -> Instance:  # fmt: skip
    """n candidates and e endpoints scattered over 1.5 km, walking at 1.3 m/s."""
    rng = np.random.default_rng(seed)
    cand, ends = rng.uniform(0, 1500, (n, 2)), rng.uniform(0, 1500, (e, 2))
    walk = 1.25 * np.linalg.norm(ends[:, None] - cand[None], axis=2) / 1.3
    pairs = sorted({(int(a), int(b)) for a, b in rng.integers(0, e, (4 * m, 2)) if a != b})[:m]
    od = np.array(pairs, np.int32)
    return Instance(
        meta=InstanceMeta(name="random", topology=topology, k=k, metro_speed_mps=10.0,
                          dwell_s=30.0, wait_s=90.0, shaft_down_s=40.0, shaft_up_s=35.0),
        candidate_ids=np.array([f"C{i}" for i in range(n)], dtype=object),
        candidate_xyz=np.column_stack([cand, np.zeros(n)]),
        tunnel_m=np.linalg.norm(cand[:, None] - cand[None], axis=2).astype(np.float32),
        endpoint_keys=np.array([f"E{i}" for i in range(e)], dtype=object),
        access_s=walk.astype(np.float32),
        egress_s=walk.T.copy().astype(np.float32),
        od_from=od[:, 0].copy(),
        od_to=od[:, 1].copy(),
        od_weight=rng.integers(5, 200, len(od)).astype(np.float32),
        od_walk_s=(1.25 * np.linalg.norm(ends[od[:, 0]] - ends[od[:, 1]], axis=1) / 1.3)
        .astype(np.float32),
    )  # fmt: skip


@pytest.mark.parametrize("topology", ["line", "loop"])
def test_compiled_objective_equals_the_numpy_reference(topology):
    inst = _campus(topology=topology)
    f = Objective(inst)
    lines = list(all_lines(9, 4, topology))[:200]
    ref = np.array([f.travel_numpy(ln) for ln in lines])
    single = np.array([f(ln) for ln in lines])
    batch = Objective(inst).many(np.array(lines))
    np.testing.assert_allclose(single, ref, rtol=1e-12)
    np.testing.assert_allclose(batch, ref, rtol=1e-12)
    assert f.evaluations == len(lines)


def test_tunnel_length_and_penalty():
    inst = _campus(k=3)
    f = Objective(inst)
    line = [0, 4, 7]
    assert f.tunnel_m(line) == pytest.approx(inst.tunnel_m[0, 4] + inst.tunnel_m[4, 7])
    loop = Objective(_campus(k=3, topology="loop"))
    assert loop.tunnel_m(line) == pytest.approx(f.tunnel_m(line) + inst.tunnel_m[7, 0])
    taxed = objective_for(inst, {"metro": {"tunnel_penalty_per_km": 0.1}})
    extra = 0.1 * f.baseline * f.tunnel_m(line) / 1000
    assert taxed(line) == pytest.approx(f(line) + extra)
    assert taxed.travel(line) == pytest.approx(f(line))
    assert objective_for(inst, {})(line) == f(line)  # default: no penalty


def test_default_heuristic_is_unchanged_and_variants_work():
    inst = _campus()
    d0, e0 = heuristic(inst)
    d1, e1 = heuristic(inst, "demand_distance")
    np.testing.assert_array_equal(d0, d1)
    np.testing.assert_array_equal(e0, e1)
    for kind in HEURISTICS:
        start, eta = heuristic(inst, kind)
        assert start.shape == (9,) and eta.shape == (9, 9)
        assert (np.diag(eta) == 0).all() and (start > 0).all()
    with pytest.raises(ValueError, match="aco.heuristic"):
        heuristic(inst, "magic")
    cfg = {"seed": 0, "optimize": {"local_search": False},
           "aco": {"n_ants": 10, "n_iterations": 10, "alpha": 1.0, "beta": 1.0, "rho": 0.1,
                   "tau_min_ratio": 0.01, "heuristic": "distance",
                   "trace": {"every": 5, "max_ants": 10}}}  # fmt: skip
    r = run_mmas(inst, cfg, np.random.default_rng(0))
    assert r.params["heuristic"] == "distance"
    assert r.best_cost < r.objective.baseline


def test_statistics():
    assert a12([1, 2, 3], [1, 2, 3]) == 0.5
    assert a12([2, 2], [1, 1]) == 1.0  # higher saving is better
    assert effect(0.5) == "none" and effect(0.8) == "large" and effect(0.6) == "small"
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    adj = holm([math.nan, 0.02])
    assert math.isnan(adj[0]) and adj[1] == pytest.approx(0.02)
    assert math.isnan(rank_sum([1.0], [2.0, 3.0]))  # one run: no test
    assert rank_sum([1.0, 1.0], [1.0, 1.0]) == 1.0
    rng = np.random.default_rng(0)
    assert rank_sum(rng.normal(1, 0.1, 30), rng.normal(0, 0.1, 30)) < 1e-6

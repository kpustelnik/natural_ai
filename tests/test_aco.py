"""MMAS finds a sensible line on a tiny hand-made instance."""

import numpy as np
import pytest

from metro_agh.aco import Objective, run_mmas
from metro_agh.aco.objective import canonical
from metro_agh.baselines.brute_force import all_lines, count_lines
from metro_agh.optimize import ALGORITHMS, run_algorithm
from metro_agh.schemas.instance import Instance, InstanceMeta
from metro_agh.schemas.tables import CONVERGENCE


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


ACO = {
    "n_ants": 10,
    "n_iterations": 20,
    "alpha": 1.0,
    "beta": 2.0,
    "rho": 0.1,
    "tau_min_ratio": 0.01,
    "q0": 0.9,
    "xi": 0.1,
    "trace": {"every": 5, "max_ants": 10},
}


def test_brute_force_counts_every_line_once():
    for topology, n, k in [("line", 6, 3), ("line", 5, 5), ("loop", 6, 4), ("loop", 5, 3)]:
        lines = list(all_lines(n, k, topology))
        assert len(lines) == count_lines(n, k, topology)
        keys = {canonical(line, topology) for line in lines}
        assert len(keys) == len(lines)  # no line twice, reversed or rotated
    assert count_lines(55, 5, "line") > 2e8  # the campus: why brute force has a limit


def test_every_algorithm_on_the_toy_instance():
    inst = _toy_instance()
    cfg = {"seed": 0, "aco": ACO}
    exact = run_algorithm(inst, {**cfg, "optimize": {"algorithm": "brute_force"}}, None)
    assert exact.objective.evaluations == 12  # 4·3·2 / 2
    for name in ALGORITHMS:
        r = run_algorithm(inst, {**cfg, "optimize": {"algorithm": name}}, np.random.default_rng(0))
        assert r.algorithm == name
        assert len(r.best_line) == 3 and len(set(r.best_line)) == 3
        assert r.best_cost == pytest.approx(Objective(inst)(r.best_line))
        assert r.best_cost >= exact.best_cost - 1e-6
        CONVERGENCE.validate(r.convergence)
        assert r.convergence.best_s.iloc[-1] == r.best_cost
        assert (r.trace is not None) == (name in ("mmas", "acs"))
        if r.trace is not None:
            r.trace.validate()
    # four candidates: the colonies and greedy find the optimum
    for name in ("mmas", "acs", "greedy"):
        r = run_algorithm(inst, {**cfg, "optimize": {"algorithm": name}}, np.random.default_rng(0))
        assert r.best_cost == pytest.approx(exact.best_cost)


def test_local_search_and_evaluation_budget():
    from metro_agh.aco.local_search import improve, neighbours

    line = [0, 1, 2]
    moves = neighbours(line, 4)
    assert len(moves) == 3 * 1 + 3 + 3 * 2  # replace, swap, move
    assert all(len(set(m)) == 3 for m in moves)
    inst = _toy_instance()
    f = Objective(inst)
    worst = [1, 2, 0]  # A, the end the demand needs, in the middle
    best, cost = improve(f, worst, f(worst), 4)
    exact = run_algorithm(inst, {"optimize": {"algorithm": "brute_force"}})
    assert cost == pytest.approx(exact.best_cost) and cost < f(worst)

    cfg = {"aco": {**ACO, "n_iterations": 1000}, "optimize": {"max_evaluations": 6}}
    for name in ("mmas", "acs", "random"):
        c = {**cfg, "optimize": {**cfg["optimize"], "algorithm": name, "local_search": True}}
        r = run_algorithm(inst, c, np.random.default_rng(0))
        assert r.eval_budget == 6
        assert r.objective.evaluations <= 6 + 2 * ACO["n_ants"]  # stops after the iteration
        assert len(r.convergence) < 1000
        if r.trace is not None:
            r.trace.validate()
            assert r.trace.iterations[-1] == len(r.convergence) - 1  # the last one sampled


def test_unknown_algorithm_and_brute_force_limit():
    inst = _toy_instance()
    with pytest.raises(ValueError, match="optimize.algorithm"):
        run_algorithm(inst, {"aco": ACO, "optimize": {"algorithm": "tabu"}}, None)
    cfg = {"aco": ACO, "optimize": {"algorithm": "brute_force", "brute_force_max_lines": 5}}
    with pytest.raises(ValueError, match="12 lines"):
        run_algorithm(inst, cfg, None)


def test_loop_ride_takes_one_direction():
    # loop 0-1-2-3-4-0: 0 -> 2 is 1000 m with one stop one way, 10 m with two stops the
    # other way; the distance and the stops must come from the same direction
    xy = np.array([[0, 0], [0, 500], [10, 0], [6, 0], [3, 0]], float)
    inst = _toy_instance()
    inst.meta = inst.meta.model_copy(update={"topology": "loop"})
    inst.tunnel_m = np.linalg.norm(xy[:, None] - xy[None], axis=2)
    ride = Objective(inst).ride([0, 1, 2, 3, 4])
    assert ride[0, 2] == pytest.approx(10 / 10 + 2 * 30)


def test_reversed_line_is_one_evaluation():
    f = Objective(_toy_instance())
    a = f([0, 1, 3])
    assert f([3, 1, 0]) == a
    assert f.evaluations == 1
    assert canonical([2, 0, 1], "loop") == canonical([0, 1, 2], "loop")
    assert canonical([0, 2, 1], "loop") == canonical([1, 2, 0], "loop")  # reflected
    assert canonical([0, 1, 2], "line") != canonical([1, 0, 2], "line")


def test_teleport_bound_is_below_every_line():
    from metro_agh.aco.objective import teleport_bound

    inst = _toy_instance()
    f = Objective(inst)
    bound = teleport_bound(inst)
    assert all(bound <= f(line) + 1e-6 for line in all_lines(4, 3, "line"))
    assert bound <= f.baseline


def test_subset_equals_the_smaller_instance():
    inst = _toy_instance()
    small = inst.subset([0, 3])
    small.validate()
    assert small.meta.k == 2  # at most the candidates kept
    assert list(small.candidate_ids) == ["A", "D"]
    assert small.tunnel_m[0, 1] == 1200
    assert Objective(small)([0, 1]) == pytest.approx(Objective(inst)([0, 3]))

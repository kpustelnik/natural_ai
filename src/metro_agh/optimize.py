"""Stage 4's choice of optimiser: ``optimize.algorithm`` in ``config.yaml``.

Every algorithm takes (instance, config, rng) and returns ``aco.common.RunResult``, so
``04_optimize.py`` and the experiments save and compare them the same way.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .aco.acs import run_acs
from .aco.common import RunResult
from .aco.mmas import run_mmas
from .baselines.brute_force import run_brute_force
from .baselines.greedy import run_greedy
from .baselines.random_search import run_random
from .schemas.instance import Instance

ALGORITHMS: dict[str, Callable[..., RunResult]] = {
    "mmas": run_mmas,
    "acs": run_acs,
    "random": run_random,
    "greedy": run_greedy,
    "brute_force": run_brute_force,
}


def algorithm_of(cfg: dict) -> str:
    name = str(cfg.get("optimize", {}).get("algorithm", "mmas"))
    if name not in ALGORITHMS:
        raise ValueError(f"optimize.algorithm: {name!r}, expected one of {', '.join(ALGORITHMS)}")
    return name


def run_algorithm(inst: Instance, cfg: dict, rng: np.random.Generator | None = None) -> RunResult:
    """Run the configured algorithm on ``inst``."""
    return ALGORITHMS[algorithm_of(cfg)](inst, cfg, rng)

"""Optimisation outputs: the chosen line, per-run metadata and the ant trace.

Run directory: ``experiments/results/<run_id>/``
    run.json          RunMeta
    convergence.csv   tables.CONVERGENCE
    trace.npz         AcoTrace (ACO runs only)
Best line for the rest of the pipeline: ``experiments/results/best_line.json`` (BestLine).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import Field, model_validator

from .common import BuildingId, MetroTopology, Provenance, StrictModel


class BestLine(StrictModel):
    provenance: Provenance
    run_id: str
    topology: MetroTopology
    stations: list[BuildingId] = Field(min_length=2, description="in line order")
    objective_s: float = Field(ge=0, description="weighted total travel time with this line")
    baseline_s: float = Field(ge=0, description="same without metro")
    lower_bound_s: float | None = Field(
        default=None, ge=0, description="teleport bound: every leg takes 0 s via metro access"
    )

    @model_validator(mode="after")
    def _distinct(self) -> "BestLine":
        if len(set(self.stations)) != len(self.stations):
            raise ValueError("stations must be distinct")
        return self


class RunMeta(StrictModel):
    provenance: Provenance
    run_id: str
    experiment: str
    algorithm: str = Field(description="mmas | acs | random | greedy | brute_force")
    instance: str = Field(description="instance path")
    instance_hash: str
    seed: int
    params: dict[str, Any] = Field(description="algorithm parameters actually used")
    eval_budget: int = Field(ge=1)
    evaluations: int = Field(ge=1)
    wall_time_s: float = Field(ge=0)
    best: BestLine


@dataclass
class AcoTrace:
    """Sampled ant tours and pheromone, used both for analysis and the web animation.

    I sampled iterations, A sampled ants per iteration, k stations, N candidates.
    Tours hold candidate indices into ``Instance.candidate_ids``.
    """

    iterations: np.ndarray  # (I,) i32       which iterations were sampled
    tours: np.ndarray  # (I, A, k) i16       station sequence of each sampled ant
    tour_cost_s: np.ndarray  # (I, A) f32    objective of each tour
    best_tour: np.ndarray  # (I, k) i16      best-so-far tour at that iteration
    pheromone: np.ndarray  # (I, N, N) f32   tau after the update of that iteration
    candidate_ids: np.ndarray  # (N,) str

    ARRAYS = ("iterations", "tours", "tour_cost_s", "best_tour", "pheromone", "candidate_ids")

    def validate(self) -> None:
        i, a, k = self.tours.shape
        n = len(self.candidate_ids)
        shapes = {
            "iterations": (i,),
            "tour_cost_s": (i, a),
            "best_tour": (i, k),
            "pheromone": (i, n, n),
        }
        bad = [
            f"{name}: {getattr(self, name).shape} != {shape}"
            for name, shape in shapes.items()
            if getattr(self, name).shape != shape
        ]
        if self.tours.size and (self.tours.min() < 0 or self.tours.max() >= n):
            bad.append("tours contain invalid candidate indices")
        if bad:
            raise ValueError("trace: " + "; ".join(bad))

    def save(self, path: Path) -> None:
        self.validate()
        # unicode, not object dtype — np.load(..., allow_pickle=False) rejects object arrays
        arrays = {name: getattr(self, name) for name in self.ARRAYS}
        arrays["candidate_ids"] = np.asarray(arrays["candidate_ids"], dtype="U64")
        np.savez_compressed(path, **arrays)

    @classmethod
    def load(cls, path: Path) -> "AcoTrace":
        with np.load(path, allow_pickle=False) as z:
            trace = cls(**{name: z[name] for name in cls.ARRAYS})
        trace.candidate_ids = np.asarray(trace.candidate_ids, dtype=object)
        trace.validate()
        return trace


def load_json(model: type[StrictModel], path: Path) -> StrictModel:
    return model.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

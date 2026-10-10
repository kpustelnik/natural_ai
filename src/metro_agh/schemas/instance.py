"""Problem instance: everything ACO and the baselines need, as plain NumPy arrays.

Written by ``network`` (person 2), read by ``aco`` / ``baselines`` (person 3) and by the tests.
File: ``instance/instance.npz`` (and small hand-made ones under ``data/sample``).
No graph, no geometry, no config: an instance file is self-contained.

Shapes: N candidates, E endpoints, M OD pairs.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import Field, PositiveFloat

from .common import SCHEMA_VERSION, MetroTopology, StrictModel


class InstanceMeta(StrictModel):
    schema_version: int = SCHEMA_VERSION
    name: str = Field(description="'campus', 'sample', 'brute12', ...")
    topology: MetroTopology
    k: int = Field(ge=2, description="stations to place")
    metro_speed_mps: PositiveFloat
    dwell_s: float = Field(ge=0, description="stop time at every intermediate station")
    wait_s: float = Field(ge=0, description="expected platform wait (headway / 2)")
    shaft_down_s: float = Field(ge=0, description="shaft top -> platform")
    shaft_up_s: float = Field(ge=0, description="platform -> shaft top")
    source_hash: str | None = Field(default=None, description="hash of graph + demand inputs")


@dataclass
class Instance:
    meta: InstanceMeta
    candidate_ids: np.ndarray  # (N,) str     building ids, index = candidate index
    candidate_xyz: np.ndarray  # (N, 3) f64   shaft top, EPSG:2180 x, y + absolute z
    tunnel_m: np.ndarray  # (N, N) f32        tunnel length between candidates (symmetric)
    endpoint_keys: np.ndarray  # (E,) str     endpoint keys, index = endpoint index
    access_s: np.ndarray  # (E, N) f32        walk endpoint -> shaft top; inf = unreachable
    egress_s: np.ndarray  # (N, E) f32        walk shaft top -> endpoint
    od_from: np.ndarray  # (M,) i32           endpoint index
    od_to: np.ndarray  # (M,) i32             endpoint index
    od_weight: np.ndarray  # (M,) f32         student-legs per week
    od_walk_s: np.ndarray  # (M,) f32         walking time without metro

    ARRAYS = (
        "candidate_ids",
        "candidate_xyz",
        "tunnel_m",
        "endpoint_keys",
        "access_s",
        "egress_s",
        "od_from",
        "od_to",
        "od_weight",
        "od_walk_s",
    )

    @property
    def n_candidates(self) -> int:
        return len(self.candidate_ids)

    def validate(self) -> None:
        n, e, m = len(self.candidate_ids), len(self.endpoint_keys), len(self.od_from)
        expected = {
            "candidate_xyz": ((n, 3), np.floating),
            "tunnel_m": ((n, n), np.floating),
            "access_s": ((e, n), np.floating),
            "egress_s": ((n, e), np.floating),
            "od_from": ((m,), np.integer),
            "od_to": ((m,), np.integer),
            "od_weight": ((m,), np.floating),
            "od_walk_s": ((m,), np.floating),
        }
        problems = []
        for name, (shape, kind) in expected.items():
            arr = getattr(self, name)
            if arr.shape != shape:
                problems.append(f"{name}: shape {arr.shape}, expected {shape}")
            elif not np.issubdtype(arr.dtype, kind):
                problems.append(f"{name}: dtype {arr.dtype}")
        if not problems:
            if not np.allclose(self.tunnel_m, self.tunnel_m.T):
                problems.append("tunnel_m must be symmetric")
            if m and (self.od_from.min() < 0 or max(self.od_from.max(), self.od_to.max()) >= e):
                problems.append("od_from / od_to out of range")
            if (self.od_weight <= 0).any():
                problems.append("od_weight must be positive")
            if not np.isfinite(self.od_walk_s).all():
                problems.append("od_walk_s must be finite (every OD pair walkable)")
            if self.meta.k > n:
                problems.append(f"k={self.meta.k} > N={n}")
        if problems:
            raise ValueError("instance: " + "; ".join(problems))

    def save(self, path: Path) -> None:
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        # unicode, not object dtype — np.load(..., allow_pickle=False) rejects object arrays
        arrays = {name: getattr(self, name) for name in self.ARRAYS}
        for key in ("candidate_ids", "endpoint_keys"):
            arrays[key] = np.asarray(arrays[key], dtype="U64")
        np.savez_compressed(
            path,
            meta_json=np.array(self.meta.model_dump_json()),
            **arrays,
        )

    @classmethod
    def load(cls, path: Path) -> "Instance":
        with np.load(path, allow_pickle=False) as z:
            meta = InstanceMeta.model_validate(json.loads(str(z["meta_json"])))
            inst = cls(meta=meta, **{name: z[name] for name in cls.ARRAYS})
        inst.candidate_ids = np.asarray(inst.candidate_ids, dtype=object)
        inst.endpoint_keys = np.asarray(inst.endpoint_keys, dtype=object)
        inst.validate()
        return inst

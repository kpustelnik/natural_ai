"""demand.json heatmap: OD pairs routed onto walk-graph edges."""

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from metro_agh.schemas.common import Provenance
from metro_agh.schemas.web import BufferView, NetworkHeader
from metro_agh.web.export_demand import edge_loads_from_od


def _header(n_nodes: int, n_edges: int, endpoints: dict[str, int]) -> NetworkHeader:
    empty = BufferView(dtype="uint8", offset=0, count=0, shape=[0])
    return NetworkHeader(
        provenance=Provenance(
            schema_version=1, generated_at="2026-01-01T00:00:00+00:00", generator="test"
        ),
        bin="network.bin",
        buffers={name: empty for name in NetworkHeader.REQUIRED},
        n_nodes=n_nodes,
        n_edges=n_edges,
        node_kind_names=["place"],
        edge_kind_names=["footway"],
        node_keys=[f"n{i}" for i in range(n_nodes)],
        endpoints=endpoints,
        edge_sources=[None] * n_edges,
    )


def test_edge_loads_follow_shortest_path():
    # 0 --1s-- 1 --1s-- 2 ; also 0 --10s-- 2 (longer). OD 0→2 weight 5 uses 0-1-2.
    mat = csr_matrix(
        ([1.0, 1.0, 1.0, 1.0, 10.0, 10.0], ([0, 1, 1, 2, 0, 2], [1, 0, 2, 1, 2, 0])),
        shape=(3, 3),
    )
    edge_of = {(0, 1): 0, (1, 0): 0, (1, 2): 1, (2, 1): 1, (0, 2): 2, (2, 0): 2}
    header = _header(3, 3, {"A": 0, "B": 2})
    od = pd.DataFrame([{"from_key": "A", "to_key": "B", "n_legs": 5}])
    loads = edge_loads_from_od(header, mat, edge_of, od)
    np.testing.assert_array_equal(loads, [5, 5, 0])


def test_unknown_endpoints_are_skipped():
    mat = csr_matrix(([], ([], [])), shape=(2, 2))
    header = _header(2, 0, {"A": 0})
    od = pd.DataFrame([{"from_key": "A", "to_key": "missing", "n_legs": 9}])
    loads = edge_loads_from_od(header, mat, {}, od)
    assert loads.shape == (0,)

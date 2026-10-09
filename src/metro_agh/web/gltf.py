"""Minimal glTF 2.0 binary (.glb) writer.

Just what the viewer contract needs (docs/data_contracts.md, section 10.2): a node tree
with names and ``extras``, one primitive per mesh node (triangles or line segments),
named materials and optional custom float attributes (``_FEATURE_ID``).
"""

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..geometry.mesh import Lines, TriMesh

# Default look; the viewer replaces materials by name, so these only matter in other tools.
MATERIAL_COLORS: dict[str, tuple[float, float, float, float]] = {
    "mat:wall": (0.93, 0.93, 0.92, 1.0),
    "mat:roof": (0.86, 0.86, 0.85, 1.0),
    "mat:slab": (0.80, 0.80, 0.79, 1.0),
    "mat:edge": (0.18, 0.19, 0.21, 1.0),
    "mat:context": (0.78, 0.79, 0.80, 1.0),
    "mat:ground": (0.95, 0.95, 0.95, 1.0),
    "mat:road": (0.86, 0.86, 0.87, 1.0),
    "mat:footway": (0.90, 0.89, 0.87, 1.0),
    "mat:steps": (0.70, 0.69, 0.67, 1.0),
    "mat:boundary": (0.30, 0.30, 0.30, 1.0),
    "mat:fence": (0.45, 0.42, 0.38, 1.0),
}

_TRIANGLES, _LINES = 4, 1
_FLOAT, _UINT16, _UINT32 = 5126, 5123, 5125
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963


@dataclass
class Node:
    name: str
    mesh: TriMesh | Lines | None = None
    material: str | None = None
    children: "list[Node]" = field(default_factory=list)
    extras: dict | None = None
    translation: tuple[float, float, float] | None = None
    attributes: dict[str, np.ndarray] = field(default_factory=dict)  # name -> (n,) float32


class _Builder:
    def __init__(self) -> None:
        self.bin = bytearray()
        self.doc: dict = {
            "asset": {"version": "2.0", "generator": "metro_agh.web.gltf"},
            "scene": 0,
            "scenes": [{"nodes": []}],
            "nodes": [],
            "meshes": [],
            "materials": [],
            "accessors": [],
            "bufferViews": [],
            "buffers": [],
        }
        self.materials: dict[str, int] = {}

    def _view(self, data: bytes, target: int) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        self.doc["bufferViews"].append(
            {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data), "target": target}
        )
        self.bin += data
        return len(self.doc["bufferViews"]) - 1

    def _accessor(self, arr: np.ndarray, target: int, minmax: bool = False) -> int:
        if arr.dtype == np.float32:
            comp = _FLOAT
        elif arr.dtype == np.uint16:
            comp = _UINT16
        else:
            comp = _UINT32
        kind = {1: "SCALAR", 2: "VEC2", 3: "VEC3"}[1 if arr.ndim == 1 else arr.shape[1]]
        acc = {
            "bufferView": self._view(np.ascontiguousarray(arr).tobytes(), target),
            "componentType": comp,
            "count": len(arr),
            "type": kind,
        }
        if minmax:
            acc["min"] = [float(v) for v in np.atleast_1d(arr.min(axis=0))]
            acc["max"] = [float(v) for v in np.atleast_1d(arr.max(axis=0))]
        self.doc["accessors"].append(acc)
        return len(self.doc["accessors"]) - 1

    def _material(self, name: str) -> int:
        if name not in self.materials:
            color = MATERIAL_COLORS.get(name, (0.8, 0.8, 0.8, 1.0))
            self.doc["materials"].append(
                {
                    "name": name,
                    "pbrMetallicRoughness": {
                        "baseColorFactor": list(color),
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.9,
                    },
                }
            )
            self.materials[name] = len(self.doc["materials"]) - 1
        return self.materials[name]

    def _mesh(self, node: Node) -> int | None:
        m = node.mesh
        if m is None or len(m.positions) == 0:
            return None
        pos = np.asarray(m.positions, np.float32)
        attrs = {"POSITION": self._accessor(pos, _ARRAY_BUFFER, minmax=True)}
        prim: dict = {"attributes": attrs}
        if isinstance(m, TriMesh):
            attrs["NORMAL"] = self._accessor(np.asarray(m.normals, np.float32), _ARRAY_BUFFER)
            dtype = np.uint16 if len(pos) < 65536 else np.uint32
            prim["indices"] = self._accessor(m.indices.astype(dtype), _ELEMENT_ARRAY_BUFFER)
            prim["mode"] = _TRIANGLES
        else:
            prim["mode"] = _LINES
        for name, values in node.attributes.items():
            if len(values) != len(pos):
                raise ValueError(f"{node.name}: attribute {name} has {len(values)} values")
            attrs[name] = self._accessor(np.asarray(values, np.float32), _ARRAY_BUFFER)
        if node.material:
            prim["material"] = self._material(node.material)
        self.doc["meshes"].append({"name": node.name, "primitives": [prim]})
        return len(self.doc["meshes"]) - 1

    def add(self, node: Node) -> int:
        entry: dict = {"name": node.name}
        mesh = self._mesh(node)
        if mesh is not None:
            entry["mesh"] = mesh
        if node.extras:
            entry["extras"] = node.extras
        if node.translation is not None:
            entry["translation"] = [float(v) for v in node.translation]
        index = len(self.doc["nodes"])
        self.doc["nodes"].append(entry)
        children = [self.add(c) for c in node.children]
        if children:
            entry["children"] = children
        return index

    def glb(self) -> bytes:
        while len(self.bin) % 4:
            self.bin.append(0)
        self.doc["buffers"] = [{"byteLength": len(self.bin)}]
        doc = {k: v for k, v in self.doc.items() if v != []}
        js = json.dumps(doc, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        return (
            struct.pack("<4sII", b"glTF", 2, total)
            + struct.pack("<I4s", len(js), b"JSON")
            + js
            + struct.pack("<I4s", len(self.bin), b"BIN\x00")
            + bytes(self.bin)
        )


def write_glb(path: Path, roots: list[Node]) -> int:
    """Write the node trees as one scene; returns the file size in bytes."""
    b = _Builder()
    b.doc["scenes"][0]["nodes"] = [b.add(r) for r in roots]
    data = b.glb()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def read_glb_json(path: Path) -> dict:
    """The JSON chunk of a .glb (tests and debugging)."""
    data = Path(path).read_bytes()
    magic, version, _ = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2:
        raise ValueError(f"{path}: not a glTF 2 binary")
    length, kind = struct.unpack_from("<I4s", data, 12)
    if kind != b"JSON":
        raise ValueError(f"{path}: first chunk is not JSON")
    return json.loads(data[20 : 20 + length])

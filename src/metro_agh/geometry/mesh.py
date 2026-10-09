"""Triangle and line soups in the web frame, built from EPSG:2180 polygons.

Everything here takes metric shapes (x = easting, y = northing) plus absolute web heights
and returns arrays in the web frame (x = east, y = up, z = -north). Faces are flat-shaded
(no shared vertices between faces) so normals stay crisp, which suits the clean look.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.polygon import orient

Origin = tuple[float, float]  # EPSG:2180 easting, northing of the web origin


@dataclass
class TriMesh:
    positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float32))
    normals: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float32))
    indices: np.ndarray = field(default_factory=lambda: np.zeros(0, np.uint32))

    @property
    def n_vertices(self) -> int:
        return len(self.positions)

    @property
    def n_triangles(self) -> int:
        return len(self.indices) // 3

    @staticmethod
    def concat(parts: "list[TriMesh]") -> "TriMesh":
        parts = [p for p in parts if p.n_vertices]
        if not parts:
            return TriMesh()
        offsets = np.cumsum([0] + [p.n_vertices for p in parts[:-1]])
        return TriMesh(
            np.concatenate([p.positions for p in parts]).astype(np.float32),
            np.concatenate([p.normals for p in parts]).astype(np.float32),
            np.concatenate([p.indices + o for p, o in zip(parts, offsets, strict=True)]).astype(
                np.uint32
            ),
        )


@dataclass
class Lines:
    """Line segments: ``positions`` is (2n, 3), consecutive pairs are one segment."""

    positions: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float32))

    @staticmethod
    def concat(parts: "list[Lines]") -> "Lines":
        parts = [p for p in parts if len(p.positions)]
        if not parts:
            return Lines()
        return Lines(np.concatenate([p.positions for p in parts]).astype(np.float32))


def web(e: np.ndarray, n: np.ndarray, y, origin: Origin) -> np.ndarray:
    """EPSG:2180 (+ web height) -> web positions (k, 3)."""
    e, n = np.asarray(e, float), np.asarray(n, float)
    y = np.broadcast_to(np.asarray(y, float), e.shape)
    return np.column_stack([e - origin[0], y, -(n - origin[1])]).astype(np.float32)


def polygons(geom) -> list[Polygon]:
    """Polygon parts of any geometry, oriented (exterior counter-clockwise)."""
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [orient(geom, 1.0)]
    if isinstance(geom, MultiPolygon):
        return [orient(p, 1.0) for p in geom.geoms]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in polygons(g)]
    return []


def _fix_winding(positions: np.ndarray, indices: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """Make every triangle counter-clockwise when seen from the side its normal points to."""
    tri = indices.reshape(-1, 3).copy()
    a, b, c = positions[tri[:, 0]], positions[tri[:, 1]], positions[tri[:, 2]]
    face = np.cross(b - a, c - a)
    flip = (face * normals[tri[:, 0]]).sum(axis=1) < 0
    tri[flip, 1], tri[flip, 2] = tri[flip, 2], tri[flip, 1].copy()
    return tri.reshape(-1).astype(np.uint32)


def flat(geom, y: float, origin: Origin, up: bool = True) -> TriMesh:
    """Horizontal faces (slab, roof, ground patch) at web height ``y``."""
    meshes = []
    for poly in polygons(geom):
        tris = shapely.constrained_delaunay_triangles(poly)
        coords = shapely.get_coordinates(tris)  # 4 points per triangle (closed ring)
        if not len(coords):
            continue
        pts = coords.reshape(-1, 4, 2)[:, :3].reshape(-1, 2)
        pos = web(pts[:, 0], pts[:, 1], y, origin)
        nrm = np.tile(np.array([0, 1 if up else -1, 0], np.float32), (len(pos), 1))
        idx = np.arange(len(pos), dtype=np.uint32)
        meshes.append(TriMesh(pos, nrm, _fix_winding(pos, idx, nrm)))
    return TriMesh.concat(meshes)


def _rings(poly: Polygon) -> list[np.ndarray]:
    return [np.asarray(poly.exterior.coords)] + [np.asarray(r.coords) for r in poly.interiors]


def walls(geom, y0: float, y1: float, origin: Origin) -> TriMesh:
    """Vertical faces along every ring of the polygon(s), normals pointing out of the solid."""
    quads_pos, quads_nrm = [], []
    for poly in polygons(geom):
        for ring in _rings(poly):
            p, q = ring[:-1], ring[1:]
            d = q - p
            length = np.hypot(d[:, 0], d[:, 1])
            keep = length > 1e-6
            p, q, d, length = p[keep], q[keep], d[keep], length[keep]
            if not len(p):
                continue
            # oriented polygons have the solid on the left of every ring: outward = right
            out_e, out_n = d[:, 1] / length, -d[:, 0] / length
            corners = [(p, y0), (q, y0), (q, y1), (p, y1)]
            quad = np.stack([web(c[:, 0], c[:, 1], y, origin) for c, y in corners], axis=1)
            nrm = np.column_stack([out_e, np.zeros_like(out_e), -out_n]).astype(np.float32)
            quads_pos.append(quad.reshape(-1, 3))
            quads_nrm.append(np.repeat(nrm, 4, axis=0))
    if not quads_pos:
        return TriMesh()
    pos = np.concatenate(quads_pos)
    nrm = np.concatenate(quads_nrm)
    base = np.arange(0, len(pos), 4, dtype=np.uint32)[:, None]
    idx = (base + np.array([0, 1, 2, 0, 2, 3], np.uint32)).reshape(-1)
    return TriMesh(pos, nrm, _fix_winding(pos, idx, nrm))


def prism(geom, y0: float, y1: float, origin: Origin) -> TriMesh:
    """Closed extrusion without the bottom: walls + top face."""
    return TriMesh.concat([walls(geom, y0, y1, origin), flat(geom, y1, origin)])


def outline(geom, ys: list[float], origin: Origin, corner_deg: float = 20.0) -> Lines:
    """Drawing lines of an extrusion: each ring at every height in ``ys`` and vertical lines
    at corners sharper than ``corner_deg``, from min(ys) to max(ys)."""
    segs = []
    lo, hi = min(ys), max(ys)
    for poly in polygons(geom):
        for ring in _rings(poly):
            p, q = ring[:-1], ring[1:]
            for y in ys:
                a, b = web(p[:, 0], p[:, 1], y, origin), web(q[:, 0], q[:, 1], y, origin)
                segs.append(np.stack([a, b], axis=1).reshape(-1, 3))
            d = q - p
            heading = np.arctan2(d[:, 1], d[:, 0])
            turn = np.abs((heading - np.roll(heading, 1) + math.pi) % (2 * math.pi) - math.pi)
            c = p[np.degrees(turn) > corner_deg]
            if len(c) and hi > lo:
                a, b = web(c[:, 0], c[:, 1], lo, origin), web(c[:, 0], c[:, 1], hi, origin)
                segs.append(np.stack([a, b], axis=1).reshape(-1, 3))
    return Lines(np.concatenate(segs).astype(np.float32)) if segs else Lines()


def polyline(line: LineString, y: float, origin: Origin) -> Lines:
    pts = np.asarray(line.coords)
    a = web(pts[:-1, 0], pts[:-1, 1], y, origin)
    b = web(pts[1:, 0], pts[1:, 1], y, origin)
    return Lines(np.stack([a, b], axis=1).reshape(-1, 3))

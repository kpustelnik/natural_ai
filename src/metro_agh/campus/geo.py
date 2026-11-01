"""Coordinate frames (docs/data_contracts.md, section 2).

- geo:    EPSG:4326 lon/lat
- metric: EPSG:2180 x = easting, y = northing (metres)
- local:  one building; origin at its anchor, +x along bearing_deg, +y to the left
- web:    three.js; x = east, y = up, z = -north, metres from campus.web_origin

Bearings are measured clockwise from EPSG:2180 grid north, which differs from true north
by under 1 degree on the campus.
"""

import math
from dataclasses import dataclass

import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon

from ..schemas.common import GEO_CRS, METRIC_CRS

_TO_METRIC = Transformer.from_crs(GEO_CRS, METRIC_CRS, always_xy=True)
_TO_GEO = Transformer.from_crs(METRIC_CRS, GEO_CRS, always_xy=True)


def to_metric(lon, lat):
    return _TO_METRIC.transform(lon, lat)


def to_geo(x, y):
    return _TO_GEO.transform(x, y)


@dataclass(frozen=True)
class LocalFrame:
    """Building frame. ``anchor`` is in EPSG:2180."""

    anchor: tuple[float, float]
    bearing_deg: float

    @property
    def axes(self) -> tuple[np.ndarray, np.ndarray]:
        b = math.radians(self.bearing_deg)
        ex = np.array([math.sin(b), math.cos(b)])  # +x in (east, north)
        ey = np.array([-math.cos(b), math.sin(b)])  # +y: 90 degrees counter-clockwise
        return ex, ey

    def to_local(self, xy: np.ndarray) -> np.ndarray:
        """(n, 2) EPSG:2180 -> (n, 2) local."""
        ex, ey = self.axes
        d = np.asarray(xy, dtype=float) - np.asarray(self.anchor)
        return np.column_stack([d @ ex, d @ ey])

    def to_metric(self, local: np.ndarray) -> np.ndarray:
        """(n, 2) local -> (n, 2) EPSG:2180."""
        ex, ey = self.axes
        p = np.asarray(local, dtype=float)
        return np.asarray(self.anchor) + np.outer(p[:, 0], ex) + np.outer(p[:, 1], ey)


def long_axis_bearing(poly: Polygon) -> float:
    """Grid bearing in [0, 180) of the longer side of the minimum rotated rectangle."""
    rect = poly.minimum_rotated_rectangle
    pts = np.asarray(rect.exterior.coords)[:4]
    sides = [pts[1] - pts[0], pts[2] - pts[1]]
    dx, dy = max(sides, key=lambda v: float(np.hypot(*v)))
    return math.degrees(math.atan2(dx, dy)) % 180.0

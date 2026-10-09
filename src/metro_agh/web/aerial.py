"""Aerial underlay: the GUGiK orthophoto (Polish open data) of the campus extent.

Fetched once from the WMS in EPSG:2180, so the image is an axis-aligned rectangle in the web
frame, stitched from tiles, cached in ``data/raw/aerial/`` and copied to
``campus/aerial.jpg``. Exports without ``--aerial`` reuse the cached image when there is one.
"""

import hashlib
import io
import logging
import math
import shutil
import time
from pathlib import Path

import requests
from PIL import Image

from ..config import path

log = logging.getLogger(__name__)

WMS_URL = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution"
ATTRIBUTION = "Orthophoto © GUGiK (geoportal.gov.pl)"
M_PER_PX = 0.5
TILE_PX = 2000
JPEG_QUALITY = 82


def _tile(bbox: tuple[float, float, float, float], w: int, h: int, user_agent: str) -> Image.Image:
    params = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.1.1",  # 1.1.1: BBOX is easting, northing (1.3.0 swaps the axes)
        "LAYERS": "Raster",
        "STYLES": "",
        "SRS": "EPSG:2180",
        "BBOX": ",".join(f"{v:.2f}" for v in bbox),
        "WIDTH": str(w),
        "HEIGHT": str(h),
        "FORMAT": "image/jpeg",
    }
    for attempt in range(4):
        try:
            # the WMS answers 404 to some agents (also a bare project name)
            headers = {"User-Agent": f"Mozilla/5.0 (compatible; {user_agent})"}
            r = requests.get(WMS_URL, params=params, timeout=120, headers=headers)
            if r.ok and r.headers.get("content-type", "").startswith("image/"):
                return Image.open(io.BytesIO(r.content)).convert("RGB")
            log.warning("WMS answered %s %s", r.status_code, r.text[:200])
        except requests.RequestException as err:
            log.warning("WMS request failed: %s", err)
        time.sleep(2 + 3 * attempt)
    raise RuntimeError("could not fetch the orthophoto from the GUGiK WMS")


def fetch(bounds: tuple[float, float, float, float], target: Path, user_agent: str) -> None:
    """Orthophoto of ``bounds`` (EPSG:2180 minx, miny, maxx, maxy) at ``M_PER_PX``."""
    minx, miny, maxx, maxy = bounds
    w = math.ceil((maxx - minx) / M_PER_PX)
    h = math.ceil((maxy - miny) / M_PER_PX)
    out = Image.new("RGB", (w, h))
    for ty in range(0, h, TILE_PX):
        for tx in range(0, w, TILE_PX):
            tw, th = min(TILE_PX, w - tx), min(TILE_PX, h - ty)
            x0 = minx + tx * M_PER_PX
            y1 = maxy - ty * M_PER_PX  # image rows go north to south
            img = _tile((x0, y1 - th * M_PER_PX, x0 + tw * M_PER_PX, y1), tw, th, user_agent)
            out.paste(img, (tx, ty))
            log.info("aerial tile %d,%d (%dx%d px)", tx, ty, tw, th)
    target.parent.mkdir(parents=True, exist_ok=True)
    out.save(target, quality=JPEG_QUALITY, optimize=True)


def aerial_image(cfg: dict, bounds: tuple[float, float, float, float], out: Path, download: bool):
    """Copy the cached orthophoto to ``out`` (fetching it first if asked); False if there is
    no image."""
    key = hashlib.sha1(f"{bounds}|{M_PER_PX}|{WMS_URL}".encode()).hexdigest()[:12]
    cached = path(cfg, "raw") / "aerial" / f"orto-{key}.jpg"
    if not cached.exists():
        if not download:
            return False
        w, h = bounds[2] - bounds[0], bounds[3] - bounds[1]
        log.info("fetching the orthophoto (%.0f x %.0f m)", w, h)
        fetch(bounds, cached, cfg["osm"]["user_agent"])
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, out)
    return True

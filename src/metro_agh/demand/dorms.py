"""How many AGH students live in each dorm (``population/dorms.csv``).

A dorm YAML may give ``residents`` (beds). AGH does not publish beds per house, only the
total (Miasteczko Studenckie: over 8000 places, about 7000 for AGH students; the four big
houses 720-900 each), so the others are estimated from the floor area: footprint x storeys,
spread over ``population.dorm_beds`` minus the beds already known. Floor area is a better
proxy than the footprint alone, since the houses range from 4 to 15 storeys.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from shapely.geometry import Polygon

from ..schemas import load_building
from ..schemas.tables import DORMS

log = logging.getLogger(__name__)


def estimate_dorms(campus_dir: Path, cfg: dict) -> pd.DataFrame:
    """``tables.DORMS`` for every ``kind: dorm`` building of the campus."""
    pop = cfg["population"]
    default_levels = int(cfg["campus"].get("default_levels", 3))
    rows = []
    for f in sorted((Path(campus_dir) / "buildings").glob("*.yaml")):
        b = load_building(f)
        if b.kind != "dorm":
            continue
        area = Polygon(b.footprint, b.footprint_holes).area if b.footprint else None
        levels = len([lv for lv in b.levels if lv.id >= 0]) or b.n_levels or default_levels
        rows.append(
            {
                "building_id": b.id,
                "name": b.name,
                "floor_area_m2": None if area is None else round(area * levels, 1),
                "levels": int(levels),
                "residents": b.residents,
                "source": "yaml" if b.residents is not None else "estimate",
            }
        )
    df = pd.DataFrame(rows, columns=DORMS.column_names)
    if df.empty:
        return df
    known = df["residents"].notna()
    area = df["floor_area_m2"].astype(float)
    area = area.fillna(area.median() if area.notna().any() else 1000.0)
    total = float(pop.get("dorm_beds", 0) or 0)
    left = max(0.0, total - df.loc[known, "residents"].sum())
    if (~known).any():
        if left <= 0:
            # no total to spread: a bed per ``m2_per_bed`` of floor area
            left = float(area[~known].sum()) / float(pop.get("m2_per_bed", 25.0))
        share = area[~known] / area[~known].sum()
        df.loc[~known, "residents"] = (share * left).round()
    df["residents"] = df["residents"].astype("Int64")
    log.info(
        "dorms: %d houses, %d beds (%d from YAML, the rest by floor area)",
        len(df), int(df["residents"].sum()), int(known.sum()),
    )  # fmt: skip
    DORMS.validate(df)
    return df

"""Data contracts between pipeline stages. Described in docs/data_contracts.md.

Change a contract only after agreeing in the team, bump SCHEMA_VERSION when a change
breaks readers, and regenerate ``schemas/`` (``python -m metro_agh.schemas.export``).
"""

from pathlib import Path

import yaml

from .building import Building
from .campus import Campus
from .common import SCHEMA_VERSION
from .instance import Instance, InstanceMeta
from .results import AcoTrace, BestLine, RunMeta
from .tables import ALL_TABLES, SchemaError, Table

__all__ = [
    "ALL_TABLES",
    "SCHEMA_VERSION",
    "AcoTrace",
    "BestLine",
    "Building",
    "Campus",
    "Instance",
    "InstanceMeta",
    "RunMeta",
    "SchemaError",
    "Table",
    "load_building",
    "load_buildings",
    "load_campus",
]


# libyaml is ~10x faster than the pure-Python loader; same results
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load_building(path: Path) -> Building:
    path = Path(path)
    building = Building.model_validate(yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader))
    if building.id != path.stem:
        raise ValueError(f"{path.name}: id {building.id!r} does not match the file name")
    return building


def load_buildings(campus_dir: Path) -> dict[str, Building]:
    """All ``<campus_dir>/buildings/*.yaml``; also checks aliases do not collide."""
    buildings = {
        p.stem: load_building(p) for p in sorted((Path(campus_dir) / "buildings").glob("*.yaml"))
    }
    seen: dict[str, str] = {}
    for b in buildings.values():
        for name in [b.id, *b.aliases]:
            if name in seen and seen[name] != b.id:
                raise ValueError(f"alias {name!r} used by both {seen[name]} and {b.id}")
            seen[name] = b.id
    return buildings


def load_campus(campus_dir: Path) -> Campus:
    """``<campus_dir>/campus.yaml``, with passages checked against the buildings."""
    campus_dir = Path(campus_dir)
    campus = Campus.model_validate(
        yaml.safe_load((campus_dir / "campus.yaml").read_text(encoding="utf-8"))
    )
    buildings = load_buildings(campus_dir)
    for p in campus.passages:
        for end in (p.a, p.b):
            b = buildings.get(end.building)
            if b is None:
                raise ValueError(f"passage {p.id}: unknown building {end.building}")
            corridors = b.corridors()
            if end.corridor not in corridors:
                raise ValueError(f"passage {p.id}: no corridor {end.corridor} in {b.id}")
            if end.at > corridors[end.corridor][1].length + 0.05:
                raise ValueError(f"passage {p.id}: at={end.at} beyond corridor {end.corridor}")
    return campus

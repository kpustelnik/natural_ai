"""Stage 1: AGH USOS -> usos/*.csv (the model) and usos/all/*.csv (the whole term).

    uv run scripts/01_fetch_usos.py                       # everything (a few hours once)
    uv run scripts/01_fetch_usos.py --campus-only         # campus rooms only (~1 h once)
    uv run scripts/01_fetch_usos.py --buildings D-17 B-1  # a few buildings (campus mode)
    uv run scripts/01_fetch_usos.py --offline             # rebuild the CSVs from the cache
    uv run scripts/01_fetch_usos.py --refresh             # fetch every page again

Public sources only, no login and no API key (metro_agh.usos.fetch): the USOS API for
buildings, rooms and seats, the USOSweb catalogue for the room plans, course pages
(cohorts) and class-group pages (meetings, registered students, limits). The full crawl
(usos.scope: all) also walks the catalogue of every faculty, so it finds every programme,
semester and course, every room of every building, and every dated meeting of the term
(usos/all/: course_groups, courses, class_groups, meetings). Every page is
cached in data/raw/usos/, so the crawl can be interrupted and resumed; pages older than
usos.cache_days are fetched again (registered-student counts change until registration
closes). Run it in a teaching week: the room plans show the current week. Formats:
docs/data_contracts.md, section 4.
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

from metro_agh.config import load_config, path
from metro_agh.schemas.tables import ROOM_MAP
from metro_agh.usos.fetch import crawl
from metro_agh.usos.full import full_tables
from metro_agh.usos.http import CachedHttp
from metro_agh.usos.parse import build_tables, building_resolver

log = logging.getLogger("01_fetch_usos")


def campus_buildings(campus_dir: Path) -> tuple[set[str], dict[str, str]]:
    """Building ids of the campus YAMLs and their USOS aliases (alias -> id)."""
    known: set[str] = set()
    aliases: dict[str, str] = {}
    for f in sorted((campus_dir / "buildings").glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        bid = str(data.get("id") or f.stem)
        known.add(bid)
        for a in data.get("aliases") or []:
            aliases[str(a)] = bid
    return known, aliases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--buildings", nargs="*", help="canonical ids (implies --campus-only)")
    parser.add_argument("--campus-only", action="store_true", help="only rooms of the campus")
    parser.add_argument("--offline", action="store_true", help="use only the cached pages")
    parser.add_argument("--refresh", action="store_true", help="fetch every page again")
    parser.add_argument("--max-requests", type=int, default=None, help="stop after N requests")
    parser.add_argument("--week", default=None, help="cache folder of room plans (ISO week)")
    parser.add_argument("--sample", action="store_true", help="campus from data/sample/campus")
    parser.add_argument("--config", default=None, help="YAML of config.yaml keys merged over it")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    u = cfg["usos"]
    campus_dir = path(cfg, "sample") / "campus" if args.sample else path(cfg, "campus")
    known, aliases = campus_buildings(campus_dir)
    resolve = building_resolver(known, aliases)

    http = CachedHttp(
        path(cfg, "raw") / "usos",
        user_agent=cfg["osm"]["user_agent"],
        delay_s=float(u.get("delay_s", 0.5)),
        offline=args.offline,
        max_requests=args.max_requests,
        max_age_s={k: float(d) * 86400 for k, d in (u.get("cache_days") or {}).items()},
        refresh=args.refresh,
    )
    from metro_agh.usos.fetch import API

    index = http.json("api/buildings", f"{API}/geo/building_index")
    usos_ids = {b["id"]: resolve(b["id"]) for b in index}
    unmapped = sorted(k for k, v in usos_ids.items() if v is None)
    if unmapped:
        log.warning(
            "USOS buildings not in the campus model (classes there are dropped): %s", unmapped
        )
    full = u.get("scope", "all") == "all" and not (args.campus_only or args.buildings)
    crawl_ids = None
    if not full:
        wanted = set(args.buildings) if args.buildings else known
        crawl_ids = {k for k, v in usos_ids.items() if v in wanted}
        if not crawl_ids:
            log.error("no USOS building maps to %s", sorted(wanted))
            return 1

    result = crawl(http, str(u["term"]), crawl_ids, week=args.week, full=full)
    room_map_file = path(cfg, "campus") / "usos_room_map.csv"  # also with --sample
    room_map = ROOM_MAP.read(room_map_file) if room_map_file.exists() else None
    tables = build_tables(result, known, aliases, room_map)
    out = path(cfg, "processed")
    tables.write(out)
    if not full and (out / "usos" / "all" / "meetings.csv").exists():
        log.warning(
            "usos/all/ is from an earlier full crawl: 03_build_demand (week: auto) still "
            "takes its dated meetings; rerun the full crawl or use --typical"
        )
    if full:
        everything = full_tables(result, tables.rooms)
        everything.write(out)
        log.info("wrote %s/usos/all/ (%d course groups, %d courses, %d class groups, "
                 "%d dated meetings)", out, len(everything.course_groups),
                 len(everything.courses), len(everything.class_groups),
                 len(everything.meetings))  # fmt: skip
    log.info("wrote %s/usos/ (%d slots, %d groups, %d cohorts, %d students in cohorts)",
             out, len(tables.timetable), len(tables.groups), len(tables.cohorts),
             int(tables.cohorts.n_students.sum()))  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())

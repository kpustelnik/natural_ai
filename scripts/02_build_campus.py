"""Stage 2: campus from OpenStreetMap.

    uv run scripts/02_build_campus.py              # fetch (cached) + layers + report + preview
    uv run scripts/02_build_campus.py --bootstrap  # + LOD1 YAML for new AGH buildings
    uv run scripts/02_build_campus.py --refresh    # download from Overpass again

Outputs (data/processed/osm/): campus.gpkg (open in QGIS), report.md, preview.html.
The walk network + indoor graph (network/*.parquet) will be added to this stage later.
"""

import argparse
import logging
import time

import pandas as pd

from metro_agh.campus.bootstrap import bootstrap
from metro_agh.campus.osm import fetch
from metro_agh.campus.osm_process import build_layers
from metro_agh.campus.osm_report import write_preview, write_report
from metro_agh.config import load_config, path
from metro_agh.schemas.tables import OSM_BUILDING_MAP, OSM_TABLES

log = logging.getLogger("02_build_campus")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="ignore the Overpass cache")
    parser.add_argument("--bootstrap", action="store_true", help="write LOD1 building YAMLs")
    parser.add_argument("--config", default=None, help="experiment config overriding keys")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    campus_dir = path(cfg, "campus")
    out_dir = path(cfg, "processed") / "osm"
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    raw = fetch(cfg, path(cfg, "raw") / "osm", refresh=args.refresh)
    log.info(
        "fetched %d features, walk graph %d nodes in %.0f s",
        len(raw.features), raw.graph.number_of_nodes(), time.perf_counter() - t0,
    )  # fmt: skip

    map_file = campus_dir / "osm_building_map.csv"
    overrides = OSM_BUILDING_MAP.read(map_file) if map_file.exists() else pd.DataFrame()
    layers, issues = build_layers(raw.features, raw.graph, raw.bbox, overrides, cfg)

    gpkg = out_dir / "campus.gpkg"
    gpkg.unlink(missing_ok=True)
    for table in OSM_TABLES:
        table.write(layers[table.layer], gpkg)
        log.info("%-11s %5d rows", table.layer, len(layers[table.layer]))

    boot = None
    if args.bootstrap:
        walk_nodes = set(layers["walk_nodes"].osm_node)
        boot = bootstrap(
            layers["buildings"], layers["entrances"], walk_nodes,
            campus_dir / "buildings", cfg, issues,
        )  # fmt: skip
        log.info(
            "bootstrap: %d written, %d skipped, %d failed",
            len(boot.written), len(boot.skipped), len(boot.failed),
        )  # fmt: skip

    write_report(out_dir / "report.md", layers, issues, boot)
    write_preview(out_dir / "preview.html", layers)
    log.info("wrote %s, report.md, preview.html", gpkg)


if __name__ == "__main__":
    main()

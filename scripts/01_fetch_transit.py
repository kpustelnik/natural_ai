"""Stage 1b: Kraków GTFS -> transit/stops.csv, rides.csv, trips.parquet (+ campus.yaml stops).

    uv run scripts/01_fetch_transit.py                 # feeds from config.yaml, next Tuesday
    uv run scripts/01_fetch_transit.py --date 2026-10-13
    uv run scripts/01_fetch_transit.py --print-yaml    # the stops: block for campus.yaml

Stops in campus.bbox with the vehicles arriving in the morning peak (their weight spreads
the commuting students), and the direct rides between campus stops (the transport a metro
competes with). Feeds are cached in data/raw/gtfs/; --refresh downloads them again.
"""

import argparse
import datetime as dt
import logging
import sys

from metro_agh.config import load_config, path
from metro_agh.schemas.tables import TRANSIT_RIDES, TRANSIT_STOPS, TRANSIT_TRIPS
from metro_agh.transit.gtfs import campus_transit, campus_yaml_stops, default_date, download

log = logging.getLogger("01_fetch_transit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=None, help="service day YYYY-MM-DD")
    parser.add_argument("--refresh", action="store_true", help="download the feeds again")
    parser.add_argument("--print-yaml", action="store_true", help="print campus.yaml stops")
    parser.add_argument("--config", default=None, help="YAML of config.yaml keys merged over it")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    t = cfg["transit"]
    zips = download(t["feeds"], path(cfg, "raw") / "gtfs", cfg["osm"]["user_agent"], args.refresh)
    when = args.date or (None if t.get("date", "auto") == "auto" else str(t["date"]))
    date = dt.date.fromisoformat(when) if when else default_date(zips)
    stops, rides, trips = campus_transit(zips, cfg["campus"]["bbox"], date, cfg)
    out = path(cfg, "processed")
    TRANSIT_STOPS.write(stops, out / TRANSIT_STOPS.path)
    TRANSIT_RIDES.write(rides, out / TRANSIT_RIDES.path)
    TRANSIT_TRIPS.write(trips, out / TRANSIT_TRIPS.path)
    log.info("wrote %s and %s", out / TRANSIT_STOPS.path, out / TRANSIT_RIDES.path)
    if args.print_yaml:
        print(campus_yaml_stops(stops))
    return 0


if __name__ == "__main__":
    sys.exit(main())

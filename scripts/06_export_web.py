"""Stage 6: files for the browser viewer (web/public/data/).

    uv run scripts/06_export_web.py --campus            # buildings, context, ground, network
    uv run scripts/06_export_web.py --campus --sample   # from data/sample/campus
    uv run scripts/06_export_web.py --campus --watch    # rebuild on every save (modelling)
    uv run scripts/06_export_web.py --campus --aerial   # also fetch the orthophoto (once)

Then: cd web && npm run dev (or `npm run model`, which starts the watcher too).
Formats: docs/data_contracts.md, section 10.
Metro, ACO and simulation replays (--metro / --aco / --sim) are added with those stages.
"""

import argparse
import contextlib
import logging
import sys

from metro_agh.config import load_config, path
from metro_agh.web.export_campus import CampusExport
from metro_agh.web.watch import watch

log = logging.getLogger("06_export_web")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--campus", action="store_true", help="export the campus (default)")
    parser.add_argument("--sample", action="store_true", help="use data/sample/campus")
    parser.add_argument("--watch", action="store_true", help="rebuild when sources change")
    parser.add_argument("--aerial", action="store_true", help="fetch the GUGiK orthophoto")
    parser.add_argument("--config", default=None, help="experiment config overriding keys")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    campus_dir = path(cfg, "sample") / "campus" if args.sample else path(cfg, "campus")
    ex = CampusExport(cfg, campus_dir=campus_dir)
    ex.download_aerial = args.aerial

    if args.watch:
        with contextlib.suppress(KeyboardInterrupt):  # Ctrl+C ends the watch
            watch(ex)
        return

    status = ex.full()
    for e in status.errors:
        where = f"{e.file}:{e.line}" if e.line else e.file
        log.error("%s: %s%s", where, f"{e.loc}: " if e.loc else "", e.message)
    log.info("status.json version %d, %d files", status.version, len(status.changed))
    sys.exit(1 if status.errors else 0)


if __name__ == "__main__":
    main()

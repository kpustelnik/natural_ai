"""Watch mode: rebuild the viewer files when the campus sources change.

Polls modification times (no extra dependency, works the same on every OS):

- ``buildings/*.yaml`` changed, added or removed -> only those buildings are rebuilt
  (their glb + json, then scene.json, issues.json and status.json);
- ``campus.yaml``, ``campus.gpkg`` or the OSM ``issues.json`` changed -> full export.

A change is handled once the files stop changing for one poll interval, because editors
often write a file in several steps.
"""

import contextlib
import logging
import time
from pathlib import Path

from .export_campus import CampusExport

log = logging.getLogger(__name__)


def _snapshot(paths: list[Path]) -> dict[Path, float]:
    out = {}
    for p in paths:
        with contextlib.suppress(OSError):  # deleted in the meantime
            out[p] = p.stat().st_mtime
    return out


def _sources(ex: CampusExport) -> tuple[list[Path], list[Path]]:
    buildings = sorted((ex.campus_dir / "buildings").glob("*.yaml"))
    others = [ex.campus_dir / "campus.yaml", ex.osm_dir / "campus.gpkg", ex.osm_dir / "issues.json"]
    return buildings, others


def watch(ex: CampusExport, interval_s: float = 0.3, max_runs: int | None = None) -> None:
    """Run a full export, then rebuild on every change until interrupted.
    ``max_runs`` (tests) stops after that many rebuilds."""
    ex.full()
    buildings, others = _sources(ex)
    seen = _snapshot(buildings + others)
    log.info("watching %s (Ctrl+C to stop)", ex.campus_dir)
    runs = 0
    while max_runs is None or runs < max_runs:
        time.sleep(interval_s)
        buildings, others = _sources(ex)
        now = _snapshot(buildings + others)
        if now == seen:
            continue
        # wait until the files settle
        while True:
            time.sleep(interval_s)
            buildings, others = _sources(ex)
            settled = _snapshot(buildings + others)
            if settled == now:
                break
            now = settled
        changed = {p for p in set(now) | set(seen) if now.get(p) != seen.get(p)}
        seen = now
        runs += 1
        try:
            if changed & set(others):
                log.info("sources changed: full export")
                status = ex.full()
            else:
                names = ", ".join(sorted(p.stem for p in changed))
                log.info("rebuilding %s", names)
                status = ex.update(sorted(changed))
        except Exception:  # keep watching; the next save may fix it
            log.exception("export failed")
            continue
        for e in status.errors:
            where = f"{e.file}:{e.line}" if e.line else e.file
            log.error("%s: %s%s", where, f"{e.loc}: " if e.loc else "", e.message)
        log.info("status.json version %d", status.version)

"""Stage 6: files for the browser viewer (web/public/data/).

    uv run scripts/06_export_web.py --campus            # buildings, context, ground, network
    uv run scripts/06_export_web.py --campus --sample   # from data/sample/campus
    uv run scripts/06_export_web.py --campus --watch    # rebuild on every save (modelling)
    uv run scripts/06_export_web.py --campus --aerial   # also fetch the orthophoto (once)
    uv run scripts/06_export_web.py --aco               # every ACO run with a trace -> replay
    uv run scripts/06_export_web.py --aco RUN_DIR ...   # only these experiments/results/<run_id>
    uv run scripts/06_export_web.py --metro             # results/best_line.json -> replay
    uv run scripts/06_export_web.py --sim               # simulation/*/legs.parquet -> replay
    uv run scripts/06_export_web.py --fake              # synthetic ACO run, line and week
    uv run scripts/06_export_web.py --fake --sample     # the same on data/sample/campus

--aco, --metro, --sim and --fake read scene.json, so run --campus first (once is enough;
with --fake, from the same campus: add --sample to both or to neither).
Then: cd web && npm run dev (or `npm run model`, which starts the watcher too).
Formats: docs/data_contracts.md, section 10.
"""

import argparse
import contextlib
import logging
import sys
from pathlib import Path

from metro_agh.config import load_config, path
from metro_agh.web.export_campus import CampusExport, write_replay_catalog, write_status_file
from metro_agh.web.export_demand import export_demand, refresh_demand
from metro_agh.web.export_metro import export_aco_run, export_best_line, load_scene
from metro_agh.web.export_sim import export_simulation
from metro_agh.web.fake import NOTE, SIM_NOTE, write_fake_results, write_fake_simulation
from metro_agh.web.watch import watch

log = logging.getLogger("06_export_web")


def export_replays(cfg: dict, args: argparse.Namespace) -> int:
    """--aco / --metro / --sim / --fake: replays next to the campus files."""
    out = path(cfg, "web_data")
    results = path(cfg, "results")
    runs: list[Path] = []
    best_line: Path | None = None
    simulated: Path | None = None  # the processed dir with simulation/
    note = None
    if args.fake:
        root = path(cfg, "processed") / "fake"
        scene = load_scene(out)
        runs.append(write_fake_results(scene, cfg, root, seed=int(cfg["seed"])))
        best_line, note = root / "results" / "best_line.json", NOTE
        campus_dir = path(cfg, "sample") / "campus" if args.sample else path(cfg, "campus")
        simulated = write_fake_simulation(scene, cfg, campus_dir, root, seed=int(cfg["seed"]))
    if args.aco is not None:
        runs += [Path(r) for r in args.aco] or sorted(p.parent for p in results.glob("*/trace.npz"))
        if not runs:
            log.warning("no %s/*/trace.npz: nothing to export (try --fake)", results)
    if args.metro:
        best_line = results / "best_line.json"
        if not best_line.exists():
            log.error("%s missing: run 04_optimize.py first (or --fake)", best_line)
            return 1
    if args.sim:
        best_line, simulated = results / "best_line.json", path(cfg, "processed")
        if not (simulated / "simulation").exists():
            log.error("%s/simulation missing: run 05_simulate.py first (or --fake)", simulated)
            return 1

    changed: list[str] = []
    for run in runs:
        export_aco_run(cfg, run, out, changed, note=note)
    if simulated is not None:
        sim_note = SIM_NOTE if args.fake else None
        export_simulation(cfg, simulated, best_line, out, changed, note=sim_note)
        export_demand(cfg, simulated, out, changed, note=sim_note)
    elif best_line is not None:
        schedule = path(cfg, "processed") / "simulation" / "metro" / "schedule.parquet"
        export_best_line(cfg, best_line, out, changed, schedule_file=schedule)
        # heatmap from whatever demand/ exists next to the real pipeline
        export_demand(cfg, path(cfg, "processed"), out, changed)
    changed.append(write_replay_catalog(out, cfg))
    status = write_status_file(out, changed)
    log.info("status.json version %d, %d files", status.version, len(status.changed))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--campus", action="store_true", help="export the campus (default)")
    parser.add_argument("--sample", action="store_true", help="use data/sample/campus")
    parser.add_argument("--watch", action="store_true", help="rebuild when sources change")
    parser.add_argument("--aerial", action="store_true", help="fetch the GUGiK orthophoto")
    parser.add_argument(
        "--aco", nargs="*", metavar="RUN_DIR", help="ACO runs with a trace.npz (default: all)"
    )
    parser.add_argument("--metro", action="store_true", help="the line in best_line.json")
    parser.add_argument("--sim", action="store_true", help="the simulated week (stage 5)")
    parser.add_argument("--fake", action="store_true", help="synthetic ACO run, line and week")
    parser.add_argument("--config", default=None, help="YAML of config.yaml keys merged over it")
    args = parser.parse_args()
    if args.fake and (args.aco is not None or args.metro or args.sim):
        # the synthetic run would label the real runs and simulation as synthetic too
        parser.error("--fake cannot be combined with --aco, --metro or --sim")
    if args.watch and (args.aco is not None or args.metro or args.sim or args.fake):
        parser.error("--watch rebuilds only the campus: export replays in a separate run")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(override=args.config)
    replays = args.aco is not None or args.metro or args.sim or args.fake
    code = 0
    if args.campus or args.watch or not replays:
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
        refresh_demand(cfg, ex.out_dir)  # the heatmap, if demand/od.parquet exists (03)
        log.info("status.json version %d, %d files", status.version, len(status.changed))
        code = 1 if status.errors else 0
    if replays:
        code = max(code, export_replays(cfg, args))
    sys.exit(code)


if __name__ == "__main__":
    main()

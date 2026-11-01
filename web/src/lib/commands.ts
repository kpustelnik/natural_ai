// Which export writes a data file: shown with a missing file (toast, empty states).

/** The export that writes a data file (paths relative to the data dir). */
export function commandFor(path: string): string {
  if (path.startsWith("replays/aco-")) return "uv run scripts/06_export_web.py --aco";
  if (path.includes("/trips/") || path.endsWith("stats.json")) return "uv run scripts/06_export_web.py --sim";
  if (path.startsWith("replays/sim-")) return "uv run scripts/06_export_web.py --metro";
  if (path.startsWith("campus/aerial")) return "uv run scripts/06_export_web.py --campus --aerial";
  return "uv run scripts/06_export_web.py --campus";
}

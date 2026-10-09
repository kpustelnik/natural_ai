// A shell command to run, shown where a file is missing, with a copy button.

import { toast } from "../state/app";
import { IconCopy } from "./icons";

export function Command({ lines }: { lines: string[] }) {
  const text = lines.join("\n");
  return (
    <div className="command">
      <pre>{text}</pre>
      <button
        className="icon-button"
        title="Copy"
        aria-label="Copy the command"
        onClick={() => {
          void navigator.clipboard?.writeText(text);
          toast("Copied");
        }}
      >
        <IconCopy size={13} />
      </button>
    </div>
  );
}

/** The export that writes a data file (paths relative to the data dir). */
export function commandFor(path: string): string {
  if (path.startsWith("replays/aco-")) return "uv run scripts/06_export_web.py --aco";
  if (path.includes("/trips/") || path.endsWith("stats.json")) return "uv run scripts/06_export_web.py --sim";
  if (path.startsWith("replays/sim-")) return "uv run scripts/06_export_web.py --metro";
  if (path.startsWith("campus/aerial")) return "uv run scripts/06_export_web.py --campus --aerial";
  return "uv run scripts/06_export_web.py --campus";
}

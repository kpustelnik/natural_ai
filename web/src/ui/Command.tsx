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


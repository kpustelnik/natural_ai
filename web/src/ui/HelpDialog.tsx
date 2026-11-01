// Keyboard help (the ? key): every shortcut of the viewer, grouped.

import { useEffect, useRef } from "react";
import { app, useApp } from "../state/app";
import { IconClose } from "./icons";

const GROUPS: { title: string; keys: [string, string][] }[] = [
  {
    title: "View",
    keys: [
      ["1 / 2 / 3", "orbit, plan, walk camera"],
      ["F", "frame the selection (double-click: frame what is clicked)"],
      ["PageUp / PageDown", "open the selected building, step through its levels"],
      ["\\", "hide or show both side panels"],
      ["P", "presentation mode: only the view (a replay keeps playing)"],
      ["S", "save a screenshot (PNG)"],
      ["`", "frame-rate probe"],
    ],
  },
  {
    title: "Tools",
    keys: [
      ["/", "search buildings, rooms, stops, OSM ids"],
      ["M", "measure; Backspace removes the last point"],
      ["R", "route between two points"],
      ["Alt+click", "copy local [x, y] of a building"],
      ["Alt+Shift+click", "collect a polyline; Enter copies it"],
      ["Esc", "end the tool, clear, deselect, leave presentation"],
    ],
  },
  {
    title: "Replays",
    keys: [
      ["Space", "play / pause"],
      ["Walk camera", "W A S D, Shift to run, mouse to look, Esc to leave"],
    ],
  },
];

export function HelpDialog() {
  const open = useApp((s) => s.help);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) box.current?.focus();
  }, [open]);
  if (!open) return null;
  const close = () => app.set({ help: false });
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="help-title" tabIndex={-1} ref={box}>
        <div className="modal-header">
          <h2 id="help-title">Keyboard shortcuts</h2>
          <button className="icon-button" onClick={close} title="Close (Esc)" aria-label="Close">
            <IconClose size={14} />
          </button>
        </div>
        <div className="help-groups">
          {GROUPS.map((g) => (
            <section key={g.title}>
              <div className="group-title">{g.title}</div>
              <dl className="help-keys">
                {g.keys.map(([k, v]) => (
                  <div key={k} className="help-row">
                    <dt>
                      <kbd>{k}</kbd>
                    </dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

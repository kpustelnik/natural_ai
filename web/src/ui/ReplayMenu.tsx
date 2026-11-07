// The menu that chooses what to replay: every optimisation run (ACO) and simulation the
// pipeline exported to replays/<id>/, read from replays/index.json (ReplayCatalog).

import { useEffect, useRef, useState } from "react";
import type { Replay, ReplayCatalog } from "../generated/schemas";
import { dateTime, WEEKDAYS } from "../lib/format";
import { inStage } from "../lib/stage";
import { app, setPlayback, setWorkspace, useApp } from "../state/app";
import { Command } from "./Command";
import { IconChevronDown, IconClose, IconReplay } from "./icons";

const isSynthetic = (r: Replay) => (r.run_id ?? "").startsWith("fake-");

/** Menu groups: real simulations, then real ACO runs (each by line length), synthetic last. */
const GROUPS: { title: string; pick: (r: Replay) => boolean }[] = [
  { title: "Week simulations (with / without metro)", pick: (r) => r.kind === "simulation" && !isSynthetic(r) },
  { title: "Optimisation runs (ACO)", pick: (r) => r.kind === "aco" && !isSynthetic(r) },
  { title: "Walking with congestion (ACO level 1)", pick: (r) => r.kind === "walk" },
  { title: "Synthetic (for developing the viewer)", pick: isSynthetic },
];

export function openReplay(r: Replay | null): void {
  setPlayback({
    replayId: r?.id ?? null,
    playing: false,
    t: 8 * 3600,
    iteration: 0,
    acoView: "ants",
    split: false,
    speed: r?.kind === "simulation" || !r ? 60 : 5,
  });
  if (r) {
    setWorkspace(r.kind === "simulation" ? "simulation" : "metro");
    if (r.kind === "walk") app.set({ layers: { ...app.get().layers, labels: false } });
    app.set({ rightOpen: true });
    if (r.scenarios.length) setPlayback({ scenario: r.scenarios.includes("metro") ? "metro" : r.scenarios[0]! });
    if (r.weekdays.length) setPlayback({ weekday: r.weekdays[0]! });
  } else if (app.get().workspace === "metro" || app.get().workspace === "simulation") {
    setWorkspace("campus");
  }
}

function details(r: Replay): string {
  const parts: string[] = [];
  if (r.topology) parts.push(r.topology);
  if (r.stations.length) parts.push(`${r.stations.length} stations`);
  if (r.scenarios.length) parts.push(r.scenarios.map((s) => s.replace("_", " ")).join(" / "));
  if (r.weekdays.length) parts.push(r.weekdays.map((d) => WEEKDAYS[d - 1]).join(" "));
  return parts.join(" · ");
}

export function ReplayMenu({ catalog }: { catalog: ReplayCatalog | undefined }) {
  const [open, setOpen] = useState(false);
  const replayId = useApp((s) => s.playback.replayId);
  const box = useRef<HTMLDivElement>(null);
  const stage = useApp((s) => s.stage);
  const replays = (catalog?.replays ?? []).filter((r) => inStage(r, stage));
  const current = replays.find((r) => r.id === replayId) ?? null;

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); // only close the menu: App's Escape would also clear the selection
      setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="menu" ref={box}>
      <button className={`menu-button ${current ? "active" : ""}`} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <IconReplay />
        <span className="menu-button-label">{current ? current.title : "Replays"}</span>
        {!current && replays.length > 0 && <span className="count">{replays.length}</span>}
        <IconChevronDown size={14} />
      </button>
      {open && (
        <div className="menu-popover replay-popover">
          <div className="popover-header">
            <span>Choose what to replay</span>
            {current && (
              <button
                className="link-button"
                onClick={() => {
                  openReplay(null);
                  setOpen(false);
                }}
              >
                <IconClose size={14} /> Close replay
              </button>
            )}
          </div>
          {replays.length === 0 && (
            <div className="empty">
              <p>No replays exported yet.</p>
              <p className="muted">Run the optimiser, then export:</p>
              <Command
                lines={[
                  "uv run scripts/04_optimize.py",
                  "uv run scripts/06_export_web.py --aco",
                ]}
              />
              <p className="muted">Or a full synthetic week for the viewer:</p>
              <Command lines={["uv run scripts/06_export_web.py --fake"]} />
            </div>
          )}
          {GROUPS.map((g) => {
            const group = replays.filter(g.pick).sort((a, b) => a.stations.length - b.stations.length || a.title.localeCompare(b.title));
            if (!group.length) return null;
            return (
              <div key={g.title} className="replay-group">
                <div className="group-title">{g.title}</div>
                {group.map((r) => (
                  <button
                    key={r.id}
                    className={`replay-item ${r.id === replayId ? "selected" : ""}`}
                    onClick={() => {
                      openReplay(r);
                      setOpen(false);
                    }}
                  >
                    <div className="replay-title">
                      <span>{r.title}</span>
                      <span className="muted">{dateTime(r.created_at)}</span>
                    </div>
                    {details(r) && <div className="replay-meta">{details(r)}</div>}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// The menu that chooses what to replay: every optimisation run (ACO) and simulation the
// pipeline exported to replays/<id>/, read from replays/index.json (ReplayCatalog).

import { useEffect, useRef, useState } from "react";
import type { Replay, ReplayCatalog } from "../generated/schemas";
import { dateTime, WEEKDAYS } from "../lib/format";
import { app, setPlayback, setWorkspace, useApp } from "../state/app";
import { IconChevronDown, IconClose, IconReplay } from "./icons";

const KIND_LABEL: Record<Replay["kind"], string> = {
  aco: "Optimisation runs (ACO)",
  simulation: "Simulations",
};

export function openReplay(r: Replay | null): void {
  setPlayback({
    replayId: r?.id ?? null,
    playing: false,
    t: 8 * 3600,
    iteration: 0,
    acoView: "ants",
    speed: r?.kind === "aco" ? 5 : 60,
  });
  if (r) {
    setWorkspace(r.kind === "aco" ? "metro" : "simulation");
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
  const replays = catalog?.replays ?? [];
  const current = replays.find((r) => r.id === replayId) ?? null;

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
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
              <p className="muted">
                Optimisation runs and simulations appear here once the pipeline exports them to{" "}
                <code>web/public/data/replays/&lt;id&gt;/replay.json</code>.
              </p>
            </div>
          )}
          {(["simulation", "aco"] as const).map((kind) => {
            const group = replays.filter((r) => r.kind === kind);
            if (!group.length) return null;
            return (
              <div key={kind} className="replay-group">
                <div className="group-title">{KIND_LABEL[kind]}</div>
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
                    {r.description && <div className="replay-desc">{r.description}</div>}
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

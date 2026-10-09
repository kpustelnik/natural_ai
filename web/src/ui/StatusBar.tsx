import { useStatus } from "../data/resource";
import type { Scene } from "../generated/schemas";
import { dateTime, lonLat } from "../lib/format";
import { webToGeo, webToLocal } from "../lib/frames";
import { app, openedBuilding, useApp } from "../state/app";

function BuildStatusItem() {
  const status = useStatus().data;
  if (!status) return <span className="status-item muted">no status.json</span>;
  const errors = status.errors.length;
  return (
    <button
      className={`status-item status-button ${errors ? "has-errors" : ""}`}
      title={
        errors
          ? `${status.errors.map((e) => `${e.file}${e.line ? `:${e.line}` : ""}  ${e.message}`).join("\n")}\n\nClick to list them`
          : "Data build status"
      }
      onClick={() => errors && app.set({ rightOpen: true, rightTab: "issues" })}
    >
      <span className={`dot ${errors ? "error" : "ok"}`} />
      data v{status.version} · {dateTime(status.built_at)}
      {errors > 0 && <span className="error-text"> · {errors} error{errors > 1 ? "s" : ""}</span>}
    </button>
  );
}

export function StatusBar({ scene }: { scene: Scene }) {
  const cursor = useApp((s) => s.cursor);
  const hovered = useApp((s) => s.cursorBuilding);
  const selected = useApp((s) => openedBuilding(s) ?? (s.selection?.kind === "building" ? s.selection.id : null));
  const walking = useApp((s) => s.camera === "walk");
  const id = hovered ?? selected;
  const b = id ? scene.buildings.find((x) => x.id === id) : undefined;

  let local: string | null = null;
  if (cursor && b) {
    const [x, y, h] = webToLocal(b.frame, cursor);
    const level = [...b.levels].reverse().find((l) => cursor[1] >= l.floor_y - 0.01);
    local = `${b.id} local  x ${x.toFixed(1)}  y ${y.toFixed(1)}  z ${h.toFixed(1)}${level && hovered ? `  L${level.id}` : ""}`;
  }
  const hint = walking ? null : local ? "Alt+click copies [x, y] · Alt+Shift+click collects a polyline" : null;

  return (
    <footer className="statusbar">
      <BuildStatusItem />
      <span className="status-spacer" />
      {hint && <span className="status-item muted">{hint}</span>}
      {cursor && <span className="status-item mono">{lonLat(...webToGeo(scene.frame, cursor))}</span>}
      {local && <span className="status-item mono">{local}</span>}
    </footer>
  );
}

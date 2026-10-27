// Controls drawn over the 3D view: camera mode, colour mode, level stepper, compass,
// scale bar, legend, tool panels (measure, captured points), toasts and hints; the empty
// state of the Metro and Simulation workspaces, the split-view captions, the frame-rate
// probe. In presentation mode only the compass, scale bar, captions, toasts and the probe stay.

import { useEffect, useState } from "react";
import { useBuildingInfo } from "../data/resource";
import type { Replay, ReplayCatalog, Scene } from "../generated/schemas";
import { registry } from "../scene/registry";
import { screenshot } from "../scene/screenshot";
import {
  CAPACITY,
  CAPACITY_UNKNOWN,
  DEMAND,
  DEMAND_NONE,
  DEMAND_ZERO,
  legend,
  NETWORK,
  NETWORK_LABELS,
  SCENARIOS,
  SPACE_KIND,
} from "../scene/palette";
import { segmentLength } from "../scene/tools/Tools";
import {
  app,
  captureText,
  type ColorMode,
  copyCapture,
  enterBuilding,
  openedBuilding,
  pickBuilding,
  type RoomColorMode,
  splitActive,
  stepLevel,
  useApp,
} from "../state/app";
import { Command } from "./Command";
import { IconCamera, IconClose, IconChevronDown, IconCopy, IconHelp, IconOrbit, IconPlan, IconPresent, IconRuler, IconUp, IconWalk } from "./icons";
import { openReplay } from "./ReplayMenu";

const COLOR_MODES: { id: ColorMode; label: string }[] = [
  { id: "category", label: "Category" },
  { id: "lod", label: "Detail" },
  { id: "issues", label: "Issues" },
  { id: "demand", label: "Demand" },
];

const ROOM_MODES: { id: RoomColorMode; label: string }[] = [
  { id: "kind", label: "Kind" },
  { id: "capacity", label: "Capacity" },
];

function Compass() {
  const heading = useApp((s) => s.azimuthDeg);
  const plan = useApp((s) => s.camera === "plan");
  return (
    <button
      className="compass"
      title={plan ? "Plan view: north is where the needle points" : "Turn north up"}
      onClick={() => app.set((s) => ({ northRequest: s.northRequest + 1 }))}
    >
      <svg viewBox="-20 -20 40 40" width="40" height="40" style={{ transform: `rotate(${-heading}deg)` }}>
        <circle r="18" className="compass-ring" />
        <path d="M0 -13 L5 2 L0 -1 L-5 2 Z" className="compass-north" />
        <path d="M0 13 L5 -2 L0 1 L-5 -2 Z" className="compass-south" />
        <text y="-15.5" className="compass-n">
          N
        </text>
      </svg>
    </button>
  );
}

const NICE = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000];

function ScaleBar() {
  const mpp = useApp((s) => s.metresPerPixel);
  const target = mpp * 110; // about 110 px
  const metres = NICE.reduce((best, n) => (Math.abs(n - target) < Math.abs(best - target) ? n : best), NICE[0]!);
  const px = metres / mpp;
  return (
    <div className="scalebar" title="Scale at the view centre">
      <div className="scalebar-bar" style={{ width: `${px}px` }} />
      <span>{metres >= 1000 ? `${metres / 1000} km` : `${metres} m`}</span>
    </div>
  );
}

function Hint({ scene }: { scene: Scene }) {
  const workspace = useApp((s) => s.workspace);
  const building = useApp((s) => pickBuilding(s.selection));
  const level = useApp((s) => s.level);
  const replay = useApp((s) => s.playback.replayId);
  const tool = useApp((s) => s.tool);
  let text: string | null = null;
  const routeSlot = useApp((s) => s.route.slot);
  if (tool === "measure") text = "Click points to measure · Backspace removes the last · Esc clears";
  else if (tool === "route")
    text = `Click the ${routeSlot === "from" ? "start (A)" : "destination (B)"}: a room, building, stop or any point on the paths · Esc ends`;
  else if (workspace === "building" && !building) text = "Select a building to open it.";
  else if (workspace === "building" && level === null) {
    const b = scene.buildings.find((x) => x.id === building);
    text = b && b.lod > 1 ? "Choose a level (PageUp / PageDown) to see its plan." : "Choose a level to cut the building at it.";
  } else if ((workspace === "metro" || workspace === "simulation") && !replay) text = "Choose a replay from the Replays menu.";
  return text ? <div className="hint">{text}</div> : null;
}

function LevelStepper({ scene }: { scene: Scene }) {
  const id = useApp((s) => openedBuilding(s));
  const level = useApp((s) => s.level);
  const b = id ? scene.buildings.find((x) => x.id === id) : undefined;
  if (!b) return null;
  const levels = b.levels.map((l) => l.id).sort((a, c) => c - a);
  return (
    <div className="level-stepper" role="group" aria-label="Level">
      <button title="Level up (PageUp)" onClick={() => stepLevel(levels, 1)}>
        <IconUp size={14} />
      </button>
      <button className={level === null ? "active" : ""} aria-pressed={level === null} onClick={() => app.set({ level: null })} title="Whole building">
        All
      </button>
      {levels.map((l) => (
        <button key={l} className={level === l ? "active" : ""} aria-pressed={level === l} onClick={() => app.set({ level: l })} title={`Level ${l}`}>
          {l}
        </button>
      ))}
      <button title="Level down (PageDown)" onClick={() => stepLevel(levels, -1)}>
        <IconChevronDown size={14} />
      </button>
    </div>
  );
}

function MeasurePanel({ scene }: { scene: Scene }) {
  const points = useApp((s) => s.measure);
  const building = useApp((s) => openedBuilding(s) ?? pickBuilding(s.selection));
  const b = building ? scene.buildings.find((x) => x.id === building) : undefined;
  const segs = points.slice(1).map((p, i) => segmentLength(points[i]!, p));
  const total = segs.reduce((a, b) => a + b, 0);
  const a = points[points.length - 2];
  const z = points[points.length - 1];
  let angle: string | null = null;
  if (a && z) {
    const dx = z[0] - a[0];
    const dn = -(z[2] - a[2]);
    const bearing = ((Math.atan2(dx, dn) * 180) / Math.PI + 360) % 360;
    // angle from the building's +x axis, counter-clockwise like the local frame
    angle = b
      ? `${((((b.frame.bearing_deg - bearing) % 360) + 540) % 360 - 180).toFixed(1)}° from ${b.id} +x`
      : `bearing ${bearing.toFixed(1)}°`;
  }
  return (
    <div className="tool-panel">
      <div className="tool-head">
        <IconRuler size={14} /> Measure
        <button className="icon-button" title="Close (M)" aria-label="Close" onClick={() => app.set({ tool: "select", measure: [] })}>
          <IconClose size={14} />
        </button>
      </div>
      {points.length < 2 ? (
        <p className="muted small">Click two or more points. Points snap to corners, edges and path nodes.</p>
      ) : (
        <div className="kv-list">
          {segs.map((d, i) => (
            <div className="kv" key={i}>
              <span className="k">segment {i + 1}</span>
              <span className="v mono">{d.toFixed(2)} m</span>
            </div>
          ))}
          <div className="kv">
            <span className="k">total</span>
            <span className="v mono strong">{total.toFixed(2)} m</span>
          </div>
          {angle && (
            <div className="kv">
              <span className="k">last segment</span>
              <span className="v mono">{angle}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CapturePanel() {
  const capture = useApp((s) => s.capture);
  if (!capture) return null;
  return (
    <div className="tool-panel">
      <div className="tool-head">
        Points in {capture.building} local
        <button className="icon-button" title="Clear (Esc)" aria-label="Clear" onClick={() => app.set({ capture: null })}>
          <IconClose size={14} />
        </button>
      </div>
      <pre className="capture-text">{captureText(capture)}</pre>
      <div className="actions">
        <button className="button" onClick={copyCapture}>
          <IconCopy size={14} /> Copy <kbd>Enter</kbd>
        </button>
      </div>
      <p className="muted small">Alt+Shift+click adds a point, Backspace removes the last.</p>
    </div>
  );
}

function RoomLegend() {
  const mode = useApp((s) => s.roomColor);
  if (mode === "capacity") {
    return (
      <>
        {CAPACITY.map((c) => (
          <div key={c.label} className="legend-row">
            <span className="swatch" style={{ background: c.color }} />
            {c.label}
          </div>
        ))}
        <div className="legend-row">
          <span className="swatch" style={{ background: CAPACITY_UNKNOWN.color }} />
          {CAPACITY_UNKNOWN.label}
        </div>
      </>
    );
  }
  return (
    <>
      {Object.values(SPACE_KIND).map((k) => (
        <div key={k.label} className="legend-row">
          <span className="swatch" style={{ background: k.color }} />
          {k.label}
        </div>
      ))}
    </>
  );
}

function DemandLegend() {
  return (
    <>
      {DEMAND.map((b) => (
        <div key={b.label} className="legend-row">
          <span className="swatch line" style={{ background: b.color }} />
          {b.label}
        </div>
      ))}
      <div className="legend-row">
        <span className="swatch line" style={{ background: DEMAND_ZERO.color }} />
        {DEMAND_ZERO.label}
      </div>
      <div className="legend-row">
        <span className="swatch line" style={{ background: DEMAND_NONE.color }} />
        {DEMAND_NONE.label}
      </div>
    </>
  );
}

function SplitCaptions() {
  return (
    <div className="split-overlay" aria-hidden>
      <span className="split-label left">{SCENARIOS.no_metro.label}</span>
      <span className="split-label right">{SCENARIOS.metro.label}</span>
    </div>
  );
}

function Toasts() {
  const toasts = useApp((s) => s.toasts);
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

function WalkHelp() {
  return (
    <div className="walk-help">
      Click to look around · <kbd>W</kbd>
      <kbd>A</kbd>
      <kbd>S</kbd>
      <kbd>D</kbd> move · <kbd>Shift</kbd> run · <kbd>Esc</kbd> back to orbit
    </div>
  );
}

/** Metro / Simulation workspace with no replay open: what can be opened, or how to make one. */
function NoReplay({ catalog }: { catalog: ReplayCatalog | undefined }) {
  const workspace = useApp((s) => s.workspace);
  const open = useApp((s) => s.playback.replayId !== null);
  if (open || (workspace !== "metro" && workspace !== "simulation")) return null;
  const kind: Replay["kind"] = workspace === "metro" ? "aco" : "simulation";
  const list = catalog?.replays.filter((r) => r.kind === kind) ?? [];
  return (
    <div className="empty-card">
      <h2>{kind === "aco" ? "No optimisation run open" : "No simulation open"}</h2>
      {list.length > 0 ? (
        <>
          <p className="muted">Open one:</p>
          <div className="empty-list">
            {list.slice(0, 5).map((r) => (
              <button key={r.id} className="button" onClick={() => openReplay(r)}>
                {r.title}
              </button>
            ))}
          </div>
        </>
      ) : (
        <>
          <p className="muted">
            {kind === "aco"
              ? "Runs with a trace.npz in experiments/results/ become replays with:"
              : "The simulated week (stage 5) becomes a replay with:"}
          </p>
          <Command lines={[kind === "aco" ? "uv run scripts/06_export_web.py --aco" : "uv run scripts/05_simulate.py", ...(kind === "aco" ? [] : ["uv run scripts/06_export_web.py --sim"])]} />
          <p className="muted">Before the pipeline exists, a synthetic run, line and week:</p>
          <Command lines={["uv run scripts/06_export_web.py --fake"]} />
        </>
      )}
    </div>
  );
}

/** Frame rate, draw calls and students of the last second (the ` key). */
function PerfPanel() {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 500);
    return () => clearInterval(id);
  }, []);
  const p = registry.perf;
  return (
    <div className="perf-panel mono" aria-live="off">
      {p ? (
        <>
          <span className={p.fps < 50 ? "error-text" : ""}>{p.fps.toFixed(0)} fps</span> · worst {p.worstMs.toFixed(0)} ms ·{" "}
          {p.calls} calls · {(p.triangles / 1000).toFixed(0)}k tris{p.students ? ` · ${p.students.toLocaleString("en-US")} students` : ""}
        </>
      ) : (
        "measuring…"
      )}
    </div>
  );
}

export function ViewportOverlay({ scene, catalog }: { scene: Scene; catalog: ReplayCatalog | undefined }) {
  const present = useApp((s) => s.present);
  const perf = useApp((s) => s.perf !== "off");
  const camera = useApp((s) => s.camera);
  const colorMode = useApp((s) => s.colorMode);
  const roomColor = useApp((s) => s.roomColor);
  const tool = useApp((s) => s.tool);
  const showAgh = useApp((s) => s.layers.agh);
  const aerialOn = useApp((s) => s.layers.aerial);
  const opened = useApp((s) => openedBuilding(s));
  const selectedBuilding = useApp((s) => pickBuilding(s.selection));
  const level = useApp((s) => s.level);
  const workspace = useApp((s) => s.workspace);
  const networkLegend = useApp((s) => s.workspace === "network" && s.layers.network && s.colorMode !== "demand");
  const demandLegend = useApp((s) => s.colorMode === "demand" && s.layers.network);
  const split = useApp(splitActive);
  const openedB = opened ? scene.buildings.find((b) => b.id === opened) : undefined;
  const info = useBuildingInfo(openedB?.info).data;
  const interior = !!openedB && level !== null && camera !== "walk";
  const hasRooms = !!info?.levels.some((l) => l.spaces.length);

  if (present) {
    return (
      <div className="overlay">
        <div className="overlay-top-right">
          <Compass />
        </div>
        <button className="present-exit" onClick={() => app.set({ present: false })} title="Leave presentation mode (P or Esc)">
          Presentation · <kbd>P</kbd> to leave
        </button>
        <div className="overlay-bottom-right">
          {aerialOn && scene.aerial && <div className="attribution">{scene.aerial.attribution}</div>}
          <ScaleBar />
        </div>
        {split && <SplitCaptions />}
        {perf && <PerfPanel />}
        <Toasts />
      </div>
    );
  }

  if (camera === "walk") {
    return (
      <div className="overlay">
        <div className="overlay-top-right">
          <Compass />
        </div>
        <WalkHelp />
        <Toasts />
      </div>
    );
  }

  return (
    <div className="overlay">
      <div className="overlay-top-left">
        <div className="segmented" role="group" aria-label="Camera">
          <button className={camera === "orbit" ? "active" : ""} aria-pressed={camera === "orbit"} onClick={() => app.set({ camera: "orbit" })} title="Orbit camera (1)">
            <IconOrbit size={15} /> 3D
          </button>
          <button className={camera === "plan" ? "active" : ""} aria-pressed={camera === "plan"} onClick={() => app.set({ camera: "plan" })} title="Plan view (2)">
            <IconPlan size={15} /> Plan
          </button>
          <button onClick={() => app.set({ camera: "walk" })} title="Walk: first person (3)">
            <IconWalk size={15} /> Walk
          </button>
        </div>
        {interior && hasRooms ? (
          <div className="segmented" role="group" aria-label="Colour rooms by">
            {ROOM_MODES.map((m) => (
              <button key={m.id} className={roomColor === m.id ? "active" : ""} aria-pressed={roomColor === m.id} onClick={() => app.set({ roomColor: m.id })}>
                {m.label}
              </button>
            ))}
          </div>
        ) : (
          <div className="segmented" role="group" aria-label="Colour by">
            {COLOR_MODES.map((m) => (
              <button
                key={m.id}
                className={colorMode === m.id ? "active" : ""}
                aria-pressed={colorMode === m.id}
                title={m.id === "demand" ? "Colour walk-graph edges by weekly OD load" : undefined}
                onClick={() =>
                  app.set((s) => ({
                    colorMode: m.id,
                    // demand lives on the network layer
                    layers: m.id === "demand" ? { ...s.layers, network: true } : s.layers,
                  }))
                }
              >
                {m.label}
              </button>
            ))}
          </div>
        )}
        <button
          className={`tool-button ${tool === "measure" ? "active" : ""}`}
          title="Measure (M)"
          onClick={() => app.set({ tool: tool === "measure" ? "select" : "measure", measure: [] })}
        >
          <IconRuler size={15} /> Measure
        </button>
        {(workspace === "network" || tool === "route") && (
          <button
            className={`tool-button ${tool === "route" ? "active" : ""}`}
            title="Route between two points (R)"
            onClick={() => app.set({ tool: tool === "route" ? "select" : "route", rightTab: "route", rightOpen: true })}
          >
            Route
          </button>
        )}
        {workspace !== "building" && selectedBuilding && (
          <button
            className="tool-button"
            title="Open the building in the Building workspace (PageUp / PageDown)"
            onClick={() =>
              enterBuilding(selectedBuilding, scene.buildings.find((b) => b.id === selectedBuilding)?.levels.map((l) => l.id) ?? [])
            }
          >
            Open {selectedBuilding}
          </button>
        )}
        <Hint scene={scene} />
      </div>
      <div className="overlay-top-right">
        <Compass />
        <div className="view-actions" role="group" aria-label="View">
          <button className="icon-button" onClick={screenshot} title="Save a screenshot (S)" aria-label="Save a screenshot">
            <IconCamera size={16} />
          </button>
          <button className="icon-button" onClick={() => app.set({ present: true })} title="Presentation mode (P)" aria-label="Presentation mode">
            <IconPresent size={16} />
          </button>
          <button className="icon-button" onClick={() => app.set({ help: true })} title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts">
            <IconHelp size={16} />
          </button>
        </div>
        <LevelStepper scene={scene} />
      </div>
      <div className="overlay-right-panels">
        {tool === "measure" && <MeasurePanel scene={scene} />}
        <CapturePanel />
      </div>
      {demandLegend ? (
        <div className="overlay-bottom-left legend">
          <DemandLegend />
        </div>
      ) : networkLegend ? (
        <div className="overlay-bottom-left legend">
          {(Object.keys(NETWORK) as (keyof typeof NETWORK)[]).map((k) => (
            <div key={k} className="legend-row">
              <span className="swatch line" style={{ background: NETWORK[k] }} />
              {NETWORK_LABELS[k]}
            </div>
          ))}
        </div>
      ) : showAgh && (
        <div className="overlay-bottom-left legend">
          {interior && hasRooms ? (
            <RoomLegend />
          ) : (
            legend(colorMode, scene.buildings).map((e) => (
              <div key={e.label} className="legend-row">
                <span className="swatch" style={{ background: e.swatch }} />
                {e.label}
              </div>
            ))
          )}
        </div>
      )}
      <div className="overlay-bottom-right">
        {aerialOn && scene.aerial && <div className="attribution">{scene.aerial.attribution}</div>}
        <ScaleBar />
      </div>
      {split && <SplitCaptions />}
      <NoReplay catalog={catalog} />
      {perf && <PerfPanel />}
      <Toasts />
    </div>
  );
}

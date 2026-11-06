import { useEffect } from "react";
import { applyStatus } from "./data/live";
import { MissingDataError } from "./data/loader";
import { useReplays, useScene, useStatus } from "./data/resource";
import { pickBox, registry } from "./scene/registry";
import { screenshot } from "./scene/screenshot";
import { Viewport } from "./scene/Viewport";
import { app, copyCapture, enterBuilding, focusBox, openedBuilding, pickBuilding, resetView, select, setPlayback, stepLevel, toggleLayer, useApp } from "./state/app";
import { bindUrl } from "./state/url";
import { Command } from "./ui/Command";
import { HelpDialog } from "./ui/HelpDialog";
import { LeftPanel } from "./ui/LeftPanel";
import { RightPanel } from "./ui/RightPanel";
import { StatusBar } from "./ui/StatusBar";
import { iterationEnd, jumpBlock, PlaybackBar, PlaybackClock, stepClock, stepIteration, DAY_START, DAY_END } from "./ui/Timeline";
import { TopBar } from "./ui/TopBar";
import { ViewportOverlay } from "./ui/ViewportOverlay";

function levelsOf(id: string | null): number[] {
  return registry.scene?.buildings.find((b) => b.id === id)?.levels.map((l) => l.id) ?? [];
}

function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, select, textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
      const s = app.get();
      if (s.camera === "walk") return; // the walk camera owns the keyboard
      if (s.help) {
        if (e.key === "Escape" || e.key === "?") app.set({ help: false });
        return;
      }
      switch (e.key) {
        case "?":
          app.set({ help: true });
          break;
        case "p":
        case "P":
          app.set({ present: !s.present });
          break;
        case "s":
        case "S":
          screenshot();
          break;
        case "`":
          app.set({ perf: s.perf === "off" ? "on" : "off" });
          break;
        case "PageUp":
        case "PageDown":
          if (e.shiftKey && s.playback.replayId) {
            jumpBlock(e.key === "PageUp" ? -1 : 1); // the previous / next class block
            break;
          }
        {
          const id = openedBuilding(s) ?? pickBuilding(s.selection);
          if (!id) return;
          if (!openedBuilding(s)) enterBuilding(id, levelsOf(id));
          else stepLevel(levelsOf(id), e.key === "PageUp" ? 1 : -1);
          break;
        }
        case "m":
        case "M":
          app.set({ tool: s.tool === "measure" ? "select" : "measure", measure: [] });
          break;
        case "r":
        case "R":
          app.set({ tool: s.tool === "route" ? "select" : "route", rightTab: "route", rightOpen: true });
          break;
        case "3":
          app.set({ camera: "walk" });
          break;
        case "h":
        case "H":
          resetView();
          break;
        case "x":
        case "X":
          toggleLayer("xray");
          break;
        case "Enter":
          if (!s.capture) return;
          copyCapture();
          break;
        case "Backspace":
          if (s.tool === "measure" && s.measure.length) app.set({ measure: s.measure.slice(0, -1) });
          else if (s.capture?.points.length) {
            const n = s.capture.points.length - 1;
            app.set({ capture: n ? { ...s.capture, points: s.capture.points.slice(0, n), web: s.capture.web.slice(0, n) } : null });
          } else return;
          break;
        case "/":
          app.set({ searchFocus: s.searchFocus + 1 });
          break;
        case "f":
        case "F": {
          const box = s.selection && pickBox(s.selection);
          if (box) focusBox(box.min, box.max);
          break;
        }
        case "Escape":
          // clear the innermost thing first: measure points, the tool, the capture, the selection
          if (s.playback.pov) setPlayback({ pov: false });
          else if (s.present) app.set({ present: false });
          else if (s.tool === "measure" && s.measure.length) app.set({ measure: [] });
          else if (s.tool !== "select") app.set({ tool: "select" });
          else if (s.capture) app.set({ capture: null });
          else select(null);
          break;
        case "\\":
          app.set({ leftOpen: !(s.leftOpen || s.rightOpen), rightOpen: !(s.leftOpen || s.rightOpen) });
          break;
        case "1":
          app.set({ camera: "orbit" });
          break;
        case "2":
          app.set({ camera: "plan" });
          break;
        case " ":
          if (!s.playback.replayId) return;
          setPlayback({ playing: !s.playback.playing });
          break;
        case "ArrowLeft":
        case "ArrowRight":
        case "Home":
        case "End": {
          // playback steps: 15 min (Shift: 1 h) of the day, or iterations of the ant player
          if (!s.playback.replayId) return;
          const ants = s.workspace === "metro" && s.playback.acoView === "ants";
          const d = e.key === "ArrowLeft" ? -1 : 1;
          if (e.key === "Home") setPlayback(ants ? { iteration: 0 } : { t: DAY_START });
          else if (e.key === "End") setPlayback(ants ? { iteration: iterationEnd } : { t: DAY_END });
          else if (ants) stepIteration(d * (e.shiftKey ? 10 : 1), iterationEnd);
          else stepClock(d * (e.shiftKey ? 3600 : 900));
          break;
        }
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function Message({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="message-screen">
      <div className="message">
        <h1>{title}</h1>
        {children}
      </div>
    </div>
  );
}

export function App() {
  useEffect(() => bindUrl(), []);
  useShortcuts();
  const { data: scene, error } = useScene();
  const status = useStatus().data;
  useEffect(() => {
    if (status) applyStatus(status);
  }, [status]);
  const catalog = useReplays(scene?.replays).data;
  const leftOpen = useApp((s) => s.leftOpen);
  const rightOpen = useApp((s) => s.rightOpen);
  const present = useApp((s) => s.present);
  const rightWidth = useApp((s) => s.rightWidth);

  if (error) {
    return error instanceof MissingDataError ? (
      <Message title="No data exported yet">
        <p>The viewer reads web/public/data/, written by the Python pipeline:</p>
        <Command lines={["uv run scripts/02_build_campus.py", "uv run scripts/06_export_web.py --campus"]} />
        <p className="muted">Then reload this page.</p>
      </Message>
    ) : (
      <Message title="Could not load the scene">
        <pre>{String(error)}</pre>
      </Message>
    );
  }
  if (!scene) {
    return (
      <Message title="Loading the campus…">
        <p className="muted">scene.json, then the buildings and the ground.</p>
      </Message>
    );
  }

  const left = leftOpen && !present;
  const right = rightOpen && !present;
  return (
    <div
      className={`app ${left ? "" : "no-left"} ${right ? "" : "no-right"} ${present ? "present" : ""}`}
      style={{ "--right": `${rightWidth}px` } as React.CSSProperties}
    >
      {!present && <TopBar scene={scene} catalog={catalog} />}
      {left && <LeftPanel scene={scene} />}
      <main className="viewport">
        <Viewport scene={scene} />
        <ViewportOverlay scene={scene} catalog={catalog} />
        <PlaybackBar catalog={catalog} />
      </main>
      {right && <RightPanel scene={scene} catalog={catalog} />}
      {!present && <StatusBar scene={scene} />}
      <HelpDialog />
      <PlaybackClock catalog={catalog} />
    </div>
  );
}

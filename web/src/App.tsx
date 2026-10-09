import { useEffect } from "react";
import { applyStatus } from "./data/live";
import { MissingDataError } from "./data/loader";
import { useReplays, useScene, useStatus } from "./data/resource";
import { pickBox, registry } from "./scene/registry";
import { Viewport } from "./scene/Viewport";
import { app, copyCapture, enterBuilding, focusBox, openedBuilding, pickBuilding, select, setPlayback, stepLevel, useApp } from "./state/app";
import { bindUrl } from "./state/url";
import { LeftPanel } from "./ui/LeftPanel";
import { RightPanel } from "./ui/RightPanel";
import { StatusBar } from "./ui/StatusBar";
import { Timeline } from "./ui/Timeline";
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
      switch (e.key) {
        case "PageUp":
        case "PageDown": {
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
        case "3":
          app.set({ camera: "walk" });
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
          if (s.tool === "measure" && s.measure.length) app.set({ measure: [] });
          else if (s.tool === "measure") app.set({ tool: "select" });
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

  if (error) {
    return error instanceof MissingDataError ? (
      <Message title="No data exported yet">
        <p>The viewer reads web/public/data/, written by the Python pipeline:</p>
        <pre>uv run scripts/02_build_campus.py{"\n"}uv run scripts/06_export_web.py --campus</pre>
      </Message>
    ) : (
      <Message title="Could not load the scene">
        <pre>{String(error)}</pre>
      </Message>
    );
  }
  if (!scene) return <Message title="Loading…">{null}</Message>;

  return (
    <div className={`app ${leftOpen ? "" : "no-left"} ${rightOpen ? "" : "no-right"}`}>
      <TopBar scene={scene} catalog={catalog} />
      {leftOpen && <LeftPanel scene={scene} />}
      <main className="viewport">
        <Viewport scene={scene} />
        <ViewportOverlay scene={scene} />
        <Timeline catalog={catalog} />
      </main>
      {rightOpen && <RightPanel scene={scene} />}
      <StatusBar scene={scene} />
    </div>
  );
}

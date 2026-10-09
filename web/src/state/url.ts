// App state <-> location.hash, so reloads keep the view and views can be shared:
//   #ws=building&cam=plan&sel=building:D-17&replay=run-1&pose=x,y,z,tx,ty,tz,zoom

import type { Vec3 } from "../lib/frames";
import { app, type AppState, type CameraPose, type Pick, pickKey, WORKSPACE_LAYERS, WORKSPACES } from "./app";

export function parsePick(text: string | null): Pick | null {
  if (!text) return null;
  const i = text.indexOf(":");
  const kind = text.slice(0, i);
  const rest = text.slice(i + 1);
  switch (kind) {
    case "building":
      return rest ? { kind, id: rest } : null;
    case "stop":
      return rest ? { kind, id: rest } : null;
    case "context":
      return Number.isInteger(Number(rest)) ? { kind, fid: Number(rest) } : null;
    case "edge":
      return Number.isInteger(Number(rest)) ? { kind, index: Number(rest) } : null;
    case "space": {
      const m = /^([^/]+)\/(.+)@(-?\d+)$/.exec(rest);
      return m ? { kind, building: m[1]!, id: m[2]!, level: Number(m[3]) } : null;
    }
    case "entrance": {
      const [building, id] = rest.split("#");
      return building && id ? { kind, building, id } : null;
    }
    default:
      return null;
  }
}

export function parsePose(text: string | null): CameraPose | null {
  const v = text?.split(",").map(Number) ?? [];
  if (v.length !== 7 || v.some((x) => !Number.isFinite(x))) return null;
  return { position: v.slice(0, 3) as Vec3, target: v.slice(3, 6) as Vec3, zoom: v[6]! };
}

export function formatPose(p: CameraPose): string {
  return [...p.position, ...p.target].map((x) => x.toFixed(1)).concat(p.zoom.toFixed(3)).join(",");
}

export function stateFromHash(hash: string): Partial<AppState> {
  const q = new URLSearchParams(hash.replace(/^#/, ""));
  const out: Partial<AppState> = {};
  const ws = WORKSPACES.find((w) => w.id === q.get("ws"))?.id;
  if (ws) {
    out.workspace = ws;
    out.layers = WORKSPACE_LAYERS[ws];
  }
  const cam = q.get("cam");
  if (cam === "orbit" || cam === "plan") out.camera = cam;
  const level = q.get("level");
  if (level !== null && Number.isInteger(Number(level))) out.level = Number(level);
  const sel = parsePick(q.get("sel"));
  if (sel) out.selection = sel;
  const pose = parsePose(q.get("pose"));
  if (pose) out.initialPose = pose;
  const replay = q.get("replay");
  if (replay) out.playback = { ...app.get().playback, replayId: replay };
  return out;
}

let lastPose: CameraPose | null = null;

/** Called by the camera rig when the user stops moving the camera. */
export function rememberPose(pose: CameraPose): void {
  lastPose = pose;
  writeHash();
}

function writeHash(): void {
  const s = app.get();
  const q = new URLSearchParams();
  q.set("ws", s.workspace);
  if (s.camera === "plan") q.set("cam", s.camera);
  if (s.selection) q.set("sel", pickKey(s.selection));
  if (s.level !== null) q.set("level", String(s.level));
  if (s.playback.replayId) q.set("replay", s.playback.replayId);
  if (lastPose) q.set("pose", formatPose(lastPose));
  const hash = `#${q.toString()}`;
  if (hash !== location.hash) history.replaceState(null, "", hash);
}

/** Load state from the URL once, then keep the URL in sync. */
export function bindUrl(): () => void {
  app.set(stateFromHash(location.hash));
  let prev = app.get();
  return app.subscribe(() => {
    const s = app.get();
    if (
      s.workspace !== prev.workspace ||
      s.camera !== prev.camera ||
      s.selection !== prev.selection ||
      s.level !== prev.level ||
      s.playback.replayId !== prev.playback.replayId
    ) {
      writeHash();
    }
    prev = s;
  });
}

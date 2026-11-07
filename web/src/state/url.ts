// App state <-> location.hash, so reloads keep the view and views can be shared:
//   #ws=building&cam=plan&sel=building:D-17&replay=run-1&pose=x,y,z,tx,ty,tz,zoom
//   #ws=network&from=stop:miasteczko_studenckie_agh&to=D-17/1.38   (route tool)
//   #ws=metro&replay=aco-run&it=40&view=trains&day=1&t=30600       (a paused replay moment)
//   #ws=simulation&replay=sim-run&sc=no_metro&split=1&tab=stats      (scenario, split view)
//   #...&present=1&play=1&speed=60&perf=log      (presentation, autoplay, frame-rate probe)

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
    case "barrier":
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
  if (replay) {
    const p = { ...app.get().playback, replayId: replay };
    const num = (k: string) => (q.get(k) !== null && Number.isFinite(Number(q.get(k))) ? Number(q.get(k)) : null);
    p.t = num("t") ?? p.t;
    p.iteration = num("it") ?? p.iteration;
    p.weekday = num("day") ?? p.weekday;
    if (q.get("view") === "trains") p.acoView = "trains";
    const sc = q.get("sc");
    if (sc === "metro" || sc === "no_metro") p.scenario = sc;
    p.split = q.get("split") === "1";
    if (q.get("play") === "1") p.playing = true;
    p.speed = num("speed") ?? p.speed;
    p.student = num("student");
    p.follow = q.get("follow") === "1";
    out.playback = p;
    if (p.student !== null) out.rightTab = "student";
    if (q.get("tab") === "stats") out.rightTab = "stats";
  }
  if (q.get("present") === "1") out.present = true;
  if (q.get("stage") === "1") out.stage = 1;
  const perf = q.get("perf");
  if (perf === "1" || perf === "log") out.perf = perf === "log" ? "log" : "on";
  const from = q.get("from");
  const to = q.get("to");
  if (from || to) {
    out.route = { from, to, slot: from && !to ? "to" : "from" };
    out.rightTab = "route";
  }
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
  if (s.stage === 1) q.set("stage", "1");
  q.set("ws", s.workspace);
  if (s.camera === "plan") q.set("cam", s.camera);
  if (s.selection) q.set("sel", pickKey(s.selection));
  if (s.level !== null) q.set("level", String(s.level));
  const p = s.playback;
  if (p.replayId) {
    q.set("replay", p.replayId);
    q.set("day", String(p.weekday));
    if (p.acoView === "trains") q.set("view", "trains");
    // the moment of the replay, while paused (a running clock would rewrite the URL every frame)
    if (!p.playing) {
      q.set("t", String(Math.round(p.t)));
      q.set("it", String(Math.round(p.iteration * 10) / 10));
    }
    q.set("speed", String(p.speed));
    if (s.workspace === "simulation") {
      if (p.split) q.set("split", "1");
      else if (p.scenario !== "metro") q.set("sc", p.scenario);
      if (s.rightTab === "stats") q.set("tab", "stats");
      if (p.student !== null) q.set("student", String(p.student));
      if (p.follow) q.set("follow", "1");
    }
  }
  if (s.route.from) q.set("from", s.route.from);
  if (s.route.to) q.set("to", s.route.to);
  if (s.present) q.set("present", "1");
  if (s.perf !== "off") q.set("perf", s.perf === "log" ? "log" : "1");
  if (lastPose) q.set("pose", formatPose(lastPose));
  const hash = `#${q.toString()}`;
  if (hash !== location.hash) history.replaceState(null, "", hash);
}

/** Load state from the URL once, then keep the URL in sync. */
export function bindUrl(): () => void {
  app.set(stateFromHash(location.hash));
  lastPose = app.get().initialPose; // keep a shared pose until the camera moves
  let prev = app.get();
  return app.subscribe(() => {
    const s = app.get();
    if (
      s.workspace !== prev.workspace ||
      s.camera !== prev.camera ||
      s.selection !== prev.selection ||
      s.level !== prev.level ||
      s.playback.replayId !== prev.playback.replayId ||
      (!s.playback.playing && s.playback !== prev.playback) ||
      s.route.from !== prev.route.from ||
      s.route.to !== prev.route.to ||
      s.rightTab !== prev.rightTab ||
      s.present !== prev.present ||
      s.perf !== prev.perf ||
      s.stage !== prev.stage ||
      s.playback.split !== prev.playback.split ||
      s.playback.weekday !== prev.playback.weekday ||
      s.playback.acoView !== prev.playback.acoView ||
      s.playback.scenario !== prev.playback.scenario ||
      s.playback.student !== prev.playback.student ||
      s.playback.follow !== prev.playback.follow
    ) {
      writeHash();
    }
    prev = s;
  });
}

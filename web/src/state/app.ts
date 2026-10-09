// Viewer state: what is shown, what is selected, and what is being replayed.
// The UI and the 3D scene only talk through this store.

import type { Scenario } from "../generated/schemas";
import type { Vec3 } from "../lib/frames";
import { createStore, useSlice } from "./store";

export type Workspace = "campus" | "building" | "network" | "metro" | "simulation";
export type CameraMode = "orbit" | "plan" | "walk";
export type ColorMode = "category" | "lod" | "issues";
export type RoomColorMode = "kind" | "capacity";
export type Tool = "select" | "measure" | "route";
export type RightTab = "inspector" | "issues" | "route";
export type AcoView = "ants" | "trains";

export const WORKSPACES: { id: Workspace; label: string }[] = [
  { id: "campus", label: "Campus" },
  { id: "building", label: "Building" },
  { id: "network", label: "Network" },
  { id: "metro", label: "Metro" },
  { id: "simulation", label: "Simulation" },
];

export type LayerId =
  | "agh"
  | "context"
  | "ground"
  | "paths"
  | "boundary"
  | "fences"
  | "network"
  | "barriers"
  | "entrances"
  | "stops"
  | "otherStops"
  | "labels"
  | "aerial"
  | "grid"
  | "osmOutline"
  | "roomLabels";

export const LAYER_GROUPS: { title: string; layers: { id: LayerId; label: string }[] }[] = [
  {
    title: "Buildings",
    layers: [
      { id: "agh", label: "AGH buildings" },
      { id: "context", label: "Other buildings" },
      { id: "entrances", label: "Entrances" },
      { id: "labels", label: "Labels" },
    ],
  },
  {
    title: "Modelling",
    layers: [
      { id: "roomLabels", label: "Room labels" },
      { id: "grid", label: "Building grid" },
      { id: "osmOutline", label: "OSM outline" },
    ],
  },
  {
    title: "Ground",
    layers: [
      { id: "ground", label: "Ground" },
      { id: "aerial", label: "Aerial photo" },
      { id: "paths", label: "Paths and roads" },
      { id: "boundary", label: "Campus boundary" },
      { id: "fences", label: "Fences and walls" },
    ],
  },
  {
    title: "Transport",
    layers: [
      { id: "network", label: "Walk network" },
      { id: "barriers", label: "Gates and barriers" },
      { id: "stops", label: "Stops (simulation)" },
      { id: "otherStops", label: "Other stops" },
    ],
  },
];

type Layers = Record<LayerId, boolean>;

const BASE: Layers = {
  agh: true,
  context: true,
  ground: true,
  paths: true,
  boundary: true,
  fences: false,
  network: false,
  barriers: false,
  entrances: true,
  stops: true,
  otherStops: false,
  labels: true,
  aerial: false,
  grid: false,
  osmOutline: false,
  roomLabels: true,
};

/** Default layers of each workspace (applied when switching to it). */
export const WORKSPACE_LAYERS: Record<Workspace, Layers> = {
  campus: BASE,
  building: { ...BASE, labels: false, stops: false, grid: true, osmOutline: true },
  network: { ...BASE, network: true, barriers: true, fences: true, paths: false, otherStops: true, labels: false },
  metro: { ...BASE, entrances: false },
  simulation: { ...BASE, entrances: false },
};

export type Pick =
  | { kind: "building"; id: string }
  | { kind: "context"; fid: number }
  | { kind: "stop"; id: string }
  | { kind: "entrance"; building: string; id: string }
  | { kind: "space"; building: string; id: string; level: number }
  | { kind: "edge"; index: number }
  | { kind: "barrier"; index: number };

export function pickKey(p: Pick | null): string {
  if (!p) return "";
  switch (p.kind) {
    case "building":
      return `building:${p.id}`;
    case "context":
      return `context:${p.fid}`;
    case "stop":
      return `stop:${p.id}`;
    case "entrance":
      return `entrance:${p.building}#${p.id}`;
    case "space":
      return `space:${p.building}/${p.id}@${p.level}`;
    case "edge":
      return `edge:${p.index}`;
    case "barrier":
      return `barrier:${p.index}`;
  }
}

export function samePick(a: Pick | null, b: Pick | null): boolean {
  return pickKey(a) === pickKey(b);
}

export interface FocusRequest {
  seq: number;
  min: Vec3;
  max: Vec3;
}

export interface CameraPose {
  position: Vec3;
  target: Vec3;
  zoom: number; // plan camera: pixels per metre
}

export interface Playback {
  replayId: string | null;
  playing: boolean;
  speed: number; // simulated seconds per real second
  t: number; // seconds since 00:00 of the weekday (trains, students)
  iteration: number; // ACO replays: fractional iteration of the ant player
  acoView: AcoView; // ACO replays: the ants or the best line's trains
  weekday: number; // 1..5
  scenario: Scenario;
}

/** Route tool: two endpoints (endpoint keys like D-17/1.38, stop:…, or node keys). */
export interface Route {
  from: string | null;
  to: string | null;
  slot: "from" | "to"; // which end the next click in the 3D view sets
}

export interface Toast {
  id: number;
  kind: "info" | "error";
  text: string;
}

/** Points picked with Alt+Shift+click, in one building's local frame (ready for the YAML). */
export interface Capture {
  building: string;
  points: [number, number][];
  web: Vec3[]; // the same points in the scene, for drawing
}

export interface AppState {
  workspace: Workspace;
  camera: CameraMode;
  colorMode: ColorMode;
  layers: Layers;
  selection: Pick | null;
  hover: Pick | null;
  level: number | null; // active level of the opened building; null = the whole building
  roomColor: RoomColorMode;
  tool: Tool;
  measure: Vec3[]; // measure tool points (web)
  route: Route;
  capture: Capture | null;
  toasts: Toast[];
  leftOpen: boolean;
  rightOpen: boolean;
  rightTab: RightTab;
  focus: FocusRequest | null;
  initialPose: CameraPose | null; // from the URL, applied once
  cursor: Vec3 | null; // web position under the pointer
  cursorBuilding: string | null; // building under the pointer
  azimuthDeg: number; // camera heading, 0 = looking north
  metresPerPixel: number;
  playback: Playback;
  searchFocus: number; // bumped to focus the search box
  northRequest: number; // bumped by the compass: turn the camera to north-up
}

export const app = createStore<AppState>({
  workspace: "campus",
  camera: "orbit",
  colorMode: "category",
  layers: BASE,
  selection: null,
  hover: null,
  level: null,
  roomColor: "kind",
  tool: "select",
  measure: [],
  route: { from: null, to: null, slot: "from" },
  capture: null,
  toasts: [],
  leftOpen: true,
  rightOpen: true,
  rightTab: "inspector",
  focus: null,
  initialPose: null,
  cursor: null,
  cursorBuilding: null,
  azimuthDeg: 0,
  metresPerPixel: 1,
  playback: {
    replayId: null,
    playing: false,
    speed: 60,
    t: 8 * 3600,
    iteration: 0,
    acoView: "ants",
    weekday: 1,
    scenario: "metro",
  },
  searchFocus: 0,
  northRequest: 0,
});

export function useApp<S>(selector: (s: AppState) => S): S {
  return useSlice(app, selector);
}

// --- actions -------------------------------------------------------------------------

export function setWorkspace(workspace: Workspace): void {
  app.set({ workspace, layers: WORKSPACE_LAYERS[workspace] });
}

export function toggleLayer(id: LayerId): void {
  app.set((s) => ({ layers: { ...s.layers, [id]: !s.layers[id] } }));
}

/** Building a pick belongs to (building, space, entrance). */
export function pickBuilding(p: Pick | null): string | null {
  if (!p) return null;
  if (p.kind === "building") return p.id;
  if (p.kind === "space" || p.kind === "entrance") return p.building;
  return null;
}

/** The building shown open (isolated, with floors) in the Building workspace. */
export function openedBuilding(s: AppState): string | null {
  return s.workspace === "building" || s.camera === "walk" ? pickBuilding(s.selection) : null;
}

export function select(selection: Pick | null): void {
  app.set((s) => {
    const level = selection?.kind === "space" ? selection.level : pickBuilding(selection) === pickBuilding(s.selection) ? s.level : null;
    return { selection, level, rightTab: selection ? "inspector" : s.rightTab };
  });
}

/** Open a building in the Building workspace at a level (default: the entrance level). */
export function enterBuilding(id: string, levels: number[], level?: number): void {
  const ground = levels.filter((l) => l >= 0).sort((a, b) => a - b)[0] ?? levels[0] ?? null;
  app.set((s) => ({
    workspace: "building",
    layers: s.workspace === "building" ? s.layers : WORKSPACE_LAYERS.building,
    selection: s.selection && pickBuilding(s.selection) === id ? s.selection : { kind: "building", id },
    level: level ?? ground,
  }));
}

/** Step through levels: up from the top level shows the whole building again. */
export function stepLevel(levels: number[], dir: 1 | -1): void {
  const order: (number | null)[] = [...[...levels].sort((a, b) => a - b), null];
  const i = order.indexOf(app.get().level);
  const next = order[Math.max(0, Math.min(order.length - 1, (i < 0 ? order.length - 1 : i) + dir))];
  app.set({ level: next ?? null });
}

let toastSeq = 0;
export function toast(text: string, kind: Toast["kind"] = "info", ms = 3500): void {
  const id = ++toastSeq;
  app.set((s) => ({ toasts: [...s.toasts.slice(-3), { id, kind, text }] }));
  setTimeout(() => app.set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), ms);
}

let focusSeq = 0;
export function focusBox(min: Vec3, max: Vec3): void {
  app.set({ focus: { seq: ++focusSeq, min, max } });
}

export function focusPoint(p: Vec3, radius = 40): void {
  focusBox([p[0] - radius, p[1], p[2] - radius], [p[0] + radius, p[1] + radius / 2, p[2] + radius]);
}

export function setPlayback(patch: Partial<Playback>): void {
  app.set((s) => ({ playback: { ...s.playback, ...patch } }));
}

/** The captured points as a YAML flow list, ready for `path:` or `polygon:`. */
export function captureText(c: Capture): string {
  return `[${c.points.map(([x, y]) => `[${x}, ${y}]`).join(", ")}]`;
}

export function copyCapture(): void {
  const c = app.get().capture;
  if (!c?.points.length) return;
  void navigator.clipboard?.writeText(captureText(c));
  toast(`Copied ${c.points.length} points (${c.building} local)`);
}

/** Set one end of the route; the next click then sets the other end. */
export function setRouteEnd(slot: "from" | "to", key: string | null): void {
  app.set((s) => ({
    route: { ...s.route, [slot]: key, slot: slot === "from" ? "to" : "from" },
    rightTab: "route",
    rightOpen: true,
  }));
}

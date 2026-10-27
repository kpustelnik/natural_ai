// Every colour used in the 3D scene, in one place. Flat, light, architectural.
// UI colours live in theme.css; the few shared ones (accent) are repeated here on purpose.

import type { Demand, SceneBuilding } from "../generated/schemas";
import type { ColorMode } from "../state/app";

export const ACCENT = "#c8102e";

export const SCENE = {
  background: "#f4f5f6",
  ground: "#eceeef",
  road: "#dfe1e4",
  footway: "#e6e2db",
  steps: "#cfc8bd",
  boundary: "#5f656c",
  fence: "#9a9184",
  edge: "#2f3338",
  contextEdge: "#8d939a",
  context: "#d5d8db",
  slab: "#dcdad5",
  hover: "#ffffff",
  // interiors
  innerWall: "#f7f6f3",
  poche: "#3a3e44", // walls cut by the section plane
  shellInside: "#efeee9",
  flight: "#cbc5ba",
  shaft: ACCENT,
  error: "#e35d5d",
  // modelling helpers
  gridMinor: "#c9ccd1",
  gridMajor: "#9aa0a7",
  osmOutline: "#1c63b8",
  measure: ACCENT,
};

export const SPACE_KIND: Record<"corridor" | "room" | "stairs", { color: string; label: string }> = {
  corridor: { color: "#e9e6df", label: "corridor" },
  room: { color: "#fcfbf9", label: "room" },
  stairs: { color: "#d3cec5", label: "stairs" },
};

/** Rooms by capacity: a few classes, not a gradient. */
export const CAPACITY: { max: number; color: string; label: string }[] = [
  { max: 30, color: "#e3eef7", label: "up to 30" },
  { max: 80, color: "#b9d4ea", label: "31 to 80" },
  { max: 150, color: "#86b3d8", label: "81 to 150" },
  { max: Infinity, color: "#4f8cc2", label: "more than 150" },
];
export const CAPACITY_UNKNOWN = { color: "#eeeeec", label: "capacity unknown" };

/** Weekly student-leg load (heatmap). Bins are fractions of the max in the file. */
export const DEMAND: { maxFrac: number; color: string; label: string }[] = [
  { maxFrac: 0.25, color: "#ffe8a3", label: "low" },
  { maxFrac: 0.5, color: "#f5b942", label: "medium" },
  { maxFrac: 0.75, color: "#e07b39", label: "high" },
  { maxFrac: 1, color: "#c8102e", label: "highest" },
];
export const DEMAND_NONE = { color: "#eeeeec", label: "no demand data" };
export const DEMAND_ZERO = { color: "#f4f4f2", label: "no legs" };

export function demandColour(nLegs: number | undefined, maxLegs: number): string {
  if (maxLegs <= 0 || nLegs == null) return DEMAND_NONE.color;
  if (nLegs <= 0) return DEMAND_ZERO.color;
  const frac = nLegs / maxLegs;
  return DEMAND.find((b) => frac <= b.maxFrac)!.color;
}

export function indexDemand(demand: Demand | null | undefined): {
  edges: Map<number, number>;
  maxLegs: number;
  nEdges: number;
} {
  const edges = new Map<number, number>();
  let maxLegs = 0;
  if (demand) {
    maxLegs = demand.max_n_legs;
    for (const row of demand.edges) {
      edges.set(row.edge, row.n_legs);
      if (row.n_legs > maxLegs) maxLegs = row.n_legs;
    }
  }
  return { edges, maxLegs, nEdges: demand?.n_edges ?? 0 };
}

export function spaceColour(kind: string, capacity: number | null | undefined, mode: "kind" | "capacity"): string {
  if (mode === "capacity" && kind === "room") {
    if (capacity == null) return CAPACITY_UNKNOWN.color;
    return CAPACITY.find((c) => capacity <= c.max)!.color;
  }
  return SPACE_KIND[kind as keyof typeof SPACE_KIND]?.color ?? SPACE_KIND.room.color;
}

/** Wall and roof colour of an AGH building by colour mode. */
export const CATEGORY: Record<SceneBuilding["category"], { wall: string; roof: string; swatch: string }> = {
  academic: { wall: "#f1e3e0", roof: "#e3cfcb", swatch: "#d9a7a0" },
  dorm: { wall: "#e1e8f1", roof: "#cfd9e6", swatch: "#9fb5d1" },
  other: { wall: "#e8e2ef", roof: "#d8cfe2", swatch: "#b7a6cc" },
  connector: { wall: "#f2e8d5", roof: "#e5d6b9", swatch: "#d2b47c" },
};

export const LOD_COLOURS: Record<1 | 2 | 3, { wall: string; roof: string; swatch: string; label: string }> = {
  1: { wall: "#ecebe8", roof: "#dddcd8", swatch: "#c9c7c2", label: "LOD1 block" },
  2: { wall: "#dbe8f2", roof: "#c7d9e8", swatch: "#8fb3d1", label: "LOD2 corridors" },
  3: { wall: "#d9eedc", roof: "#c3e0c8", swatch: "#86bf91", label: "LOD3 rooms" },
};

export const ISSUE_COLOURS = {
  ok: { wall: "#ecebe8", roof: "#dddcd8", swatch: "#c9c7c2", label: "no issues" },
  issues: { wall: "#f6dfbd", roof: "#ebcc9d", swatch: "#e0a458", label: "has issues" },
};

/** Walk graph edges by class (network.json edge_kind_names). */
export const NETWORK = {
  footway: "#3d7a5a",
  road: "#7c838b",
  steps: "#d9480f",
  corridor: "#4f6d9a",
  door: "#8d9bb3",
  stairs: "#7a4fb0",
  entrance: "#e8a33d",
  passage: "#1c63b8",
  shaft: ACCENT,
  link: "#aab0b8",
} as const;

export const NETWORK_LABELS: Record<keyof typeof NETWORK, string> = {
  footway: "footway, path",
  road: "road, service",
  steps: "steps",
  corridor: "corridor",
  door: "room door",
  stairs: "stairs",
  entrance: "entrance",
  passage: "passage",
  shaft: "metro shaft",
  link: "link to the paths",
};

/** Route tool: the parts of a route. */
export const ROUTE_PARTS = {
  outdoor: { color: "#3d7a5a", label: "outdoor" },
  indoor: { color: "#4f6d9a", label: "indoor" },
  stairs: { color: "#7a4fb0", label: "stairs" },
} as const;

/** Metro and ACO playback. */
export const METRO = {
  tunnel: ACCENT,
  platform: "#d9d6d0",
  shaft: ACCENT,
  train: "#15181b",
  candidate: "#9aa0a7",
  chosen: ACCENT,
  ant: "#3a3f45",
  pheromone: "#2f3338",
};

/** Students by what they are doing (simulation replays). */
export const STUDENTS = [
  { color: "#2a6fb0", label: "walking" },
  { color: "#e8a33d", label: "waiting (platform or stop)" },
  { color: ACCENT, label: "riding (metro, bus, tram)" },
] as const;

/** The two scenarios in charts and the split view. */
export const SCENARIOS = {
  no_metro: { color: "#848a91", label: "No metro" },
  metro: { color: ACCENT, label: "With metro" },
} as const;

export const MARKERS = {
  entrance: "#3a3f45",
  mainEntrance: "#e8a33d",
  stop: "#1c63b8",
  otherStop: "#9aa0a6",
  barrier: "#a08a6c",
};

const DEMAND_MUTE = { wall: "#ecebe8", roof: "#dddcd8" };

export function buildingColours(b: SceneBuilding, mode: ColorMode): { wall: string; roof: string } {
  if (mode === "lod") return LOD_COLOURS[b.lod];
  if (mode === "issues") return (b.n_issues ?? 0) > 0 ? ISSUE_COLOURS.issues : ISSUE_COLOURS.ok;
  // demand heatmap is on the walk graph; mute buildings so paths stand out
  if (mode === "demand") return DEMAND_MUTE;
  return CATEGORY[b.category];
}

export interface LegendEntry {
  label: string;
  swatch: string;
}

export function legend(mode: ColorMode, buildings: SceneBuilding[]): LegendEntry[] {
  const count = (f: (b: SceneBuilding) => boolean) => buildings.filter(f).length;
  if (mode === "lod") {
    return ([1, 2, 3] as const).map((l) => ({
      label: `${LOD_COLOURS[l].label} (${count((b) => b.lod === l)})`,
      swatch: LOD_COLOURS[l].swatch,
    }));
  }
  if (mode === "issues") {
    return [
      { label: `${ISSUE_COLOURS.issues.label} (${count((b) => (b.n_issues ?? 0) > 0)})`, swatch: ISSUE_COLOURS.issues.swatch },
      { label: `${ISSUE_COLOURS.ok.label} (${count((b) => !b.n_issues)})`, swatch: ISSUE_COLOURS.ok.swatch },
    ];
  }
  if (mode === "demand") {
    return [
      ...DEMAND.map((b) => ({ label: b.label, swatch: b.color })),
      { label: DEMAND_ZERO.label, swatch: DEMAND_ZERO.color },
      { label: DEMAND_NONE.label, swatch: DEMAND_NONE.color },
    ];
  }
  return (Object.keys(CATEGORY) as SceneBuilding["category"][]).map((c) => ({
    label: `${c} (${count((b) => b.category === c)})`,
    swatch: CATEGORY[c].swatch,
  }));
}

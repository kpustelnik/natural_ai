// Loaded scene data that non-scene code needs (framing a selection, the inspector).
// Layers register what they load; nothing here triggers loading.

import { Box3, type BufferGeometry, type Object3D, Vector3 } from "three";
import type { BuildingInfo, NetworkHeader, Scene } from "../generated/schemas";
import type { Day, Frame, Paths } from "../lib/trips";
import type { Vec3 } from "../lib/frames";
import { boxAround, type Pick } from "../state/app";
import type { BinaryFile } from "../data/loader";
import { networkIndex } from "../data/network";

export const registry: {
  scene: Scene | null;
  context: BufferGeometry | null;
  network: BinaryFile<NetworkHeader> | null;
  infos: Map<string, BuildingInfo>; // building id -> loaded BuildingInfo
  split: { left: Set<Object3D>; right: Set<Object3D> }; // drawn on one half of the split view only
  onScreen: Record<string, [number, number, number, number]>; // scenario -> walking, waiting, metro, bus / tram
  frames: Record<string, { paths: Paths; day: Day; frame: Frame }>; // scenario -> the students drawn last
  studentAt: ((clientX: number, clientY: number) => number | null) | null; // the student near a click
  follow: Vector3 | null; // where the student looked at is now (the camera may follow)
  perf: Perf | null; // last second, from PerfProbe
  canvas: HTMLCanvasElement | null; // for screenshots
} = {
  scene: null,
  context: null,
  network: null,
  infos: new Map(),
  split: { left: new Set(), right: new Set() },
  onScreen: {},
  frames: {},
  studentAt: null,
  follow: null,
  perf: null,
  canvas: null,
};

export interface Perf {
  fps: number;
  worstMs: number;
  calls: number;
  triangles: number;
  students: number;
}

/** Bounding box of a pick, for framing. */
export function pickBox(p: Pick): { min: Vec3; max: Vec3 } | null {
  const scene = registry.scene;
  if (!scene) return null;
  switch (p.kind) {
    case "building": {
      const b = scene.buildings.find((x) => x.id === p.id);
      return b ? { min: b.bbox_min, max: b.bbox_max } : null;
    }
    case "stop": {
      const s = [...scene.stops, ...scene.other_stops].find((x) => x.id === p.id);
      return s ? boxAround(s.position, 60) : null;
    }
    case "entrance": {
      const e = scene.buildings.find((x) => x.id === p.building)?.entrances.find((x) => x.id === p.id);
      return e ? boxAround(e.position, 25) : null;
    }
    case "context": {
      const g = registry.context;
      const ids = g?.getAttribute("_feature_id");
      const index = g?.getIndex();
      if (!g || !ids || !index) return null;
      const pos = g.getAttribute("position");
      const box = new Box3();
      const v = new Vector3();
      // features are contiguous in the vertex buffer: scan the vertices that carry the id
      for (let i = 0; i < ids.count; i++) {
        if (ids.getX(i) === p.fid) box.expandByPoint(v.fromBufferAttribute(pos, i));
      }
      return box.isEmpty() ? null : { min: box.min.toArray() as Vec3, max: box.max.toArray() as Vec3 };
    }
    case "space": {
      const level = registry.infos.get(p.building)?.levels.find((l) => l.id === p.level);
      const sp = level?.spaces.find((x) => x.id === p.id);
      return sp ? { min: sp.bbox_min, max: sp.bbox_max } : null;
    }
    case "edge": {
      const n = registry.network;
      if (!n) return null;
      const seg = n.arrays.segment_xyz as Float32Array;
      const { segStart } = networkIndex(n);
      const box = new Box3();
      const v = new Vector3();
      for (let s = segStart[p.index]!; s < segStart[p.index + 1]!; s++) {
        box.expandByPoint(v.fromArray(seg, s * 6));
        box.expandByPoint(v.fromArray(seg, s * 6 + 3));
      }
      return box.isEmpty() ? null : { min: box.min.toArray() as Vec3, max: box.max.toArray() as Vec3 };
    }
    case "barrier": {
      const b = registry.network?.header.barriers[p.index];
      return b ? boxAround(b.position, 25) : null;
    }
  }
}

/** Draw `obj` only on one half of the split view (null: on both). Returns the cleanup. */
export function onSplitSide(obj: Object3D, side: "left" | "right" | null): () => void {
  if (!side) return () => {};
  registry.split[side].add(obj);
  return () => registry.split[side].delete(obj);
}

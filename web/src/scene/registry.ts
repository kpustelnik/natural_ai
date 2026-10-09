// Loaded scene data that non-scene code needs (framing a selection, the inspector).
// Layers register what they load; nothing here triggers loading.

import { Box3, type BufferGeometry, Vector3 } from "three";
import type { BuildingInfo, NetworkHeader, Scene } from "../generated/schemas";
import type { Vec3 } from "../lib/frames";
import type { Pick } from "../state/app";
import type { BinaryFile } from "../data/loader";

export const registry: {
  scene: Scene | null;
  context: BufferGeometry | null;
  network: BinaryFile<NetworkHeader> | null;
  infos: Map<string, BuildingInfo>; // building id -> loaded BuildingInfo
} = { scene: null, context: null, network: null, infos: new Map() };

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
      return s ? around(s.position, 60) : null;
    }
    case "entrance": {
      const e = scene.buildings.find((x) => x.id === p.building)?.entrances.find((x) => x.id === p.id);
      return e ? around(e.position, 25) : null;
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
      const edge = n.arrays.segment_edge as Uint32Array;
      const box = new Box3();
      const v = new Vector3();
      for (let s = 0; s < edge.length; s++) {
        if (edge[s] !== p.index) continue;
        box.expandByPoint(v.fromArray(seg, s * 6));
        box.expandByPoint(v.fromArray(seg, s * 6 + 3));
      }
      return box.isEmpty() ? null : { min: box.min.toArray() as Vec3, max: box.max.toArray() as Vec3 };
    }
  }
}

function around(p: Vec3, r: number): { min: Vec3; max: Vec3 } {
  return { min: [p[0] - r, p[1], p[2] - r], max: [p[0] + r, p[1] + r / 2, p[2] + r] };
}

// Snapping for the measure tool and point capture: the clicked point moves to the nearest
// vertex of the hit triangle, else to its nearest edge, else to a walk-network node, when
// one is close enough on screen.

import { type Camera, type Intersection, type Mesh, Vector3 } from "three";
import type { Vec3 } from "../../lib/frames";
import { registry } from "../registry";

const VERTEX_PX = 12;
const EDGE_PX = 7;
const NODE_PX = 10;

export type SnapKind = "vertex" | "edge" | "node" | "free";

function toScreen(p: Vector3, camera: Camera, w: number, h: number): [number, number] {
  const v = p.clone().project(camera);
  return [((v.x + 1) / 2) * w, ((1 - v.y) / 2) * h];
}

function closestOnSegment(p: Vector3, a: Vector3, b: Vector3): Vector3 {
  const ab = b.clone().sub(a);
  const t = Math.max(0, Math.min(1, p.clone().sub(a).dot(ab) / Math.max(ab.lengthSq(), 1e-12)));
  return a.clone().addScaledVector(ab, t);
}

export function snap(
  hit: Intersection,
  camera: Camera,
  width: number,
  height: number,
  useNetwork: boolean,
): { point: Vec3; kind: SnapKind } {
  const p = hit.point.clone();
  const [px, py] = toScreen(p, camera, width, height);
  const dist = (q: Vector3) => {
    const [x, y] = toScreen(q, camera, width, height);
    return Math.hypot(x - px, y - py);
  };

  const mesh = hit.object as Mesh;
  const pos = mesh.geometry?.getAttribute("position");
  if (hit.face && pos) {
    const corners = [hit.face.a, hit.face.b, hit.face.c].map((i) =>
      new Vector3().fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld),
    );
    const best = corners.reduce((a, b) => (dist(a) <= dist(b) ? a : b));
    if (dist(best) < VERTEX_PX) return { point: best.toArray() as Vec3, kind: "vertex" };
    const edges = corners.map((a, i) => closestOnSegment(p, a, corners[(i + 1) % 3]!));
    const e = edges.reduce((a, b) => (dist(a) <= dist(b) ? a : b));
    if (dist(e) < EDGE_PX) return { point: e.toArray() as Vec3, kind: "edge" };
  }

  const net = registry.network;
  if (useNetwork && net) {
    const xyz = net.arrays.node_xyz as Float32Array;
    const q = new Vector3();
    let best: Vector3 | null = null;
    let bestD = NODE_PX;
    for (let i = 0; i < xyz.length; i += 3) {
      q.set(xyz[i]!, xyz[i + 1]!, xyz[i + 2]!);
      if (q.distanceToSquared(p) > 2500) continue; // 50 m: cheap prefilter
      const d = dist(q);
      if (d < bestD) {
        bestD = d;
        best = q.clone();
      }
    }
    if (best) return { point: best.toArray() as Vec3, kind: "node" };
  }
  return { point: p.toArray() as Vec3, kind: "free" };
}

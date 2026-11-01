// The ACO player (trace.json + .bin, contract 10.6): candidate stations as pins at their
// shafts, the pheromone between candidates as ribbons (width and opacity follow tau), the
// sampled ants walking their tours, and the best line so far. Between two sampled
// iterations the pheromone is interpolated and the ants of the earlier sample walk.

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  CylinderGeometry,
  DoubleSide,
  InstancedMesh,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  MeshLambertMaterial,
  SphereGeometry,
} from "three";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import type { BinaryFile } from "../../data/loader";
import { useAcoTrace } from "../../data/resource";
import type { AcoTraceHeader } from "../../generated/schemas";
import type { Vec3 } from "../../lib/frames";
import { alongPolyline, sampleAt } from "../../lib/metro";
import { app, pickKey, useApp } from "../../state/app";
import { METRO } from "../palette";
import { setPickable } from "../picking";

type Trace = BinaryFile<AcoTraceHeader>;

const PIN_H = 14;
const PIN_R = 2.2;
const RIBBON_Y = 1.2;
const RIBBON_MAX_W = 9; // metres, at the strongest trail
const ANT_Y = 3;
const SHOW_BELOW = 0.04; // trails weaker than this share of the strongest are not drawn

interface Arrays {
  iterations: Int32Array;
  tours: Int16Array;
  best: Int16Array;
  tau: Float32Array;
  n: number;
  a: number;
  k: number;
}

function arraysOf(trace: Trace): Arrays {
  const [, a, k] = trace.header.buffers.tours!.shape as [number, number, number];
  return {
    iterations: trace.arrays.iterations as Int32Array,
    tours: trace.arrays.tours as Int16Array,
    best: trace.arrays.best_tour as Int16Array,
    tau: trace.arrays.pheromone as Float32Array,
    n: trace.header.candidate_ids.length,
    a,
    k,
  };
}

function Candidates({ trace, best }: { trace: Trace; best: number[] }) {
  const tops = trace.header.candidate_tops;
  const ids = trace.header.candidate_ids;
  const selected = useApp((s) => pickKey(s.selection));
  const mesh = useMemo(() => {
    const g = new CylinderGeometry(PIN_R, PIN_R, PIN_H, 16);
    g.translate(0, PIN_H / 2, 0);
    const m = new InstancedMesh(g, new MeshLambertMaterial(), Math.max(1, tops.length));
    const mat = new Matrix4();
    tops.forEach((p, i) => m.setMatrixAt(i, mat.makeTranslation(p[0], p[1], p[2])));
    setPickable(m, (hit) => (hit.instanceId === undefined ? null : { kind: "building", id: ids[hit.instanceId]! }));
    return m;
  }, [tops, ids]);
  useEffect(
    () => () => {
      mesh.geometry.dispose();
      (mesh.material as MeshLambertMaterial).dispose();
    },
    [mesh],
  );
  useEffect(() => {
    const c = new Color();
    const chosen = new Set(best);
    ids.forEach((id, i) => {
      c.set(chosen.has(i) ? METRO.chosen : METRO.candidate);
      if (selected === `building:${id}`) c.lerp(new Color("#000000"), 0.35);
      mesh.setColorAt(i, c);
    });
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [mesh, ids, best, selected]);
  return <primitive object={mesh} />;
}

/** Ribbons between every pair of candidates, re-shaped when the iteration changes. */
function Pheromone({ trace }: { trace: Trace }) {
  const arr = useMemo(() => arraysOf(trace), [trace]);
  const tops = trace.header.candidate_tops;
  const { mesh, pairs } = useMemo(() => {
    const pairs: [number, number][] = [];
    for (let i = 0; i < arr.n; i++) for (let j = i + 1; j < arr.n; j++) pairs.push([i, j]);
    const g = new BufferGeometry();
    g.setAttribute("position", new BufferAttribute(new Float32Array(pairs.length * 12), 3));
    g.setAttribute("color", new BufferAttribute(new Float32Array(pairs.length * 16), 4));
    const index = new Uint32Array(pairs.length * 6);
    pairs.forEach((_, p) => index.set([0, 1, 2, 0, 2, 3].map((v) => v + 4 * p), 6 * p));
    g.setIndex(new BufferAttribute(index, 1));
    const m = new Mesh(
      g,
      new MeshBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false, side: DoubleSide }),
    );
    m.frustumCulled = false;
    m.raycast = () => {};
    return { mesh: m, pairs };
  }, [arr]);
  useEffect(
    () => () => {
      mesh.geometry.dispose();
      (mesh.material as MeshBasicMaterial).dispose();
    },
    [mesh],
  );

  const last = useRef(-1);
  const color = useMemo(() => new Color(METRO.pheromone), []);
  useFrame(() => {
    const it = app.get().playback.iteration;
    if (it === last.current) return;
    last.current = it;
    const { s, f } = sampleAt(arr.iterations, it);
    const s1 = Math.min(s + 1, arr.iterations.length - 1);
    const nn = arr.n * arr.n;
    const tauAt = (i: number, j: number) => {
      const a = arr.tau[s * nn + i * arr.n + j]!;
      return a + (arr.tau[s1 * nn + i * arr.n + j]! - a) * f;
    };
    // scale between the weakest and the strongest trail: early on (all trails alike) the
    // trails are faint, and they stand out as the pheromone concentrates
    let max = 0;
    let min = Infinity;
    for (const [i, j] of pairs) {
      const v = tauAt(i, j);
      max = Math.max(max, v);
      min = Math.min(min, v);
    }
    const range = max - min > 1e-6 * max ? max - min : 0;
    const pos = mesh.geometry.getAttribute("position") as BufferAttribute;
    const col = mesh.geometry.getAttribute("color") as BufferAttribute;
    pairs.forEach(([i, j], p) => {
      const w = range > 0 ? (tauAt(i, j) - min) / range : 0.05;
      const a = tops[i]!;
      const b = tops[j]!;
      const dx = b[0] - a[0];
      const dz = b[2] - a[2];
      const len = Math.hypot(dx, dz) || 1;
      const half = w < SHOW_BELOW ? 0 : (0.4 + w * RIBBON_MAX_W) / 2;
      const nx = (-dz / len) * half;
      const nz = (dx / len) * half;
      const y0 = a[1] + RIBBON_Y;
      const y1 = b[1] + RIBBON_Y;
      pos.array.set([a[0] + nx, y0, a[2] + nz, b[0] + nx, y1, b[2] + nz, b[0] - nx, y1, b[2] - nz, a[0] - nx, y0, a[2] - nz], 12 * p);
      const alpha = w < SHOW_BELOW ? 0 : 0.08 + 0.72 * w;
      for (let v = 0; v < 4; v++) col.array.set([color.r, color.g, color.b, alpha], 16 * p + 4 * v);
    });
    pos.needsUpdate = true;
    col.needsUpdate = true;
  });
  useEffect(() => {
    last.current = -1;
  }, [mesh]);
  return <primitive object={mesh} />;
}

function Ants({ trace }: { trace: Trace }) {
  const arr = useMemo(() => arraysOf(trace), [trace]);
  const tops = trace.header.candidate_tops;
  const mesh = useMemo(() => {
    const m = new InstancedMesh(new SphereGeometry(1, 12, 8), new MeshLambertMaterial({ color: METRO.ant }), Math.max(1, arr.a));
    m.frustumCulled = false;
    m.raycast = () => {};
    return m;
  }, [arr]);
  useEffect(
    () => () => {
      mesh.geometry.dispose();
      (mesh.material as MeshLambertMaterial).dispose();
    },
    [mesh],
  );
  const last = useRef("");
  const m4 = useMemo(() => new Matrix4(), []);
  useFrame(() => {
    const it = app.get().playback.iteration;
    const r = Math.max(1.6, 3 * app.get().metresPerPixel);
    const key = `${it}/${r.toFixed(2)}`;
    if (key === last.current) return;
    last.current = key;
    const { s, f } = sampleAt(arr.iterations, it);
    // the ants of a sample walk their tours until the next sample; the last ones stay put
    const progress = s === arr.iterations.length - 1 ? 1 : f;
    for (let ant = 0; ant < arr.a; ant++) {
      const tour: Vec3[] = [];
      for (let q = 0; q < arr.k; q++) tour.push(tops[arr.tours[(s * arr.a + ant) * arr.k + q]!]!);
      if (trace.header.topology === "loop") tour.push(tour[0]!); // the ring closes, as the best line
      const p = alongPolyline(tour, progress);
      m4.makeScale(r, r, r).setPosition(p[0], p[1] + ANT_Y, p[2]);
      mesh.setMatrixAt(ant, m4);
    }
    mesh.count = arr.a;
    mesh.instanceMatrix.needsUpdate = true;
  });
  useEffect(() => {
    last.current = "";
  }, [mesh]);
  return <primitive object={mesh} />;
}

function BestLine({ trace, best }: { trace: Trace; best: number[] }) {
  const size = useThree((s) => s.size);
  const tops = trace.header.candidate_tops;
  const line = useMemo(() => {
    if (best.length < 2) return null;
    const pts = best.map((i) => tops[i]!);
    if (trace.header.topology === "loop") pts.push(pts[0]!);
    const g = new LineGeometry();
    g.setPositions(pts.flatMap((p) => [p[0], p[1] + RIBBON_Y + 0.3, p[2]]));
    const l = new Line2(g, new LineMaterial({ color: METRO.chosen, linewidth: 4 }));
    l.computeLineDistances();
    l.raycast = () => {};
    return l;
  }, [best, tops, trace]);
  useEffect(() => {
    if (line) (line.material as LineMaterial).resolution.set(size.width, size.height);
  }, [line, size]);
  useEffect(
    () => () => {
      line?.geometry.dispose();
      (line?.material as LineMaterial | undefined)?.dispose();
    },
    [line],
  );
  return line ? <primitive object={line} /> : null;
}

/** Best-so-far line at the current sample; changes only when the sample does. */
function useBestTour(trace: Trace | undefined): number[] {
  const arr = useMemo(() => (trace ? arraysOf(trace) : null), [trace]);
  const sample = useApp((s) => (arr ? sampleAt(arr.iterations, s.playback.iteration).s : 0));
  return useMemo(() => (arr ? Array.from(arr.best.subarray(sample * arr.k, (sample + 1) * arr.k)) : []), [arr, sample]);
}

export function AcoLayer({ path }: { path: string }) {
  const trace = useAcoTrace(path).data;
  const best = useBestTour(trace);
  if (!trace) return null;
  return (
    <group>
      <Candidates trace={trace} best={best} />
      <Pheromone trace={trace} />
      <BestLine trace={trace} best={best} />
      <Ants trace={trace} />
    </group>
  );
}

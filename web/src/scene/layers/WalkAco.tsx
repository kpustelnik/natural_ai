// ACO level 1 player (walk.json + .bin, contract 10.6): the peak walking flows the ants
// assigned with congestion. The walk-graph segments that carry people are drawn thick and
// coloured by load / capacity at the playback iteration (or by the pheromone, or by the
// load of the plain shortest paths for comparison), and the sampled ants of the current
// sample walk their paths node by node until the next sample.

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { Color, InstancedMesh, Matrix4, MeshLambertMaterial, SphereGeometry } from "three";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import type { BinaryFile } from "../../data/loader";
import { useNetwork, useWalkTrace } from "../../data/resource";
import type { NetworkHeader, WalkTraceHeader } from "../../generated/schemas";
import type { Vec3 } from "../../lib/frames";
import { alongPolyline, sampleAt } from "../../lib/metro";
import { app, type WalkView } from "../../state/app";
import { WALK } from "../palette";

type Trace = BinaryFile<WalkTraceHeader>;
type Net = BinaryFile<NetworkHeader>;

const LIFT = 0.8; // metres above the paths
const ANT_Y = 1.6;

export function ratioColour(r: number): string {
  return WALK.ratio.find((b) => r <= b.max)!.color;
}

/** The value of edge `e` that colours it in `view`, between two samples. */
function valueAt(trace: Trace, view: WalkView, s: number, s1: number, f: number, e: number): number {
  const E = trace.header.buffers.flow!.shape[1]!;
  if (view === "aon") return (trace.arrays.ratio_aon as Float32Array)[e]!;
  const a = (view === "pheromone" ? trace.arrays.pheromone : trace.arrays.ratio) as Float32Array;
  const v0 = a[s * E + e]!;
  return v0 + (a[s1 * E + e]! - v0) * f;
}

function Segments({ trace, net }: { trace: Trace; net: Net }) {
  const size = useThree((s) => s.size);
  // only the segments of edges that ever carry anyone (in any sample or the shortest paths)
  const { segs, edgeOf } = useMemo(() => {
    const flow = trace.arrays.flow as Float32Array;
    const aon = trace.arrays.ratio_aon as Float32Array;
    const E = trace.header.buffers.flow!.shape[1]!;
    const used = new Uint8Array(E);
    for (let i = 0; i < flow.length; i++) if (flow[i]! > 0.01) used[i % E] = 1;
    for (let e = 0; e < E; e++) if (aon[e]! > 0) used[e] = 1;
    const ids = net.arrays.segment_edge as Uint32Array;
    const xyz = net.arrays.segment_xyz as Float32Array;
    const pos: number[] = [];
    const edgeOf: number[] = [];
    for (let s = 0; s < ids.length; s++) {
      const e = ids[s]!;
      if (!used[e]) continue;
      for (let k = 0; k < 6; k++) pos.push(xyz[s * 6 + k]! + (k % 3 === 1 ? LIFT : 0));
      edgeOf.push(e);
    }
    return { segs: new Float32Array(pos), edgeOf };
  }, [trace, net]);

  const line = useMemo(() => {
    const g = new LineSegmentsGeometry();
    g.setPositions(segs);
    g.setColors(new Float32Array(segs.length));
    const l = new LineSegments2(g, new LineMaterial({ vertexColors: true, linewidth: 3.5 }));
    l.raycast = () => {};
    l.frustumCulled = false;
    return l;
  }, [segs]);
  useEffect(() => {
    (line.material as LineMaterial).resolution.set(size.width, size.height);
  }, [line, size]);
  useEffect(
    () => () => {
      line.geometry.dispose();
      (line.material as LineMaterial).dispose();
    },
    [line],
  );

  const last = useRef("");
  useFrame(() => {
    const p = app.get().playback;
    const key = `${p.iteration}/${p.walkView}`;
    if (key === last.current) return;
    last.current = key;
    const iters = trace.arrays.iterations as Int32Array;
    const { s, f } = sampleAt(iters, p.iteration);
    const s1 = Math.min(s + 1, iters.length - 1);
    const lo = new Color(WALK.pheromoneLow);
    const hi = new Color(WALK.pheromone);
    const c = new Color();
    const colors = new Float32Array(segs.length);
    for (let i = 0; i < edgeOf.length; i++) {
      const v = valueAt(trace, p.walkView, s, s1, f, edgeOf[i]!);
      if (p.walkView === "pheromone") c.copy(lo).lerp(hi, Math.min(1, Math.max(0, v)));
      else c.set(v > 0.005 ? ratioColour(v) : WALK.pheromoneLow);
      for (const k of [0, 3]) colors.set([c.r, c.g, c.b], i * 6 + k);
    }
    (line.geometry as LineSegmentsGeometry).setColors(colors);
  });
  useEffect(() => {
    last.current = "";
  }, [line]);
  return <primitive object={line} />;
}

function Ants({ trace, net }: { trace: Trace; net: Net }) {
  const nodeXyz = net.arrays.node_xyz as Float32Array;
  const sampleOff = trace.arrays.ant_sample_offsets as Uint32Array;
  const antOff = trace.arrays.ant_offsets as Uint32Array;
  const antNodes = trace.arrays.ant_nodes as Uint32Array;
  const maxAnts = useMemo(() => {
    let m = 1;
    for (let i = 0; i + 1 < sampleOff.length; i++) m = Math.max(m, sampleOff[i + 1]! - sampleOff[i]!);
    return m;
  }, [sampleOff]);
  const mesh = useMemo(() => {
    const m = new InstancedMesh(new SphereGeometry(1, 10, 6), new MeshLambertMaterial({ color: WALK.ant }), maxAnts);
    m.frustumCulled = false;
    m.raycast = () => {};
    return m;
  }, [maxAnts]);
  useEffect(
    () => () => {
      mesh.geometry.dispose();
      (mesh.material as MeshLambertMaterial).dispose();
    },
    [mesh],
  );
  const paths = useMemo(() => {
    const out: Vec3[][] = [];
    for (let p = 0; p + 1 < antOff.length; p++) {
      const pts: Vec3[] = [];
      for (let q = antOff[p]!; q < antOff[p + 1]!; q++) {
        const n = antNodes[q]!;
        pts.push([nodeXyz[n * 3]!, nodeXyz[n * 3 + 1]!, nodeXyz[n * 3 + 2]!]);
      }
      out.push(pts);
    }
    return out;
  }, [antOff, antNodes, nodeXyz]);
  const m4 = useMemo(() => new Matrix4(), []);
  const last = useRef("");
  useFrame(() => {
    const it = app.get().playback.iteration;
    const r = Math.max(1.2, 2.5 * app.get().metresPerPixel);
    const key = `${it}/${r.toFixed(2)}`;
    if (key === last.current) return;
    last.current = key;
    const iters = trace.arrays.iterations as Int32Array;
    const { s, f } = sampleAt(iters, it);
    const progress = s === iters.length - 1 ? 1 : f;
    let k = 0;
    for (let p = sampleOff[s]!; p < sampleOff[s + 1]!; p++) {
      const pts = paths[p]!;
      if (pts.length < 2) continue;
      const at = alongPolyline(pts, progress);
      m4.makeScale(r, r, r).setPosition(at[0], at[1] + ANT_Y, at[2]);
      mesh.setMatrixAt(k++, m4);
    }
    mesh.count = k;
    mesh.instanceMatrix.needsUpdate = true;
  });
  return <primitive object={mesh} />;
}

export function WalkLayer({ path, network }: { path: string; network: string }) {
  const trace = useWalkTrace(path).data;
  const net = useNetwork(network).data;
  if (!trace || !net) return null;
  return (
    <group>
      <Segments trace={trace} net={net} />
      <Ants trace={trace} net={net} />
    </group>
  );
}

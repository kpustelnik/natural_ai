// Students of a simulation replay (trips/<scenario>/, contract 10.6): one InstancedMesh of
// low cylinders, positions interpolated on the CPU every frame from the shared paths
// (lib/trips.ts). The colour says what each one is doing: walking, waiting (at a platform or
// a stop), or riding. They get bigger as the camera zooms out, so a crowd stays visible.
//
// The simulation is deterministic: everyone on the same path leaving at the same second is
// at the same point. For drawing only, such a group is laid out as a sunflower spiral around
// that point (lib/trips.ts, spiral), so its area shows its size instead of one dot.

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { Color, CylinderGeometry, DynamicDrawUsage, InstancedBufferAttribute, InstancedMesh, MeshLambertMaterial } from "three";
import { useTrips } from "../../data/resource";
import { makeFrame, peakCount, spiral, studentsAt } from "../../lib/trips";
import { app, useApp } from "../../state/app";
import { STUDENTS } from "../palette";
import { onSplitSide, registry } from "../registry";

const MIN_R = 0.35; // metres: a person, seen up close
const PX_R = 2.2; // radius in pixels when zoomed out
const HEIGHT = 1.7;
const SPACING = 1.3; // spiral spacing, in dot radii

export function Students({ dir, scenario, side }: { dir: string; scenario: string; side: "left" | "right" | null }) {
  const weekday = useApp((s) => s.playback.weekday);
  const trips = useTrips(dir, weekday).data;
  const capacity = useMemo(() => (trips ? Math.max(1, peakCount(trips.day)) : 1), [trips]);

  const mesh = useMemo(() => {
    const g = new CylinderGeometry(1, 1, 1, 10);
    g.translate(0, 0.5, 0);
    const m = new InstancedMesh(g, new MeshLambertMaterial(), capacity);
    m.instanceMatrix.setUsage(DynamicDrawUsage);
    m.instanceColor = new InstancedBufferAttribute(new Float32Array(capacity * 3), 3).setUsage(DynamicDrawUsage);
    m.count = 0;
    m.frustumCulled = false;
    m.raycast = () => {};
    return m;
  }, [capacity]);
  useEffect(
    () => () => {
      mesh.geometry.dispose();
      (mesh.material as MeshLambertMaterial).dispose();
    },
    [mesh],
  );
  useEffect(() => onSplitSide(mesh, side), [mesh, side]);

  const frame = useMemo(() => makeFrame(capacity), [capacity]);
  const colors = useMemo(() => STUDENTS.map((s) => new Color(s.color)), []);
  const off = useMemo(() => [0, 0], []);
  const last = useRef("");
  useEffect(() => {
    last.current = "";
    return () => {
      delete registry.onScreen[scenario];
    };
  }, [mesh, trips, scenario]);

  useFrame(() => {
    if (!trips) {
      mesh.count = 0;
      return;
    }
    const s = app.get();
    const t = s.playback.t;
    const r = Math.max(MIN_R, PX_R * s.metresPerPixel);
    const key = `${t}/${r.toFixed(3)}`;
    if (key === last.current) return;
    last.current = key;
    const f = studentsAt(trips.paths, trips.day, t, frame);
    const h = Math.max(HEIGHT, 1.2 * r);
    const spacing = SPACING * r;
    const m = mesh.instanceMatrix.array as Float32Array;
    const c = mesh.instanceColor!.array as Float32Array;
    for (let i = 0; i < f.n; i++) {
      // scale (r, h, r) and translation, no rotation: write the matrix directly
      const o = 16 * i;
      m[o] = r;
      m[o + 1] = m[o + 2] = m[o + 3] = m[o + 4] = 0;
      m[o + 5] = h;
      m[o + 6] = m[o + 7] = m[o + 8] = m[o + 9] = 0;
      m[o + 10] = r;
      m[o + 11] = 0;
      spiral(f.rank[i]!, off);
      m[o + 12] = f.xyz[3 * i]! + spacing * off[0]!;
      m[o + 13] = f.xyz[3 * i + 1]!;
      m[o + 14] = f.xyz[3 * i + 2]! + spacing * off[1]!;
      m[o + 15] = 1;
      const col = colors[f.state[i]!]!;
      c[3 * i] = col.r;
      c[3 * i + 1] = col.g;
      c[3 * i + 2] = col.b;
    }
    mesh.count = f.n;
    mesh.instanceMatrix.clearUpdateRanges();
    mesh.instanceMatrix.addUpdateRange(0, 16 * f.n);
    mesh.instanceMatrix.needsUpdate = true;
    mesh.instanceColor!.clearUpdateRanges();
    mesh.instanceColor!.addUpdateRange(0, 3 * f.n);
    mesh.instanceColor!.needsUpdate = true;
    registry.onScreen[scenario] = [f.counts[0], f.counts[1], f.counts[2]];
  });

  return <primitive object={mesh} />;
}

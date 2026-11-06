// Students of a simulation replay (trips/<scenario>/, contract 10.6): one InstancedMesh of
// low cylinders, positions interpolated on the CPU every frame from the shared paths
// (lib/trips.ts). The colour says what each one is doing: walking, waiting (at a platform or
// a stop), riding the metro, or a bus / tram. Their size is fixed in metres (a person, a
// little enlarged), so zooming does not change them; with the "counts" layer, crowds carry
// a label with how many are there (students binned on the screen).
//
// The simulation is deterministic: everyone on the same path leaving at the same second is
// at the same point. For drawing only, such a group is laid out as a sunflower spiral around
// that point (lib/trips.ts, spiral), so its area shows its size instead of one dot.
//
// The student looked at (playback.student) gets a marker above them; their position goes to
// registry.follow for the camera, and a click near a student picks them (registry.studentAt).

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import {
  Color,
  ConeGeometry,
  CylinderGeometry,
  DynamicDrawUsage,
  Group,
  InstancedBufferAttribute,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  MeshLambertMaterial,
  Vector3,
} from "three";
import type { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { useTrips } from "../../data/resource";
import { makeFrame, peakCount, spiral, studentsAt } from "../../lib/trips";
import { app, useApp } from "../../state/app";
import { htmlLabel } from "../Css2d";
import { ACCENT, STUDENTS } from "../palette";
import { onSplitSide, registry } from "../registry";

const R = 0.6; // metres: a person, a little enlarged so a crowd reads from afar
const HEIGHT = 1.8;
const SPACING = 1.25 * 2 * R; // between members of a group
const PICK_PX = 10; // a click this close to a student picks them
const CELL_PX = 90; // crowd labels: one per cell of this size on the screen
const MIN_CROWD = 8; // smaller groups get no label
const MAX_LABELS = 60;
const LABEL_MS = 250;

export function Students({ dir, scenario, side }: { dir: string; scenario: string; side: "left" | "right" | null }) {
  const weekday = useApp((s) => s.playback.weekday);
  const showCounts = useApp((s) => s.layers.counts);
  const trips = useTrips(dir, weekday).data;
  const capacity = useMemo(() => (trips ? Math.max(1, peakCount(trips.day)) : 1), [trips]);
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);

  const mesh = useMemo(() => {
    const g = new CylinderGeometry(R, R, HEIGHT, 10);
    g.translate(0, HEIGHT / 2, 0);
    const m = new InstancedMesh(g, new MeshLambertMaterial(), capacity);
    m.instanceMatrix.setUsage(DynamicDrawUsage);
    m.instanceColor = new InstancedBufferAttribute(new Float32Array(capacity * 3), 3).setUsage(DynamicDrawUsage);
    m.count = 0;
    m.frustumCulled = false;
    m.raycast = () => {};
    return m;
  }, [capacity]);
  // the marker of the student looked at: an upside-down cone above the head
  const marker = useMemo(() => {
    const g = new ConeGeometry(1.6, 4, 16);
    g.rotateX(Math.PI);
    g.translate(0, HEIGHT + 4, 0);
    const m = new Mesh(g, new MeshBasicMaterial({ color: ACCENT, depthTest: false, transparent: true }));
    m.renderOrder = 10;
    m.visible = false;
    m.raycast = () => {};
    return m;
  }, []);
  useEffect(
    () => () => {
      mesh.geometry.dispose();
      (mesh.material as MeshLambertMaterial).dispose();
    },
    [mesh],
  );
  useEffect(() => onSplitSide(mesh, side), [mesh, side]);
  useEffect(() => onSplitSide(marker, side), [marker, side]);

  // crowd labels, a pool reused every refresh
  const labelGroup = useMemo(() => new Group(), []);
  const labels = useMemo(() => {
    const out: CSS2DObject[] = [];
    for (let i = 0; i < MAX_LABELS; i++) {
      const l = htmlLabel("", "crowd-label crowd-count");
      l.visible = false;
      out.push(l);
    }
    return out;
  }, []);
  useEffect(() => {
    labelGroup.add(...labels);
    return () => {
      labelGroup.remove(...labels);
      for (const l of labels) l.element.remove();
    };
  }, [labelGroup, labels]);

  const frame = useMemo(() => makeFrame(capacity), [capacity]);
  const drawn = useMemo(() => new Float32Array(capacity * 3), [capacity]);
  const colors = useMemo(() => STUDENTS.map((s) => new Color(s.color)), []);
  const off = useMemo(() => [0, 0], []);
  const last = useRef(-1);
  const lastLabels = useRef(0);
  const v = useMemo(() => new Vector3(), []);
  const followPos = useMemo(() => new Vector3(), []);

  useEffect(() => {
    last.current = -1;
    return () => {
      delete registry.onScreen[scenario];
      delete registry.frames[scenario];
    };
  }, [mesh, trips, scenario]);

  // a click near a student picks them (the view with metro wins in the split view)
  useEffect(() => {
    if (side === "left") return;
    registry.studentAt = (x, y) => {
      const rect = registry.canvas?.getBoundingClientRect();
      if (!rect) return null;
      const f = frame;
      let best: number | null = null;
      let dist = PICK_PX;
      for (let i = 0; i < f.n; i++) {
        v.set(drawn[3 * i]!, drawn[3 * i + 1]! + HEIGHT / 2, drawn[3 * i + 2]!).project(camera);
        if (v.z > 1) continue;
        const sx = rect.left + ((v.x + 1) / 2) * rect.width;
        const sy = rect.top + ((1 - v.y) / 2) * rect.height;
        const d = Math.hypot(sx - x, sy - y);
        if (d < dist) [best, dist] = [f.student[i]!, d];
      }
      return best;
    };
    return () => {
      registry.studentAt = null;
    };
  }, [frame, drawn, camera, side, v]);

  useFrame(() => {
    if (!trips) {
      mesh.count = 0;
      marker.visible = false;
      return;
    }
    const s = app.get();
    const t = s.playback.t;
    const selected = s.playback.student;
    if (t !== last.current) {
      last.current = t;
      const f = studentsAt(trips.paths, trips.day, t, frame);
      const m = mesh.instanceMatrix.array as Float32Array;
      const c = mesh.instanceColor!.array as Float32Array;
      for (let i = 0; i < f.n; i++) {
        spiral(f.rank[i]!, off);
        const x = f.xyz[3 * i]! + SPACING * off[0]!;
        const y = f.xyz[3 * i + 1]!;
        const z = f.xyz[3 * i + 2]! + SPACING * off[1]!;
        drawn[3 * i] = x;
        drawn[3 * i + 1] = y;
        drawn[3 * i + 2] = z;
        const o = 16 * i; // translation only: write the matrix directly
        m[o] = m[o + 5] = m[o + 10] = m[o + 15] = 1;
        m[o + 1] = m[o + 2] = m[o + 3] = m[o + 4] = m[o + 6] = m[o + 7] = m[o + 8] = m[o + 9] = m[o + 11] = 0;
        m[o + 12] = x;
        m[o + 13] = y;
        m[o + 14] = z;
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
      registry.onScreen[scenario] = [f.counts[0], f.counts[1], f.counts[2], f.counts[3]];
      registry.frames[scenario] = { paths: trips.paths, day: trips.day, frame: f };
    }

    // the student looked at
    let found = -1;
    if (selected !== null) for (let i = 0; i < frame.n; i++) if (frame.student[i] === selected) found = i;
    marker.visible = found >= 0 && !s.playback.pov; // not in the eyes' own view
    if (found >= 0) {
      marker.position.set(drawn[3 * found]!, drawn[3 * found + 1]!, drawn[3 * found + 2]!);
      const k = Math.max(1, s.metresPerPixel / 0.4); // stays visible from afar
      marker.scale.setScalar(k);
      if (side !== "left") registry.follow = followPos.copy(marker.position);
    } else if (side !== "left") registry.follow = null;

    // crowd labels: students binned in screen cells, a label on each crowded cell
    const now = performance.now();
    if (now - lastLabels.current < LABEL_MS) return;
    lastLabels.current = now;
    if (!showCounts || side !== null) {
      for (const l of labels) l.visible = false;
      return;
    }
    const cells = new Map<number, { n: number; x: number; y: number; z: number }>();
    const cols = Math.ceil(size.width / CELL_PX) + 1;
    for (let i = 0; i < frame.n; i++) {
      v.set(drawn[3 * i]!, drawn[3 * i + 1]!, drawn[3 * i + 2]!).project(camera);
      if (v.z > 1 || Math.abs(v.x) > 1.05 || Math.abs(v.y) > 1.05) continue;
      const cx = Math.floor((((v.x + 1) / 2) * size.width) / CELL_PX);
      const cy = Math.floor((((1 - v.y) / 2) * size.height) / CELL_PX);
      const key = cy * cols + cx;
      const cell = cells.get(key);
      if (cell) {
        cell.n++;
        cell.x += drawn[3 * i]!;
        cell.y = Math.max(cell.y, drawn[3 * i + 1]!);
        cell.z += drawn[3 * i + 2]!;
      } else cells.set(key, { n: 1, x: drawn[3 * i]!, y: drawn[3 * i + 1]!, z: drawn[3 * i + 2]! });
    }
    const crowds = [...cells.values()].filter((c) => c.n >= MIN_CROWD).sort((a, b) => b.n - a.n);
    labels.forEach((l, i) => {
      const c = crowds[i];
      if (!c) {
        l.visible = false;
        return;
      }
      l.position.set(c.x / c.n, c.y + HEIGHT + 1, c.z / c.n);
      const text = String(c.n);
      if (l.element.textContent !== text) l.element.textContent = text;
      l.visible = true;
    });
  });

  return (
    <>
      <primitive object={mesh} />
      <primitive object={marker} />
      <primitive object={labelGroup} />
    </>
  );
}

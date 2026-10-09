// Helpers drawn for the opened building (Building workspace): room labels on the active
// level, a 1 m / 5 m grid in the building's local frame, and the OSM outline next to the
// modelled footprint. All of them come from buildings/<id>.json (BuildingInfo).

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import {
  BufferGeometry,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineDashedMaterial,
  LineSegments,
  Vector3,
} from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { useFileVersion } from "../../data/live";
import { useBuildingInfo } from "../../data/resource";
import type { BuildingInfo, Scene, SceneBuilding } from "../../generated/schemas";
import { localToWeb } from "../../lib/frames";
import { app, openedBuilding, pickKey, select, useApp } from "../../state/app";
import { htmlLabel } from "../Css2d";
import { ACCENT, SCENE } from "../palette";
import { noRaycast } from "../picking";

/** The opened building, its info and the web height of the active floor. */
export function useOpened(scene: Scene): { b: SceneBuilding; info: BuildingInfo | undefined; floorY: number } | null {
  const id = useApp((s) => (s.camera === "walk" ? null : openedBuilding(s)));
  const level = useApp((s) => s.level);
  const b = id ? scene.buildings.find((x) => x.id === id) : undefined;
  useFileVersion(b?.info); // re-render after a live reload of the info file
  const info = useBuildingInfo(b?.info).data;
  if (!b) return null;
  const lv = b.levels.find((l) => l.id === level);
  return { b, info: info?.id === b.id ? info : undefined, floorY: lv ? lv.floor_y : b.frame.anchor[1] };
}

function segments(points: number[], material: LineBasicMaterial | LineDashedMaterial): LineSegments {
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(points, 3));
  const l = new LineSegments(g, material);
  if (material instanceof LineDashedMaterial) l.computeLineDistances();
  noRaycast(l);
  return l;
}

function useDispose(obj: Group) {
  useEffect(
    () => () =>
      obj.traverse((o) => {
        if (o instanceof LineSegments) {
          o.geometry.dispose();
          (o.material as LineBasicMaterial).dispose();
        }
        if (o instanceof CSS2DObject) o.element.remove();
      }),
    [obj],
  );
}

// --- room labels ---------------------------------------------------------------------

interface RoomLabel {
  obj: CSS2DObject;
  key: string;
  rank: number; // higher first when labels overlap
  w: number;
  h: number;
}

export function RoomLabels({ scene }: { scene: Scene }) {
  const opened = useOpened(scene);
  const level = useApp((s) => s.level);
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const last = useRef(0);

  const { group, labels } = useMemo(() => {
    const group = new Group();
    const labels: RoomLabel[] = [];
    const lv = opened?.info?.levels.find((l) => l.id === level);
    if (!opened || !lv) return { group, labels };
    for (const sp of lv.spaces) {
      const text = sp.id;
      const sub = sp.kind === "room" ? (sp.name ?? (sp.capacity != null ? `${sp.capacity} seats` : null)) : null;
      const obj = htmlLabel(text, `room ${sp.kind}`, sub);
      const pick = { kind: "space" as const, building: opened.b.id, id: sp.id, level: lv.id };
      obj.element.addEventListener("click", () => select(pick));
      obj.center.set(0.5, 0.5);
      const h = lv.floor_y - opened.b.frame.anchor[1] + 0.1;
      obj.position.set(...localToWeb(opened.b.frame, sp.centre[0], sp.centre[1], h));
      const rank = sp.kind === "room" ? 2 + sp.area_m2 / 1e4 : sp.kind === "stairs" ? 1 : 0;
      const w = 10 + 6.5 * Math.max(text.length, sub ? sub.length * 0.85 : 0);
      labels.push({ obj, key: pickKey(pick), rank, w, h: sub ? 30 : 18 });
      group.add(obj);
    }
    labels.sort((a, b) => b.rank - a.rank);
    return { group, labels };
  }, [opened?.b, opened?.info, level]);
  useDispose(group);

  // declutter: keep the selected label, then the larger rooms, drop overlapping ones
  useFrame(() => {
    const now = performance.now();
    if (now - last.current < 120) return;
    last.current = now;
    const sel = pickKey(app.get().selection);
    const placed: [number, number, number, number][] = [];
    const v = new Vector3();
    const order = [...labels].sort((a, b) => Number(b.key === sel) - Number(a.key === sel));
    for (const l of order) {
      v.copy(l.obj.position).project(camera);
      const x = ((v.x + 1) / 2) * size.width;
      const y = ((1 - v.y) / 2) * size.height;
      const r: [number, number, number, number] = [x - l.w / 2, y - l.h / 2, x + l.w / 2, y + l.h / 2];
      const free = !placed.some((p) => r[0] < p[2] && r[2] > p[0] && r[1] < p[3] && r[3] > p[1]);
      l.obj.visible = free || l.key === sel;
      l.obj.element.classList.toggle("selected", l.key === sel);
      if (l.obj.visible) placed.push(r);
    }
  });

  return <primitive object={group} />;
}

// --- building grid -------------------------------------------------------------------

const MINOR = new LineBasicMaterial({ color: SCENE.gridMinor, transparent: true, opacity: 0.55 });
const MAJOR = new LineBasicMaterial({ color: SCENE.gridMajor, transparent: true, opacity: 0.7 });

export function BuildingGrid({ scene }: { scene: Scene }) {
  const opened = useOpened(scene);
  const b = opened?.b;
  const info = opened?.info;
  const floorY = opened?.floorY ?? 0;

  const group = useMemo(() => {
    const group = new Group();
    if (!b || !info) return group;
    const xs = info.footprint.map((p) => p[0]);
    const ys = info.footprint.map((p) => p[1]);
    const x0 = Math.floor(Math.min(...xs, 0) / 5) * 5 - 5;
    const x1 = Math.ceil(Math.max(...xs, 0) / 5) * 5 + 5;
    const y0 = Math.floor(Math.min(...ys, 0) / 5) * 5 - 5;
    const y1 = Math.ceil(Math.max(...ys, 0) / 5) * 5 + 5;
    const h = floorY - b.frame.anchor[1] + 0.06;
    const minor: number[] = [];
    const major: number[] = [];
    const axes: number[] = [];
    const push = (arr: number[], ax: number, ay: number, bx: number, by: number) =>
      arr.push(...localToWeb(b.frame, ax, ay, h), ...localToWeb(b.frame, bx, by, h));
    for (let x = x0; x <= x1; x++) push(x === 0 ? axes : x % 5 ? minor : major, x, y0, x, y1);
    for (let y = y0; y <= y1; y++) push(y === 0 ? axes : y % 5 ? minor : major, x0, y, x1, y);
    group.add(segments(minor, MINOR.clone()), segments(major, MAJOR.clone()));
    group.add(segments(axes, new LineBasicMaterial({ color: ACCENT })));
    for (const [text, x, y] of [
      ["+x", x1, 0],
      ["+y", 0, y1],
    ] as const) {
      const l = htmlLabel(text, "axis");
      l.position.set(...localToWeb(b.frame, x, y, h));
      group.add(l);
    }
    // metre ticks every 10 m along the grid's edges
    for (let x = Math.ceil(x0 / 10) * 10; x <= x1; x += 10) {
      if (x === 0) continue;
      const l = htmlLabel(String(x), "tick");
      l.position.set(...localToWeb(b.frame, x, y0, h));
      group.add(l);
    }
    for (let y = Math.ceil(y0 / 10) * 10; y <= y1; y += 10) {
      if (y === 0) continue;
      const l = htmlLabel(String(y), "tick");
      l.position.set(...localToWeb(b.frame, x0, y, h));
      group.add(l);
    }
    return group;
  }, [b, info, floorY]);
  useDispose(group);
  return <primitive object={group} />;
}

// --- OSM outline ---------------------------------------------------------------------

export function OsmOutline({ scene }: { scene: Scene }) {
  const opened = useOpened(scene);
  const b = opened?.b;
  const info = opened?.info;
  const floorY = opened?.floorY ?? 0;

  const group = useMemo(() => {
    const group = new Group();
    if (!b || !info?.osm_outline.length) return group;
    const pts: number[] = [];
    const heights = [0.2, floorY - b.frame.anchor[1] + 0.12];
    for (const h of new Set(heights)) {
      for (const ring of info.osm_outline) {
        ring.forEach((p, i) => {
          const q = ring[(i + 1) % ring.length]!;
          pts.push(...localToWeb(b.frame, p[0], p[1], h), ...localToWeb(b.frame, q[0], q[1], h));
        });
      }
    }
    const m = new LineDashedMaterial({ color: SCENE.osmOutline, dashSize: 1.2, gapSize: 0.8, depthTest: false });
    const lines = segments(pts, m);
    lines.renderOrder = 10;
    group.add(lines);
    return group;
  }, [b, info, floorY]);
  useDispose(group);
  return <primitive object={group} />;
}

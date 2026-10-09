// Drawing of the measure tool (M) and of the captured local points (Alt+Shift+click):
// an accent polyline with its points, and the length of each measured segment.

import { useEffect, useMemo } from "react";
import {
  BufferGeometry,
  Float32BufferAttribute,
  Group,
  Line,
  LineBasicMaterial,
  LineDashedMaterial,
  Points,
  PointsMaterial,
} from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import type { Vec3 } from "../../lib/frames";
import { useApp } from "../../state/app";
import { htmlLabel } from "../Css2d";
import { SCENE } from "../palette";
import { noRaycast } from "../picking";

const LIFT = 0.05; // above the clicked surface, so the line is not hidden in it

function polyline(points: Vec3[], dashed: boolean): Group {
  const group = new Group();
  if (!points.length) return group;
  const flat = points.flatMap((p) => [p[0], p[1] + LIFT, p[2]]);
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(flat, 3));
  const lineMat = dashed
    ? new LineDashedMaterial({ color: SCENE.measure, dashSize: 0.5, gapSize: 0.3, depthTest: false })
    : new LineBasicMaterial({ color: SCENE.measure, depthTest: false });
  const line = new Line(g, lineMat);
  if (dashed) line.computeLineDistances();
  const dots = new Points(g, new PointsMaterial({ color: SCENE.measure, size: 7, sizeAttenuation: false, depthTest: false }));
  line.renderOrder = dots.renderOrder = 20;
  noRaycast(line);
  noRaycast(dots);
  group.add(line, dots);
  return group;
}

function useDisposeGroup(group: Group) {
  useEffect(
    () => () =>
      group.traverse((o) => {
        if (o instanceof Line || o instanceof Points) {
          o.geometry.dispose();
          (o.material as LineBasicMaterial).dispose();
        }
        if (o instanceof CSS2DObject) o.element.remove();
      }),
    [group],
  );
}

export function segmentLength(a: Vec3, b: Vec3): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
}

export function MeasureLayer() {
  const points = useApp((s) => s.measure);
  const group = useMemo(() => {
    const group = polyline(points, false);
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1]!;
      const b = points[i]!;
      const l = htmlLabel(`${segmentLength(a, b).toFixed(2)} m`, "measure");
      l.position.set((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + LIFT, (a[2] + b[2]) / 2);
      group.add(l);
    }
    return group;
  }, [points]);
  useDisposeGroup(group);
  return <primitive object={group} />;
}

export function CaptureLayer() {
  const web = useApp((s) => s.capture?.web);
  const group = useMemo(() => polyline(web ?? [], true), [web]);
  useDisposeGroup(group);
  return <primitive object={group} />;
}

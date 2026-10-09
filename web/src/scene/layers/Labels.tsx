// HTML labels anchored in 3D: building ids and stop names. Decluttered by zoom; the
// selected building's label is always shown. Drawn by the shared Css2dLayer.

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { Group } from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import type { Scene } from "../../generated/schemas";
import { app, focusBox, type Pick, pickKey, select } from "../../state/app";
import { pickBox } from "../registry";

interface Label {
  obj: CSS2DObject;
  pick: Pick;
  maxMpp: number; // shown while metres-per-pixel is below this
}

function makeLabel(text: string, sub: string | null, cls: string, pick: Pick): CSS2DObject {
  const el = document.createElement("div");
  el.className = `label ${cls}`;
  el.textContent = text;
  if (sub) {
    const s = document.createElement("span");
    s.textContent = sub;
    el.append(s);
  }
  el.addEventListener("click", () => select(pick));
  el.addEventListener("dblclick", () => {
    const box = pickBox(pick);
    if (box) focusBox(box.min, box.max);
  });
  const obj = new CSS2DObject(el);
  obj.center.set(0.5, 1);
  return obj;
}

export function Labels({ scene, showStops }: { scene: Scene; showStops: boolean }) {
  const { group, labels } = useMemo(() => {
    const group = new Group();
    const labels: Label[] = [];
    for (const b of scene.buildings) {
      const pick: Pick = { kind: "building", id: b.id };
      const obj = makeLabel(b.id, null, `building ${b.category}`, pick);
      obj.position.set((b.bbox_min[0] + b.bbox_max[0]) / 2, b.bbox_max[1] + 1, (b.bbox_min[2] + b.bbox_max[2]) / 2);
      const maxMpp = b.category === "academic" ? 1.6 : b.category === "connector" ? 0.35 : 0.9;
      labels.push({ obj, pick, maxMpp });
    }
    if (showStops) {
      for (const s of scene.stops) {
        const pick: Pick = { kind: "stop", id: s.id };
        const obj = makeLabel(s.name, null, "stop", pick);
        obj.position.set(s.position[0], s.position[1] + 3, s.position[2]);
        labels.push({ obj, pick, maxMpp: 3 });
      }
    }
    labels.forEach((l) => group.add(l.obj));
    return { group, labels };
  }, [scene, showStops]);

  useEffect(
    () => () => {
      labels.forEach((l) => l.obj.element.remove());
    },
    [labels],
  );

  useFrame(() => {
    const s = app.get();
    const sel = pickKey(s.selection);
    for (const l of labels) {
      const key = pickKey(l.pick);
      const selected = key === sel;
      const opened = s.workspace === "building" && s.level !== null;
      l.obj.visible = !opened && (selected || s.metresPerPixel < l.maxMpp);
      l.obj.element.classList.toggle("selected", selected);
    }
  });

  return <primitive object={group} />;
}

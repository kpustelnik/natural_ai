// One CSS2DRenderer (three/addons) for every HTML label in the scene: building ids, room
// labels, measure lengths. Labels are CSS2DObjects anywhere in the scene graph.

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { splitActive, useApp } from "../state/app";

export function Css2dLayer() {
  const gl = useThree((s) => s.gl);
  const size = useThree((s) => s.size);
  const renderer = useMemo(() => {
    const r = new CSS2DRenderer();
    r.domElement.className = "labels-layer";
    return r;
  }, []);

  useEffect(() => {
    gl.domElement.parentElement?.appendChild(renderer.domElement);
    return () => renderer.domElement.remove();
  }, [gl, renderer]);
  useEffect(() => renderer.setSize(size.width, size.height), [renderer, size]);
  // labels would land on the wrong half of a split view: hide them there
  const split = useApp(splitActive);
  // and through a student's eyes the building labels would fill the view
  const pov = useApp((s) => s.playback.pov && s.camera === "orbit");
  useEffect(() => {
    renderer.domElement.style.display = split || pov ? "none" : "";
  }, [renderer, split, pov]);

  // mounted last, so it runs after the layers' frame callbacks that set label visibility
  // (a positive priority would take over the main render loop)
  useFrame(({ scene, camera }) => {
    if (!split) renderer.render(scene, camera);
  });
  return null;
}

/** A small HTML label; `cls` adds classes to the `label` element. */
export function htmlLabel(text: string, cls: string, sub?: string | null): CSS2DObject {
  const el = document.createElement("div");
  el.className = `label ${cls}`;
  el.textContent = text;
  if (sub) {
    const s = document.createElement("span");
    s.textContent = sub;
    el.append(s);
  }
  return new CSS2DObject(el);
}

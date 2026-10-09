// Ground plate, path ribbons, campus boundary and fences from campus/ground.glb.
// Only the ground plate is raycast (for the cursor position); nothing here is selectable.
// `seeThrough` makes the surfaces translucent, for the metro tunnel underneath.

import { useLoader } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { LineBasicMaterial, LineDashedMaterial, LineSegments, Mesh, MeshLambertMaterial, type Object3D } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DATA_URL } from "../../data/loader";
import { useApp } from "../../state/app";
import { buildBoundsTrees } from "../bvh";
import { SCENE } from "../palette";
import { noRaycast } from "../picking";

const SURFACES: Record<string, { color: string; offset: number }> = {
  ground: { color: SCENE.ground, offset: 0 },
  "paths:road": { color: SCENE.road, offset: -1 },
  "paths:footway": { color: SCENE.footway, offset: -2 },
  "paths:steps": { color: SCENE.steps, offset: -3 },
};

export function Ground({ glb, seeThrough = false }: { glb: string; seeThrough?: boolean }) {
  const gltf = useLoader(GLTFLoader, DATA_URL + glb);
  const layers = useApp((s) => s.layers);

  const parts = useMemo(() => {
    const byLayer = new Map<string, Object3D[]>();
    gltf.scene.traverse((o) => {
      const layer = o.userData.layer as string | undefined;
      if (!layer) return;
      byLayer.set(layer, [...(byLayer.get(layer) ?? []), o]);
      const surface = SURFACES[layer];
      if (surface && o instanceof Mesh) {
        o.material = new MeshLambertMaterial({
          color: surface.color,
          polygonOffset: surface.offset !== 0,
          polygonOffsetFactor: surface.offset,
          polygonOffsetUnits: surface.offset * 2,
        });
        if (layer === "ground") buildBoundsTrees(o);
        else noRaycast(o);
      } else if (o instanceof LineSegments) {
        o.material =
          layer === "boundary"
            ? new LineDashedMaterial({ color: SCENE.boundary, dashSize: 6, gapSize: 4 })
            : new LineBasicMaterial({ color: SCENE.fence, transparent: true, opacity: 0.8 });
        if (layer === "boundary") o.computeLineDistances();
        noRaycast(o);
      }
    });
    return byLayer;
  }, [gltf]);

  useEffect(() => {
    for (const layer of Object.keys(SURFACES)) {
      for (const o of parts.get(layer) ?? []) {
        if (!(o instanceof Mesh)) continue;
        const m = o.material as MeshLambertMaterial;
        m.transparent = seeThrough;
        m.opacity = seeThrough ? (layer === "ground" ? 0.3 : 0.45) : 1;
        m.depthWrite = !seeThrough;
        m.needsUpdate = true;
      }
    }
  }, [parts, seeThrough]);

  useEffect(() => {
    const show = (layer: string, on: boolean) => parts.get(layer)?.forEach((o) => (o.visible = on));
    show("ground", layers.ground);
    for (const l of ["paths:road", "paths:footway", "paths:steps"]) show(l, layers.paths);
    show("boundary", layers.boundary);
    show("fences", layers.fences);
  }, [parts, layers]);

  return <primitive object={gltf.scene} />;
}

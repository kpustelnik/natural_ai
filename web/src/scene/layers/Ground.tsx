// Ground plate, path ribbons, campus boundary and fences from campus/ground.glb.
// Only the ground plate is raycast (for the cursor position); nothing here is selectable.
// `seeThrough` makes the surfaces translucent, for the metro tunnel underneath.

import { useEffect, useMemo } from "react";
import { LineBasicMaterial, LineDashedMaterial, LineSegments, type Material, Mesh, MeshLambertMaterial, type Object3D } from "three";
import { useFileVersion } from "../../data/live";
import { useApp } from "../../state/app";
import { buildBoundsTrees } from "../bvh";
import { SCENE } from "../palette";
import { noRaycast } from "../picking";
import { useGlb } from "../useGlb";

const SURFACES: Record<string, { color: string; offset: number }> = {
  ground: { color: SCENE.ground, offset: 0 },
  "paths:road": { color: SCENE.road, offset: -1 },
  "paths:footway": { color: SCENE.footway, offset: -2 },
  "paths:steps": { color: SCENE.steps, offset: -3 },
};

export function Ground({ glb, seeThrough = false, visible = true }: { glb: string; seeThrough?: boolean; visible?: boolean }) {
  // a re-export (live reload) loads the new file; useGlb disposes the old geometry
  const root = useGlb(glb, useFileVersion(glb));
  const layers = useApp((s) => s.layers);

  const { parts, materials } = useMemo(() => {
    const byLayer = new Map<string, Object3D[]>();
    const materials: Material[] = [];
    root?.traverse((o) => {
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
      if (o instanceof Mesh || o instanceof LineSegments) materials.push(o.material as Material);
    });
    return { parts: byLayer, materials };
  }, [root]);
  useEffect(() => () => materials.forEach((m) => m.dispose()), [materials]);

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

  return root ? (
    <group visible={visible}>
      <primitive object={root} />
    </group>
  ) : null;
}

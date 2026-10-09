// Orthophoto underlay (campus/aerial.jpg), an axis-aligned rectangle just above the ground
// plate and below the paths. Not raycast: the cursor still reads the ground.

import { useEffect, useMemo, useState } from "react";
import { Mesh, MeshBasicMaterial, PlaneGeometry, SRGBColorSpace, type Texture, TextureLoader } from "three";
import { DATA_URL } from "../../data/loader";
import type { SceneAerial } from "../../generated/schemas";
import { noRaycast } from "../picking";

export function Aerial({ aerial }: { aerial: SceneAerial }) {
  const [texture, setTexture] = useState<Texture | null>(null);

  useEffect(() => {
    let alive = true;
    let loaded: Texture | null = null;
    new TextureLoader().loadAsync(DATA_URL + aerial.image).then((t) => {
      loaded = t;
      if (!alive) return t.dispose();
      t.colorSpace = SRGBColorSpace;
      t.anisotropy = 8;
      setTexture(t);
    });
    return () => {
      alive = false;
      loaded?.dispose();
    };
  }, [aerial.image]);

  const mesh = useMemo(() => {
    if (!texture) return null;
    const w = aerial.max[0] - aerial.min[0];
    const d = aerial.max[2] - aerial.min[2];
    const g = new PlaneGeometry(w, d);
    g.rotateX(-Math.PI / 2); // +v of the image (north) becomes -z (north)
    const m = new Mesh(g, new MeshBasicMaterial({ map: texture, polygonOffset: true, polygonOffsetFactor: -0.5 }));
    m.position.set((aerial.min[0] + aerial.max[0]) / 2, aerial.min[1], (aerial.min[2] + aerial.max[2]) / 2);
    noRaycast(m);
    return m;
  }, [texture, aerial]);

  useEffect(
    () => () => {
      if (!mesh) return;
      mesh.geometry.dispose();
      (mesh.material as MeshBasicMaterial).dispose();
    },
    [mesh],
  );

  return mesh ? <primitive object={mesh} /> : null;
}

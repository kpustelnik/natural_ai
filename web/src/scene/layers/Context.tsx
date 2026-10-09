// Every non-AGH building in one mesh (one draw call). The mesh carries _FEATURE_ID per
// vertex; hover and selection draw the feature's triangle range again in a highlight colour.

import { useLoader } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import {
  BufferGeometry,
  LineBasicMaterial,
  Mesh,
  MeshLambertMaterial,
  type Object3D,
} from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DATA_URL } from "../../data/loader";
import { useContextFeatures } from "../../data/resource";
import type { SceneContext } from "../../generated/schemas";
import { useApp } from "../../state/app";
import { buildBoundsTrees } from "../bvh";
import { SCENE } from "../palette";
import { noRaycast, setPickable } from "../picking";
import { registry } from "../registry";

function Highlight({ source, start, count, color }: { source: BufferGeometry; start: number; count: number; color: string }) {
  const { geometry, material } = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute("position", source.getAttribute("position"));
    g.setAttribute("normal", source.getAttribute("normal"));
    g.setIndex(source.getIndex());
    const m = new MeshLambertMaterial({ color, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4 });
    return { geometry: g, material: m };
  }, [source, color]);
  useEffect(() => geometry.setDrawRange(start, count), [geometry, start, count]);
  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material],
  );
  return <mesh geometry={geometry} material={material} raycast={() => {}} />;
}

export function ContextBuildings({ context }: { context: SceneContext }) {
  const gltf = useLoader(GLTFLoader, DATA_URL + context.glb);
  const features = useContextFeatures(context.features).data;
  const selected = useApp((s) => (s.selection?.kind === "context" ? s.selection.fid : null));
  const hovered = useApp((s) => (s.hover?.kind === "context" ? s.hover.fid : null));
  const ghost = useApp((s) => s.workspace === "building" && s.selection?.kind === "building");

  const { root, mesh } = useMemo(() => {
    let mesh: Mesh | null = null;
    gltf.scene.traverse((o) => {
      if (o instanceof Mesh && o.userData.part === "context") {
        o.material = new MeshLambertMaterial({ color: SCENE.context });
        mesh = o;
      } else if (o.userData.part === "edges") {
        (o as Mesh).material = new LineBasicMaterial({ color: SCENE.contextEdge, transparent: true, opacity: 0.45 });
        noRaycast(o);
      }
    });
    const m = mesh as Mesh | null;
    if (m) {
      setPickable(m, (hit) => {
        const ids = m.geometry.getAttribute("_feature_id");
        return hit.face && ids ? { kind: "context", fid: ids.getX(hit.face.a) } : null;
      });
      registry.context = m.geometry;
    }
    buildBoundsTrees(gltf.scene, true); // keep triangle order: features are index ranges
    return { root: gltf.scene as Object3D, mesh: m };
  }, [gltf]);

  useEffect(() => {
    if (!mesh) return;
    const m = mesh.material as MeshLambertMaterial;
    m.transparent = ghost;
    m.opacity = ghost ? 0.3 : 1;
    m.depthWrite = !ghost;
    m.needsUpdate = true;
  }, [mesh, ghost]);

  const range = (fid: number | null) => (fid === null ? null : features?.features[fid]);
  const sel = range(selected);
  const hov = hovered !== selected ? range(hovered) : null;

  return (
    <group>
      <primitive object={root} />
      {mesh && sel && <Highlight source={mesh.geometry} start={sel.index_start} count={sel.index_count} color="#f0c4ca" />}
      {mesh && hov && <Highlight source={mesh.geometry} start={hov.index_start} count={hov.index_count} color="#e9ebed" />}
    </group>
  );
}

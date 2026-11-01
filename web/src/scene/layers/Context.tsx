// Every non-AGH building in one mesh (one draw call). The mesh carries _FEATURE_ID per
// vertex; hover and selection draw the feature's triangle range again in a highlight colour.

import { useEffect, useMemo } from "react";
import { BufferGeometry, LineBasicMaterial, type Material, Mesh, MeshLambertMaterial } from "three";
import { useFileVersion } from "../../data/live";
import { useContextFeatures } from "../../data/resource";
import type { SceneContext } from "../../generated/schemas";
import { useApp } from "../../state/app";
import { buildBoundsTrees } from "../bvh";
import { SCENE } from "../palette";
import { noRaycast, setPickable } from "../picking";
import { registry } from "../registry";
import { useGlb } from "../useGlb";

function Highlight({ source, start, count, color }: { source: BufferGeometry; start: number; count: number; color: string }) {
  const { geometry, material } = useMemo(() => {
    const m = new MeshLambertMaterial({ color, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4 });
    return { geometry: new BufferGeometry(), material: m };
  }, [color]);
  useEffect(() => {
    // the buffers belong to the context mesh: borrow them while mounted and give them back
    // before dispose(), which would delete them on the GPU (attach here, not in useMemo, so a
    // StrictMode remount gets them again)
    geometry.setAttribute("position", source.getAttribute("position"));
    geometry.setAttribute("normal", source.getAttribute("normal"));
    geometry.setIndex(source.getIndex());
    return () => {
      geometry.setIndex(null);
      geometry.deleteAttribute("position");
      geometry.deleteAttribute("normal");
    };
  }, [geometry, source]);
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

export function ContextBuildings({ context, visible }: { context: SceneContext; visible: boolean }) {
  // a re-export (live reload) loads the new file; useGlb disposes the old geometry
  const root = useGlb(context.glb, useFileVersion(context.glb));
  const features = useContextFeatures(context.features).data;
  const selected = useApp((s) => (s.selection?.kind === "context" ? s.selection.fid : null));
  const hovered = useApp((s) => (s.hover?.kind === "context" ? s.hover.fid : null));
  const ghost = useApp((s) => s.workspace === "building" && s.selection?.kind === "building");

  const { mesh, materials } = useMemo(() => {
    let mesh: Mesh | null = null;
    const materials: Material[] = [];
    root?.traverse((o) => {
      if (o instanceof Mesh && o.userData.part === "context") {
        o.material = new MeshLambertMaterial({ color: SCENE.context });
        materials.push(o.material);
        mesh = o;
      } else if (o.userData.part === "edges") {
        (o as Mesh).material = new LineBasicMaterial({ color: SCENE.contextEdge, transparent: true, opacity: 0.45 });
        materials.push((o as Mesh).material as Material);
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
    if (root) buildBoundsTrees(root, true); // keep triangle order: features are index ranges
    return { mesh: m, materials };
  }, [root]);
  useEffect(() => () => materials.forEach((m) => m.dispose()), [materials]);

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

  if (!root) return null;
  return (
    <group visible={visible}>
      <primitive object={root} />
      {mesh && sel && <Highlight source={mesh.geometry} start={sel.index_start} count={sel.index_count} color="#f0c4ca" />}
      {mesh && hov && <Highlight source={mesh.geometry} start={hov.index_start} count={hov.index_count} color="#e9ebed" />}
    </group>
  );
}

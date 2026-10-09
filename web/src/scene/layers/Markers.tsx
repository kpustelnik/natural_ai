// Point markers: building entrances, stops and barriers, as instanced discs that keep a
// minimum size on screen when zoomed out.

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { Color, CylinderGeometry, InstancedMesh, Matrix4, MeshLambertMaterial, Vector3 } from "three";
import type { NetworkBarrier, Scene, SceneStop } from "../../generated/schemas";
import type { Vec3 } from "../../lib/frames";
import { app, type Pick, pickKey, useApp } from "../../state/app";
import { ACCENT, MARKERS } from "../palette";
import { setPickable } from "../picking";

interface Marker {
  position: Vec3;
  color: string;
  radius: number; // metres when zoomed in
  minPx: number; // minimum radius in pixels
  pick: Pick;
}

export function MarkerSet({ markers, height }: { markers: Marker[]; height: number }) {
  const selKey = useApp((s) => pickKey(s.selection));
  const hovKey = useApp((s) => pickKey(s.hover));
  const lastScale = useRef(0);

  const mesh = useMemo(() => {
    const geo = new CylinderGeometry(1, 1, height, 24);
    geo.translate(0, height / 2, 0);
    const m = new InstancedMesh(geo, new MeshLambertMaterial(), Math.max(1, markers.length));
    m.count = markers.length;
    m.frustumCulled = false;
    setPickable(m, (hit) => (hit.instanceId === undefined ? null : (markers[hit.instanceId]?.pick ?? null)));
    return m;
  }, [markers, height]);

  useEffect(() => {
    lastScale.current = 0; // a new mesh needs its matrices
    return () => {
      mesh.geometry.dispose();
      (mesh.material as MeshLambertMaterial).dispose();
    };
  }, [mesh]);

  useEffect(() => {
    const c = new Color();
    markers.forEach((mk, i) => {
      const key = pickKey(mk.pick);
      c.set(key === selKey ? ACCENT : mk.color);
      if (key === hovKey && key !== selKey) c.lerp(new Color("#ffffff"), 0.4);
      mesh.setColorAt(i, c);
    });
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [markers, mesh, selKey, hovKey]);

  useFrame(() => {
    const mpp = app.get().metresPerPixel;
    if (Math.abs(mpp - lastScale.current) / (lastScale.current || 1) < 0.02) return;
    lastScale.current = mpp;
    const m = new Matrix4();
    const s = new Vector3();
    markers.forEach((mk, i) => {
      const r = Math.max(mk.radius, mk.minPx * mpp);
      s.set(r, Math.max(1, r / mk.radius), r);
      m.makeScale(s.x, s.y, s.z).setPosition(...mk.position);
      mesh.setMatrixAt(i, m);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  });

  return <primitive object={mesh} />;
}

export function Entrances({ scene }: { scene: Scene }) {
  const markers = useMemo<Marker[]>(
    () =>
      scene.buildings.flatMap((b) =>
        b.entrances.map((e) => ({
          position: e.position,
          color: e.metro_shaft ? ACCENT : e.main ? MARKERS.mainEntrance : MARKERS.entrance,
          radius: e.main ? 1.0 : 0.7,
          minPx: e.main ? 3.5 : 2.5,
          pick: { kind: "entrance" as const, building: b.id, id: e.id },
        })),
      ),
    [scene],
  );
  return <MarkerSet markers={markers} height={0.6} />;
}

export function Stops({ stops, other }: { stops: SceneStop[]; other: boolean }) {
  const markers = useMemo<Marker[]>(
    () =>
      stops.map((s) => ({
        position: s.position,
        color: other ? MARKERS.otherStop : MARKERS.stop,
        radius: other ? 2.5 : 4,
        minPx: other ? 4 : 6,
        pick: { kind: "stop" as const, id: s.id },
      })),
    [stops, other],
  );
  return <MarkerSet markers={markers} height={1.2} />;
}

export function Barriers({ barriers }: { barriers: NetworkBarrier[] }) {
  const markers = useMemo<Marker[]>(
    () =>
      barriers.map((b, index) => ({
        position: b.position,
        color: MARKERS.barrier,
        radius: 0.4,
        minPx: 1.3,
        pick: { kind: "barrier" as const, index },
      })),
    [barriers],
  );
  return <MarkerSet markers={markers} height={0.3} />;
}

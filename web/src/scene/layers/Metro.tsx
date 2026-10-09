// The metro line of a replay (metro.json): shafts from the main entrances down to the
// platforms, the tunnel between platforms, and the trains, interpolated from the timetable
// at the playback clock every frame (no per-frame data is stored, contract 10.6).

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import {
  BoxGeometry,
  CylinderGeometry,
  Group,
  InstancedMesh,
  Matrix4,
  Mesh,
  MeshLambertMaterial,
  Quaternion,
  Vector3,
} from "three";
import { useMetro } from "../../data/resource";
import type { Metro } from "../../generated/schemas";
import { dayRuns, trainsAt } from "../../lib/metro";
import { app, useApp } from "../../state/app";
import { METRO } from "../palette";
import { setPickable } from "../picking";
import { onSplitSide } from "../registry";

const TUNNEL_R = 2.4;
const TRAIN = { length: 24, width: 2.8, height: 3.2 };
const PLATFORM = { length: 40, width: 8, height: 0.6 };
const SHAFT_SIDE = 5;
const UP = new Vector3(0, 1, 0);

function heading(a: number[], b: number[]): number {
  return Math.atan2(b[0]! - a[0]!, b[2]! - a[2]!);
}

/** Shafts, platforms and the tunnel: static meshes built once per metro.json. */
function buildLine(metro: Metro): { group: Group; dispose: () => void } {
  const group = new Group();
  const tunnelMat = new MeshLambertMaterial({ color: METRO.tunnel, transparent: true, opacity: 0.55 });
  const shaftMat = new MeshLambertMaterial({ color: METRO.shaft, transparent: true, opacity: 0.35, depthWrite: false });
  const platformMat = new MeshLambertMaterial({ color: METRO.platform });
  const geos: (BoxGeometry | CylinderGeometry)[] = [];

  const t = metro.tunnel;
  for (let i = 0; i + 1 < t.length; i++) {
    const a = new Vector3(...t[i]!);
    const b = new Vector3(...t[i + 1]!);
    const len = a.distanceTo(b);
    const g = new CylinderGeometry(TUNNEL_R, TUNNEL_R, len, 16, 1, true);
    geos.push(g);
    const m = new Mesh(g, tunnelMat);
    m.position.copy(a).add(b).multiplyScalar(0.5).y += TUNNEL_R;
    m.quaternion.setFromUnitVectors(UP, b.clone().sub(a).normalize());
    m.raycast = () => {};
    group.add(m);
  }

  metro.stations.forEach((s, i) => {
    const depth = s.top[1] - s.platform[1];
    const shaftGeo = new BoxGeometry(SHAFT_SIDE, depth, SHAFT_SIDE);
    geos.push(shaftGeo);
    const shaft = new Mesh(shaftGeo, shaftMat);
    shaft.position.set(s.top[0], s.platform[1] + depth / 2, s.top[2]);
    setPickable(shaft, () => ({ kind: "building", id: s.building_id }));
    group.add(shaft);

    const prev = metro.stations[i - 1]?.platform;
    const next = metro.stations[i + 1]?.platform;
    const dir = next ? heading(s.platform, next) : prev ? heading(prev, s.platform) : 0;
    const platGeo = new BoxGeometry(PLATFORM.width, PLATFORM.height, PLATFORM.length);
    geos.push(platGeo);
    const plat = new Mesh(platGeo, platformMat);
    plat.position.set(s.platform[0], s.platform[1] + PLATFORM.height / 2, s.platform[2]);
    plat.rotation.y = dir;
    plat.translateX(TUNNEL_R + PLATFORM.width / 2 - 1);
    setPickable(plat, () => ({ kind: "building", id: s.building_id }));
    group.add(plat);
  });
  return {
    group,
    dispose: () => {
      geos.forEach((g) => g.dispose());
      [tunnelMat, shaftMat, platformMat].forEach((m) => m.dispose());
    },
  };
}

function Trains({ metro }: { metro: Metro }) {
  const weekday = useApp((s) => s.playback.weekday);
  const day = useMemo(() => dayRuns(metro, weekday), [metro, weekday]);
  const capacity = Math.max(1, Math.min(512, day.runs.length));
  const mesh = useMemo(() => {
    const m = new InstancedMesh(
      new BoxGeometry(TRAIN.width, TRAIN.height, TRAIN.length),
      new MeshLambertMaterial({ color: METRO.train }),
      capacity,
    );
    m.count = 0;
    m.frustumCulled = false;
    m.raycast = () => {};
    return m;
  }, [capacity]);
  useEffect(
    () => () => {
      mesh.geometry.dispose();
      (mesh.material as MeshLambertMaterial).dispose();
    },
    [mesh],
  );

  const last = useRef(-1);
  const m4 = useMemo(() => new Matrix4(), []);
  const q = useMemo(() => new Quaternion(), []);
  const pos = useMemo(() => new Vector3(), []);
  const one = useMemo(() => new Vector3(1, 1, 1), []);
  useFrame(() => {
    const t = app.get().playback.t;
    if (t === last.current) return;
    last.current = t;
    const trains = trainsAt(metro, day, t);
    const n = Math.min(trains.length, capacity);
    for (let i = 0; i < n; i++) {
      const tr = trains[i]!;
      q.setFromAxisAngle(UP, tr.heading);
      pos.set(tr.position[0], tr.position[1] + TRAIN.height / 2 + 0.4, tr.position[2]);
      mesh.setMatrixAt(i, m4.compose(pos, q, one));
    }
    mesh.count = n;
    mesh.instanceMatrix.needsUpdate = true;
  });
  useEffect(() => {
    last.current = -1; // a new day or mesh: redraw on the next frame
  }, [mesh, day]);

  return <primitive object={mesh} />;
}

export function MetroLayer({ path, side }: { path: string; side: "left" | "right" | null }) {
  const metro = useMetro(path).data;
  const line = useMemo(() => (metro ? buildLine(metro) : null), [metro]);
  useEffect(() => () => line?.dispose(), [line]);
  const group = useRef<Group>(null);
  useEffect(() => (group.current ? onSplitSide(group.current, side) : undefined), [side, line]);
  if (!metro || !line) return null;
  return (
    <group ref={group}>
      <primitive object={line.group} />
      <Trains metro={metro} />
    </group>
  );
}

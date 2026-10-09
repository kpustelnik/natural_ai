// The 3D view: canvas, lights, cameras, layers and pointer interaction (hover, select,
// measure, point capture, cursor position). Layers only draw; state lives in the store.

import { Canvas, type ThreeEvent } from "@react-three/fiber";
import { Suspense, useEffect, useMemo } from "react";
import type { Intersection, Object3D } from "three";
import { useNetwork } from "../data/resource";
import type { Scene } from "../generated/schemas";
import { type Vec3, webToLocal } from "../lib/frames";
import {
  app,
  type FocusRequest,
  focusBox,
  openedBuilding,
  type Pick,
  pickBuilding,
  samePick,
  select,
  toast,
  useApp,
} from "../state/app";
import { CameraRig } from "./CameraRig";
import { Css2dLayer } from "./Css2d";
import { Aerial } from "./layers/Aerial";
import { BuildingGrid, OsmOutline, RoomLabels } from "./layers/BuildingHelpers";
import { Buildings } from "./layers/Buildings";
import { ContextBuildings } from "./layers/Context";
import { Ground } from "./layers/Ground";
import { Labels } from "./layers/Labels";
import { Entrances, Stops } from "./layers/Markers";
import { Network } from "./layers/Network";
import { SCENE } from "./palette";
import { resolvePick } from "./picking";
import { pickBox, registry } from "./registry";
import { snap } from "./tools/snap";
import { CaptureLayer, MeasureLayer } from "./tools/Tools";

const CLICK_PX = 4;

/** Hidden objects and parts cut away by a building's section plane cannot be hit. */
function hitVisible(h: Intersection): boolean {
  for (let o: Object3D | null = h.object; o; o = o.parent) {
    if (!o.visible) return false;
    const clipY = o.userData.clipY as number | undefined;
    if (clipY !== undefined && h.point.y > clipY + 1e-3) return false;
  }
  return true;
}

function firstHit(e: ThreeEvent<PointerEvent | MouseEvent>): { hit: Intersection | null; pick: Pick | null } {
  const hit = e.intersections.find(hitVisible) ?? null;
  return { hit, pick: hit ? resolvePick(hit) : null };
}

const fmt = (v: number) => Math.round(v * 10) / 10;

function canvasSize(e: ThreeEvent<MouseEvent>): [number, number] {
  const el = e.nativeEvent.target as HTMLElement | null;
  return [el?.clientWidth || 1, el?.clientHeight || 1];
}

/** Building whose local frame a captured point is expressed in. */
function captureBuilding(pick: Pick | null): string | null {
  const s = app.get();
  return pickBuilding(pick) ?? openedBuilding(s) ?? pickBuilding(s.selection);
}

function capturePoint(e: ThreeEvent<MouseEvent>, hit: Intersection, pick: Pick | null) {
  const id = captureBuilding(pick);
  const b = id ? registry.scene?.buildings.find((x) => x.id === id) : undefined;
  if (!b) {
    toast("Alt+click a building (or select one) to read local coordinates", "error");
    return;
  }
  const point = snap(hit, e.camera, ...canvasSize(e), false).point;
  const [x, y] = webToLocal(b.frame, point);
  const xy: [number, number] = [fmt(x), fmt(y)];
  if (e.shiftKey) {
    app.set((s) => {
      const same = s.capture?.building === b.id;
      return {
        capture: {
          building: b.id,
          points: [...(same ? s.capture!.points : []), xy],
          web: [...(same ? s.capture!.web : []), point],
        },
      };
    });
    return;
  }
  const text = `[${xy[0]}, ${xy[1]}]`;
  void navigator.clipboard?.writeText(text);
  toast(`Copied ${text}  (${b.id} local)`);
}

// R3F calls a group's handlers once per object under the pointer: each handler stops the
// propagation and looks at e.intersections itself.
function Interaction({ children }: { children: React.ReactNode }) {
  const onMove = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    if (app.get().camera === "walk") return;
    const { hit, pick } = firstHit(e);
    const s = app.get();
    const cursor = hit ? (hit.point.toArray() as Vec3) : null;
    const building = pickBuilding(pick);
    app.set({
      cursor,
      cursorBuilding: building,
      ...(samePick(pick, s.hover) ? {} : { hover: pick }),
    });
  };
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    const s = app.get();
    if (e.delta > CLICK_PX || s.camera === "walk") return;
    const { hit, pick } = firstHit(e);
    if (e.altKey) {
      if (hit) capturePoint(e, hit, pick);
      return;
    }
    if (s.tool === "measure") {
      if (!hit) return;
      const p = snap(hit, e.camera, ...canvasSize(e), s.layers.network).point;
      app.set({ measure: [...s.measure, p] });
      return;
    }
    select(pick);
  };
  const onDoubleClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    const s = app.get();
    if (s.tool === "measure" || s.camera === "walk") return;
    const { hit, pick } = firstHit(e);
    const box = pick ? pickBox(pick) : null;
    if (box) focusBox(box.min, box.max);
    else if (hit) {
      const p = hit.point;
      focusBox([p.x - 60, 0, p.z - 60], [p.x + 60, 30, p.z + 60]);
    }
  };
  const onLeave = () => app.set({ hover: null, cursor: null, cursorBuilding: null });
  return (
    <group onPointerMove={onMove} onClick={onClick} onDoubleClick={onDoubleClick} onPointerLeave={onLeave}>
      {children}
    </group>
  );
}

function NetworkLayer({ path }: { path: string }) {
  const net = useNetwork(path).data;
  return net ? <Network net={net} /> : null;
}

export function Viewport({ scene }: { scene: Scene }) {
  const layers = useApp((s) => s.layers);
  const tool = useApp((s) => s.tool);
  const hasCapture = useApp((s) => s.capture !== null);
  const opened = useApp((s) => (s.camera === "walk" ? null : openedBuilding(s)));
  // a basement is under the ground plate: hide the ground while it is the active level
  const underground = useApp((s) => {
    const id = openedBuilding(s);
    if (!id || s.level === null || s.camera === "walk") return false;
    const b = scene.buildings.find((x) => x.id === id);
    const lv = b?.levels.find((l) => l.id === s.level);
    return !!b && !!lv && lv.floor_y < b.frame.anchor[1] - 0.5;
  });
  registry.scene = scene;

  // first view: all AGH buildings
  const home = useMemo<FocusRequest>(() => {
    const min: Vec3 = [Infinity, 0, Infinity];
    const max: Vec3 = [-Infinity, 0, -Infinity];
    for (const b of scene.buildings) {
      for (const i of [0, 1, 2] as const) {
        min[i] = Math.min(min[i], b.bbox_min[i]);
        max[i] = Math.max(max[i], b.bbox_max[i]);
      }
    }
    if (!scene.buildings.length) return { seq: 0, min: scene.extent.min, max: scene.extent.max };
    return { seq: 0, min, max: [max[0], 0, max[2]] };
  }, [scene]);

  // a selection from the URL without a camera pose: frame it once
  useEffect(() => {
    const s = app.get();
    if (s.selection && !s.initialPose) {
      const box = pickBox(s.selection);
      if (box) focusBox(box.min, box.max);
    }
  }, []);

  return (
    <Canvas
      flat
      dpr={[1, 2]}
      gl={{ antialias: true, preserveDrawingBuffer: true, localClippingEnabled: true }}
      onPointerMissed={(e) => {
        if (app.get().tool !== "measure" && !e.altKey) select(null);
      }}
      style={{ cursor: tool === "measure" ? "crosshair" : undefined }}
    >
      <color attach="background" args={[SCENE.background]} />
      <hemisphereLight args={["#ffffff", "#c9c6bf", 2.2]} />
      <directionalLight position={[-400, 700, 250]} intensity={1.6} />
      <CameraRig home={home} />
      <Interaction>
        <Suspense fallback={null}>{scene.ground_glb && !underground && <Ground glb={scene.ground_glb} />}</Suspense>
        {layers.agh && <Buildings scene={scene} />}
        <Suspense fallback={null}>{layers.context && scene.context && <ContextBuildings context={scene.context} />}</Suspense>
        {layers.network && scene.network && <NetworkLayer path={scene.network} />}
        {layers.entrances && layers.agh && <Entrances scene={scene} />}
        {layers.stops && <Stops stops={scene.stops} other={false} />}
        {layers.otherStops && <Stops stops={scene.other_stops} other />}
      </Interaction>
      {layers.aerial && scene.aerial && !underground && <Aerial aerial={scene.aerial} />}
      {opened && layers.grid && <BuildingGrid scene={scene} />}
      {opened && layers.osmOutline && <OsmOutline scene={scene} />}
      {opened && layers.roomLabels && <RoomLabels scene={scene} />}
      <MeasureLayer />
      {hasCapture && <CaptureLayer />}
      {layers.labels && layers.agh && <Labels scene={scene} showStops={layers.stops} />}
      <Css2dLayer />
    </Canvas>
  );
}

// Cameras sharing one target: an orbit (perspective) camera, a top-down plan
// (orthographic) camera with north up (or, for an opened building, its +x axis to the
// right, so walls look axis-aligned), and the first-person walk camera (WalkRig).
// Handles framing requests and reports the view (heading, scale) to the store for the
// compass and the scale bar.

import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MOUSE, OrthographicCamera, PerspectiveCamera, Vector3 } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Vec3 } from "../lib/frames";
import { app, type FocusRequest, openedBuilding, splitActive, useApp } from "../state/app";
import { rememberPose } from "../state/url";
import { registry } from "./registry";
import { type WalkStart, WalkRig } from "./WalkRig";

const FOV = 40;
const ANIM_MS = 450;
// with "reduce motion" set in the OS, the camera jumps instead of flying
const REDUCED = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const PLAN_HEIGHT = 3000;
const DEFAULT_DIR = new Vector3(0.25, 0.75, 0.62).normalize(); // from south-south-east, 50 deg up

interface Flight {
  t0: number;
  fromPos: Vector3;
  fromTarget: Vector3;
  toPos: Vector3;
  toTarget: Vector3;
  fromZoom: number;
  toZoom: number;
}

const ease = (t: number) => 1 - (1 - t) ** 3;

/** Direction (web, horizontal) that the plan view shows at the top of the screen. */
function planUpOf(bearingDeg: number | null): Vector3 {
  if (bearingDeg === null) return new Vector3(0, 0, -1); // north
  const b = (bearingDeg * Math.PI) / 180;
  return new Vector3(-Math.cos(b), 0, -Math.sin(b)); // the building's local +y
}

function planOffset(up: Vector3): Vector3 {
  // looking straight down, tilted a hair towards `up`, so OrbitControls keeps it on top
  return new Vector3(0, PLAN_HEIGHT, 0).addScaledVector(up, -1e-3);
}

/** Where the walk starts: just inside the opened building's main entrance, or at the
 * orbit target. */
function walkStart(target: Vector3, camera: PerspectiveCamera): WalkStart {
  const id = openedBuilding(app.get());
  const b = id ? registry.scene?.buildings.find((x) => x.id === id) : undefined;
  const e = b?.entrances.find((x) => x.main) ?? b?.entrances[0];
  if (b && e) {
    const centre = new Vector3((b.bbox_min[0] + b.bbox_max[0]) / 2, e.position[1], (b.bbox_min[2] + b.bbox_max[2]) / 2);
    const look = centre.sub(new Vector3(...e.position)).setY(0).normalize();
    return { feet: new Vector3(...e.position).addScaledVector(look, 1.5), look };
  }
  const look = camera.getWorldDirection(new Vector3()).setY(0);
  if (look.lengthSq() < 1e-6) look.set(0, 0, -1);
  return { feet: target.clone().setY(0), look: look.normalize() };
}
export function CameraRig({ home }: { home: FocusRequest }) {
  const mode = useApp((s) => s.camera);
  const alignBearing = useApp((s) => {
    const id = s.workspace === "building" ? openedBuilding(s) : null;
    return id ? (registry.scene?.buildings.find((b) => b.id === id)?.frame.bearing_deg ?? null) : null;
  });
  const planUp = useMemo(() => planUpOf(alignBearing), [alignBearing]);
  const [walk, setWalk] = useState<WalkStart | null>(null);
  const focus = useApp((s) => s.focus);
  const northRequest = useApp((s) => s.northRequest);
  const set = useThree((s) => s.set);
  const canvas = useThree((s) => s.size);
  // the split view draws the scene twice, each half with its own projection
  const split = useApp(splitActive);
  const size = useMemo(
    () => ({ width: split ? Math.floor(canvas.width / 2) : canvas.width, height: canvas.height }),
    [split, canvas.width, canvas.height],
  );
  const dom = useThree((s) => s.gl.domElement);

  const cams = useMemo(() => {
    const persp = new PerspectiveCamera(FOV, 1, 1, 20000);
    const ortho = new OrthographicCamera(-1, 1, 1, -1, 1, 20000);
    return { persp, ortho };
  }, []);
  const controls = useRef<OrbitControls | null>(null);
  const target = useRef(new Vector3());
  const flight = useRef<Flight | null>(null);
  const lastReport = useRef({ azimuth: NaN, mpp: NaN, time: 0 });
  const sizeRef = useRef(size);
  sizeRef.current = size;

  // first view: pose from the URL, else the home box
  const started = useRef(false);
  if (!started.current) {
    started.current = true;
    const pose = app.get().initialPose;
    if (pose) {
      cams.persp.position.set(...pose.position);
      target.current.set(...pose.target);
      cams.ortho.zoom = pose.zoom;
    } else {
      const { pos, tgt } = frameBox(home.min, home.max, DEFAULT_DIR, 0.8);
      cams.persp.position.copy(pos);
      target.current.copy(tgt);
      cams.ortho.zoom = planZoom(home.min, home.max, size.width, size.height);
    }
  }

  // keep the projection in sync with the canvas size
  useEffect(() => {
    updateOrtho(cams.ortho, size.width, size.height);
    cams.persp.aspect = size.width / size.height;
    cams.persp.updateProjectionMatrix();
  }, [cams, size.width, size.height]);

  // switching modes keeps the target and roughly the scale
  const prevMode = useRef<typeof mode | null>(null);
  useEffect(() => {
    const { persp, ortho } = cams;
    const t = target.current;
    const { width, height } = sizeRef.current;
    const switching = prevMode.current !== null && prevMode.current !== mode;
    const fromWalk = prevMode.current === "walk";
    prevMode.current = mode;
    if (mode === "walk") {
      if (persp.position.distanceTo(t) < 1e-3) persp.position.add(DEFAULT_DIR);
      setWalk(walkStart(t, persp));
      persp.aspect = width / height;
      persp.updateProjectionMatrix();
      set({ camera: persp });
      controls.current = null;
      return;
    }
    setWalk(null);
    if (fromWalk) {
      // orbit around a point in front of where the walk ended
      const dir = persp.getWorldDirection(new Vector3());
      t.copy(persp.position).addScaledVector(dir.setY(Math.min(dir.y, -0.35)).normalize(), 12);
      persp.position.addScaledVector(dir, -6).setY(persp.position.y + 4);
    }
    if (mode === "plan") {
      if (switching) {
        const visible = 2 * persp.position.distanceTo(t) * Math.tan((FOV * Math.PI) / 360);
        ortho.zoom = height / Math.max(visible, 1);
      }
      ortho.position.copy(t).add(planOffset(planUp));
      ortho.lookAt(t);
      updateOrtho(ortho, width, height);
      set({ camera: ortho });
    } else {
      if (switching) {
        const visible = height / Math.max(ortho.zoom, 1e-6);
        const dist = visible / (2 * Math.tan((FOV * Math.PI) / 360));
        const dir = persp.position.clone().sub(t);
        if (dir.lengthSq() < 1e-6) dir.copy(DEFAULT_DIR);
        persp.position.copy(t).add(dir.normalize().multiplyScalar(dist));
      }
      persp.aspect = width / height;
      persp.updateProjectionMatrix();
      set({ camera: persp });
    }

    const c = new OrbitControls(mode === "plan" ? ortho : persp, dom);
    c.target.copy(t);
    c.enableDamping = true;
    c.dampingFactor = 0.12;
    c.zoomToCursor = true;
    if (mode === "plan") {
      c.enableRotate = false;
      c.screenSpacePanning = true;
      c.mouseButtons = { LEFT: MOUSE.PAN, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN };
      c.minZoom = 0.05;
      c.maxZoom = 400;
    } else {
      c.screenSpacePanning = false;
      c.maxPolarAngle = (86 * Math.PI) / 180;
      c.minDistance = 3;
      c.maxDistance = 8000;
    }
    const onEnd = () => {
      const cam = mode === "plan" ? ortho : persp;
      rememberPose({
        position: cam.position.toArray() as Vec3,
        target: c.target.toArray() as Vec3,
        zoom: ortho.zoom,
      });
    };
    c.addEventListener("end", onEnd);
    c.update();
    controls.current = c;
    return () => {
      target.current.copy(c.target);
      c.removeEventListener("end", onEnd);
      c.dispose();
      controls.current = null;
    };
  }, [mode, cams, dom, set, planUp]);

  // framing requests: fly to the box, keeping the viewing direction. Each request once: the
  // effect also re-runs on a mode change, which must not fly back to an old box.
  const doneFocus = useRef(0);
  useEffect(() => {
    const c = controls.current;
    if (!focus || !c || focus.seq === doneFocus.current) return;
    doneFocus.current = focus.seq;
    const cam = mode === "plan" ? cams.ortho : cams.persp;
    const dir = cam.position.clone().sub(c.target).normalize();
    const { pos, tgt } = frameBox(focus.min, focus.max, mode === "plan" ? new Vector3(0, 1, 1e-6) : dir);
    if (mode === "plan") pos.copy(tgt).add(planOffset(planUp));
    flight.current = {
      t0: performance.now(),
      fromPos: cam.position.clone(),
      fromTarget: c.target.clone(),
      toPos: pos,
      toTarget: tgt,
      fromZoom: cams.ortho.zoom,
      toZoom: mode === "plan" ? planZoom(focus.min, focus.max, sizeRef.current.width, sizeRef.current.height) : cams.ortho.zoom,
    };
  }, [focus, mode, cams, planUp]);

  // compass click: turn to north-up, keeping distance and tilt (each click once)
  const doneNorth = useRef(0);
  useEffect(() => {
    const c = controls.current;
    if (northRequest === doneNorth.current) return;
    doneNorth.current = northRequest;
    if (!c || mode === "plan") return;
    const cam = cams.persp;
    const offset = cam.position.clone().sub(c.target);
    const horizontal = Math.hypot(offset.x, offset.z);
    flight.current = {
      t0: performance.now(),
      fromPos: cam.position.clone(),
      fromTarget: c.target.clone(),
      toPos: c.target.clone().add(new Vector3(0, offset.y, horizontal)),
      toTarget: c.target.clone(),
      fromZoom: cams.ortho.zoom,
      toZoom: cams.ortho.zoom,
    };
  }, [northRequest, mode, cams]);

  useFrame(() => {
    const c = controls.current;
    if (!c) return;
    const cam = mode === "plan" ? cams.ortho : cams.persp;
    const f = flight.current;
    if (f) {
      const k = REDUCED ? 1 : ease(Math.min(1, (performance.now() - f.t0) / ANIM_MS));
      cam.position.lerpVectors(f.fromPos, f.toPos, k);
      c.target.lerpVectors(f.fromTarget, f.toTarget, k);
      if (mode === "plan") {
        cams.ortho.zoom = f.fromZoom + (f.toZoom - f.fromZoom) * k;
        cams.ortho.updateProjectionMatrix();
      }
      if (k >= 1) {
        flight.current = null;
        c.dispatchEvent({ type: "end" });
      }
    }
    c.update();
    target.current.copy(c.target);
    report(cam, c);
  });

  function report(cam: PerspectiveCamera | OrthographicCamera, c: OrbitControls) {
    const now = performance.now();
    if (now - lastReport.current.time < 100) return;
    const azimuth = mode === "plan" ? -Math.atan2(planUp.x, -planUp.z) : c.getAzimuthalAngle();
    const mpp =
      mode === "plan"
        ? 1 / cams.ortho.zoom
        : (2 * cam.position.distanceTo(c.target) * Math.tan((FOV * Math.PI) / 360)) / size.height;
    const last = lastReport.current;
    if (Math.abs(azimuth - last.azimuth) < 1e-3 && Math.abs(mpp / last.mpp - 1) < 0.01) return;
    lastReport.current = { azimuth, mpp, time: now };
    const heading = ((((-azimuth * 180) / Math.PI) % 360) + 360) % 360;
    app.set({ azimuthDeg: heading, metresPerPixel: mpp });
  }

  const exitWalk = useCallback(() => app.set({ camera: "orbit" }), []);
  return mode === "walk" && walk ? <WalkRig camera={cams.persp} start={walk} onExit={exitWalk} /> : null;
}

function updateOrtho(cam: OrthographicCamera, w: number, h: number) {
  cam.left = -w / 2;
  cam.right = w / 2;
  cam.top = h / 2;
  cam.bottom = -h / 2;
  cam.updateProjectionMatrix();
}

function frameBox(min: Vec3, max: Vec3, dir: Vector3, margin = 1.5) {
  const tgt = new Vector3((min[0] + max[0]) / 2, min[1], (min[2] + max[2]) / 2);
  const radius = Math.max(15, 0.5 * Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]));
  const dist = (radius / Math.sin((FOV * Math.PI) / 360)) * margin;
  return { pos: tgt.clone().add(dir.clone().normalize().multiplyScalar(dist)), tgt };
}

function planZoom(min: Vec3, max: Vec3, w: number, h: number) {
  const sx = Math.max(30, max[0] - min[0]) * 1.25;
  const sz = Math.max(30, max[2] - min[2]) * 1.25;
  return Math.min(w / sx, h / sz);
}

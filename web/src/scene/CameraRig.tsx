// Cameras sharing one target: an orbit (perspective) camera, a top-down plan
// (orthographic) camera with north up (or, for an opened building, its +x axis to the
// right, so walls look axis-aligned), and the first-person walk camera (WalkRig).
// Handles framing requests and reports the view (heading, scale) to the store for the
// compass and the scale bar.

import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type Intersection, type Mesh, MOUSE, type Object3D, OrthographicCamera, PerspectiveCamera, Raycaster, Vector3 } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { ModelControls } from "./ModelControls";
import type { Vec3 } from "../lib/frames";
import { app, type FocusRequest, openedBuilding, setPlayback, splitActive, useApp } from "../state/app";
import { rememberPose } from "../state/url";
import { registry } from "./registry";
import { type WalkStart, WalkRig } from "./WalkRig";

const FOV = 40;
const ANIM_MS = 450;
// with "reduce motion" set in the OS, the camera jumps instead of flying
const REDUCED = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const PLAN_HEIGHT = 3000;
const DEFAULT_DIR = new Vector3(0.25, 0.75, 0.62).normalize(); // from south-south-east, 50 deg up
// the orbit camera may go under the ground (the metro is 15 m down), short of straight up
const MAX_POLAR = (172 * Math.PI) / 180;
const CLICK_PX = 4; // a press that moved further is a drag, not a click on a label

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

/** A click near a student (of a simulation) picks them for the Student tab; true if it did.
 *  Checked here, on the canvas wrapper, so it works wherever the student stands (off the
 *  ground plate too, where no mesh is hit). */
function pickStudent(e: MouseEvent): boolean {
  const s = app.get();
  if (e.button !== 0 || s.tool !== "select" || s.camera === "walk" || s.playback.pov || e.altKey || !registry.studentAt) return false;
  const id = registry.studentAt(e.clientX, e.clientY);
  if (id === null) return false;
  setPlayback({ student: id });
  app.set({ rightTab: "student", rightOpen: true, tabsOpen: true });
  return true;
}

/** What the rig uses of either controls: OrbitControls (plan) or ModelControls (orbit). */
interface Controls {
  target: Vector3;
  update(): void;
  dispose(): void;
  getAzimuthalAngle(): number;
  addEventListener(type: "end", listener: () => void): void;
  removeEventListener(type: "end", listener: () => void): void;
  dispatchEvent(event: { type: "end" }): void;
}

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
  const canvasEl = useThree((s) => s.gl.domElement);
  // the controls listen on the canvas' wrapper: the HTML labels (Css2d) sit in it above the
  // canvas, so a right-drag that starts on a label pans instead of opening the browser menu
  const dom = canvasEl.parentElement ?? canvasEl;
  useEffect(() => {
    let down: [number, number] | null = null;
    const onDown = (e: PointerEvent) => {
      down = [e.clientX, e.clientY];
    };
    const onClick = (e: MouseEvent) => {
      // a drag that ended on a label must not select it
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > CLICK_PX) e.stopPropagation();
      // a click near a student picks them, before anything under them gets selected
      else if (pickStudent(e)) e.stopPropagation();
    };
    const noMenu = (e: MouseEvent) => e.preventDefault();
    // a drag whose pointerup got lost (context menu, cancelled capture) would stick until the
    // next click: a move with no button held ends it (OrbitControls listens on the document)
    let dragging = -1;
    const onPress = (e: PointerEvent) => {
      dragging = e.pointerId;
    };
    const onRelease = () => {
      dragging = -1;
    };
    const onMove = (e: PointerEvent) => {
      if (dragging < 0 || e.buttons !== 0 || e.pointerType !== "mouse") return;
      const id = dragging;
      dragging = -1;
      dom.ownerDocument.dispatchEvent(new PointerEvent("pointerup", { pointerId: id, pointerType: "mouse", clientX: e.clientX, clientY: e.clientY }));
    };
    dom.addEventListener("pointerdown", onPress);
    dom.ownerDocument.addEventListener("pointerup", onRelease, true);
    dom.ownerDocument.addEventListener("pointermove", onMove, true);
    dom.addEventListener("pointerdown", onDown, true);
    dom.addEventListener("click", onClick, true);
    dom.addEventListener("contextmenu", noMenu);
    return () => {
      dom.removeEventListener("pointerdown", onDown, true);
      dom.removeEventListener("pointerdown", onPress);
      dom.ownerDocument.removeEventListener("pointerup", onRelease, true);
      dom.ownerDocument.removeEventListener("pointermove", onMove, true);
      dom.removeEventListener("click", onClick, true);
      dom.removeEventListener("contextmenu", noMenu);
    };
  }, [dom]);

  const cams = useMemo(() => {
    const persp = new PerspectiveCamera(FOV, 1, 1, 20000);
    const ortho = new OrthographicCamera(-1, 1, 1, -1, 1, 20000);
    return { persp, ortho };
  }, []);
  const controls = useRef<Controls | null>(null);
  const scene = useThree((s) => s.scene);
  // the point under the pointer for the orbit controls: buildings, context, ground (the
  // meshes with a BVH), visible ones only
  const pick = useMemo(() => {
    const ray = new Raycaster();
    ray.firstHitOnly = true;
    const visible = (h: Intersection) => {
      for (let o: Object3D | null = h.object; o; o = o.parent) if (!o.visible) return false;
      return !!(h.object as Mesh).geometry?.boundsTree;
    };
    return (ndc: { x: number; y: number }, cam: PerspectiveCamera) => {
      ray.setFromCamera(ndc as never, cam);
      return ray.intersectObject(scene, true).find(visible)?.point.clone() ?? null;
    };
  }, [scene]);
  const target = useRef(new Vector3());
  const flight = useRef<Flight | null>(null);
  const lastReport = useRef({ azimuth: NaN, mpp: NaN, time: 0 });
  const sizeRef = useRef(size);
  sizeRef.current = size;

  // the student's eyes (playback.pov): the camera at their eye height, looking where they go;
  // a drag turns the head (yaw, pitch), the orbit controls rest meanwhile
  const pov = useApp((s) => s.playback.pov && s.camera === "orbit");
  const eyes = useRef({ heading: new Vector3(0, 0, -1), last: null as Vector3 | null, yaw: 0, pitch: -0.08 });
  useEffect(() => {
    const c = controls.current as unknown as { enabled?: boolean } | null;
    if (!pov) return;
    if (c) c.enabled = false;
    const cam = cams.persp;
    const near = cam.near;
    cam.near = 0.1; // tunnels and crowds are close
    cam.updateProjectionMatrix();
    eyes.current.last = null;
    eyes.current.yaw = 0;
    eyes.current.pitch = -0.08;
    let drag: [number, number] | null = null;
    const down = (e: PointerEvent) => {
      if (e.button === 0) drag = [e.clientX, e.clientY];
    };
    const move = (e: PointerEvent) => {
      if (!drag || e.buttons === 0) {
        drag = null;
        return;
      }
      eyes.current.yaw -= (e.clientX - drag[0]) * 0.004;
      eyes.current.pitch = Math.max(-1.3, Math.min(1.3, eyes.current.pitch - (e.clientY - drag[1]) * 0.004));
      drag = [e.clientX, e.clientY];
    };
    const up = () => {
      drag = null;
    };
    dom.addEventListener("pointerdown", down);
    dom.ownerDocument.addEventListener("pointermove", move);
    dom.ownerDocument.addEventListener("pointerup", up);
    return () => {
      dom.removeEventListener("pointerdown", down);
      dom.ownerDocument.removeEventListener("pointermove", move);
      dom.ownerDocument.removeEventListener("pointerup", up);
      cam.near = near;
      cam.updateProjectionMatrix();
      const ctl = controls.current;
      if (ctl) {
        (ctl as unknown as { enabled?: boolean }).enabled = true;
        // step back and up from the student, looking at them
        const back = eyes.current.heading.clone().multiplyScalar(-70);
        ctl.target.copy(cam.position).setY(cam.position.y - 1.6);
        cam.position.add(back).setY(cam.position.y + 55);
        ctl.update();
      }
    };
  }, [pov, cams, dom]);

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
      if (app.get().cameraBelow) app.set({ cameraBelow: false });
      // the walk starts where the view looks: the scene point in the middle of the screen
      const hit = pick({ x: 0, y: 0 }, persp);
      if (hit) t.copy(hit);
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

    let c: Controls;
    if (mode === "plan") {
      const o = new OrbitControls(ortho, dom);
      o.enableDamping = true;
      o.dampingFactor = 0.12;
      o.zoomToCursor = true;
      o.zoomSpeed = 1.6;
      o.enableRotate = false;
      o.screenSpacePanning = true;
      o.mouseButtons = { LEFT: MOUSE.PAN, MIDDLE: MOUSE.PAN, RIGHT: MOUSE.PAN };
      o.minZoom = 0.05;
      o.maxZoom = 400;
      c = o as unknown as Controls;
    } else {
      const m = new ModelControls(persp, dom);
      m.maxPolarAngle = MAX_POLAR;
      m.pick = (ndc) => pick(ndc, persp);
      c = m as unknown as Controls;
    }
    c.target.copy(t);
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
  }, [mode, cams, dom, set, planUp, pick]);

  // framing requests: fly to the box, keeping the viewing direction. Each request once: the
  // effect also re-runs on a mode change, which must not fly back to an old box.
  const doneFocus = useRef(0);
  useEffect(() => {
    const c = controls.current;
    if (!focus || !c || focus.seq === doneFocus.current) return;
    doneFocus.current = focus.seq;
    const cam = mode === "plan" ? cams.ortho : cams.persp;
    const dir = focus.reset ? DEFAULT_DIR.clone() : cam.position.clone().sub(c.target).normalize();
    const { pos, tgt } = frameBox(focus.min, focus.max, mode === "plan" ? new Vector3(0, 1, 1e-6) : dir, focus.reset ? 0.8 : 1.5);
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
    if (pov) {
      const p = registry.follow;
      const e = eyes.current;
      if (p) {
        if (e.last) {
          const d = p.clone().sub(e.last).setY(0);
          if (d.length() > 0.02) e.heading.lerp(d.normalize(), 0.12).normalize();
        }
        e.last = p.clone();
        const dir = e.heading.clone().applyAxisAngle(new Vector3(0, 1, 0), e.yaw);
        dir.multiplyScalar(Math.cos(e.pitch)).setY(Math.sin(e.pitch));
        cam.position.set(p.x, p.y + 1.6, p.z);
        c.target.copy(cam.position).addScaledVector(dir, 5);
        c.update();
        report(cam, c);
      }
      return;
    }
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
    // follow the student looked at: move camera and target with them (eased)
    if (!f && registry.follow && app.get().playback.follow) {
      const d = registry.follow.clone().sub(c.target);
      if (mode === "plan") d.y = 0;
      if (d.lengthSq() > 1e-4) {
        d.multiplyScalar(Math.min(1, 0.15));
        cam.position.add(d);
        c.target.add(d);
      }
    }
    c.update();
    target.current.copy(c.target);
    report(cam, c);
    const below = mode !== "plan" && cam.position.y < 0;
    if (below !== app.get().cameraBelow) app.set({ cameraBelow: below });
  });

  function report(cam: PerspectiveCamera | OrthographicCamera, c: Controls) {
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

// First-person camera: eyes 1.7 m above the feet, WASD to move, Shift to run (3x), the wheel
// sets the speed (1 to 40 m/s, kept for the next walk), mouse to look. Space flies up and
// Ctrl (or C) down, through the ground too (the metro is 15 m below); G walks again (falls
// to the floor below).
// (PointerLockControls from three/addons). Walls stop you and floors, slabs and stair
// steps carry you: a ray down from knee height finds the floor (steps up to 0.55 m are
// climbed), two rays forward (knee and chest) find walls, and the move slides along them.
// Raycasts use the BVHs of the building, context and ground meshes. Esc returns to orbit.

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { type Intersection, type Mesh, type Object3D, type PerspectiveCamera, Raycaster, Vector3 } from "three";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";
import { app, toast } from "../state/app";

const EYE = 1.7;
const STEP_UP = 0.55;
const RADIUS = 0.3;
const RUN = 3; // Shift: this many times faster
const SPEED_MIN = 1;
const SPEED_MAX = 40;
let speedSetting = 4; // m/s, the wheel changes it; module level, so the next walk keeps it
const GRAVITY = 9.81;
const RAY_HEIGHTS = [0.5, 1.5];

export interface WalkStart {
  feet: Vector3;
  look: Vector3; // horizontal direction
}

function hitVisible(h: Intersection): boolean {
  for (let o: Object3D | null = h.object; o; o = o.parent) if (!o.visible) return false;
  return !!(h.object as Mesh).geometry?.boundsTree; // buildings, context, ground; not markers
}

export function WalkRig({ camera, start, onExit }: { camera: PerspectiveCamera; start: WalkStart; onExit: () => void }) {
  const dom = useThree((s) => s.gl.domElement);
  const scene = useThree((s) => s.scene);
  const keys = useRef(new Set<string>());
  const feet = useRef(start.feet.clone());
  const vy = useRef(0);
  const flying = useRef(false);
  const ray = useMemo(() => {
    const r = new Raycaster();
    r.firstHitOnly = true;
    return r;
  }, []);

  const controls = useMemo(() => new PointerLockControls(camera, dom), [camera, dom]);

  // walls get close: a 1 m near plane (orbit) would cut into them
  useEffect(() => {
    const near = camera.near;
    camera.near = 0.05;
    camera.updateProjectionMatrix();
    return () => {
      camera.near = near;
      camera.updateProjectionMatrix();
    };
  }, [camera]);

  useEffect(() => {
    feet.current.copy(start.feet);
    // stand on the ground under the start: the lowest surface straight down from high up
    // (the terrain is not at y = 0 everywhere; a roof above it is not where to start)
    const down = new Raycaster(new Vector3(start.feet.x, start.feet.y + 300, start.feet.z), new Vector3(0, -1, 0), 0, 700);
    const hits = down.intersectObject(scene, true).filter(hitVisible);
    const ground = hits.find((h) => h.object.userData.layer === "ground") ?? hits[hits.length - 1];
    if (ground) feet.current.y = ground.point.y;
    camera.position.copy(feet.current).add(new Vector3(0, EYE, 0));
    camera.lookAt(camera.position.clone().add(start.look));
  }, [camera, start, scene]);

  useEffect(() => {
    // dispose() in the cleanup disconnects the controls; StrictMode remounts with the same
    // (memoised) ones, so connect them on every mount (connect() is idempotent)
    controls.connect(dom);
    const lock = () => controls.lock();
    const onUnlock = () => onExit();
    const down = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, select, textarea")) return;
      keys.current.add(e.code);
      const vertical = e.code === "Space" || e.code === "ControlLeft" || e.code === "ControlRight" || e.code === "KeyC";
      if (vertical) {
        e.preventDefault(); // no page scroll, no button press
        if (!flying.current) toast("Flying: Space up, Ctrl / C down (into the metro too), G to walk again", "info", 2500);
        flying.current = true;
      }
      if (e.code === "KeyG" && flying.current) {
        flying.current = false;
        vy.current = 0;
        toast("Walking", "info", 1000);
      }
      if (e.code === "Escape" && !controls.isLocked) onExit();
    };
    const up = (e: KeyboardEvent) => keys.current.delete(e.code);
    const blur = () => keys.current.clear();
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const f = Math.exp(-Math.sign(e.deltaY) * 0.2);
      speedSetting = Math.min(SPEED_MAX, Math.max(SPEED_MIN, speedSetting * f));
      toast(`Walking speed ${speedSetting.toFixed(1)} m/s (${(speedSetting * 3.6).toFixed(0)} km/h), Shift ×${RUN}`, "info", 1200);
    };
    dom.addEventListener("click", lock);
    dom.addEventListener("wheel", wheel, { passive: false });
    controls.addEventListener("unlock", onUnlock);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    app.set({ hover: null, cursor: null, cursorBuilding: null });
    return () => {
      dom.removeEventListener("click", lock);
      dom.removeEventListener("wheel", wheel);
      controls.removeEventListener("unlock", onUnlock);
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      controls.unlock();
      controls.dispose();
    };
  }, [controls, dom, onExit]);

  const tmp = useMemo(
    () => ({ fwd: new Vector3(), right: new Vector3(), move: new Vector3(), origin: new Vector3(), n: new Vector3() }),
    [],
  );

  function cast(origin: Vector3, dir: Vector3, far: number): Intersection | null {
    ray.set(origin, dir);
    ray.far = far;
    const hits = ray.intersectObject(scene, true);
    return hits.find(hitVisible) ?? null;
  }

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05);
    const k = keys.current;
    const { fwd, right, move, origin, n } = tmp;
    camera.getWorldDirection(fwd);
    fwd.y = 0;
    fwd.normalize();
    right.set(-fwd.z, 0, fwd.x);
    move.set(0, 0, 0);
    if (k.has("KeyW") || k.has("ArrowUp")) move.add(fwd);
    if (k.has("KeyS") || k.has("ArrowDown")) move.sub(fwd);
    if (k.has("KeyD") || k.has("ArrowRight")) move.add(right);
    if (k.has("KeyA") || k.has("ArrowLeft")) move.sub(right);
    const speed = speedSetting * (k.has("ShiftLeft") || k.has("ShiftRight") ? RUN : 1);
    if (move.lengthSq() > 0) move.normalize().multiplyScalar(speed * dt);

    // walls: slide along whatever the knee or chest ray hits
    for (let pass = 0; pass < 2 && move.lengthSq() > 1e-10; pass++) {
      const len = move.length();
      const dir = move.clone().divideScalar(len);
      for (const h of RAY_HEIGHTS) {
        origin.copy(feet.current).setY(feet.current.y + h);
        const hit = cast(origin, dir, len + RADIUS);
        if (!hit?.face) continue;
        n.copy(hit.face.normal).setY(0);
        if (n.lengthSq() < 1e-6) continue;
        n.normalize();
        if (n.dot(dir) > 0) n.negate();
        const into = move.dot(n);
        if (into < 0) move.addScaledVector(n, -into);
        // keep the radius from the wall
        const gap = hit.distance - RADIUS;
        if (gap < 0) move.addScaledVector(n, -gap);
      }
    }
    feet.current.add(move);

    if (flying.current) {
      // no gravity, no floors: Space up, Ctrl / C down, at the walking speed
      const up = k.has("Space") ? 1 : 0;
      const dn = k.has("ControlLeft") || k.has("ControlRight") || k.has("KeyC") ? 1 : 0;
      feet.current.y += (up - dn) * speed * dt;
    } else {
      // floors: highest surface below the knees
      origin.copy(feet.current).setY(feet.current.y + STEP_UP);
      const floor = cast(origin, new Vector3(0, -1, 0), 400);
      if (floor) {
        const y = floor.point.y;
        if (y >= feet.current.y - 0.02) {
          feet.current.y += (y - feet.current.y) * Math.min(1, dt * 18); // climb a step smoothly
          vy.current = 0;
        } else {
          vy.current -= GRAVITY * dt;
          feet.current.y = Math.max(y, feet.current.y + vy.current * dt);
          if (feet.current.y === y) vy.current = 0;
        }
      }
    }
    camera.position.copy(feet.current).add(new Vector3(0, EYE, 0));

    const heading = ((Math.atan2(fwd.x, -fwd.z) * 180) / Math.PI + 360) % 360;
    if (Math.abs(heading - app.get().azimuthDeg) > 0.5) app.set({ azimuthDeg: heading, metresPerPixel: 0.01 });
  });

  return null;
}

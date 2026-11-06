// Orbit-camera controls in the manner of 3D modelling tools, with y always up:
// - left drag: turn round the point under the cursor (turntable: yaw about the vertical,
//   pitch about the screen's horizontal axis), from above or from under the ground;
// - right or middle drag (or Shift + left): move, holding the grabbed point under the cursor;
// - wheel: zoom towards the point under the cursor.
// `pick` finds the point under the cursor (the rig raycasts the scene); without a hit, the
// ground plane or a point at the target's distance stands in.
//
// Same surface as three's OrbitControls where CameraRig needs it: `target`, `update()`,
// `getAzimuthalAngle()`, the "end" event (a pose to remember), `dispose()`.

import { EventDispatcher, Plane, type PerspectiveCamera, Quaternion, Ray, Vector2, Vector3 } from "three";

const UP = new Vector3(0, 1, 0);

type Events = { end: object; change: object };

export class ModelControls extends EventDispatcher<Events> {
  readonly target = new Vector3();
  enabled = true;
  rotateSpeed = (2 * Math.PI) / 1400; // radians per pixel: a full turn in 1400 px
  zoomSpeed = 0.0011; // per wheel delta unit: one notch (100) zooms by ~10 %
  minDistance = 3;
  maxDistance = 8000;
  minPolarAngle = 0.02;
  maxPolarAngle = Math.PI - 0.15;
  /** World point under the pointer (client coordinates), or null. */
  pick: (ndc: Vector2) => Vector3 | null = () => null;
  /** Ray through the pointer, from the camera. */
  ray: (ndc: Vector2, out: Ray) => void;

  private mode: "rotate" | "pan" | null = null;
  private last = new Vector2();
  private pivot = new Vector3();
  private grab = new Vector3();
  private grabPlane = new Plane();
  private endTimer = 0;
  private readonly onDown = (e: PointerEvent) => this.down(e);
  private readonly onMove = (e: PointerEvent) => this.move(e);
  private readonly onUp = (e: PointerEvent) => this.up(e);
  private pointerId = -1;
  private readonly onWheel = (e: WheelEvent) => this.wheel(e);

  constructor(
    readonly camera: PerspectiveCamera,
    readonly dom: HTMLElement,
  ) {
    super();
    this.ray = (ndc, out) => {
      out.origin.copy(camera.position);
      out.direction.set(ndc.x, ndc.y, 0.5).unproject(camera).sub(camera.position).normalize();
    };
    dom.addEventListener("pointerdown", this.onDown);
    dom.addEventListener("wheel", this.onWheel, { passive: false });
    dom.style.touchAction = "none";
  }

  dispose(): void {
    this.dom.removeEventListener("pointerdown", this.onDown);
    this.dom.removeEventListener("wheel", this.onWheel);
    this.dom.ownerDocument.removeEventListener("pointermove", this.onMove);
    this.dom.ownerDocument.removeEventListener("pointerup", this.onUp);
    clearTimeout(this.endTimer);
  }

  /** Looks at the target, y up (after the rig moved the camera or the target). */
  update(): void {
    this.camera.up.copy(UP);
    this.camera.lookAt(this.target);
  }

  /** Moves the target onto the scene point in the middle of the view (the camera stays):
   *  the scale bar, the markers' size and the walk start are measured there. */
  recentre(): void {
    const hit = this.pick(new Vector2(0, 0));
    if (hit && hit.distanceTo(this.camera.position) > this.minDistance) this.target.copy(hit);
  }

  /** Heading of the camera round the target, as OrbitControls reports it. */
  getAzimuthalAngle(): number {
    const o = this.camera.position.clone().sub(this.target);
    return Math.atan2(o.x, o.z);
  }

  private ndc(e: { clientX: number; clientY: number }): Vector2 {
    const r = this.dom.getBoundingClientRect();
    return new Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  }

  /** The point under the pointer, else on the ground, else at the target's distance. */
  private pointAt(ndc: Vector2): Vector3 {
    const hit = this.pick(ndc);
    if (hit) return hit;
    const ray = new Ray();
    this.ray(ndc, ray);
    const ground = ray.intersectPlane(new Plane(UP, 0), new Vector3());
    if (ground && ground.distanceTo(this.camera.position) < this.maxDistance) return ground;
    return ray.at(this.camera.position.distanceTo(this.target), new Vector3());
  }

  private down(e: PointerEvent): void {
    if (!this.enabled || this.mode) return;
    const pan = e.button === 1 || e.button === 2 || (e.button === 0 && e.shiftKey);
    if (e.button !== 0 && !pan) return;
    this.mode = pan ? "pan" : "rotate";
    this.last.set(e.clientX, e.clientY);
    const ndc = this.ndc(e);
    if (pan) {
      this.grab.copy(this.pointAt(ndc));
      const fwd = this.camera.getWorldDirection(new Vector3());
      this.grabPlane.setFromNormalAndCoplanarPoint(fwd, this.grab);
    } else {
      this.pivot.copy(this.pick(ndc) ?? this.target);
    }
    this.pointerId = e.pointerId;
    this.dom.setPointerCapture(e.pointerId);
    this.dom.ownerDocument.addEventListener("pointermove", this.onMove);
    this.dom.ownerDocument.addEventListener("pointerup", this.onUp);
    // a lost pointerup (the browser's context menu, a cancelled capture) must not leave the
    // drag running until the next click: these end it too
    this.dom.ownerDocument.addEventListener("pointercancel", this.onUp);
    this.dom.addEventListener("lostpointercapture", this.onUp);
    this.dom.style.cursor = pan ? "grabbing" : "";
    if (e.button === 1) e.preventDefault(); // no autoscroll
  }

  private move(e: PointerEvent): void {
    if (!this.mode) return;
    if (e.buttons === 0) return this.up(e); // released where we did not hear it
    const dx = e.clientX - this.last.x;
    const dy = e.clientY - this.last.y;
    this.last.set(e.clientX, e.clientY);
    if (this.mode === "rotate") this.rotate(dx, dy);
    else this.pan(this.ndc(e));
    this.dispatchEvent({ type: "change" });
  }

  private up(e: PointerEvent): void {
    if (!this.mode) return;
    this.mode = null;
    const id = this.pointerId >= 0 ? this.pointerId : e.pointerId;
    this.pointerId = -1;
    this.dom.ownerDocument.removeEventListener("pointermove", this.onMove);
    this.dom.ownerDocument.removeEventListener("pointerup", this.onUp);
    this.dom.ownerDocument.removeEventListener("pointercancel", this.onUp);
    this.dom.removeEventListener("lostpointercapture", this.onUp);
    if (this.dom.hasPointerCapture(id)) this.dom.releasePointerCapture(id);
    this.recentre();
    this.dom.style.cursor = "";
    this.dispatchEvent({ type: "end" });
  }

  /** Turntable round the pivot: yaw about the vertical, pitch about the screen's horizontal. */
  private rotate(dx: number, dy: number): void {
    const cam = this.camera.position;
    const offset = cam.clone().sub(this.target);
    const polar = Math.acos(Math.min(1, Math.max(-1, offset.y / offset.length())));
    const wanted = Math.min(this.maxPolarAngle, Math.max(this.minPolarAngle, polar - dy * this.rotateSpeed));
    const axis = new Vector3().crossVectors(UP, offset).normalize(); // +angle: polar grows
    const q = new Quaternion().setFromAxisAngle(UP, -dx * this.rotateSpeed);
    if (axis.lengthSq() > 0.5) q.multiply(new Quaternion().setFromAxisAngle(axis, wanted - polar));
    cam.sub(this.pivot).applyQuaternion(q).add(this.pivot);
    this.target.sub(this.pivot).applyQuaternion(q).add(this.pivot);
    this.update();
  }

  /** Moves camera and target so the grabbed point stays under the pointer. */
  private pan(ndc: Vector2): void {
    const ray = new Ray();
    this.ray(ndc, ray);
    const p = ray.intersectPlane(this.grabPlane, new Vector3());
    if (!p) return;
    const d = this.grab.clone().sub(p);
    if (d.length() > this.maxDistance) return;
    this.camera.position.add(d);
    this.target.add(d);
    this.update();
  }

  private wheel(e: WheelEvent): void {
    if (!this.enabled) return;
    e.preventDefault();
    const delta = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
    const z = this.pointAt(this.ndc(e));
    const cam = this.camera.position;
    const dist = cam.distanceTo(z);
    let f = Math.exp(delta * this.zoomSpeed);
    f = Math.min(this.maxDistance / Math.max(dist, 1e-3), Math.max(1 / Math.max(dist, 1e-3), f)); // stay 1 m off
    cam.sub(z).multiplyScalar(f).add(z);
    this.target.sub(z).multiplyScalar(f).add(z);
    // closer than minDistance to the target: push the target ahead, so zooming goes on
    const fwd = this.target.clone().sub(cam);
    if (fwd.length() < this.minDistance) this.target.copy(cam).addScaledVector(fwd.normalize(), this.minDistance);
    this.update();
    this.dispatchEvent({ type: "change" });
    clearTimeout(this.endTimer);
    this.endTimer = window.setTimeout(() => {
      this.recentre();
      this.dispatchEvent({ type: "end" });
    }, 200);
  }
}

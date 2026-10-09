// Picking: layers attach a resolver to their objects; the viewport walks up from the hit
// object to the nearest resolver. Objects that should never be hit opt out of raycasting.

import type { Intersection, Object3D } from "three";
import type { Pick } from "../state/app";

export type PickResolver = (hit: Intersection) => Pick | null;

const RESOLVER = "pickResolver";

export function setPickable(obj: Object3D, resolver: PickResolver): void {
  obj.userData[RESOLVER] = resolver;
}

export function resolvePick(hit: Intersection): Pick | null {
  let o: Object3D | null = hit.object;
  while (o) {
    const r = o.userData[RESOLVER] as PickResolver | undefined;
    if (r) return r(hit);
    o = o.parent;
  }
  return null;
}

/** Exclude an object (and its children) from raycasts: lines, ground, overlays. */
export function noRaycast(root: Object3D): void {
  root.traverse((o) => {
    o.raycast = () => {};
  });
}

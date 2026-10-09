// three-mesh-bvh: fast raycasting against building meshes (picking rooms, keeping the
// first-person camera out of walls). Import this module once, before any raycast.

import { BufferGeometry, Mesh, type Object3D } from "three";
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from "three-mesh-bvh";

BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;
Mesh.prototype.raycast = acceleratedRaycast;

/** Build a BVH for every mesh under `root` (call after loading a glb). */
export function buildBoundsTrees(root: Object3D): void {
  root.traverse((obj) => {
    if (obj instanceof Mesh && !obj.geometry.boundsTree) obj.geometry.computeBoundsTree();
  });
}

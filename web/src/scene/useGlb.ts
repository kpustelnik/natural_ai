// Load a glb and keep showing the previous one until the new version has arrived, so a
// live reload never blinks. Replaced and unmounted scenes are disposed (geometries and
// their BVHs), so reloading a building fifty times does not leak GPU memory.

import { useEffect, useRef, useState } from "react";
import { type Group, Mesh, type Object3D } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DATA_URL } from "../data/loader";
import { versioned } from "../data/live";

const loader = new GLTFLoader();

export function disposeTree(root: Object3D): void {
  root.traverse((o) => {
    if (o instanceof Mesh || "isLineSegments" in o) {
      const g = (o as Mesh).geometry;
      if (g.boundsTree) g.disposeBoundsTree();
      g.dispose();
    }
  });
}

export function useGlb(path: string | null, version: number): Group | null {
  const [scene, setScene] = useState<Group | null>(null);
  const current = useRef<Group | null>(null);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    loader.loadAsync(DATA_URL + versioned(path, version)).then(
      (gltf) => {
        if (!alive) {
          disposeTree(gltf.scene);
          return;
        }
        const old = current.current;
        current.current = gltf.scene;
        setScene(gltf.scene);
        // dispose after React has swapped the object in the scene graph
        if (old) requestAnimationFrame(() => disposeTree(old));
      },
      (err: unknown) => console.error(`${path}:`, err),
    );
    return () => {
      alive = false;
    };
  }, [path, version]);

  useEffect(
    () => () => {
      if (current.current) disposeTree(current.current);
      current.current = null;
    },
    [],
  );

  return scene;
}

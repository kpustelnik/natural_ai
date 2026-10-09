import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/** Orbit camera for the campus overview. First-person mode inside buildings comes later. */
export function Controls() {
  const camera = useThree((s) => s.camera);
  const dom = useThree((s) => s.gl.domElement);
  const controls = useRef<OrbitControls | null>(null);

  useEffect(() => {
    const c = new OrbitControls(camera, dom);
    c.enableDamping = true;
    c.maxPolarAngle = Math.PI / 2 - 0.05; // stay above the ground
    controls.current = c;
    return () => c.dispose();
  }, [camera, dom]);

  useFrame(() => controls.current?.update());
  return null;
}

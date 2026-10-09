import { useLoader } from "@react-three/fiber";
import { Suspense, useEffect } from "react";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DATA_URL } from "../data/loader";
import type { Scene, SceneBuilding } from "../generated/schemas";
import { buildBoundsTrees } from "./bvh";

function Building({ building }: { building: SceneBuilding }) {
  const gltf = useLoader(GLTFLoader, DATA_URL + building.glb);
  useEffect(() => buildBoundsTrees(gltf.scene), [gltf]);
  // glb positions are already in the web frame: no transform
  return <primitive object={gltf.scene} />;
}

function Ground() {
  return (
    <>
      <mesh rotation-x={-Math.PI / 2} receiveShadow>
        <planeGeometry args={[4000, 4000]} />
        <meshStandardMaterial color="#d9d6cf" />
      </mesh>
      <gridHelper args={[4000, 80, "#b5b1a8", "#c9c5bc"]} position-y={0.01} />
    </>
  );
}

export function Campus({ scene }: { scene: Scene | null }) {
  return (
    <>
      <Ground />
      {scene?.buildings.map((b) => (
        <Suspense key={b.id} fallback={null}>
          <Building building={b} />
        </Suspense>
      ))}
    </>
  );
}

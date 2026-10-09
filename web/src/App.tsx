import { Canvas } from "@react-three/fiber";
import { useEffect, useState } from "react";
import { fetchJson, MissingDataError } from "./data/loader";
import type { Scene } from "./generated/schemas";
import { Campus } from "./scene/Campus";
import { Controls } from "./scene/Controls";
import { Panel, type Playback } from "./ui/Panel";

export function App() {
  const [scene, setScene] = useState<Scene | null>(null);
  const [status, setStatus] = useState<string | null>("Wczytywanie…");
  const [playback, setPlayback] = useState<Playback>({
    scenario: "metro",
    weekday: 1,
    t: 8 * 3600,
  });

  useEffect(() => {
    fetchJson<Scene>("scene.json")
      .then((s) => {
        setScene(s);
        setStatus(null);
      })
      .catch((err: unknown) =>
        setStatus(
          err instanceof MissingDataError
            ? "Brak danych: uruchom scripts/06_export_web.py"
            : `Błąd: ${String(err)}`,
        ),
      );
  }, []);

  return (
    <>
      <Canvas shadows camera={{ position: [300, 250, 300], fov: 45, near: 0.1, far: 10000 }}>
        <color attach="background" args={["#eef0f2"]} />
        <hemisphereLight args={["#ffffff", "#b9b4aa", 1.2]} />
        <directionalLight position={[400, 600, 200]} intensity={1.5} castShadow />
        <Campus scene={scene} />
        <Controls />
      </Canvas>
      <Panel playback={playback} onChange={setPlayback} status={status} />
    </>
  );
}

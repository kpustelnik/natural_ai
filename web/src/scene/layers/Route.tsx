// The route tool's result: the fastest path between its two ends as a thick accent line,
// drawn over everything (also through walls, so indoor parts stay visible), and the ends.

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { Mesh, MeshBasicMaterial, SphereGeometry } from "three";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { type Network, nodePosition, pathPolyline, resolveKey, useRoute } from "../../data/network";
import { app, useApp } from "../../state/app";
import { ACCENT, SCENE } from "../palette";

const LIFT = 0.7; // above the network lines

function EndMarker({ net, keyName, color }: { net: Network; keyName: string | null; color: string }) {
  const node = keyName ? resolveKey(net, keyName) : null;
  const mesh = useMemo(() => {
    const m = new Mesh(new SphereGeometry(1, 16, 12), new MeshBasicMaterial({ color, depthTest: false }));
    m.renderOrder = 21;
    m.raycast = () => {};
    return m;
  }, [color]);
  useEffect(
    () => () => {
      mesh.geometry.dispose();
      (mesh.material as MeshBasicMaterial).dispose();
    },
    [mesh],
  );
  useFrame(() => mesh.scale.setScalar(Math.max(1.2, 6 * app.get().metresPerPixel)));
  if (node === null) return null;
  const p = nodePosition(net, node);
  return <primitive object={mesh} position={[p[0], p[1] + LIFT, p[2]]} />;
}

export function RouteLayer({ net }: { net: Network }) {
  const route = useApp((s) => s.route);
  const result = useRoute(net, route);
  const size = useThree((s) => s.size);

  const line = useMemo(() => {
    if (!result?.ok) return null;
    const pts = pathPolyline(net, result.path);
    if (pts.length < 2) return null;
    const g = new LineGeometry();
    g.setPositions(pts.flatMap((p) => [p[0], p[1] + LIFT, p[2]]));
    const m = new LineMaterial({ color: ACCENT, linewidth: 5, depthTest: false, transparent: true, opacity: 0.9 });
    const l = new Line2(g, m);
    l.computeLineDistances();
    l.renderOrder = 20;
    l.raycast = () => {};
    return l;
  }, [net, result]);

  useEffect(() => {
    if (line) (line.material as LineMaterial).resolution.set(size.width, size.height);
  }, [line, size]);
  useEffect(
    () => () => {
      line?.geometry.dispose();
      (line?.material as LineMaterial | undefined)?.dispose();
    },
    [line],
  );

  return (
    <group>
      {line && <primitive object={line} />}
      <EndMarker net={net} keyName={route.from} color={SCENE.edge} />
      <EndMarker net={net} keyName={route.to} color={ACCENT} />
    </group>
  );
}

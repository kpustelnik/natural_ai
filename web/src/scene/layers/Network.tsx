// The walk graph (network.json + .bin): edge polylines coloured by kind (outdoor paths,
// corridors, doors, stairs, passages, shafts), or by weekly OD demand when colour mode is
// Demand. Edges are selectable; the picked edge is redrawn in the accent colour. With a
// building opened at a level, the graph is cut at the same section height as the building.

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { BufferAttribute, BufferGeometry, Color, LineBasicMaterial, LineSegments, Plane, Vector3 } from "three";
import type { BinaryFile } from "../../data/loader";
import { networkIndex } from "../../data/network";
import { useDemand } from "../../data/resource";
import type { NetworkHeader } from "../../generated/schemas";
import { app, useApp } from "../../state/app";
import { ACCENT, DEMAND_ZERO, demandColour, indexDemand, NETWORK } from "../palette";
import { setPickable } from "../picking";
import { registry } from "../registry";

const LIFT = 0.4;

function edgeGeometry(net: BinaryFile<NetworkHeader>, edge: number): BufferGeometry {
  const seg = net.arrays.segment_xyz as Float32Array;
  const { segStart } = networkIndex(net);
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(seg.slice(segStart[edge]! * 6, segStart[edge + 1]! * 6), 3));
  return g;
}

function paintEdges(
  net: BinaryFile<NetworkHeader>,
  mode: "kind" | "demand",
  loads: Map<number, number>,
  maxLegs: number,
): Float32Array {
  const ids = net.arrays.segment_edge as Uint32Array;
  const kinds = net.arrays.edge_kind as Uint8Array;
  const names = net.header.edge_kind_names;
  const palette = names.map((n) => new Color(NETWORK[n as keyof typeof NETWORK] ?? NETWORK.road));
  const zero = new Color(DEMAND_ZERO.color);
  const colors = new Float32Array(ids.length * 6);
  for (let s = 0; s < ids.length; s++) {
    const edge = ids[s]!;
    const c =
      mode === "demand"
        ? maxLegs > 0
          ? new Color(demandColour(loads.get(edge) ?? 0, maxLegs))
          : zero
        : palette[kinds[edge]!]!;
    for (const v of [0, 3]) {
      colors[s * 6 + v] = c.r;
      colors[s * 6 + v + 1] = c.g;
      colors[s * 6 + v + 2] = c.b;
    }
  }
  return colors;
}

export function Network({ net, clipY }: { net: BinaryFile<NetworkHeader>; clipY: number | null }) {
  const raycaster = useThree((s) => s.raycaster);
  const selected = useApp((s) => (s.selection?.kind === "edge" ? s.selection.index : null));
  const hovered = useApp((s) => (s.hover?.kind === "edge" ? s.hover.index : null));
  const demandMode = useApp((s) => s.colorMode === "demand");
  const demand = useDemand().data;
  const indexed = useMemo(() => indexDemand(demand), [demand]);

  const lines = useMemo(() => {
    const seg = net.arrays.segment_xyz as Float32Array;
    const ids = net.arrays.segment_edge as Uint32Array;
    const colors = paintEdges(net, "kind", indexed.edges, indexed.maxLegs);
    const g = new BufferGeometry();
    g.setAttribute("position", new BufferAttribute(seg, 3));
    g.setAttribute("color", new BufferAttribute(colors, 3));
    const obj = new LineSegments(g, new LineBasicMaterial({ vertexColors: true }));
    obj.position.y = LIFT;
    setPickable(obj, (hit) =>
      hit.index === undefined ? null : { kind: "edge", index: ids[Math.floor(hit.index / 2)]! },
    );
    return obj;
  }, [net]); // eslint-disable-line react-hooks/exhaustive-deps -- colours updated below

  // recolour when switching Demand ↔ kind (or when demand.json loads)
  useEffect(() => {
    const attr = lines.geometry.getAttribute("color") as BufferAttribute;
    const colors = paintEdges(net, demandMode ? "demand" : "kind", indexed.edges, indexed.maxLegs);
    (attr.array as Float32Array).set(colors);
    attr.needsUpdate = true;
  }, [lines, net, demandMode, indexed]);

  useEffect(() => {
    const m = lines.material as LineBasicMaterial;
    m.clippingPlanes = clipY === null ? [] : [new Plane(new Vector3(0, -1, 0), clipY + LIFT)];
    lines.userData.clipY = clipY === null ? undefined : clipY + LIFT;
    m.needsUpdate = true;
  }, [lines, clipY]);

  useEffect(() => {
    registry.network = net;
    return () => {
      lines.geometry.dispose();
      (lines.material as LineBasicMaterial).dispose();
    };
  }, [net, lines]);

  // pick tolerance of a few pixels at any zoom
  useFrame(() => {
    raycaster.params.Line = { threshold: Math.max(0.3, 4 * app.get().metresPerPixel) };
  });

  const highlight = useMemo(() => {
    const edge = selected ?? hovered;
    if (edge === null) return null;
    const obj = new LineSegments(
      edgeGeometry(net, edge),
      new LineBasicMaterial({ color: selected !== null ? ACCENT : "#111111", depthTest: false }),
    );
    obj.position.y = LIFT + 0.05;
    obj.renderOrder = 10;
    obj.raycast = () => {};
    return obj;
  }, [net, selected, hovered]);

  useEffect(
    () => () => {
      highlight?.geometry.dispose();
      (highlight?.material as LineBasicMaterial | undefined)?.dispose();
    },
    [highlight],
  );

  return (
    <group>
      <primitive object={lines} />
      {highlight && <primitive object={highlight} />}
    </group>
  );
}

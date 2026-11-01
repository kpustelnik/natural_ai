// Routing on the loaded walk graph: key lookup, the directed adjacency (built once per
// network file) and the route between two endpoints, shared by the route layer and panel.

import { useMemo } from "react";
import type { NetworkHeader } from "../generated/schemas";
import type { Vec3 } from "../lib/frames";
import { buildCsr, type Csr, type Path, type RouteSummary, shortestPath, summarise } from "../lib/graph";
import type { Route } from "../state/app";
import type { BinaryFile } from "./loader";

export type Network = BinaryFile<NetworkHeader>;

interface Index {
  csr: Csr;
  byKey: Map<string, number>; // node key -> node
  endpointOf: Map<number, string>; // node -> endpoint key
  segStart: Uint32Array; // edge e is drawn by segments segStart[e] .. segStart[e + 1] - 1
}

const indexes = new WeakMap<Network, Index>();

export function networkIndex(net: Network): Index {
  let ix = indexes.get(net);
  if (!ix) {
    const a = net.arrays;
    const segEdge = a.segment_edge as Uint32Array;
    const segStart = new Uint32Array(net.header.n_edges + 1);
    for (let s = 0; s < segEdge.length; s++) segStart[segEdge[s]! + 1]!++; // the export writes them in edge order
    for (let e = 0; e < net.header.n_edges; e++) segStart[e + 1]! += segStart[e]!;
    ix = {
      segStart,
      csr: buildCsr(
        net.header.n_nodes,
        a.edge_nodes as Uint32Array,
        a.time_uv_s as Float32Array,
        a.time_vu_s as Float32Array,
      ),
      byKey: new Map(net.header.node_keys.map((k, i) => [k, i])),
      endpointOf: new Map(Object.entries(net.header.endpoints).map(([k, i]) => [i, k])),
    };
    indexes.set(net, ix);
  }
  return ix;
}

/** Node of an endpoint key (D-17/1.38, D-17, stop:…) or of a node key (osm:123, D-17:c0@4.00). */
export function resolveKey(net: Network, key: string): number | null {
  return net.header.endpoints[key] ?? networkIndex(net).byKey.get(key) ?? null;
}

/** Readable name of a node: its endpoint key when it is one, else its node key. */
export function nodeName(net: Network, node: number): string {
  return networkIndex(net).endpointOf.get(node) ?? net.header.node_keys[node] ?? `#${node}`;
}

export function nodePosition(net: Network, node: number): Vec3 {
  const xyz = net.arrays.node_xyz as Float32Array;
  return [xyz[3 * node]!, xyz[3 * node + 1]!, xyz[3 * node + 2]!];
}

/** Nearest node to a point, within `maxDist` metres (3D distance with height counted twice,
 *  so the clicked floor wins). */
export function nearestNode(net: Network, p: Vec3, maxDist = 25): number | null {
  const xyz = net.arrays.node_xyz as Float32Array;
  let best = -1;
  let bestD = maxDist * maxDist;
  for (let i = 0; i < net.header.n_nodes; i++) {
    const dx = xyz[3 * i]! - p[0];
    const dy = (xyz[3 * i + 1]! - p[1]) * 2; // prefer the floor that was clicked
    const dz = xyz[3 * i + 2]! - p[2];
    const d = dx * dx + dy * dy + dz * dz;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best < 0 ? null : best;
}

export type RouteResult =
  | { ok: true; from: number; to: number; path: Path; summary: RouteSummary }
  | { ok: false; error: string };

export function computeRoute(net: Network, fromKey: string, toKey: string): RouteResult {
  const from = resolveKey(net, fromKey);
  const to = resolveKey(net, toKey);
  if (from === null) return { ok: false, error: `${fromKey} is not in the walk graph` };
  if (to === null) return { ok: false, error: `${toKey} is not in the walk graph` };
  const path = shortestPath(networkIndex(net).csr, from, to);
  if (!path) return { ok: false, error: `No path from ${fromKey} to ${toKey}` };
  const a = net.arrays;
  const xyz = a.node_xyz as Float32Array;
  const summary = summarise(path, {
    edgeNodes: a.edge_nodes as Uint32Array,
    edgeKind: a.edge_kind as Uint8Array,
    kindNames: net.header.edge_kind_names,
    lengths: a.length_m as Float32Array,
    timeUv: a.time_uv_s as Float32Array,
    timeVu: a.time_vu_s as Float32Array,
    nodeY: (n) => xyz[3 * n + 1]!,
    sources: net.header.edge_sources,
  });
  return { ok: true, from, to, path, summary };
}

/** The route between the two ends of the route tool, recomputed when they change. */
export function useRoute(net: Network | undefined, route: Route): RouteResult | null {
  return useMemo(
    () => (net && route.from && route.to ? computeRoute(net, route.from, route.to) : null),
    [net, route.from, route.to],
  );
}

/** The drawn polyline of a path (the edges' real geometry, in travel order). */
export function pathPolyline(net: Network, path: Path): Vec3[] {
  const { segStart } = networkIndex(net);
  const seg = net.arrays.segment_xyz as Float32Array;
  const edgeNodes = net.arrays.edge_nodes as Uint32Array;
  const out: Vec3[] = [];
  path.edges.forEach((e, i) => {
    const pts: Vec3[] = [];
    for (let s = segStart[e]!; s < segStart[e + 1]!; s++) {
      if (s === segStart[e]) pts.push([seg[6 * s]!, seg[6 * s + 1]!, seg[6 * s + 2]!]);
      pts.push([seg[6 * s + 3]!, seg[6 * s + 4]!, seg[6 * s + 5]!]);
    }
    if (edgeNodes[2 * e] !== path.nodes[i]) pts.reverse();
    out.push(...(out.length ? pts.slice(1) : pts));
  });
  if (!out.length && path.nodes.length) out.push(nodePosition(net, path.nodes[0]!));
  return out;
}

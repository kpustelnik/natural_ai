// Shortest paths on the walk graph (network.json + .bin). Each edge has a walking time per
// direction (stairs are slower going up), so the graph is directed: an adjacency in CSR form
// and Dijkstra with a binary heap. Pure functions, unit-tested in graph.test.ts.

export interface Csr {
  n: number;
  offsets: Uint32Array; // node v's out-edges are offsets[v] .. offsets[v + 1] - 1
  targets: Uint32Array;
  times: Float32Array;
  edges: Uint32Array; // edge index of each out-edge
}

export function buildCsr(n: number, edgeNodes: Uint32Array, timeUv: Float32Array, timeVu: Float32Array): Csr {
  const e = timeUv.length;
  const degree = new Uint32Array(n + 1);
  for (let i = 0; i < e; i++) {
    degree[edgeNodes[2 * i]! + 1]!++;
    degree[edgeNodes[2 * i + 1]! + 1]!++;
  }
  for (let v = 0; v < n; v++) degree[v + 1]! += degree[v]!;
  const offsets = degree;
  const fill = offsets.slice(0, n);
  const targets = new Uint32Array(2 * e);
  const times = new Float32Array(2 * e);
  const edges = new Uint32Array(2 * e);
  for (let i = 0; i < e; i++) {
    const u = edgeNodes[2 * i]!;
    const v = edgeNodes[2 * i + 1]!;
    let k = fill[u]!++;
    targets[k] = v;
    times[k] = timeUv[i]!;
    edges[k] = i;
    k = fill[v]!++;
    targets[k] = u;
    times[k] = timeVu[i]!;
    edges[k] = i;
  }
  return { n, offsets, targets, times, edges };
}

export interface Path {
  time: number; // seconds
  nodes: number[]; // from .. to
  edges: number[]; // edges[i] joins nodes[i] and nodes[i + 1]
}

/** Fastest path from `from` to `to`, or null when `to` cannot be reached. */
export function shortestPath(g: Csr, from: number, to: number): Path | null {
  const dist = new Float64Array(g.n).fill(Infinity);
  const prevEdge = new Int32Array(g.n).fill(-1);
  const prevNode = new Int32Array(g.n).fill(-1);
  const done = new Uint8Array(g.n);
  const heap = new Heap();
  dist[from] = 0;
  heap.push(from, 0);
  while (heap.size) {
    const u = heap.pop();
    if (done[u]) continue;
    done[u] = 1;
    if (u === to) break;
    const du = dist[u]!;
    for (let k = g.offsets[u]!; k < g.offsets[u + 1]!; k++) {
      const v = g.targets[k]!;
      const dv = du + g.times[k]!;
      if (dv < dist[v]!) {
        dist[v] = dv;
        prevEdge[v] = g.edges[k]!;
        prevNode[v] = u;
        heap.push(v, dv);
      }
    }
  }
  if (!Number.isFinite(dist[to]!)) return null;
  const nodes = [to];
  const edges: number[] = [];
  for (let v = to; v !== from; v = prevNode[v]!) {
    edges.push(prevEdge[v]!);
    nodes.push(prevNode[v]!);
  }
  return { time: dist[to]!, nodes: nodes.reverse(), edges: edges.reverse() };
}

/** Min-heap of (node, key) pairs; stale entries are skipped by the caller. */
class Heap {
  private nodes: number[] = [];
  private keys: number[] = [];

  get size(): number {
    return this.nodes.length;
  }

  push(node: number, key: number): void {
    const { nodes, keys } = this;
    let i = nodes.length;
    nodes.push(node);
    keys.push(key);
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (keys[p]! <= key) break;
      nodes[i] = nodes[p]!;
      keys[i] = keys[p]!;
      i = p;
    }
    nodes[i] = node;
    keys[i] = key;
  }

  pop(): number {
    const { nodes, keys } = this;
    const top = nodes[0]!;
    const lastNode = nodes.pop()!;
    const lastKey = keys.pop()!;
    const n = nodes.length;
    if (n) {
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        if (l >= n) break;
        const c = l + 1 < n && keys[l + 1]! < keys[l]! ? l + 1 : l;
        if (keys[c]! >= lastKey) break;
        nodes[i] = nodes[c]!;
        keys[i] = keys[c]!;
        i = c;
      }
      nodes[i] = lastNode;
      keys[i] = lastKey;
    }
    return top;
  }
}

// --- route summary -------------------------------------------------------------------

export type RoutePart = "outdoor" | "indoor" | "stairs";

/** Which part of a route an edge class belongs to (edge_kind_names of the network). */
export function routePart(kind: string): RoutePart {
  if (kind === "stairs" || kind === "shaft") return "stairs";
  if (kind === "corridor" || kind === "door" || kind === "entrance" || kind === "passage") return "indoor";
  return "outdoor"; // footway, road, steps, link
}

export interface Leg {
  part: RoutePart;
  kind: string; // edge class of the first edge
  building: string | null; // for indoor and stairs legs
  length: number;
  time: number;
  rise: number; // metres up (positive) or down along the leg
  from: number; // node indices
  to: number;
}

export interface RouteSummary {
  time: number;
  length: number;
  parts: Record<RoutePart, { time: number; length: number }>;
  legs: Leg[];
}

export interface RouteInputs {
  edgeNodes: Uint32Array;
  edgeKind: Uint8Array;
  kindNames: string[];
  lengths: Float32Array;
  timeUv: Float32Array;
  timeVu: Float32Array;
  nodeY: (node: number) => number;
  sources: (string | null)[];
}

/** Totals per part and consecutive edges of the same part (and building) merged into legs. */
export function summarise(path: Path, g: RouteInputs): RouteSummary {
  const parts: RouteSummary["parts"] = {
    outdoor: { time: 0, length: 0 },
    indoor: { time: 0, length: 0 },
    stairs: { time: 0, length: 0 },
  };
  const legs: Leg[] = [];
  let length = 0;
  path.edges.forEach((e, i) => {
    const a = path.nodes[i]!;
    const b = path.nodes[i + 1]!;
    const forward = g.edgeNodes[2 * e] === a;
    const time = forward ? g.timeUv[e]! : g.timeVu[e]!;
    const kind = g.kindNames[g.edgeKind[e]!]!;
    const part = routePart(kind);
    const building = part === "outdoor" ? null : (g.sources[e] ?? null);
    const len = g.lengths[e]!;
    length += len;
    parts[part].time += time;
    parts[part].length += len;
    const last = legs[legs.length - 1];
    if (last && last.part === part && last.building === building) {
      last.length += len;
      last.time += time;
      last.rise += g.nodeY(b) - g.nodeY(a);
      last.to = b;
    } else {
      legs.push({ part, kind, building, length: len, time, rise: g.nodeY(b) - g.nodeY(a), from: a, to: b });
    }
  });
  return { time: path.time, length, parts, legs };
}

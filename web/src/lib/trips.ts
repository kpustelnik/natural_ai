// Student trips (contract 10.6): distinct paths stored once, and per day one segment per
// (student, path, start time). Everything here is allocation-free per frame, so it runs
// for 20,000 students every frame.

/** Distinct paths of one scenario: vertices `offsets[p] .. offsets[p+1]-1`. */
export interface Paths {
  offsets: Uint32Array; // (P+1)
  xyz: Float32Array; // (V*3)
  t: Float32Array; // (V) seconds since the start of the path
  mode: Uint8Array; // (P) 0 walk, 1 metro
}

/** One day of one scenario, with the time each segment stays on screen. */
export interface Day {
  student: Uint32Array;
  leg: Uint32Array;
  path: Uint32Array;
  start: Float32Array; // sorted
  end: Float32Array; // start of the leg's next segment, else the end of the path
  maxSpan: number; // longest end - start: how far back a still-visible segment can start
  rank: Uint32Array; // place in its group: rows with the same path and start move together
}

export const WALK = 0;
export const METRO = 1;

/** Student states, for colour: walking, waiting (standing between two segments), riding. */
export const State = { Walk: 0, Wait: 1, Ride: 2 } as const;
export type State = (typeof State)[keyof typeof State];

export function duration(paths: Paths, p: number): number {
  return paths.t[paths.offsets[p + 1]! - 1]!;
}

/** Adds `end` and `maxSpan`: a segment shows until the next segment of its leg starts (the
 * student waits at the end of the path), and the last one of a leg until its path ends. */
export function prepareDay(
  paths: Paths,
  rows: { student_id: Uint32Array; leg_id: Uint32Array; path_id: Uint32Array; t_start: Float32Array },
): Day {
  const n = rows.t_start.length;
  const end = new Float32Array(n);
  const next = new Map<number, number>();
  let maxSpan = 0;
  for (let i = n - 1; i >= 0; i--) {
    const leg = rows.leg_id[i]!;
    const s = rows.t_start[i]!;
    const e = next.get(leg) ?? s + duration(paths, rows.path_id[i]!);
    end[i] = e;
    next.set(leg, s);
    if (e - s > maxSpan) maxSpan = e - s;
  }
  // the simulation is deterministic: everyone on the same path leaving at the same second
  // is at the same point. Number them, so the view can spread each group out.
  const order = Array.from({ length: n }, (_, i) => i).sort(
    (a, b) => rows.path_id[a]! - rows.path_id[b]! || rows.t_start[a]! - rows.t_start[b]!,
  );
  const rank = new Uint32Array(n);
  for (let k = 1; k < n; k++) {
    const a = order[k - 1]!;
    const b = order[k]!;
    if (rows.path_id[a] === rows.path_id[b] && rows.t_start[a] === rows.t_start[b]) rank[b] = rank[a]! + 1;
  }
  return { student: rows.student_id, leg: rows.leg_id, path: rows.path_id, start: rows.t_start, end, maxSpan, rank };
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/** Offset of the k-th member of a group in a sunflower spiral with spacing 1: a group of n
 * covers a disc of radius about sqrt(n), so its area shows how many there are. */
export function spiral(k: number, out: number[]): void {
  const r = Math.sqrt(k);
  const a = k * GOLDEN_ANGLE;
  out[0] = r * Math.cos(a);
  out[1] = r * Math.sin(a);
}

/** First index with a[i] >= v (a sorted ascending). */
export function lowerBound(a: Float32Array, v: number, lo = 0, hi = a.length): number {
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (a[mid]! < v) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Range of rows that may be on screen at `t`; check `end[i] > t` for each. */
export function candidates(day: Day, t: number): [number, number] {
  return [lowerBound(day.start, t - day.maxSpan), lowerBound(day.start, t + 1e-3)];
}

/** Position on path `p` at `tau` seconds after its start (clamped) into `out[o..o+2]`;
 * returns whether the student is still moving. */
export function positionAt(paths: Paths, p: number, tau: number, out: Float32Array | number[], o = 0): boolean {
  const a = paths.offsets[p]!;
  const b = paths.offsets[p + 1]! - 1;
  const t = paths.t;
  const xyz = paths.xyz;
  if (tau >= t[b]!) {
    out[o] = xyz[3 * b]!;
    out[o + 1] = xyz[3 * b + 1]!;
    out[o + 2] = xyz[3 * b + 2]!;
    return false;
  }
  if (tau <= 0 || b === a) {
    out[o] = xyz[3 * a]!;
    out[o + 1] = xyz[3 * a + 1]!;
    out[o + 2] = xyz[3 * a + 2]!;
    return b !== a;
  }
  // last vertex with t <= tau
  let lo = a;
  let hi = b;
  while (hi - lo > 1) {
    const mid = (lo + hi) >>> 1;
    if (t[mid]! <= tau) lo = mid;
    else hi = mid;
  }
  const span = t[hi]! - t[lo]!;
  const f = span > 0 ? (tau - t[lo]!) / span : 1;
  out[o] = xyz[3 * lo]! + (xyz[3 * hi]! - xyz[3 * lo]!) * f;
  out[o + 1] = xyz[3 * lo + 1]! + (xyz[3 * hi + 1]! - xyz[3 * lo + 1]!) * f;
  out[o + 2] = xyz[3 * lo + 2]! + (xyz[3 * hi + 2]! - xyz[3 * lo + 2]!) * f;
  return true;
}

export interface Frame {
  n: number; // students on screen
  xyz: Float32Array; // (n*3)
  state: Uint8Array; // (n) State
  student: Uint32Array; // (n)
  rank: Uint32Array; // (n) place in the group moving together
  counts: [number, number, number]; // walking, waiting, riding
}

export function makeFrame(capacity: number): Frame {
  return {
    n: 0,
    xyz: new Float32Array(capacity * 3),
    state: new Uint8Array(capacity),
    student: new Uint32Array(capacity),
    rank: new Uint32Array(capacity),
    counts: [0, 0, 0],
  };
}

/** Every student on screen at `t` (seconds since 00:00) into `f`. */
export function studentsAt(paths: Paths, day: Day, t: number, f: Frame): Frame {
  const [lo, hi] = candidates(day, t);
  const cap = f.state.length;
  let n = 0;
  f.counts[0] = f.counts[1] = f.counts[2] = 0;
  for (let i = lo; i < hi && n < cap; i++) {
    if (day.end[i]! <= t) continue;
    const p = day.path[i]!;
    const moving = positionAt(paths, p, t - day.start[i]!, f.xyz, 3 * n);
    const s: State = paths.mode[p] === METRO ? State.Ride : moving ? State.Walk : State.Wait;
    f.state[n] = s;
    f.student[n] = day.student[i]!;
    f.rank[n] = day.rank[i]!;
    f.counts[s]++;
    n++;
  }
  f.n = n;
  return f;
}

/** Most students on screen at once over the day (sweep over starts and ends). */
export function peakCount(day: Day): number {
  const ends = Float32Array.from(day.end).sort();
  let peak = 0;
  let j = 0;
  for (let i = 0; i < day.start.length; i++) {
    while (j < ends.length && ends[j]! <= day.start[i]!) j++;
    peak = Math.max(peak, i + 1 - j);
  }
  return peak;
}

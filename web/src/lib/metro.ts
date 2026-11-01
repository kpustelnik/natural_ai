// Playback maths for the Metro workspace, without three.js: train positions from the
// timetable (metro.json) and the ACO trace interpolated between sampled iterations.

import type { Metro } from "../generated/schemas";
import type { Vec3 } from "./frames";

// --- trains --------------------------------------------------------------------------

export interface DayRuns {
  starts: Float64Array; // first departure of each run, sorted
  ends: Float64Array; // last arrival
  runs: Metro["runs"];
  longest: number; // longest run duration, bounds the search window
}

/** Runs of one weekday, sorted by start, for fast lookup every frame. On a loop a run lasts
 *  until its train leaves on the next round (the dwell at station 0), so the train stays
 *  drawn there instead of vanishing between rounds. */
export function dayRuns(metro: Metro, weekday: number): DayRuns {
  const runs = metro.runs.filter((r) => r.weekday === weekday).sort((a, b) => a.stops[0].depart_t - b.stops[0].depart_t);
  const starts = new Float64Array(runs.map((r) => r.stops[0].depart_t));
  const layover = metro.topology === "loop" ? metro.dwell_s : 0;
  const ends = new Float64Array(runs.map((r) => r.stops[r.stops.length - 1]!.arrive_t + layover));
  let longest = 0;
  for (let i = 0; i < runs.length; i++) longest = Math.max(longest, ends[i]! - starts[i]!);
  return { starts, ends, runs, longest };
}

export interface TrainState {
  position: Vec3;
  heading: number; // radians, atan2(dx, dz) of the travel direction
  station: number | null; // standing at this station, else moving
}

/** Where every running train is at time `t` (seconds since 00:00). */
export function trainsAt(metro: Metro, day: DayRuns, t: number): TrainState[] {
  const out: TrainState[] = [];
  // runs that started before t but not longer ago than the longest run
  let lo = 0;
  let hi = day.starts.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (day.starts[mid]! < t - day.longest) lo = mid + 1;
    else hi = mid;
  }
  for (let i = lo; i < day.runs.length && day.starts[i]! <= t; i++) {
    if (day.ends[i]! < t) continue;
    const stops = day.runs[i]!.stops;
    let j = 0;
    while (j < stops.length - 1 && stops[j + 1]!.arrive_t <= t) j++;
    const a = metro.stations[stops[j]!.station]!.platform;
    const next = stops[Math.min(j + 1, stops.length - 1)]!;
    const prev = stops[Math.max(j - 1, 0)]!;
    if (t <= stops[j]!.depart_t || j === stops.length - 1) {
      // dwelling: face the next station (at the end of a line run the previous one; a loop
      // goes on round, towards the run's second stop)
      const end = j === stops.length - 1;
      const loop = metro.topology === "loop";
      const towards = end && !loop ? metro.stations[prev.station]!.platform : metro.stations[(end ? stops[1]! : next).station]!.platform;
      const h = end && !loop ? heading(towards, a) : heading(a, towards);
      out.push({ position: [...a], heading: h, station: stops[j]!.station });
      continue;
    }
    const b = metro.stations[next.station]!.platform;
    const f = (t - stops[j]!.depart_t) / Math.max(1e-6, next.arrive_t - stops[j]!.depart_t);
    out.push({ position: lerp(a, b, f), heading: heading(a, b), station: null });
  }
  return out;
}

/** Rotation about y that faces from ``a`` to ``b`` (web frame). */
export function heading(a: readonly number[], b: readonly number[]): number {
  return Math.atan2(b[0]! - a[0]!, b[2]! - a[2]!);
}

export function lerp(a: Vec3, b: Vec3, f: number): Vec3 {
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

/** Point at fraction `f` (0..1) of the length of a polyline. */
export function alongPolyline(points: Vec3[], f: number): Vec3 {
  if (points.length === 1) return [...points[0]!];
  const lengths = points.slice(1).map((p, i) => Math.hypot(p[0] - points[i]![0], p[1] - points[i]![1], p[2] - points[i]![2]));
  const total = lengths.reduce((s, l) => s + l, 0);
  let rest = Math.min(1, Math.max(0, f)) * total;
  for (let i = 0; i < lengths.length; i++) {
    if (rest <= lengths[i]! || i === lengths.length - 1) return lerp(points[i]!, points[i + 1]!, lengths[i]! ? rest / lengths[i]! : 0);
    rest -= lengths[i]!;
  }
  return [...points[points.length - 1]!];
}

// --- ACO trace -----------------------------------------------------------------------

/** Sample index and fraction for a (fractional) iteration: the sampled iteration at or
 * before it, and how far it is towards the next sample. */
export function sampleAt(iterations: Int32Array, iteration: number): { s: number; f: number } {
  const n = iterations.length;
  if (!n || iteration <= iterations[0]!) return { s: 0, f: 0 };
  if (iteration >= iterations[n - 1]!) return { s: n - 1, f: 0 };
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (iterations[mid]! <= iteration) lo = mid;
    else hi = mid;
  }
  return { s: lo, f: (iteration - iterations[lo]!) / (iterations[hi]! - iterations[lo]!) };
}

/** Value of a curve (sorted x) at x, holding the last value before it. */
export function curveAt(xs: Int32Array, ys: Float32Array, x: number): number {
  let lo = 0;
  let hi = xs.length - 1;
  if (hi < 0) return NaN;
  if (x <= xs[0]!) return ys[0]!;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (xs[mid]! <= x) lo = mid;
    else hi = mid - 1;
  }
  return ys[lo]!;
}

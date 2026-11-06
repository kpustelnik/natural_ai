// One student's day from students/day-<weekday> (StudentsHeader): their legs in order, with
// both scenarios side by side. Pure functions over the typed arrays, unit-tested.

export const NONE16 = 65535;
export const MODE_LABEL = ["walk", "metro", "bus / tram"] as const;

export interface StudentArrays {
  student_id: Uint32Array;
  leg_id: Uint32Array;
  leg_kind: Uint8Array;
  from: Uint16Array;
  to: Uint16Array;
  earliest: Float32Array;
  deadline: Float32Array;
  [k: string]: ArrayLike<number>;
}

export interface Trip {
  depart: number;
  arrive: number;
  wait: number;
  late: number;
  mode: number; // 0 walk, 1 metro, 2 bus / tram
  board: string | null;
  alight: string | null;
}

export interface LegRow {
  leg: number;
  kind: string;
  from: string;
  to: string;
  earliest: number | null; // the previous class ends
  deadline: number | null; // the class starts
  trips: Record<string, Trip>; // scenario -> how it went
}

/** Rows [lo, hi) of `id` (student_id is sorted). */
export function rowsOf(ids: Uint32Array, id: number): [number, number] {
  let lo = 0;
  let hi = ids.length;
  while (lo < hi) {
    const m = (lo + hi) >>> 1;
    if (ids[m]! < id) lo = m + 1;
    else hi = m;
  }
  let end = lo;
  while (end < ids.length && ids[end] === id) end++;
  return [lo, end];
}

const key = (keys: string[], i: number) => (i === NONE16 ? null : (keys[i] ?? null));
const num = (v: number) => (Number.isNaN(v) ? null : v);

/** The legs of one student, in the order of the day. */
export function studentLegs(a: StudentArrays, keys: string[], kinds: string[], scenarios: string[], id: number): LegRow[] {
  const [lo, hi] = rowsOf(a.student_id, id);
  const out: LegRow[] = [];
  for (let i = lo; i < hi; i++) {
    const trips: Record<string, Trip> = {};
    for (const sc of scenarios) {
      const dep = a[`${sc}_depart`];
      if (!dep || Number.isNaN(dep[i]!)) continue;
      trips[sc] = {
        depart: dep[i]!,
        arrive: a[`${sc}_arrive`]![i]!,
        wait: a[`${sc}_wait`]![i]!,
        late: a[`${sc}_late`]![i]!,
        mode: a[`${sc}_mode`]![i]!,
        board: key(keys, a[`${sc}_board`]![i]!),
        alight: key(keys, a[`${sc}_alight`]![i]!),
      };
    }
    out.push({
      leg: a.leg_id[i]!,
      kind: kinds[a.leg_kind[i]!] ?? "",
      from: key(keys, a.from[i]!) ?? "?",
      to: key(keys, a.to[i]!) ?? "?",
      earliest: num(a.earliest[i]!),
      deadline: num(a.deadline[i]!),
      trips,
    });
  }
  return out;
}

/** Travel time, late legs and metro legs of a day's legs in one scenario. */
export function dayTotals(legs: LegRow[], scenario: string): { travel: number; late: number; metro: number; n: number } {
  let travel = 0;
  let late = 0;
  let metro = 0;
  let n = 0;
  for (const l of legs) {
    const t = l.trips[scenario];
    if (!t) continue;
    n++;
    travel += t.arrive - t.depart;
    if (t.late > 0) late++;
    if (t.mode === 1) metro++;
  }
  return { travel, late, metro, n };
}

/** A random student of the day; with `metroOnly`, one who takes the metro at least once. */
export function randomStudent(a: StudentArrays, metroOnly: boolean, rnd = Math.random): number | null {
  const n = a.student_id.length;
  if (!n) return null;
  const mode = a.metro_mode;
  for (let tries = 0; tries < 2000; tries++) {
    const i = Math.floor(rnd() * n);
    if (!metroOnly || (mode && mode[i] === 1)) return a.student_id[i]!;
  }
  return a.student_id[Math.floor(rnd() * n)]!;
}

/** "stop:plac_inwalidow" -> "stop Plac inwalidow"; rooms and buildings stay as they are. */
export function placeName(k: string): string {
  if (k.startsWith("stop:")) {
    const s = k.slice(5).replace(/_/g, " ");
    return `stop ${s.charAt(0).toUpperCase()}${s.slice(1)}`;
  }
  return k;
}

/** Where the student is at `t` in a scenario: on a leg, in a class, or not on campus. */
export function whereAt(legs: LegRow[], scenario: string, t: number): string {
  let last: LegRow | null = null;
  for (const l of legs) {
    const tr = l.trips[scenario];
    if (!tr) continue;
    if (t < tr.depart) return last ? `at ${placeName(last.to)}` : "not on campus yet";
    if (t <= tr.arrive) return `on the way ${placeName(l.from)} → ${placeName(l.to)} (${MODE_LABEL[tr.mode] ?? "?"})`;
    last = l;
  }
  return last ? (last.kind === "class_to_home" ? "gone home" : `at ${placeName(last.to)}`) : "no classes today";
}

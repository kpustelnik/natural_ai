import { describe, expect, it } from "vitest";
import { arrivedBy, binLegs, candidates, dayLegs, makeFrame, type Paths, peakCount, positionAt, prepareDay, spiral, State, stateCurve, studentsAt } from "./trips";

// path 0: walk 100 m east in 100 s; path 1: ride 0 -> 0,-15,-500 in 50 s; path 2: walk 10 s
const paths: Paths = {
  offsets: new Uint32Array([0, 3, 5, 7]),
  xyz: new Float32Array([0, 0, 0, 50, 0, 0, 100, 0, 0, 100, -15, 0, 100, -15, -500, 100, 0, -500, 110, 0, -500]),
  t: new Float32Array([0, 50, 100, 0, 50, 0, 10]),
  mode: new Uint8Array([0, 1, 0]),
};

// student 7, leg 3: walk (t 1000), wait until the train at 1150, ride, walk out at 1200
// student 8, leg 4: one walk from 1050
const day = prepareDay(paths, {
  student_id: new Uint32Array([7, 8, 7, 7]),
  leg_id: new Uint32Array([3, 4, 3, 3]),
  path_id: new Uint32Array([0, 0, 1, 2]),
  t_start: new Float32Array([1000, 1050, 1150, 1200]),
});

describe("trips", () => {
  it("shows a segment until the next one of its leg", () => {
    expect(Array.from(day.end)).toEqual([1150, 1150, 1200, 1210]);
    expect(day.maxSpan).toBe(150);
  });

  it("interpolates along a path and clamps at its ends", () => {
    const out = [0, 0, 0];
    expect(positionAt(paths, 0, 75, out)).toBe(true);
    expect(out).toEqual([75, 0, 0]);
    expect(positionAt(paths, 0, 500, out)).toBe(false);
    expect(out).toEqual([100, 0, 0]);
    expect(positionAt(paths, 0, -5, out)).toBe(true);
    expect(out).toEqual([0, 0, 0]);
  });

  it("finds the students on screen with their state", () => {
    const f = makeFrame(10);
    studentsAt(paths, day, 1120, f); // 7 waits on the platform, 8 walks
    expect(f.n).toBe(2);
    expect(Array.from(f.student.subarray(0, 2))).toEqual([7, 8]);
    expect(Array.from(f.state.subarray(0, 2))).toEqual([State.Wait, State.Walk]);
    expect(Array.from(f.xyz.subarray(3, 6))).toEqual([70, 0, 0]);
    expect(f.counts).toEqual([1, 1, 0, 0]);

    studentsAt(paths, day, 1175, f); // 7 rides, 8 has arrived
    expect(f.n).toBe(1);
    expect(f.state[0]).toBe(State.Metro);
    expect(f.xyz[1]).toBe(-15);
    expect(studentsAt(paths, day, 1300, f).n).toBe(0);
    expect(studentsAt(paths, day, 999, f).n).toBe(0);
  });

  it("only scans rows that can be on screen", () => {
    const [lo, hi] = candidates(day, 1300);
    expect(lo).toBe(2); // 1300 - maxSpan = 1150: the ride and the last walk
    expect(hi).toBe(4);
  });

  it("numbers the members of groups that move together", () => {
    const g = prepareDay(paths, {
      student_id: new Uint32Array([1, 2, 3, 4]),
      leg_id: new Uint32Array([1, 2, 3, 4]),
      path_id: new Uint32Array([0, 0, 2, 0]),
      t_start: new Float32Array([500, 500, 500, 600]),
    });
    expect(Array.from(g.rank)).toEqual([0, 1, 0, 0]);
    const o = [0, 0];
    spiral(0, o);
    expect(o).toEqual([0, 0]);
    spiral(9, o);
    expect(Math.hypot(o[0]!, o[1]!)).toBeCloseTo(3);
  });

  it("counts the peak", () => {
    expect(peakCount(day)).toBe(2);
  });

  it("links each segment to the next one of its leg", () => {
    expect(Array.from(day.next)).toEqual([2, -1, 3, -1]);
  });

  it("sums up the legs of the day", () => {
    const legs = dayLegs(paths, day);
    expect(Array.from(legs.leg)).toEqual([4, 3]); // by arrival: 4 at 1150, 3 at 1210
    expect(Array.from(legs.arrive)).toEqual([1150, 1210]);
    expect(Array.from(legs.mode)).toEqual([0, 1]);
    expect(arrivedBy(legs, 1160)).toEqual({ n: 1, mean: 100 });
    expect(arrivedBy(legs, 1300)).toEqual({ n: 2, mean: 155 });
    const b = binLegs(legs, 1000, 1300, 100);
    expect(Array.from(b.n)).toEqual([0, 1, 1]);
    expect(Array.from(b.metro)).toEqual([0, 0, 1]);
    const c = stateCurve(paths, day, 1120, 1175, 2);
    expect(Array.from(c[State.Wait]!)).toEqual([1, 0]);
    expect(Array.from(c[State.Metro]!)).toEqual([0, 1]);
  });
});

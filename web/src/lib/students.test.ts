import { describe, expect, it } from "vitest";
import { dayTotals, NONE16, placeName, randomStudent, rowsOf, type StudentArrays, studentLegs, whereAt } from "./students";

// student 3: home (stop) -> D-17 for 8:00 by metro, D-17 -> home; student 5: one walk
const a: StudentArrays = {
  student_id: new Uint32Array([3, 3, 5]),
  leg_id: new Uint32Array([10, 11, 12]),
  leg_kind: new Uint8Array([1, 0, 1]),
  from: new Uint16Array([0, 1, 2]),
  to: new Uint16Array([1, 0, 1]),
  earliest: new Float32Array([NaN, 36000, NaN]),
  deadline: new Float32Array([28800, NaN, 30000]),
  metro_depart: new Float32Array([28000, 36000, 29000]),
  metro_arrive: new Float32Array([28700, 36500, 29400]),
  metro_wait: new Float32Array([60, 0, 0]),
  metro_late: new Float32Array([0, 0, 0]),
  metro_mode: new Uint8Array([1, 0, 0]),
  metro_board: new Uint16Array([3, NONE16, NONE16]),
  metro_alight: new Uint16Array([1, NONE16, NONE16]),
};
const keys = ["stop:plac_inwalidow", "D-17", "H-D8", "A-0"];
const kinds = ["class_to_home", "home_to_class"];

describe("students", () => {
  it("finds a student's rows", () => {
    expect(rowsOf(a.student_id, 3)).toEqual([0, 2]);
    expect(rowsOf(a.student_id, 5)).toEqual([2, 3]);
    expect(rowsOf(a.student_id, 4)).toEqual([2, 2]);
  });

  it("reads a student's legs", () => {
    const legs = studentLegs(a, keys, kinds, ["metro"], 3);
    expect(legs).toHaveLength(2);
    expect(legs[0]!.from).toBe("stop:plac_inwalidow");
    expect(legs[0]!.deadline).toBe(28800);
    expect(legs[0]!.earliest).toBeNull();
    expect(legs[0]!.trips.metro).toMatchObject({ mode: 1, board: "A-0", alight: "D-17", wait: 60 });
    expect(legs[1]!.trips.metro!.board).toBeNull();
    expect(dayTotals(legs, "metro")).toEqual({ travel: 1200, late: 0, metro: 1, n: 2 });
  });

  it("says where the student is", () => {
    const legs = studentLegs(a, keys, kinds, ["metro"], 3);
    expect(whereAt(legs, "metro", 20000)).toBe("not on campus yet");
    expect(whereAt(legs, "metro", 28100)).toContain("on the way");
    expect(whereAt(legs, "metro", 30000)).toBe("at D-17");
    expect(whereAt(legs, "metro", 40000)).toBe("gone home");
  });

  it("picks a metro rider and names places", () => {
    expect(randomStudent(a, true, () => 0.9)).toBe(5); // always row 2, no rider: gives up and takes it
    expect(randomStudent(a, true, () => 0.1)).toBe(3);
    expect(placeName("stop:plac_inwalidow")).toBe("stop Plac inwalidow");
    expect(placeName("D-17/1.38")).toBe("D-17/1.38");
  });
});

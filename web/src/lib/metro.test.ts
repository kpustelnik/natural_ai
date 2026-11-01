import { describe, expect, it } from "vitest";
import type { Metro } from "../generated/schemas";
import { alongPolyline, curveAt, dayRuns, sampleAt, trainsAt } from "./metro";

const prov = { schema_version: 1, generated_at: "", generator: "test", config_hash: null, git_commit: null };

// A (0,-15,0) -- 100 m east -- B (100,-15,0): one run each way, 10 s per hop, 30 s dwell at B
const metro: Metro = {
  provenance: prov,
  topology: "line",
  stations: [
    { building_id: "A-0", top: [0, 0, 0], platform: [0, -15, 0] },
    { building_id: "B-1", top: [100, 0, 0], platform: [100, -15, 0] },
    { building_id: "C-2", top: [100, 0, -100], platform: [100, -15, -100] },
  ],
  tunnel: [
    [0, -15, 0],
    [100, -15, 0],
    [100, -15, -100],
  ],
  headway_s: 180,
  dwell_s: 30,
  speed_mps: 10,
  runs: [
    {
      run_id: 0,
      train_id: 0,
      weekday: 1,
      direction: 1,
      stops: [
        { station: 0, arrive_t: 1000, depart_t: 1000 },
        { station: 1, arrive_t: 1010, depart_t: 1040 },
        { station: 2, arrive_t: 1050, depart_t: 1050 },
      ],
    },
    {
      run_id: 1,
      train_id: 1,
      weekday: 2,
      direction: 1,
      stops: [
        { station: 0, arrive_t: 1000, depart_t: 1000 },
        { station: 1, arrive_t: 1010, depart_t: 1010 },
      ],
    },
  ],
};

describe("trainsAt", () => {
  const day = dayRuns(metro, 1);

  it("moves trains between platforms and holds them at stations", () => {
    expect(trainsAt(metro, day, 999)).toEqual([]);
    const moving = trainsAt(metro, day, 1005)[0]!;
    expect(moving.position).toEqual([50, -15, 0]);
    expect(moving.station).toBeNull();
    expect(moving.heading).toBeCloseTo(Math.PI / 2); // towards +x
    const dwelling = trainsAt(metro, day, 1020)[0]!;
    expect(dwelling.station).toBe(1);
    expect(dwelling.position).toEqual([100, -15, 0]);
    expect(trainsAt(metro, day, 1045)[0]!.position).toEqual([100, -15, -50]);
    expect(trainsAt(metro, day, 1051)).toEqual([]);
  });

  it("only uses the runs of the weekday", () => {
    expect(dayRuns(metro, 2).runs).toHaveLength(1);
    expect(dayRuns(metro, 3).runs).toHaveLength(0);
  });
});

describe("trainsAt on a loop", () => {
  // A -> B -> C -> A in one run, then the same train's next round 30 s (the dwell) later
  const stops = (t: number): Metro["runs"][number]["stops"] => [
    { station: 0, arrive_t: t, depart_t: t },
    { station: 1, arrive_t: t + 10, depart_t: t + 40 },
    { station: 2, arrive_t: t + 50, depart_t: t + 80 },
    { station: 0, arrive_t: t + 94, depart_t: t + 94 },
  ];
  const loop: Metro = {
    ...metro,
    topology: "loop",
    runs: [
      { run_id: 0, train_id: 0, weekday: 1, direction: 1, stops: stops(1000) },
      { run_id: 1, train_id: 0, weekday: 1, direction: 1, stops: stops(1124) },
    ],
  };
  it("keeps the train at station 0 between rounds, facing on round", () => {
    const day = dayRuns(loop, 1);
    const between = trainsAt(loop, day, 1110); // back at A at 1094, leaves again at 1124
    expect(between).toHaveLength(1);
    expect(between[0]!.station).toBe(0);
    const leaving = trainsAt(loop, day, 1124)[0]!;
    expect(between[0]!.heading).toBeCloseTo(leaving.heading); // towards B, as it will go
  });
});

describe("trace helpers", () => {
  it("finds the sample before an iteration", () => {
    const it = new Int32Array([0, 5, 10]);
    expect(sampleAt(it, 0)).toEqual({ s: 0, f: 0 });
    expect(sampleAt(it, 7.5)).toEqual({ s: 1, f: 0.5 });
    expect(sampleAt(it, 12)).toEqual({ s: 2, f: 0 });
  });

  it("reads a step curve", () => {
    const xs = new Int32Array([0, 1, 2, 3]);
    const ys = new Float32Array([9, 8, 8, 5]);
    expect(curveAt(xs, ys, 2.7)).toBe(8);
    expect(curveAt(xs, ys, 10)).toBe(5);
  });

  it("walks along a polyline by length", () => {
    const pts: [number, number, number][] = [
      [0, 0, 0],
      [10, 0, 0],
      [10, 0, 30],
    ];
    expect(alongPolyline(pts, 0.5)).toEqual([10, 0, 10]);
    expect(alongPolyline(pts, 1)).toEqual([10, 0, 30]);
  });
});

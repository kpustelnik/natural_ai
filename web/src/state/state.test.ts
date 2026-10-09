import { describe, expect, it } from "vitest";
import { app, captureText, pickKey, stepLevel } from "./app";
import { parsePick } from "./url";

describe("picks in the URL", () => {
  it("round-trips a room", () => {
    const p = { kind: "space" as const, building: "D-17", id: "1.38", level: 1 };
    expect(parsePick(pickKey(p))).toEqual(p);
  });
  it("keeps negative levels", () => {
    expect(parsePick("space:A-0/cb@-1")).toEqual({ kind: "space", building: "A-0", id: "cb", level: -1 });
  });
});

describe("level stepper", () => {
  it("steps up to the whole building and back down", () => {
    app.set({ level: 0 });
    stepLevel([-1, 0, 1], 1);
    expect(app.get().level).toBe(1);
    stepLevel([-1, 0, 1], 1);
    expect(app.get().level).toBe(null);
    stepLevel([-1, 0, 1], -1);
    expect(app.get().level).toBe(1);
    stepLevel([-1, 0, 1], -1);
    stepLevel([-1, 0, 1], -1);
    stepLevel([-1, 0, 1], -1);
    expect(app.get().level).toBe(-1);
  });
});

it("formats captured points for the YAML", () => {
  expect(captureText({ building: "D-17", points: [[0, 0], [12.4, -3.1]], web: [] })).toBe("[[0, 0], [12.4, -3.1]]");
});

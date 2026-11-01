import { describe, expect, it } from "vitest";
import { formatPose, parsePick, parsePose } from "./url";

describe("url state", () => {
  it("parses selections", () => {
    expect(parsePick("building:D-17")).toEqual({ kind: "building", id: "D-17" });
    expect(parsePick("stop:stop:czarnowiejska")).toEqual({ kind: "stop", id: "stop:czarnowiejska" });
    expect(parsePick("entrance:D-17#main")).toEqual({ kind: "entrance", building: "D-17", id: "main" });
    expect(parsePick("context:12")).toEqual({ kind: "context", fid: 12 });
    expect(parsePick("context:x")).toBeNull();
    expect(parsePick("nonsense")).toBeNull();
  });

  it("round-trips camera poses", () => {
    const pose = { position: [1, 2, 3] as [number, number, number], target: [4, 5, 6] as [number, number, number], zoom: 1.5 };
    expect(parsePose(formatPose(pose))).toEqual(pose);
    expect(parsePose("1,2")).toBeNull();
  });
});

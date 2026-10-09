import { describe, expect, it } from "vitest";
import { search, type SearchItem } from "./search";
import { parsePick, parsePose, formatPose } from "../state/url";

const items: SearchItem[] = [
  { key: "building:D-17", id: "D-17", label: "Wydział Informatyki", group: "Buildings", terms: ["D-17", "Wydział Informatyki"] },
  { key: "building:D-1", id: "D-1", label: "", group: "Buildings", terms: ["D-1"] },
  { key: "building:DS-Alfa", id: "DS-Alfa", label: "Akademik Alfa", group: "Buildings", terms: ["DS-Alfa", "Akademik Alfa"] },
  { key: "stop:stop:czarnowiejska", id: "stop:czarnowiejska", label: "Czarnowiejska", group: "Stops", terms: ["stop:czarnowiejska", "Czarnowiejska"] },
];

describe("search", () => {
  it("ranks exact ids first and ignores dashes and accents", () => {
    expect(search(items, "d17")[0]?.id).toBe("D-17");
    expect(search(items, "D-1")[0]?.id).toBe("D-1");
    expect(search(items, "wydzial")[0]?.id).toBe("D-17");
    expect(search(items, "alfa")[0]?.id).toBe("DS-Alfa");
    expect(search(items, "czarno")[0]?.group).toBe("Stops");
    expect(search(items, "zzz")).toEqual([]);
  });
});

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

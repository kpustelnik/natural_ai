import { describe, expect, it } from "vitest";
import { search, type SearchItem } from "./search";

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
    expect(search(items, "-")).toEqual([]); // separators alone match nothing
    expect(search(items, " / ")).toEqual([]);
  });
});

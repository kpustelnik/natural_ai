import { describe, expect, it } from "vitest";
import { buildCsr, routePart, shortestPath, summarise } from "./graph";

// 0 --corridor 10s-- 1 ==stairs up 12s / down 8s== 2 --corridor 5s-- 3
//  \______________________ footway 40s _______________________/
const edgeNodes = new Uint32Array([0, 1, 1, 2, 2, 3, 0, 3]);
const timeUv = new Float32Array([10, 12, 5, 40]);
const timeVu = new Float32Array([10, 8, 5, 40]);
const kindNames = ["footway", "corridor", "stairs"];
const edgeKind = new Uint8Array([1, 2, 1, 0]);
const lengths = new Float32Array([13, 7, 6.5, 52]);
const ys = [0, 0, 3.5, 3.5];
const g = buildCsr(4, edgeNodes, timeUv, timeVu);

describe("shortestPath", () => {
  it("uses the time of the direction travelled", () => {
    const up = shortestPath(g, 0, 3)!;
    expect(up.time).toBe(27);
    expect(up.nodes).toEqual([0, 1, 2, 3]);
    expect(up.edges).toEqual([0, 1, 2]);
    const down = shortestPath(g, 3, 0)!;
    expect(down.time).toBe(23);
    expect(down.nodes).toEqual([3, 2, 1, 0]);
  });

  it("takes the detour when it is faster", () => {
    const slow = buildCsr(4, edgeNodes, new Float32Array([10, 60, 5, 40]), timeVu);
    expect(shortestPath(slow, 0, 3)!.edges).toEqual([3]);
  });

  it("returns null for unreachable nodes and an empty path for from = to", () => {
    const g2 = buildCsr(5, edgeNodes, timeUv, timeVu);
    expect(shortestPath(g2, 0, 4)).toBeNull();
    expect(shortestPath(g2, 2, 2)).toEqual({ time: 0, nodes: [2], edges: [] });
  });
});

describe("summarise", () => {
  it("splits a route into outdoor, indoor and stairs", () => {
    const path = shortestPath(g, 0, 3)!;
    const s = summarise(path, {
      edgeNodes,
      edgeKind,
      kindNames,
      lengths,
      timeUv,
      timeVu,
      nodeY: (n) => ys[n]!,
      sources: ["D-17", "D-17", "D-17", "way/1"],
    });
    expect(s.length).toBeCloseTo(26.5);
    expect(s.parts.indoor).toEqual({ time: 15, length: 19.5 });
    expect(s.parts.stairs.time).toBe(12);
    expect(s.legs.map((l) => l.part)).toEqual(["indoor", "stairs", "indoor"]);
    expect(s.legs[1]!.rise).toBeCloseTo(3.5);
  });

  it("classifies edge kinds", () => {
    expect(routePart("steps")).toBe("outdoor");
    expect(routePart("link")).toBe("outdoor");
    expect(routePart("passage")).toBe("indoor");
    expect(routePart("shaft")).toBe("stairs");
  });
});

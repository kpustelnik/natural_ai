import { describe, expect, it } from "vitest";
import type { BuildingFrame } from "../generated/schemas";
import fixture from "./frames.fixture.json";
import { geoToMetric, localToWeb, metricToGeo, webToLocal } from "./frames";

describe("EPSG:2180", () => {
  it("matches pyproj in both directions", () => {
    for (const p of fixture.points) {
      const [x, y] = geoToMetric(p.lon, p.lat);
      expect(Math.abs(x - p.x)).toBeLessThan(0.001);
      expect(Math.abs(y - p.y)).toBeLessThan(0.001);
      const [lon, lat] = metricToGeo(p.x, p.y);
      expect(Math.abs(lon - p.lon)).toBeLessThan(1e-8);
      expect(Math.abs(lat - p.lat)).toBeLessThan(1e-8);
    }
  });
});

describe("building frame", () => {
  const frame: BuildingFrame = { anchor: [10, 0, -20], bearing_deg: 63 };

  it("round-trips local coordinates", () => {
    const [x, y, h] = webToLocal(frame, localToWeb(frame, 12, -4, 3));
    expect(x).toBeCloseTo(12, 9);
    expect(y).toBeCloseTo(-4, 9);
    expect(h).toBeCloseTo(3, 9);
  });

  it("puts +x along the bearing and +y to its left", () => {
    const east: BuildingFrame = { anchor: [0, 0, 0], bearing_deg: 90 };
    const px = localToWeb(east, 1, 0);
    expect(px[0]).toBeCloseTo(1); // +x = east
    expect(px[2]).toBeCloseTo(0);
    const py = localToWeb(east, 0, 1);
    expect(py[0]).toBeCloseTo(0);
    expect(py[2]).toBeCloseTo(-1); // left of east = north = -z
  });
});

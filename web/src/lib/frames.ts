// Coordinate frames (docs/data_contracts.md, section 2). Pure functions, unit-tested.
//
// web:    three.js, x = east, y = up, z = -north, metres from the scene origin
// metric: EPSG:2180 (PL-1992), E = easting, N = northing
// geo:    EPSG:4326 lon/lat
// local:  one building; origin at its anchor, +x along bearing_deg, +y to the left

import type { BuildingFrame, WebFrame } from "../generated/schemas";

export type Vec3 = [number, number, number];

// --- EPSG:2180: transverse Mercator on GRS80 (Krüger series, sub-millimetre here) ---

const A = 6378137;
const F = 1 / 298.257222101;
const K0 = 0.9993;
const LON0 = (19 * Math.PI) / 180;
const FE = 500000;
const FN = -5300000;

const N = F / (2 - F);
const N2 = N * N;
const N3 = N2 * N;
const RECT = (A / (1 + N)) * (1 + N2 / 4 + (N2 * N2) / 64);
const ALPHA = [N / 2 - (2 * N2) / 3 + (5 * N3) / 16, (13 * N2) / 48 - (3 * N3) / 5, (61 * N3) / 240];
const BETA = [N / 2 - (2 * N2) / 3 + (37 * N3) / 96, N2 / 48 + N3 / 15, (17 * N3) / 480];
const DELTA = [2 * N - (2 * N2) / 3 - 2 * N3, (7 * N2) / 3 - (8 * N3) / 5, (56 * N3) / 15];
const E2 = F * (2 - F);
const E = Math.sqrt(E2);

export function metricToGeo(east: number, north: number): [number, number] {
  const xi = (north - FN) / (K0 * RECT);
  const eta = (east - FE) / (K0 * RECT);
  let xi1 = xi;
  let eta1 = eta;
  for (let j = 1; j <= 3; j++) {
    const b = BETA[j - 1]!;
    xi1 -= b * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
    eta1 -= b * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
  }
  const chi = Math.asin(Math.sin(xi1) / Math.cosh(eta1));
  let lat = chi;
  for (let j = 1; j <= 3; j++) lat += DELTA[j - 1]! * Math.sin(2 * j * chi);
  const lon = LON0 + Math.atan2(Math.sinh(eta1), Math.cos(xi1));
  return [(lon * 180) / Math.PI, (lat * 180) / Math.PI];
}

export function geoToMetric(lon: number, lat: number): [number, number] {
  const phi = (lat * Math.PI) / 180;
  const dl = (lon * Math.PI) / 180 - LON0;
  const t = Math.sinh(Math.atanh(Math.sin(phi)) - E * Math.atanh(E * Math.sin(phi)));
  const xi1 = Math.atan2(t, Math.cos(dl));
  const eta1 = Math.atanh(Math.sin(dl) / Math.sqrt(1 + t * t));
  let xi = xi1;
  let eta = eta1;
  for (let j = 1; j <= 3; j++) {
    const a = ALPHA[j - 1]!;
    xi += a * Math.sin(2 * j * xi1) * Math.cosh(2 * j * eta1);
    eta += a * Math.cos(2 * j * xi1) * Math.sinh(2 * j * eta1);
  }
  return [FE + K0 * RECT * eta, FN + K0 * RECT * xi];
}

// --- web <-> metric / geo -------------------------------------------------------------

export function webToMetric(frame: WebFrame, p: Vec3): [number, number] {
  return [p[0] + frame.origin_x, -p[2] + frame.origin_y];
}

export function webToGeo(frame: WebFrame, p: Vec3): [number, number] {
  const [e, n] = webToMetric(frame, p);
  return metricToGeo(e, n);
}

// --- building local frame -------------------------------------------------------------

/** Web position -> building local [x, y] (metres) and height above the building ground. */
export function webToLocal(frame: BuildingFrame, p: Vec3): [number, number, number] {
  const b = (frame.bearing_deg * Math.PI) / 180;
  const de = p[0] - frame.anchor[0];
  const dn = -(p[2] - frame.anchor[2]);
  return [de * Math.sin(b) + dn * Math.cos(b), -de * Math.cos(b) + dn * Math.sin(b), p[1] - frame.anchor[1]];
}

export function localToWeb(frame: BuildingFrame, x: number, y: number, h = 0): Vec3 {
  const b = (frame.bearing_deg * Math.PI) / 180;
  const [ax, ay, az] = frame.anchor;
  return [ax + x * Math.sin(b) - y * Math.cos(b), ay + h, az - x * Math.cos(b) - y * Math.sin(b)];
}

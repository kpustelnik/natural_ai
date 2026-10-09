export function clock(t: number): string {
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function metres(v: number, digits = 1): string {
  return Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(2)} km` : `${v.toFixed(digits)} m`;
}

export function area(v: number): string {
  return `${Math.round(v).toLocaleString("en-US")} m²`;
}

export function lonLat(lon: number, lat: number): string {
  return `${lat.toFixed(6)} N  ${lon.toFixed(6)} E`;
}

export function dateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/** "way/123" -> https://www.openstreetmap.org/way/123 */
export function osmUrl(osmId: string): string {
  return `https://www.openstreetmap.org/${osmId}`;
}

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

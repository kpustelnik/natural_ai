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

/** A walking time: "42 s", "13 min 05 s", "1 h 02 min". */
export function duration(s: number): string {
  const t = Math.round(s);
  if (t < 60) return `${t} s`;
  if (t < 3600) return `${Math.floor(t / 60)} min ${String(t % 60).padStart(2, "0")} s`;
  return `${Math.floor(t / 3600)} h ${String(Math.floor((t % 3600) / 60)).padStart(2, "0")} min`;
}

/** An objective (student-seconds per week) as student-hours: "12,345 h". */
export function studentHours(s: number): string {
  return `${Math.round(s / 3600).toLocaleString("en-US")} h`;
}

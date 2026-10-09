// Live reload in dev: the Vite plugin (plugins/metroData.ts) sends status.json as the HMR
// event "metro:data" after every export. Changed JSON files are dropped from the resource
// cache, and glb files get a new version number, which is part of their URL.

import type { BuildStatus } from "../generated/schemas";
import { createStore, useSlice } from "../state/store";
import { toast } from "../state/app";
import { invalidate } from "./resource";

export const live = createStore<{ versions: Record<string, number>; status: BuildStatus | null }>({
  versions: {},
  status: null,
});

/** Version of a data file (0 until it changes); use it to cache-bust its URL. */
export function useFileVersion(path: string | null | undefined): number {
  return useSlice(live, (s) => (path ? (s.versions[path] ?? 0) : 0));
}

export function versioned(path: string, version: number): string {
  return version ? `${path}?v=${version}` : path;
}

function describe(status: BuildStatus, before: BuildStatus | null): void {
  const fresh = status.errors.filter(
    (e) => !before?.errors.some((o) => o.file === e.file && o.message === e.message && o.line === e.line),
  );
  for (const e of fresh.slice(0, 3)) {
    toast(`${e.file}${e.line ? `:${e.line}` : ""}  ${e.message}`, "error", 8000);
  }
  const rebuilt = status.changed
    .filter((p) => p.startsWith("buildings/") && p.endsWith(".glb"))
    .map((p) => p.slice("buildings/".length, -".glb".length));
  if (rebuilt.length && rebuilt.length <= 3) toast(`Reloaded ${rebuilt.join(", ")}`);
  else if (status.changed.length) toast(`Data reloaded (${status.changed.length} files)`);
  if (!fresh.length && before?.errors.length && !status.errors.length) toast("All building files are valid again");
}

export function applyStatus(status: BuildStatus): void {
  const before = live.get().status;
  if (before && before.version === status.version) return;
  if (!before) {
    // first status of the session: everything on screen is already this version
    live.set({ status });
    return;
  }
  live.set((s) => {
    const versions = { ...s.versions };
    for (const p of status.changed) versions[p] = status.version;
    return { versions, status };
  });
  invalidate([...status.changed.filter((p) => p.endsWith(".json")), "status.json"]);
  describe(status, before);
}

if (import.meta.hot) {
  import.meta.hot.on("metro:data", (status: BuildStatus) => applyStatus(status));
}

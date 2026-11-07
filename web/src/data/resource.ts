// Cached loading of data files with React hooks. Each path is fetched once; invalidate()
// (used by live reload in phase 2) drops entries so the next render refetches them.

import { useEffect, useState, useSyncExternalStore } from "react";
import type {
  AcoTraceHeader,
  WalkTraceHeader,
  BuildingInfo,
  BuildStatus,
  ContextFeatures,
  DayHeader,
  Demand,
  IssueList,
  Metro,
  NetworkHeader,
  PathsHeader,
  ReplayCatalog,
  Scene,
  Stats,
  StudentsHeader,
} from "../generated/schemas";
import { commandFor } from "../lib/commands";
import { type Day, type Paths, prepareDay } from "../lib/trips";
import { registry } from "../scene/registry";
import { toast } from "../state/app";
import { type BinaryFile, fetchJson, loadBinary, MissingDataError } from "./loader";

const cache = new Map<string, Promise<unknown>>();
const listeners = new Set<() => void>();

// files being fetched, for the loading indicator in the status bar
let pending = 0;
const pendingListeners = new Set<() => void>();
const setPending = (d: number) => {
  pending += d;
  pendingListeners.forEach((l) => l());
};
const missingReported = new Set<string>();

function load<T>(key: string, loader: () => Promise<T>): Promise<T> {
  let p = cache.get(key) as Promise<T> | undefined;
  if (!p) {
    setPending(1);
    p = loader();
    p.then(
      () => setPending(-1),
      (err: unknown) => {
        setPending(-1);
        // a file the viewer expects is missing: say once which export writes it
        if (err instanceof MissingDataError && !missingReported.has(err.message)) {
          missingReported.add(err.message);
          toast(`Missing ${err.message}: ${commandFor(err.message)}`, "error", 8000);
        }
      },
    );
    cache.set(key, p);
  }
  return p;
}

/** Number of data files being fetched right now. */
export function useLoading(): number {
  return useSyncExternalStore(
    (l) => {
      pendingListeners.add(l);
      return () => pendingListeners.delete(l);
    },
    () => pending,
  );
}

export function invalidate(paths?: string[]): void {
  if (!paths) cache.clear();
  else
    for (const p of paths) {
      cache.delete(p);
      missingReported.delete(p);
      // derived entries ("<dir>|<more>", e.g. trips) go with any file of their dir
      const dir = p.slice(0, p.lastIndexOf("/"));
      for (const k of cache.keys()) if (k.startsWith(`${dir}|`)) cache.delete(k);
    }
  listeners.forEach((l) => l());
}

export interface Resource<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
}

export function useResource<T>(key: string | null | undefined, loader: (key: string) => Promise<T>): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ data: undefined, error: undefined, loading: !!key });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const l = () => setVersion((v) => v + 1);
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, []);

  useEffect(() => {
    if (!key) {
      setState({ data: undefined, error: undefined, loading: false });
      return;
    }
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    load(key, () => loader(key)).then(
      (data) => alive && setState({ data, error: undefined, loading: false }),
      (error: unknown) => alive && setState({ data: undefined, error, loading: false }),
    );
    return () => {
      alive = false;
    };
    // the loader is fixed per hook below; the key decides what is loaded
  }, [key, version]);

  return state;
}

export const useScene = () => useResource<Scene>("scene.json", fetchJson);
export const useStatus = () => useResource<BuildStatus>("status.json", fetchJson);
export const useIssues = (path?: string | null) => useResource<IssueList>(path, fetchJson);
export const useContextFeatures = (path?: string | null) => useResource<ContextFeatures>(path, fetchJson);
async function fetchInfo(path: string): Promise<BuildingInfo> {
  const info = await fetchJson<BuildingInfo>(path);
  registry.infos.set(info.id, info); // for framing spaces and the labels
  return info;
}

/** BuildingInfo through the cache (also outside React, e.g. when choosing a search hit). */
export const loadBuildingInfo = (path: string) => load(path, () => fetchInfo(path));
export const useBuildingInfo = (path?: string | null) => useResource<BuildingInfo>(path, fetchInfo);
export const useReplays = (path?: string | null) => useResource<ReplayCatalog>(path, fetchJson);
async function fetchNetwork(path: string): Promise<BinaryFile<NetworkHeader>> {
  const net = await loadBinary<NetworkHeader>(path);
  registry.network = net; // for the inspector, framing and the route tool's clicks
  return net;
}

export const useNetwork = (path?: string | null) => useResource<BinaryFile<NetworkHeader>>(path, fetchNetwork);
export const useMetro = (path?: string | null) => useResource<Metro>(path, fetchJson);
export const useAcoTrace = (path?: string | null) =>
  useResource<BinaryFile<AcoTraceHeader>>(path, (p) => loadBinary<AcoTraceHeader>(p));
export const useWalkTrace = (path?: string | null) =>
  useResource<BinaryFile<WalkTraceHeader>>(path, (p) => loadBinary<WalkTraceHeader>(p));
export const useStats = (path?: string | null) => useResource<Stats>(path, fetchJson);

/** Campus-wide weekly load for the Demand colour modes; null until `--fake` / `--sim`. */
async function fetchDemand(path: string): Promise<Demand | null> {
  try {
    return await fetchJson<Demand>(path);
  } catch (err) {
    if (err instanceof MissingDataError) return null;
    throw err;
  }
}

export const useDemand = () => useResource<Demand | null>("demand.json", fetchDemand);

export interface Trips {
  paths: Paths;
  day: Day;
  header: DayHeader;
}

async function fetchTrips(key: string): Promise<Trips> {
  // key: "<trips dir>|<weekday>"; the paths are shared by every day of the scenario
  const [dir, weekday] = key.split("|") as [string, string];
  const pathsFile = `${dir}/paths.json`;
  const [p, d] = await Promise.all([
    load(pathsFile, () => loadBinary<PathsHeader>(pathsFile)),
    loadBinary<DayHeader>(`${dir}/day-${weekday}.json`),
  ]);
  const paths: Paths = {
    offsets: p.arrays.path_offsets as Uint32Array,
    xyz: p.arrays.xyz as Float32Array,
    t: p.arrays.t as Float32Array,
    mode: p.arrays.mode as Uint8Array,
  };
  const rows = d.arrays as unknown as Parameters<typeof prepareDay>[1];
  return { paths, day: prepareDay(paths, rows), header: d.header };
}

/** One day of one scenario's students: `dir` is `replay.files.trips[scenario]`. */
export const useTrips = (dir: string | null | undefined, weekday: number) =>
  useResource<Trips>(dir ? `${dir}|${weekday}` : null, fetchTrips);

/** One day of every student's legs, both scenarios (StudentsHeader): `dir` is
 *  `replay.files.students`. Loaded only when a student is looked at. */
export const useStudents = (dir: string | null | undefined, weekday: number) =>
  useResource<BinaryFile<StudentsHeader>>(dir ? `${dir}/day-${weekday}.json` : null, (p) => loadBinary<StudentsHeader>(p));

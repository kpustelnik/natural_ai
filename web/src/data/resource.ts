// Cached loading of data files with React hooks. Each path is fetched once; invalidate()
// (used by live reload in phase 2) drops entries so the next render refetches them.

import { useEffect, useState } from "react";
import type {
  AcoTraceHeader,
  BuildingInfo,
  BuildStatus,
  ContextFeatures,
  IssueList,
  Metro,
  NetworkHeader,
  ReplayCatalog,
  Scene,
} from "../generated/schemas";
import { registry } from "../scene/registry";
import { type BinaryFile, fetchJson, loadBinary } from "./loader";

const cache = new Map<string, Promise<unknown>>();
const listeners = new Set<() => void>();

function load<T>(key: string, loader: () => Promise<T>): Promise<T> {
  let p = cache.get(key) as Promise<T> | undefined;
  if (!p) {
    p = loader();
    cache.set(key, p);
  }
  return p;
}

export function invalidate(paths?: string[]): void {
  if (!paths) cache.clear();
  else for (const p of paths) cache.delete(p);
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

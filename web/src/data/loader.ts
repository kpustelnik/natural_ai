// Loading of files from public/data/ (written by scripts/06_export_web.py).
// Formats: docs/data_contracts.md, section 10.

import type { BufferView } from "../generated/schemas";

export const DATA_URL = `${import.meta.env.BASE_URL}data/`;

export class MissingDataError extends Error {}

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(DATA_URL + path);
  const isJson = res.headers.get("content-type")?.includes("json") ?? false;
  // Vite answers unknown paths with index.html, so a non-JSON reply means "not exported yet"
  if (res.status === 404 || !isJson) throw new MissingDataError(path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

const ARRAY_TYPES = {
  uint8: Uint8Array,
  int16: Int16Array,
  uint16: Uint16Array,
  int32: Int32Array,
  uint32: Uint32Array,
  float32: Float32Array,
} as const;

type ArrayTypes = typeof ARRAY_TYPES;
export type TypedArray = InstanceType<ArrayTypes[keyof ArrayTypes]>;

interface BinaryHeader {
  bin: string;
  buffers: { [name: string]: BufferView };
}

export interface BinaryFile<H extends BinaryHeader> {
  header: H;
  arrays: Record<string, TypedArray>;
}

/** Load `<name>.json` + the `.bin` it names; buffers become zero-copy typed-array views. */
export async function loadBinary<H extends BinaryHeader>(headerPath: string): Promise<BinaryFile<H>> {
  const header = await fetchJson<H>(headerPath);
  const dir = headerPath.includes("/") ? headerPath.slice(0, headerPath.lastIndexOf("/") + 1) : "";
  const res = await fetch(DATA_URL + dir + header.bin);
  // a missing .bin also comes back as index.html (see fetchJson)
  if (res.status === 404 || res.headers.get("content-type")?.includes("html")) throw new MissingDataError(dir + header.bin);
  if (!res.ok) throw new Error(`${header.bin}: HTTP ${res.status}`);
  const bin = await res.arrayBuffer();

  const arrays: Record<string, TypedArray> = {};
  for (const [name, view] of Object.entries(header.buffers)) {
    arrays[name] = new ARRAY_TYPES[view.dtype](bin, view.offset, view.count);
  }
  return { header, arrays };
}

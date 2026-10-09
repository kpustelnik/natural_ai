import { useEffect, useMemo, useRef, useState } from "react";
import { loadBuildingInfo, useContextFeatures } from "../data/resource";
import type { Scene } from "../generated/schemas";
import { search, type SearchItem } from "../lib/search";
import { parsePick } from "../state/url";
import { enterBuilding, focusBox, select, useApp } from "../state/app";
import { pickBox } from "../scene/registry";
import { IconSearch } from "./icons";

export function Search({ scene }: { scene: Scene }) {
  const features = useContextFeatures(scene.context?.features).data;
  const focusSeq = useApp((s) => s.searchFocus);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (focusSeq) {
      input.current?.focus();
      input.current?.select();
    }
  }, [focusSeq]);

  const items = useMemo<SearchItem[]>(() => {
    const out: SearchItem[] = scene.buildings.map((b) => ({
      key: `building:${b.id}`,
      id: b.id,
      label: b.name ?? "",
      group: "AGH buildings",
      terms: [b.id, ...(b.name ? [b.name] : [])],
    }));
    for (const b of scene.buildings) {
      for (const r of b.rooms) {
        out.push({ key: `room:${b.id}/${r}`, id: `${b.id}/${r}`, label: b.name ?? "", group: "Rooms", terms: [`${b.id}/${r}`, `${b.id} ${r}`] });
      }
    }
    for (const s of scene.stops)
      out.push({ key: `stop:${s.id}`, id: s.name, label: "stop used by the simulation", group: "Stops", terms: [s.name, s.id] });
    for (const s of scene.other_stops)
      out.push({ key: `stop:${s.id}`, id: s.name, label: "other stop", group: "Stops", terms: [s.name, s.id] });
    features?.features.forEach((f, fid) =>
      out.push({
        key: `context:${fid}`,
        id: f.name ?? f.osm_id,
        label: f.name ? f.osm_id : f.building,
        group: "Other buildings",
        terms: f.name ? [f.osm_id, f.name] : [f.osm_id],
      }),
    );
    return out;
  }, [scene, features]);

  const results = useMemo(() => search(items, query), [items, query]);

  async function chooseRoom(key: string) {
    const [bid, room] = [key.slice(5, key.indexOf("/")), key.slice(key.indexOf("/") + 1)];
    const b = scene.buildings.find((x) => x.id === bid);
    if (!b) return;
    const info = await loadBuildingInfo(b.info);
    const level = info.levels.find((l) => l.spaces.some((sp) => sp.kind === "room" && sp.id === room));
    if (!level) return;
    enterBuilding(b.id, b.levels.map((l) => l.id), level.id);
    const pick = { kind: "space" as const, building: b.id, id: room, level: level.id };
    select(pick);
    const box = pickBox(pick);
    if (box) focusBox(box.min, box.max);
  }

  function choose(item: SearchItem | undefined) {
    if (!item) return;
    if (item.key.startsWith("room:")) {
      void chooseRoom(item.key);
      setOpen(false);
      input.current?.blur();
      return;
    }
    const pick = parsePick(item.key);
    if (!pick) return;
    select(pick);
    const box = pickBox(pick);
    if (box) focusBox(box.min, box.max);
    setOpen(false);
    input.current?.blur();
  }

  return (
    <div className="search">
      <IconSearch className="search-icon" />
      <input
        ref={input}
        value={query}
        placeholder="Search buildings, rooms, stops, OSM ids   /"
        spellCheck={false}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, results.length - 1));
          else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          else if (e.key === "Enter") choose(results[active]);
          else if (e.key === "Escape") input.current?.blur();
          else return;
          e.preventDefault();
        }}
      />
      {open && query.trim() && (
        <div className="search-results" role="listbox">
          {results.length === 0 && <div className="search-empty">No matches</div>}
          {results.map((r, i) => (
            <button
              key={r.key}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""} aria-pressed={i === active}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(r);
              }}
            >
              <span className="result-id">{r.id}</span>
              <span className="result-label">{r.label}</span>
              <span className="result-group">{r.group}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

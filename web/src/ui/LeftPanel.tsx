import { useEffect, useMemo, useRef, useState } from "react";
import { useBuildingInfo } from "../data/resource";
import type { InfoLevel, Scene, SceneBuilding } from "../generated/schemas";
import { area } from "../lib/format";
import { CATEGORY, SPACE_KIND } from "../scene/palette";
import { pickBox } from "../scene/registry";
import { enterBuilding, focusBox, LAYER_GROUPS, openedBuilding, pickBuilding, select, toggleLayer, useApp } from "../state/app";
import { IconChevronDown, IconChevronRight } from "./icons";

function Layers({ scene }: { scene: Scene }) {
  const layers = useApp((s) => s.layers);
  return (
    <section className="panel-section">
      <h2 className="section-title">Layers</h2>
      {LAYER_GROUPS.map((g) => (
        <div key={g.title} className="layer-group">
          <div className="group-title">{g.title}</div>
          {g.layers.filter((l) => l.id !== "aerial" || scene.aerial).map((l) => (
            <label key={l.id} className="check-row">
              <input type="checkbox" checked={layers[l.id]} onChange={() => toggleLayer(l.id)} />
              <span>{l.label}</span>
            </label>
          ))}
        </div>
      ))}
    </section>
  );
}

const ORDER: SceneBuilding["category"][] = ["academic", "dorm", "connector", "other"];
const GROUP_LABEL: Record<SceneBuilding["category"], string> = {
  academic: "Academic",
  dorm: "Dorms",
  connector: "Connectors",
  other: "Other",
};

function frame(id: string) {
  const box = pickBox({ kind: "building", id });
  if (box) focusBox(box.min, box.max);
}

function LevelRow({ b, level, spaces }: { b: SceneBuilding; level: SceneBuilding["levels"][number]; spaces: InfoLevel["spaces"] }) {
  const levels = b.levels.map((l) => l.id);
  const active = useApp((s) => openedBuilding(s) === b.id && s.level === level.id);
  const selSpace = useApp((s) => (s.selection?.kind === "space" && s.selection.building === b.id && s.selection.level === level.id ? s.selection.id : null));
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (selSpace) setOpen(true);
  }, [selSpace]);
  const kinds = ["room", "corridor", "stairs"] as const;
  const sorted = [...spaces].sort(
    (x, y) => kinds.indexOf(x.kind) - kinds.indexOf(y.kind) || x.id.localeCompare(y.id, "en", { numeric: true }),
  );
  return (
    <>
      <div className={`tree-row leaf level ${active ? "active-level" : ""}`} onClick={() => enterBuilding(b.id, levels, level.id)} title="Show this level (PageUp / PageDown)">
        {spaces.length > 0 ? (
          <button
            className="twisty"
            aria-label={open ? "Collapse" : "Expand"}
            onClick={(e) => {
              e.stopPropagation();
              setOpen((o) => !o);
            }}
          >
            {open ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />}
          </button>
        ) : (
          <span className="twisty" />
        )}
        Level {level.id}
        <span className="tree-name">{spaces.length ? `${spaces.filter((x) => x.kind === "room").length} rooms` : `${level.height.toFixed(1)} m`}</span>
      </div>
      {open &&
        sorted.map((sp) => (
          <div
            key={sp.id}
            className={`tree-row leaf deep ${selSpace === sp.id ? "selected" : ""}`}
            onClick={() => {
              enterBuilding(b.id, levels, level.id);
              select({ kind: "space", building: b.id, id: sp.id, level: level.id });
            }}
            onDoubleClick={() => focusBox(sp.bbox_min, sp.bbox_max)}
          >
            <span className="swatch small" style={{ background: SPACE_KIND[sp.kind].color }} />
            <span className="tree-id">{sp.id}</span>
            <span className="tree-name">{sp.name ?? (sp.kind === "room" ? area(sp.area_m2) : sp.kind)}</span>
          </div>
        ))}
    </>
  );
}

function BuildingRow({ b }: { b: SceneBuilding }) {
  const selected = useApp((s) => s.selection?.kind === "building" && s.selection.id === b.id);
  const inside = useApp((s) => pickBuilding(s.selection) === b.id && s.selection?.kind !== "building");
  const selectedEntrance = useApp((s) => (s.selection?.kind === "entrance" && s.selection.building === b.id ? s.selection.id : null));
  const isOpened = useApp((s) => openedBuilding(s) === b.id);
  const [open, setOpen] = useState(false);
  const row = useRef<HTMLDivElement>(null);
  const info = useBuildingInfo(open ? b.info : null).data;

  useEffect(() => {
    if (selected) row.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);
  useEffect(() => {
    if (inside || (isOpened && b.lod > 1)) setOpen(true);
  }, [inside, isOpened, b.lod]);

  return (
    <div className="tree-item">
      <div
        ref={row}
        className={`tree-row ${selected ? "selected" : ""}`}
        onClick={() => select({ kind: "building", id: b.id })}
        onDoubleClick={() => frame(b.id)}
      >
        <button
          className="twisty"
          aria-label={open ? "Collapse" : "Expand"}
          onClick={(e) => {
            e.stopPropagation();
            setOpen((o) => !o);
          }}
        >
          {open ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />}
        </button>
        <span className="tree-id">{b.id}</span>
        <span className="tree-name">{b.name ?? ""}</span>
        {b.stale && <span className="dot error" title="The YAML fails validation: showing the last good build" />}
        {(b.n_issues ?? 0) > 0 && !b.stale && <span className="dot warn" title={`${b.n_issues} issues`} />}
        <span className={`lod lod-${b.lod}`}>L{b.lod}</span>
      </div>
      {open && (
        <div className="tree-children">
          {[...b.levels].reverse().map((l) => (
            <LevelRow key={l.id} b={b} level={l} spaces={info?.levels.find((x) => x.id === l.id)?.spaces ?? []} />
          ))}
          {b.entrances.map((e) => (
            <div
              key={e.id}
              className={`tree-row leaf ${selectedEntrance === e.id ? "selected" : ""}`}
              onClick={() => select({ kind: "entrance", building: b.id, id: e.id })}
            >
              Entrance {e.id}
              <span className="tree-name">{e.metro_shaft ? "metro shaft" : e.main ? "main" : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Outliner({ scene }: { scene: Scene }) {
  const [filter, setFilter] = useState("");
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const groups = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const match = (b: SceneBuilding) => !f || b.id.toLowerCase().includes(f) || (b.name ?? "").toLowerCase().includes(f);
    return ORDER.map((c) => ({
      category: c,
      buildings: scene.buildings
        .filter((b) => b.category === c && match(b))
        .sort((a, b) => a.id.localeCompare(b.id, "en", { numeric: true })),
    })).filter((g) => g.buildings.length);
  }, [scene, filter]);

  return (
    <section className="panel-section grow">
      <h2 className="section-title">
        Buildings <span className="muted">{scene.buildings.length}</span>
      </h2>
      <input className="filter" placeholder="Filter by id or name" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <div className="tree">
        {groups.map((g) => (
          <div key={g.category}>
            <button className="tree-group" onClick={() => setClosed((c) => ({ ...c, [g.category]: !c[g.category] }))}>
              {closed[g.category] ? <IconChevronRight size={12} /> : <IconChevronDown size={12} />}
              <span className="swatch" style={{ background: CATEGORY[g.category].swatch }} />
              {GROUP_LABEL[g.category]}
              <span className="muted">{g.buildings.length}</span>
            </button>
            {!closed[g.category] && g.buildings.map((b) => <BuildingRow key={b.id} b={b} />)}
          </div>
        ))}
      </div>
    </section>
  );
}

export function LeftPanel({ scene }: { scene: Scene }) {
  return (
    <aside className="sidebar left">
      <Layers scene={scene} />
      <Outliner scene={scene} />
    </aside>
  );
}

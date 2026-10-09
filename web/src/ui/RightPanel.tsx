import { useMemo, useState } from "react";
import { live } from "../data/live";
import { useBuildingInfo, useContextFeatures, useIssues } from "../data/resource";
import type { BuildError, Issue, Scene, SceneBuilding } from "../generated/schemas";
import { area, duration, lonLat, metres, osmUrl } from "../lib/format";
import { type Vec3, webToGeo } from "../lib/frames";
import { pickBox, registry } from "../scene/registry";
import { app, enterBuilding, focusBox, focusPoint, openedBuilding, type Pick, select, setRouteEnd, useApp } from "../state/app";
import { useSlice } from "../state/store";
import { IconAlert, IconCode, IconCopy, IconEnter, IconExternal, IconFrame, IconInfo } from "./icons";
import { RoutePanel } from "./RoutePanel";

/** vscode:// link to a repo file (and line), for the machine that exported the data. */
export function editorUrl(scene: Scene, file: string, line?: number | null): string | null {
  if (!scene.source_root) return null;
  return `vscode://file/${scene.source_root}/${file}${line ? `:${line}:1` : ""}`;
}

function ErrorRow({ scene, e }: { scene: Scene; e: BuildError }) {
  const url = editorUrl(scene, e.file, e.line);
  const where = `${e.file.split("/").pop()}${e.line ? `:${e.line}` : ""}`;
  return (
    <div className="issue error">
      <IconAlert size={14} />
      <div>
        <div>{e.message}</div>
        <div className="muted small">
          {url ? (
            <a href={url} title="Open in VS Code">
              {where}
            </a>
          ) : (
            where
          )}
          {e.loc ? ` · ${e.loc}` : ""}
          {e.element ? ` · ${e.element}` : ""}
        </div>
      </div>
    </div>
  );
}

const EMPTY: BuildError[] = [];

function useBuildErrors(): BuildError[] {
  return useSlice(live, (s) => s.status?.errors ?? EMPTY);
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="kv">
      <span className="k">{k}</span>
      <span className="v">{children}</span>
    </div>
  );
}

function Actions({ pick, extra }: { pick: Pick; extra?: React.ReactNode }) {
  return (
    <div className="actions">
      <button
        className="button"
        onClick={() => {
          const box = pickBox(pick);
          if (box) focusBox(box.min, box.max);
        }}
      >
        <IconFrame size={14} /> Frame <kbd>F</kbd>
      </button>
      {extra}
    </div>
  );
}

function RouteButtons({ keyName }: { keyName: string }) {
  return (
    <>
      <button className="button" onClick={() => setRouteEnd("from", keyName)} title="Start a route here (Route tab)">
        Route from
      </button>
      <button className="button" onClick={() => setRouteEnd("to", keyName)} title="End a route here (Route tab)">
        Route to
      </button>
    </>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        });
      }}
    >
      <IconCopy size={14} /> {done ? "Copied" : label}
    </button>
  );
}

function Position({ scene, p }: { scene: Scene; p: Vec3 }) {
  const [lon, lat] = webToGeo(scene.frame, p);
  return <Row k="position">{lonLat(lon, lat)}</Row>;
}

function IssueList({ issues }: { issues: Issue[] }) {
  if (!issues.length) return null;
  return (
    <div className="issues-inline">
      <div className="group-title">Issues</div>
      {issues.map((i, n) => (
        <div key={n} className={`issue ${i.severity}`}>
          <IconAlert size={14} />
          <div>
            <div>{i.section}</div>
            <div className="muted">{i.message}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function BuildingInspector({ scene, b }: { scene: Scene; b: SceneBuilding }) {
  const info = useBuildingInfo(b.info).data;
  const yamlUrl = editorUrl(scene, b.yaml);
  const levels = b.levels.map((l) => l.id);
  const opened = useApp((s) => openedBuilding(s) === b.id);
  const errors = useBuildErrors().filter((e) => e.building_id === b.id);
  const rooms = info?.levels.reduce((n, l) => n + l.spaces.filter((x) => x.kind === "room").length, 0) ?? 0;
  return (
    <>
      <div className="inspector-head">
        <div className="title">{b.id}</div>
        {b.name && <div className="subtitle">{b.name}</div>}
        <div className="chips">
          <span className="chip">{b.category}</span>
          <span className={`chip lod-${b.lod}`}>LOD{b.lod}</span>
          {b.entrances.some((e) => e.metro_shaft) && <span className="chip accent">metro candidate</span>}
          {b.stale && <span className="chip error">YAML invalid: last good build</span>}
        </div>
      </div>
      {errors.map((e, i) => (
        <ErrorRow key={i} scene={scene} e={e} />
      ))}
      <Actions
        pick={{ kind: "building", id: b.id }}
        extra={
          <>
            {!opened && (
              <button className="button" onClick={() => enterBuilding(b.id, levels)} title="Open in the Building workspace">
                <IconEnter size={14} /> Enter
              </button>
            )}
            {yamlUrl && (
              <a className="button" href={yamlUrl} title={b.yaml}>
                <IconCode size={14} /> Open YAML
              </a>
            )}
            <CopyButton text={b.id} label="Copy id" />
            <RouteButtons keyName={b.id} />
          </>
        }
      />
      <div className="kv-list">
        <Row k="levels">
          {levels.length} ({Math.min(...levels)} to {Math.max(...levels)})
        </Row>
        <Row k="height">{metres(b.height_m)}</Row>
        {info && <Row k="footprint">{area(info.area_m2)}</Row>}
        {b.lod > 1 && info && <Row k="rooms">{rooms}</Row>}
        <Row k="frame">
          bearing {b.frame.bearing_deg.toFixed(1)}°
        </Row>
        <Position scene={scene} p={b.frame.anchor} />
        <Row k="source">{b.yaml}</Row>
        {b.osm_id && (
          <Row k="OSM">
            <a href={osmUrl(b.osm_id)} target="_blank" rel="noreferrer">
              {b.osm_id} <IconExternal size={12} />
            </a>
          </Row>
        )}
        {info?.osm_hausdorff_m != null && <Row k="vs OSM outline">{metres(info.osm_hausdorff_m, 2)}</Row>}
      </div>
      <div className="group-title">Entrances</div>
      {b.entrances.length === 0 && <p className="muted small">None in the YAML.</p>}
      {b.entrances.map((e) => (
        <button key={e.id} className="list-row" onClick={() => select({ kind: "entrance", building: b.id, id: e.id })}>
          <span className="tree-id">{e.id}</span>
          <span className="muted">{e.metro_shaft ? "main · metro shaft" : e.main ? "main" : ""}</span>
        </button>
      ))}
      {info && <IssueList issues={info.issues} />}
    </>
  );
}

function SpaceInspector({ scene, sel }: { scene: Scene; sel: Extract<Pick, { kind: "space" }> }) {
  const b = scene.buildings.find((x) => x.id === sel.building);
  const info = useBuildingInfo(b?.info).data;
  const errors = useBuildErrors().filter((e) => e.building_id === sel.building && e.element === sel.id);
  if (!b) return <p className="muted">Unknown building.</p>;
  if (!info) return <p className="muted">Loading…</p>;
  const level = info.levels.find((l) => l.id === sel.level);
  const sp = level?.spaces.find((x) => x.id === sel.id);
  if (!sp || !level) return <p className="muted">{sel.id} is not on level {sel.level} of {b.id}.</p>;
  const key = sp.kind === "room" ? `${b.id}/${sp.id}` : sp.id;
  return (
    <>
      <div className="inspector-head">
        <div className="title">{key}</div>
        {sp.name && <div className="subtitle">{sp.name}</div>}
        <div className="chips">
          <span className="chip">{sp.kind}</span>
          <span className="chip">level {level.id}</span>
        </div>
      </div>
      {errors.map((e, i) => (
        <ErrorRow key={i} scene={scene} e={e} />
      ))}
      <Actions
        pick={sel}
        extra={
          <>
            <CopyButton text={key} label="Copy key" />
            {sp.kind === "room" && <RouteButtons keyName={key} />}
            <button className="button" onClick={() => select({ kind: "building", id: b.id })}>
              Building {b.id}
            </button>
          </>
        }
      />
      <div className="kv-list">
        <Row k="area">{area(sp.area_m2)}</Row>
        <Row k="size">
          {sp.size[0].toFixed(1)} × {sp.size[1].toFixed(1)} m
        </Row>
        {sp.kind === "room" && <Row k="capacity">{sp.capacity ?? <span className="muted">not given</span>}</Row>}
        <Row k="doors">{sp.doors.length}</Row>
        <Row k="floor">
          {metres(level.elevation)} <span className="muted">above ground, {metres(level.height)} high</span>
        </Row>
        <Row k="local centre">
          <span className="mono">
            [{sp.centre[0]}, {sp.centre[1]}]
          </span>
        </Row>
      </div>
      <p className="muted small">Students per hour and the USOS groups using it come with the simulation.</p>
    </>
  );
}

function Inspector({ scene }: { scene: Scene }) {
  const sel = useApp((s) => s.selection);
  const features = useContextFeatures(scene.context?.features).data;

  if (!sel) {
    return (
      <div className="empty">
        <p>Nothing selected.</p>
        <p className="muted">Click a building, an entrance, a stop or a path. Double-click frames it.</p>
      </div>
    );
  }
  switch (sel.kind) {
    case "building": {
      const b = scene.buildings.find((x) => x.id === sel.id);
      return b ? <BuildingInspector scene={scene} b={b} /> : <p className="muted">Unknown building {sel.id}.</p>;
    }
    case "context": {
      const f = features?.features[sel.fid];
      if (!f) return <p className="muted">Loading…</p>;
      return (
        <>
          <div className="inspector-head">
            <div className="title">{f.name ?? "Unnamed building"}</div>
            <div className="chips">
              <span className="chip">not AGH</span>
              <span className="chip">{f.building}</span>
            </div>
          </div>
          <Actions pick={sel} extra={<CopyButton text={f.osm_id} label="Copy OSM id" />} />
          <div className="kv-list">
            <Row k="OSM">
              <a href={osmUrl(f.osm_id)} target="_blank" rel="noreferrer">
                {f.osm_id} <IconExternal size={12} />
              </a>
            </Row>
            <Row k="height">
              {metres(f.height_m)} <span className="muted">({f.height_source})</span>
            </Row>
          </div>
          <p className="muted small">
            If this is an AGH building, map it in <code>data/campus/osm_building_map.csv</code>.
          </p>
        </>
      );
    }
    case "stop": {
      const used = scene.stops.find((s) => s.id === sel.id);
      const s = used ?? scene.other_stops.find((x) => x.id === sel.id);
      if (!s) return <p className="muted">Unknown stop.</p>;
      return (
        <>
          <div className="inspector-head">
            <div className="title">{s.name}</div>
            <div className="chips">
              <span className={`chip ${used ? "accent" : ""}`}>{used ? "used by the simulation" : "not in campus.yaml"}</span>
            </div>
          </div>
          <Actions
            pick={sel}
            extra={
              <>
                <CopyButton text={s.id} label="Copy id" />
                {used && <RouteButtons keyName={s.id} />}
              </>
            }
          />
          <div className="kv-list">
            <Row k="id">{s.id}</Row>
            <Position scene={scene} p={s.position} />
          </div>
        </>
      );
    }
    case "space":
      return <SpaceInspector scene={scene} sel={sel} />;
    case "entrance": {
      const b = scene.buildings.find((x) => x.id === sel.building);
      const e = b?.entrances.find((x) => x.id === sel.id);
      if (!b || !e) return <p className="muted">Unknown entrance.</p>;
      return (
        <>
          <div className="inspector-head">
            <div className="title">
              {b.id} · {e.id}
            </div>
            <div className="chips">
              {e.main && <span className="chip">main entrance</span>}
              {e.metro_shaft && <span className="chip accent">metro shaft</span>}
            </div>
          </div>
          <Actions
            pick={sel}
            extra={
              <button className="button" onClick={() => select({ kind: "building", id: b.id })}>
                Building {b.id}
              </button>
            }
          />
          <div className="kv-list">
            <Position scene={scene} p={e.position} />
          </div>
        </>
      );
    }
    case "edge": {
      const net = registry.network;
      if (!net) return <p className="muted">Loading…</p>;
      const h = net.header;
      const kind = h.edge_kind_names[(net.arrays.edge_kind as Uint8Array)[sel.index]!];
      const length = (net.arrays.length_m as Float32Array)[sel.index]!;
      const tuv = (net.arrays.time_uv_s as Float32Array)[sel.index]!;
      const tvu = (net.arrays.time_vu_s as Float32Array)[sel.index]!;
      const nodes = net.arrays.edge_nodes as Uint32Array;
      const from = h.node_keys[nodes[sel.index * 2]!]!;
      const to = h.node_keys[nodes[sel.index * 2 + 1]!]!;
      const source = h.edge_sources[sel.index] ?? null;
      const ways = source?.startsWith("way/") ? source.split("|") : [];
      const building = source && !ways.length && scene.buildings.some((b) => b.id === source) ? source : null;
      return (
        <>
          <div className="inspector-head">
            <div className="title">{kind === "footway" || kind === "road" || kind === "steps" ? "Path segment" : "Graph edge"}</div>
            <div className="chips">
              <span className="chip">{kind}</span>
            </div>
          </div>
          <Actions
            pick={sel}
            extra={
              <>
                <button className="button" onClick={() => setRouteEnd("from", from)} title="Start a route here">
                  Route from
                </button>
                <button className="button" onClick={() => setRouteEnd("to", to)} title="End a route here">
                  Route to
                </button>
              </>
            }
          />
          <div className="kv-list">
            <Row k="length">{metres(length)}</Row>
            <Row k="time">
              {tuv === tvu ? (
                duration(tuv)
              ) : (
                <>
                  {duration(tuv)} → <span className="muted">· back {duration(tvu)}</span>
                </>
              )}
            </Row>
            <Row k="from">{from}</Row>
            <Row k="to">{to}</Row>
            {ways.length > 0 && (
              <Row k="OSM ways">
                <span className="links">
                  {ways.map((w) => (
                    <a key={w} href={osmUrl(w)} target="_blank" rel="noreferrer">
                      {w}
                    </a>
                  ))}
                </span>
              </Row>
            )}
            {building && (
              <Row k="building">
                <button className="link-button" onClick={() => select({ kind: "building", id: building })}>
                  {building}
                </button>
              </Row>
            )}
            {source && !ways.length && !building && <Row k="source">{source}</Row>}
          </div>
        </>
      );
    }
    case "barrier": {
      const b = registry.network?.header.barriers[sel.index];
      if (!b) return <p className="muted">Loading…</p>;
      return (
        <>
          <div className="inspector-head">
            <div className="title">{b.barrier.replace(/_/g, " ")}</div>
            <div className="chips">
              <span className="chip">barrier</span>
              {b.access && <span className="chip">access: {b.access}</span>}
            </div>
          </div>
          <Actions pick={sel} extra={<CopyButton text={b.osm_id} label="Copy OSM id" />} />
          <div className="kv-list">
            <Row k="OSM">
              <a href={osmUrl(b.osm_id)} target="_blank" rel="noreferrer">
                {b.osm_id} <IconExternal size={12} />
              </a>
            </Row>
            <Position scene={scene} p={b.position} />
          </div>
          <p className="muted small">The graph ignores barriers in v1. A gate students cannot pass goes to removed_ways in campus.yaml.</p>
        </>
      );
    }
  }
}

function IssuesPanel({ scene }: { scene: Scene }) {
  const issues = useIssues(scene.issues).data?.issues ?? [];
  const [severity, setSeverity] = useState<"all" | Issue["severity"]>("all");
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const groups = useMemo(() => {
    const m = new Map<string, Issue[]>();
    for (const i of issues) if (severity === "all" || i.severity === severity) m.set(i.section, [...(m.get(i.section) ?? []), i]);
    return [...m.entries()].sort((a, b) => sevRank(b[1]) - sevRank(a[1]) || a[0].localeCompare(b[0]));
  }, [issues, severity]);

  function open(i: Issue) {
    if (i.building_id && scene.buildings.some((b) => b.id === i.building_id)) {
      select({ kind: "building", id: i.building_id });
      const box = pickBox({ kind: "building", id: i.building_id });
      if (box) focusBox(box.min, box.max);
    } else if (i.position) {
      focusPoint(i.position);
    }
  }

  const errors = useBuildErrors();
  return (
    <div className="issues-panel">
      {errors.length > 0 && (
        <div className="build-errors">
          <div className="group-title error-text">Build errors ({errors.length})</div>
          {errors.map((e, i) => (
            <div
              key={i}
              className="clickable"
              onClick={() => {
                if (!e.building_id || !scene.buildings.some((b) => b.id === e.building_id)) return;
                select({ kind: "building", id: e.building_id });
                const box = pickBox({ kind: "building", id: e.building_id });
                if (box) focusBox(box.min, box.max);
              }}
            >
              <ErrorRow scene={scene} e={e} />
            </div>
          ))}
        </div>
      )}
      <div className="segmented small">
        {(["all", "error", "warning", "info"] as const).map((s) => (
          <button key={s} className={severity === s ? "active" : ""} onClick={() => setSeverity(s)}>
            {s}
          </button>
        ))}
      </div>
      {groups.length === 0 && <p className="muted small">No issues.</p>}
      {groups.map(([section, items]) => (
        <div key={section} className="issue-group">
          <button className="tree-group" onClick={() => setClosed((c) => ({ ...c, [section]: !c[section] }))}>
            <span className={`dot ${items[0]!.severity}`} />
            <span className="issue-section">{section}</span>
            <span className="muted">{items.length}</span>
          </button>
          {!closed[section] &&
            items.map((i, n) => (
              <button
                key={n}
                className="list-row"
                disabled={!i.building_id && !i.position}
                onClick={() => open(i)}
                title={i.message}
              >
                <span className="issue-message">{i.message}</span>
              </button>
            ))}
        </div>
      ))}
    </div>
  );
}

function sevRank(items: Issue[]): number {
  return items.some((i) => i.severity === "error") ? 2 : items.some((i) => i.severity === "warning") ? 1 : 0;
}

export function RightPanel({ scene }: { scene: Scene }) {
  const tab = useApp((s) => s.rightTab);
  const count = useIssues(scene.issues).data?.issues.length ?? 0;
  return (
    <aside className="sidebar right">
      <div className="panel-tabs">
        <button className={tab === "inspector" ? "active" : ""} onClick={() => app.set({ rightTab: "inspector" })}>
          <IconInfo size={14} /> Inspector
        </button>
        <button className={tab === "issues" ? "active" : ""} onClick={() => app.set({ rightTab: "issues" })}>
          <IconAlert size={14} /> Issues <span className="count">{count}</span>
        </button>
        <button className={tab === "route" ? "active" : ""} onClick={() => app.set({ rightTab: "route" })} title="Route tool (R)">
          Route
        </button>
      </div>
      <div className="panel-body">
        {tab === "inspector" ? <Inspector scene={scene} /> : tab === "issues" ? <IssuesPanel scene={scene} /> : <RoutePanel scene={scene} />}
      </div>
    </aside>
  );
}

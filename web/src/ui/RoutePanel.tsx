// Route tool (Network workspace): the fastest walk between two endpoints (room, building,
// stop or any graph node), its time split into outdoor / indoor / stairs, the legs, and the
// field measurements (data/validation/field_measurements.csv) next to the graph's times.

import { useEffect, useMemo, useState } from "react";
import { computeRoute, type Network, nodeName, nodePosition, pathPolyline, resolveKey, useRoute } from "../data/network";
import { useNetwork } from "../data/resource";
import type { Scene } from "../generated/schemas";
import { duration, metres } from "../lib/format";
import type { Leg } from "../lib/graph";
import { ROUTE_PARTS } from "../scene/palette";
import { app, focusBox, type Route, setRouteEnd, useApp } from "../state/app";
import { Command } from "./Command";
import { IconClose, IconFrame } from "./icons";

function frameRoute(net: Network, route: Route): void {
  if (!route.from || !route.to) return;
  const r = computeRoute(net, route.from, route.to);
  if (!r.ok) return;
  const pts = pathPolyline(net, r.path);
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const p of pts) for (let i = 0; i < 3; i++) (min[i] = Math.min(min[i]!, p[i]!)), (max[i] = Math.max(max[i]!, p[i]!));
  focusBox([min[0]! - 20, min[1]!, min[2]! - 20], [max[0]! + 20, max[1]! + 10, max[2]! + 20]);
}

function EndInput({ net, slot, value, next }: { net: Network; slot: "from" | "to"; value: string | null; next: boolean }) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  const valid = !text || resolveKey(net, text.trim()) !== null;
  const commit = () => {
    const key = text.trim();
    if (!key) setRouteEnd(slot, null);
    else if (resolveKey(net, key) !== null && key !== value) setRouteEnd(slot, key);
  };
  return (
    <div className={`route-end ${next ? "next" : ""}`}>
      <span className={`end-badge ${slot}`}>{slot === "from" ? "A" : "B"}</span>
      <input
        list="route-endpoints"
        value={text}
        placeholder={slot === "from" ? "From: D-17/1.38, A-0, stop:…" : "To"}
        className={valid ? "" : "invalid"}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        title={valid ? "Endpoint key or graph node key" : "Not in the walk graph"}
      />
      <button className="icon-button" title="Clear" aria-label="Clear" onClick={() => setRouteEnd(slot, null)} disabled={!value}>
        <IconClose size={12} />
      </button>
    </div>
  );
}

function legLabel(net: Network, leg: Leg): string {
  if (leg.part === "stairs") {
    const what = leg.kind === "shaft" ? "Metro shaft" : "Stairs";
    return `${what} ${leg.rise >= 0 ? "up" : "down"} ${Math.abs(leg.rise).toFixed(1)} m${leg.building ? ` · ${leg.building}` : ""}`;
  }
  if (leg.part === "indoor") return leg.kind === "passage" ? `Passage ${leg.building ?? ""}` : `Inside ${leg.building ?? ""}`;
  return `Outdoor to ${nodeName(net, leg.to)}`;
}

function Measurements({ net }: { net: Network }) {
  const rows = net.header.measurements;
  const results = useMemo(() => rows.map((m) => computeRoute(net, m.from_key, m.to_key)), [net, rows]);
  if (!rows.length) {
    return (
      <p className="muted small">
        No field measurements yet. Walk a route with a stopwatch and add a row to <code>data/validation/field_measurements.csv</code>{" "}
        (<code>from_key</code>, <code>to_key</code> are endpoint keys); the next export lists it here with the graph's time.
      </p>
    );
  }
  return (
    <table className="measure-table">
      <thead>
        <tr>
          <th>route</th>
          <th className="num">measured</th>
          <th className="num">graph</th>
          <th className="num">Δ</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((m, i) => {
          const r = results[i]!;
          const diff = r.ok ? (r.summary.time - m.measured_s) / m.measured_s : null;
          return (
            <tr
              key={`${m.route_id}-${m.date}-${m.who}`}
              className="clickable"
              title={`${m.from_key} → ${m.to_key}${m.notes ? ` · ${m.notes}` : ""} (${m.date}, ${m.who})`}
              onClick={() => {
                const route = { from: m.from_key, to: m.to_key, slot: "from" as const };
                app.set({ route });
                frameRoute(net, route);
              }}
            >
              <td>{m.route_id}</td>
              <td className="num">{duration(m.measured_s)}</td>
              <td className="num">{r.ok ? duration(r.summary.time) : "–"}</td>
              <td className="num">{diff === null ? "no path" : `${diff >= 0 ? "+" : "−"}${Math.abs(100 * diff).toFixed(0)} %`}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function RoutePanel({ scene }: { scene: Scene }) {
  const net = useNetwork(scene.network).data;
  const route = useApp((s) => s.route);
  const picking = useApp((s) => s.tool === "route");
  const result = useRoute(net, route);
  const endpoints = useMemo(
    () => (net ? Object.keys(net.header.endpoints).sort((a, b) => a.localeCompare(b, "en", { numeric: true })) : []),
    [net],
  );

  if (!scene.network) {
    return (
      <div className="muted">
        <p>No walk graph exported (network.json). It comes with the campus export:</p>
        <Command lines={["uv run scripts/06_export_web.py --campus"]} />
      </div>
    );
  }
  if (!net) return <p className="muted">Loading the walk graph…</p>;
  const s = result?.ok ? result.summary : null;

  return (
    <div className="route-panel">
      <datalist id="route-endpoints">
        {endpoints.map((k) => (
          <option key={k} value={k} />
        ))}
      </datalist>
      <EndInput net={net} slot="from" value={route.from} next={picking && route.slot === "from"} />
      <EndInput net={net} slot="to" value={route.to} next={picking && route.slot === "to"} />
      <div className="actions">
        <button
          className={`button ${picking ? "active" : ""}`}
          onClick={() => app.set({ tool: picking ? "select" : "route" })}
          title="Click a room, building, stop or any point on the paths (R)"
        >
          {picking ? "Picking in 3D…" : "Pick in 3D"} <kbd>R</kbd>
        </button>
        <button
          className="button"
          disabled={!route.from && !route.to}
          onClick={() => app.set({ route: { from: route.to, to: route.from, slot: route.slot } })}
          title="Swap the ends"
        >
          ⇅ Swap
        </button>
        <button className="button" disabled={!s} onClick={() => frameRoute(net, route)}>
          <IconFrame size={14} /> Frame
        </button>
      </div>

      {result && !result.ok && <p className="error-text small">{result.error}</p>}
      {!route.from && !route.to && (
        <p className="muted small">
          Choose two ends: type an endpoint key (a room like <code>D-17/1.38</code>, a building, a stop) or pick them in the view.
        </p>
      )}
      {s && result?.ok && (
        <>
          <div className="route-total">
            <span className="big mono">{duration(s.time)}</span>
            <span className="muted">{metres(s.length, 0)}</span>
          </div>
          <div className="route-bar" aria-hidden>
            {(Object.keys(ROUTE_PARTS) as (keyof typeof ROUTE_PARTS)[])
              .filter((p) => s.parts[p].time > 0)
              .map((p) => (
                <span key={p} style={{ flex: s.parts[p].time, background: ROUTE_PARTS[p].color }} />
              ))}
          </div>
          <div className="kv-list">
            {(Object.keys(ROUTE_PARTS) as (keyof typeof ROUTE_PARTS)[]).map((p) => (
              <div className="kv" key={p}>
                <span className="k">
                  <span className="swatch small" style={{ background: ROUTE_PARTS[p].color }} /> {ROUTE_PARTS[p].label}
                </span>
                <span className="v mono">
                  {duration(s.parts[p].time)} <span className="muted">· {metres(s.parts[p].length, 0)}</span>
                </span>
              </div>
            ))}
          </div>
          <div className="group-title">Legs</div>
          <div className="route-legs">
            {s.legs.map((leg, i) => (
              <div
                key={i}
                className="route-leg"
                title={`${nodeName(net, leg.from)} → ${nodeName(net, leg.to)}`}
                onDoubleClick={() => {
                  const a = nodePosition(net, leg.from);
                  const b = nodePosition(net, leg.to);
                  focusBox(
                    [Math.min(a[0], b[0]) - 15, Math.min(a[1], b[1]), Math.min(a[2], b[2]) - 15],
                    [Math.max(a[0], b[0]) + 15, Math.max(a[1], b[1]) + 10, Math.max(a[2], b[2]) + 15],
                  );
                }}
              >
                <span className="dot-part" style={{ background: ROUTE_PARTS[leg.part].color }} />
                <span className="tree-name">{legLabel(net, leg)}</span>
                <span className="muted mono">{metres(leg.length, 0)}</span>
                <span className="mono">{duration(leg.time)}</span>
              </div>
            ))}
          </div>
          <p className="muted small">
            {nodeName(net, result.from)} → {nodeName(net, result.to)}. Times follow <code>time_model</code> in config.yaml.
            Double-click a leg to frame it.
          </p>
        </>
      )}
      <div className="group-title">Field measurements</div>
      <Measurements net={net} />
    </div>
  );
}

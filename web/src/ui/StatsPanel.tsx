// Stats of a simulation replay (stats.json, contract 10.6): the two scenarios side by side,
// travel time per hour of the day, station use and the largest savings between endpoints.
// Rows are clickable: an hour moves the clock there, a station frames it, an OD pair draws
// its walking route.

import { useMemo, useState } from "react";
import { useStats } from "../data/resource";
import type { Replay, ScenarioStats, Stats } from "../generated/schemas";
import { duration, studentHours, WEEKDAYS } from "../lib/format";
import { SCENARIOS } from "../scene/palette";
import { pickBox } from "../scene/registry";
import { app, focusBox, select, setPlayback, useApp } from "../state/app";
import { Command } from "./Command";

const pct = (v: number) => `${(100 * v).toFixed(1)} %`;
const int = (v: number) => Math.round(v).toLocaleString("en-US");

const ROWS: { label: string; value: (s: ScenarioStats) => string; title?: string }[] = [
  { label: "legs", value: (s) => int(s.n_legs) },
  { label: "travel", value: (s) => studentHours(s.total_travel_s), title: "Door to door, waiting included, student-hours a week" },
  { label: "mean leg", value: (s) => duration(s.mean_leg_s) },
  { label: "late", value: (s) => pct(s.late_share), title: "Legs arriving after the class starts" },
  { label: "longer than the break", value: (s) => pct(s.longer_than_break_share), title: "Of the legs between two classes" },
  { label: "by metro", value: (s) => pct(s.metro_share) },
  { label: "by bus / tram", value: (s) => pct(s.transit_share), title: "Rides between campus stops (GTFS timetable)" },
];

function Totals({ stats }: { stats: Stats }) {
  const nm = stats.scenarios.no_metro;
  const m = stats.scenarios.metro;
  return (
    <>
      {nm && m && (
        <div className="stat-hero">
          <span className="big mono">−{studentHours(stats.saving_s)}</span>
          <span className="muted">
            a week with the metro ({pct(stats.saving_s / Math.max(1, nm.total_travel_s))} of all travel time)
          </span>
        </div>
      )}
      <table className="measure-table stats-table">
        <thead>
          <tr>
            <th />
            {nm && <th className="num">{SCENARIOS.no_metro.label}</th>}
            {m && <th className="num">{SCENARIOS.metro.label}</th>}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.label} title={r.title}>
              <td>{r.label}</td>
              {nm && <td className="num mono">{r.value(nm)}</td>}
              {m && <td className="num mono">{r.value(m)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

const W = 300;
const H = 110;
const PAD = { left: 2, right: 2, top: 6, bottom: 2 };
const FIRST_HOUR = 6;
const LAST_HOUR = 21;

/** Travel time per hour of the selected weekday: paired bars, one per scenario. */
function HourChart({ stats }: { stats: Stats }) {
  const weekday = useApp((s) => s.playback.weekday);
  const t = useApp((s) => s.playback.t);
  const [hover, setHover] = useState<number | null>(null);
  const series = (["no_metro", "metro"] as const).filter((sc) => stats.scenarios[sc]);
  const hours = useMemo(() => {
    const out = new Map<number, { n: number; no_metro: number; metro: number }>();
    for (const h of stats.per_hour) {
      if (h.weekday === weekday) out.set(h.hour, { n: h.n_legs, no_metro: h.no_metro_s, metro: h.metro_s });
    }
    return out;
  }, [stats, weekday]);
  const n = LAST_HOUR - FIRST_HOUR + 1;
  const max = Math.max(1, ...[...hours.values()].flatMap((v) => series.map((sc) => v[sc])));
  const slot = (W - PAD.left - PAD.right) / n;
  const bar = Math.max(2, (slot - 4) / series.length - 1);
  const y = (v: number) => PAD.top + (1 - v / max) * (H - PAD.top - PAD.bottom);
  const at = hover ?? Math.floor(t / 3600);
  const cur = hours.get(at);
  const hourAt = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.floor((((e.clientX - r.left) / r.width) * W - PAD.left) / slot);
    return Math.max(FIRST_HOUR, Math.min(LAST_HOUR, FIRST_HOUR + i));
  };
  // a rounded data end anchored to the baseline: a rectangle with the top corners rounded
  const barPath = (x: number, v: number) => {
    const top = y(v);
    const base = H - PAD.bottom;
    const r = Math.min(2, bar / 2, base - top);
    return `M${x},${base}V${top + r}Q${x},${top} ${x + r},${top}H${x + bar - r}Q${x + bar},${top} ${x + bar},${top + r}V${base}Z`;
  };

  return (
    <div className="chart">
      <div className="chart-legend">
        {series.map((sc) => (
          <span key={sc} className="legend-item">
            <span className="swatch small" style={{ background: SCENARIOS[sc].color }} />
            {SCENARIOS[sc].label} <span className="mono">{cur ? studentHours(cur[sc]) : "–"}</span>
          </span>
        ))}
        <span className="legend-item muted">
          {String(at).padStart(2, "0")}:00 · {cur ? `${int(cur.n)} legs` : "no legs"}
        </span>
      </div>
      <svg
        className="chart-plot hour-plot"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Travel time per hour on ${WEEKDAYS[weekday - 1]}, student-hours, by scenario`}
        onMouseMove={(e) => setHover(hourAt(e))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => setPlayback({ t: hourAt(e) * 3600 })}
      >
        {Array.from({ length: n }, (_, i) => {
          const h = FIRST_HOUR + i;
          const v = hours.get(h);
          const x0 = PAD.left + i * slot + 2;
          return (
            <g key={h} opacity={hover === null || hover === h ? 1 : 0.55}>
              {h === Math.floor(t / 3600) && <rect x={x0 - 2} y={0} width={slot} height={H} fill="#eef0f2" />}
              {v &&
                series.map((sc, k) =>
                  v[sc] > 0 ? <path key={sc} d={barPath(x0 + k * (bar + 2), v[sc])} fill={SCENARIOS[sc].color} /> : null,
                )}
            </g>
          );
        })}
        <line x1={0} x2={W} y1={H - PAD.bottom} y2={H - PAD.bottom} stroke="#c3c8ce" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="chart-caption muted">
        <span>{FIRST_HOUR}:00</span>
        <span>{hover !== null ? "click to go to this hour" : `travel per hour, ${WEEKDAYS[weekday - 1]}`}</span>
        <span>{LAST_HOUR + 1}:00</span>
      </div>
    </div>
  );
}

function Stations({ stats }: { stats: Stats }) {
  if (!stats.stations.length) return null;
  const max = Math.max(1, ...stats.stations.map((s) => s.boardings + s.alightings));
  return (
    <>
      <div className="group-title">Stations, a week</div>
      <table className="measure-table stats-table">
        <thead>
          <tr>
            <th>station</th>
            <th className="num">boardings</th>
            <th className="num">alightings</th>
            <th aria-hidden />
          </tr>
        </thead>
        <tbody>
          {stats.stations.map((s) => (
            <tr
              key={s.building_id}
              className="clickable"
              title="Select and frame"
              onClick={() => {
                const pick = { kind: "building" as const, id: s.building_id };
                select(pick);
                const box = pickBox(pick);
                if (box) focusBox(box.min, box.max);
              }}
            >
              <td>
                <strong>{s.building_id}</strong>
              </td>
              <td className="num mono">{int(s.boardings)}</td>
              <td className="num mono">{int(s.alightings)}</td>
              <td className="bar-cell">
                <span className="mini-bar" style={{ width: `${(100 * (s.boardings + s.alightings)) / max}%` }} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TopOd({ stats }: { stats: Stats }) {
  const [all, setAll] = useState(false);
  if (!stats.top_od.length) return null;
  const rows = all ? stats.top_od : stats.top_od.slice(0, 10);
  return (
    <>
      <div className="group-title">Largest savings, a week</div>
      <table className="measure-table stats-table">
        <thead>
          <tr>
            <th>from → to</th>
            <th className="num">legs</th>
            <th className="num">saved</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={`${r.from_key}>${r.to_key}`}
              className="clickable"
              title={`${duration(r.saving_s / r.n_legs)} saved per leg. Click: the walking route in 3D`}
              onClick={() => app.set({ route: { from: r.from_key, to: r.to_key, slot: "from" }, rightTab: "route" })}
            >
              <td className="od-cell">
                {r.from_key} → {r.to_key}
              </td>
              <td className="num mono">{int(r.n_legs)}</td>
              <td className="num mono">{studentHours(r.saving_s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {stats.top_od.length > 10 && (
        <button className="link-button" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${stats.top_od.length}`}
        </button>
      )}
    </>
  );
}

export function StatsPanel({ replay }: { replay: Replay | null }) {
  const stats = useStats(replay?.files.stats);
  if (!replay) {
    return (
      <p className="muted">
        Open a simulation from <strong>Replays</strong> to see its stats.
      </p>
    );
  }
  if (!replay.files.stats) {
    return (
      <div className="muted">
        <p>This replay has no students or stats yet. Simulate the week, then export it:</p>
        <Command lines={["uv run scripts/05_simulate.py", "uv run scripts/06_export_web.py --sim"]} />
      </div>
    );
  }
  if (stats.error) return <p className="error-text small">Could not load {replay.files.stats}.</p>;
  if (!stats.data) return <p className="muted">Loading stats…</p>;
  return (
    <div className="stats-panel">
      <Totals stats={stats.data} />
      <div className="group-title">Per hour</div>
      <HourChart stats={stats.data} />
      <Stations stats={stats.data} />
      <TopOd stats={stats.data} />
    </div>
  );
}

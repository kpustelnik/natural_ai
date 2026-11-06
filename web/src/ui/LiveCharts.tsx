// Live charts of a simulation replay (the dock, under the clock): the day so far, from the
// trips already loaded for the 3D view (lib/trips.ts), so nothing new is exported.
//
// - mean leg time per 15 minutes, without and with the metro (the gap is what the metro saves);
// - student-hours saved so far today (legs counted by the hour they leave);
// - what everyone is doing (walking, waiting, metro, bus / tram), stacked.
//
// Each chart draws the whole day faint and the part up to the clock solid; hovering reads a
// time off, clicking moves the clock there.

import { useMemo, useState } from "react";
import { useTrips } from "../data/resource";
import type { Replay } from "../generated/schemas";
import { clock, duration } from "../lib/format";
import { arrivedBy, binLegs, dayLegs, type Legs, N_STATES, stateCurve } from "../lib/trips";
import { SCENARIOS, STUDENTS } from "../scene/palette";
import { setPlayback, useApp } from "../state/app";

const T0 = 6 * 3600;
const T1 = 22 * 3600;
const STEP = 15 * 60;
const SAMPLES = 129; // every 7.5 minutes
const W = 300;
const H = 96;
const PAD = { l: 30, r: 4, t: 6, b: 14 };

const x = (t: number) => PAD.l + ((t - T0) / (T1 - T0)) * (W - PAD.l - PAD.r);
const tOf = (px: number) => T0 + ((px - PAD.l) / (W - PAD.l - PAD.r)) * (T1 - T0);
const y = (v: number, max: number) => H - PAD.b - (max > 0 ? v / max : 0) * (H - PAD.t - PAD.b);

function line(ts: ArrayLike<number>, vs: ArrayLike<number>, max: number, upTo = Infinity): string {
  let d = "";
  for (let i = 0; i < vs.length; i++) {
    if (ts[i]! > upTo) break;
    if (Number.isNaN(vs[i]!)) continue;
    d += `${d ? "L" : "M"}${x(ts[i]!).toFixed(1)},${y(vs[i]!, max).toFixed(1)}`;
  }
  return d;
}

/** Saved travel per bin of the hour a leg leaves without the metro (seconds). */
function savedPerBin(nm: Legs, m: Legs): Float64Array {
  const k = Math.ceil((T1 - T0) / STEP);
  const out = new Float64Array(k);
  const withMetro = new Map<number, number>();
  for (let i = 0; i < m.leg.length; i++) withMetro.set(m.leg[i]!, m.arrive[i]! - m.depart[i]!);
  for (let i = 0; i < nm.leg.length; i++) {
    const j = Math.floor((nm.depart[i]! - T0) / STEP);
    const tm = withMetro.get(nm.leg[i]!);
    if (j < 0 || j >= k || tm === undefined) continue;
    out[j]! += nm.arrive[i]! - nm.depart[i]! - tm;
  }
  return out;
}

function Axis({ max, unit }: { max: number; unit: (v: number) => string }) {
  return (
    <g className="live-axis">
      <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} />
      <text x={PAD.l - 3} y={PAD.t + 6} textAnchor="end">
        {unit(max)}
      </text>
      <text x={PAD.l - 3} y={H - PAD.b} textAnchor="end">
        0
      </text>
      {[8, 12, 16, 20].map((h) => (
        <text key={h} x={x(h * 3600)} y={H - 2} textAnchor="middle">
          {h}:00
        </text>
      ))}
    </g>
  );
}

/** One small chart: the plot, the clock line, the hover line; click moves the clock. */
function Plot({ t, hover, setHover, children, label }: { t: number; hover: number | null; setHover: (t: number | null) => void; children: React.ReactNode; label: string }) {
  const at = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const v = tOf(((e.clientX - r.left) / r.width) * W);
    return v < T0 || v > T1 ? null : v;
  };
  return (
    <svg
      className="live-chart"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={label}
      onMouseMove={(e) => setHover(at(e))}
      onMouseLeave={() => setHover(null)}
      onClick={(e) => {
        const v = at(e);
        if (v !== null) setPlayback({ t: v });
      }}
    >
      {children}
      <line className="live-now" x1={x(t)} x2={x(t)} y1={PAD.t} y2={H - PAD.b} />
      {hover !== null && <line className="live-hover" x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b} />}
    </svg>
  );
}

export function LiveCharts({ replay }: { replay: Replay }) {
  const weekday = useApp((s) => s.playback.weekday);
  const split = useApp((s) => s.playback.split);
  const scenario = useApp((s) => s.playback.scenario);
  // the clock, a minute at a time (the charts redraw at most once a simulated minute)
  const t = useApp((s) => Math.floor(s.playback.t / 60) * 60);
  const nmTrips = useTrips(replay.files.trips.no_metro, weekday).data;
  const mTrips = useTrips(replay.files.trips.metro, weekday).data;
  const [hover, setHover] = useState<number | null>(null);

  const legs = useMemo(
    () => ({ no_metro: nmTrips ? dayLegs(nmTrips.paths, nmTrips.day) : null, metro: mTrips ? dayLegs(mTrips.paths, mTrips.day) : null }),
    [nmTrips, mTrips],
  );
  const bins = useMemo(() => {
    const ts = Float64Array.from({ length: Math.ceil((T1 - T0) / STEP) }, (_, i) => T0 + (i + 0.5) * STEP);
    const mean = (l: Legs | null) => {
      if (!l) return null;
      const b = binLegs(l, T0, T1, STEP);
      return b.travel.map((v, i) => (b.n[i]! >= 5 ? v / b.n[i]! : NaN)); // a few legs: no mean
    };
    const saved = legs.no_metro && legs.metro ? savedPerBin(legs.no_metro, legs.metro) : null;
    let run = 0;
    const cumulative = saved ? saved.map((v) => (run += v) / 3600) : null;
    return { ts, no_metro: mean(legs.no_metro), metro: mean(legs.metro), cumulative };
  }, [legs]);
  const shown = split || scenario === "metro" ? mTrips : nmTrips;
  const states = useMemo(() => {
    if (!shown) return null;
    const c = stateCurve(shown.paths, shown.day, T0, T1, SAMPLES);
    const ts = Float64Array.from({ length: SAMPLES }, (_, k) => T0 + ((T1 - T0) * k) / (SAMPLES - 1));
    let max = 0;
    for (let k = 0; k < SAMPLES; k++) max = Math.max(max, c.reduce((a, row) => a + row[k]!, 0));
    return { c, ts, max };
  }, [shown]);

  if (!legs.no_metro && !legs.metro) return <div className="dock-note muted">Loading the day…</div>;
  const read = hover ?? t;
  const so = { no_metro: legs.no_metro ? arrivedBy(legs.no_metro, t) : null, metro: legs.metro ? arrivedBy(legs.metro, t) : null };
  const maxMean = Math.max(...[bins.no_metro, bins.metro].flatMap((b) => (b ? Array.from(b).filter((v) => !Number.isNaN(v)) : [])), 60);
  const bin = Math.min(bins.ts.length - 1, Math.max(0, Math.floor((read - T0) / STEP)));
  const savedMax = bins.cumulative ? Math.max(1, bins.cumulative[bins.cumulative.length - 1]!) : 1;
  const sample = states ? Math.round(((read - T0) / (T1 - T0)) * (SAMPLES - 1)) : 0;

  return (
    <div className="live">
      <div className="live-head">
        <span className="muted">Today until {clock(t)}</span>
        {(["no_metro", "metro"] as const).map((sc) =>
          so[sc] ? (
            <span key={sc} className="live-stat" title={`${SCENARIOS[sc].label}: mean door-to-door time of the ${so[sc]!.n} legs arrived so far`}>
              <span className="swatch" style={{ background: SCENARIOS[sc].color }} />
              {SCENARIOS[sc].label} <b className="mono">{duration(so[sc]!.mean)}</b>
            </span>
          ) : null,
        )}
      </div>

      <div className="live-title">
        Mean leg, per 15 min
        <span className="muted mono">
          {clock(bins.ts[bin]! - STEP / 2)}: {bins.no_metro && !Number.isNaN(bins.no_metro[bin]!) ? duration(bins.no_metro[bin]!) : "–"} →{" "}
          {bins.metro && !Number.isNaN(bins.metro[bin]!) ? duration(bins.metro[bin]!) : "–"}
        </span>
      </div>
      <Plot t={t} hover={hover} setHover={setHover} label="Mean leg time per 15 minutes, without and with the metro">
        <Axis max={maxMean} unit={(v) => `${Math.round(v / 60)}m`} />
        {(["no_metro", "metro"] as const).map((sc) =>
          bins[sc] ? (
            <g key={sc} stroke={SCENARIOS[sc].color}>
              <path className="live-future" d={line(bins.ts, bins[sc]!, maxMean)} />
              <path className="live-line" d={line(bins.ts, bins[sc]!, maxMean, t)} />
            </g>
          ) : null,
        )}
      </Plot>

      {bins.cumulative && (
        <>
          <div className="live-title">
            Saved today
            <span className="muted mono">
              {clock(read)}: {bins.cumulative[bin]!.toFixed(0)} of {savedMax.toFixed(0)} student-hours
            </span>
          </div>
          <Plot t={t} hover={hover} setHover={setHover} label="Student-hours saved by the metro so far today">
            <Axis max={savedMax} unit={(v) => `${Math.round(v)}h`} />
            <g stroke={SCENARIOS.metro.color}>
              <path className="live-future" d={line(bins.ts, bins.cumulative, savedMax)} />
              <path className="live-line" d={line(bins.ts, bins.cumulative, savedMax, t)} />
            </g>
          </Plot>
        </>
      )}

      {states && (
        <>
          <div className="live-title">
            On the move{split ? " (with metro)" : ""}
            <span className="muted mono">
              {clock(read)}: {STUDENTS.map((s, i) => `${Math.round(states.c[i]![sample]!)} ${s.label}`).join(" · ")}
            </span>
          </div>
          <Plot t={t} hover={hover} setHover={setHover} label="Students walking, waiting, on the metro and on buses or trams">
            <Axis max={states.max} unit={(v) => `${Math.round(v)}`} />
            {Array.from({ length: N_STATES }, (_, s) => {
              // stacked: the top of state s is the sum of states 0..s
              const top = new Float64Array(SAMPLES);
              for (let k = 0; k < SAMPLES; k++) for (let j = 0; j <= s; j++) top[k]! += states.c[j]![k]!;
              return (
                <g key={s} stroke={STUDENTS[s]!.color}>
                  <path className="live-future" d={line(states.ts, top, states.max)} />
                  <path className="live-line" d={line(states.ts, top, states.max, t)} />
                </g>
              );
            })}
          </Plot>
        </>
      )}
    </div>
  );
}

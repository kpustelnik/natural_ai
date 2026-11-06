// Playback of the chosen replay, in two places:
// - PlaybackBar, floating at the bottom centre of the view: play, the clock and its slider,
//   steps (15 min, 1 h, the next class block), speed, weekday, scenario / split; for an ACO
//   run in the "ants" view the iteration player instead. The wheel over it steps the clock.
// - ReplayPanel, at the top of the right panel: what there is to read, the students' legend
//   with live charts (simulations) or the convergence chart and the best line (ACO).
// The clock itself (PlaybackClock) is mounted by App, so a replay keeps playing with the
// panels hidden or in presentation mode.

import { useEffect, useMemo, useState } from "react";
import { useAcoTrace } from "../data/resource";
import type { Replay, ReplayCatalog } from "../generated/schemas";
import { clock, studentHours, WEEKDAYS } from "../lib/format";
import { curveAt, sampleAt } from "../lib/metro";
import { STUDENTS, SCENARIOS } from "../scene/palette";
import { registry } from "../scene/registry";
import { app, setPlayback, useApp } from "../state/app";
import { ConvergenceChart, type Curve } from "./ConvergenceChart";
import { LiveCharts } from "./LiveCharts";
import { IconClose, IconPause, IconPlay } from "./icons";
import { Command } from "./Command";
import { openReplay } from "./ReplayMenu";

export const DAY_START = 6 * 3600;
export const DAY_END = 22 * 3600;
const DAY_SPEEDS = [1, 10, 60, 300, 600, 1800];
const ITER_SPEEDS = [1, 2, 5, 10, 20]; // iterations per second
// AGH class blocks (the most common class starts in demand/legs.parquet): the rushes
const BLOCKS = [8 * 60, 9 * 60 + 45, 11 * 60 + 30, 13 * 60 + 15, 15 * 60, 16 * 60 + 45, 18 * 60 + 30].map((m) => m * 60);
const RUSH_LEAD = 15 * 60; // a jump lands this long before the block starts

/** Advances the playback while playing: the iteration (ants) or the day time. Play at the
 *  end starts over. ``end`` null (no replay, trace still loading): no clock. */
function useClock(mode: "iteration" | "day", end: number | null) {
  const playing = useApp((s) => s.playback.playing);
  useEffect(() => {
    if (!playing || end === null) return;
    const start = app.get().playback;
    if (mode === "iteration" && start.iteration >= end) setPlayback({ iteration: 0 });
    if (mode === "day" && start.t >= end) setPlayback({ t: DAY_START });
    let last = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const p = app.get().playback;
      const dt = ((now - last) / 1000) * p.speed;
      last = now;
      if (mode === "iteration") {
        const iteration = Math.min(end, p.iteration + dt);
        setPlayback({ iteration, playing: iteration < end });
      } else {
        const t = Math.min(end, p.t + dt);
        setPlayback({ t, playing: t < end });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, mode, end]);
}

/** The playback clock of the open replay. Mounted by App, not by the dock, so a replay keeps
 *  playing with the right panel hidden or in presentation mode. */
export function PlaybackClock({ catalog }: { catalog: ReplayCatalog | undefined }) {
  const id = useApp((s) => s.playback.replayId);
  const acoView = useApp((s) => s.playback.acoView);
  const replay = catalog?.replays.find((r) => r.id === id);
  const ants = replay?.kind === "aco" && acoView === "ants" && !!replay.files.aco_trace;
  const trace = useAcoTrace(ants ? replay!.files.aco_trace : null).data;
  useEffect(() => {
    // a replay opened from the URL keeps the default speed: make it fit the view
    if (!replay) return;
    const p = app.get().playback;
    if (ants && !ITER_SPEEDS.includes(p.speed)) setPlayback({ speed: 5 });
    if (!ants && !DAY_SPEEDS.includes(p.speed)) setPlayback({ speed: 60 });
  }, [replay, ants]);
  useClock(ants ? "iteration" : "day", !replay ? null : ants ? (trace ? trace.header.n_iterations - 1 : null) : DAY_END);
  return null;
}

/** Moves the day clock by `dt` seconds (kept inside the day). */
export function stepClock(dt: number): void {
  const t = app.get().playback.t;
  setPlayback({ t: Math.min(DAY_END, Math.max(DAY_START, t + dt)) });
}

/** Jumps to just before the next (dir 1) or previous (dir -1) class block. */
export function jumpBlock(dir: 1 | -1): void {
  const t = app.get().playback.t;
  const marks = BLOCKS.map((b) => b - RUSH_LEAD);
  const next = dir > 0 ? marks.find((m) => m > t + 30) : [...marks].reverse().find((m) => m < t - 30);
  if (next !== undefined) setPlayback({ t: next });
}

/** Moves the iteration player by `d` iterations. */
export function stepIteration(d: number, end: number): void {
  const it = app.get().playback.iteration;
  setPlayback({ iteration: Math.min(end, Math.max(0, Math.round(it) + d)), playing: false });
}

function PlayButton() {
  const playing = useApp((s) => s.playback.playing);
  return (
    <button className="play" onClick={() => setPlayback({ playing: !playing })} title="Play / pause (space)">
      {playing ? <IconPause size={16} /> : <IconPlay size={16} />}
    </button>
  );
}

function Step({ label, title, onClick }: { label: string; title: string; onClick: () => void }) {
  return (
    <button className="step-button mono" onClick={onClick} title={title} aria-label={title}>
      {label}
    </button>
  );
}

function Speed({ options, unit }: { options: number[]; unit: string }) {
  const speed = useApp((s) => s.playback.speed);
  return (
    <div className="segmented small" role="group" aria-label="Speed">
      {options.map((s) => (
        <button key={s} className={s === speed ? "active" : ""} aria-pressed={s === speed} onClick={() => setPlayback({ speed: s })}>
          {s}
          {unit}
        </button>
      ))}
    </div>
  );
}

function DayControls({ replay }: { replay: Replay }) {
  const p = useApp((s) => s.playback);
  const sim = replay.kind === "simulation";
  return (
    <>
      <div className="dock-controls">
        <Step label="⏮" title="Start of the day (Home)" onClick={() => setPlayback({ t: DAY_START })} />
        <Step label="«" title="Previous class block (Shift+PageUp)" onClick={() => jumpBlock(-1)} />
        <Step label="−1h" title="Back an hour (Shift+←)" onClick={() => stepClock(-3600)} />
        <Step label="−15" title="Back 15 minutes (←, wheel)" onClick={() => stepClock(-900)} />
        <PlayButton />
        <Step label="+15" title="Forward 15 minutes (→, wheel)" onClick={() => stepClock(900)} />
        <Step label="+1h" title="Forward an hour (Shift+→)" onClick={() => stepClock(3600)} />
        <Step label="»" title="Next class block, 15 min before it starts (Shift+PageDown)" onClick={() => jumpBlock(1)} />
        <span className="clock mono">
          {WEEKDAYS[p.weekday - 1]} {clock(p.t)}
        </span>
        <input
          className="time-slider"
          type="range"
          min={DAY_START}
          max={DAY_END}
          step={60}
          value={p.t}
          onChange={(e) => setPlayback({ t: Number(e.target.value) })}
          aria-label="Time of day"
        />
      </div>
      <div className="dock-controls">
        <Speed options={DAY_SPEEDS} unit="×" />
        {replay.weekdays.length > 1 && (
          <div className="segmented small" role="group" aria-label="Weekday">
            {replay.weekdays.map((d) => (
              <button key={d} className={p.weekday === d ? "active" : ""} aria-pressed={p.weekday === d} onClick={() => setPlayback({ weekday: d })}>
                {WEEKDAYS[d - 1]}
              </button>
            ))}
          </div>
        )}
        {sim && replay.scenarios.length > 0 && (
          <div className="segmented small" role="group" aria-label="Scenario">
            {replay.scenarios.map((s) => (
              <button
                key={s}
                className={!p.split && p.scenario === s ? "active" : ""}
                aria-pressed={!p.split && p.scenario === s}
                onClick={() => setPlayback({ scenario: s, split: false })}
              >
                {SCENARIOS[s].label}
              </button>
            ))}
            {replay.scenarios.length === 2 && (
              <button className={p.split ? "active" : ""} aria-pressed={p.split} onClick={() => setPlayback({ split: !p.split })} title="Both scenarios side by side">
                Split
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function useCurve(replay: Replay) {
  const trace = useAcoTrace(replay.files.aco_trace).data;
  const curve = useMemo<Curve | null>(
    () =>
      trace
        ? {
            iteration: trace.arrays.curve_iteration as Int32Array,
            best: trace.arrays.curve_best_s as Float32Array,
            iterBest: trace.arrays.curve_iter_best_s as Float32Array,
            iterMean: trace.arrays.curve_iter_mean_s as Float32Array,
          }
        : null,
    [trace],
  );
  return { trace, curve };
}

/** Last iteration of the open ACO trace, for the keyboard steps (App). */
export let iterationEnd = 0;

function AntControls({ replay }: { replay: Replay }) {
  const { trace } = useCurve(replay);
  const iteration = useApp((s) => s.playback.iteration);
  if (!trace) return <div className="dock-note muted">Loading the trace…</div>;
  const end = trace.header.n_iterations - 1;
  iterationEnd = end;
  return (
    <div className="dock-controls">
      <Step label="⏮" title="First iteration (Home)" onClick={() => setPlayback({ iteration: 0, playing: false })} />
      <Step label="−10" title="Back 10 iterations (Shift+←)" onClick={() => stepIteration(-10, end)} />
      <Step label="−1" title="Back one iteration (←, wheel)" onClick={() => stepIteration(-1, end)} />
      <PlayButton />
      <Step label="+1" title="Forward one iteration (→, wheel)" onClick={() => stepIteration(1, end)} />
      <Step label="+10" title="Forward 10 iterations (Shift+→)" onClick={() => stepIteration(10, end)} />
      <Step label="⏭" title="Last iteration (End)" onClick={() => setPlayback({ iteration: end, playing: false })} />
      <span className="clock mono" title="Iteration">
        {Math.floor(iteration)}/{end}
      </span>
      <input
        className="time-slider"
        type="range"
        min={0}
        max={end}
        step={1}
        value={Math.floor(iteration)}
        onChange={(e) => setPlayback({ iteration: Number(e.target.value), playing: false })}
        aria-label="Iteration"
      />
      <Speed options={ITER_SPEEDS} unit="/s" />
    </div>
  );
}

function AcoInfo({ replay, catalog }: { replay: Replay; catalog: ReplayCatalog | undefined }) {
  const { trace, curve } = useCurve(replay);
  const iteration = useApp((s) => s.playback.iteration);
  const week = simulationOf(replay, catalog);
  const link = week ? (
    <button className="link-button" onClick={() => openReplay(week)} title={week.title}>
      Simulate this line: the week with and without it →
    </button>
  ) : (
    <span className="muted">This line has no week simulation (05_simulate.py --showcase).</span>
  );
  if (!trace || !curve) return <div className="dock-note">{link}</div>;
  const h = trace.header;
  const sampled = trace.arrays.iterations as Int32Array;
  const { s } = sampleAt(sampled, iteration);
  const k = h.k;
  const best = Array.from((trace.arrays.best_tour as Int16Array).subarray(s * k, (s + 1) * k)).map((i) => h.candidate_ids[i]!);
  // the cost of the line shown: the trace keeps a best line every few iterations only
  const bestCost = curve.best.length ? curveAt(curve.iteration, curve.best, sampled[s]!) : h.best_s;
  const saving = 1 - bestCost / h.baseline_s;
  const delta = `${saving >= 0 ? "−" : "+"}${Math.abs(100 * saving).toFixed(1)}%`;
  const line = best.join(" – ") + (h.topology === "loop" ? " (loop)" : "");
  return (
    <>
      <div className="aco-body">
        <ConvergenceChart
          curve={curve}
          baseline={h.baseline_s}
          iteration={iteration}
          nIterations={h.n_iterations}
          onScrub={(it) => setPlayback({ iteration: it, playing: false })}
        />
        <div className="aco-stats" title={line}>
          <span className="mono strong">{studentHours(bestCost)}</span>
          <span className="mono muted">{delta}</span>
          <span className="aco-line">{line}</span>
        </div>
      </div>
      <div className="dock-note">{link}</div>
    </>
  );
}

const fmt = (v: number) => v.toLocaleString("en-US");

/** Legend of the student colours, with how many are on screen (refreshed 4× a second). */
function StudentLegend({ replay }: { replay: Replay }) {
  const split = useApp((s) => s.playback.split);
  const scenario = useApp((s) => s.playback.scenario);
  const [counts, setCounts] = useState<Record<string, [number, number, number, number]>>({});
  useEffect(() => {
    const id = setInterval(() => setCounts({ ...registry.onScreen }), 250);
    return () => clearInterval(id);
  }, []);
  const shown = (split ? replay.scenarios : replay.scenarios.filter((s) => s === scenario)).filter((s) => counts[s]);
  const total = (s: string) => counts[s]!.reduce((a, b) => a + b, 0);
  return (
    <div className="dock-legend">
      {STUDENTS.map((st, i) => (
        <span key={st.label} className="legend-item" title={st.label}>
          <span className="dot" style={{ background: st.color }} />
          {st.label}
          {shown.length === 1 && <span className="mono">{fmt(counts[shown[0]!]![i]!)}</span>}
        </span>
      ))}
      {shown.map((s) => (
        <span key={s} className="legend-item muted">
          {split ? `${SCENARIOS[s].label} ` : ""}
          <span className="mono">{fmt(total(s))}</span>
        </span>
      ))}
    </div>
  );
}

/** The simulated week of the same line (stations in any order: a reversed line is the same). */
function simulationOf(replay: Replay, catalog: ReplayCatalog | undefined): Replay | null {
  const key = (r: Replay) => [...r.stations].sort().join("|") + r.topology;
  return catalog?.replays.find((r) => r.kind === "simulation" && key(r) === key(replay)) ?? null;
}

function useReplay(catalog: ReplayCatalog | undefined): Replay | undefined {
  const id = useApp((s) => s.playback.replayId);
  return catalog?.replays.find((r) => r.id === id);
}

/** The floating playback bar at the bottom centre of the view. */
export function PlaybackBar({ catalog }: { catalog: ReplayCatalog | undefined }) {
  const replay = useReplay(catalog);
  const acoView = useApp((s) => s.playback.acoView);
  const workspace = useApp((s) => s.workspace);
  const trace = useAcoTrace(replay?.kind === "aco" && acoView === "ants" ? replay.files.aco_trace : null).data;
  if (!replay || (workspace !== "metro" && workspace !== "simulation")) return null;
  const sim = replay.kind === "simulation";
  const files = replay.files;
  const ants = !sim && acoView === "ants" && !!files.aco_trace;
  const onWheel = (e: React.WheelEvent) => {
    const d = Math.sign(e.deltaY); // down: later
    if (!d) return;
    if (ants) stepIteration(e.shiftKey ? d * 10 : d, trace ? trace.header.n_iterations - 1 : 0);
    else stepClock(d * (e.shiftKey ? 3600 : 900));
  };
  return (
    <div className="playback-bar" onWheel={onWheel}>
      <div className="dock-title">
        <strong title={replay.title}>{replay.title}</strong>
        {!sim && (
          <div className="segmented small" role="group" aria-label="Show">
            <button
              className={acoView === "ants" ? "active" : ""}
              aria-pressed={acoView === "ants"}
              onClick={() => setPlayback({ acoView: "ants", playing: false, speed: 5 })}
              disabled={!files.aco_trace}
            >
              Ants
            </button>
            <button
              className={acoView === "trains" ? "active" : ""}
              aria-pressed={acoView === "trains"}
              onClick={() => setPlayback({ acoView: "trains", playing: false, speed: 60 })}
              disabled={!files.metro}
              title="Best line with trains"
            >
              Trains
            </button>
          </div>
        )}
        <button className="icon-button" title="Close replay" aria-label="Close replay" onClick={() => openReplay(null)}>
          <IconClose size={14} />
        </button>
      </div>
      {ants ? <AntControls replay={replay} /> : <DayControls replay={replay} />}
      {!sim && !files.aco_trace && !files.metro && (
        <div className="dock-note muted">
          No playable files.
          <Command lines={["uv run scripts/06_export_web.py --aco"]} />
        </div>
      )}
    </div>
  );
}

/** What the open replay has to read, at the top of the right panel. */
export function ReplayPanel({ catalog }: { catalog: ReplayCatalog | undefined }) {
  const replay = useReplay(catalog);
  const tabsOpen = useApp((s) => s.tabsOpen);
  const height = useApp((s) => s.replayHeight);
  if (!replay) return null;
  const sim = replay.kind === "simulation";
  const hasTrips = Object.keys(replay.files.trips ?? {}).length > 0;
  return (
    <div className="replay-panel" style={tabsOpen ? { height } : undefined}>
      {!sim && <AcoInfo replay={replay} catalog={catalog} />}
      {sim && hasTrips && <StudentLegend replay={replay} />}
      {sim && hasTrips && <LiveCharts replay={replay} />}
      {sim && !hasTrips && (
        <div className="dock-note muted">
          No students yet.
          <Command lines={["uv run scripts/05_simulate.py", "uv run scripts/06_export_web.py --sim"]} />
        </div>
      )}
    </div>
  );
}

/** Kept for the old name: the right panel's replay part. */
export const Timeline = ReplayPanel;

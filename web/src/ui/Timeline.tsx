// Playback dock for the chosen replay (mounted at the top of the right panel). The clock
// runs here; the scene layers read it from the store every frame.
//
// - ACO run, "ants" view: the iteration player (scrubber, iterations per second) with the
//   convergence chart and the best line so far;
// - ACO run, "trains" view, and simulations: the day clock (06:00 to 22:00), speed,
//   weekday; simulations also the scenario (or both side by side) and a legend of the
//   students with how many are on screen.

import { useEffect, useMemo, useState } from "react";
import { useAcoTrace } from "../data/resource";
import type { Replay, ReplayCatalog } from "../generated/schemas";
import { clock, studentHours, WEEKDAYS } from "../lib/format";
import { sampleAt } from "../lib/metro";
import { STUDENTS, SCENARIOS } from "../scene/palette";
import { registry } from "../scene/registry";
import { app, setPlayback, useApp } from "../state/app";
import { ConvergenceChart, type Curve } from "./ConvergenceChart";
import { IconClose, IconPause, IconPlay } from "./icons";
import { Command } from "./Command";
import { openReplay } from "./ReplayMenu";

const DAY_START = 6 * 3600;
const DAY_END = 22 * 3600;
const DAY_SPEEDS = [1, 10, 60, 300, 600];
const ITER_SPEEDS = [1, 2, 5, 10, 20]; // iterations per second

/** Advances the playback while playing: the iteration (ants) or the day time. */
function useClock(mode: "iteration" | "day", end: number) {
  const playing = useApp((s) => s.playback.playing);
  useEffect(() => {
    if (!playing) return;
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

function PlayButton() {
  const playing = useApp((s) => s.playback.playing);
  return (
    <button className="play" onClick={() => setPlayback({ playing: !playing })} title="Play / pause (space)">
      {playing ? <IconPause size={16} /> : <IconPlay size={16} />}
    </button>
  );
}

function Speed({ options, unit }: { options: number[]; unit: string }) {
  const speed = useApp((s) => s.playback.speed);
  return (
    <select value={speed} onChange={(e) => setPlayback({ speed: Number(e.target.value) })} title="Speed">
      {!options.includes(speed) && <option value={speed}>{speed}</option>}
      {options.map((s) => (
        <option key={s} value={s}>
          {s}
          {unit}
        </option>
      ))}
    </select>
  );
}

function DayControls({ replay, scenarios }: { replay: Replay; scenarios: boolean }) {
  const p = useApp((s) => s.playback);
  useClock("day", DAY_END);
  return (
    <div className="dock-controls">
      <PlayButton />
      <span className="clock mono">{clock(p.t)}</span>
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
      <Speed options={DAY_SPEEDS} unit="×" />
      {replay.weekdays.length > 0 && (
        <select
          value={p.weekday}
          onChange={(e) => setPlayback({ weekday: Number(e.target.value) })}
          title="Weekday"
          aria-label="Weekday"
        >
          {replay.weekdays.map((d) => (
            <option key={d} value={d}>
              {WEEKDAYS[d - 1]}
            </option>
          ))}
        </select>
      )}
      {scenarios && replay.scenarios.length > 0 && (
        <div className="segmented small" role="group" aria-label="Scenario">
          {replay.scenarios.map((s) => (
            <button
              key={s}
              className={!p.split && p.scenario === s ? "active" : ""}
              aria-pressed={!p.split && p.scenario === s}
              onClick={() => setPlayback({ scenario: s, split: false })}
            >
              {s === "metro" ? "Metro" : "Walk"}
            </button>
          ))}
          {replay.scenarios.length === 2 && (
            <button
              className={p.split ? "active" : ""}
              aria-pressed={p.split}
              onClick={() => setPlayback({ split: !p.split })}
              title="Both scenarios side by side"
            >
              Split
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const fmt = (v: number) => v.toLocaleString("en-US");

/** Legend of the student colours, with how many are on screen (refreshed 4× a second). */
function StudentLegend({ replay }: { replay: Replay }) {
  const split = useApp((s) => s.playback.split);
  const scenario = useApp((s) => s.playback.scenario);
  const [counts, setCounts] = useState<Record<string, [number, number, number]>>({});
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

function AntControls({ replay }: { replay: Replay }) {
  const trace = useAcoTrace(replay.files.aco_trace).data;
  const iteration = useApp((s) => s.playback.iteration);
  const end = trace ? trace.header.n_iterations - 1 : 0;
  useClock("iteration", end);
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
  if (!trace || !curve) return <div className="dock-note muted">Loading the trace…</div>;
  const h = trace.header;
  const { s } = sampleAt(trace.arrays.iterations as Int32Array, iteration);
  const k = h.k;
  const best = Array.from((trace.arrays.best_tour as Int16Array).subarray(s * k, (s + 1) * k)).map((i) => h.candidate_ids[i]!);
  const bestCost = curve.best[Math.min(curve.best.length - 1, Math.max(0, Math.floor(iteration)))] ?? h.best_s;
  const saving = 1 - bestCost / h.baseline_s;
  const delta = `${saving >= 0 ? "−" : "+"}${Math.abs(100 * saving).toFixed(1)}%`;
  const line = best.join(" – ") + (h.topology === "loop" ? " (loop)" : "");
  return (
    <>
      <div className="dock-controls">
        <PlayButton />
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
    </>
  );
}

function Dock({ replay }: { replay: Replay }) {
  const acoView = useApp((s) => s.playback.acoView);
  useEffect(() => {
    // a replay opened from the URL keeps the default speed: make it fit the view
    const p = app.get().playback;
    const ants = replay.kind === "aco" && p.acoView === "ants";
    if (ants && !ITER_SPEEDS.includes(p.speed)) setPlayback({ speed: 5 });
    if (!ants && !DAY_SPEEDS.includes(p.speed)) setPlayback({ speed: 60 });
  }, [replay]);
  const sim = replay.kind === "simulation";
  const files = replay.files;
  const hasTrips = Object.keys(files.trips ?? {}).length > 0;
  const view = sim ? "day" : acoView === "ants" && files.aco_trace ? "ants" : "day";

  return (
    <div className="dock">
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
      {view === "ants" ? <AntControls replay={replay} /> : <DayControls replay={replay} scenarios={sim} />}
      {sim && hasTrips && <StudentLegend replay={replay} />}
      {sim && !hasTrips && (
        <div className="dock-note muted">
          No students yet.
          <Command lines={["uv run scripts/05_simulate.py", "uv run scripts/06_export_web.py --sim"]} />
        </div>
      )}
      {!sim && !files.aco_trace && !files.metro && (
        <div className="dock-note muted">
          No playable files.
          <Command lines={["uv run scripts/06_export_web.py --aco"]} />
        </div>
      )}
    </div>
  );
}

export function Timeline({ catalog }: { catalog: ReplayCatalog | undefined }) {
  const id = useApp((s) => s.playback.replayId);
  const replay = catalog?.replays.find((r) => r.id === id);
  return replay ? <Dock replay={replay} /> : null;
}

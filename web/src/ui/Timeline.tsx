// Playback dock for the chosen replay. The clock runs here; the scene layers read it from
// the store every frame.
//
// - ACO run, "ants" view: the iteration player (scrubber, iterations per second) with the
//   convergence chart and the best line so far;
// - ACO run, "trains" view, and simulations: the day clock (06:00 to 22:00), speed,
//   weekday and scenario. Trains run on the line; students arrive with phase 6.

import { useEffect, useMemo } from "react";
import { useAcoTrace } from "../data/resource";
import type { Replay, ReplayCatalog } from "../generated/schemas";
import { clock, studentHours, WEEKDAYS } from "../lib/format";
import { sampleAt } from "../lib/metro";
import { app, setPlayback, useApp } from "../state/app";
import { ConvergenceChart, type Curve } from "./ConvergenceChart";
import { IconClose, IconPause, IconPlay } from "./icons";
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
        <div className="segmented small">
          {replay.weekdays.map((d) => (
            <button key={d} className={p.weekday === d ? "active" : ""} onClick={() => setPlayback({ weekday: d })}>
              {WEEKDAYS[d - 1]}
            </button>
          ))}
        </div>
      )}
      {scenarios && replay.scenarios.length > 0 && (
        <div className="segmented small">
          {replay.scenarios.map((s) => (
            <button key={s} className={p.scenario === s ? "active" : ""} onClick={() => setPlayback({ scenario: s })}>
              {s === "metro" ? "with metro" : "no metro"}
            </button>
          ))}
        </div>
      )}
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
  return (
    <>
      <div className="dock-controls">
        <PlayButton />
        <span className="clock mono" title="Iteration">
          {Math.floor(iteration)} / {end}
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
        <Speed options={ITER_SPEEDS} unit=" it/s" />
      </div>
      <div className="aco-body">
        <ConvergenceChart
          curve={curve}
          baseline={h.baseline_s}
          iteration={iteration}
          nIterations={h.n_iterations}
          onScrub={(it) => setPlayback({ iteration: it, playing: false })}
        />
        <div className="aco-stats">
          <div className="kv">
            <span className="k">best so far</span>
            <span className="v mono strong">{studentHours(bestCost)}</span>
          </div>
          <div className="kv">
            <span className="k">vs no metro</span>
            <span className="v mono">{saving >= 0 ? "−" : "+"}{Math.abs(100 * saving).toFixed(1)} %</span>
          </div>
          <div className="kv">
            <span className="k">ants shown</span>
            <span className="v mono">{h.buffers.tours!.shape[1]} per sample</span>
          </div>
          <div className="aco-line" title="Best line so far, in line order">
            {best.map((id, i) => (
              <span key={id}>
                {i > 0 && <span className="muted"> – </span>}
                <strong>{id}</strong>
              </span>
            ))}
            {h.topology === "loop" && <span className="muted"> (loop)</span>}
          </div>
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
    <div className={`dock ${view === "ants" ? "wide" : ""}`}>
      <div className="dock-title">
        <span className="chip">{sim ? "simulation" : "ACO run"}</span>
        <strong>{replay.title}</strong>
        {!sim && (
          <div className="segmented small" role="group" aria-label="Show">
            <button
              className={acoView === "ants" ? "active" : ""}
              onClick={() => setPlayback({ acoView: "ants", playing: false, speed: 5 })}
              disabled={!files.aco_trace}
            >
              Ants
            </button>
            <button
              className={acoView === "trains" ? "active" : ""}
              onClick={() => setPlayback({ acoView: "trains", playing: false, speed: 60 })}
              disabled={!files.metro}
              title="The best line with its trains"
            >
              Trains
            </button>
          </div>
        )}
        <button className="icon-button" title="Close replay" onClick={() => openReplay(null)}>
          <IconClose size={14} />
        </button>
      </div>
      {view === "ants" ? <AntControls replay={replay} /> : <DayControls replay={replay} scenarios={sim} />}
      {replay.description && <div className="dock-note muted">{replay.description}</div>}
      {sim && !hasTrips && (
        <div className="dock-note muted">
          {files.metro ? "Trains run on the line; " : ""}students appear once the simulation is exported (phase 6).
        </div>
      )}
      {!sim && !files.aco_trace && !files.metro && <div className="dock-note muted">This replay lists no playable files.</div>}
    </div>
  );
}

export function Timeline({ catalog }: { catalog: ReplayCatalog | undefined }) {
  const id = useApp((s) => s.playback.replayId);
  const replay = catalog?.replays.find((r) => r.id === id);
  return replay ? <Dock replay={replay} /> : null;
}

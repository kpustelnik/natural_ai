// Playback dock for the chosen replay: play/pause, speed, time, weekday and scenario.
// The clock runs here; the metro, ACO and student layers (phases 5 and 6) read it from
// the store every frame.

import { useEffect } from "react";
import type { Replay, ReplayCatalog } from "../generated/schemas";
import { clock, WEEKDAYS } from "../lib/format";
import { app, setPlayback, useApp } from "../state/app";
import { IconClose, IconPause, IconPlay } from "./icons";
import { openReplay } from "./ReplayMenu";

const DAY_START = 6 * 3600;
const DAY_END = 22 * 3600;
const SPEEDS = [1, 10, 60, 300, 600];

function useClock(replay: Replay) {
  const playing = useApp((s) => s.playback.playing);
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const p = app.get().playback;
      const dt = ((now - last) / 1000) * (replay.kind === "aco" ? p.speed / 60 : p.speed);
      last = now;
      const end = replay.kind === "aco" ? Number.POSITIVE_INFINITY : DAY_END;
      const t = Math.min(end, p.t + dt);
      setPlayback({ t, playing: t < end });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, replay]);
}

function Dock({ replay }: { replay: Replay }) {
  const p = useApp((s) => s.playback);
  useClock(replay);
  const sim = replay.kind === "simulation";
  const files = replay.files;
  const ready = sim ? Object.keys(files.trips ?? {}).length > 0 : !!files.aco_trace;

  return (
    <div className="dock">
      <div className="dock-title">
        <span className="chip">{sim ? "simulation" : "ACO run"}</span>
        <strong>{replay.title}</strong>
        <button className="icon-button" title="Close replay" onClick={() => openReplay(null)}>
          <IconClose size={14} />
        </button>
      </div>
      <div className="dock-controls">
        <button className="play" onClick={() => setPlayback({ playing: !p.playing })} title="Play / pause (space)">
          {p.playing ? <IconPause size={16} /> : <IconPlay size={16} />}
        </button>
        <span className="clock mono">{sim ? clock(p.t) : `iter ${Math.floor(p.t)}`}</span>
        {sim ? (
          <input
            className="time-slider"
            type="range"
            min={DAY_START}
            max={DAY_END}
            step={60}
            value={p.t}
            onChange={(e) => setPlayback({ t: Number(e.target.value) })}
          />
        ) : (
          <div className="time-slider placeholder">iteration scrubber appears when the trace is loaded</div>
        )}
        <select value={p.speed} onChange={(e) => setPlayback({ speed: Number(e.target.value) })} title="Speed">
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
        {sim && replay.weekdays.length > 0 && (
          <div className="segmented small">
            {replay.weekdays.map((d) => (
              <button key={d} className={p.weekday === d ? "active" : ""} onClick={() => setPlayback({ weekday: d })}>
                {WEEKDAYS[d - 1]}
              </button>
            ))}
          </div>
        )}
        {sim && replay.scenarios.length > 0 && (
          <div className="segmented small">
            {replay.scenarios.map((s) => (
              <button key={s} className={p.scenario === s ? "active" : ""} onClick={() => setPlayback({ scenario: s })}>
                {s === "metro" ? "with metro" : "no metro"}
              </button>
            ))}
          </div>
        )}
      </div>
      {!ready && <div className="dock-note muted">This replay lists no playable files.</div>}
      {ready && <div className="dock-note muted">3D playback of {sim ? "students" : "ants and pheromone"} arrives in phase {sim ? 6 : 5}.</div>}
    </div>
  );
}

export function Timeline({ catalog }: { catalog: ReplayCatalog | undefined }) {
  const id = useApp((s) => s.playback.replayId);
  const replay = catalog?.replays.find((r) => r.id === id);
  return replay ? <Dock replay={replay} /> : null;
}

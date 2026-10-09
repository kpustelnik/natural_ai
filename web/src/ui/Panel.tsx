import type { Scenario } from "../generated/schemas";

export interface Playback {
  scenario: Scenario;
  weekday: number; // 1 = Monday ... 5 = Friday
  t: number; // seconds since 00:00
}

const WEEKDAYS = ["Pon", "Wt", "Śr", "Czw", "Pt"];
const T_MIN = 6 * 3600;
const T_MAX = 22 * 3600;

function clock(t: number): string {
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

interface Props {
  playback: Playback;
  onChange: (p: Playback) => void;
  status: string | null;
}

export function Panel({ playback, onChange, status }: Props) {
  return (
    <div className="panel">
      <h1>Metro AGH</h1>

      <div className="row">
        {(["no_metro", "metro"] as const).map((s) => (
          <button
            key={s}
            className={playback.scenario === s ? "active" : ""}
            onClick={() => onChange({ ...playback, scenario: s })}
          >
            {s === "metro" ? "z metrem" : "bez metra"}
          </button>
        ))}
      </div>

      <div className="row">
        {WEEKDAYS.map((name, i) => (
          <button
            key={name}
            className={playback.weekday === i + 1 ? "active" : ""}
            onClick={() => onChange({ ...playback, weekday: i + 1 })}
          >
            {name}
          </button>
        ))}
      </div>

      <label className="time">
        <span>{clock(playback.t)}</span>
        <input
          type="range"
          min={T_MIN}
          max={T_MAX}
          step={60}
          value={playback.t}
          onChange={(e) => onChange({ ...playback, t: Number(e.target.value) })}
        />
      </label>

      {status && <p className="status">{status}</p>}
    </div>
  );
}

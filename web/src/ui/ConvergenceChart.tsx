// Convergence of an ACO run: best-so-far objective (accent), the best and the mean of
// each iteration (greys, told apart by stroke too), the no-metro baseline (dashed) and a
// cursor at the playback iteration. Hover reads the values; a click scrubs to there.

import { useMemo, useState } from "react";
import { studentHours } from "../lib/format";
import { curveAt } from "../lib/metro";
import { ACCENT } from "../scene/palette";

export interface Curve {
  iteration: Int32Array;
  best: Float32Array;
  iterBest: Float32Array;
  iterMean: Float32Array;
}

const W = 340;
const H = 52;
const PAD = { left: 4, right: 4, top: 4, bottom: 3 };
const SERIES = [
  { key: "best", label: "best", color: ACCENT, width: 2, dash: undefined },
  { key: "iterBest", label: "iter", color: "#5f656c", width: 1, dash: undefined },
  { key: "iterMean", label: "mean", color: "#8a9098", width: 1, dash: "2 2" },
] as const;

export function ConvergenceChart({
  curve,
  baseline,
  iteration,
  nIterations,
  onScrub,
  labels,
  baseLabel = "base",
  format = studentHours,
}: {
  curve: Curve;
  baseline: number;
  iteration: number;
  nIterations: number;
  onScrub: (iteration: number) => void;
  /** other names for the three series (the walk player: assignment, iteration, MSA) */
  labels?: [string, string, string];
  baseLabel?: string;
  format?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const { x, y, paths } = useMemo(() => {
    let lo = Infinity;
    let hi = baseline;
    for (const s of SERIES) for (const v of curve[s.key]) (lo = Math.min(lo, v)), (hi = Math.max(hi, v));
    const pad = (hi - lo) * 0.06 || 1;
    lo -= pad;
    hi += pad;
    const x = (i: number) => PAD.left + (i / Math.max(1, nIterations - 1)) * (W - PAD.left - PAD.right);
    const y = (v: number) => PAD.top + ((hi - v) / (hi - lo)) * (H - PAD.top - PAD.bottom);
    const paths = SERIES.map((s) => {
      const ys = curve[s.key];
      let d = "";
      curve.iteration.forEach((it, i) => (d += `${i ? "L" : "M"}${x(it).toFixed(1)},${y(ys[i]!).toFixed(1)}`));
      return d;
    });
    return { x, y, paths };
  }, [curve, baseline, nIterations]);

  const at = hover ?? iteration;
  const toIteration = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const f = ((e.clientX - r.left) / r.width) * W;
    const it = ((f - PAD.left) / (W - PAD.left - PAD.right)) * (nIterations - 1);
    return Math.max(0, Math.min(nIterations - 1, Math.round(it)));
  };

  return (
    <div className="chart">
      <div className="chart-legend">
        {SERIES.map((s, i) => (
          <span key={s.key} className="legend-item" title={`${labels?.[i] ?? s.label}: ${format(curveAt(curve.iteration, curve[s.key], at))}`}>
            <svg width="12" height="6" aria-hidden>
              <line x1="0" y1="3" x2="12" y2="3" stroke={s.color} strokeWidth={s.width + 0.5} strokeDasharray={s.dash} />
            </svg>
            {labels?.[i] ?? s.label}
          </span>
        ))}
        <span className="legend-item muted" title={`${baseLabel}: ${format(baseline)}`}>
          <svg width="12" height="6" aria-hidden>
            <line x1="0" y1="3" x2="12" y2="3" stroke="#9aa0a7" strokeDasharray="4 3" />
          </svg>
          {baseLabel}
        </span>
        <span className="legend-item mono chart-hover">
          {hover !== null ? `it ${hover}` : ""} {format(curveAt(curve.iteration, curve.best, at))}
        </span>
      </div>
      <svg
        className="chart-plot"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Objective per iteration, student-hours per week"
        onMouseMove={(e) => setHover(toIteration(e))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => onScrub(toIteration(e))}
      >
        <line x1={PAD.left} x2={W - PAD.right} y1={y(baseline)} y2={y(baseline)} stroke="#9aa0a7" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
        {SERIES.map((s, i) => (
          <path
            key={s.key}
            d={paths[i]}
            fill="none"
            stroke={s.color}
            strokeWidth={s.width}
            strokeDasharray={s.dash}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <line x1={x(iteration)} x2={x(iteration)} y1={PAD.top} y2={H - PAD.bottom} stroke="#2f3338" vectorEffect="non-scaling-stroke" />
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} stroke="#9aa0a7" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
    </div>
  );
}

// The Student tab of a simulation: one student's day (students/day-<weekday>): their legs
// in order (where from, where to, when the class starts) and how each went without and with
// the metro: when they leave, how (walk / metro / bus or tram, where they board), waiting,
// door to door, late. Pick a student by clicking one in the view, at random, or by number;
// the view marks them and can follow them. A leg row moves the clock to its start.

import { useMemo, useState } from "react";
import { useStudents } from "../data/resource";
import type { Replay } from "../generated/schemas";
import { clock, duration, WEEKDAYS } from "../lib/format";
import { dayTotals, type LegRow, MODE_LABEL, placeName, randomStudent, type StudentArrays, studentLegs, whereAt } from "../lib/students";
import { SCENARIOS, STUDENTS } from "../scene/palette";
import { app, setPlayback, useApp } from "../state/app";
import { Command } from "./Command";

const MODE_COLOR = [STUDENTS[0].color, STUDENTS[2].color, STUDENTS[3].color];
const KIND_LABEL: Record<string, string> = {
  home_to_class: "to the first class",
  class_to_class: "between classes",
  class_to_home: "home",
};

function TripCell({ t, deadline }: { t: LegRow["trips"][string] | undefined; deadline: number | null }) {
  if (!t) return <td className="muted">–</td>;
  const via = t.board && t.alight ? ` ${placeName(t.board)} → ${placeName(t.alight)}` : "";
  return (
    <td>
      <div>
        <span className="dot" style={{ background: MODE_COLOR[t.mode] }} /> {MODE_LABEL[t.mode]}
        <span className="muted">{via}</span>
      </div>
      <div className="mono">
        {clock(t.depart)}–{clock(t.arrive)} · {duration(t.arrive - t.depart)}
      </div>
      <div className="muted mono">
        {t.wait > 0.5 ? `waits ${duration(t.wait)}` : ""}
        {t.late > 0 ? <span className="late"> late {duration(t.late)}</span> : deadline !== null ? ` ${duration(deadline - t.arrive)} early` : ""}
      </div>
    </td>
  );
}

export function StudentPanel({ replay }: { replay: Replay | null }) {
  const weekday = useApp((s) => s.playback.weekday);
  const student = useApp((s) => s.playback.student);
  const follow = useApp((s) => s.playback.follow);
  const pov = useApp((s) => s.playback.pov);
  const t = useApp((s) => Math.floor(s.playback.t / 60) * 60);
  const dir = replay?.files.students ?? null;
  const file = useStudents(dir, weekday);
  const [typed, setTyped] = useState("");

  const data = file.data;
  const scenarios = data?.header.scenarios ?? [];
  const arrays = data?.arrays as unknown as StudentArrays | undefined;
  const legs = useMemo(
    () => (data && arrays && student !== null ? studentLegs(arrays, data.header.keys, data.header.leg_kinds, scenarios, student) : []),
    [data, arrays, student, scenarios],
  );

  if (!replay) return <p className="muted">Open a week simulation to look at one student.</p>;
  if (!dir)
    return (
      <div className="muted">
        This replay has no student files yet.
        <Command lines={["uv run scripts/06_export_web.py --sim --showcase"]} />
      </div>
    );
  const pick = (id: number | null) => setPlayback({ student: id, follow: id !== null && follow });

  return (
    <div className="student-panel">
      <div className="student-pick">
        <button className="btn" disabled={!arrays} onClick={() => arrays && pick(randomStudent(arrays, true))} title="Someone who takes the metro today">
          Random metro rider
        </button>
        <button className="btn" disabled={!arrays} onClick={() => arrays && pick(randomStudent(arrays, false))}>
          Random student
        </button>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const v = Number(typed);
            if (Number.isInteger(v) && v >= 0) pick(v);
          }}
        >
          <input className="student-id mono" placeholder="no." value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Student number" />
        </form>
      </div>
      <p className="muted small">Or click a student in the view.</p>
      {file.loading && <p className="muted">Loading {WEEKDAYS[weekday - 1]}…</p>}
      {student !== null && data && (
        <>
          <div className="student-head">
            <strong>Student {student}</strong>
            <label className="check">
              <input type="checkbox" checked={follow} onChange={() => setPlayback({ follow: !follow })} /> follow with the camera
            </label>
            <button
              className={`btn ${pov ? "active" : ""}`}
              onClick={() => {
                if (!pov) app.set({ camera: "orbit" });
                setPlayback({ pov: !pov, follow: true, speed: pov ? 60 : 10 });
              }}
              title="See through their eyes: drag to look round, Esc to leave"
            >
              {pov ? "Leave their eyes" : "Be this student"}
            </button>
            <button className="link-button" onClick={() => setPlayback({ student: null, follow: false, pov: false })}>
              clear
            </button>
          </div>
          {legs.length === 0 ? (
            <p className="muted">No classes on {WEEKDAYS[weekday - 1]}.</p>
          ) : (
            <>
              <p className="student-now">
                {clock(t)}: {whereAt(legs, scenarios.includes("metro") ? "metro" : scenarios[0]!, t)}
              </p>
              <table className="measure-table student-totals">
                <thead>
                  <tr>
                    <th>{WEEKDAYS[weekday - 1]}</th>
                    {scenarios.map((sc) => (
                      <th key={sc} className="num">
                        {SCENARIOS[sc].label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["on the way", (x: ReturnType<typeof dayTotals>) => duration(x.travel)],
                      ["late", (x: ReturnType<typeof dayTotals>) => `${x.late} of ${x.n}`],
                      ["by metro", (x: ReturnType<typeof dayTotals>) => `${x.metro} legs`],
                    ] as const
                  ).map(([label, f]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      {scenarios.map((sc) => (
                        <td key={sc} className="num mono">
                          {f(dayTotals(legs, sc))}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <table className="student-legs">
                <thead>
                  <tr>
                    <th>leg</th>
                    {scenarios.map((sc) => (
                      <th key={sc}>{SCENARIOS[sc].label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {legs.map((l) => {
                    const first = l.trips.metro ?? l.trips[scenarios[0]!];
                    return (
                      <tr
                        key={l.leg}
                        className="student-leg"
                        title="Move the clock to this trip and follow the student"
                        onClick={() => first && setPlayback({ t: Math.max(0, first.depart - 60), follow: true, playing: false })}
                      >
                        <td>
                          <div>
                            {placeName(l.from)} → <strong>{placeName(l.to)}</strong>
                          </div>
                          <div className="muted">
                            {KIND_LABEL[l.kind] ?? l.kind}
                            {l.deadline !== null ? `, class ${clock(l.deadline)}` : ""}
                            {l.earliest !== null ? `, free from ${clock(l.earliest)}` : ""}
                          </div>
                          {l.trips.no_metro && l.trips.metro && (
                            <div className="mono small">
                              Δ {duration(Math.abs(l.trips.no_metro.arrive - l.trips.no_metro.depart - (l.trips.metro.arrive - l.trips.metro.depart)))}
                              {l.trips.no_metro.arrive - l.trips.no_metro.depart > l.trips.metro.arrive - l.trips.metro.depart ? " saved" : ""}
                            </div>
                          )}
                        </td>
                        {scenarios.map((sc) => (
                          <TripCell key={sc} t={l.trips[sc]} deadline={l.deadline} />
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}

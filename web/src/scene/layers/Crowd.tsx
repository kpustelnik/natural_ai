// Who is waiting for the metro and who is on board, as numbers in the view: one label above
// each station (students standing on its platform until their train) and one on each
// running train (riders nearest to it). Read from the students drawn last
// (registry.frames, written by Students), refreshed a few times a second.

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { Group } from "three";
import type { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { useMetro } from "../../data/resource";
import type { Metro } from "../../generated/schemas";
import { dayRuns, trainsAt } from "../../lib/metro";
import { METRO as METRO_MODE, type Paths, State } from "../../lib/trips";
import { app, useApp } from "../../state/app";
import { htmlLabel } from "../Css2d";
import { registry } from "../registry";

const REFRESH_MS = 250;
const MAX_TRAINS = 64;

/** Station index of each metro ride path (its first vertex is the boarding platform). */
function boardingStation(paths: Paths, metro: Metro, cache: Map<number, number>, p: number): number {
  const hit = cache.get(p);
  if (hit !== undefined) return hit;
  const o = 3 * paths.offsets[p]!;
  let best = -1;
  let dist = Infinity;
  metro.stations.forEach((s, i) => {
    const d = Math.hypot(paths.xyz[o]! - s.platform[0], paths.xyz[o + 2]! - s.platform[2]);
    if (d < dist) [best, dist] = [i, d];
  });
  cache.set(p, best);
  return best;
}

function setText(label: CSS2DObject, text: string, visible: boolean) {
  if (label.element.textContent !== text) label.element.textContent = text;
  label.visible = visible;
}

export function Crowd({ path, scenario }: { path: string; scenario: string }) {
  const metro = useMetro(path).data;
  const weekday = useApp((s) => s.playback.weekday);
  const show = useApp((s) => s.layers.counts);
  const day = useMemo(() => (metro ? dayRuns(metro, weekday) : null), [metro, weekday]);
  const group = useMemo(() => new Group(), []);
  const labels = useMemo(() => {
    if (!metro) return null;
    const stations = metro.stations.map((s) => {
      const l = htmlLabel("", "crowd-label");
      l.position.set(s.platform[0], s.platform[1], s.platform[2]); // under the building label
      return l;
    });
    const trains = Array.from({ length: MAX_TRAINS }, () => {
      const l = htmlLabel("", "crowd-label train-label");
      l.visible = false;
      return l;
    });
    return { stations, trains };
  }, [metro]);
  useEffect(() => {
    if (!labels) return;
    group.add(...labels.stations, ...labels.trains);
    return () => {
      group.remove(...labels.stations, ...labels.trains);
      for (const l of [...labels.stations, ...labels.trains]) l.element.remove();
    };
  }, [group, labels]);

  const cache = useRef(new Map<number, number>());
  const last = useRef({ time: 0, t: -1 });
  useEffect(() => {
    cache.current = new Map();
  }, [metro, weekday]);

  useFrame(() => {
    if (!metro || !day || !labels) return;
    const now = performance.now();
    const t = app.get().playback.t;
    if (now - last.current.time < REFRESH_MS || t === last.current.t) return;
    last.current = { time: now, t };
    const fr = registry.frames[scenario];
    const waiting = new Array<number>(metro.stations.length).fill(0);
    const trains = trainsAt(metro, day, t);
    const aboard = new Array<number>(trains.length).fill(0);
    if (fr) {
      const { paths, day: d, frame: f } = fr;
      for (let i = 0; i < f.n; i++) {
        const s = f.state[i];
        if (s === State.Wait) {
          const nx = d.next[f.row[i]!]!;
          if (nx >= 0 && paths.mode[d.path[nx]!] === METRO_MODE) waiting[boardingStation(paths, metro, cache.current, d.path[nx]!)]!++;
        } else if (s === State.Metro && trains.length) {
          let best = 0;
          let dist = Infinity;
          for (let k = 0; k < trains.length; k++) {
            const p = trains[k]!.position;
            const dd = Math.hypot(f.xyz[3 * i]! - p[0], f.xyz[3 * i + 2]! - p[2]);
            if (dd < dist) [best, dist] = [k, dd];
          }
          aboard[best]!++;
        }
      }
    }
    labels.stations.forEach((l, i) => setText(l, `${metro.stations[i]!.building_id} · ${waiting[i]} waiting`, true));
    labels.trains.forEach((l, k) => {
      const tr = trains[k];
      if (!tr) return setText(l, "", false);
      l.position.set(tr.position[0], tr.position[1] + 6, tr.position[2]);
      setText(l, `${aboard[k]} on board`, true);
    });
  });

  return <primitive object={group} visible={show} />;
}

// Frame-rate probe (the ` key, or #perf=1 / #perf=log): frames per second, the slowest
// frame, draw calls and triangles of the last second, in registry.perf for the overlay.
// With perf=log every second is also printed to the console, for measuring in a headless
// browser.

import { useFrame, useThree } from "@react-three/fiber";
import { useRef } from "react";
import { app } from "../state/app";
import { registry } from "./registry";

export function PerfProbe() {
  const gl = useThree((s) => s.gl);
  const acc = useRef({ start: performance.now(), last: performance.now(), frames: 0, worst: 0 });
  useFrame(() => {
    const now = performance.now();
    const a = acc.current;
    a.frames++;
    a.worst = Math.max(a.worst, now - a.last);
    a.last = now;
    if (now - a.start < 1000) return;
    const s = app.get();
    const students = Object.values(registry.onScreen).reduce((n, c) => n + c[0] + c[1] + c[2] + c[3], 0);
    registry.perf = {
      fps: (1000 * a.frames) / (now - a.start),
      worstMs: a.worst,
      calls: gl.info.render.calls,
      triangles: gl.info.render.triangles,
      students,
    };
    if (s.perf === "log") {
      const p = registry.perf;
      console.log(
        `[perf] t=${Math.round(s.playback.t)} fps=${p.fps.toFixed(1)} worst=${p.worstMs.toFixed(1)}ms calls=${p.calls} tris=${p.triangles} students=${students}`,
      );
    }
    a.start = now;
    a.frames = 0;
    a.worst = 0;
  });
  return null;
}

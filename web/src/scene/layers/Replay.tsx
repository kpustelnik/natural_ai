// What the open replay draws in the Metro and Simulation workspaces:
// - an ACO run in the "ants" view: candidates, pheromone, the sampled ants, the best line;
// - the trains view of an ACO run, and every simulation: the line underground (shafts,
//   platforms, tunnel) with its trains on the day clock. The ground turns see-through.

import { useReplays } from "../../data/resource";
import type { Replay, Scene } from "../../generated/schemas";
import { useApp } from "../../state/app";
import { AcoLayer } from "./AcoTrace";
import { MetroLayer } from "./Metro";

export function useOpenReplay(scene: Scene): Replay | null {
  const id = useApp((s) => s.playback.replayId);
  const catalog = useReplays(scene.replays).data;
  return catalog?.replays.find((r) => r.id === id) ?? null;
}

type ReplayView = "ants" | "line" | null;

export function useReplayView(scene: Scene): { replay: Replay | null; view: ReplayView } {
  const replay = useOpenReplay(scene);
  const workspace = useApp((s) => s.workspace);
  const acoView = useApp((s) => s.playback.acoView);
  if (!replay || (workspace !== "metro" && workspace !== "simulation")) return { replay, view: null };
  if (replay.kind === "aco" && acoView === "ants") return { replay, view: replay.files.aco_trace ? "ants" : null };
  return { replay, view: replay.files.metro ? "line" : null };
}

export function ReplayLayers({ scene }: { scene: Scene }) {
  const { replay, view } = useReplayView(scene);
  if (!replay || !view) return null;
  return view === "ants" ? <AcoLayer path={replay.files.aco_trace!} /> : <MetroLayer path={replay.files.metro!} />;
}

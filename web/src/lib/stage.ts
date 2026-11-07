// Project stages for the site: `#stage=1` shows the viewer as it was at the intermediate
// presentation (stage 1: data, the first ACO runs, the week simulation), without what came
// in stage 2 (experiment charts in the viewer: live charts and the Stats tab; the other
// algorithms' and lines' replays). Without the parameter everything is shown (stage 2).

import type { Replay } from "../generated/schemas";

export type Stage = 1 | 2;

/** Replays of stage 1: MMAS without local search (k = 5), its week, ACO level 1. */
export const STAGE1_REPLAYS = new Set([
  "aco-showcase-mmas-k5-mmas-k5-s42",
  "sim-showcase-mmas-k5-mmas-k5-s42",
  "walk-s42",
]);

export function inStage(replay: Replay, stage: Stage): boolean {
  return stage === 2 || STAGE1_REPLAYS.has(replay.id);
}

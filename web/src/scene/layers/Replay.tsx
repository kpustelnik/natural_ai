// What the open replay draws in the Metro and Simulation workspaces:
// - an ACO run in the "ants" view: candidates, pheromone, the sampled ants, the best line;
// - the trains view of an ACO run, and every simulation: the line underground (shafts,
//   platforms, tunnel) with its trains on the day clock. The ground turns see-through;
// - a simulation also draws its students, of one scenario or, in the split view, of both
//   (no metro on the left half, with metro and the line on the right);
// - a walk run (ACO level 1): the walk graph's loaded segments and the sampled ants.

import { useReplays } from "../../data/resource";
import type { Replay, Scenario, Scene } from "../../generated/schemas";
import { splitActive, useApp } from "../../state/app";
import { AcoLayer } from "./AcoTrace";
import { Crowd } from "./Crowd";
import { MetroLayer } from "./Metro";
import { Students } from "./Students";
import { WalkLayer } from "./WalkAco";

export function useOpenReplay(scene: Scene): Replay | null {
  const id = useApp((s) => s.playback.replayId);
  const catalog = useReplays(scene.replays).data;
  return catalog?.replays.find((r) => r.id === id) ?? null;
}

type ReplayView = "ants" | "line" | "walk" | null;

/** The scenario a simulation shows outside the split view: the chosen one, if exported. */
function shownScenario(replay: Replay, scenario: Scenario): Scenario | undefined {
  const trips = replay.files.trips;
  return trips[scenario] ? scenario : (Object.keys(trips) as Scenario[])[0];
}

function useSplit(replay: Replay | null): boolean {
  return useApp((s) => splitActive(s) && !!replay?.files.trips.no_metro && !!replay.files.trips.metro);
}

export function useReplayView(scene: Scene): { replay: Replay | null; view: ReplayView } {
  const replay = useOpenReplay(scene);
  const workspace = useApp((s) => s.workspace);
  const acoView = useApp((s) => s.playback.acoView);
  const scenario = useApp((s) => s.playback.scenario);
  const split = useSplit(replay);
  if (!replay || (workspace !== "metro" && workspace !== "simulation")) return { replay, view: null };
  if (replay.kind === "walk") return { replay, view: replay.files.walk_trace ? "walk" : null };
  if (replay.kind === "aco" && acoView === "ants") return { replay, view: replay.files.aco_trace ? "ants" : null };
  // a simulation without the metro scenario on show draws no line
  if (replay.kind === "simulation" && !split && shownScenario(replay, scenario) === "no_metro") return { replay, view: null };
  return { replay, view: replay.files.metro ? "line" : null };
}

function SimulationLayers({ replay }: { replay: Replay }) {
  const split = useSplit(replay);
  const scenario = useApp((s) => s.playback.scenario);
  const trips = replay.files.trips;
  const metro = replay.files.metro;
  if (split) {
    return (
      <>
        <Students key="left" dir={trips.no_metro!} scenario="no_metro" side="left" />
        <Students key="right" dir={trips.metro!} scenario="metro" side="right" />
        {metro && <MetroLayer path={metro} side="right" />}
      </>
    );
  }
  const shown = shownScenario(replay, scenario);
  return (
    <>
      {shown && <Students key={shown} dir={trips[shown]!} scenario={shown} side={null} />}
      {metro && shown !== "no_metro" && <MetroLayer path={metro} side={null} />}
      {metro && shown === "metro" && <Crowd path={metro} scenario="metro" />}
    </>
  );
}

export function ReplayLayers({ scene }: { scene: Scene }) {
  const { replay, view } = useReplayView(scene);
  const shown = useApp((s) => s.workspace === "metro" || s.workspace === "simulation");
  if (!replay || !shown) return null;
  if (replay.kind === "simulation") return <SimulationLayers replay={replay} />;
  if (!view) return null;
  if (view === "walk") return scene.network ? <WalkLayer path={replay.files.walk_trace!} network={scene.network} /> : null;
  return view === "ants" ? <AcoLayer path={replay.files.aco_trace!} /> : <MetroLayer path={replay.files.metro!} side={null} />;
}

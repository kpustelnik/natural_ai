# Architecture: what is where

A map of the code for making a change without reading everything first. Formats live in
[docs/data_contracts.md](docs/data_contracts.md), the viewer's design and phase notes in
[docs/viewer_plan.md](docs/viewer_plan.md), commands in [README.md](README.md). This file
names files and functions, not line numbers, so it stays true as the code moves.

**Keep it current:** when you add, move or rename a file or a main function, update its line
here in the same change.

## The big picture

```
data/campus/*.yaml, campus.yaml ─┐
OSM (02_build_campus) ───────────┤
USOS (01_fetch_usos) ────────────┼─► data/processed/  (usos/, transit/, gpkg, network/,
GTFS (01_fetch_transit) ─────────┘     population/, demand/, simulation/, fake/)
                                            │  03_build_demand: usos + campus -> legs, od
                                            ▼
                    06_export_web.py ─► web/public/data/  (scene.json, glb, network.bin, replays/)
                                            │
                                            ▼
                    web/ (React + three.js) reads only these files, computes nothing heavy
```

- **Python is the only geometry and data builder.** The browser never reads YAML or parquet.
- **Contracts:** pydantic models in `src/metro_agh/schemas/` → `schemas/*.schema.json` →
  `web/src/generated/schemas.ts` (generated, never edit by hand).
- **Coordinates:** EPSG:2180 in Python, the "web frame" in every exported file
  (x = east, y = up, z = −north, metres from `campus.web_origin`).

## Configuration and data

| path | what |
|---|---|
| `config.yaml` | every parameter (paths, campus bbox, time model, metro, ACO, population). Comments are Polish |
| `data/campus/buildings/*.yaml` | hand-modelled buildings (89, mostly LOD1; U-13 from `osm_building_map.csv`) |
| `data/campus/campus.yaml` | passages, extra paths, removed ways, stops with weights |
| `data/campus/osm_building_map.csv`, `usos_room_map.csv` | hand-written mappings (USOS building ids: `aliases` in the building YAML) |
| `data/campus/campus.yaml` `stops` | the 12 stops from GTFS (`01_fetch_transit.py --print-yaml`) |
| `data/sample/campus/` | 5 buildings with interiors (D-17 is LOD3, A-0 is LOD2): use `--sample` |
| `data/processed/` | generated, gitignored: `osm/campus.gpkg`, `network/*.parquet`, `fake/…` |
| `web/public/data/` | generated, gitignored: everything the viewer loads |

## Python: `src/metro_agh/`

### Shared

| file | contents |
|---|---|
| `config.py` | `load_config`, `path(cfg, key)` (repo-absolute paths), `provenance`, `ROOT` |
| `schemas/tables.py` | every table contract (`Table`, `Column`): `GRAPH_NODES/EDGES`, `LEGS`, `SIM_LEGS`, `METRO_SCHEDULE`, `CONVERGENCE`, `OSM_*` …; `Table.read/write/validate` |
| `schemas/common.py` | enums (`NodeKind`, `LegKind`, `Scenario`, `Mode`, …), id patterns |
| `schemas/building.py`, `campus.py` | YAML models (`load_building`, `Campus`) |
| `schemas/instance.py`, `results.py` | ACO instance (`Instance`), results (`RunMeta`, `BestLine`, `AcoTrace`) |
| `schemas/web.py` | **every viewer file format** (`Scene`, `BuildingInfo`, `NetworkHeader`, `Metro`, `PathsHeader`, `DayHeader`, `AcoTraceHeader`, `Stats`, `Replay`, …) |
| `schemas/export.py` | `python -m metro_agh.schemas.export`: models → `schemas/*.json` |

### USOS (stage 1): `usos/`

| file | contents |
|---|---|
| `usos/http.py` | `CachedHttp` (polite GET with a disk cache in `data/raw/usos/`: expiry per kind `max_age_s` from `usos.cache_days`, `refresh`, `offline`, request budget, old copy when a refetch fails), `OfflineMiss` |
| `usos/pages.py` | pure parsers of public USOSweb pages: `parse_room_week` (`Tile`), `parse_unit_groups` (`UnitPage`, `GroupRow`, `Meeting`), `parse_course` (`CoursePage`, `CourseGroup`), `parse_faculty_groups`, `parse_group_courses`; `parity_of`, `weekday_of`, `cohort_of` |
| `usos/fetch.py` | `crawl` (rooms -> room plans -> courses -> class groups, one term; `full=True`: + every unit's catalogue and dated meetings) -> `Crawl`; `fetch_rooms`, `fetch_terms`, `fetch_faculties`, `fetch_catalogue`, `fetch_meetings` (`tt/classgroups`) |
| `usos/full.py` | `full_tables` (Crawl -> `FullTables`: course_groups, courses, class_groups, meetings in `usos/all/`) |
| `usos/parse.py` | `build_tables` (Crawl -> `UsosTables`: timetable, groups with sizes, cohorts, group_cohorts, rooms); `group_ids`, `building_resolver`, `room_key`, `semester_of`, `study_level` + `pool_members` (courses in no cohort -> `pool:1S`) |

### Public transport: `transit/`

| file | contents |
|---|---|
| `transit/gtfs.py` | `download`, `services_on`, `default_date`, `campus_transit` (campus stops with peak arrivals and weights, direct rides between them, every single ride), `campus_yaml_stops` |

### Demand (stage 3): `demand/`

| file | contents |
|---|---|
| `demand/dorms.py` | `estimate_dorms` (beds per dorm: YAML `residents`, else `population.dorm_beds` by floor area) |
| `demand/population.py` | `synthesize` (students per cohort, homes, course take-up, dean's-group quantile, clash-free group choice), `calendar_slots` + `busiest_week` (a real week from `meetings.csv`), `modelled_slots` (typical week), `Homes` |
| `demand/legs.py` | `build_legs` (section 5.4 rules), `resolve_keys` (room or building endpoint), `od_matrix`, `migrations` (flows between buildings per weekday and hour) |

### Campus and OSM (stage 2)

| file | contents |
|---|---|
| `campus/osm.py` | Overpass download with cache (`fetch`) |
| `campus/osm_process.py` | OSM → layers (`build_layers`: buildings, entrances, stops, barriers, boundary, walk graph), `Issues` |
| `campus/osm_report.py` | `report.md`, `issues.json`, `preview.html` |
| `campus/bootstrap.py` | LOD1 building YAML skeletons from OSM (`--bootstrap`) |
| `campus/geo.py` | `to_metric`, `to_geo`, `LocalFrame` (building local ↔ EPSG:2180) |

### Geometry (YAML → meshes, no I/O)

| file | contents |
|---|---|
| `geometry/building.py` | `place` (YAML → `PlacedBuilding`: levels, entrances, frame), `lod1_meshes`, `match_osm`, `osm_index` |
| `geometry/interior.py` | LOD2/3: `plan_levels` (rooms, corridors, doors, stairs), `interior_meshes` (walls with door gaps, slabs, flights), `shaft_lines` |
| `geometry/mesh.py` | `TriMesh`, `Lines`, `web()` (EPSG:2180 → web), `flat`, `prism`, `walls`, `outline`, `polyline` |

### Walk network (stage 2b)

| file | contents |
|---|---|
| `network/indoor.py` | one building's graph: `building_part` (corridor chains, rooms, stairs, entrances, shaft → platform), `TimeModel`, `GraphIssue`, `Part` |
| `network/graph.py` | `outdoor_part` (OSM paths), `passage_part`, `stop_part`, `assemble` (links, dedupe, issues), `build_campus_graph`, `Graph.write` |
| `network/instance.py` | `build_instance`, `write_instance` (network + OD → `instance/instance.npz`); `load_or_build` (rebuilds when `inputs_hash` changed), `with_config` / `metro_meta` (k, speed, dwell, headway, shafts from the current config), `transit_rides` (no-metro time = min(walk, bus / tram)) |

### ACO (stage 4): `aco/`

| file | contents |
|---|---|
| `aco/objective.py` | `Objective` (weighted Σ min(walk, metro) over OD pairs; cache keyed by `canonical`: a reversed line / rotated loop is one line) |
| `aco/mmas.py` | `run_mmas` → `MmasResult` (best line, convergence, trace) |
| `experiments.py` | parameter sweeps / ablations: `load_experiment`, `expand_jobs`, `execute_job`, `summarise`, `append_runs_csv` |

### Simulation (stage 5)

| file | contents |
|---|---|
| `simulation/schedule.py` | train timetable: `build_schedule`, `station_order`, `run_times`, `hhmm` |
| `simulation/simulate.py` | `simulate` (both scenarios: Dijkstra per origin in batches; walk vs bus / tram (`Transit`) vs metro (`Line`), each a timetabled `_Net` boarded via `Connections.earliest/latest` in `_best_rides`), `load_transit`, `run_simulation` (reads a processed dir, writes schedule + legs) |

### Web export (stage 6): `web/`

| file | contents |
|---|---|
| `web/export_campus.py` | `CampusExport` (`full`, `update` for watch mode, `_building`, `_network`); `export_context`, `export_ground`, `export_network`, `export_stops`, `export_aerial`, `write_replay_catalog`, `write_status_file` |
| `web/export_demand.py` | `load_web_graph`, `edge_loads_from_od`, `export_demand` (OD → shortest-path edge loads on `network.json`) |
| `web/export_metro.py` | `export_aco_run` (`--aco` → `replays/aco-<run>/`), `export_best_line` (`--metro` → `replays/sim-<run>/metro.json`), `metro_model`, `shafts`, `load_scene` |
| `web/export_sim.py` | `export_simulation` (`--sim`: `trips/<scenario>/paths.*`, `day-N.*`, `stats.json`), `PathBuilder` (node paths → web polylines with times), `stats` |
| `web/fake.py` | `--fake`: `fake_instance` + `mmas` (synthetic ACO run on `aco.objective.Objective`), `fake_population` (students, legs), `write_fake_results`, `write_fake_simulation` |
| `web/gltf.py` | minimal GLB writer (`Node`, `write_glb`) |
| `web/binary.py` | header `.json` + `.bin` containers (`write_binary`, `pack`) |
| `web/watch.py` | `--watch` polling loop → `CampusExport.update` |
| `web/yaml_errors.py` | pydantic errors → YAML line numbers |
| `web/aerial.py` | GUGiK orthophoto download (`--aerial`) |

### Scripts and tests

| file | contents |
|---|---|
| `scripts/01_fetch_usos.py` | crawl + `build_tables` -> `usos/*.csv`, + `full_tables` -> `usos/all/*.csv` (`--campus-only`, `--buildings`, `--offline`, `--refresh`, `--max-requests`) |
| `scripts/01_fetch_transit.py` | GTFS -> `transit/stops.csv`, `rides.csv`, `trips.parquet` (`--print-yaml` for campus.yaml) |
| `scripts/02_build_campus.py` | OSM layers, report, `--bootstrap`, then `network/*.parquet` |
| `scripts/03_build_demand.py` | dorms, population, legs, OD, migrations for a calendar week (`--week`, default busiest; `--typical`); rooms when `network/nodes.parquet` exists |
| `scripts/plot_experiments.py` | `runs.csv` -> `docs/figures/<experiment>.png` + `.csv` (saving vs k) |
| `experiments/configs/k_sweep.yaml` | k = 2 … 10 × 5 seeds on the USOS demand |
| `scripts/04_optimize.py` | build/load instance, `run_mmas`, write `results/<run_id>/` + `best_line.json` |
| `scripts/run_experiments.py` | YAML sweep / ablation → many runs + `runs.csv` + `summary_<name>.csv` |
| `scripts/05_simulate.py` | stage 5 on `data/processed` |
| `scripts/06_export_web.py` | flags `--campus --sample --watch --aerial --aco --metro --sim --fake`; `export_replays` (+ `export_demand`) |
| `experiments/configs/*.yaml` | experiment specs (`aco_ablation.yaml`, `aco_grid.yaml`): mode, seeds, sweep / variants |
| `tests/test_web_export.py` | fixture `exported` (sample campus + synthetic OSM in a temp dir), used by the other export tests |
| `tests/test_network.py`, `test_interior.py`, `test_osm.py`, `test_schemas.py` | graph, geometry, OSM, contracts |
| `tests/test_aco.py` | toy-instance objective + MMAS |
| `tests/test_usos_http.py` | cache expiry, refresh, offline, failed refetch |
| `tests/test_usos.py` (+ `tests/fixtures/usos/*.html`) | USOSweb parsers on trimmed pages, ids, parity, semesters, `build_tables`, size fallbacks, catalogue pages, `full_tables` |
| `tests/test_demand.py` | dorm beds, population on `data/sample/usos`, legs rules, OD, migrations |
| `tests/test_transit.py` | GTFS stops / rides on a synthetic feed |
| `tests/test_experiments.py` | experiment YAML expansion + `runs.csv` append, `metro.*` overrides reach the run |
| `tests/test_metro_export.py`, `test_simulation.py` | schedule, ACO / line replays, simulator, `--sim` export |

## Viewer: `web/src/`

Data flows one way: **files → `data/` hooks → `scene/` layers**. UI and scene talk only
through the store (`state/app.ts`). Values read every frame (clock, iteration) are read with
`app.get()` inside `useFrame`, not through React state.

### Shell, state, data

| file | contents |
|---|---|
| `App.tsx` | layout (top bar, panels, viewport, dock, status bar), **all keyboard shortcuts** (`useShortcuts`), presentation mode, the "no data" screen |
| `state/app.ts` | the store: `AppState`, workspaces, `LAYER_GROUPS` + `WORKSPACE_LAYERS` (default layers per workspace), `Pick` (selection kinds), `Playback`, actions (`select`, `setPlayback`, `setRouteEnd`, `focusBox`, `toast`, `splitActive`, …) |
| `state/url.ts` | store ↔ `location.hash` (`stateFromHash`, `writeHash`): add new URL params here |
| `state/store.ts` | the tiny external store (`createStore`, `useSlice`) |
| `data/loader.ts` | `fetchJson`, `loadBinary` (typed-array views), `MissingDataError` |
| `data/resource.ts` | cached hooks: `useScene`, `useNetwork`, `useMetro`, `useAcoTrace`, `useTrips`, `useStats`, `useDemand`, …; `invalidate`, `useLoading`, the missing-file toast |
| `data/live.ts` | live reload: `status.json` → refetch changed files |
| `data/network.ts` | network index and routing helpers (`computeRoute`, `useRoute`, `resolveKey`, `nearestNode`) |
| `generated/schemas.ts` | generated TS types (`npm run gen:types`) |

### Pure logic (`lib/`, unit-tested)

| file | contents |
|---|---|
| `lib/frames.ts` | web ↔ lon/lat ↔ building local |
| `lib/graph.ts` | Dijkstra on the CSR graph, route summary (legs, outdoor / indoor / stairs) |
| `lib/metro.ts` | train positions from the timetable (`trainsAt`), ACO sample interpolation (`sampleAt`, `curveAt`) |
| `lib/trips.ts` | students: `prepareDay`, `studentsAt` (who is where at t; any non-walk path is a ride: metro or bus / tram), `spiral` (crowd layout), `peakCount` |
| `lib/search.ts`, `lib/format.ts` | search ranking; number / time / duration formatting, `WEEKDAYS` |

### 3D scene (`scene/`)

| file | contents |
|---|---|
| `scene/Viewport.tsx` | the `<Canvas>`, lights, **which layers are mounted when**, pointer interaction (hover, select, measure, route clicks, Alt-capture) |
| `scene/CameraRig.tsx` | orbit / plan cameras, framing flights (`ANIM_MS`), view reporting (azimuth, metres per pixel), split-view projection |
| `scene/WalkRig.tsx` | first-person walk camera with collisions |
| `scene/palette.ts` | **every colour** of the scene: categories, LOD, demand edge heatmap, network kinds, route parts, `METRO`, `STUDENTS`, `SCENARIOS`, markers; `indexDemand`, `demandColour` |
| `scene/registry.ts` | loaded things non-scene code needs (`scene`, `network`, `infos`, split sides, `onScreen` counts, `perf`, `canvas`), `pickBox` |
| `scene/picking.ts`, `bvh.ts`, `useGlb.ts` | hit → `Pick`, BVH setup, GLB loading |
| `scene/Css2d.tsx` | one CSS2DRenderer for all HTML labels (`htmlLabel`) |
| `scene/SplitView.tsx` | split view: `SplitRenderer` (two passes), `splitEvents` (pointer mapping) |
| `scene/PerfProbe.tsx` | fps / draw calls into `registry.perf`, `perf=log` console lines |
| `scene/screenshot.ts` | PNG of the canvas + redrawn labels |
| `scene/tools/Tools.tsx`, `snap.ts` | measure and capture drawings, point snapping |

Layers (`scene/layers/`):

| file | draws |
|---|---|
| `Buildings.tsx` | AGH buildings: materials, colour modes (muted under Demand), ghosting, level isolation and section cut (`SECTION_HEIGHT`) |
| `Context.tsx` | the merged context buildings (one mesh) |
| `Ground.tsx`, `Aerial.tsx` | ground plate, paths, boundary, fences (`seeThrough` for the metro); orthophoto |
| `Labels.tsx` | building and stop labels with collision culling |
| `BuildingHelpers.tsx` | `RoomLabels`, `BuildingGrid`, `OsmOutline` |
| `Markers.tsx` | `Entrances`, `Stops`, `Barriers` (`MarkerSet`) |
| `Network.tsx`, `Route.tsx` | walk graph lines (kind or Demand edge-load colours; clipped at the active level); the route line |
| `Replay.tsx` | what a replay draws per workspace (`useOpenReplay`, `useReplayView`, `ReplayLayers`, `SimulationLayers`) |
| `AcoTrace.tsx` | ACO player: candidate pins, pheromone ribbons, ants, best line |
| `Metro.tsx` | shafts, platforms, tunnel, trains |
| `Students.tsx` | students (InstancedMesh, per-frame CPU update, colour by state) |

### UI (`ui/`)

| file | contents |
|---|---|
| `TopBar.tsx` | panel toggles, workspace tabs, search, replay menu |
| `LeftPanel.tsx` | layer checkboxes (`Layers`) and the building outliner (`Outliner`, `BuildingRow`, `LevelRow`) |
| `RightPanel.tsx` | playback dock (`Timeline`) when a replay is open; tabs Inspector / Issues / Route / Stats; `BuildingInspector`, `SpaceInspector`, edge / barrier inspector in `Inspector`, `IssuesPanel` |
| `RoutePanel.tsx` | route tool tab: ends, totals, legs, field measurements |
| `StatsPanel.tsx` | simulation stats tab: totals, `HourChart`, `Stations`, `TopOd` |
| `ViewportOverlay.tsx` | over the 3D view: camera / colour mode buttons, tool buttons, `Compass`, view actions (screenshot, presentation, help), `LevelStepper`, legends, `ScaleBar`, measure / capture panels, `NoReplay` empty state, split captions, `PerfPanel`, `Toasts`, presentation overlay |
| `Timeline.tsx` | the playback dock (mounted in `RightPanel`): `Dock`, `DayControls` (clock, speed, weekday, scenario / split), `AntControls` (iteration player), `StudentLegend`, speed presets |
| `ConvergenceChart.tsx` | ACO convergence chart (SVG) |
| `ReplayMenu.tsx` | replay menu, `openReplay` (sets workspace, opens right panel, speed, scenario) |
| `Search.tsx` | search box |
| `StatusBar.tsx` | build status, loading count, cursor coordinates, shortcuts button |
| `HelpDialog.tsx` | keyboard help (`GROUPS`; update it when you add a shortcut) |
| `Command.tsx` | copyable command box, `commandFor(path)` (missing file → export command) |
| `icons.tsx` | inline SVG icons (`icon()` helper) |

### Styles

`theme.css`: design tokens in `:root` (colours, `--muted`, sizes), then sections marked
`/* --- … --- */`: layout, top bar, menu, panels, segmented controls, viewport overlays,
playback dock, messages, then one section per phase (building tools, route / ACO, simulation,
finish: focus rings, modal, presentation, spinner). Search for the class name used in the TSX.

## Common changes: where to go

| change | files |
|---|---|
| a colour in 3D | `scene/palette.ts` |
| a UI colour, spacing or font | `theme.css` tokens in `:root`, or the section of that component |
| a new keyboard shortcut | `App.tsx` `useShortcuts`, plus `ui/HelpDialog.tsx` and the README shortcuts line |
| a new layer toggle | `state/app.ts` (`LayerId`, `LAYER_GROUPS`, `BASE`, `WORKSPACE_LAYERS`), mount in `scene/Viewport.tsx` |
| default layers of a workspace | `state/app.ts` `WORKSPACE_LAYERS` |
| inspector content | `ui/RightPanel.tsx` (`BuildingInspector`, `SpaceInspector`, `Inspector`) |
| dock / playback controls, speeds | `ui/Timeline.tsx` |
| a new URL parameter | `state/url.ts` (`stateFromHash`, `writeHash`, and the change test in `bindUrl`) |
| student size / colour / crowd spread | `scene/layers/Students.tsx` (`MIN_R`, `PX_R`, `SPACING`), colours in `palette.ts` `STUDENTS` |
| a new field in an exported file | `schemas/web.py` → `python -m metro_agh.schemas.export` → `npm run gen:types` → the exporter in `web/export_*.py` → `docs/data_contracts.md` section 10 |
| how walking times are computed | `network/indoor.py` `TimeModel`, `network/graph.py`, `config.yaml` `time_model` |
| metro / bus choice in the simulation | `simulation/simulate.py` (`simulation.transit` turns buses off) |
| synthetic data for the viewer | `web/fake.py` |
| a USOSweb page changed its HTML | `usos/pages.py` (+ the trimmed page in `tests/fixtures/usos/`) |
| a USOS building id maps wrongly | `aliases:` in that building YAML; single rooms: `usos_room_map.csv` |
| group size / cohort size rules | `usos/parse.py` (`_sizes`, `_cohorts`) |
| who takes which group | `demand/population.py` (`synthesize`, `_pick`) |
| stops and their weights | `scripts/01_fetch_transit.py --print-yaml` -> `campus.yaml` `stops` |

## Checks before finishing

```bash
uv run pytest -q && uv run ruff check src scripts tests && uv run ruff format --check src scripts tests
cd web && npx tsc --noEmit && npm test && npm run build
```

# Browser viewer: implementation plan

Status: **phases 0 to 7 are implemented** (2026-10-09), 5 and 6 on synthetic data (`--fake`); the
frame-rate target of phase 6 is not measured yet (see its notes).
Where the implementation differs from the plan below, the phase notes in
[section 7](#7-phases) say so.
Formats are defined in [data_contracts.md](data_contracts.md), section 10. The contract
changes of [section 4](#4-contract-changes) are in place.

## 1. Goals

The viewer has two jobs, in this order:

1. **Review and modelling tool.** You can see everything the pipeline produced (OSM layers,
   bootstrapped buildings, the walk and indoor graphs) and edit building YAMLs in VS Code
   with the result visible about a second after saving. It also gives you what you need to
   model: local coordinates under the cursor, a measure tool, a grid in the building's
   frame, floor plans per level, the OSM outline next to your footprint, and validation
   errors.
2. **Presentation of results.** Metro stations, shafts, tunnel and trains, the ACO run with
   ants and pheromone, and the 20,000 students for a whole day, both scenarios, with stats.

Decisions already made:

| topic | decision |
|---|---|
| geometry | **Python is the only geometry builder.** YAML → `metro_agh.geometry` → GLB + indoor graph. The browser never interprets YAML. A watch mode rebuilds on save. |
| editing | Inspect + modelling helpers; the YAML stays hand-written in VS Code. No in-browser editor. |
| stack | React 19, three.js 0.186 via React Three Fiber, three-mesh-bvh, TypeScript 7, Vite. No drei. Helpers come from `three/addons`. |
| language | English UI. |
| look | Clean architectural: flat colours, thin dark edges, one light grey ground, no gradients, no textures (except the optional aerial underlay), no glow effects. |

Non-goals for v1: an in-browser editor, a mobile layout beyond "usable", VR, terrain.

## 2. User experience

### 2.1 Layout

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Metro AGH   Campus · Building · Network · Metro · Simulation   [ search D-17/1.38 ]│  top bar 44px
├─────────────┬──────────────────────────────────────────────────────┬─────────────┤
│ LAYERS      │                                                      │ INSPECTOR   │
│ ☑ AGH bldgs │                                                      │ D-17        │
│ ☑ Context   │                                                      │ academic ·  │
│ ☐ Aerial    │                    viewport                          │ LOD3        │
│ ☑ Walk net  │                                                      │ levels 0–4  │
│ ☐ Fences    │                                          ┌──────┐    │ entrances 2 │
│ ...         │                                          │  N   │    │ ──────────  │
│ OUTLINER    │                                          │compas│    │ placement   │
│ ▸ A-0       │  [orbit][top][walk]   [level ▴ 1 ▾]      └──────┘    │ anchor ...  │
│ ▾ D-17      │                                                      │ bearing 72° │
│   ▸ L0      │                                                      │ [Open YAML] │
│   ▾ L1      │                                        0   50 m      │ issues (1)  │
│     1.38    │                                                      │             │
├─────────────┴──────────────────────────────────────────────────────┴─────────────┤
│ ● data v12 built 14:02:11 │ cursor 50.06712 N 19.91234 E │ D-17 local (12.4, 3.1) L1 │  status bar 28px
└──────────────────────────────────────────────────────────────────────────────────┘
```

- **Top bar**: workspace tabs, a search box that accepts building ids, room keys
  (`D-17/1.38`), stop ids and OSM ids (`way/123`) with fuzzy matching on names, and the
  **Replays menu**.
- **Replays menu**: lists every exported optimisation run and simulation
  (`replays/index.json`, contract 10.10), grouped by kind, with date, topology, stations,
  scenarios and weekdays. Choosing one switches to the Metro (ACO) or Simulation workspace
  and opens the playback dock. *Close replay* returns to the campus.
- **Left sidebar** (collapsible): *Layers* (visibility toggles, grouped) and *Outliner*
  (tree: building → level → corridors / rooms / stairs / entrances).
- **Right sidebar** (collapsible): *Inspector* for the current selection, plus *Issues*.
- **Viewport overlays**: camera mode switch, level stepper, compass (click: north up),
  scale bar, and a small toast area for reloads and errors.
- **Status bar**: data build status (green, amber while building, red with an error),
  cursor position as lon/lat, as web coordinates, and in the hovered building's local
  frame with its level.
- **Playback dock** (when a replay is open): play/pause, speed, time (simulation: 06:00 to
  22:00; ACO: iteration), weekday and scenario, and later a small per-hour chart. The clock
  lives in the store, and the metro, ant and student layers read it every frame.

Visual rules: Inter-like system font stack (`system-ui`), 13px base size, 1px `#d0d4d9`
borders, 4px radius, white panels on a `#f4f5f6` ground, a single accent colour (`#c8102e`,
also the metro line), and neutral greys everywhere else. Category colours appear only as
small swatches and as subtle tints on AGH buildings. Icons are inline SVG in
`ui/icons.tsx` (no icon library), and both sidebars can be hidden for clean screenshots
(`\` key).

### 2.2 Workspaces

The workspaces share one viewport, one scene and one selection. A workspace only picks the
default layers, the panels and the bottom dock.

| workspace | shows | for |
|---|---|---|
| **Campus** | all buildings (AGH tinted, context grey), ground with paths, stops, boundary, entrances; issues list | reviewing OSM and the bootstrap, navigating |
| **Building** | one building isolated (others ghosted at 15 %), level stepper, floor-plan view, room labels, building grid, OSM outline, local coordinate readout, measure | modelling |
| **Network** | walk graph (steps highlighted), barriers, fences, indoor graph, passages; route tool between two endpoints | checking the graph is accurate |
| **Metro** | candidates, chosen stations, shafts, tunnel, trains on the timeline; ACO trace player with pheromone | optimisation results |
| **Simulation** | students on the timeline, both scenarios (switch or split), stats panel | the final animation |

### 2.3 Cameras

- **Orbit** (default): perspective camera with `OrbitControls` from `three/addons`. Damping
  is on, the camera can't go below ground, and double-click focuses the clicked point.
- **Top / plan**: orthographic camera looking straight down, north up (or aligned to the
  building's +x axis in the Building workspace, so walls look axis-aligned). This replaces
  `preview.html` for 2D review, and with level isolation it gives floor plans.
- **Walk**: first person at 1.7 m eye height. Uses `PointerLockControls` (WASD, Shift to
  run), a capsule collider against the BVH of the building meshes, and gravity onto slabs
  and stair ramps, so you can walk through doors and up stairwells. Esc returns to orbit
  at the same spot.
- `F` frames the selection; camera changes animate over 400 ms.

### 2.4 Inside buildings

- **Level isolation**: with a building selected, the level stepper (PageUp / PageDown)
  shows levels ≤ N, hides the roof and the levels above, and draws level N's walls cut at
  1.2 m, a section height like a floor plan. This uses one clipping plane on the
  building's materials. The other levels can be shown "ghosted" for context.
- **Room labels**: room ids (and names, if any) placed at room centres on the active level
  only, using `CSS2DRenderer` from `three/addons`, with collision culling so labels don't
  overlap.
- **Colour modes** for rooms: by kind (room / corridor / stairs), by capacity, and later by
  demand (students per hour, from the simulation) or by USOS mapping (mapped / unmapped
  rooms, to find gaps in `usos_room_map.csv`).

### 2.5 Selection and inspection

Hovering highlights (a lighter tint) and clicking selects (accent outline plus tint). Picking
is a BVH raycast with `firstHitOnly`, and the hit object's glTF `extras` give the key. The
Inspector shows:

- **Building**: id, name, kind, LOD, levels with elevations, entrances, `metro_shaft`, OSM
  id, height and level sources, its issues, and actions *Copy id*, *Open YAML*
  (`vscode://file/...` link), *Frame*, *Enter* (switch to the Building workspace).
- **Room / corridor / stairs**: key, level, area, dimensions, doors, capacity. Later also
  USOS groups using it and students per hour.
- **Context building / OSM feature**: OSM id with a link to openstreetmap.org, and its
  tags.
- **Graph node / edge**: id, kind, length, time, OSM way.

The selection lives in the URL (`#building/D-17?level=1&sel=D-17/1.38&cam=…`), so a
reload, including live reloads, keeps the view, and a view can be shared by copying the
URL.

## 3. Modelling helpers

These are the main reason the viewer exists before the simulation does.

1. **Live reload.**
   - `uv run scripts/06_export_web.py --campus --watch` watches `data/campus/**`.
   - When a building YAML changes, only that building's GLB and info JSON are rebuilt;
     when `campus.yaml` changes, the scene and the passages are rebuilt.
   - It writes `status.json` (version, time, the changed files, errors).
   - A small Vite plugin (`web/plugins/metroData.ts`) watches `public/data/status.json` and
     sends an HMR event. The viewer refetches only the changed files and keeps the camera
     and selection.
   - In dev, `npm run model` starts Vite and the Python watcher together.
2. **Validation errors in place.**
   - If a YAML fails `load_building`, the last good GLB stays.
   - The status bar turns red, and a panel shows the file, line and the pydantic message
     (the YAML is loaded with line marks, so `levels.1.rooms.3` maps to a line in the
     file).
   - If the error names an element that exists in the last good build (room `1.38`), it
     is outlined in red.
   - Clicking the error opens VS Code at that line.
3. **Local coordinates.**
   - The status bar shows the cursor position in the hovered building's local frame
     (metres, 0.1 m) and the level.
   - Click with Alt to copy `[x, y]` to the clipboard, ready to paste into `path:` or
     `polygon:`. With Alt+Shift, each click appends a point, and Enter copies the whole
     polyline.
   - This works because the web frame and the local frame are both aligned to the
     EPSG:2180 grid, so local ↔ web is one rotation by `bearing_deg` plus a translation.
     `scene.json` carries each building's anchor and bearing.
4. **Building grid**: a 1 m / 5 m grid in the selected building's frame, on the active
   level's floor, with the axes drawn in the accent colour. You can see what `[40, 0]`
   means.
5. **Measure tool** (`M`): click two or more points (snapping to vertices, edges and graph
   nodes); it shows segment lengths, the total length and the angle relative to the
   building's +x axis.
6. **OSM comparison**: draws the OSM outline as a dashed line over the modelled footprint
   and lists the Hausdorff distance in the Inspector, so you can see when a hand-made
   footprint drifts.
7. **Aerial underlay** (optional layer, off by default):
   - Orthophoto from the GUGiK WMS (Polish open data), fetched and baked once by Python
     into `ground/aerial.jpg`, cached in `data/raw/aerial/`, and draped on the ground.
   - Useful for checking outlines, entrances and paths.
8. **Issues panel**:
   - Lists the issues from `osm/report.md` (as JSON this time) and the validation of all
     buildings: no entrance, levels missing, outside the campus, and so on.
   - Each row jumps to its building.
   - Filters: by kind; "only buildings at LOD1".
9. **Progress overview**: in the Campus workspace, a colour mode by LOD (1 / 2 / 3), with
   counts in the legend. It shows what's still left to model.

## 4. Contract changes

To be added to `schemas/web.py` and `docs/data_contracts.md` section 10 in phase 0.
Everything stays in the web frame.

| file | model | content |
|---|---|---|
| `scene.json` | `Scene` (extended) | `SceneBuilding` gains `frame: {anchor: Vec3, bearing_deg}`, `category`, `osm_id`, `yaml: str` (repo-relative path, for *Open YAML*), and `n_issues`. New `context_glb`, `ground_glb`, `aerial` (image + bounds), `layers` (which optional files exist). |
| `buildings/<id>.glb` | contract 10.2 | unchanged. LOD1 also follows it: `L0…Ln` groups with one block per level, so isolation works the same everywhere. |
| `buildings/<id>.json` | `BuildingInfo` (new) | per level: room, corridor and stairs outlines in local metres, doors, entrances, `metro_shaft`; the OSM outline in local metres; Hausdorff distance; validation issues. It feeds the Inspector, labels and the outliner without parsing the GLB. |
| `campus/context.glb` | contract 10.2 style | all context buildings merged into **one mesh** with a `_FEATURE_ID` vertex attribute (uint16); one draw call. |
| `campus/context.json` | `ContextFeatures` (new) | feature id → `osm_id`, `name`, `height_m`, tags subset. |
| `campus/ground.glb` | | ground plane, campus boundary, walk paths as flat ribbons (width from OSM or 2 m), steps as ribbons in a darker tone. |
| `network.json` + `.bin` | `NetworkHeader` (new, binary container 10.4) | nodes `xyz` float32 (N,3), `node_kind` uint8; edges `edge_nodes` uint32 (E,2), `edge_kind` uint8, `length_m` / `time_s` float32; `osm_way` id per edge. Walk graph now, and the indoor graph and passages once `network/*.parquet` exists. |
| `issues.json` | `Issues` (new) | `[{severity, code, message, building_id?, osm_id?, position?}]` from the OSM stage and building validation. |
| `status.json` | `BuildStatus` (new) | `version` (incrementing), `built_at`, `changed: [paths]`, `errors: [{file, line?, loc, message}]`. |

The TypeScript types still come only from the generated `src/generated/schemas.ts`.

## 5. Python side

New package layout:

```
src/metro_agh/
├── geometry/                 YAML → geometry, no I/O; also used by the graph builder later
│   ├── frame.py              building local frame → web frame (uses campus.geo.LocalFrame)
│   ├── polygons.py           corridor ribbons, attached boxes → polygons; triangulation (earcut)
│   ├── walls.py              wall segments from room/corridor edges, door gaps, wall dedupe
│   ├── building.py           Building → BuildingGeometry (levels → slabs, walls, rooms, stairs, roof)
│   └── lod1.py               footprint (+holes) × n_levels → per-level blocks and a roof
└── web/
    ├── gltf.py               minimal GLB writer: nodes, names, extras, materials, uint16/32 indices
    ├── export_campus.py      scene.json, buildings/*.glb|json, context, ground, network, issues
    ├── aerial.py             GUGiK WMS → ground/aerial.jpg (cached)
    └── watch.py              watchfiles loop, incremental rebuild, status.json
scripts/06_export_web.py      --campus [--watch] now; --metro / --aco / --sim added in later phases
```

Notes:

- **GLB writer**: about 150 lines of numpy plus the glTF JSON. We need exact control over
  node names and `extras`, and a 16-bit feature attribute, and that is easier to write
  than to coax out of trimesh. Tests read the files back with `pygltflib` (a dev
  dependency) to check the node naming contract.
- **Triangulation**: `mapbox-earcut` (polygons with holes, needed for A-0 courtyards).
- **Walls**: each room polygon edge and corridor side becomes a wall segment. Coincident
  segments of neighbouring rooms are merged, and doors cut gaps of `door_width` (0.9 m;
  entrances 1.8 m) at 2.1 m height. Walls are 0.2 m thick, slabs 0.25 m.
- **Stairs**: a ramp box between the two landings of consecutive levels, drawn as steps
  (stepped geometry is cheap at this scale). The metro shaft is drawn the same way down to
  `station_depth_m`, and the platform box is added in the Metro phase.
- **Performance**: building all 88 LOD1 buildings should take well under 2 s. A single
  building in watch mode should take under 300 ms. Context buildings are rebuilt only when
  `campus.gpkg` changes.

## 6. Frontend architecture

```
web/
├── plugins/metroData.ts      Vite plugin: watch status.json → HMR event; `npm run model` spawns the watcher
└── src/
    ├── main.tsx, App.tsx     layout shell only
    ├── state/
    │   ├── store.ts          tiny external store (useSyncExternalStore), no state library
    │   ├── url.ts            store ↔ location.hash (workspace, selection, level, camera)
    │   └── selection.ts      keys: building | room | node | edge | osm feature
    ├── data/
    │   ├── loader.ts         (exists) fetchJson, loadBinary
    │   ├── cache.ts          versioned cache; invalidate(paths) on HMR event
    │   ├── live.ts           subscribes to the HMR event, bumps versions
    │   └── useData.ts        hooks: useScene, useBuildingInfo(id), useNetwork, ...
    ├── lib/
    │   ├── frames.ts         web ↔ lon/lat ↔ building local (pure, unit-tested)
    │   ├── format.ts         numbers, times, ids
    │   └── graph.ts          Dijkstra on network buffers (route tool)
    ├── scene/
    │   ├── Viewport.tsx      Canvas, lights, renderer settings, clipping enabled
    │   ├── cameras/          OrbitRig, PlanRig, WalkRig (BVH capsule collision), transitions
    │   ├── materials.ts      the palette: one shared material per kind, edge material
    │   ├── edges.ts          EdgesGeometry (30°) overlay per loaded mesh, the "drawing" look
    │   ├── picking.ts        pointer → BVH raycast → selection key (+ feature id lookup)
    │   ├── layers/
    │   │   ├── Ground.tsx, Aerial.tsx, ContextBuildings.tsx
    │   │   ├── Buildings.tsx, Building.tsx (level isolation, ghosting, clipping)
    │   │   ├── RoomLabels.tsx (CSS2DRenderer), Entrances.tsx, Stops.tsx
    │   │   ├── Network.tsx   LineSegments from network.bin, colour by kind
    │   │   ├── BuildingGrid.tsx, OsmOutline.tsx, Route.tsx, IssueMarkers.tsx
    │   │   ├── Metro.tsx, AcoTrace.tsx (later)
    │   │   └── Students.tsx  InstancedMesh cylinders, positions on the GPU (later)
    │   └── tools/            MeasureTool, PickPoint (copy local coords)
    └── ui/
        ├── TopBar, Search, Sidebar, LayerPanel, Outliner, Inspector, IssuesPanel
        ├── StatusBar, Toasts, Timeline, StatsPanel, Legend, Compass, ScaleBar
        ├── icons.tsx         inline SVG icons
        └── theme.css         design tokens (colours, spacing, radii) as CSS variables
```

Principles:

- **Data flows one way**: files → `data/` hooks → `scene/` layers. UI and scene talk only
  through the store (selection, visibility, level, camera mode, time). Scene components
  never fetch data themselves.
- **Store**: one small typed store with slices (`view`, `layers`, `selection`, `playback`)
  and selector hooks, so a slider move doesn't re-render the sidebars. Values read every
  frame, such as playback time, are read with `store.get()` inside `useFrame`, not
  through React state.
- **Materials**: shared materials from `materials.ts` replace the GLB materials by name
  (`mat:wall` → `wall`), so the look is changed in one file. Ghosting and isolation set
  per-building material clones, cached.
- **No per-frame allocations.** Instanced meshes are used for students, trains and ants.
- **Disposal**: when a building is reloaded, its old geometries, BVHs and edge overlays
  are disposed, so the live-reload loop doesn't leak memory.

Planned dependencies: `vitest` (dev). Nothing else is needed. `CSS2DRenderer`,
`OrbitControls`, `PointerLockControls` and `GLTFLoader` come from `three/addons`, and the
BVH collision comes from three-mesh-bvh.

## 7. Phases

Each phase ends with something usable, and its acceptance checks are run before moving on.

### Phase 0: campus export (Python), done
- Contract changes from section 4 (models, JSON Schema, generated TS, docs).
- `geometry/lod1.py`, `web/gltf.py`, `export_campus.py`: scene, the 88 building GLBs and
  info JSONs, context, ground, network (walk graph), issues.
- Tests: GLB node names and extras follow 10.2, footprint area equals slab area (holes
  included), and the web position of the anchor matches the `LocalFrame` round trip.
- **Done when** `06_export_web.py --campus` writes all files and they validate against the
  schemas.

### Phase 1: viewer shell and Campus workspace, done
- Layout, theme tokens, store, URL state, top bar, sidebars, status bar.
- Orbit and plan cameras; ground, context (one draw call), AGH buildings, entrances, stops,
  boundary.
- Picking, hover, selection, Inspector, Outliner, search, `F` to frame, compass, scale bar.
- Colour modes: category, LOD. Issues panel with jump-to.
- Replays menu and playback dock (clock, speed, weekday, scenario); the drawing of replays
  comes in phases 5 and 6.
- **Done when** every AGH building and context building can be found, clicked and
  inspected, at 60 fps on the campus view. Measured: 60 fps with 88 buildings, 1,846 context
  buildings and the full walk network (Edge, 1600×900).

### Phase 2: modelling loop, done
- `watch.py`, `status.json`, Vite plugin, `npm run model`, partial reload, error panel
  with YAML line numbers, VS Code links.
- Building workspace: isolation, ghosting, building grid, local coordinate readout and
  copy, polyline capture, measure tool, OSM outline with Hausdorff, aerial underlay.
- **Done when** editing `D-17.yaml` (sample promoted to `data/campus`) shows the change in
  under 2 s without losing the camera, and a broken YAML shows a red error with its line.
  Measured on `npm run model:sample`: about 0.6 s from save to screen (the rebuild of one
  building takes 0.03 to 0.08 s), with no page reload. A broken YAML keeps the last good
  build (marked stale), turns the status bar red, lists the error with a VS Code link to its
  line and tints the room it names red.
- Implementation notes:
  - `watch.py` polls modification times (0.3 s) instead of using `watchfiles`, so there is no
    new dependency; edits are handled once the files stop changing.
  - `CampusExport` keeps its inputs in memory; `update(paths)` rebuilds only those
    buildings, and the merged context mesh only when a building takes over an OSM outline.
  - Errors of the whole-building check (`a; b; c`) are split and placed on the line of the
    room, stairs or entrance they name (`web/yaml_errors.py`).
  - The aerial underlay is the GUGiK orthophoto at 0.5 m/px (`--aerial`, cached in
    `data/raw/aerial/`).

### Phase 3: interiors (LOD2/3), done
- `geometry/building.py`, `polygons.py`, `walls.py`: slabs, walls with door gaps,
  corridors, rooms, stairs, shaft, roof.
- Level stepper, section clipping, plan view aligned to the building, room labels, room
  colour modes, outliner down to rooms.
- Walk camera with collisions and stairs.
- **Done when** the sample D-17 (LOD3) and A-0 (LOD2) can be entered, floors stepped
  through and walked, with labels matching the YAML. Checked on `--sample`, including the
  A-0 basement (the ground is hidden while a level below it is active) and climbing the
  D-17 stairs on foot.
- Implementation notes:
  - All interior geometry is in `geometry/interior.py` (not split into `polygons.py` and
    `walls.py`). Walls are the merged outlines of all spaces, the corridors' union and the
    footprint, thickened to 0.2 m, minus door gaps (0.9 m, entrances 1.8 m, stairwells open
    to the corridor), with lintels from 2.1 m. They are closed solids, so a cut wall shows
    its inside as the dark poché, also in the plan view.
  - Stairs are dog-leg flights (up away from the corridor, landing, back), so you arrive
    next to the corridor one level up. The walk camera collides with the stepped geometry
    directly (a ray down from knee height finds the next step); no hidden ramp is needed.
  - Room colour modes: kind and capacity. Demand and USOS mapping come with the simulation.
  - The metro shaft is drawn as a dashed outline down to `metro.station_depth_m`.

### Phase 4: Network workspace, done
- Walk graph overlay (steps, barriers, fences), and the indoor graph and passages once the
  network builder (stage 2b) writes `network/*.parquet`.
- Route tool: pick two endpoints (building, room, stop) and see the shortest path, its time
  and its parts (outdoor, indoor, stairs). This is the quickest way to check the graph is
  accurate against your own walking times (`field_measurements.csv`).
- **Done when** a route from `stop:miasteczko-studenckie-agh` to `D-17/1.38` is shown with
  a plausible time. Checked on `--sample` (the only campus with room 1.38): 13 min 39 s for
  1.05 km, of it 12 min 34 s outdoors, 55 s inside D-17 and 10 s up the stairs `s1`
  (`#ws=network&from=stop:miasteczko_studenckie_agh&to=D-17/1.38`).
- Implementation notes:
  - Stage 2b did not exist, so this phase wrote it (`metro_agh.network`, section 6.4 of the
    contracts): `02_build_campus.py` writes `network/*.parquet`, and the web export builds the
    same graph in memory, so the graph follows YAML edits in watch mode (a rebuild of one
    building with the graph takes about 0.2 s). The real campus (all LOD1) gives 5,340
    nodes and 6,505 edges in 0.6 s.
  - `network.json` now carries the whole graph with times per direction, node kinds, the
    endpoint index, barriers and the field measurements (contract 10.7).
  - Route tool: right panel tab *Route* (`R`, or *Route from / to* in the inspector), ends
    typed as keys or picked in the view (a room, building, stop, entrance, or else the
    nearest graph node). Dijkstra over the directed CSR (`lib/graph.ts`); the route is in
    the URL (`from`, `to`). Field measurements are listed with the graph's time and the
    difference; the CSV is still empty.
  - With a building opened at a level, the indoor graph is cut at the section height like
    the building. Barriers are only shown: the graph ignores them in v1.

### Phase 5: Metro workspace, done (on a synthetic run)
- `--metro` / `--aco` export: `metro.json`, `aco/trace.*`.
- Candidates as cylinders at their shafts, the chosen stations, shafts, platforms, the
  tunnel (cut-away ground or translucent ground), and trains interpolated from runs.
- ACO player: iteration scrubber, sampled ants moving along their tours, pheromone as
  tunnel-candidate edge thickness and opacity, best-so-far cost chart.
- **Done when** the trace of a real run plays from iteration 0 to the end. There is no
  optimiser yet (stage 4), so this was checked on `--fake`: a MAX-MIN ant system on a
  synthetic instance of the real campus (54 candidates, k = 5, 120 iterations, 30 ants)
  plays from 0 to 119 with the pheromone concentrating and the best line improving. The
  exporters read only the contracted files (`run.json`, `convergence.csv`, `trace.npz`,
  `best_line.json`), so a real run goes through the same path: `06_export_web.py --aco`.
- Implementation notes:
  - Replays: `--aco` → `replays/aco-<run_id>/` (trace + the best line's `metro.json`),
    `--metro` → `replays/sim-<run_id>/` (kind `simulation`, trains only until `--sim`).
    The timetable comes from `simulation/metro/schedule.parquet` if it is for the same line,
    else from `metro_agh.simulation.schedule` with the config's headway, speed and dwell.
  - `AcoTraceHeader` gained the convergence curve, `candidate_tops`, `k`, `n_iterations`,
    `best_s`, `baseline_s` and the final `stations` (contract 10.6).
  - The dock of an ACO replay has two views: *Ants* (iteration player, convergence chart,
    best line so far) and *Trains* (the best line on the day clock). Simulation replays
    show the trains too. While the line is on show the ground turns see-through.
  - Pheromone ribbons are scaled between the weakest and the strongest trail of the current
    (interpolated) iteration, so early near-uniform trails stay faint.
  - A paused replay moment is in the URL (`it`, `t`, `day`, `view`).

### Phase 6: Simulation workspace, done (on a synthetic week; fps not measured)
- `--sim` export: `trips/<scenario>/paths.*`, `day-*.{json,bin}`, `stats.json`.
- Students as an `InstancedMesh` of low cylinders (up to 20,000). Positions are
  interpolated per frame in a vertex shader from a path texture, or on the CPU with
  incremental pointers, whichever measures faster. Colour by mode (walk / waiting /
  metro).
- Timeline (06:00–22:00, 1× to 600×), weekday and scenario; split view comparing
  no_metro and metro side by side with synced cameras.
- Stats panel: totals, per-hour chart (own SVG, no chart library), station boardings,
  top OD savings, each clickable to show it in 3D.
- **Done when** a full Monday plays at 60× with 20,000 students at ≥ 50 fps.
- Status: plays on `--fake`, a synthetic week of 20,000 students (253,179 legs) on the real
  walk graph, simulated by the real stage-5 code (`metro_agh.simulation.simulate`,
  `05_simulate.py`; it did not exist, so this phase wrote it from section 9 of the contracts).
  At most about 7,400 students are on the move at once. The CPU update takes 0.1 ms per frame
  on average over a whole Monday at 60× (worst 19 ms, at start-up). **The ≥ 50 fps target is not
  verified**: headless Chrome on a busy machine gave about 30 fps in this view even with no
  students on screen (and 60 in the Campus view), which says more about the measuring than the
  view. To measure on a laptop: open
  `#ws=simulation&replay=<id>&day=1&t=26400&play=1&speed=60&perf=1` and read the probe.
- Implementation notes:
  - CPU interpolation was enough (`lib/trips.ts`: binary search for the rows that can be on
    screen, then one search per student in its path), so no vertex shader.
  - The simulation is deterministic, so everyone on the same path leaving at the same second is
    at one point. For drawing only, such a group is laid out as a sunflower spiral around it,
    so its area shows its size.
  - Split view: the scene is drawn twice per frame with one camera (`scene/SplitView.tsx`),
    no metro on the left, with metro and the line on the right; pointer events map into their
    half. HTML labels are hidden while split.
  - Stats tab: totals per scenario, travel per hour of the selected weekday (click: go to that
    hour), stations (click: frame), largest savings (click: the walking route in 3D).
  - `per_hour` counts a leg in the hour it leaves in when walking (contract 10.6).

### Phase 7: finish, done
- Screenshot / clean presentation mode, keyboard help (`?`), loading states, an empty
  state per missing file with the command to produce it, accessibility pass (focus,
  contrast), performance pass.
- Implementation notes:
  - `P` presentation mode (only the view, compass, scale bar and the playback dock; `#present=1`),
    `S` screenshot: the canvas plus the HTML labels redrawn on top, as a PNG.
  - `?` keyboard help; the status bar shows how many files are loading.
  - A missing file shows the command that writes it (a toast once per file, and in the replay
    menu, the empty Metro / Simulation workspaces, the Route and Stats tabs, the dock).
  - Accessibility: visible keyboard focus, `aria-pressed` on toggle buttons, labels on icon
    buttons, `--muted` text darkened to 4.5:1, reduced-motion camera jumps.
  - Performance: a frame-rate probe (`` ` ``, or `#perf=1`; `#perf=log` prints a line per
    second for measuring headless), and `#play=1&speed=N` to start a replay from a link.

Phases 0–3 don't depend on USOS or the optimiser. Phase 4 needed the network builder (now
written), 5 the optimiser, and 6 the simulation. Until they exist, phases 5 and 6 are
developed on synthetic files from the `--fake` export flag, which follow the same contracts.

## 8. Performance budgets

| item | budget |
|---|---|
| first render of the Campus workspace | < 2 s on localhost |
| draw calls, campus view | < 300 (context = 1; AGH buildings merged per building) |
| frame rate | 60 fps campus / building, ≥ 50 fps with 20,000 students (laptop iGPU) |
| live reload of one building | < 2 s from save to screen |
| memory after 50 reloads | no growth (disposal tested) |

## 9. Testing

- **Python**: geometry unit tests (areas, wall counts, door gaps, closed volumes), GLB
  contract test, an export smoke test on `data/sample/campus`, and the watcher's
  incremental-rebuild test with a temp dir.
- **TypeScript**: vitest for `lib/` (frames against Python-computed fixtures, graph routing,
  trip interpolation) and `data/` (binary loader, cache invalidation).
- **CI**: the existing web job adds `npm test`. The Python job also runs the sample export
  and validates the outputs against the JSON Schemas.

## 10. Risks and open points

- **Wall generation** from parametric rooms is the hardest geometry part (T-junctions,
  rooms of different depths, corridor corners). If it gets messy, fall back to rooms as
  floor plates with low walls only around rooms. It still reads well in the clean style.
- **Walk camera on stairs** needs ramps in the collision geometry. Render the stepped
  geometry but collide with a hidden ramp mesh.
- **Context building heights**: most context buildings have no levels in OSM, so they use
  the default height. That's fine for grey massing.
- **Aerial licence**: the GUGiK orthophoto is open data, but the attribution must be shown
  in the viewer when the layer is on.
- Simulation playback strategy (GPU vs CPU interpolation) is decided by measurement in
  phase 6.

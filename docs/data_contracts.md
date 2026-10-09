# Data contracts

Every file that passes between pipeline stages is described here. The code version of each
contract lives in `src/metro_agh/schemas/` and is the source of truth: if this document and
the code disagree, the code wins and this document has a bug.

**Rules**

- A contract changes only after the team agrees (PR touching `schemas/` + this file).
- A change that breaks existing readers bumps `SCHEMA_VERSION` in `schemas/common.py`.
- Writers validate before saving (`TABLE.write(df, path)`, pydantic models, `Instance.save`).
- After changing a pydantic model run `uv run python -m metro_agh.schemas.export`; CI fails
  if `schemas/*.schema.json` are stale.
- Read CSV contracts with `TABLE.read(path)`, never plain `pd.read_csv`: room `0.10` would
  turn into the float `0.1`.

## Contents

1. [Pipeline and ownership](#1-pipeline-and-ownership)
2. [Conventions](#2-conventions)
3. [Hand-written data](#3-hand-written-data)
4. [USOS](#4-usos)
5. [Population and demand](#5-population-and-demand)
6. [Walk network](#6-walk-network)
7. [Problem instance](#7-problem-instance)
8. [Optimisation results](#8-optimisation-results)
9. [Simulation](#9-simulation)
10. [Web viewer](#10-web-viewer)
11. [Open questions](#11-open-questions)

---

## 1. Pipeline and ownership

```
 hand-written (git)                    generated (data/processed, gitignored)
 ─────────────────                     ──────────────────────────────────────
                       01_fetch_usos
 usos_room_map.csv ──────────────────► usos/timetable.csv, groups.csv,
                                       cohorts.csv, group_cohorts.csv
                                              │
 buildings/*.yaml ──┐  02_build_campus        │
 campus.yaml ───────┼────────────────► network/nodes.parquet, edges.parquet
 OSM (raw cache) ───┘                  osm/footprints.geojson
                                              │
                       03_build_demand        ▼
 config: population ─────────────────► population/students.parquet, enrollments.parquet
                                       demand/legs.parquet, od.parquet
                                              │
                       (end of 03)            ▼
                                       instance/instance.npz ◄── network + od
                                              │
                       04_optimize            ▼
                                       experiments/results/<run_id>/{run.json,
                                         convergence.csv, trace.npz}
                                       experiments/results/best_line.json, runs.csv
                                              │
                       05_simulate            ▼
                                       simulation/{no_metro,metro}/legs.parquet
                                       simulation/metro/schedule.parquet
                                              │
                       06_export_web          ▼
                                       web/public/data/  (scene, glb, metro, trips, aco, stats)
```

Paths of generated files are relative to `paths.processed` (`data/processed`), or to
`paths.sample` when a script runs with `--sample`. Hand-written campus data lives in
`paths.campus` (`data/campus`, sample: `data/sample/campus`).

| Contract | Code | Written by | Read by |
|---|---|---|---|
| `buildings/*.yaml`, `campus.yaml` | `schemas.building`, `schemas.campus` | by hand | campus, network, export |
| `usos_room_map.csv` | `tables.ROOM_MAP` | by hand | usos |
| `usos/*.csv` | `tables.TIMETABLE`, `GROUPS`, `COHORTS`, `GROUP_COHORTS` | person 1 | demand |
| `population/*.parquet` | `tables.STUDENTS`, `ENROLLMENTS` | person 1 | demand, simulation |
| `demand/legs.parquet`, `od.parquet` | `tables.LEGS`, `OD` | person 1 | network (instance), simulation |
| `network/*.parquet` | `tables.GRAPH_NODES`, `GRAPH_EDGES` | person 2 | instance, simulation, export |
| `instance/instance.npz` | `schemas.instance.Instance` | person 2 | aco, baselines, tests |
| `results/<run_id>/*`, `best_line.json` | `schemas.results`, `tables.CONVERGENCE` | person 3 | experiments, simulation, export |
| `results/runs.csv` | `tables.RUNS` | person 5 (`run_experiments.py`) | notebooks |
| `simulation/**` | `tables.SIM_LEGS`, `METRO_SCHEDULE` | person 4 | export, notebooks |
| `web/public/data/**` | `schemas.web` | person 4 | viewer (TypeScript) |
| `field_measurements.csv` | `tables.FIELD_MEASUREMENTS` | by hand | notebooks |

---

## 2. Conventions

### Units and names

Metres and seconds everywhere, no minutes. Name suffixes carry the unit:

| suffix | meaning | example |
|---|---|---|
| `_s` | duration, seconds | `walk_s`, `break_s` |
| `_wt` | **week time**: seconds since Monday 00:00 of the modelled week | `deadline_wt` |
| `_m` | length, metres | `length_m` |
| `t`, `*_t` (web only) | seconds since 00:00 of that weekday | `t_start` |

`timetable.csv` is the only file using `HH:MM` strings, because people check it by hand.
`weekday` is always `1` (Monday) … `5` (Friday).

### Identifiers

| id | format | example |
|---|---|---|
| building | canonical AGH code, upper case | `D-17`, `A-0`, `DS-7` |
| room | room number as in USOS, without the building | `1.38`, `0.10` |
| stop | `stop:` + lower-case slug | `stop:czarnowiejska` |
| corridor, stairs, entrance | `[A-Za-z0-9_-]`, unique **within one building** | `c0`, `s_main` |
| student | integer `0 … n_students-1` | `1734` |
| group | `<course_id>:<class_type>:<number>` | `ALG:LAB:2` |
| cohort | `<programme>-<semester>` | `IS-ISI-3` |

**Endpoint key**: where a student is at the start or end of a leg. It is one of:

- `D-17/1.38`: a room, when that room is modelled (LOD3),
- `D-17`: the building, when its rooms are not modelled or USOS has no room. It resolves to
  the inside of the main entrance,
- `stop:miasteczko_studenckie_agh`: a bus/tram stop,
- `DS-7`: a dorm (a building of kind `dorm`).

Demand always uses the most specific key that exists in the graph. If the timetable says
`A-0/1.21` but A-0 is LOD2, the leg uses `A-0`. When someone adds rooms to A-0 later, a
rebuild picks them up automatically.

### Coordinate frames

| frame | used in | axes |
|---|---|---|
| WGS84 `EPSG:4326` (lon, lat) | GeoJSON, `placement.anchor`, `campus.yaml` | lon, lat |
| PL-1992 `EPSG:2180` | every computation, `network/nodes.parquet`, `instance.npz` | x = easting, y = northing, z = absolute height |
| building local | `buildings/*.yaml` | origin at `anchor`; +x along `bearing_deg`; +y to the left; z up |
| web (three.js) | everything in `web/public/data` | x = east, **y = up**, z = −north; metres from `campus.web_origin` |

With pyproj always use `Transformer.from_crs(..., always_xy=True)`. EPSG:2180 officially
lists northing first, which is a classic source of swapped coordinates.

### Provenance

Every generated JSON carries a `provenance` object (`schemas.common.Provenance`):
`schema_version`, `generated_at`, `generator` (script name), `config_hash`, `git_commit`.
The `.npz` files hold the same fields in their meta.

---

## 3. Hand-written data

Everything here is committed to git and edited by hand. The JSON Schemas in `schemas/` give
autocompletion and inline errors:

- **VS Code**: works out of the box (`redhat.vscode-yaml` + mapping in `.vscode/settings.json`).
- **PyCharm**: Settings → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings.
  Map `schemas/building.schema.json` to `data/**/buildings/*.yaml`.

Validate everything with `uv run pytest tests/test_schemas.py`, or for one file:

```python
from metro_agh.schemas import load_building
load_building("data/campus/buildings/D-17.yaml")
```

### 3.1 `buildings/<id>.yaml`

One file per building, file name = building id. Model: `schemas/building.py`.
Full examples: `data/sample/campus/buildings/` (`D-17` = LOD3, `A-0` = LOD2,
`C-2` / `DS-7` = LOD1).

#### Level of detail

You do not have to model everything at once. The detail level follows from what the file
contains:

| LOD | contains | routing | look |
|---|---|---|---|
| 1 | `footprint` (or OSM), `n_levels`, `height_m`, point entrances | to the building as a whole | extruded block |
| 2 | `levels` with `corridors` + `stairs`, corridor entrances | to the main entrance inside | floors, corridors, stairwells |
| 3 | + `rooms` | room to room | full interior |

`02_build_campus.py --bootstrap` writes a LOD1 file for every OSM building that has no YAML
yet. It **never overwrites** an existing file. You then refine files by hand.

#### Local frame

Pick the anchor at the main entrance and the bearing along the main corridor; then most
coordinates are simple numbers like `[0, 0]`, `[40, 0]`.

```
            +y (left of +x)
             ▲
             │   room (side: left)
     ────────┼──────────────────────────► +x  (compass bearing = bearing_deg)
   anchor  [0,0]  corridor c0 centreline
             │   room (side: right)
```

- `placement.anchor`: `[lon, lat]` of the local origin. Copy it from any web map.
- `placement.bearing_deg`: compass bearing of +x (0 = north, **90 = east, the default**).
- z = 0 is the ground at the anchor. Level `elevation` is the floor height relative to it,
  so basements are negative.

#### Corridors, rooms and stairs

```yaml
levels:
  - id: 0              # 0 = ground, -1 = basement, 1 = first floor
    elevation: 0.0     # floor height, m
    height: 3.6        # floor-to-floor, default 3.5
    corridors:
      - id: c0         # unique in the whole building
        path: [[0, 0], [40, 0]]      # centreline polyline, local m
        width: 2.5                   # default 2.5
    rooms:
      # a box attached to the corridor: starts `at` m along the centreline,
      # spans `width` along it and `depth` away from the corridor wall
      - { id: "0.12", corridor: c0, side: left, at: 10, width: 8, depth: 7 }
      # door_at moves the door within the box (default: middle)
      - { id: "0.14", corridor: c0, side: left, at: 18, width: 8, depth: 7, door_at: 1 }
      # anything that is not a box: explicit polygon + doors onto corridors
      - id: "1.40"
        polygon: [[20, 1.25], [38, 1.25], [38, 8.25], [20, 8.25]]
        doors: [{ corridor: c0, at: 22 }, { corridor: c0, at: 36 }]
        capacity: 120              # optional
        name: Sala wykładowa       # optional
    stairs:
      # same shape options as rooms. The same id on several levels = one stairwell;
      # consecutive levels where it appears are connected
      - { id: s1, corridor: c0, side: right, at: 30, width: 4, depth: 6 }
```

Rules (the validator enforces all of them):

- `left` / `right` are relative to the corridor direction (first point → last point).
- `at` is measured along the whole polyline, so it may go round corners.
  `at + width` must not exceed the corridor length.
- Corridors on the same level that touch (an end point lying within 0.5 m of another
  corridor's centreline) are connected automatically. Corridors on different levels are
  connected only by stairs.
- Room ids are unique in the building; stairs must appear on at least two levels.
- Rooms open only onto corridors. A room reachable only through another room is out of
  scope for v1.
- Quote room ids (`"0.10"`), otherwise YAML reads them as numbers.

#### Entrances and the metro shaft

```yaml
entrances:
  - { id: main, corridor: c0, side: start, metro_shaft: true }  # door in the end wall at the first point
  - { id: back, corridor: c0, side: end }                       # ... at the last point
  - { id: side, corridor: c1, side: left, at: 12 }              # door in a side wall
  # LOD1 only: a point on the outline
  - { id: main, point: [17, 0], metro_shaft: true }
```

- The **main entrance** is the one with `metro_shaft: true`; if there is none, it's the
  first one listed. The endpoint key `D-17` resolves to it.
- `metro_shaft: true` marks a **candidate station**. The station lies `metro.station_depth_m`
  under that entrance, reached by one more flight of stairs (the shaft). At most one per
  building. `metro.candidates` in config can narrow the set further.
- An entrance links to the nearest OSM walk node, unless `osm_node` forces a specific one.

#### LOD1 fields and dorms

```yaml
footprint: [[0, 0], [60, 0], [60, 14], [0, 14]]  # local; omit to use the OSM outline (osm_id)
osm_id: way/123456                               # optional, the OSM baseline
n_levels: 11
height_m: 33.0
kind: dorm          # academic (default) | dorm | other
residents: 400      # dorms only: distributes dorm students between dorms
aliases: ["D17"]    # other spellings found in USOS
```

#### What gets generated from a building

- **3D**: slabs per level, walls along corridor and room edges, door gaps, stair blocks, roof;
  room meshes carry their id (see [10.2](#102-buildingsidglb)).
- **Indoor graph**: a node every few metres along each corridor centreline, a door node and
  a room-centre node per room, stair landings, entrance nodes inside and outside. Walking
  times use `time_model`: horizontal at `walk_speed_mps`, stairs at
  `stairs_up_mps` / `stairs_down_mps` vertically, `door_s` per door.

### 3.2 `campus.yaml`

Model: `schemas/campus.py`. Example: `data/sample/campus/campus.yaml`.

```yaml
schema_version: 1
passages:          # building-to-building connections outside OSM (indoor links, bridges)
  - id: a0_b1
    a: { building: A-0, corridor: c0, at: 70 }
    b: { building: B-1, corridor: c0, at: 30 }
    kind: indoor   # indoor | bridge | tunnel | covered
    width: 3.0
    waypoints: []  # optional [lon, lat] points for the geometry
extra_paths:       # outdoor walkways missing in OSM; ends snap to the nearest walk node
  - { id: shortcut, path: [[19.9131, 50.0681], [19.9140, 50.0676]] }
removed_ways:      # OSM ways students cannot use
  - { osm_way_id: 123456789, reason: gate closed }
stops:             # where commuting students arrive (3 stops)
  - { id: "stop:czarnowiejska", name: Czarnowiejska, location: [19.9172, 50.0665], weight: 2 }
```

`weight` is the relative share of commuters arriving at a stop. Passage ends need buildings
with corridors (LOD2+).

### 3.3 `usos_room_map.csv`

Fixes for raw USOS room strings that automatic parsing gets wrong. Contract: `tables.ROOM_MAP`.

| column | type | example |
|---|---|---|
| `usos_room` | str | `D-17 Sala 1.38 (lab)` |
| `building_id` | str | `D-17` |
| `room_id` | str, nullable | `1.38` |
| `note` | str, nullable | `USOS uses an old building name` |

### 3.4 `data/validation/field_measurements.csv`

Contract: `tables.FIELD_MEASUREMENTS`. One row per measured walk.

`route_id, from_key, to_key, measured_s, date (YYYY-MM-DD), who (initials), notes`

`from_key` / `to_key` are endpoint keys, so a measurement can start in a room (`D-17/1.38`)
or at a building's main entrance (`D-17`).

---

## 4. USOS

Raw API responses are stored as-is in `data/raw/usos/` (gitignored). Lecturer names and any
other personal data are dropped in `usos/parse.py`; nothing personal reaches
`data/processed`.

### 4.1 `usos/timetable.csv`: `tables.TIMETABLE`

One row per **weekly meeting slot** of a class group.

| column | type | example | note |
|---|---|---|---|
| `activity_id` | str | `a002` | unique |
| `group_id` | str | `ALG:LAB:1` | → `groups.csv` |
| `weekday` | int | `1` | 1–5 |
| `start`, `end` | str | `09:45`, `11:15` | `HH:MM` |
| `week_parity` | str | `all` | `all` / `odd` / `even` |
| `building_id` | str | `D-17` | canonical, after aliases and `usos_room_map.csv` |
| `room_id` | str, nullable | `0.10` | null when USOS has no room |

Only slots matching `demand.week_parity` (or `all`) enter the modelled week.

### 4.2 `usos/groups.csv`: `tables.GROUPS`

`group_id, course_id, course_name, class_type (WYK/CW/LAB/PROJ/SEM/…), size, size_source`

`size_source` is `usos` when USOS returns the count, `room_capacity` when it is taken from
the room, and `estimate` otherwise.

### 4.3 `usos/cohorts.csv` and `usos/group_cohorts.csv`

A **cohort** is the students of one programme and semester (`IS-ISI-3`); they share a
timetable apart from their choice of groups.

- `cohorts.csv`: `cohort_id, programme, semester, n_students, size_source`
- `group_cohorts.csv`: `group_id, cohort_id` (many-to-many; a lecture usually belongs to
  several cohorts)

These two files are what makes individual students possible (section 5) and stop
overlapping groups from being counted twice.

---

## 5. Population and demand

### 5.1 `population/students.parquet`: `tables.STUDENTS`

Synthetic students, `population.n_students` in total (20 000).

| column | type | note |
|---|---|---|
| `student_id` | int | 0 … n−1 |
| `cohort_id` | str | |
| `home_kind` | str | `dorm` / `stop` |
| `home_key` | str | dorm building id (`DS-7`) or stop id (`stop:miasteczko_studenckie_agh`) |

`population.dorm_share` of students get a dorm, chosen in proportion to `residents`; the rest
get a stop, chosen in proportion to the stop `weight`.

### 5.2 `population/enrollments.parquet`: `tables.ENROLLMENTS`

`student_id, group_id`. Each student attends every group of their cohort that has only one
group for its (course, class type), such as the lecture. For a course with several groups of
one type (e.g. LAB 1 and LAB 2), the student is in exactly one, and group sizes are respected.

### 5.3 `demand/legs.parquet`: `tables.LEGS`

One row per movement one student must make in the modelled week.

| column | type | note |
|---|---|---|
| `leg_id` | int | unique |
| `student_id` | int | |
| `weekday` | int | |
| `seq` | int | order within that student's day |
| `kind` | str | `home_to_class` / `class_to_class` / `class_to_home` |
| `from_key`, `to_key` | str | endpoint keys |
| `earliest_depart_wt` | int, nullable | end of the previous class; null for `home_to_class` |
| `deadline_wt` | int, nullable | start of the next class; null for `class_to_home` |
| `break_s` | int, nullable | `deadline − earliest_depart` when both are known |

Rules:

- Consecutive classes in the same room produce no leg; different rooms in the same building
  do, since they are indoor walks.
- A break longer than `demand.max_break_s`: dorm students go home and come back (two legs);
  commuters stay on campus (one `class_to_class` leg).
- `home_to_class` targets `deadline − demand.arrival_buffer_s`.

### 5.4 `demand/od.parquet`: `tables.OD`

`from_key, to_key, n_legs`: legs summed over the week. This is the demand ACO optimises.

---

## 6. Walk network

One graph for everything walkable: OSM outdoor paths (with `campus.yaml` corrections), the
indoor graphs of all buildings, passages, stops, and the metro shafts down to the platforms.
Train rides are **not** edges: the objective and the simulation add them analytically, which
keeps the graph independent of the chosen line.

### 6.1 `network/nodes.parquet`: `tables.GRAPH_NODES`

| column | type | note |
|---|---|---|
| `node_id` | int | dense 0…n−1, valid only within one build |
| `key` | str | stable, readable (below) |
| `kind` | str | `osm, corridor, room, door, stairs, entrance, shaft_top, platform, stop, place` |
| `x`, `y`, `z` | float | EPSG:2180 + absolute height |
| `building_id` | str, nullable | null outdoors |
| `level` | int, nullable | null outdoors |
| `endpoint_key` | str, nullable | set on nodes that are trip endpoints |

Node `key` format, so people can refer to nodes across rebuilds:

| kind | key | example |
|---|---|---|
| osm | `osm:<osm id>` | `osm:2187654` |
| corridor | `<b>:<corridor>@<at, 2 dp>` | `D-17:c0@12.50` |
| room | `<b>/<room>` | `D-17/1.38` |
| door | `<b>/<room>#<n>` | `D-17/1.40#1` |
| stairs | `<b>:<stairs>:L<level>` | `A-0:s_main:L-1` |
| entrance | `<b>:<entrance>:in` / `:out` | `D-17:main:out` |
| shaft_top / platform | `<b>:shaft` / `<b>:platform` | `D-17:platform` |
| stop | stop id | `stop:miasteczko_studenckie_agh` |
| place (LOD1 / building endpoint) | building id | `C-2` |

### 6.2 `network/edges.parquet`: `tables.GRAPH_EDGES`

`u, v, kind, length_m, time_uv_s, time_vu_s, source`

Each edge is stored once, with a walking time per direction (stairs and shafts are slower
going up). `kind` is one of `outdoor, corridor, door, stairs, entrance, passage, shaft, link`.
`source` is the OSM way id, building id or passage id the edge came from.

For debugging in QGIS, `02_build_campus.py --debug` also writes `network/graph.gpkg`. It
isn't a contract.

---

## 7. Problem instance

`instance/instance.npz`: `schemas/instance.py`. **This is the whole interface between the
campus/demand side and the optimisation side.** It contains only NumPy arrays, no graph and
no config, so ACO, the baselines and the brute-force tests run on it alone. Small hand-made
instances for tests follow the same format.

N candidate stations, E endpoints, M OD pairs.

| array | shape, dtype | meaning |
|---|---|---|
| `candidate_ids` | (N,) str | building ids; index = candidate index |
| `candidate_xyz` | (N, 3) f64 | shaft top, EPSG:2180 + height |
| `tunnel_m` | (N, N) f32 | straight tunnel length between platforms (symmetric) |
| `endpoint_keys` | (E,) str | index = endpoint index |
| `access_s` | (E, N) f32 | walk endpoint → shaft top (`inf` if unreachable) |
| `egress_s` | (N, E) f32 | walk shaft top → endpoint |
| `od_from`, `od_to` | (M,) i32 | endpoint indices |
| `od_weight` | (M,) f32 | student-legs per week |
| `od_walk_s` | (M,) f32 | walking time without metro |
| `meta_json` | str | `InstanceMeta`: `name, topology, k, metro_speed_mps, dwell_s, wait_s, shaft_down_s, shaft_up_s, source_hash` |

**Objective** for a line `s_0 … s_{k-1}` (candidate indices, in line order):

```
ride(i, j) = (Σ tunnel_m along the line between positions i and j) / metro_speed_mps
             + dwell_s × (stations strictly between i and j)
             (loop: the shorter of the two directions)

metro(a, b) = min over i ≠ j of
              access_s[a, s_i] + shaft_down_s + wait_s + ride(i, j) + shaft_up_s + egress_s[s_j, b]

objective   = Σ_m od_weight[m] × min(od_walk_s[m], metro(od_from[m], od_to[m]))
```

`wait_s = metro.headway_s / 2`. The simulation (section 9) uses the real timetable instead,
and the difference between the two is reported.

---

## 8. Optimisation results

### 8.1 Run directory `experiments/results/<run_id>/`

`run_id` = `<experiment>-<algorithm>-k<k>-s<seed>`, e.g. `baselines-mmas-k5-s3`.

**`run.json`**: `schemas.results.RunMeta`: provenance, experiment, algorithm, instance path +
hash, seed, `params` (exactly what was used), eval budget, evaluations, wall time, and the
`best` line.

**`convergence.csv`**: `tables.CONVERGENCE`, one row per iteration:

`iteration, evaluations, best_s, iter_best_s, iter_mean_s, tau_min, tau_max, pheromone_entropy`

The pheromone columns are null for the baselines; `evaluations` is cumulative, so curves of
different algorithms are compared at equal budget.

**`trace.npz`**: `schemas.results.AcoTrace`, ACO only. Sampled every `aco.trace.every`
iterations, at most `aco.trace.max_ants` ants. The same file feeds the analysis notebooks
and the web animation.

| array | shape, dtype | meaning |
|---|---|---|
| `iterations` | (I,) i32 | sampled iteration numbers |
| `tours` | (I, A, k) i16 | candidate indices in visiting order |
| `tour_cost_s` | (I, A) f32 | objective per tour |
| `best_tour` | (I, k) i16 | best-so-far at that iteration |
| `pheromone` | (I, N, N) f32 | τ after that iteration's update |
| `candidate_ids` | (N,) str | for checking against the instance |

### 8.2 `experiments/results/runs.csv`: `tables.RUNS`

One row per run, appended by `run_experiments.py`. It's the input for the boxplots, the
Wilcoxon tests and the gap-to-optimum table:

`run_id, experiment, algorithm, topology, k, n_candidates, seed, eval_budget, evaluations,
evaluations_to_best, best_s, baseline_s, optimum_s, wall_time_s, stations ('|'-joined),
params_json`

### 8.3 `experiments/results/best_line.json`: `schemas.results.BestLine`

The line used by simulation and export.

```json
{
  "provenance": { "schema_version": 1, "generated_at": "…", "generator": "04_optimize.py" },
  "run_id": "main-mmas-k5-s42",
  "topology": "line",
  "stations": ["D-17", "C-2", "B-1", "A-0", "U-2"],
  "objective_s": 7407402.0,
  "baseline_s": 9014046.0,
  "lower_bound_s": 5120000.0
}
```

---

## 9. Simulation

Every student, every leg, both scenarios. Deterministic shortest paths. In the `metro`
scenario a student takes the metro only when it gets them there earlier than walking, given
the actual train timetable. No congestion or train capacity in v1.

### 9.1 `simulation/metro/schedule.parquet`: `tables.METRO_SCHEDULE`

`run_id, train_id, weekday, direction (+1/−1), stop_seq, station, arrive_wt, depart_wt`

These are train runs between `metro.service.start` and `end`, every `metro.headway_s`. The
web viewer animates trains from the same data.

### 9.2 `simulation/<scenario>/legs.parquet`: `tables.SIM_LEGS`

| column | type | note |
|---|---|---|
| `leg_id`, `student_id` | int | same ids as `demand/legs.parquet` |
| `scenario` | str | `no_metro` / `metro` |
| `mode` | str | `walk` / `metro` |
| `depart_wt`, `arrive_wt` | int | |
| `walk_s`, `wait_s`, `ride_s` | float | walk includes stairs and shafts |
| `board_station`, `alight_station` | str, nullable | building ids |
| `late_s` | float | `max(0, arrive − deadline)` |
| `path_nodes` | list[int] | node ids walked; a metro ride appears as platform → platform |

Departure rule: `class_to_class` legs leave at `earliest_depart_wt`. `home_to_class` legs
leave so that they arrive at `deadline − arrival_buffer_s`. `class_to_home` legs leave right
after class.

---

## 10. Web viewer

React + three.js (React Three Fiber) with TypeScript and Vite, in `web/`. The viewer only plays back the files below, which are
all written by `06_export_web.py` into `web/public/data/` (gitignored). **All positions are
already in the web frame** (x = east, y = up, z = −north, metres from `campus.web_origin`),
so the viewer never converts coordinates.

TypeScript types are generated from `schemas/web/*.schema.json`:

```bash
cd web && npm run gen:types   # json-schema-to-typescript -> src/generated/schemas.ts
```

### 10.1 `scene.json`: `schemas.web.Scene`

The entry point the viewer loads first: the frame (`origin_lonlat`, EPSG:2180 origin,
`origin_z`), the list of buildings (`id, name, kind, lod, glb, levels[{id, floor_y,
height}], bbox_min, bbox_max`), stops (`id, name, position`) and an optional `ground_glb`
(terrain + outdoor paths).

### 10.2 `buildings/<id>.glb`

One glTF binary per building, so buildings load lazily and one edit re-exports one file.
Positions are in web coordinates, so no transform is needed. glTF is Y-up, so it matches
three.js directly.

Node hierarchy and names (the viewer finds things by name, e.g. to highlight a room):

```
D-17                      root, extras {building: "D-17", lod: 3}
├── L0                    one group per level, extras {level: 0}
│   ├── slab
│   ├── walls
│   ├── corridor:c0
│   ├── room:0.10         extras {kind: "room", id: "0.10", level: 0}
│   ├── stairs:s1
│   └── door:0.10#0
├── L1 …
├── entrance:main
└── roof                  hidden when the viewer enters the building
```

Materials are named by kind (`mat:wall`, `mat:slab`, `mat:room`, `mat:corridor`,
`mat:stairs`, `mat:glass`, `mat:roof`). The viewer replaces them with its own palette, so
the look is changed in TypeScript without re-exporting. The style is clean architectural:
flat colours, no textures.

### 10.3 `metro.json`: `schemas.web.Metro`

`topology`, `stations[{building_id, top, platform}]` in line order, `tunnel` (platform-level
polyline through the stations, closed for a loop), `headway_s`, `dwell_s`, `speed_mps`, and
`runs[{run_id, train_id, weekday, direction, stops[{station, arrive_t, depart_t}]}]`
(from `schedule.parquet`). The viewer builds shafts, platforms, tunnels and trains from this
and interpolates train positions itself; no per-frame train data is stored.

### 10.4 Binary containers

Large arrays travel as a header + raw buffer pair: `<name>.json` (header) + `<name>.bin`
(little-endian).

```json
{
  "provenance": { "…": "…" },
  "kind": "day",
  "bin": "day-1.bin",
  "buffers": {
    "t_start": { "dtype": "float32", "offset": 0, "count": 182344, "shape": [182344] }
  }
}
```

- `dtype`: `uint8, int16, uint16, int32, uint32, float32`.
- `offset` is in bytes and a multiple of 4, so typed arrays need no copy:
  `new Float32Array(bin, v.offset, v.count)`.
- `count` is in elements; `shape` is the logical shape, and its product equals `count`.

### 10.5 Student trips `trips/<scenario>/…`

20 000 students × 5 days won't fit as one-polyline-per-trip, but most students on the same
room-to-room leg walk the same path. Paths are therefore stored once and referenced by
time-shifted segments.

**`paths.json` + `paths.bin`**: `PathsHeader`, every distinct path of the scenario, shared
by all days:

| buffer | dtype, shape | meaning |
|---|---|---|
| `path_offsets` | uint32 (P+1) | path p = vertices `path_offsets[p] … path_offsets[p+1]−1` |
| `xyz` | float32 (V, 3) | vertex positions |
| `t` | float32 (V) | seconds since the start of the path |
| `mode` | uint8 (P) | `0` walk, `1` metro (train ride from platform to platform) |

**`day-<weekday>.json` + `.bin`**: `DayHeader`, one row per segment, sorted by `t_start`:

| buffer | dtype | meaning |
|---|---|---|
| `student_id` | uint32 (S) | |
| `leg_id` | uint32 (S) | link back to `simulation/<scenario>/legs.parquet` |
| `path_id` | uint32 (S) | into `paths` |
| `t_start` | float32 (S) | seconds since 00:00 of that day |

A walking leg is one segment. A metro leg has three: walk to the platform, the ride, and the
walk out. Between segments of one leg the student stands at the end of the previous path
(waiting on the platform). Between legs the student is in class and is not drawn. The student
position at time `t` is the path interpolated at `t − t_start`.

### 10.6 `aco/trace.json` + `.bin`: `AcoTraceHeader`

Same buffers as `trace.npz` (section 8.1), plus `run_id`, `algorithm`, `topology`,
`candidate_ids` and `candidate_platforms` (web positions). The viewer draws candidates as
cylinders, animates each sampled ant along its tour between platforms, and shows pheromone
as tunnel thickness or opacity.

### 10.7 `stats.json`: `schemas.web.Stats`

- `scenarios.{no_metro, metro}`: `n_legs, total_travel_s, mean_leg_s, n_late, late_share,
  longer_than_break_share, metro_share`
- `saving_s`: total no_metro − total metro
- `per_hour[{weekday, hour, n_legs, no_metro_s, metro_s}]`: the time-of-day chart
- `stations[{building_id, boardings, alightings}]`
- `top_od[{from_key, to_key, n_legs, saving_s}]`: the 50 largest savings

The notebooks use the same numbers, computed from `simulation/*/legs.parquet`.

---

## 11. Open questions

- **Stops**: which three stops are used (Miasteczko Studenckie AGH is confirmed; its location is approximate).
- **Group sizes and cohort sizes**: what the USOS API actually exposes. Until then
  `size_source = estimate`.
- **Elevators**: not routed in v1 (stairs only).
- **Time-dependent closures** (gates open only at certain hours): not in v1; such ways go to
  `removed_ways` or stay open.
- **Terrain**: building `ground_elevation_m` is optional; until a DEM is added, the campus is
  flat (z = 0 at every anchor).

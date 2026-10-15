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
6. [Campus and walk network](#6-campus-and-walk-network)
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
                       01_fetch_usos (USOS API + USOSweb, public)
 usos_room_map.csv ──────────────────► usos/timetable.csv, groups.csv, rooms.csv,
                                       cohorts.csv, group_cohorts.csv
                       01_fetch_transit (GTFS ZTP Kraków)
                     ────────────────► transit/stops.csv, rides.csv (──► campus.yaml stops)
                                              │
 OSM (raw/osm/cache) ── 02_build_campus ──► osm/campus.gpkg, report.md, issues.json, preview.html
                          --bootstrap ──────► buildings/*.yaml (LOD1, new files only)
 buildings/*.yaml ──┐                         │
 campus.yaml ───────┼── 02_build_campus ──► network/nodes.parquet, edges.parquet
                                              │
                       03_build_demand        ▼
 config: population ─────────────────► population/dorms.csv, students.parquet,
 usos/*, campus dorms + stops,          enrollments.parquet
 network/nodes.parquet                  demand/legs.parquet, od.parquet, migrations.csv
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
                                       web/public/data/  (scene, glb, network, issues, replays/<id>/…)
```

Paths of generated files are relative to `paths.processed` (`data/processed`), or to
`paths.sample` when a script runs with `--sample`. Hand-written campus data lives in
`paths.campus` (`data/campus`, sample: `data/sample/campus`).

| Contract | Code | Written by | Read by |
|---|---|---|---|
| `osm/campus.gpkg` | `tables.OSM_*` | person 2 (`02_build_campus.py`) | bootstrap, network, export |
| `osm_building_map.csv` | `tables.OSM_BUILDING_MAP` | by hand | campus |
| `buildings/*.yaml`, `campus.yaml` | `schemas.building`, `schemas.campus` | bootstrap, then by hand | campus, network, export |
| `usos_room_map.csv` | `tables.ROOM_MAP` | by hand | usos |
| `usos/*.csv` | `tables.TIMETABLE`, `GROUPS`, `COHORTS`, `GROUP_COHORTS`, `ROOMS` | person 1 (`01_fetch_usos.py`) | demand |
| `transit/*.csv` | `tables.TRANSIT_STOPS`, `TRANSIT_RIDES` | `01_fetch_transit.py` | campus.yaml stops, notebooks |
| `population/dorms.csv`, `*.parquet` | `tables.DORMS`, `STUDENTS`, `ENROLLMENTS` | person 1 (`03_build_demand.py`) | demand, simulation |
| `demand/legs.parquet`, `od.parquet` | `tables.LEGS`, `OD` | person 1 | network (instance), simulation |
| `demand/migrations.csv` | `tables.MIGRATIONS` | person 1 | notebooks, report |
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
| building | AGH code as in OSM `ref` | `D-17`, `A-0`, `DS-7`, `DS-Alfa`, `P-A0-A1` |
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
| building local | `buildings/*.yaml` | origin at `anchor`; +x along `bearing_deg` (grid bearing in EPSG:2180, within 1° of true north); +y to the left; z up |
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

`02_build_campus.py --bootstrap` writes a LOD1 file for every AGH building in OSM that has
no YAML yet (section 6.3). It **never overwrites** an existing file. You then refine files by
hand.

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
footprint_holes: [[[20, 4], [40, 4], [40, 10], [20, 10]]]  # courtyards (A-0)
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

Fixes for USOS rooms that automatic parsing gets wrong. Contract: `tables.ROOM_MAP`.
A whole USOS building that maps to the wrong id gets an `aliases` entry in its building YAML
instead (`DS-Alfa`: `aliases: [DSALFA1]`).

| column | type | example |
|---|---|---|
| `usos_room` | str | `D17/1.38` (USOS building id / room number) |
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

Source: the **public** USOS of AGH, no login and no API key (`metro_agh.usos`):

| what | where |
|---|---|
| buildings, rooms, seats | USOS API `apps.usos.agh.edu.pl/services/geo/{building_index,building2,rooms}` (anonymous) |
| which courses meet in a room | USOSweb room plan `kontroler.php?_action=katalog2/jednostki/pokazSale&sala_id=…` (current week) |
| cohorts of a course, its units per term | course page `…katalog2/przedmioty/pokazPrzedmiot&prz_kod=…` ("Grupy:", "Zajęcia w cyklu") |
| groups: meetings, frequency, room, registered / limit | `…katalog2/przedmioty/pokazGrupyZajec&zaj_cyk_id=…` |
| every unit of the university | USOS API `fac/subfaculties_deep?fac_id=000-000` (full crawl) |
| course groups of a unit, courses of a group | `…szukajPrzedmiotu&method=faculty_groups&jed_org_kod=…[&grupaKod=…]` (full crawl) |
| every dated meeting of a group | USOS API `tt/classgroups` (anonymous, 300 groups x 7 days a call; full crawl) |

Every response is cached as-is in `data/raw/usos/` (gitignored), so a crawl resumes and
`--offline` rebuilds the CSVs. Pages older than `usos.cache_days` (class groups: 3 days, since the
registered counts change until registration closes) are fetched again; `--refresh` fetches all. Lecturer names are on those pages; the parsers never read them,
so nothing personal reaches `data/processed`. The room plans only discover courses (they show
the current week: run the crawl in a teaching week); the course page lists every unit of the
term, so a group that meets only in even weeks is still found.

### 4.1 `usos/timetable.csv`: `tables.TIMETABLE`

One row per **weekly meeting slot** of a class group.

| column | type | example | note |
|---|---|---|---|
| `activity_id` | str | `a000002` | unique |
| `group_id` | str | `240-INF-1S-436:CWL:3` | `<course>:<class type>:<group nr>` → `groups.csv` |
| `weekday` | int | `1` | 1–5 |
| `start`, `end` | str | `09:45`, `11:15` | `HH:MM` |
| `week_parity` | str | `all` | `all` / `odd` / `even` |
| `building_id` | str | `D-17` | canonical, after aliases and `usos_room_map.csv` |
| `room_id` | str, nullable | `1.38` | null when USOS has no room; `-1.15c` becomes `m1.15c` |

Only slots matching `demand.week_parity` (or `all`) enter the modelled week. Parity comes from
the group's frequency text ("każdy wtorek" → `all`, "co drugi wtorek (nieparzyste)" → `odd`).
Weekend meetings, one-off and monthly ones, and meetings in buildings the campus does not
model are dropped; "wielokrotnie" (several dates) is kept as `all` when the crawled week has it.

### 4.2 `usos/groups.csv`: `tables.GROUPS`

`group_id, course_id, course_name, class_type, size, size_source, enrolled, limit, room_capacity`

`class_type` is the USOS code (`W` lecture, `CWA` / `CWL` / `CWP` exercises / lab / project, …).
`enrolled` is USOS "liczba osób w grupie", `limit` the group's (else the unit's) "limit miejsc",
`room_capacity` the seats of the smallest room it meets in. `size` is what the demand uses:
`enrolled` when positive (`size_source = usos`), else `limit` (`estimate`), else 60 % of
`room_capacity` (`room_capacity`), else the median of the class type (`estimate`).

### 4.3 `usos/cohorts.csv` and `usos/group_cohorts.csv`

A **cohort** is the students of one programme and semester; they share a timetable apart from
their choice of groups. They are the USOS course groups ("grupy przedmiotów") of the course
pages that name a semester: `240-INF-1S-1R-Z` = "240_Informatyka, stacjonarne, 1 semestr".

- `cohorts.csv`: `cohort_id, programme, semester, n_students, size_source`. `n_students` is the
  75th percentile, over the cohort's courses, of the course's registered students split evenly
  between the cohorts sharing it (compulsory lectures dominate the upper quantiles).
- `group_cohorts.csv`: `group_id, cohort_id` (many-to-many; a lecture usually belongs to
  several cohorts). A specialisation (`ELT_1S_sem_5_A`) is also linked to the groups of its
  parent (`ELT_1S_sem_5`). A course in no cohort (languages `440-…`, PE, humanities) is linked
  to a **pool** instead: `pool:1S` stands for every cohort whose code has that cycle and mode
  (`1S`, `2S`, `1N`, …), `pool:all` for every cohort. Its students are regular students of
  those cohorts, not extra people.

These two files are what makes individual students possible (section 5) and stop
overlapping groups from being counted twice.

### 4.4 `usos/rooms.csv`: `tables.ROOMS`

`room_usos_id, building_usos_id, number, building_id, room_id, capacity`: every USOS room, the
canonical building and room it maps to (null = not modelled) and its seats.

### 4.5 `usos/all/`: the whole term (`usos.scope: all`)

The full crawl starts from the catalogue of every unit, not from the campus rooms, so it covers
every programme, semester and course of the term, every room of every building (including
`poza AGH` and `online`), and every dated meeting: weekends, one-off dates and rooms outside
the campus model are kept here. Code: `metro_agh.usos.full`.

| file | contract | one row per |
|---|---|---|
| `course_groups.csv` | `tables.COURSE_GROUPS` | course group (programme × semester, or a pool): `code, cohort_id, label, faculty_id, programme, semester, level, n_courses` |
| `courses.csv` | `tables.COURSES` | course: `course_id, course_name, faculty_id, course_groups, n_units, n_groups, enrolled` |
| `class_groups.csv` | `tables.CLASS_GROUPS` | class group: `group_id, unit_id, course_id, class_type, class_type_name, group_nr, enrolled, limit, hours, terms, rooms` |
| `meetings.csv` | `tables.MEETINGS` | dated meeting: `date, weekday, start, end, unit_id, group_nr, group_id, course_id, class_type, kind, building_usos_id, building_id, room_usos_id, room_number, frequency` |

`group_id` is the same as in `groups.csv` and `timetable.csv`. In `meetings.csv`, `kind` is the
USOS activity type: `classgroup2` is a confirmed meeting, `classgroup` one derived from the
weekly pattern; `building_id` is null where the campus model has no such building.

### 4.6 `transit/stops.csv`, `transit/rides.csv`: `tables.TRANSIT_STOPS`, `TRANSIT_RIDES`

From the Kraków GTFS feeds (`transit.feeds`; `metro_agh.transit.gtfs`) for one weekday
(`transit.date`). **Stops**: every stop within `transit.margin_m` of `campus.bbox`, platforms
merged by name: lines, vehicles arriving in `transit.peak_hours` and all day, peak headway and
`weight` = peak vehicles × `transit.seats` / 1000, which is the `weight` of the stop in
campus.yaml (`01_fetch_transit.py --print-yaml`). **Rides**: every pair of campus stops a line
joins without a change: trips 06:00–21:00, shortest and median in-vehicle time, median headway.
**Trips** (`transit/trips.parquet`, `tables.TRANSIT_TRIPS`): each of those rides,
`from_stop, to_stop, line, dep_s, arr_s` (seconds after midnight), which the simulation
boards (section 9).

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

Each cohort contributes `n_students` students (`population.n_students: auto`; a number scales
the cohorts to that total). `population.dorm_share` of them (`auto`: dorm beds / students) get
a dorm, chosen in proportion to its beds (`population/dorms.csv`); the rest get a stop, chosen
in proportion to the stop `weight`.

`population/dorms.csv` (`tables.DORMS`): `building_id, name, floor_area_m2, levels, residents,
source`. `residents` comes from the building YAML when given (`source = yaml`); otherwise
`population.dorm_beds` (minus the known beds) is spread over the dorms by floor area
(footprint × storeys), since AGH publishes only the total (about 7000 of 8000+ places).

### 5.2 `population/enrollments.parquet`: `tables.ENROLLMENTS`

`student_id, group_id`. A course shared by cohorts S with `total` registered students (its
largest class type) is taken by each student of S with probability
`min(1, total / Σ n_students of S)`: compulsory courses by all, electives by enough to match the
USOS count. In every class type of a taken course the student is in exactly one group: each
student draws one place q ∈ [0, 1) (a dean's group) and goes to the group where q falls on the
cumulative group sizes, so group sizes are respected and lab partners share their other groups.
A group that clashes with a class already taken is swapped for the nearest one that does not.

### 5.3 Which week

`demand.week: auto` (default) models a **real calendar week**: the dated meetings of
`usos/all/meetings.csv` from Monday to Friday of the week with the most meetings, in buildings of
the campus model (`03_build_demand.py --week 2026-10-26` picks another Monday). Holidays, moved
classes, one-off dates and fortnightly classes are then as USOS has them, so no week parity is
chosen. Groups that meet on campus only on such dates ("wielokrotnie") are in `groups.csv` for
this. `demand.week: typical` (or `--typical`, or no `meetings.csv`) uses the weekly pattern of
`timetable.csv` with `demand.week_parity` instead.

### 5.4 `demand/legs.parquet`: `tables.LEGS`

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

### 5.5 `demand/od.parquet`: `tables.OD`

`from_key, to_key, n_legs`: legs summed over the week. This is the demand ACO optimises.

### 5.6 `demand/migrations.csv`: `tables.MIGRATIONS`

`weekday, hour, kind, from_place, to_place, n_legs, median_break_s`: legs between places
(buildings, dorms, stops; rooms folded into their building) per weekday and hour of departure
(end of the previous class, or the deadline for legs from home). The `class_to_class` rows are
the student migrations between buildings; `median_break_s` is the time they have for it.

---

## 6. Campus and walk network

### 6.1 `osm/campus.gpkg`: `tables.OSM_*`

Written by `scripts/02_build_campus.py` from one Overpass query for features and one for the
walk network over `campus.bbox`. Raw responses are cached in `data/raw/osm/cache`
(`--refresh` downloads again). One GeoPackage, **all layers in EPSG:2180**; open it in
QGIS to inspect, or open `osm/preview.html` in a browser. `osm/report.md` lists everything a
human should check. `osm/issues.json` (`schemas.web.IssueList`) holds the same issues with
`building_id` / `osm_id`, for the viewer's issues panel (section 10.8).

| layer | geometry | one row per | key columns |
|---|---|---|---|
| `boundary` | polygon | area | `kind` (`agh_campus` = OSM relation, `miasteczko` = hull of dorms, `bbox`) |
| `buildings` | polygon | AGH building (parts merged) or context building | `osm_id, osm_ids, building_id, category, ref, name, building, levels, levels_underground, roof_levels, height_m, height_source, connects, main_entrance_node, n_entrances` |
| `entrances` | point | OSM entrance node | `osm_node, entrance, name, ref, level, access, wheelchair, building_id, building_osm_id, is_main` |
| `stops` | point | stop (platforms grouped by name) | `stop_id, name, modes, n_platforms, platform_ids` |
| `barriers` | point | gate, bollard, turnstile, … | `osm_id, barrier, access, name` |
| `fences` | line/polygon | fence, wall, hedge | `osm_id, barrier, access` |
| `walk_nodes` | point | walk-network node | `osm_node, street_count, highway, barrier, access, entrance` |
| `walk_edges` | line | walk-network edge (undirected) | `u, v, key, osm_ways, highway, name, length_m, is_steps, step_count, incline, access, foot, covered, tunnel, bridge, indoor, level, surface` |

**Building classification** (`category`):

| category | rule | becomes |
|---|---|---|
| `academic` | AGH code in `ref` (`A-0`, `D-17`, `U-2`, `H-A1`, `Z-15`…), building tag university/college/library/yes/… | building YAML, metro candidate |
| `dorm` | `DS-*` code or `building=dormitory` with an AGH code | building YAML, student home |
| `other` | AGH code on a non-academic building (hospital, hotel, sports hall…) | building YAML |
| `connector` | `P-<a>-<b>` code (`P-A0-A1`); `connects` = the two building ids | building YAML of kind `other`; later a `passage` |
| `context` | everything else (no AGH code) | grey LOD1 block in 3D only, never a trip endpoint |

Rules: refs are normalised (`Z15` → `Z-15`; `;`-lists take the first AGH code). Parts with the
same code are merged into one outline. Height comes from `height`, else
`building:levels` × `campus.floor_height_m`, else `campus.default_levels` ×
`floor_height_m`; `height_source` says which. An entrance belongs to the building whose
outline is within `osm.entrance_snap_m`, with AGH buildings taking precedence over context
buildings. The main entrance of a building is chosen by: not private, then `entrance=main`,
then `yes`, then the rest, then lowest node id. Emergency exits are never the main entrance.

### 6.2 `data/campus/osm_building_map.csv`: `tables.OSM_BUILDING_MAP`

Hand-written fixes for the classification, e.g. a dorm OSM has without a ref:

| column | example | note |
|---|---|---|
| `osm_id` | `way/230301584` | element as in the `buildings` layer |
| `building_id` | `DS-Kolumny` | empty = make it context |
| `category` | `dorm` | empty = derive from the rules |
| `note` | `AGH dorm without ref in OSM` | |

### 6.3 Building bootstrap (`--bootstrap`)

For every non-context building without `data/campus/buildings/<id>.yaml`, a LOD1 file is
written and then validated with `load_building`:

- `placement.anchor` = the main entrance (or a point inside the outline if there is none),
- `placement.bearing_deg` = the building's long axis, flipped so the building centre lies
  on the positive side (+x in front of an end entrance, +y for an entrance on a long side),
- `footprint` (+ `footprint_holes`) in local metres, simplified by `osm.footprint_simplify_m`,
  rounded to 0.1 m,
- `n_levels` (if OSM has it), `height_m`, `osm_id`, `name`, `aliases` (raw ref if different),
- `entrances` as points: `main` first, then `e1`, `e2`…, emergency exits skipped;
  `metro_shaft: true` on the main entrance of academic buildings; `osm_node` when the entrance
  is a node of the walk network.

Disjoint parts keep only the largest outline (listed in the report). Files that already exist
are never touched.

### 6.4 Walk network contracts

One graph for everything walkable: OSM outdoor paths (with `campus.yaml` corrections), the
indoor graphs of all buildings, passages, stops, and the metro shafts down to the platforms.
Train rides are **not** edges: the objective and the simulation add them analytically, which
keeps the graph independent of the chosen line.

#### `network/nodes.parquet`: `tables.GRAPH_NODES`

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

#### `network/edges.parquet`: `tables.GRAPH_EDGES`

`u, v, kind, length_m, time_uv_s, time_vu_s, source`

Each edge is stored once, with a walking time per direction (stairs and shafts are slower
going up). `kind` is one of `outdoor, corridor, door, stairs, entrance, passage, shaft, link`.
`source` is the OSM way id, building id or passage id the edge came from.

Code: `metro_agh.network` (`indoor.py`: one building; `graph.py`: outdoor, passages, stops,
links and the assembly). Details of the build:

- Outdoor edges take `length / walk_speed_mps`, OSM steps `× time_model.outdoor_steps_factor`
  (OSM has no heights). `removed_ways` drop their edges; `extra_paths` snap both ends to the
  nearest walk node. Parallel edges keep the shortest.
- Corridor nodes every `network.corridor_node_step_m` and at every door, stairwell, entrance,
  junction and passage end. A door edge adds `door_s` (room doors and entrances).
- Stairs join the landings of consecutive levels where the stairwell appears:
  `rise / stairs_up_mps` up, `rise / stairs_down_mps` down. The shaft is the same, from the
  shaft top (at the `metro_shaft` entrance, inside) down to the platform.
- `:out` entrance nodes, stops and LOD1 buildings without entrances are linked (`link`) to the
  nearest node of the largest connected OSM component, or to `osm_node` when given.
- An endpoint `D-17` is the inside node of the main entrance (LOD2/3) or the `place` node
  (LOD1). Building files that fail validation are left out; problems (far links, unreachable
  endpoints, buildings without entrances) become issues in the viewer, section *Network: …*.

The web export builds the same graph in memory from the same inputs, so the viewer follows
YAML edits live without rerunning stage 2.

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
| `od_walk_s` | (M,) f32 | time without metro: the faster of walking and the expected bus / tram ride (below) |
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

Every student, every leg, both scenarios. Deterministic shortest paths. With
`simulation.transit` (default) **both** scenarios may ride a bus or tram between two campus
stops, from the GTFS rides of `transit/trips.parquet`: `no_metro` is "walk or public
transport", the fair baseline, and `metro` adds the train. A leg takes a ride only when it
gets the student there earlier than the options before it (walk, then bus / tram, then metro).
No congestion or vehicle capacity in v1.

The instance (section 7) uses the same baseline: `od_walk_s` is the faster of the walk and
the expected ride walk → stop + `median_headway_s` / 2 + `median_ride_s` + stop → walk over
the stop pairs of `transit/rides.csv` (`metro_agh.network.instance`).

### 9.1 `simulation/metro/schedule.parquet`: `tables.METRO_SCHEDULE`

`run_id, train_id, weekday, direction (+1/−1), stop_seq, station, arrive_wt, depart_wt`

These are train runs between `metro.service.start` and `end`, every `metro.headway_s`. The
web viewer animates trains from the same data. `metro_agh.simulation.schedule.build_schedule`
writes it from the line and the config: straight tunnels at `speed_mps`, `dwell_s` at every
intermediate station, runs in both directions; a train finishing a run takes the next one
leaving from that station, so `train_id` counts the trains a day needs.

### 9.2 `simulation/<scenario>/legs.parquet`: `tables.SIM_LEGS`

| column | type | note |
|---|---|---|
| `leg_id`, `student_id` | int | same ids as `demand/legs.parquet` |
| `scenario` | str | `no_metro` / `metro` |
| `mode` | str | `walk` / `metro` / `transit` (bus or tram) |
| `depart_wt`, `arrive_wt` | int | |
| `walk_s`, `wait_s`, `ride_s` | float | walk includes stairs and shafts |
| `board_station`, `alight_station` | str, nullable | metro: building ids; transit: stop ids |
| `late_s` | float | `max(0, arrive − deadline)` |
| `path_nodes` | list[int] | node ids walked; a ride appears as platform → platform (metro) or stop → stop (transit) |

Departure rule: `class_to_class` legs leave at `earliest_depart_wt`. `home_to_class` legs
leave so that they arrive at `deadline − arrival_buffer_s`. `class_to_home` legs leave right
after class.

Code: `metro_agh.simulation.simulate` (`scripts/05_simulate.py`). Walks are shortest paths on
the directed graph of 6.4 (Dijkstra once per distinct origin). A metro leg walks to the
platform of station i (the shaft is in the graph), takes the first train of the timetable that
reaches station j, and walks out of j; `wait_s` runs from reaching the platform to the train's
departure, `ride_s` from that departure to the arrival at j. It is taken only when it arrives
earlier than walking (`class_to_class`, `class_to_home`), or, for `home_to_class`, when it lets
the student leave later and still arrive by `deadline − arrival_buffer_s`. A bus or tram
leg works the same way from the stop node to the stop node, with the GTFS departures of that
stop pair on every weekday.

---

## 10. Web viewer

React + three.js (React Three Fiber) with TypeScript and Vite, in `web/`. The viewer only
plays back the files below, which are all written by `06_export_web.py` into
`web/public/data/` (gitignored). **All positions are already in the web frame** (x = east,
y = up, z = −north, metres from `campus.web_origin`), so the viewer never converts
coordinates. Implementation plan: [viewer_plan.md](viewer_plan.md).

TypeScript types are generated from `schemas/web/*.schema.json`:

```bash
uv run python -m metro_agh.schemas.export   # pydantic -> schemas/
cd web && npm run gen:types                 # json-schema-to-typescript -> src/generated/schemas.ts
```

Web schemas are exported in pydantic's *serialization* mode: every field is always present in
the files, so the TypeScript types have no optional fields.

```
web/public/data/
├── scene.json                  10.1  Scene: entry point
├── status.json                 10.9  BuildStatus: written last by every export
├── issues.json                 10.8  IssueList
├── network.json + .bin         10.7  NetworkHeader: walk graph
├── demand.json                 10.11 Demand: weekly walk-edge load (path heatmap)
├── buildings/<id>.glb          10.2  one per building YAML
├── buildings/<id>.json         10.3  BuildingInfo
├── campus/context.glb + .json  10.4  every other OSM building, merged; ContextFeatures
├── campus/ground.glb           10.5  ground, paths, boundary, fences
├── campus/aerial.jpg           10.1  orthophoto underlay (optional, `--aerial`)
└── replays/                    10.10 what can be played back
    ├── index.json              ReplayCatalog
    └── <id>/replay.json        Replay, plus its files (metro.json, trace.*, trips/, stats.json)
```

`06_export_web.py --campus` writes everything except the replays, which the metro, ACO and
simulation exports add later. Each export rebuilds `replays/index.json` from the
`replay.json` files it finds. `demand.json` is written from `demand/od.parquet` routed on
`network.json` when both exist (`--fake`, `--sim`, or a prior demand build next to `--campus`).

### 10.1 `scene.json`: `schemas.web.Scene`

The entry point the viewer loads first:

- `frame`: `origin_lonlat`, the EPSG:2180 origin, `origin_z`.
- `extent`: the downloaded bbox in web coordinates (camera limits, ground).
- `source_root`: the absolute repo path on the exporting machine, used for *Open YAML*
  links (`vscode://file/…`).
- `buildings[]`:
  - identity: `id, name, kind, category` (kind, but with connectors `P-…` told apart),
    `lod`;
  - files: `glb`, `info` (10.3), `yaml` (source file, repo-relative), `osm_id`;
  - geometry: `height_m`, `frame` (anchor in web coordinates + `bearing_deg`),
    `levels[{id, floor_y, height}]`, `entrances[{id, position, main, metro_shaft}]`,
    `bbox_min`, `bbox_max`;
  - `rooms`: room ids (LOD3), for the search (`D-17/1.38`);
  - `n_issues`, and `stale: true` when the YAML currently fails validation: the files are then
    the last good build.
- `stops[]`: the stops from `campus.yaml`. `other_stops[]`: OSM stops that are not in
  `campus.yaml`, shown greyed out to help choose more.
- Paths of the other files: `ground_glb`, `context {glb, features}`, `network`, `issues`,
  `replays`.
- `aerial`: `{image, min, max, attribution}` when an orthophoto was exported
  (`campus/aerial.jpg`, an axis-aligned rectangle in web coordinates), else `null`.

Local ↔ web for a building is a rotation plus a translation, because both frames are aligned
to the EPSG:2180 grid:

```
web = anchor + x · (sin b, 0, −cos b) + y · (−cos b, 0, −sin b) + (0, h, 0)      b = bearing_deg
```

The viewer uses this for the cursor readout in local metres (`web/src/lib/frames.ts`).

### 10.2 `buildings/<id>.glb`

One glTF binary per building, so buildings load lazily and one edit re-exports one file.
Positions are in web coordinates, so no transform is needed. glTF is Y-up, so it matches
three.js directly.

**The viewer identifies nodes by their `extras` (three.js `userData`), not by name**:
three.js `GLTFLoader` strips `.`, `:` and `/` from node names (`room:0.10` becomes
`room010`).

Node hierarchy:

```
D-17              extras {building: "D-17", lod: 3}
├── shell         extras {part: "shell"}     outer walls, all levels       mat:wall
├── roof          extras {part: "roof"}                                    mat:roof
├── edges         extras {part: "edges"}     line segments: outline at every floor and corners  mat:edge
├── L0            extras {level: 0}
│   ├── slab      extras {part: "slab", level: 0}   floor plate minus stairwell openings  mat:slab
│   ├── walls     extras {part: "walls", level: 0}  LOD2/3: walls with door gaps and lintels  mat:iwall
│   ├── space:0.10  extras {part: "space", kind: "room", id: "0.10", level: 0, capacity?}  floor patch
│   │               (kind corridor | room | stairs)   mat:room | mat:corridor | mat:stairs
│   └── flight:s1 extras {part: "flight", kind: "stairs", id: "s1", level: 0}   stairs up to the next level  mat:flight
├── L1 …
├── shaft         extras {part: "shaft"}     line segments: metro shaft under the metro_shaft entrance  mat:shaft
└── entrance:main extras {kind: "entrance", id, main, metro_shaft}   empty node at the entrance
```

LOD1 levels only have the `slab`. Slabs sit 0.15 m above their floor (above the path ribbons
of the ground), space patches 0.02 m above the slab. Walls are closed solids from just above
the patches to the next floor, so the viewer can cut a level with one clipping plane and
draw the inside of cut walls as a section.

Materials are named by kind (`mat:wall`, `mat:roof`, `mat:slab`, `mat:edge`, …). The viewer
replaces them with its own palette (`web/src/scene/palette.ts`), so the look is changed in
TypeScript without re-exporting. The style is clean architectural: flat colours, thin edges,
no textures.

### 10.3 `buildings/<id>.json`: `schemas.web.BuildingInfo`

What the inspector shows about one building, without parsing the glb. All outlines are in
**local metres**:

- `frame`, `lod`, `area_m2`, `height_m`;
- `footprint` and `footprint_holes`: counter-clockwise;
- `levels[{id, elevation, height, floor_y, spaces[]}]`: `spaces` holds the corridors, rooms
  and stairwells of LOD2/3 levels: `{id, kind, polygon, centre, size, area_m2, doors,
  name, capacity, bbox_min, bbox_max}` (`centre` is the label point, `size` the sides of the
  minimum rotated rectangle, `doors` the door positions, all local; the bbox is web);
- `entrances[{id, local, position, main, metro_shaft, osm_node}]`;
- `osm_outline` (rings) and `osm_hausdorff_m`: how far the modelled footprint is from OSM;
- `issues`.

### 10.4 `campus/context.glb` + `campus/context.json`: `schemas.web.ContextFeatures`

Every OSM building not covered by a building YAML, merged into **one mesh** (one draw call)
plus one `edges` line node.

- The mesh carries a custom vertex attribute `_FEATURE_ID` (float; three.js:
  `geometry.attributes._feature_id`).
- `context.json` lists the features; feature id = position in `features[]`:
  `{osm_id, name, building, height_m, height_source, index_start, index_count}`.
- `index_start` / `index_count` are the feature's range in the index buffer, so a feature
  can be highlighted with a draw range. Build BVHs over this mesh with
  `{indirect: true}`, otherwise three-mesh-bvh reorders the index.

### 10.5 `campus/ground.glb`

One root `ground` node with children identified by `extras.layer`:

- `ground`: the bbox plate, at y = 0.
- `paths:road`, `paths:footway`, `paths:steps`: walk edges buffered into ribbons (5, 2 and
  2.2 m wide), unioned per class.
- `boundary:<kind>`: the campus and Miasteczko outlines, as lines.
- `fences`: fences and walls, as lines.

### 10.6 Metro, ACO trace, trips and stats (inside replays)

These keep the formats below and now live inside a replay directory (10.10).

**`replays/<id>/metro.json`: `schemas.web.Metro`.** `topology`, `stations[{building_id, top,
platform}]` in line order, `tunnel` (platform-level polyline through the stations, closed for
a loop), `headway_s`, `dwell_s`, `speed_mps`, and `runs[{run_id, train_id, weekday,
direction, stops[{station, arrive_t, depart_t}]}]` (from `schedule.parquet`). The viewer
builds shafts, platforms, tunnels and trains from this and interpolates train positions
itself; no per-frame train data is stored.

**Binary containers.** Large arrays travel as a header + raw buffer pair: `<name>.json`
(header) + `<name>.bin` (little-endian).

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

**Student trips `replays/<id>/trips/<scenario>/…`.** 20 000 students × 5 days won't fit as
one-polyline-per-trip, but most students on the same room-to-room leg walk the same path.
Paths are therefore stored once and referenced by time-shifted segments.

`paths.json` + `paths.bin` (`PathsHeader`) holds every distinct path of the scenario, shared
by all days:

| buffer | dtype, shape | meaning |
|---|---|---|
| `path_offsets` | uint32 (P+1) | path p = vertices `path_offsets[p] … path_offsets[p+1]−1` |
| `xyz` | float32 (V, 3) | vertex positions |
| `t` | float32 (V) | seconds since the start of the path |
| `mode` | uint8 (P) | `0` walk, `1` metro (train ride from platform to platform), `2` bus / tram (stop to stop, straight, at street level) |

`day-<weekday>.json` + `.bin` (`DayHeader`) has one row per segment, sorted by `t_start`:

| buffer | dtype | meaning |
|---|---|---|
| `student_id` | uint32 (S) | |
| `leg_id` | uint32 (S) | link back to `simulation/<scenario>/legs.parquet` |
| `path_id` | uint32 (S) | into `paths` |
| `t_start` | float32 (S) | seconds since 00:00 of that day |

- A walking leg is one segment.
- A metro leg has three: the walk to the platform, the ride, and the walk out. Between
  segments of one leg the student stands at the end of the previous path (waiting on the
  platform).
- Between legs the student is in class and is not drawn.
- The student position at time `t` is the path interpolated at `t − t_start`.

**`replays/<id>/trace.json` + `.bin`: `AcoTraceHeader`.** The same buffers as `trace.npz`
(section 8.1) and the convergence curve (`curve_iteration` int32, `curve_best_s`,
`curve_iter_best_s`, `curve_iter_mean_s` float32: `convergence.csv`, or the sampled
iterations when it is missing). The header adds `run_id`, `algorithm`, `topology`, `k`,
`n_iterations`, `best_s`, `baseline_s`, the final `stations`, `candidate_ids`,
`candidate_tops` and `candidate_platforms` (web positions). The viewer draws candidates as
pins at their shafts, animates each sampled ant along its tour, and shows the pheromone
between candidates as ribbon width and opacity.

**Where replays come from.** `06_export_web.py --aco` turns every
`results/<run_id>/` with a `trace.npz` into `replays/aco-<run_id>/` (trace, `metro.json` of its
best line, replay.json). `--metro` turns `results/best_line.json` into
`replays/sim-<run_id>/` (kind `simulation`, trains only). `--sim` reads
`simulation/<scenario>/legs.parquet`, `demand/legs.parquet` and `network/*.parquet` and adds
`trips/` and `stats.json` to that replay (`metro_agh.web.export_sim`). Walking paths follow
the edges' polylines from `network.json`, matched by node key, so the web export must be of the
same campus; a ride path runs through the platforms it passes, with the timetable's times. The trains
follow `simulation/metro/schedule.parquet` when it is for the same line, else a timetable
built from `metro` in the config (`metro_agh.simulation.schedule`). Station positions come
from scene.json, so `--campus` runs first. `--fake` writes a synthetic run
(`data/processed/fake/results/`, same contracts as section 8) and a synthetic week:
`network/`, `population/`, `demand/` (random students and AGH time slots, not USOS) and
`simulation/` by the real stage-5 code, all under `data/processed/fake/`; then it exports both
replays. It is only for developing the viewer.

**`replays/<id>/stats.json`: `schemas.web.Stats`.**

- `scenarios.{no_metro, metro}`: `n_legs, total_travel_s, mean_leg_s, n_late, late_share,
  longer_than_break_share, metro_share, transit_share` (bus / tram).
- `saving_s`: total no_metro − total metro.
- `per_hour[{weekday, hour, n_legs, no_metro_s, metro_s}]`: the time-of-day chart; a leg
  counts in the hour it leaves in when walking (`no_metro` `depart_wt`), and `*_s` sum the
  door-to-door times (`arrive_wt − depart_wt`, waiting included).
- `stations[{building_id, boardings, alightings}]`.
- `top_od[{from_key, to_key, n_legs, saving_s}]`: the 50 largest savings.

The notebooks use the same numbers, computed from `simulation/*/legs.parquet`.

### 10.7 `network.json` + `.bin`: `schemas.web.NetworkHeader`

The whole walk graph of section 6.4 (outdoor, indoor, passages, stops, shafts), for drawing
and for the route tool:

| buffer | dtype, shape | meaning |
|---|---|---|
| `node_xyz` | float32 (N, 3) | node positions |
| `node_kind` | uint8 (N) | index into `node_kind_names` (the `GRAPH_NODES` kinds) |
| `edge_nodes` | uint32 (E, 2) | the two node indices of each edge (u, v) |
| `edge_kind` | uint8 (E) | index into `edge_kind_names`: `footway`, `road`, `steps` for outdoor edges, else the `GRAPH_EDGES` kind |
| `length_m` | float32 (E) | edge length |
| `time_uv_s`, `time_vu_s` | float32 (E) | walking time u → v and v → u |
| `segment_xyz` | float32 (S, 2, 3) | the edges' real polylines as segments, in edge order, for drawing |
| `segment_edge` | uint32 (S) | edge index of each segment |

The header also carries `node_keys` (per node, e.g. `osm:123`, `D-17/1.38`; OSM ids exceed
uint32), `endpoints` (endpoint key → node index), `edge_sources` (per edge: `way/1|way/2`, a
building id, a passage id), `barriers` (OSM point barriers with their web position) and
`measurements` (the rows of `field_measurements.csv`, so the route tool can compare).

### 10.8 `issues.json`: `schemas.web.IssueList`

`issues[{severity, section, message, building_id, osm_id, position}]`, the viewer's issues
panel. The list combines:

- the OSM stage issues (`data/processed/osm/issues.json`, the same entries as `report.md`);
- the checks the export runs on every building YAML:
  - the file fails validation (`error`);
  - the footprint is more than 1 m from the OSM outline;
  - the `osm_id` was not found;
  - the YAML has no entrances.

`position` is filled in so every row can be jumped to.

### 10.9 `status.json`: `schemas.web.BuildStatus`

`{version, built_at, changed[], errors[{file, line, loc, message, building_id, element}]}`,
written last by every export:

- `version` increases on every export.
- `changed` lists the data files written.
- `errors` lists building files that failed validation. Their old glb/json files are kept,
  so the viewer still shows the last good version. `line` is 1-based in the YAML, `loc` the
  pydantic location (`levels.0.rooms.2.width`), `element` the room, corridor, stairs or
  entrance id the error is about.

The status bar shows it. In dev, `web/plugins/metroData.ts` watches this file and sends it to
the page (HMR event `metro:data`), which refetches only the files in `changed`.

### 10.10 Replays: `replays/index.json` (`ReplayCatalog`) and `replays/<id>/replay.json` (`Replay`)

A **replay** is one thing the viewer can play back, chosen from the *Replays* menu: an
optimisation run (`kind: "aco"`) or a simulation (`kind: "simulation"`). Each one lives in
its own directory with a `replay.json`:

```json
{
  "id": "sim-mmas-k5-s42",
  "kind": "simulation",
  "title": "Week simulation, MMAS line k=5",
  "description": null,
  "created_at": "2026-10-09T09:00:00+02:00",
  "run_id": "mmas-k5-s42",
  "topology": "line",
  "stations": ["A-0", "B-1", "C-2", "D-17", "DS-7"],
  "scenarios": ["no_metro", "metro"],
  "weekdays": [1, 2, 3, 4, 5],
  "files": {
    "metro": "replays/sim-mmas-k5-s42/metro.json",
    "aco_trace": null,
    "trips": {
      "no_metro": "replays/sim-mmas-k5-s42/trips/no_metro",
      "metro": "replays/sim-mmas-k5-s42/trips/metro"
    },
    "stats": "replays/sim-mmas-k5-s42/stats.json"
  }
}
```

- `id` matches the directory name (lower case, digits, `_ . -`).
- File paths are relative to the data dir.
- An ACO replay normally has `aco_trace` (and `metro` for the best line).
- `replays/index.json` is rebuilt by every export from the `replay.json` files found,
  newest first.
- Several replays can exist side by side (different runs, configs or seeds). The viewer
  plays one at a time; choosing one switches to the Metro (ACO) or Simulation workspace and
  opens the playback dock.

### 10.11 `demand.json`: `schemas.web.Demand`

Weekly load on **walk-graph edges** for the viewer's **Demand** colour mode (path heatmap).

Built from `demand/od.parquet` routed on `network.json`: each OD pair's shortest walk
(Dijkstra on walk times) adds `n_legs` to every undirected edge on that path. Edge indices
match `NetworkHeader` / the polylines the viewer draws.

```json
{
  "provenance": { "...": "..." },
  "note": null,
  "unit": "legs_per_week",
  "n_edges": 6505,
  "max_n_legs": 12000,
  "edges": [{ "edge": 42, "n_legs": 12000 }, { "edge": 7, "n_legs": 9800 }]
}
```

`edges` lists non-zero loads only, busiest first. Written by `06_export_web.py` whenever
`od.parquet` is present (`--fake`, `--sim`, or next to `--campus`) and `network.json` exists.

---

## 11. Open questions

- **Buildings in USOS but not in the campus model**: `D12` (Kawiory 40, 173 meetings a term;
  OSM has no clear outline there), `U4` (no location in USOS), `U8` (Budryka 6, no classes).
  Their classes are dropped until they are modelled or aliased. `U13` (sports hall, 3200 PE
  meetings) is `U-13`, bootstrapped from OSM way/1166315212 via `osm_building_map.csv`. `D8`
  (51 rooms) is aliased to `H-D8` (same address, Reymonta 23; OSM has one outline there) until
  D-8 gets its own YAML.
- **Students in several course groups** (a base cohort and an elective pool) are modelled in one
  cohort; two USOS course groups for the same students (`ZIP-1S_2s_PP` and `ZIP-1S_2sem_PP`)
  are two cohorts, so the total is somewhat high.
- **Commuters' arrival**: stops are weighted by peak vehicles; the timetable of the ride itself
  (`transit/rides.csv`) is not yet used by the simulation.
- **Elevators**: not routed in v1 (stairs only).
- **Time-dependent closures** (gates open only at certain hours): not in v1; such ways go to
  `removed_ways` or stay open.
- **Terrain**: building `ground_elevation_m` is optional; until a DEM is added, the campus is
  flat (z = 0 at every anchor).

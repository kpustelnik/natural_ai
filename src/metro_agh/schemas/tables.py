"""Tabular contracts (CSV / Parquet) and a small validator for pandas DataFrames.

Every table that crosses a module boundary is declared here. Writers call
``TABLE.validate(df)`` before saving, readers may call it after loading.
Paths are relative to ``paths.processed`` (or ``paths.sample`` with --sample),
except where marked as hand-written (``data/campus``, ``data/validation``).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd
from pandas.api import types as ptypes

from .common import (
    BUILDING_ID_PATTERN,
    ENDPOINT_KEY_PATTERN,
    ROOM_ID_PATTERN,
    EdgeKind,
    HomeKind,
    LegKind,
    MetroTopology,
    Mode,
    NodeKind,
    Scenario,
    SizeSource,
    WeekParity,
)

DType = Literal["str", "int", "float", "bool", "list[int]"]

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Column:
    name: str
    dtype: DType
    description: str
    nullable: bool = False
    allowed: tuple[str, ...] | None = None
    pattern: str | None = None
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class Table:
    name: str
    path: str
    description: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...] = ()
    hand_written: bool = field(default=False)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def validate(self, df: pd.DataFrame) -> None:
        """Raise SchemaError listing every problem found."""
        problems: list[str] = []
        missing = [c for c in self.column_names if c not in df.columns]
        extra = [c for c in df.columns if c not in self.column_names]
        if missing:
            problems.append(f"missing columns {missing}")
        if extra:
            problems.append(f"unexpected columns {extra}")

        for col in self.columns:
            if col.name not in df.columns:
                continue
            problems += _check_column(col, df[col.name])

        if self.primary_key and not missing:
            dup = df.duplicated(list(self.primary_key)).sum()
            if dup:
                problems.append(f"{dup} duplicate rows on key {self.primary_key}")

        if problems:
            raise SchemaError(f"{self.name}: " + "; ".join(problems))

    def read(self, path: str | Path) -> pd.DataFrame:
        """Load and validate. Use this instead of pd.read_csv: room ids like '0.10'
        must stay strings."""
        path = Path(path)
        if path.suffix == ".csv":
            dtypes = {
                c.name: {"str": "string", "int": "Int64", "float": "float64", "bool": "boolean"}[
                    c.dtype
                ]
                for c in self.columns
                if c.dtype != "list[int]"
            }
            df = pd.read_csv(path, dtype=dtypes, keep_default_na=False, na_values=[""])
        else:
            df = pd.read_parquet(path)
        self.validate(df)
        return df

    def write(self, df: pd.DataFrame, path: str | Path) -> None:
        """Validate, then save with columns in contract order."""
        self.validate(df)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = df[self.column_names]
        if path.suffix == ".csv":
            df.to_csv(path, index=False, lineterminator="\n")
        else:
            df.to_parquet(path, index=False)


def _check_column(col: Column, s: pd.Series) -> list[str]:
    out: list[str] = []
    nulls = s.isna()
    if nulls.any() and not col.nullable:
        out.append(f"{col.name}: {int(nulls.sum())} null values")
    v = s[~nulls]
    if v.empty:
        return out

    if col.dtype == "str":
        if not (ptypes.is_string_dtype(v) or ptypes.is_object_dtype(v)):
            out.append(f"{col.name}: expected str, got {s.dtype}")
            return out
        v = v.astype(str)
    elif col.dtype == "int":
        if not ptypes.is_integer_dtype(v) and not (
            ptypes.is_float_dtype(v) and (v == v.round()).all()
        ):
            out.append(f"{col.name}: expected int, got {s.dtype}")
            return out
    elif col.dtype == "float":
        if not ptypes.is_numeric_dtype(v) or ptypes.is_bool_dtype(v):
            out.append(f"{col.name}: expected float, got {s.dtype}")
            return out
    elif col.dtype == "bool":
        if not ptypes.is_bool_dtype(v):
            out.append(f"{col.name}: expected bool, got {s.dtype}")
        return out
    elif col.dtype == "list[int]":
        if not v.map(lambda x: hasattr(x, "__len__") and not isinstance(x, str)).all():
            out.append(f"{col.name}: expected list of ints")
        return out

    if col.allowed is not None:
        bad = sorted(set(v) - set(col.allowed))
        if bad:
            out.append(f"{col.name}: values {bad[:5]} not in {list(col.allowed)}")
    if col.pattern is not None:
        rx = re.compile(col.pattern)
        bad = [x for x in v if not rx.match(x)]
        if bad:
            out.append(f"{col.name}: {len(bad)} values not matching {col.pattern}, e.g. {bad[:3]}")
    if col.min is not None and (v < col.min).any():
        out.append(f"{col.name}: values below {col.min}")
    if col.max is not None and (v > col.max).any():
        out.append(f"{col.name}: values above {col.max}")
    return out


def _values(enum) -> tuple[str, ...]:
    return tuple(e.value for e in enum)


WEEK_S = 7 * 24 * 3600

# --- USOS ------------------------------------------------------------------

TIMETABLE = Table(
    name="timetable",
    path="usos/timetable.csv",
    description="One row per weekly meeting slot of a class group. Only file using HH:MM.",
    primary_key=("activity_id",),
    columns=(
        Column("activity_id", "str", "unique id of the meeting slot"),
        Column("group_id", "str", "class group, e.g. 'IS-ISI-3:LAB:2'"),
        Column("weekday", "int", "1 = Monday ... 5 = Friday", min=1, max=5),
        Column("start", "str", "local time HH:MM", pattern=_HHMM),
        Column("end", "str", "local time HH:MM", pattern=_HHMM),
        Column("week_parity", "str", "which weeks it runs", allowed=_values(WeekParity)),
        Column("building_id", "str", "canonical building code", pattern=BUILDING_ID_PATTERN),
        Column(
            "room_id", "str", "room number, null if unknown", nullable=True, pattern=ROOM_ID_PATTERN
        ),
    ),
)

GROUPS = Table(
    name="groups",
    path="usos/groups.csv",
    description="Class groups (course x class type x group number).",
    primary_key=("group_id",),
    columns=(
        Column("group_id", "str", "class group id"),
        Column("course_id", "str", "USOS course id"),
        Column("course_name", "str", "human readable name", nullable=True),
        Column("class_type", "str", "USOS class type code: WYK, CW, LAB, PROJ, SEM, ..."),
        Column("size", "int", "number of students", min=1),
        Column("size_source", "str", "where size comes from", allowed=_values(SizeSource)),
    ),
)

COHORTS = Table(
    name="cohorts",
    path="usos/cohorts.csv",
    description="Students of one programme and semester; the unit of population synthesis.",
    primary_key=("cohort_id",),
    columns=(
        Column("cohort_id", "str", "programme + semester, e.g. 'IS-ISI-3'"),
        Column("programme", "str", "programme code"),
        Column("semester", "int", "semester number", min=1),
        Column("n_students", "int", "cohort size", min=1),
        Column("size_source", "str", "where size comes from", allowed=_values(SizeSource)),
    ),
)

GROUP_COHORTS = Table(
    name="group_cohorts",
    path="usos/group_cohorts.csv",
    description="Which cohorts attend a group. A lecture usually maps to several cohorts.",
    primary_key=("group_id", "cohort_id"),
    columns=(
        Column("group_id", "str", "class group id"),
        Column("cohort_id", "str", "cohort id"),
    ),
)

ROOM_MAP = Table(
    name="usos_room_map",
    path="data/campus/usos_room_map.csv",
    description="Hand-written fixes: raw USOS room strings that automatic parsing gets wrong.",
    primary_key=("usos_room",),
    hand_written=True,
    columns=(
        Column("usos_room", "str", "room string exactly as USOS returns it"),
        Column("building_id", "str", "canonical building", pattern=BUILDING_ID_PATTERN),
        Column("room_id", "str", "room in that building", nullable=True, pattern=ROOM_ID_PATTERN),
        Column("note", "str", "why", nullable=True),
    ),
)

# --- population ------------------------------------------------------------

STUDENTS = Table(
    name="students",
    path="population/students.parquet",
    description="Synthetic students (no real people).",
    primary_key=("student_id",),
    columns=(
        Column("student_id", "int", "0..n_students-1", min=0),
        Column("cohort_id", "str", "cohort"),
        Column("home_kind", "str", "dorm or stop", allowed=_values(HomeKind)),
        Column("home_key", "str", "dorm building id or stop id", pattern=ENDPOINT_KEY_PATTERN),
    ),
)

ENROLLMENTS = Table(
    name="enrollments",
    path="population/enrollments.parquet",
    description="Synthetic student -> class group membership.",
    primary_key=("student_id", "group_id"),
    columns=(
        Column("student_id", "int", "student", min=0),
        Column("group_id", "str", "class group"),
    ),
)

# --- demand ----------------------------------------------------------------

LEGS = Table(
    name="legs",
    path="demand/legs.parquet",
    description="One row per required movement of one student in the modelled week.",
    primary_key=("leg_id",),
    columns=(
        Column("leg_id", "int", "unique, stable within one build", min=0),
        Column("student_id", "int", "student", min=0),
        Column("weekday", "int", "1..5", min=1, max=5),
        Column("seq", "int", "order of the leg within the student's day", min=0),
        Column("kind", "str", "leg type", allowed=_values(LegKind)),
        Column("from_key", "str", "endpoint key", pattern=ENDPOINT_KEY_PATTERN),
        Column("to_key", "str", "endpoint key", pattern=ENDPOINT_KEY_PATTERN),
        Column(
            "earliest_depart_wt",
            "int",
            "end of previous class; null for home_to_class",
            nullable=True,
            min=0,
            max=WEEK_S,
        ),
        Column(
            "deadline_wt",
            "int",
            "start of next class; null for class_to_home",
            nullable=True,
            min=0,
            max=WEEK_S,
        ),
        Column("break_s", "int", "deadline - earliest_depart, null if open", nullable=True, min=0),
    ),
)

OD = Table(
    name="od",
    path="demand/od.parquet",
    description="Legs aggregated over the week: the demand ACO optimises for.",
    primary_key=("from_key", "to_key"),
    columns=(
        Column("from_key", "str", "endpoint key", pattern=ENDPOINT_KEY_PATTERN),
        Column("to_key", "str", "endpoint key", pattern=ENDPOINT_KEY_PATTERN),
        Column("n_legs", "int", "student-legs per week", min=1),
    ),
)

# --- network ---------------------------------------------------------------

GRAPH_NODES = Table(
    name="graph_nodes",
    path="network/nodes.parquet",
    description="Walk graph nodes: OSM outdoor network + generated indoor graph + metro access.",
    primary_key=("node_id",),
    columns=(
        Column("node_id", "int", "dense index 0..n-1, valid only within one build", min=0),
        Column("key", "str", "stable readable id, e.g. 'osm:123', 'D-17/1.38', 'D-17:c0@12.5'"),
        Column("kind", "str", "node type", allowed=_values(NodeKind)),
        Column("x", "float", "EPSG:2180 easting, m"),
        Column("y", "float", "EPSG:2180 northing, m"),
        Column("z", "float", "absolute height, m"),
        Column("building_id", "str", "null outdoors", nullable=True, pattern=BUILDING_ID_PATTERN),
        Column("level", "int", "null outdoors", nullable=True),
        Column(
            "endpoint_key",
            "str",
            "set on trip endpoints",
            nullable=True,
            pattern=ENDPOINT_KEY_PATTERN,
        ),
    ),
)

GRAPH_EDGES = Table(
    name="graph_edges",
    path="network/edges.parquet",
    description="Undirected edges with direction-dependent walking times (stairs up != down).",
    primary_key=("u", "v"),
    columns=(
        Column("u", "int", "node_id", min=0),
        Column("v", "int", "node_id", min=0),
        Column("kind", "str", "edge type", allowed=_values(EdgeKind)),
        Column("length_m", "float", "3D length", min=0),
        Column("time_uv_s", "float", "walking time u -> v", min=0),
        Column("time_vu_s", "float", "walking time v -> u", min=0),
        Column("source", "str", "osm way id, building id or passage id", nullable=True),
    ),
)

# --- simulation ------------------------------------------------------------

SIM_LEGS = Table(
    name="sim_legs",
    path="simulation/{scenario}/legs.parquet",
    description="Result of every leg of every student for one scenario.",
    primary_key=("leg_id",),
    columns=(
        Column("leg_id", "int", "same as demand/legs.parquet", min=0),
        Column("student_id", "int", "student", min=0),
        Column("scenario", "str", "scenario", allowed=_values(Scenario)),
        Column("mode", "str", "chosen mode", allowed=_values(Mode)),
        Column("depart_wt", "int", "leaves the origin", min=0, max=WEEK_S),
        Column("arrive_wt", "int", "reaches the destination", min=0, max=WEEK_S),
        Column("walk_s", "float", "time walking incl. stairs and shafts", min=0),
        Column("wait_s", "float", "time waiting on the platform", min=0),
        Column("ride_s", "float", "time in the train", min=0),
        Column("board_station", "str", "building id", nullable=True, pattern=BUILDING_ID_PATTERN),
        Column("alight_station", "str", "building id", nullable=True, pattern=BUILDING_ID_PATTERN),
        Column("late_s", "float", "max(0, arrive - deadline); 0 if no deadline", min=0),
        Column("path_nodes", "list[int]", "node_ids walked, metro ride is board->alight"),
    ),
)

METRO_SCHEDULE = Table(
    name="metro_schedule",
    path="simulation/metro/schedule.parquet",
    description="Every stop of every train run in the modelled week.",
    primary_key=("run_id", "stop_seq"),
    columns=(
        Column("run_id", "int", "one train trip end to end", min=0),
        Column("train_id", "int", "physical train", min=0),
        Column("weekday", "int", "1..5", min=1, max=5),
        Column("direction", "int", "+1 along station order, -1 against", min=-1, max=1),
        Column("stop_seq", "int", "0.. within the run", min=0),
        Column("station", "str", "building id", pattern=BUILDING_ID_PATTERN),
        Column("arrive_wt", "int", "arrival", min=0, max=WEEK_S),
        Column("depart_wt", "int", "departure", min=0, max=WEEK_S),
    ),
)

# --- experiments -----------------------------------------------------------

CONVERGENCE = Table(
    name="convergence",
    path="experiments/results/{run_id}/convergence.csv",
    description="One row per ACO / baseline iteration.",
    primary_key=("iteration",),
    columns=(
        Column("iteration", "int", "0..", min=0),
        Column("evaluations", "int", "cumulative objective evaluations", min=0),
        Column("best_s", "float", "best-so-far objective", min=0),
        Column("iter_best_s", "float", "best in this iteration", min=0),
        Column("iter_mean_s", "float", "mean in this iteration", min=0),
        Column("tau_min", "float", "pheromone bounds (null for baselines)", nullable=True),
        Column("tau_max", "float", "pheromone bounds (null for baselines)", nullable=True),
        Column(
            "pheromone_entropy",
            "float",
            "normalised 0..1, null for baselines",
            nullable=True,
            min=0,
            max=1,
        ),
    ),
)

RUNS = Table(
    name="runs",
    path="experiments/results/runs.csv",
    description="One row per optimisation run; input for boxplots and statistical tests.",
    primary_key=("run_id",),
    columns=(
        Column("run_id", "str", "unique run directory name"),
        Column("experiment", "str", "experiment config name"),
        Column("algorithm", "str", "mmas, acs, random, greedy, brute_force"),
        Column("topology", "str", "line or loop", allowed=_values(MetroTopology)),
        Column("k", "int", "number of stations", min=2),
        Column("n_candidates", "int", "N", min=2),
        Column("seed", "int", "RNG seed"),
        Column("eval_budget", "int", "max objective evaluations", min=1),
        Column("evaluations", "int", "evaluations used", min=1),
        Column("evaluations_to_best", "int", "when the final best was found", min=0),
        Column("best_s", "float", "objective of the best line", min=0),
        Column("baseline_s", "float", "objective without metro", min=0),
        Column("optimum_s", "float", "brute-force optimum, if known", nullable=True, min=0),
        Column("wall_time_s", "float", "runtime", min=0),
        Column("stations", "str", "best line, building ids joined with '|'"),
        Column("params_json", "str", "algorithm parameters as JSON"),
    ),
)

FIELD_MEASUREMENTS = Table(
    name="field_measurements",
    path="data/validation/field_measurements.csv",
    description="Walking times measured on campus, compared with the graph (validation 5).",
    primary_key=("route_id", "date", "who"),
    hand_written=True,
    columns=(
        Column("route_id", "str", "short id, e.g. 'r01'"),
        Column("from_key", "str", "endpoint key", pattern=ENDPOINT_KEY_PATTERN),
        Column("to_key", "str", "endpoint key", pattern=ENDPOINT_KEY_PATTERN),
        Column("measured_s", "float", "stopwatch time", min=0),
        Column("date", "str", "YYYY-MM-DD", pattern=r"^\d{4}-\d{2}-\d{2}$"),
        Column("who", "str", "initials"),
        Column("notes", "str", "route taken, crowding, weather", nullable=True),
    ),
)

ALL_TABLES: tuple[Table, ...] = (
    TIMETABLE,
    GROUPS,
    COHORTS,
    GROUP_COHORTS,
    ROOM_MAP,
    STUDENTS,
    ENROLLMENTS,
    LEGS,
    OD,
    GRAPH_NODES,
    GRAPH_EDGES,
    SIM_LEGS,
    METRO_SCHEDULE,
    CONVERGENCE,
    RUNS,
    FIELD_MEASUREMENTS,
)

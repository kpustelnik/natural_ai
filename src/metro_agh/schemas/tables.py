"""Tabular contracts (CSV / Parquet / GeoPackage layers) and a small validator for DataFrames.

Every table that crosses a module boundary is declared here. Writers call
``TABLE.validate(df)`` before saving, readers may call it after loading.
Paths are relative to ``paths.processed`` (also with --sample, which only swaps the campus),
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
    STOP_ID_PATTERN,
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
    # geo tables: GeoPackage layer name and allowed geometry types of the "geometry" column
    layer: str | None = None
    geometry: tuple[str, ...] | None = None

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def validate(self, df: pd.DataFrame) -> None:
        """Raise SchemaError listing every problem found."""
        problems: list[str] = []
        missing = [c for c in self.column_names if c not in df.columns]
        extra = [c for c in df.columns if c not in self.column_names and c != "geometry"]
        if self.geometry is not None:
            if "geometry" not in df.columns:
                missing.append("geometry")
            else:
                types = set(df.geometry.geom_type.dropna())
                if not types <= set(self.geometry):
                    problems.append(f"geometry types {sorted(types)} not in {self.geometry}")
        elif "geometry" in df.columns:
            extra.append("geometry")
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
        elif self.layer is not None:
            import geopandas as gpd

            df = gpd.read_file(path, layer=self.layer)
        else:
            df = pd.read_parquet(path)
        self.validate(df)
        return df

    def write(self, df: pd.DataFrame, path: str | Path) -> None:
        """Validate, then save with columns in contract order."""
        self.validate(df)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = df[self.column_names + (["geometry"] if self.geometry else [])]
        if self.layer is not None:
            df.to_file(path, layer=self.layer, driver="GPKG")
        elif path.suffix == ".csv":
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
        if not all(hasattr(x, "__len__") and not isinstance(x, str) for x in v):
            out.append(f"{col.name}: expected list of ints")
        return out

    distinct = pd.unique(v) if col.allowed is not None or col.pattern is not None else ()
    if col.allowed is not None:
        bad = sorted(set(distinct) - set(col.allowed))
        if bad:
            out.append(f"{col.name}: values {bad[:5]} not in {list(col.allowed)}")
    if col.pattern is not None:
        rx = re.compile(col.pattern)
        bad = [x for x in distinct if not rx.match(x)]
        if bad:
            out.append(
                f"{col.name}: {len(bad)} distinct values not matching {col.pattern}, e.g. {bad[:3]}"
            )
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
        Column("size", "int", "number of students used by the demand", min=1),
        Column("size_source", "str", "where size comes from", allowed=_values(SizeSource)),
        Column(
            "enrolled", "int", "USOS 'liczba osób w grupie'; null if unknown", nullable=True, min=0
        ),
        Column(
            "limit",
            "int",
            "USOS 'limit miejsc' (group, else unit); null = none",
            nullable=True,
            min=0,
        ),
        Column(
            "room_capacity", "int", "seats of the smallest room it meets in", nullable=True, min=0
        ),
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
        Column(
            "semester",
            "int",
            "semester number; null for a single-course cohort",
            nullable=True,
            min=0,
        ),
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

ROOMS = Table(
    name="rooms",
    path="usos/rooms.csv",
    description="Every USOS room with its seats and the canonical building / room it maps to.",
    primary_key=("room_usos_id",),
    columns=(
        Column("room_usos_id", "str", "USOS room id"),
        Column("building_usos_id", "str", "USOS building id, e.g. D17", nullable=True),
        Column("number", "str", "room number as in USOS, e.g. 1.38", nullable=True),
        Column(
            "building_id",
            "str",
            "canonical building; null = not modelled",
            nullable=True,
            pattern=BUILDING_ID_PATTERN,
        ),
        Column("room_id", "str", "room id in the building", nullable=True, pattern=ROOM_ID_PATTERN),
        Column("capacity", "int", "seats (USOS geo/rooms)", nullable=True, min=0),
    ),
)

# --- the whole USOS term (usos/all/, full crawl) --------------------------------

_DATE = r"^\d{4}-\d{2}-\d{2}$"

COURSE_GROUPS = Table(
    name="course_groups",
    path="usos/all/course_groups.csv",
    description="Every USOS course group ('grupa przedmiotów'): programme x semester, or a pool.",
    primary_key=("code",),
    columns=(
        Column("code", "str", "USOS code, e.g. 240-INF-1S-1R-Z"),
        Column("cohort_id", "str", "the code as a cohort id in cohorts.csv"),
        Column("label", "str", "USOS name, e.g. '240_Informatyka, stacjonarne, 1 semestr'"),
        Column("faculty_id", "str", "unit listing it, e.g. 240-000", nullable=True),
        Column("programme", "str", "code without the semester part"),
        Column("semester", "int", "null for pools (electives, languages)", nullable=True, min=0),
        Column("level", "str", "cycle and mode: 1S, 2S, 1N, ...", nullable=True),
        Column("n_courses", "int", "courses listed in the group", min=0),
    ),
)

COURSES = Table(
    name="courses",
    path="usos/all/courses.csv",
    description="Every course found in the term (catalogue of every faculty + room plans).",
    primary_key=("course_id",),
    columns=(
        Column("course_id", "str", "USOS course code"),
        Column("course_name", "str", "name", nullable=True),
        Column("faculty_id", "str", "unit running it", nullable=True),
        Column("course_groups", "str", "course groups listing it, '|'-joined", nullable=True),
        Column("n_units", "int", "class types (units) in the term", min=0),
        Column("n_groups", "int", "class groups in the term", min=0),
        Column("enrolled", "int", "registered students of its largest unit", nullable=True, min=0),
    ),
)

CLASS_GROUPS = Table(
    name="class_groups",
    path="usos/all/class_groups.csv",
    description="Every class group of the term, wherever and whenever it meets.",
    primary_key=("group_id",),
    columns=(
        Column("group_id", "str", "same id as groups.csv / timetable.csv"),
        Column("unit_id", "int", "USOS zaj_cyk_id", min=0),
        Column("course_id", "str", "course code"),
        Column("class_type", "str", "W, CWA, CWL, CWP, LEKT, WF, ...", nullable=True),
        Column("class_type_name", "str", "e.g. 'ćwiczenia laboratoryjne'", nullable=True),
        Column("group_nr", "int", "group number in the unit", min=0),
        Column("enrolled", "int", "USOS 'liczba osób w grupie'", nullable=True, min=0),
        Column("limit", "int", "USOS 'limit miejsc' (group, else unit)", nullable=True, min=0),
        Column("hours", "int", "hours of the unit in the term", nullable=True, min=0),
        Column("terms", "str", "meeting texts, e.g. 'każdy wtorek, 09:45-11:15'", nullable=True),
        Column("rooms", "str", "USOS room ids, '|'-joined", nullable=True),
    ),
)

MEETINGS = Table(
    name="meetings",
    path="usos/all/meetings.csv",
    description="Every dated meeting of every class group in the term (USOS tt/classgroups).",
    columns=(
        Column("date", "str", "YYYY-MM-DD", pattern=_DATE),
        Column("weekday", "int", "1 = Monday ... 7 = Sunday", min=1, max=7),
        Column("start", "str", "HH:MM", pattern=_HHMM),
        Column("end", "str", "HH:MM", pattern=_HHMM),
        Column("unit_id", "int", "USOS zaj_cyk_id", nullable=True, min=0),
        Column("group_nr", "int", "group number", nullable=True, min=0),
        Column("group_id", "str", "class_groups.group_id", nullable=True),
        Column("course_id", "str", "course code", nullable=True),
        Column("class_type", "str", "class type code", nullable=True),
        Column(
            "kind",
            "str",
            "USOS activity type: classgroup (from the weekly pattern), "
            "classgroup2 (a confirmed meeting), ...",
            nullable=True,
        ),
        Column("building_usos_id", "str", "USOS building id", nullable=True),
        Column(
            "building_id",
            "str",
            "canonical building; null = not in the campus model",
            nullable=True,
            pattern=BUILDING_ID_PATTERN,
        ),
        Column("room_usos_id", "str", "USOS room id", nullable=True),
        Column("room_number", "str", "room number", nullable=True),
        Column("frequency", "str", "USOS frequency code (classgroup only)", nullable=True),
    ),
)

ROOM_MAP = Table(
    name="usos_room_map",
    path="data/campus/usos_room_map.csv",
    description="Hand-written fixes: raw USOS room strings that automatic parsing gets wrong.",
    primary_key=("usos_room",),
    hand_written=True,
    columns=(
        Column("usos_room", "str", "USOS building id / room number, e.g. 'D17/1.38'"),
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

DORMS = Table(
    name="dorms",
    path="population/dorms.csv",
    description="Beds per dorm: from the YAML, or estimated from the floor area.",
    primary_key=("building_id",),
    columns=(
        Column("building_id", "str", "dorm building", pattern=BUILDING_ID_PATTERN),
        Column("name", "str", "dorm name", nullable=True),
        Column("floor_area_m2", "float", "footprint x storeys", nullable=True, min=0),
        Column("levels", "int", "storeys above ground", min=1),
        Column("residents", "int", "AGH students living there", min=0),
        Column("source", "str", "yaml or estimate", allowed=("yaml", "estimate")),
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

MIGRATIONS = Table(
    name="migrations",
    path="demand/migrations.csv",
    description="Student flows between buildings (and stops) per weekday and departure hour.",
    primary_key=("weekday", "hour", "kind", "from_place", "to_place"),
    columns=(
        Column("weekday", "int", "1..5", min=1, max=5),
        Column(
            "hour",
            "int",
            "hour of the departure (end of class, or deadline from home)",
            min=0,
            max=23,
        ),
        Column("kind", "str", "leg type", allowed=_values(LegKind)),
        Column("from_place", "str", "building id or stop id", pattern=ENDPOINT_KEY_PATTERN),
        Column("to_place", "str", "building id or stop id", pattern=ENDPOINT_KEY_PATTERN),
        Column("n_legs", "int", "student-legs", min=1),
        Column("median_break_s", "int", "median time between the classes", nullable=True, min=0),
    ),
)

# --- public transport (GTFS) --------------------------------------------------

TRANSIT_STOPS = Table(
    name="transit_stops",
    path="transit/stops.csv",
    description="Bus / tram stops in the campus bbox (platforms merged by name), one weekday.",
    primary_key=("stop_id",),
    columns=(
        Column("stop_id", "str", "stop:<slug of the name>", pattern=STOP_ID_PATTERN),
        Column("name", "str", "GTFS stop name"),
        Column("lon", "float", "mean of the platforms", min=-180, max=180),
        Column("lat", "float", "mean of the platforms", min=-90, max=90),
        Column("modes", "str", "bus, tram or bus|tram"),
        Column("n_platforms", "int", "GTFS stops merged", min=1),
        Column("lines", "str", "line numbers, space separated"),
        Column("arrivals_peak", "int", "vehicles arriving in transit.peak_hours", min=0),
        Column("arrivals_day", "int", "vehicles arriving 06:00-21:00", min=0),
        Column("headway_peak_s", "int", "peak hours / arrivals_peak", nullable=True, min=0),
        Column("weight", "float", "peak arrivals x seats / 1000: campus.yaml stop weight", min=0),
    ),
)

TRANSIT_RIDES = Table(
    name="transit_rides",
    path="transit/rides.csv",
    description="Direct bus / tram rides between two campus stops, 06:00-21:00 of one weekday.",
    primary_key=("from_stop", "to_stop"),
    columns=(
        Column("from_stop", "str", "stop id", pattern=STOP_ID_PATTERN),
        Column("to_stop", "str", "stop id", pattern=STOP_ID_PATTERN),
        Column("lines", "str", "line numbers, space separated"),
        Column("trips_day", "int", "trips serving the pair", min=1),
        Column("min_ride_s", "int", "shortest in-vehicle time", min=0),
        Column("median_ride_s", "int", "median in-vehicle time", min=0),
        Column("median_headway_s", "int", "median gap between departures", nullable=True, min=0),
    ),
)

TRANSIT_TRIPS = Table(
    name="transit_trips",
    path="transit/trips.parquet",
    description="Every direct ride between two campus stops on the GTFS day (06:00-21:00).",
    columns=(
        Column("from_stop", "str", "stop id", pattern=STOP_ID_PATTERN),
        Column("to_stop", "str", "stop id", pattern=STOP_ID_PATTERN),
        Column("line", "str", "line number"),
        Column("dep_s", "int", "departure from from_stop, seconds after midnight", min=0),
        Column("arr_s", "int", "arrival at to_stop, seconds after midnight", min=0),
    ),
)

# --- OSM (data/processed/osm/campus.gpkg, all layers in EPSG:2180) --------------

_OSM_GPKG = "osm/campus.gpkg"
_POLY = ("Polygon", "MultiPolygon")


def _str(name: str, description: str, nullable: bool = True, **kw) -> Column:
    return Column(name, "str", description, nullable=nullable, **kw)


OSM_CATEGORIES = ("academic", "dorm", "other", "connector", "context")

OSM_BOUNDARY = Table(
    name="osm_boundary",
    path=_OSM_GPKG,
    layer="boundary",
    geometry=_POLY,
    description="AGH campus area, Miasteczko Studenckie (derived from dorms) and the bbox.",
    primary_key=("kind",),
    columns=(
        _str("kind", "agh_campus | miasteczko | bbox", nullable=False),
        _str("name", "label"),
        _str("osm_id", "source element, e.g. relation/3830877"),
    ),
)

OSM_BUILDINGS = Table(
    name="osm_buildings",
    path=_OSM_GPKG,
    layer="buildings",
    geometry=_POLY,
    description="Every OSM building in the bbox; AGH buildings merged per building_id.",
    primary_key=("osm_id",),
    columns=(
        _str("osm_id", "largest OSM element, e.g. way/181823531", nullable=False),
        _str("osm_ids", "all merged elements joined with '|'", nullable=False),
        _str("building_id", "AGH code; null for context buildings", pattern=BUILDING_ID_PATTERN),
        _str("category", "classification", nullable=False, allowed=OSM_CATEGORIES),
        _str("ref", "raw OSM ref tag"),
        _str("name", "OSM name"),
        _str("building", "OSM building tag", nullable=False),
        Column("levels", "float", "building:levels", nullable=True, min=0),
        Column("levels_underground", "float", "building:levels:underground", nullable=True, min=0),
        Column("roof_levels", "float", "roof:levels", nullable=True, min=0),
        Column("height_m", "float", "height used for 3D", min=0),
        _str(
            "height_source",
            "tag | levels | default",
            nullable=False,
            allowed=("tag", "levels", "default"),
        ),
        _str("connects", "connectors: the two building ids joined with '|'"),
        Column("main_entrance_node", "int", "OSM node of the main entrance", nullable=True),
        Column("n_entrances", "int", "entrance nodes on the outline", min=0),
    ),
)

OSM_ENTRANCES = Table(
    name="osm_entrances",
    path=_OSM_GPKG,
    layer="entrances",
    geometry=("Point",),
    description="OSM entrance nodes, assigned to the building whose outline they lie on.",
    primary_key=("osm_node",),
    columns=(
        Column("osm_node", "int", "OSM node id"),
        _str("entrance", "OSM entrance tag: main, yes, service, emergency, ...", nullable=False),
        _str("name", "OSM name"),
        _str("ref", "OSM ref"),
        _str("level", "OSM level"),
        _str("access", "OSM access"),
        _str("wheelchair", "OSM wheelchair"),
        _str(
            "building_id",
            "AGH building, null if not on an AGH building",
            pattern=BUILDING_ID_PATTERN,
        ),
        _str("building_osm_id", "building element it lies on (any category)"),
        Column("is_main", "bool", "chosen main entrance of its AGH building"),
    ),
)

OSM_STOPS = Table(
    name="osm_stops",
    path=_OSM_GPKG,
    layer="stops",
    geometry=("Point",),
    description="Bus/tram stops: platforms grouped by name, point = their centre.",
    primary_key=("stop_id",),
    columns=(
        _str("stop_id", "stop:<slug>", nullable=False, pattern=r"^stop:[a-z0-9_]+$"),
        _str("name", "stop name without the platform number", nullable=False),
        _str("modes", "bus, tram or bus|tram", nullable=False),
        Column("n_platforms", "int", "platforms merged", min=1),
        _str("platform_ids", "OSM elements joined with '|'", nullable=False),
    ),
)

OSM_BARRIERS = Table(
    name="osm_barriers",
    path=_OSM_GPKG,
    layer="barriers",
    geometry=("Point",),
    description="Point barriers on paths: gates, bollards, turnstiles, ...",
    primary_key=("osm_id",),
    columns=(
        _str("osm_id", "OSM element", nullable=False),
        _str("barrier", "OSM barrier tag", nullable=False),
        _str("access", "OSM access"),
        _str("name", "OSM name"),
    ),
)

OSM_FENCES = Table(
    name="osm_fences",
    path=_OSM_GPKG,
    layer="fences",
    geometry=("LineString", "MultiLineString", "Polygon", "MultiPolygon"),
    description="Linear barriers: fences, walls, hedges (for viewing and later graph checks).",
    primary_key=("osm_id",),
    columns=(
        _str("osm_id", "OSM element", nullable=False),
        _str("barrier", "OSM barrier tag", nullable=False),
        _str("access", "OSM access"),
    ),
)

OSM_WALK_NODES = Table(
    name="osm_walk_nodes",
    path=_OSM_GPKG,
    layer="walk_nodes",
    geometry=("Point",),
    description="Outdoor walk network nodes (osmnx, simplified).",
    primary_key=("osm_node",),
    columns=(
        Column("osm_node", "int", "OSM node id"),
        Column("street_count", "int", "number of incident streets", min=0),
        _str("highway", "OSM highway tag of the node (crossing, ...)"),
        _str("barrier", "OSM barrier on the node"),
        _str("access", "OSM access of the node"),
        _str("entrance", "OSM entrance tag, if the node is an entrance"),
    ),
)

OSM_WALK_EDGES = Table(
    name="osm_walk_edges",
    path=_OSM_GPKG,
    layer="walk_edges",
    geometry=("LineString",),
    description="Outdoor walk network edges (undirected, simplified). Raw OSM tags kept as text.",
    primary_key=("u", "v", "key"),
    columns=(
        Column("u", "int", "osm_node"),
        Column("v", "int", "osm_node"),
        Column("key", "int", "parallel edge index", min=0),
        _str("osm_ways", "OSM way ids joined with '|'", nullable=False),
        _str("highway", "footway, steps, service, ...; '|'-joined if merged", nullable=False),
        _str("name", "street / path name"),
        Column("length_m", "float", "length", min=0),
        Column("is_steps", "bool", "contains highway=steps"),
        Column("step_count", "float", "OSM step_count", nullable=True, min=0),
        _str("incline", "OSM incline (up/down/percent)"),
        _str("access", "OSM access"),
        _str("foot", "OSM foot"),
        _str("covered", "OSM covered"),
        _str("tunnel", "OSM tunnel"),
        _str("bridge", "OSM bridge"),
        _str("indoor", "OSM indoor"),
        _str("level", "OSM level"),
        _str("surface", "OSM surface"),
    ),
)

OSM_BUILDING_MAP = Table(
    name="osm_building_map",
    path="data/campus/osm_building_map.csv",
    description="Hand-written fixes of OSM building classification.",
    primary_key=("osm_id",),
    hand_written=True,
    columns=(
        _str("osm_id", "OSM element, e.g. way/230301584", nullable=False),
        _str(
            "building_id",
            "AGH code to assign; empty = make it context",
            pattern=BUILDING_ID_PATTERN,
        ),
        _str("category", "override category; empty = derive", allowed=OSM_CATEGORIES),
        _str("note", "why"),
    ),
)

OSM_TABLES = (
    OSM_BOUNDARY,
    OSM_BUILDINGS,
    OSM_ENTRANCES,
    OSM_STOPS,
    OSM_BARRIERS,
    OSM_FENCES,
    OSM_WALK_NODES,
    OSM_WALK_EDGES,
)

# --- network ---------------------------------------------------------------

GRAPH_NODES = Table(
    name="graph_nodes",
    path="network/nodes.parquet",
    description="Walk graph nodes: OSM outdoor network + generated indoor graph + metro access.",
    primary_key=("node_id",),
    columns=(
        Column("node_id", "int", "dense index 0..n-1, valid only within one build", min=0),
        Column("key", "str", "stable readable id, e.g. 'osm:123', 'D-17/1.38', 'D-17:c0@12.50'"),
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
        Column(
            "board_station",
            "str",
            "metro: station building id; transit: stop id",
            nullable=True,
            pattern=ENDPOINT_KEY_PATTERN,
        ),
        Column(
            "alight_station",
            "str",
            "metro: station building id; transit: stop id",
            nullable=True,
            pattern=ENDPOINT_KEY_PATTERN,
        ),
        Column("late_s", "float", "max(0, arrive - deadline); 0 if no deadline", min=0),
        Column(
            "path_nodes", "list[int]", "node_ids walked; a ride (metro, transit) is board->alight"
        ),
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
        Column(
            "eval_budget",
            "int",
            "optimize.max_evaluations, else for the colonies and random search the lines the "
            "ants build (local search evaluates more on top); greedy: its own evaluations; "
            "brute force: every line",
            min=1,
        ),
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
    *OSM_TABLES,
    OSM_BUILDING_MAP,
    TIMETABLE,
    GROUPS,
    COHORTS,
    GROUP_COHORTS,
    ROOMS,
    COURSE_GROUPS,
    COURSES,
    CLASS_GROUPS,
    MEETINGS,
    ROOM_MAP,
    DORMS,
    STUDENTS,
    ENROLLMENTS,
    LEGS,
    OD,
    MIGRATIONS,
    TRANSIT_STOPS,
    TRANSIT_RIDES,
    TRANSIT_TRIPS,
    GRAPH_NODES,
    GRAPH_EDGES,
    SIM_LEGS,
    METRO_SCHEDULE,
    CONVERGENCE,
    RUNS,
    FIELD_MEASUREMENTS,
)

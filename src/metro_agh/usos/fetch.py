"""Crawl of AGH USOS for one term: rooms -> timetable tiles -> courses -> class groups.

Sources (both public, no login, no API key):

- USOS API ``apps.usos.agh.edu.pl/services`` (anonymous methods): buildings, their rooms and
  room capacities (``geo/building_index``, ``geo/building2``, ``geo/rooms``), terms;
- USOSweb catalogue ``web.usos.agh.edu.pl`` (parsed in ``pages.py``): the weekly plan of
  every didactic room, the course pages (cohorts = course groups) and the class-group
  pages (meetings, "liczba osób w grupie / limit miejsc").

The room plans only *discover* courses: USOSweb shows the current week, so a course that
meets only in even weeks may be missing there. Its course page lists every unit of the
term, and the unit pages carry the meetings with their frequency, so nothing that runs in a
campus room during the term is lost. Everything is cached in ``data/raw/usos/``.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from urllib.parse import unquote

import pandas as pd
from tqdm import tqdm

from .http import CachedHttp, FetchFailed, OfflineMiss
from .pages import (
    CourseGroup,
    CoursePage,
    Tile,
    UnitPage,
    parse_course,
    parse_faculty_groups,
    parse_group_courses,
    parse_room_week,
    parse_unit_groups,
)

log = logging.getLogger(__name__)

API = "https://apps.usos.agh.edu.pl/services"
WEB = "https://web.usos.agh.edu.pl/kontroler.php"


@dataclass
class Crawl:
    term: str
    rooms: pd.DataFrame  # every USOS room: room_usos_id, number, building_usos_id, type, capacity
    tiles: list[Tile]
    courses: dict[str, CoursePage]
    units: dict[int, UnitPage]
    # full mode: the catalogue of every faculty and the dated meetings of the whole term
    course_groups: dict[str, CourseGroup] = field(default_factory=dict)  # code -> group
    group_courses: dict[str, list[str]] = field(default_factory=dict)  # group code -> courses
    group_faculty: dict[str, str] = field(default_factory=dict)  # group code -> faculty id
    meetings: pd.DataFrame | None = None  # tt/classgroups activities, one row per meeting


def fetch_terms(http: CachedHttp) -> pd.DataFrame:
    return pd.DataFrame(http.json("api/terms", f"{API}/terms/terms_index"))


def fetch_rooms(http: CachedHttp) -> pd.DataFrame:
    """Every room of every USOS building, with type and capacity."""
    buildings = http.json("api/buildings", f"{API}/geo/building_index")
    ids: list[str] = []
    for b in buildings:
        d = http.json(
            "api/buildings", f"{API}/geo/building2", {"building_id": b["id"], "fields": "id|rooms"}
        )
        ids += [r["id"] for r in d.get("rooms") or []]
    rows = []
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        info = http.json(
            "api/rooms",
            f"{API}/geo/rooms",
            {"room_ids": "|".join(chunk), "fields": "id|number|type|capacity|building"},
        )
        for rid in chunk:
            r = info.get(rid)
            if not r:
                continue
            b = r.get("building") or {}
            loc = b.get("location") or {}
            rows.append(
                {
                    "room_usos_id": str(r["id"]),
                    "number": r.get("number") or "",
                    "building_usos_id": b.get("id"),
                    "type": r.get("type"),
                    "capacity": r.get("capacity"),
                    "lon": loc.get("long"),
                    "lat": loc.get("lat"),
                }
            )
    df = pd.DataFrame(rows)
    df["capacity"] = df["capacity"].astype("Int64")
    return df


def _each(items: Iterable, what: str, progress: bool):
    items = list(items)
    return tqdm(items, desc=what, unit="page", disable=not progress) if items else items


def fetch_faculties(http: CachedHttp, root: str = "000-000") -> list[str]:
    """Every organisational unit under the university (faculties, institutes, SJO, ...)."""
    ids = http.json("api/fac", f"{API}/fac/subfaculties_deep", {"fac_id": root})
    return sorted({root, *ids})


def fetch_catalogue(http: CachedHttp, faculties: list[str], progress: bool = True):
    """Course groups of every faculty and the courses of every group (every page of both
    lists, see ``_pages``)."""
    groups: dict[str, CourseGroup] = {}
    faculty_of: dict[str, str] = {}
    for fac in _each(faculties, "faculties", progress):
        for page in _pages(http, "web/catalogue", {**_FACULTY_GROUPS, "jed_org_kod": fac}):
            for g in parse_faculty_groups(page):
                groups.setdefault(g.code, g)
                faculty_of.setdefault(g.code, fac)
    courses: dict[str, list[str]] = {}
    for code in _each(sorted(groups), "course groups", progress):
        # the code as the link sends it is URL-encoded (``1S%2C7sem``): decode it, or
        # urlencode sends %252C and USOSweb finds no such group. tabea00_*: ignored by
        # USOSweb, kept so the first pages cached with them stay valid.
        params = {**_FACULTY_GROUPS, "jed_org_kod": faculty_of[code], "grupaKod": unquote(code),
                  "tabea00_limit": 100, "tabea00_offset": 0}  # fmt: skip
        found = [
            c for page in _pages(http, "web/catalogue", params) for c in parse_group_courses(page)
        ]
        courses[code] = list(dict.fromkeys(found))
    return groups, courses, faculty_of


def fetch_meetings(
    http: CachedHttp,
    pairs: list[tuple[int, int]],
    start: dt.date,
    end: dt.date,
    progress: bool = True,
) -> pd.DataFrame:
    """Every dated meeting of the class groups ``pairs`` (unit, group number) between
    ``start`` and ``end``: ``tt/classgroups``, 7 days and ``TT_BATCH`` groups per call."""
    rows: list[dict] = []
    weeks = []
    day = start
    while day <= end:
        weeks.append(day)
        day += dt.timedelta(days=7)
    batches = [pairs[i : i + TT_BATCH] for i in range(0, len(pairs), TT_BATCH)]
    jobs = [(w, b) for w in weeks for b in batches]
    for week, batch in _each(jobs, "meetings (weeks x batches)", progress):
        try:
            d = http.json(
                "api/tt",
                f"{API}/tt/classgroups",
                {
                    "classgroup_ids": "|".join(f"{u}|{g}" for u, g in batch),
                    "start": week.isoformat(),
                    "days": 7,
                    "partial": "true",
                    "fields": TT_FIELDS,
                },
            )
        except OfflineMiss:
            continue
        except FetchFailed as err:
            _skip(http, err)
            continue
        if "partial_response" not in d:  # an error answer (cached): these groups are lost
            log.warning("tt/classgroups %s, %d groups: %s", week, len(batch), str(d)[:200])
            continue
        for a in d["partial_response"] or []:
            rows.append({k: a.get(k) for k in TT_FIELDS.split("|")})
    df = pd.DataFrame(rows, columns=TT_FIELDS.split("|"))
    return df.drop_duplicates().reset_index(drop=True)


FAILED_IN_A_ROW = 20  # this many pages failing one after another: stop, USOS is down


def _skip(http: CachedHttp, err: FetchFailed) -> None:
    """One page that keeps failing is skipped (and counted) rather than ending an hours-long
    crawl; a rerun fetches it, since failures are not cached. A run of them is an outage."""
    if http.failed_in_a_row >= FAILED_IN_A_ROW:
        raise RuntimeError(f"{http.failed_in_a_row} pages failed in a row: {err}") from err
    log.warning("%s: skipped", err)


def _page(http: CachedHttp, kind: str, params: dict | None, url: str = WEB) -> str | None:
    try:
        return http.text(kind, url, params)
    except OfflineMiss:
        return None
    except FetchFailed as err:
        _skip(http, err)
        return None


_NEXT_PAGE = re.compile(r"next-page-url='([^']+)'")


def _pages(http: CachedHttp, kind: str, params: dict) -> Iterator[str]:
    """A catalogue list page by page. USOSweb shows 30 rows a page and ignores any other
    paging parameters; the page's ``table-nav-bar`` names the next one (its table id differs
    per list), and the last page has none."""
    page = _page(http, kind, params)
    seen: set[str] = set()
    while page is not None:
        yield page
        m = _NEXT_PAGE.search(page)
        if not m or m.group(1) in seen:
            return
        seen.add(m.group(1))
        page = _page(http, kind, None, htmllib.unescape(m.group(1)))


_FACULTY_GROUPS = {"_action": "katalog2/przedmioty/szukajPrzedmiotu", "method": "faculty_groups"}
TT_BATCH = 300  # class groups per tt/classgroups call (400 still works)
TT_FIELDS = (
    "type|start_time|end_time|unit_id|group_number|course_id|classtype_id"
    "|building_id|room_id|room_number|frequency"
)


def crawl(
    http: CachedHttp,
    term: str,
    buildings: set[str] | None,
    *,
    week: str | None = None,
    progress: bool = True,
    full: bool = False,
) -> Crawl:
    """Rooms of ``buildings`` (USOS building ids; None = every building) for ``term``.

    ``full`` also walks the catalogue of every faculty (all course groups = programmes and
    semesters, all their courses) and fetches every dated meeting of the term
    (``Crawl.meetings``). ``week`` only names the cache folder of the room plans (they
    change every week); default: the ISO week of today."""
    week = week or dt.date.today().strftime("%G-W%V")
    rooms = fetch_rooms(http)
    sel = rooms[rooms["type"].eq("didactics_room")] if not full else rooms
    if buildings is not None:
        sel = sel[sel["building_usos_id"].isin(buildings)]
    log.info(
        "%d rooms in %s buildings",
        len(sel),
        "all" if buildings is None else len(buildings),
    )

    tiles: list[Tile] = []
    misses = 0
    for rid in _each(sel["room_usos_id"], "room plans", progress):
        page = _page(
            http, f"web/room/{week}", {"_action": "katalog2/jednostki/pokazSale", "sala_id": rid}
        )
        if page is None:
            misses += 1
            continue
        tiles += parse_room_week(page)
    codes = {t.course_code for t in tiles}
    log.info("%d timetable tiles, %d courses", len(tiles), len(codes))

    groups: dict[str, CourseGroup] = {}
    group_courses: dict[str, list[str]] = {}
    group_faculty: dict[str, str] = {}
    if full:
        groups, group_courses, group_faculty = fetch_catalogue(
            http, fetch_faculties(http), progress
        )
        listed = {c for cs in group_courses.values() for c in cs}
        log.info("catalogue: %d course groups, %d courses (%d new)",
                 len(groups), len(listed), len(listed - codes))  # fmt: skip
        codes |= listed

    courses: dict[str, CoursePage] = {}
    for code in _each(sorted(codes), "courses", progress):
        page = _page(
            http, "web/course", {"_action": "katalog2/przedmioty/pokazPrzedmiot", "prz_kod": code}
        )
        if page is None:
            misses += 1
            continue
        courses[code] = parse_course(page, code)

    unit_ids = {t.unit_id for t in tiles}
    for c in courses.values():
        unit_ids.update(c.units.get(term, []))
    units: dict[int, UnitPage] = {}
    for uid in _each(sorted(unit_ids), "class groups", progress):
        page = _page(
            http, "web/unit", {"_action": "katalog2/przedmioty/pokazGrupyZajec", "zaj_cyk_id": uid}
        )
        if page is None:
            misses += 1
            continue
        unit = parse_unit_groups(page, uid)
        if unit.term not in (None, term):
            continue
        units[uid] = unit

    meetings = None
    if full:
        terms = fetch_terms(http).set_index("id")
        start = dt.date.fromisoformat(str(terms.loc[term, "start_date"]))
        end = dt.date.fromisoformat(str(terms.loc[term, "end_date"]))
        start -= dt.timedelta(days=start.weekday())  # whole weeks from Monday
        pairs = sorted((u, g.group_nr) for u, unit in units.items() for g in unit.groups)
        meetings = fetch_meetings(http, pairs, start, end, progress)
        log.info("meetings: %d dated meetings of %d groups, %s .. %s",
                 len(meetings), len(pairs), start, end)  # fmt: skip
    if misses:
        log.warning("%d pages missing (offline cache / request budget)", misses)
    if http.n_failed:
        log.warning("%d pages failed and were skipped: run again to fetch them", http.n_failed)
    log.info(
        "crawl %s: %d units, %d groups (%d requests, %d from cache, %d stale)",
        term, len(units), sum(len(u.groups) for u in units.values()),
        http.n_requests, http.n_cached, http.n_stale,
    )  # fmt: skip
    return Crawl(term, rooms, tiles, courses, units, groups, group_courses, group_faculty, meetings)

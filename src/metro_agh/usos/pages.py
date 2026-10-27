"""Parsers for the public USOSweb catalogue pages of AGH (no network, no login).

Three pages carry everything stage 1 needs:

- room timetable ``katalog2/jednostki/pokazSale&sala_id=..`` (one week): which class groups
  meet in the room, with the course code and the unit id (``zaj_cyk_id``);
- class groups of a unit ``katalog2/przedmioty/pokazGrupyZajec&zaj_cyk_id=..``: every
  group's meetings (weekday, time, frequency, room) and "liczba osób w grupie / limit";
- course ``katalog2/przedmioty/pokazPrzedmiot&prz_kod=..``: the course groups ("Grupy:"),
  e.g. ``240-INF-1S-1R-Z`` = "240_Informatyka, stacjonarne, 1 semestr": the cohorts.

Lecturer names are on these pages too; the parsers never return them.
"""

from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

WEEKDAY_STEMS = (
    ("poniedzia", 1),
    ("wtor", 2),
    ("środ", 3),
    ("srod", 3),
    ("czwart", 4),
    ("piąt", 5),
    ("piat", 5),
    ("sobot", 6),
    ("niedziel", 7),
)

_TIME = r"(\d{1,2}):(\d{2})"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def text(fragment: str) -> str:
    """Visible text of an HTML fragment, whitespace collapsed."""
    return _WS.sub(" ", htmllib.unescape(_TAG.sub(" ", fragment))).strip()


def hhmm(h: str, m: str) -> str:
    return f"{int(h):02d}:{m}"


def weekday_of(s: str) -> int | None:
    s = s.lower()
    hits = [(s.find(stem), day) for stem, day in WEEKDAY_STEMS if stem in s]
    return min(hits)[1] if hits else None


def parity_of(frequency: str) -> str | None:
    """``all`` / ``odd`` / ``even`` from a USOS frequency text; None = not weekly
    (once, monthly, irregular), which a typical week does not contain."""
    f = frequency.lower()
    if "nieparzyst" in f:
        return "odd"
    if "parzyst" in f:
        return "even"
    if re.search(r"\bkażd[yaeą]\b|\bco tydzień\b", f):  # każdy, każda, każde, każdą
        return "all"
    return None


# --- room timetable (one week) ------------------------------------------------------------


@dataclass(frozen=True)
class Tile:
    weekday: int
    start: str
    end: str
    course_code: str
    course_name: str
    class_type: str  # short USOS code from the tile: W, CWA, CWL, CWP, ...
    group_nr: int
    unit_id: int  # zaj_cyk_id
    room_usos_id: str | None
    building_usos_id: str | None
    parity_icon: str | None  # odd / even / irregular, from the icon on the tile


_DAY = re.compile(r"<h4>\s*([^<]+?)\s*</h4>\s*</div>\s*<timetable-day>(.*?)</timetable-day>", re.S)
_ENTRY = re.compile(r"<timetable-entry(.*?)</timetable-entry>", re.S)
_ICONS = {"one.svg": "odd", "two.svg": "even", "warn.svg": "irregular"}


def parse_room_week(page: str) -> list[Tile]:
    """Class-group tiles of a room's weekly plan. Meetings that are not classes (student
    clubs, defences: no course code or no group link) are left out."""
    out: list[Tile] = []
    for day_name, body in _DAY.findall(page):
        day = weekday_of(day_name)
        if day is None:
            continue
        for entry in _ENTRY.findall(body):
            code = re.search(r'name-id="([^"]*)"', entry)
            link = re.search(r"pokazZajecia&(?:amp;)?zaj_cyk_id=(\d+)&(?:amp;)?gr_nr=(\d+)", entry)
            when = re.search(rf'slot="dialog-event">\s*{_TIME}\s*(?:&mdash;|—|-)\s*{_TIME}', entry)
            if not (code and code.group(1) and link and when):
                continue
            name = re.search(r'\sname="([^"]*)"', entry)
            info = re.search(r'slot="info">(.*?)</div>', entry, re.S)
            ctype = text(info.group(1)).split(",")[0].strip() if info else ""
            room = re.search(r"pokazSale&(?:amp;)?sala_id=(\d+)", entry)
            bld = re.search(r"pokazBudynek&(?:amp;)?bud_kod=([^'\"&]+)", entry)
            icon = next((v for k, v in _ICONS.items() if k in entry), None)
            h1, m1, h2, m2 = when.groups()
            out.append(
                Tile(
                    weekday=day,
                    start=hhmm(h1, m1),
                    end=hhmm(h2, m2),
                    course_code=htmllib.unescape(code.group(1)),
                    course_name=htmllib.unescape(name.group(1)) if name else "",
                    class_type=ctype,
                    group_nr=int(link.group(2)),
                    unit_id=int(link.group(1)),
                    room_usos_id=room.group(1) if room else None,
                    building_usos_id=htmllib.unescape(bld.group(1)) if bld else None,
                    parity_icon=icon,
                )
            )
    return out


# --- class groups of one unit --------------------------------------------------------------


@dataclass(frozen=True)
class Meeting:
    frequency: str  # raw text, e.g. "każdy poniedziałek"
    weekday: int | None
    start: str | None
    end: str | None
    parity: str | None  # see parity_of
    room_usos_id: str | None


@dataclass
class GroupRow:
    group_nr: int
    meetings: list[Meeting]
    enrolled: int | None  # "liczba osób w grupie"
    limit: int | None  # "limit miejsc" of the group


@dataclass
class UnitPage:
    unit_id: int
    course_code: str | None
    course_name: str | None
    class_type: str | None  # code in brackets in the title, e.g. CWP
    class_type_name: str | None  # e.g. "ćwiczenia projektowe"
    term: str | None  # e.g. 26/27-Z
    unit_limit: int | None  # "Limit miejsc" common to all groups, None = no limit / unknown
    hours: int | None  # "Liczba godzin"
    groups: list[GroupRow] = field(default_factory=list)


def _int(s: str | None) -> int | None:
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else None


def _meeting(fragment: str) -> Meeting | None:
    t = text(fragment)
    if not t:
        return None
    when = re.search(rf"{_TIME}\s*-\s*{_TIME}", t)
    room = re.search(r"pokazSale&(?:amp;)?sala_id=(\d+)", fragment)
    freq = t.split(",")[0].strip()
    return Meeting(
        frequency=freq,
        weekday=weekday_of(freq),
        start=hhmm(*when.groups()[:2]) if when else None,
        end=hhmm(*when.groups()[2:]) if when else None,
        parity=parity_of(freq),
        room_usos_id=room.group(1) if room else None,
    )


def parse_unit_groups(page: str, unit_id: int) -> UnitPage:
    h1 = re.search(r"<h1>(.*?)</h1>", page, re.S)
    head = h1.group(1) if h1 else ""
    code = re.search(r"pokazPrzedmiot&(?:amp;)?(?:prz_)?kod=([^'\"&]+)", head)
    name = re.search(r"pokazPrzedmiot[^>]*>([^<]*)</a>", head)
    ctype = re.search(r"<br>\s*([^<(]*?)\s*\(([^)]+)\)", head)
    term = re.search(r"cdyd_kod=([^'\"&]+)", page)
    unit = UnitPage(
        unit_id=unit_id,
        course_code=htmllib.unescape(code.group(1)) if code else None,
        course_name=text(name.group(1)) if name else None,
        class_type=text(ctype.group(2)) if ctype else None,
        class_type_name=text(ctype.group(1)) if ctype else None,
        term=htmllib.unescape(term.group(1)).replace("%2F", "/") if term else None,
        unit_limit=None,
        hours=None,
    )
    for label, value in re.findall(
        r"<td class='strong'>([^<]*):</td>\s*<td>(.*?)</td>", page, re.S
    ):
        if label.strip() == "Limit miejsc":
            unit.unit_limit = _int(text(value))
        elif label.strip() == "Liczba godzin":
            unit.hours = _int(text(value))

    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        nr = re.search(r"class='strong grupa'[^>]*>\s*(\d+)\s*<", row)
        if not nr:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 4:
            continue
        meetings = [m for m in map(_meeting, re.split(r"<br\s*/?>", cells[1])) if m]
        seats = text(cells[3])
        enrolled, _, limit = seats.partition("/")
        unit.groups.append(
            GroupRow(int(nr.group(1)), meetings, _int(enrolled), _int(limit) if limit else None)
        )
    return unit


# --- course page ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CourseGroup:
    code: str  # grupaKod, e.g. 240-INF-1S-1R-Z
    label: str  # e.g. "240_Informatyka, stacjonarne, 1 semestr"


@dataclass
class CoursePage:
    course_code: str
    name: str | None
    faculty: str | None
    groups: list[CourseGroup]
    units: dict[str, list[int]]  # term (e.g. 26/27-Z) -> unit ids (zaj_cyk_id) of that cycle


def parse_course(page: str, course_code: str) -> CoursePage:
    h1 = re.search(r"<h1>(.*?)</h1>", page, re.S)
    faculty = re.search(r"pokazJednostke&(?:amp;)?kod=([^'\"&]+)", page)
    groups: list[CourseGroup] = []
    cell = re.search(r"<td class='strong'>Grupy:</td>\s*<td>(.*?)</td>", page, re.S)
    if cell:
        for code, label in re.findall(r"grupaKod=([^'\"&]+)[^>]*>([^<]*)</a>", cell.group(1)):
            groups.append(CourseGroup(htmllib.unescape(code), text(label)))
    units: dict[str, list[int]] = {}
    for section in re.split(r"Zajęcia w cyklu", page)[1:]:
        term = re.search(r"cdyd_kod=([^'\"&]+)", section)
        if not term:
            continue
        key = htmllib.unescape(term.group(1)).replace("%2F", "/")
        ids = dict.fromkeys(int(u) for u in re.findall(r"zaj_cyk_id=(\d+)", section))
        units.setdefault(key, []).extend(i for i in ids if i not in units.get(key, []))
    name = text(h1.group(1)).replace(course_code, "").strip() if h1 else None
    return CoursePage(
        course_code, name or None, faculty.group(1) if faculty else None, groups, units
    )


# --- faculty catalogue: course groups and their courses ------------------------------------


def parse_faculty_groups(page: str) -> list[CourseGroup]:
    """Course groups listed for one faculty (``szukajPrzedmiotu&method=faculty_groups``):
    code (as the link sends it, URL-encoded) and label, e.g. 240-INF-1S-1R-Z."""
    out: dict[str, CourseGroup] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        link = re.search(r"grupaKod=([^'\"&]+)", row)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if link and len(cells) >= 2:
            code = htmllib.unescape(link.group(1))
            out.setdefault(code, CourseGroup(code, text(cells[1])))
    return list(out.values())


def parse_group_courses(page: str) -> list[str]:
    """Course codes on one page of a course group's list of courses, decoded like the room
    plans' (``JA-3%2F4`` -> ``JA-3/4``; the encoded one fetches a "400" page)."""
    codes = re.findall(r"pokazPrzedmiot&(?:amp;)?prz_kod=([^'\"&]+)", page)
    return list(dict.fromkeys(unquote(htmllib.unescape(c)) for c in codes))

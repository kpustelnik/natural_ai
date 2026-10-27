"""Stage 1: USOSweb parsers and the crawl -> tables normalisation (no network)."""

from pathlib import Path

import pandas as pd

from metro_agh.schemas.tables import COHORTS, GROUP_COHORTS, GROUPS, ROOMS, TIMETABLE
from metro_agh.usos.fetch import Crawl
from metro_agh.usos.pages import (
    CourseGroup,
    CoursePage,
    parity_of,
    parse_course,
    parse_room_week,
    parse_unit_groups,
    weekday_of,
)
from metro_agh.usos.parse import build_tables, building_resolver, room_key, semester_of

FIX = Path(__file__).parent / "fixtures" / "usos"


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_room_week_tiles():
    tiles = parse_room_week(page("room.html"))
    assert len(tiles) == 2  # the student-club meeting has no course code
    first, second = tiles
    assert (first.weekday, first.start, first.end) == (1, "08:00", "09:30")
    assert (first.course_code, first.class_type, first.group_nr) == ("240-INF-1S-436", "W", 1)
    assert (first.unit_id, first.room_usos_id, first.building_usos_id) == (191280, "316", "D17")
    assert first.parity_icon is None
    assert (second.weekday, second.unit_id, second.group_nr) == (3, 191623, 2)
    assert second.parity_icon == "odd"


def test_unit_groups():
    unit = parse_unit_groups(page("unit.html"), 191623)
    assert unit.course_code == "240-IDS-2S-248"
    assert (unit.class_type, unit.class_type_name) == ("CWP", "ćwiczenia projektowe")
    assert unit.term == "26/27-Z"
    assert unit.unit_limit is None and unit.hours == 20
    g1, g2 = unit.groups
    assert (g1.group_nr, g1.enrolled, g1.limit) == (1, 7, None)
    assert [(m.weekday, m.start, m.end, m.parity, m.room_usos_id) for m in g1.meetings] == [
        (1, "13:15", "14:45", "all", "316")
    ]
    assert (g2.enrolled, g2.limit) == (12, 15)
    assert [(m.weekday, m.parity, m.room_usos_id) for m in g2.meetings] == [
        (3, "odd", "316"),
        (4, "even", "333"),
        (6, "all", "316"),
    ]


def test_course_page():
    c = parse_course(page("course.html"), "240-INF-1S-436")
    assert c.name == "Wstęp do informatyki"
    assert c.faculty == "240-000"
    assert [g.code for g in c.groups] == ["240-INF-1S-1R-Z", "240_INF-1S%2C7sem%2Cpo"]
    assert c.units == {"25/26-Z": [174070], "26/27-Z": [191280, 191334]}


def test_frequency_and_weekday_texts():
    assert parity_of("każdy wtorek") == "all"
    assert parity_of("każda środa") == "all"
    assert parity_of("w każdą sobotę i niedzielę") == "all"
    assert parity_of("co drugi piątek (nieparzyste)") == "odd"
    assert parity_of("co druga środa (parzyste)") == "even"
    assert parity_of("wielokrotnie") is None
    assert parity_of("(brak danych)") is None
    assert weekday_of("co drugi poniedziałek (parzyste)") == 1
    assert weekday_of("każda niedziela") == 7
    assert weekday_of("wielokrotnie") is None


def test_semesters_of_course_groups():
    def sem(code, label=""):
        return semester_of(CourseGroup(code, label or code))

    assert sem("240-INF-1S-1R-Z", "240_Informatyka, stacjonarne, 1 semestr") == 1
    assert sem("240-INF-1S-2R-L") == 4  # year 2, summer
    assert sem("240-IDS-2S-0R-Z", "240_Informatyka-Data Science, II st., 0 semestr") == 0
    assert sem("ELT_1S_sem_5_A") == 5
    assert sem("ENR_1S_s5_all") == 5
    assert sem("IGR_1S_s3") == 3
    assert sem("130_APR_1S_sem3") == 3
    assert sem("000-INT-ENGIN", "Engineering, manufacturing and construction - Int Courses") is None


def test_building_ids_and_rooms():
    resolve = building_resolver(
        {"D-17", "H-A1", "P-A3-A4", "D-14A", "DS-Alfa"}, {"DSALFA1": "DS-Alfa"}
    )
    assert resolve("D17") == "D-17"
    assert resolve("HA1") == "H-A1"
    assert resolve("PA3/A4") == "P-A3-A4"
    assert resolve("D14a") == "D-14A"
    assert resolve("DSALFA1") == "DS-Alfa"
    assert resolve("poza AGH") is None
    assert room_key("1.38") == "1.38"
    assert room_key("-1.15c") == "m1.15c"
    assert room_key("108/109") == "108_109"
    assert room_key("") is None


def fixture_crawl() -> Crawl:
    rooms = pd.DataFrame(
        {
            "room_usos_id": ["316", "333", "900"],
            "number": ["1.38", "3.27a", "ul. Kopernika 7a"],
            "building_usos_id": ["D17", "D17", "poza AGH"],
            "type": ["didactics_room"] * 3,
            "capacity": pd.array([250, 20, None], dtype="Int64"),
            "lon": [19.91] * 3,
            "lat": [50.07] * 3,
        }
    )
    unit = parse_unit_groups(page("unit.html"), 191623)
    courses = {
        "240-IDS-2S-248": CoursePage(
            "240-IDS-2S-248",
            "Pracownia dyplomowa 1",
            "240-000",
            [CourseGroup("240-IDS-2S-1R-Z", "240_Informatyka-Data Science, II st., 2 semestr")],
            {"26/27-Z": [191623]},
        )
    }
    return Crawl("26/27-Z", rooms, parse_room_week(page("room.html")), courses, {191623: unit})


def test_build_tables():
    t = build_tables(fixture_crawl(), {"D-17"}, {})
    TIMETABLE.validate(t.timetable)
    GROUPS.validate(t.groups)
    COHORTS.validate(t.cohorts)
    GROUP_COHORTS.validate(t.group_cohorts)
    ROOMS.validate(t.rooms)
    slots = t.timetable.set_index(["group_id", "weekday"])
    assert slots.loc[("240-IDS-2S-248:CWP:1", 1), "week_parity"] == "all"
    assert slots.loc[("240-IDS-2S-248:CWP:2", 3), "week_parity"] == "odd"
    assert slots.loc[("240-IDS-2S-248:CWP:2", 4), "room_id"] == "3.27a"
    assert 6 not in t.timetable["weekday"].to_numpy()  # Saturday dropped
    assert t.report["weekend meetings dropped"] == 1
    g = t.groups.set_index("group_id")
    assert g.loc["240-IDS-2S-248:CWP:2", "size"] == 12
    assert g.loc["240-IDS-2S-248:CWP:2", "limit"] == 15
    assert g.loc["240-IDS-2S-248:CWP:2", "room_capacity"] == 20  # the smaller room
    assert (g["size_source"] == "usos").all()
    c = t.cohorts.set_index("cohort_id")
    assert c.loc["240-IDS-2S-1R-Z", "semester"] == 2
    assert c.loc["240-IDS-2S-1R-Z", "n_students"] == 19  # 7 + 12 in the only course
    assert set(t.group_cohorts["cohort_id"]) == {"240-IDS-2S-1R-Z"}
    assert pd.isna(t.rooms.set_index("room_usos_id").loc["900", "building_id"])


def test_group_size_fallbacks():
    crawl = fixture_crawl()
    for g in crawl.units[191623].groups:
        g.enrolled = 0
    t = build_tables(crawl, {"D-17"}, {})
    g = t.groups.set_index("group_id")
    # no registrations yet: the group limit, else 60 % of the smallest room
    assert (
        g.loc["240-IDS-2S-248:CWP:2", "size"],
        g.loc["240-IDS-2S-248:CWP:2", "size_source"],
    ) == (
        15,
        "estimate",
    )
    assert (
        g.loc["240-IDS-2S-248:CWP:1", "size"],
        g.loc["240-IDS-2S-248:CWP:1", "size_source"],
    ) == (
        150,
        "room_capacity",
    )


def test_course_in_no_cohort_goes_to_a_pool():
    from metro_agh.usos.parse import pool_members, study_level

    crawl = fixture_crawl()
    crawl.courses["240-IDS-2S-248"].groups = []  # e.g. a language course
    t = build_tables(crawl, {"D-17"}, {})
    assert t.cohorts.empty or "course" not in "".join(t.cohorts["cohort_id"])
    assert set(t.group_cohorts["cohort_id"]) == {"pool:all"}  # no 2S cohort to match
    assert study_level("440-000-2S-JA") == "2S"
    assert study_level("ELT_1S_sem_5_A") == "1S"
    assert pool_members("pool:1S", ["ELT_1S_sem_5", "240-INF-2S-1R-Z"]) == ["ELT_1S_sem_5"]
    assert pool_members("pool:all", ["a", "b"]) == ["a", "b"]


def test_faculty_catalogue_pages():
    from metro_agh.usos.pages import parse_faculty_groups, parse_group_courses

    page_ = page("faculty_groups.html")
    groups = parse_faculty_groups(page_)
    assert [(g.code, g.label) for g in groups] == [
        ("240-IDS-2S-1R-Z", "240_Informatyka-Data Science, II st., 2 semestr"),
        ("240_INF-1S%2C7sem%2Cpo", "240_INF,stacjonarne, 1S,przedmioty obieralne"),
    ]
    assert parse_group_courses(page_) == ["240-INF-1S-007", "240-INF-1S-023"]
    link = "<a href='kontroler.php?_action=katalog2/przedmioty/pokazPrzedmiot&prz_kod=JA-3%2F4'>"
    assert parse_group_courses(link) == ["JA-3/4"]  # as the room plans name it


def test_catalogue_follows_every_page():
    """USOSweb lists 30 rows a page; the next page is named in the table-nav-bar, with the
    group code decoded in the first request."""
    from metro_agh.usos.fetch import WEB, fetch_catalogue

    nav = "<table-nav-bar next-page-url='{}'>"
    row = "<tr><td><a href='x?grupaKod={0}'>{0}</a></td><td>{0}</td></tr>"
    course = "<a href='kontroler.php?_action=katalog2/przedmioty/pokazPrzedmiot&prz_kod={}'>"
    pages = {
        "fac": row.format("G-1") + nav.format("fac2"),
        "fac2": row.format("G%2C2"),
        "G-1": course.format("C-1") + nav.format("g1p2&amp;x=1"),
        "g1p2&x=1": course.format("C-2"),
        "G,2": course.format("C-3"),
    }

    class Http:
        def text(self, kind, base, params=None):
            key = base if params is None else params.get("grupaKod", "fac")
            assert base == WEB or params is None
            return pages[key]

    groups, courses, faculty = fetch_catalogue(Http(), ["100-000"], progress=False)
    assert sorted(groups) == ["G%2C2", "G-1"]
    assert courses == {"G%2C2": ["C-3"], "G-1": ["C-1", "C-2"]}
    assert faculty == {"G-1": "100-000", "G%2C2": "100-000"}


def test_full_tables_cover_everything():
    from metro_agh.schemas.tables import CLASS_GROUPS, COURSE_GROUPS, COURSES, MEETINGS
    from metro_agh.usos.full import full_tables

    crawl = fixture_crawl()
    crawl.course_groups = {
        "240-IDS-2S-1R-Z": CourseGroup("240-IDS-2S-1R-Z", "Data Science, II st., 2 semestr")
    }
    crawl.group_courses = {"240-IDS-2S-1R-Z": ["240-IDS-2S-248"]}
    crawl.group_faculty = {"240-IDS-2S-1R-Z": "240-000"}
    crawl.meetings = pd.DataFrame(
        {
            "type": ["classgroup2", "classgroup2"],
            "start_time": ["2026-10-17 10:00:00", "2026-10-14 13:15:00"],
            "end_time": ["2026-10-17 11:30:00", "2026-10-14 14:45:00"],
            "unit_id": [191623, 191623],
            "group_number": [2, 2],
            "course_id": ["240-IDS-2S-248"] * 2,
            "classtype_id": ["CWP"] * 2,
            "building_id": ["D17", "D17"],
            "room_id": [316, 900],
            "room_number": ["1.38", "ul. Kopernika 7a"],
            "frequency": [None, None],
        }
    )
    t = build_tables(crawl, {"D-17"}, {})
    full = full_tables(crawl, t.rooms)
    COURSE_GROUPS.validate(full.course_groups)
    COURSES.validate(full.courses)
    CLASS_GROUPS.validate(full.class_groups)
    MEETINGS.validate(full.meetings)
    g = full.course_groups.set_index("code").loc["240-IDS-2S-1R-Z"]
    assert (g["semester"], g["level"], g["faculty_id"], g["n_courses"]) == (2, "2S", "240-000", 1)
    c = full.courses.set_index("course_id").loc["240-IDS-2S-248"]
    assert (c["n_groups"], c["enrolled"], c["course_groups"]) == (2, 19, "240-IDS-2S-1R-Z")
    cg = full.class_groups.set_index("group_id").loc["240-IDS-2S-248:CWP:2"]
    assert "każda sobota, 10:00-11:30" in cg["terms"]  # weekends are kept here
    m = full.meetings
    assert list(m["date"]) == ["2026-10-14", "2026-10-17"]  # sorted by date
    assert list(m["weekday"]) == [3, 6]
    assert m["group_id"].eq("240-IDS-2S-248:CWP:2").all()
    assert pd.isna(m.iloc[0]["building_id"]) and m.iloc[1]["building_id"] == "D-17"


def test_duplicate_course_groups_merge():
    from metro_agh.usos.parse import duplicate_cohorts

    a, b, c = {"x1", "x2", "x3", "x4"}, {"x1", "x2", "x3"}, {"x1", "y2", "y3"}
    courses = {
        "GNR_1S-s1_ALL": a,
        "GNR_1S-s1_PP": b,  # the same students, a second code
        "240-INF-1S-4R-Z": {"i1", "i2", "i3", "i4", "i5"},
        "240_INF-1S_7sem_po": {"i2", "i3", "i4", "i5"},  # its electives
        "IZP_1S_s2": c,
        "RTZ_1S_s2": c,  # another programme with the same joint courses
        "GNR_1S-s3_ALL": b,  # another semester
    }
    semester = {k: 1 for k in courses} | {"240-INF-1S-4R-Z": 7, "240_INF-1S_7sem_po": 7}
    semester["GNR_1S-s3_ALL"] = 3
    semester["IZP_1S_s2"] = semester["RTZ_1S_s2"] = 2
    assert duplicate_cohorts(courses, semester) == {
        "GNR_1S-s1_PP": "GNR_1S-s1_ALL",
        "240_INF-1S_7sem_po": "240-INF-1S-4R-Z",
    }

# OSM campus report

Generated 2026-10-14T16:37:31. Data © OpenStreetMap contributors, ODbL.

## Summary

| what | count |
|---|---|
| buildings: academic | 55 |
| buildings: connector | 10 |
| buildings: context | 1845 |
| buildings: dorm | 20 |
| buildings: other | 4 |
| entrances (on AGH buildings) | 278 (95) |
| stops | 10 |
| walk nodes / edges | 4921 / 6131 |
| walk network length | 140.8 km |
| steps edges | 415 |
| point barriers / fences | 909 / 2362 |

## Building YAML bootstrap

- written: 1 (U-13)
- skipped (file exists): 88 (A-0, A-1, A-2, A-3, A-4, B-1, B-2, B-3, B-4, B-5, B-6, B-7, B-8, B-9, C-1, C-2, C-3, C-4, C-5, C-6, C-7, D-1, D-10, D-11, D-13, D-14, D-14A, D-15, D-16, D-17, D-2, D-3, D-4, D-5, D-6, D-7, D-9, DS-1, DS-10, DS-11, DS-12, DS-13, DS-14, DS-15, DS-16, DS-17, DS-18, DS-19, DS-2, DS-3, DS-4, DS-5, DS-6, DS-7, DS-8, DS-9, DS-Alfa, H-A1, H-A2, H-B1B2, H-B3B4, H-B6, H-D8, P-A0-A1, P-A1-A2, P-A1-C1, P-A3-A4, P-A4-C4, P-B1-B2, P-B2-B3, P-B3-B4, P-D2-S-1, P-D3-S1, S-1, S-2, U-1, U-10, U-11, U-12, U-2, U-3, U-5, U-6, U-7, U-9, Z-11, Z-15, Z-2)
- failed: 0

## Issues to check

### Dorms without an AGH code (context; add to osm_building_map.csv if AGH) (6)

- way/230301584: DS "Za Kolumnami"
- way/230301981: DS "Krakowiak"
- way/231815487: None
- way/231815488: Dom Studencki Piast
- way/231815507: Dom Studencki Nawojka
- way/231815935: None

### Buildings merged from several OSM elements (2)

- D-15: way/306183303, way/231815486 (disjoint)
- D-1: way/231815562, way/231815564 (touching)

### AGH buildings without building:levels (default height used) (23)

- B-1
- B-2
- B-3
- B-4
- B-6
- C-6
- D-1
- D-13
- D-2
- D-3
- D-4
- D-6
- DS-Alfa
- H-B1B2
- H-B3B4
- H-B6
- H-D8
- P-B1-B2
- P-B2-B3
- P-B3-B4
- U-13
- U-2
- U-7

### Buildings with several entrance=main (first by node id used) (3)

- A-3
- D-7
- S-2

### AGH codes outside the campus area (check they are AGH) (3)

- U-10
- U-12
- Z-2

## AGH buildings

| id | category | name | levels | height m (source) | entrances | main entrance | OSM |
|---|---|---|---|---|---|---|---|
| A-0 | academic | Gmach Główny AGH | 5 | 17.5 (levels) | 3 | 9202416063 | relation/3111004 |
| A-1 | academic |  | 4 | 14.0 (levels) | 0 | <NA> | way/231815526 |
| A-2 | academic |  | 4 | 14.0 (levels) | 0 | <NA> | way/231815528 |
| A-3 | academic |  | 5 | 17.5 (levels) | 2 | 10614092761 | way/231815530 |
| A-4 | academic |  | 4 | 14.0 (levels) | 0 | <NA> | way/231815532 |
| B-1 | academic |  |  | 10.5 (default) | 1 | 9565592037 | way/231815533 |
| B-2 | academic |  |  | 10.5 (default) | 1 | 9565592035 | way/231815534 |
| B-3 | academic |  |  | 10.5 (default) | 1 | 9565592033 | way/231815535 |
| B-4 | academic |  |  | 10.5 (default) | 1 | 9565592031 | way/231815540 |
| B-5 | academic |  | 10 | 35.0 (levels) | 1 | 9655669758 | way/231815544 |
| B-6 | academic |  |  | 10.5 (default) | 0 | <NA> | way/288334926 |
| B-7 | academic |  | 2 | 7.0 (levels) | 1 | 12920955170 | way/396909303 |
| B-8 | academic |  | 4 | 14.0 (levels) | 0 | <NA> | way/231815476 |
| B-9 | academic | Instytut Telekomunikacji i Cyberbezpieczeństwa AGH | 4 | 14.0 (levels) | 3 | 9202429239 | way/692473858 |
| C-1 | academic |  | 5 | 17.5 (levels) | 1 | 12920955124 | way/231815553 |
| C-2 | academic |  | 5 | 17.5 (levels) | 2 | 11786755317 | way/231815555 |
| C-3 | academic |  | 5 | 17.5 (levels) | 2 | 2523058337 | way/231815556 |
| C-4 | academic |  | 6 | 21.0 (levels) | 1 | 9577438706 | way/231815558 |
| C-5 | academic |  | 5 | 17.5 (levels) | 0 | <NA> | way/601114932 |
| C-6 | academic |  |  | 10.5 (default) | 1 | 8029905868 | way/601115047 |
| C-7 | academic | Wydział Humanistyczny AGH | 7 | 24.9 (tag) | 2 | 10716155647 | way/909413671 |
| D-1 | academic |  |  | 10.5 (default) | 0 | <NA> | way/231815562, way/231815564 |
| D-10 | academic |  | 4 | 14.0 (levels) | 2 | 2504133444 | way/231815566 |
| D-11 | academic |  | 4 | 14.0 (levels) | 1 | 2351408780 | way/231815567 |
| D-13 | academic |  |  | 10.5 (default) | 0 | <NA> | way/231815572 |
| D-14 | academic | Wydział Zarządzania AGH | 4 | 14.0 (levels) | 0 | <NA> | way/231815574 |
| D-14A | academic |  | 4 | 14.0 (levels) | 0 | <NA> | way/692531587 |
| D-15 | academic | Cyfronet AGH | 4 | 14.0 (levels) | 1 | 9205394494 | way/306183303, way/231815486 |
| D-16 | academic |  | 2 | 7.0 (levels) | 1 | 6798685233 | way/231815477 |
| D-17 | academic | Centrum Informatyki AGH | 4 | 14.0 (levels) | 19 | 2184337427 | way/181823531 |
| D-2 | academic |  |  | 10.5 (default) | 1 | 11913396644 | way/1173524707 |
| D-3 | academic |  |  | 10.5 (default) | 1 | 13893588956 | way/1173524708 |
| D-4 | academic |  |  | 10.5 (default) | 0 | <NA> | way/231815575 |
| D-5 | academic |  | 2 | 7.0 (levels) | 2 | 9651065015 | way/231815576 |
| D-6 | academic | Instytut Telekomunikacji AGH |  | 10.5 (default) | 3 | 9202429270 | way/231815577 |
| D-7 | academic |  | 4 | 14.0 (levels) | 2 | 11786960619 | way/231815579 |
| D-9 | academic |  | 2 | 7.0 (levels) | 0 | <NA> | way/231815732 |
| DS-1 | dorm | Olimp | 17 | 55.0 (tag) | 1 | 9788952915 | way/231815508 |
| DS-10 | dorm | Dom Studencki Hajduczek | 5 | 17.5 (levels) | 1 | 9737313316 | way/231815505 |
| DS-11 | dorm | Dom Studencki Bonus | 5 | 17.5 (levels) | 3 | 9735791820 | way/231815502 |
| DS-12 | dorm | Dom Studencki Promyk | 5 | 17.5 (levels) | 2 | 2520230193 | way/231815510 |
| DS-13 | dorm | Dom Studencki Straszny Dwór | 5 | 17.5 (levels) | 1 | 9032253898 | way/231815514 |
| DS-14 | dorm | Dom Studencki Kapitol | 15 | 55.0 (tag) | 2 | 5365576847 | way/231815506 |
| DS-15 | dorm | Dom Studencki Maraton | 5 | 17.5 (levels) | 1 | 10044409184 | way/318847086 |
| DS-16 | dorm | Dom Studencki Itaka | 5 | 17.5 (levels) | 0 | <NA> | way/230302009 |
| DS-17 | dorm | Dom Studencki Arkadia | 5 | 17.5 (levels) | 0 | <NA> | way/230302135 |
| DS-18 | dorm | Dom Studencki Odyseja | 5 | 17.5 (levels) | 1 | 1692502124 | way/230301490 |
| DS-19 | dorm | Dom Studencki Apollo | 5 | 17.5 (levels) | 1 | 1692502086 | way/230302201 |
| DS-2 | dorm | Babilon | 16 | 55.0 (tag) | 1 | 9788980525 | way/231815501 |
| DS-3 | dorm | Dom Studencki Akropol | 16 | 55.0 (tag) | 1 | 10018432265 | way/230301330 |
| DS-4 | dorm | Dom Studencki Filutek | 5 | 17.5 (levels) | 1 | 2520230210 | way/231815504 |
| DS-5 | dorm | Dom Studencki Strumyk | 5 | 17.5 (levels) | 1 | 2520230205 | way/231815516 |
| DS-6 | dorm | Dom Studencki Bratek | 5 | 17.5 (levels) | 0 | <NA> | way/231815503 |
| DS-7 | dorm | Dom Studencki Zaścianek | 5 | 17.5 (levels) | 0 | <NA> | way/231815518 |
| DS-8 | dorm | Dom Studencki Stokrotka | 5 | 17.5 (levels) | 1 | 2520230188 | way/231815511 |
| DS-9 | dorm | Dom Studencki Omega | 5 | 17.5 (levels) | 1 | 2520230209 | way/231815509 |
| DS-Alfa | dorm | Dom Studencki Alfa |  | 10.5 (default) | 2 | 13192896560 | way/258940559 |
| H-A1 | academic |  | 3 | 10.5 (levels) | 0 | <NA> | way/231815581 |
| H-A2 | academic |  | 3 | 10.5 (levels) | 0 | <NA> | way/231815583 |
| H-B1B2 | academic |  |  | 10.5 (default) | 0 | <NA> | way/231816716 |
| H-B3B4 | academic |  |  | 10.5 (default) | 0 | <NA> | way/231815958 |
| H-B6 | academic |  |  | 10.5 (default) | 0 | <NA> | way/231815585 |
| H-D8 | academic |  |  | 10.5 (default) | 1 | 2503980019 | way/231815586 |
| P-A0-A1 | connector |  | 1 | 3.5 (levels) | 0 | <NA> | way/231815908 |
| P-A1-A2 | connector |  | 1 | 3.5 (levels) | 0 | <NA> | way/231816395 |
| P-A1-C1 | connector |  | 2 | 7.0 (levels) | 0 | <NA> | way/231815866 |
| P-A3-A4 | connector |  | 4 | 14.0 (levels) | 0 | <NA> | way/231815531 |
| P-A4-C4 | connector |  | 1 | 3.5 (levels) | 1 | 9577438705 | way/231816083 |
| P-B1-B2 | connector |  |  | 10.5 (default) | 0 | <NA> | way/231815924 |
| P-B2-B3 | connector |  |  | 10.5 (default) | 1 | 12920955140 | way/231815921 |
| P-B3-B4 | connector |  |  | 10.5 (default) | 1 | 12920955142 | way/231815909 |
| P-D2-S-1 | connector |  | 2 | 7.0 (levels) | 0 | <NA> | way/1524317680 |
| P-D3-S1 | connector |  | 2 | 7.0 (levels) | 0 | <NA> | way/231815741 |
| S-1 | academic |  | 5 | 17.5 (levels) | 0 | <NA> | way/1524317679 |
| S-2 | other |  | 3 | 10.5 (levels) | 3 | 2401456890 | way/231815731 |
| U-1 | academic | Biblioteka Główna AGH | 3 | 10.5 (levels) | 1 | 8977974244 | way/231815478 |
| U-10 | other | Scanmed S.A. | 3 | 10.5 (levels) | 2 | 3997980807 | way/230301331 |
| U-11 | other | Basen AGH | 3 | 10.5 (levels) | 2 | 9737310562 | way/230301329 |
| U-12 | academic | SWFiS AGH | 2 | 7.0 (levels) | 1 | 9202429427 | way/230301404 |
| U-13 | academic | Hala Sportowa AGH |  | 10.5 (default) | 1 | 11301119483 | way/1166315212 |
| U-2 | academic | Centrum Dydaktyki AGH |  | 10.5 (default) | 1 | 11786684680 | way/231815588 |
| U-3 | academic | Przychodnia Akademicka | 3 | 10.5 (levels) | 1 | 9565592030 | way/231815590 |
| U-5 | academic |  | 1 | 3.5 (levels) | 1 | 12920922838 | way/231815592 |
| U-6 | academic |  | 1 | 3.5 (levels) | 0 | <NA> | way/231815594 |
| U-7 | academic | Klub Studio |  | 10.5 (default) | 0 | <NA> | way/231815725 |
| U-9 | academic | Administracja MS AGH | 1 | 3.5 (levels) | 1 | 11587626715 | way/231815596 |
| Z-11 | other |  | 2 | 7.0 (levels) | 0 | <NA> | way/231815597 |
| Z-15 | academic |  | 1 | 3.5 (levels) | 0 | <NA> | way/231815475 |
| Z-2 | academic | Centrum e-Learningu AGH | 3 | 10.5 (levels) | 0 | <NA> | way/231815854 |

## Stops

| id | name | modes | platforms |
|---|---|---|---|
| `stop:agh_ur` | AGH / UR | bus | 3 |
| `stop:biprostal` | Biprostal | bus|tram | 5 |
| `stop:chopina` | Chopina | bus | 1 |
| `stop:cichy_kacik` | Cichy Kącik | bus|tram | 7 |
| `stop:czarnowiejska` | Czarnowiejska | bus | 2 |
| `stop:kawiory` | Kawiory | bus | 4 |
| `stop:miasteczko_studenckie_agh` | Miasteczko Studenckie AGH | bus | 4 |
| `stop:plac_inwalidow` | Plac Inwalidów | bus|tram | 5 |
| `stop:przybyszewskiego` | Przybyszewskiego | bus | 4 |
| `stop:urzednicza` | Urzędnicza | bus|tram | 4 |

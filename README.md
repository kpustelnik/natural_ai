# 🚇 Metro AGH

Projekt semestralny z przedmiotu **Algorytmy inteligentne inspirowane naturą** (AGH, WEAIiIB).

**Pytanie badawcze:** gdzie na kampusie AGH postawić linię metra (k stacji), aby zminimalizować łączny czas przemieszczania się studentów między budynkami w trakcie tygodnia zajęć?

**Metoda:** algorytm mrówkowy (MAX-MIN Ant System) projektuje linię metra, a funkcja celu liczy czasy dojść na grafie *chodniki (OpenStreetMap) + wnętrza budynków + szyby metra*, z popytem wyznaczonym z planów zajęć w USOS.

**Wynik:** interaktywny model 3D kampusu (three.js) z wnętrzami budynków, metrem i animacją ruchu 20 000 studentów w wariantach *bez metra* i *z metrem*.

---

## Spis treści

- [Pipeline](#pipeline)
- [Struktura katalogów](#struktura-katalogów)
- [Instalacja](#instalacja)
- [Uruchomienie](#uruchomienie)
- [Formaty danych](#formaty-danych)
- [Model](#model)
- [Walidacja](#walidacja)
- [Wizualizacja](#wizualizacja)
- [Podział pracy](#podział-pracy)
- [Roadmapa](#roadmapa)

---

## Pipeline

```
USOS ──► data/raw/usos ──► usos/timetable.csv, groups.csv, cohorts.csv, rooms.csv
GTFS ──► data/raw/gtfs ──► transit/stops.csv, rides.csv ──► przystanki w campus.yaml
                                    │
                                    ▼
     populacja (kohorty i liczebności grup z USOS) ──► demand/legs.parquet, od.parquet,
                                                       migrations.csv
                                                            │
OSM ─────────────┐                                          │
data/campus/     ├──► network/nodes.parquet, edges.parquet ─┤
(budynki YAML)  ─┘    (chodniki + wnętrza + szyby metra)    ▼
                                                  instance/instance.npz
                                                            │
                                                            ▼
                                     ACO (MMAS) ──► best_line.json, trace.npz
                                                            │
                                                            ▼
                                   symulacja: bez metra vs z metrem (każdy student)
                                                            │
                                                            ▼
                         web/public/data/ ──► web/ (React + three.js)
```

Każdy etap to osobny skrypt w `scripts/` czytający pliki z poprzedniego etapu. Dzięki temu da się pracować równolegle na danych testowych (`data/sample/`), zanim spłyną prawdziwe dane z USOS. Formaty wszystkich plików między etapami: **[docs/data_contracts.md](docs/data_contracts.md)**.

---

## Struktura katalogów

Szczegółowa mapa kodu (który plik i która funkcja odpowiada za co, gdzie wprowadzić typowe zmiany): [ARCHITECTURE.md](ARCHITECTURE.md).

```
metro-agh/
├── README.md
├── pyproject.toml              # zależności, konfiguracja ruff i pytest
├── uv.lock                     # zamrożone wersje zależności (generuje `uv lock`)
├── .python-version             # wersja Pythona dla uv
├── config.yaml                 # wszystkie parametry (ACO, model czasu, obszar kampusu)
├── .gitignore
├── .gitattributes              # LF wszędzie, diffy notebooków
├── .editorconfig               # wcięcia, kodowanie, końce linii
├── .pre-commit-config.yaml     # ruff, nbstripout, ochrona przed dużymi plikami i kluczami
├── .github/
│   ├── workflows/ci.yml        # ruff + pytest na każdy PR
│   └── pull_request_template.md
├── .vscode/                    # rekomendowane rozszerzenia i ustawienia
│
├── schemas/                    # [generowane, w repo] JSON Schema: podpowiedzi w YAML, typy TS
│
├── data/
│   ├── raw/                    # [gitignore] surowe dane, nie edytujemy ręcznie
│   │   ├── usos/               #   cache odpowiedzi USOS API i stron USOSweb
│   │   ├── gtfs/               #   GTFS ZTP Kraków (autobusy, tramwaje)
│   │   └── osm/                #   features.osm, walk.osm (surowe odpowiedzi Overpass)
│   ├── campus/                 # [w repo] ręcznie modelowany kampus
│   │   ├── buildings/*.yaml    #   budynek: piętra, korytarze, sale, schody, wejścia
│   │   ├── campus.yaml         #   przejścia między budynkami, poprawki OSM, przystanki
│   │   ├── osm_building_map.csv #  poprawki klasyfikacji budynków z OSM
│   │   └── usos_room_map.csv   #   poprawki mapowania sal z USOS
│   ├── processed/              # wyniki etapów pipeline'u ([gitignore] poza usos/, transit/, population/dorms.csv)
│   │   ├── osm/                #   campus.gpkg (QGIS), report.md, preview.html
│   │   ├── usos/               #   timetable.csv, groups.csv, cohorts.csv, group_cohorts.csv, rooms.csv
│   │   ├── transit/            #   stops.csv, rides.csv, trips.parquet (GTFS)
│   │   ├── population/         #   students.parquet, enrollments.parquet
│   │   ├── demand/             #   legs.parquet, od.parquet, migrations.csv
│   │   ├── network/            #   nodes.parquet, edges.parquet
│   │   ├── instance/           #   instance.npz (wejście ACO)
│   │   └── simulation/         #   przejścia studentów i rozkład metra
│   ├── sample/                 # [w repo] mały syntetyczny zestaw do testów i developmentu
│   └── validation/             # [w repo] pomiary terenowe
│       └── field_measurements.csv
│
├── src/metro_agh/              # kod biblioteczny (importowany przez skrypty i notebooki)
│   ├── __init__.py
│   ├── config.py               # wczytanie config.yaml, provenance plików
│   ├── schemas/                # kontrakty danych (pydantic + tabele), patrz docs/data_contracts.md
│   ├── usos/                   # publiczne USOS API + katalog USOSweb, bez logowania
│   │   ├── http.py             # zapytania z cache na dysku i limitem tempa
│   │   ├── pages.py            # parsery stron: plan sali, grupy zajęć, przedmiot
│   │   ├── fetch.py            # crawl: sale -> przedmioty -> grupy (liczba osób, limity)
│   │   ├── full.py             # tabele usos/all/ (cały semestr, wszystkie wydziały)
│   │   └── parse.py            # sala -> budynek, parzystość, liczebności, kohorty -> CSV
│   ├── transit/
│   │   └── gtfs.py             # przystanki kampusu, kursy w szczycie, przejazdy między nimi
│   ├── campus/
│   │   ├── osm.py              # pobranie danych z Overpass (z cache i serwerami zapasowymi)
│   │   ├── osm_process.py      # warstwy: budynki, wejścia, przystanki, bariery, graf pieszy
│   │   ├── osm_report.py       # report.md, issues.json i preview.html
│   │   ├── geo.py              # układy współrzędnych: lon/lat, EPSG:2180, lokalny, web
│   │   └── bootstrap.py        # szkielety LOD1 budynków z OSM (nie nadpisuje istniejących)
│   ├── demand/
│   │   ├── dorms.py            # miejsca w akademikach (YAML albo z powierzchni)
│   │   ├── population.py       # syntetyczni studenci i ich grupy
│   │   └── legs.py             # plan studenta -> przejścia A -> B, OD, migracje
│   ├── network/
│   │   ├── indoor.py           # graf jednego budynku: korytarze, sale, schody, wejścia, szyb
│   │   ├── graph.py            # graf: chodniki + wnętrza + przejścia + przystanki + szyby metra
│   │   └── instance.py         # budowa instance.npz dla ACO
│   ├── aco/
│   │   ├── objective.py        # funkcja celu: ważony łączny czas przejść
│   │   ├── mmas.py             # MAX-MIN Ant System
│   │   ├── acs.py              # Ant Colony System
│   │   ├── local_search.py     # dopracowanie linii: zamiana / przestawienie stacji
│   │   └── common.py           # wynik przebiegu, heurystyka, zapis trace (wspólne)
│   ├── baselines/
│   │   ├── random_search.py    # losowe linie, ten sam budżet co mrówki
│   │   ├── greedy.py           # zachłanne dokładanie stacji
│   │   └── brute_force.py      # optimum dokładne na małych instancjach
│   ├── optimize.py             # wybór algorytmu: optimize.algorithm
│   ├── experiments.py          # serie uruchomień: przeglądy parametrów, ablacje, runs.csv
│   ├── validation.py           # pomiary terenowe vs graf (MAE)
│   ├── figures.py              # wspólny styl wykresów do sprawozdania
│   ├── simulation/
│   │   ├── schedule.py         # rozkład jazdy pociągów
│   │   ├── simulate.py         # przejścia każdego studenta, wybór metro / pieszo wg rozkładu
│   │   └── metrics.py          # metryki tygodnia: czas, spóźnienia, przejścia dłuższe niż przerwa
│   ├── geometry/
│   │   ├── mesh.py             # obrysy (EPSG:2180) -> trójkąty i linie w układzie web
│   │   ├── building.py         # YAML budynku -> położenie, piętra, wejścia, bryła LOD1
│   │   └── interior.py         # LOD2/3: pomieszczenia, ściany z otworami drzwi, schody, stropy
│   └── web/
│       ├── gltf.py             # minimalny zapis .glb (węzły, extras, materiały)
│       ├── binary.py           # kontenery nagłówek .json + .bin
│       ├── export_campus.py    # scene, budynki, kontekst, teren, sieć, issues, katalog replayów
│       ├── export_metro.py     # replaye: przebieg ACO (trace) i linia metra z pociągami
│       ├── export_sim.py       # replay symulacji: ścieżki, odcinki na każdy dzień, stats.json
│       ├── export_demand.py    # OD -> obciążenie krawędzi grafu (demand.json)
│       ├── fake.py             # --fake: syntetyczny przebieg ACO i tydzień studentów (do rozwijania przeglądarki)
│       ├── yaml_errors.py      # błędy walidacji YAML z numerem linii
│       ├── aerial.py           # ortofotomapa GUGiK (WMS) jako podkład
│       └── watch.py            # tryb --watch: przebudowa po zapisie pliku
│
├── scripts/                    # punkty wejścia, uruchamiane po kolei
│   ├── 01_fetch_usos.py
│   ├── 01_fetch_transit.py
│   ├── 02_build_campus.py
│   ├── 03_build_demand.py
│   ├── 04_optimize.py
│   ├── 05_simulate.py
│   ├── 06_export_web.py
│   ├── run_experiments.py      # seria uruchomień do walidacji (seedy, parametry)
│   ├── plot_experiments.py     # runs.csv -> wykresy w docs/figures/
│   ├── validate_optimum.py     # luka do optimum (brute force) i granice
│   ├── validate_field.py       # pomiary terenowe vs graf
│   └── report_metrics.py       # metryki symulowanego tygodnia
│
├── experiments/
│   ├── configs/                # konfiguracje eksperymentów (YAML)
│   └── results/                # [gitignore] CSV z wynikami, logi zbieżności
│
├── notebooks/                  # eksploracja i wykresy do sprawozdania
│
├── web/                        # wizualizacja: React + three.js (React Three Fiber), TypeScript, Vite
│   ├── package.json
│   ├── index.html
│   ├── scripts/gen-types.mjs   # schemas/web/*.schema.json -> src/generated/schemas.ts
│   ├── plugins/metroData.ts    # Vite: przeładowanie danych na żywo, `npm run model` uruchamia watcher
│   ├── src/
│   │   ├── App.tsx             # układ: górny pasek, panele boczne, widok 3D, pasek stanu
│   │   ├── state/              # stan widoku (mały store), synchronizacja z adresem URL
│   │   ├── data/               # wczytywanie JSON i kontenerów binarnych, cache
│   │   ├── lib/                # układy współrzędnych (EPSG:2180 w TS), wyszukiwanie, formaty
│   │   ├── scene/              # kamery (orbita, plan, spacer), warstwy, narzędzia (pomiar), paleta
│   │   ├── ui/                 # menu replayów, wyszukiwarka, warstwy, drzewo budynków, inspektor
│   │   ├── theme.css           # wygląd (tokeny kolorów, układ)
│   │   └── generated/          # [generowane, w repo] typy TS (npm run gen:types)
│   └── public/data/            # [gitignore] dane z 06_export_web.py
│
├── docs/
│   ├── data_contracts.md       # formaty wszystkich plików między etapami
│   ├── literatura.md           # przegląd literatury z notatkami
│   ├── pomiary_terenowe.md     # jak mierzyć i które trasy (walidacja 5)
│   ├── viewer_plan.md          # plan i notatki z budowy przeglądarki
│   ├── figures/                # wykresy do sprawozdania
│   └── sprawozdanie/           # finalny raport
│
└── tests/                      # pytest, jeden plik na moduł (lista w ARCHITECTURE.md)
    ├── test_aco.py             # funkcja celu + MMAS na małej instancji
    ├── test_schemas.py         # dane z data/sample zgodne z kontraktami
    └── fixtures/usos/          # zapisane strony USOSweb dla parserów
```

---

## Instalacja

Środowiskiem zarządza **[uv](https://docs.astral.sh/uv/)**: sam pobiera właściwego Pythona (`.python-version`) i instaluje zależności dokładnie z `uv.lock`, więc każdy w zespole ma identyczne wersje.

```bash
# 1. instalacja uv (raz na komputer)
curl -LsSf https://astral.sh/uv/install.sh | sh                          # Linux / macOS
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"               # Windows

# 2. projekt
git clone <repo-url> metro-agh
cd metro-agh
uv sync                              # tworzy .venv i instaluje wszystko (z grupą dev)
uv run pre-commit install            # hooki przed każdym commitem
uv run nbdime config-git --enable    # czytelne diffy notebooków (opcjonalnie)
```

Dodawanie zależności: `uv add <pakiet>` (lub `uv add --dev <pakiet>`). Commitujemy zmieniony `pyproject.toml` **i** `uv.lock`.

> `uv.lock` musi być w repo — bez niego CI (`uv sync --locked`) nie przejdzie.

Główne zależności:

| Obszar | Biblioteki |
|---|---|
| Dane | `requests`, `pandas`, `pyarrow`, `pydantic`, `pillow` |
| Geo i grafy | `osmnx`, `geopandas`, `shapely`, `pyproj`, `networkx` |
| Algorytmy | `numpy` |
| Eksperymenty | `scipy`, `matplotlib`, `tqdm` |
| Dev | `pytest`, `ruff`, `pre-commit`, `jupyterlab`, `nbstripout`, `nbdime` |
| Web | `react`, `three`, `@react-three/fiber`, `three-mesh-bvh`, `vite`, `typescript` |

Wizualizacja wymaga **Node.js** (LTS): `cd web && npm install`. Zależności (React, three.js, React Three Fiber, three-mesh-bvh, Vite, TypeScript) są w `web/package.json`.

### Dane z USOS i komunikacji miejskiej

`01_fetch_usos.py` korzysta wyłącznie z publicznych źródeł AGH: anonimowych metod USOS API
(`apps.usos.agh.edu.pl`: budynki, sale, pojemności) i publicznego katalogu USOSweb (plany sal,
grupy przedmiotów = kohorty, liczba osób w grupach i limity miejsc), a domyślnie
(`usos.scope: all`) także katalog wszystkich jednostek AGH i daty wszystkich spotkań semestru:
`usos/all/` ma wszystkie kierunki i semestry, przedmioty, grupy zajęć i spotkania w każdej sali
(`--campus-only` ogranicza crawl do sal kampusu). Nie trzeba kluczy ani
logowania; nazwiska prowadzących nie są zapisywane. Pierwszy pełny crawl to kilka tysięcy stron
(około godziny przy `usos.delay_s`), potem wszystko jest w cache `data/raw/usos/`
(`--offline` przebudowuje CSV bez sieci). Uruchamiaj go w tygodniu zajęć: plany sal pokazują
bieżący tydzień. `01_fetch_transit.py` pobiera otwarte GTFS ZTP Kraków.

---

## Uruchomienie

Pipeline krok po kroku (każdy skrypt czyta parametry z `config.yaml`):

```bash
uv run scripts/01_fetch_usos.py          # -> data/raw/usos, data/processed/usos/*.csv + usos/all/ (cały USOS)
uv run scripts/01_fetch_transit.py       # -> data/processed/transit/ (przystanki, przejazdy)
uv run scripts/02_build_campus.py        # -> data/processed/osm/ (campus.gpkg, report.md, issues.json, preview.html) + network/*.parquet
uv run scripts/03_build_demand.py        # -> population/, demand/legs, od, migrations.csv (najruchliwszy tydzień kalendarza)
uv run scripts/04_optimize.py            # -> experiments/results/best_line.json (algorytm: optimize.algorithm)
uv run scripts/05_simulate.py            # -> simulation/{no_metro,metro}/legs.parquet, schedule.parquet
uv run scripts/06_export_web.py --campus # -> web/public/data/ (kampus dla przeglądarki)
```

Eksport dla przeglądarki ma dodatkowe flagi: `--watch` (przebudowuje po każdym zapisie YAML, jeden budynek razem z grafem w ok. 0,2 s), `--aerial` (raz pobiera ortofotomapę GUGiK do `data/raw/aerial/`, kolejne eksporty używają kopii) i `--sample`.

Replaye (po `--campus`, bo pozycje stacji biorą się ze `scene.json`):

```bash
uv run scripts/06_export_web.py --aco      # każdy experiments/results/<run_id>/ z trace.npz -> replay ACO
uv run scripts/06_export_web.py --metro    # experiments/results/best_line.json -> linia z pociągami
uv run scripts/06_export_web.py --sim      # wynik 05_simulate.py -> studenci (oba scenariusze) + statystyki
uv run scripts/06_export_web.py --fake     # syntetyczny przebieg MMAS + tydzień 20 000 studentów (data/processed/fake/)
uv run scripts/06_export_web.py --fake --sample   # to samo na data/sample/campus (eksport --campus też z --sample)
```

Kampus z OpenStreetMap:

```bash
uv run scripts/02_build_campus.py --bootstrap   # + szkielety YAML nowych budynków AGH (LOD1)
uv run scripts/02_build_campus.py --refresh     # pobierz OSM ponownie (zamiast z data/raw/osm)
```

Wynik: `data/processed/osm/campus.gpkg` (otwórz w QGIS), `preview.html` (mapa w przeglądarce) i `report.md` (lista rzeczy do sprawdzenia ręcznie). Istniejące pliki w `data/campus/buildings/` nigdy nie są nadpisywane.

Kampus testowy: `--sample` bierze budynki, akademiki i przystanki z `data/sample/campus/`, ale plan zajęć nadal czyta z `data/processed/usos/` i zapisuje wyniki do `data/processed/` (nadpisuje śledzony `population/dorms.csv`):

```bash
uv run scripts/03_build_demand.py --sample
```

Podgląd w przeglądarce (najpierw `02_build_campus.py` i `06_export_web.py --campus`):

```bash
cd web
npm run dev                              # otwórz adres wypisany przez Vite
npm run model                            # Vite + watcher Pythona: edytuj YAML w VS Code, widok odświeża się sam
npm run model:sample                     # to samo na data/sample/campus (budynki z wnętrzami)
npm test                                 # testy jednostkowe (vitest)
npm run gen:types                        # typy TS z schemas/web, po zmianie kontraktów
```

Skróty w przeglądarce: `/` szukaj (także sale, np. `D-17/1.38`), `F` pokaż zaznaczenie, `Esc` odznacz, `1` / `2` / `3` kamera 3D / plan / spacer (WASD, Shift bieg, Esc powrót), `PageUp` / `PageDown` piętro wybranego budynku, `M` pomiar, `R` trasa (zakładka *Route*: najszybsza droga między salą, budynkiem, przystankiem lub dowolnym punktem grafu, z podziałem na odcinki na zewnątrz / w środku / schody), `\` ukryj panele, spacja odtwarzanie, `P` tryb prezentacji (tylko widok i odtwarzacz), `S` zrzut ekranu (PNG z etykietami), `?` lista skrótów, `` ` `` licznik klatek (fps, wywołania rysowania). Alt+klik kopiuje współrzędne lokalne `[x, y]` budynku, Alt+Shift+klik zbiera łamaną, `Enter` kopiuje ją w formacie YAML. Widok (zakładka, zaznaczenie, piętro, kamera, replay) jest w adresie URL, więc przeładowanie strony go nie gubi.

Wejście do budynku: zaznacz go i kliknij *Enter* w inspektorze (albo `PageUp`). Zakładka *Building* wyszarza resztę kampusu, a wybrane piętro jest przecięte na wysokości 1,2 m jak rzut architektoniczny; widok *Plan* jest wtedy obrócony do osi budynku.

Po zmianie modeli w `src/metro_agh/schemas/` (najpierw uzgodnić w zespole):

```bash
uv run python -m metro_agh.schemas.export   # odświeża schemas/*.schema.json
```

Eksperymenty walidacyjne (config eksperymentu nadpisuje wybrane klucze z `config.yaml`):

```bash
uv run scripts/run_experiments.py --config experiments/configs/k_sweep.yaml
uv run scripts/plot_experiments.py k_sweep
uv run scripts/run_experiments.py --config experiments/configs/compare_algorithms.yaml   # MMAS vs ACS vs losowe vs zachłanne
uv run scripts/plot_experiments.py compare_algorithms                                   # wykres, test Wilcoxona, zbieżność
uv run scripts/run_experiments.py --config experiments/configs/compare_algorithms_hard.yaml
uv run scripts/run_experiments.py --config experiments/configs/aco_ablation.yaml        # wrażliwość parametrów
uv run scripts/validate_optimum.py       # luka do optimum (brute force) + granice
uv run scripts/validate_field.py         # pomiary terenowe vs graf
uv run scripts/report_metrics.py         # metryki symulowanego tygodnia
```

Wszystkie wykresy i tabele trafiają do `docs/figures/`.

Jakość kodu:

```bash
uv run pytest                            # testy
uv run ruff check . --fix                # lint
uv run ruff format .                     # formatowanie
uv run pre-commit run --all-files        # wszystkie hooki naraz
```

---

## Formaty danych

Ustalone formaty plików to kontrakt między etapami. Zmiany tylko po uzgodnieniu w zespole.
Pełny opis (po angielsku): **[docs/data_contracts.md](docs/data_contracts.md)**. Kod kontraktów: `src/metro_agh/schemas/`.

| Plik | Co zawiera | Kto pisze |
|---|---|---|
| `data/campus/buildings/<id>.yaml` | budynek: piętra, korytarze, sale, schody, wejścia, szyb metra | ręcznie |
| `data/campus/campus.yaml` | przejścia między budynkami, poprawki OSM, przystanki (12, z GTFS) | ręcznie |
| `usos/timetable.csv` + `groups.csv`, `cohorts.csv`, `group_cohorts.csv` | plan zajęć z USOS | osoba 1 |
| `population/students.parquet`, `enrollments.parquet` | 20 000 syntetycznych studentów i ich grupy | osoba 1 |
| `demand/legs.parquet`, `od.parquet` | każde przejście studenta / zagregowany popyt | osoba 1 |
| `network/nodes.parquet`, `edges.parquet` | graf pieszy: OSM + wnętrza + szyby metra | osoba 2 |
| `instance/instance.npz` | macierze czasów + popyt, jedyne wejście ACO | osoba 2 |
| `results/<run_id>/run.json`, `convergence.csv`, `trace.npz` | przebieg ACO, mrówki i feromon | osoba 3 |
| `results/best_line.json`, `runs.csv` | najlepsza linia / zestawienie uruchomień | osoby 3, 5 |
| `simulation/<scenariusz>/legs.parquet`, `metro/schedule.parquet` | wynik symulacji, rozkład pociągów | osoba 4 |
| `web/public/data/**` | scena, budynki `.glb`, metro, trajektorie (binarne), ślady mrówek, statystyki | osoba 4 |

Konwencje: metry i sekundy (bez minut); `*_s` to czas trwania, `*_wt` to sekundy od poniedziałku 00:00; obliczenia w EPSG:2180; w przeglądarce układ three.js (x = wschód, y = góra, z = −północ).

---

## Model

### Graf

Graf pieszy kampusu z OSM (`osmnx`, `network_type="walk"`) połączony z grafami wnętrz budynków generowanymi z `data/campus/buildings/*.yaml` (korytarze, drzwi sal, schody, wejścia) i z przejściami z `campus.yaml`. Budynki modelujemy stopniowo: LOD1 (bryła z OSM), LOD2 (piętra, korytarze, schody), LOD3 (sale). Kandydat na stację to szyb pod głównym wejściem budynku (`metro_shaft: true`); przejazd pociągiem nie jest krawędzią grafu, tylko jest liczony analitycznie.

### Czas przejścia z metrem

```
t = dojście do szybu + zejście szybem + czekanie (headway / 2)
  + tunel / v_metra + postoje na stacjach pośrednich
  + wyjście szybem + dojście od szybu do sali
```

Student wybiera metro tylko wtedy, gdy jest szybsze niż dojście pieszo (minimum z Dijkstry). Dojścia liczone są od sali do sali, razem ze schodami. Parametry są w `config.yaml` (`time_model`, `metro`). Linia może być otwarta (`line`) albo zamknięta (`loop`).

### Funkcja celu

Suma czasów wszystkich przejść wszystkich studentów w modelowanym tygodniu. Minimalizujemy.

### ACO (MAX-MIN Ant System)

- Węzły: kandydaci na stacje (wejścia do budynków).
- Mrówka buduje linię z **k** stacji, wybierając kolejną stację z prawdopodobieństwem ∝ τ^α · η^β.
- Heurystyka η: popyt w pobliżu kandydata / odległość od poprzedniej stacji.
- Feromon odkłada tylko najlepsza mrówka (iteracji lub globalnie), z ograniczeniem τ ∈ [τ_min, τ_max].

### Pozostałe algorytmy (`optimize.algorithm` w `config.yaml`)

- **ACS** (Ant Colony System): z prawdopodobieństwem `q0` mrówka bierze najlepszą następną stację; każdy krok mrówki zbliża feromon na tej parze do τ0 (lokalne parowanie `xi`), więc mrówki jednej iteracji się rozchodzą; feromon odkłada tylko najlepsza dotąd linia.
- **Losowe** (`random`): tyle losowych linii, ile zbudowałyby mrówki (`n_ants × n_iterations`).
- **Zachłanne** (`greedy`): najlepsza para stacji, potem k − 2 razy stacja i miejsce w linii, które najbardziej obniżają funkcję celu.
- **Local search** (`optimize.local_search`, domyślnie włączone): najlepsza linia iteracji jest dopracowywana (wymiana stacji na inną, zamiana dwóch, przestawienie jednej), aż nic nie pomaga; w MMAS / ACS jak u Stützlego i Hoosa, w losowym to multi-start local search, w zachłannym poprawka końcowej linii. Bez niej mrówki ledwo biją losowe linie.
- **Budżet** (`optimize.max_evaluations`): ta sama liczba różnych linii dla każdego algorytmu losowego; iteracje są wtedy tylko górną granicą.
- **Brute force**: każda linia raz, optimum dokładne; tylko małe instancje (`optimize.brute_force_max_lines`; kampus przy k = 5 ma ok. 2·10⁸ linii).

---

## Walidacja

| # | Test | Cel | Gdzie |
|---|---|---|---|
| 1 | ACO vs brute force (podinstancje: 12 kandydatów, k = 4) | czy ACO znajduje optimum, luka % | `validate_optimum.py` → `gap_to_optimum.png` |
| 2 | ACO vs losowe vs zachłanne, 30 seedów, ten sam budżet ewaluacji, z i bez local search; też k = 10 | przewaga metody; wykres punktowy, test Wilcoxona | `compare_algorithms(_hard).yaml` |
| 3 | Krzywe zbieżności MMAS vs ACS (vs losowe) | zachowanie algorytmu | `compare_algorithms_convergence.png` |
| 4 | Analiza wrażliwości: liczba mrówek, iteracji, α, β, ρ; liczba stacji k | stabilność wyniku | `aco_ablation.yaml`, `k_sweep.yaml` |
| 5 | Pomiary terenowe ~10 tras vs czasy z grafu | wiarygodność modelu świata (MAE) | `validate_field.py` (gdy są pomiary) |
| 6 | Granice: bez metra (baseline) i teleportacja (dolne ograniczenie) | sanity check | `validate_optimum.py` → `bounds.csv`, `best_line.json` |

Pomiary terenowe (protokół i 10 tras: [docs/pomiary_terenowe.md](docs/pomiary_terenowe.md)) zapisujemy w `data/validation/field_measurements.csv`:

`route_id, from_key, to_key, measured_s, date, who, notes` (`from_key` to budynek `D-17` albo sala `D-17/1.38`)

**Metryki raportowane** (`report_metrics.py` → `simulation_metrics.csv`): zaoszczędzone studento-minuty / tydzień, % przejść dłuższych niż przerwa, liczba spóźnionych przejść i zajęć (zajęcia = dzień, sala, godzina; spóźnione, gdy choć jeden student dociera po starcie).

---

## Wizualizacja

Aplikacja w `web/`: **React + three.js** (React Three Fiber), TypeScript, Vite; `three-mesh-bvh` do szybkiego raycastingu (wybór sal, kolizje kamery we wnętrzach). Odtwarza gotowe dane z `web/public/data/`; wszystkie obliczenia są w Pythonie.

- zakładki: *Campus* (przegląd OSM i budynków), *Building* (jeden budynek, modelowanie), *Network* (graf pieszy), *Metro*, *Simulation*,
- menu *Replays*: wybór, co odtworzyć — każdy przebieg ACO i każda symulacja eksportowane do `web/public/data/replays/<id>/`,
- kampus 3D: budynki z `.glb` (czysty styl architektoniczny), wejście do środka i poruszanie się po piętrach,
- metro: szyby pod wejściami, perony, tunele, kursujące pociągi wg rozkładu,
- 20 000 studentów odtwarzanych z danych binarnych, z suwakiem dnia i godziny; kolor: idzie / czeka na pociąg / jedzie,
- przełącznik *bez metra / z metrem / obok siebie* (dwie połówki widoku, jedna kamera), zakładka *Stats*: zaoszczędzone godziny, wykres na każdą godzinę, użycie stacji, największe oszczędności między punktami,
- animacja mrówek (kandydaci jako cylindry, trasy mrówek, feromon) z `trace.npz`.

---

## Zasady pracy w repo

- Na `main` tylko przez Pull Request; CI (ruff + pytest + build `web/`) musi przejść.
- Gałęzie: `feat/<co>`, `fix/<co>`, np. `feat/aco-mmas`.
- Parametry tylko w `config.yaml`, nigdy zahardkodowane w kodzie.
- Notebooki są czyszczone z outputów przez `nbstripout`; wykresy do sprawozdania zapisujemy do `docs/figures/`.
- Danych z `data/raw` nie commitujemy; z `data/processed` tylko `usos/`, `transit/` i `population/dorms.csv` (pobieranie trwa długo), reszta musi dać się odtworzyć skryptami.

---

## Podział pracy

| Osoba | Zakres | Katalogi |
|---|---|---|
| 1 | Dane z USOS, macierz OD | `src/metro_agh/usos`, `demand` |
| 2 | Kampus z OSM, graf, model czasu | `campus`, `network` |
| 3 | ACO i baseline'y | `aco`, `baselines`, `tests` |
| 4 | Wizualizacja, eksport | `web`, `export`, `simulation` |
| 5 | Eksperymenty, pomiary, literatura, sprawozdanie | `experiments`, `notebooks`, `docs` |

---

## Roadmapa

- [ ] **Tydzień 1:** sprawdzić dostęp do USOS API AGH (lub plan B: eksport iCal); ustalić formaty plików; repo i środowisko
- [ ] **Tydzień 2:** pipeline end-to-end na `data/sample/` (5 budynków, sztuczny popyt), aż do animacji w przeglądarce
- [ ] **Tydzień 3–4:** prawdziwe dane: graf kampusu, budynki, popyt z USOS
- [ ] **Tydzień 5–6:** ACO (MMAS + ACS), baseline'y, testy vs brute force
- [ ] **Tydzień 7:** eksperymenty walidacyjne, pomiary terenowe
- [ ] **Tydzień 8:** dopracowanie wizualizacji, przegląd literatury, sprawozdanie, prezentacja

---

## Dane i licencje

- Mapa i budynki: © współtwórcy OpenStreetMap, licencja ODbL.
- Plany zajęć pochodzą z USOS AGH i są używane wyłącznie w celach dydaktycznych; w repozytorium nie przechowujemy danych osobowych, tylko zagregowany popyt na poziomie grup.

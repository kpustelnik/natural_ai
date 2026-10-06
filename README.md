# 🚇 Metro AGH

Projekt semestralny z przedmiotu **Algorytmy inteligentne inspirowane naturą** (AGH, WEAIiIB).

**Pytanie badawcze:** gdzie na kampusie AGH postawić linię metra (k stacji), aby zminimalizować łączny czas przemieszczania się studentów między budynkami w trakcie tygodnia zajęć?

**Metoda:** algorytm mrówkowy (MAX-MIN Ant System) projektuje linię metra, a funkcja celu liczy czasy dojść na grafie *chodniki + metro* zbudowanym z OpenStreetMap, z popytem wyznaczonym z planów zajęć w USOS.

**Wynik:** interaktywna mapa 3D kampusu (deck.gl) z animacją ruchu studentów w wariantach *bez metra* i *z metrem*.

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
USOS ──► data/raw/usos ──► timetable.csv ──► demand.parquet (macierz OD)
                                                    │
OSM  ──► data/raw/osm  ──► walk_graph.graphml ──────┤
                           buildings.geojson         │
                           candidates.geojson        ▼
                                          ACO (MMAS) ──► best_line.json
                                                    │
                                                    ▼
                                    symulacja: bez metra vs z metrem
                                                    │
                                                    ▼
                                web/data/*.json ──► web/index.html (deck.gl)
```

Każdy etap to osobny skrypt w `scripts/` czytający pliki z poprzedniego etapu. Dzięki temu da się pracować równolegle na danych testowych (`data/sample/`), zanim spłyną prawdziwe dane z USOS.

---

## Struktura katalogów

```
metro-agh/
├── README.md
├── pyproject.toml              # zależności, konfiguracja ruff i pytest
├── uv.lock                     # zamrożone wersje zależności (generuje `uv lock`)
├── .python-version             # wersja Pythona dla uv
├── config.yaml                 # wszystkie parametry (ACO, model czasu, obszar kampusu)
├── .env.example                # szablon kluczy USOS -> skopiuj do .env
├── .gitignore
├── .gitattributes              # LF wszędzie, diffy notebooków
├── .editorconfig               # wcięcia, kodowanie, końce linii
├── .pre-commit-config.yaml     # ruff, nbstripout, ochrona przed dużymi plikami i kluczami
├── .github/
│   ├── workflows/ci.yml        # ruff + pytest na każdy PR
│   └── pull_request_template.md
├── .vscode/                    # rekomendowane rozszerzenia i ustawienia
│
├── data/
│   ├── raw/                    # [gitignore] surowe dane, nie edytujemy ręcznie
│   │   ├── usos/               #   odpowiedzi API / eksporty iCal
│   │   └── osm/                #   cache osmnx
│   ├── processed/              # [gitignore] wyniki etapów pipeline'u
│   │   ├── timetable.csv
│   │   ├── demand.parquet
│   │   ├── walk_graph.graphml
│   │   ├── buildings.geojson
│   │   └── candidates.geojson
│   ├── sample/                 # [w repo] mały syntetyczny zestaw do testów i developmentu
│   └── validation/             # [w repo] pomiary terenowe
│       └── field_measurements.csv
│
├── src/metro_agh/              # kod biblioteczny (importowany przez skrypty i notebooki)
│   ├── __init__.py
│   ├── config.py               # wczytanie config.yaml
│   ├── usos/
│   │   ├── client.py           # USOS API (OAuth 1.0a) / plan B: iCal
│   │   └── parse.py            # sala -> budynek, normalizacja do timetable.csv
│   ├── campus/
│   │   ├── osm.py              # pobranie grafu pieszego i obrysów budynków
│   │   ├── buildings.py        # wysokości, mapowanie kod budynku -> geometria
│   │   └── candidates.py       # kandydaci na stacje (wejścia do budynków)
│   ├── demand/
│   │   └── od_matrix.py        # kolejne zajęcia grupy -> przejścia A -> B z wagą
│   ├── network/
│   │   ├── graph.py            # graf multimodalny: chodniki + linia metra
│   │   └── travel_time.py      # Dijkstra, czas dojścia z metrem i bez
│   ├── aco/
│   │   ├── mmas.py             # MAX-MIN Ant System
│   │   ├── acs.py              # Ant Colony System (do porównania)
│   │   └── objective.py        # funkcja celu: ważony łączny czas przejść
│   ├── baselines/
│   │   ├── random_search.py
│   │   ├── greedy.py
│   │   └── brute_force.py      # optimum dokładne na małych instancjach
│   ├── simulation/
│   │   └── trips.py            # trajektorie studentów z timestampami
│   └── export/
│       └── deck.py             # eksport JSON dla wizualizacji
│
├── scripts/                    # punkty wejścia, uruchamiane po kolei
│   ├── 01_fetch_usos.py
│   ├── 02_build_campus.py
│   ├── 03_build_demand.py
│   ├── 04_optimize.py
│   ├── 05_simulate.py
│   ├── 06_export_web.py
│   └── run_experiments.py      # seria uruchomień do walidacji (seedy, parametry)
│
├── experiments/
│   ├── configs/                # konfiguracje eksperymentów (YAML)
│   └── results/                # [gitignore] CSV z wynikami, logi zbieżności
│
├── notebooks/                  # eksploracja i wykresy do sprawozdania
│   ├── 01_eksploracja_danych.ipynb
│   └── 02_wyniki_eksperymentow.ipynb
│
├── web/                        # wizualizacja, statyczna strona
│   ├── index.html
│   ├── main.js                 # deck.gl: budynki, TripsLayer, metro, UI
│   ├── style.css
│   └── data/                   # [gitignore] JSON-y z 06_export_web.py
│
├── docs/
│   ├── literatura.md           # przegląd literatury z notatkami
│   ├── figures/                # wykresy do sprawozdania
│   └── sprawozdanie/           # finalny raport
│
└── tests/
    ├── test_aco.py             # ACO == brute force na małej instancji
    ├── test_travel_time.py
    └── test_od_matrix.py
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
cp .env.example .env                 # i uzupełnij klucze USOS
```

Dodawanie zależności: `uv add <pakiet>` (lub `uv add --dev <pakiet>`). Commitujemy zmieniony `pyproject.toml` **i** `uv.lock`.

> `uv.lock` musi być w repo — bez niego CI (`uv sync --locked`) nie przejdzie.

Główne zależności:

| Obszar | Biblioteki |
|---|---|
| Dane | `requests`, `requests-oauthlib`, `pandas`, `pyarrow`, `icalendar` |
| Geo i grafy | `osmnx`, `geopandas`, `shapely`, `pyproj`, `networkx` |
| Algorytmy | `numpy`, `numba` |
| Eksperymenty | `scipy`, `matplotlib`, `seaborn`, `tqdm` |
| Dev | `pytest`, `ruff`, `pre-commit`, `jupyterlab`, `nbstripout`, `nbdime` |

Wizualizacja nie wymaga instalacji: deck.gl i MapLibre ładowane są z CDN.

### Klucze USOS API

Klucze trzymamy w pliku `.env` (szablon: `.env.example`). Plik `.env` jest w `.gitignore`, a hook `detect-private-key` dodatkowo pilnuje, żeby nic nie wyciekło.

---

## Uruchomienie

Pipeline krok po kroku (każdy skrypt czyta parametry z `config.yaml`):

```bash
uv run scripts/01_fetch_usos.py          # -> data/raw/usos, data/processed/timetable.csv
uv run scripts/02_build_campus.py        # -> graf, budynki, kandydaci na stacje
uv run scripts/03_build_demand.py        # -> demand.parquet
uv run scripts/04_optimize.py            # -> experiments/results/best_line.json
uv run scripts/05_simulate.py            # -> trajektorie bez / z metrem
uv run scripts/06_export_web.py          # -> web/data/*.json
```

Praca na danych testowych (bez USOS) — flaga `--sample` czyta z `data/sample/`:

```bash
uv run scripts/03_build_demand.py --sample
```

Podgląd wizualizacji:

```bash
uv run python -m http.server -d web 8000
# otwórz http://localhost:8000
```

Eksperymenty walidacyjne (config eksperymentu nadpisuje wybrane klucze z `config.yaml`):

```bash
uv run scripts/run_experiments.py --config experiments/configs/compare_baselines.yaml
```

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

### `timetable.csv`

| kolumna | typ | przykład | opis |
|---|---|---|---|
| `group_id` | str | `ISI-3-g2` | identyfikator grupy zajęciowej |
| `weekday` | int | `1` | 1 = poniedziałek … 5 = piątek |
| `start` | str | `08:00` | początek zajęć |
| `end` | str | `09:30` | koniec zajęć |
| `building` | str | `D-17` | kod budynku |
| `room` | str | `1.38` | sala (opcjonalnie) |
| `size` | int | `15` | liczebność grupy |

### `demand.parquet`

Jeden wiersz to jedno przejście grupy między kolejnymi zajęciami tego samego dnia:

`group_id, weekday, depart_time, from_building, to_building, weight, break_minutes`

### `best_line.json`

```json
{
  "stations": ["D-17", "C-2", "B-1", "A-0"],
  "objective_minutes": 123456.7,
  "baseline_minutes": 150234.1,
  "params": { "n_ants": 50, "alpha": 1.0, "beta": 3.0, "rho": 0.1 }
}
```

### `web/data/`

| plik | zawartość |
|---|---|
| `buildings.json` | obrysy budynków + wysokość (`PolygonLayer`) |
| `metro.json` | ścieżka linii i stacje |
| `trips_before.json` | trajektorie `{path: [[lon, lat], …], timestamps: […]}` bez metra |
| `trips_after.json` | to samo z metrem |
| `stats.json` | podsumowanie do paneli UI |

---

## Model

### Graf

Graf pieszy kampusu z OSM (`osmnx`, `network_type="walk"`). Każdy budynek jest podpięty do najbliższego węzła grafu. Linia metra dodawana jest jako osobne krawędzie między stacjami.

### Czas przejścia z metrem

```
t = dojście do stacji + t_wejścia + odległość_metrem / v_metra + dojście ze stacji do budynku
```

Student wybiera metro tylko wtedy, gdy jest szybsze niż dojście pieszo (minimum z Dijkstry). Parametry (`v_pieszo`, `v_metra`, `t_wejścia`) są w `config.yaml`.

### Funkcja celu

Ważona suma czasów wszystkich przejść w tygodniu (waga = liczebność grupy). Minimalizujemy.

### ACO (MAX-MIN Ant System)

- Węzły: kandydaci na stacje (wejścia do budynków).
- Mrówka buduje linię z **k** stacji, wybierając kolejną stację z prawdopodobieństwem ∝ τ^α · η^β.
- Heurystyka η: popyt w pobliżu kandydata / odległość od poprzedniej stacji.
- Feromon odkłada tylko najlepsza mrówka (iteracji lub globalnie), z ograniczeniem τ ∈ [τ_min, τ_max].
- Wariant ACS jako drugi algorytm do porównania.

---

## Walidacja

| # | Test | Cel |
|---|---|---|
| 1 | ACO vs brute force (np. 12 kandydatów, k = 4) | czy ACO znajduje optimum, luka % |
| 2 | ACO vs losowe vs zachłanne, 30 seedów, ten sam budżet ewaluacji | przewaga metody; boxploty, test Wilcoxona |
| 3 | Krzywe zbieżności MMAS vs ACS | zachowanie algorytmu |
| 4 | Analiza wrażliwości: liczba mrówek, ρ, β, liczba stacji k | stabilność wyniku |
| 5 | Pomiary terenowe ~10 tras vs czasy z grafu | wiarygodność modelu świata (MAE) |
| 6 | Granice: bez metra (baseline) i teleportacja (dolne ograniczenie) | sanity check |

Pomiary terenowe zapisujemy w `data/validation/field_measurements.csv`:

`from_building, to_building, measured_seconds, date, who`

**Metryki raportowane:** zaoszczędzone studento-minuty / tydzień, % przejść dłuższych niż przerwa, liczba „spóźnionych” grup.

---

## Wizualizacja

Statyczna strona `web/index.html` oparta na **deck.gl** i **MapLibre** (ciemny podkład, bez klucza API):

- `PolygonLayer` (extruded): budynki 3D,
- `TripsLayer`: animowane ślady studentów,
- `PathLayer` + `ScatterplotLayer`: linia metra i stacje,
- `TripsLayer`: kursujący pociąg,
- UI: suwak godziny i dnia, przełącznik *bez metra / z metrem*, licznik zaoszczędzonych minut.

Strona tylko odtwarza gotowe dane z `web/data/`; wszystkie obliczenia są w Pythonie.

---

## Zasady pracy w repo

- Na `main` tylko przez Pull Request; CI (ruff + pytest) musi przejść.
- Gałęzie: `feat/<co>`, `fix/<co>`, np. `feat/aco-mmas`.
- Parametry tylko w `config.yaml`, nigdy zahardkodowane w kodzie.
- Notebooki są czyszczone z outputów przez `nbstripout`; wykresy do sprawozdania zapisujemy do `docs/figures/`.
- Danych z `data/raw` i `data/processed` nie commitujemy; muszą dać się odtworzyć skryptami.

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

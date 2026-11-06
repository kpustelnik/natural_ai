# Roadmapa: co jest zrobione, co zostało

Stan na 2026-11-01, 17:45. Gałąź robocza: `feat/aco-merge`, zbudowana na `feat/usos` (Kamil
Pustelnik, ostatni commit 2929b71). **Zasada: kod z `feat/usos` zostaje taki, jaki jest;
dokładamy tylko rzeczy, które go nie zmieniają (nowe pliki, nowe opcjonalne klucze z
domyślną wartością równą obecnemu zachowaniu, dokumentacja).**

Priorytety: **P0** bez tego projekt nie jest skończony, **P1** wzmacnia walidację / sprawozdanie,
**P2** tylko jeśli zostanie czas.

## 1. Zrobione

### 1.1 Na `feat/usos` (podstawa)

| obszar | co jest | gdzie |
|---|---|---|
| dane | crawl USOS (poprawki), GTFS, populacja syntetyczna, popyt dla tygodnia, wszystkie wyniki etapów **w repo** | `data/processed/`, `usos/`, `demand/`, `transit/` |
| model | graf pieszy kampusu, instancja: N = 55 kandydatów, M = 4 830 par OD, 42 521 studento-godzin / tydzień bez metra | `network/`, `instance/instance.npz` |
| optymalizacja | MMAS, ACS, losowe, zachłanne, przegląd zupełny, lokalne przeszukiwanie (opcja wszystkich), wspólny budżet różnych linii, granica „teleportacja” | `aco/`, `baselines/`, `optimize.py`, klucze `optimize.*` |
| eksperymenty | porównanie 8 wariantów (z / bez LS, 30 seedów, k = 5), wariant trudny (k = 10, 60 000 linii), odległość od optimum (5 podzbiorów po 12 kandydatów), ablacja α, β, ρ, mrówek, iteracji, k-sweep 2…10 | `experiments/configs/`, `experiments/results/`, `scripts/validate_optimum.py`, `docs/figures/` |
| wynik | najlepsza linia **H-D8 – C-4 – U-9 – D-10 – A-0**: 11,6 % mniej czasu przejść (cel), 12,5 % w symulacji, ~15 min na studenta tygodniowo, spóźnione zajęcia 503 → 450 | `docs/figures/compare_algorithms.csv`, `simulation_metrics.csv` |
| symulacja | oba scenariusze dla prawdziwego tygodnia, metryki do sprawozdania | `simulation/`, `scripts/report_metrics.py` |
| sprawozdanie | `docs/sprawozdanie/sprawozdanie.md` (PL): cel, dane, model, algorytmy, wyniki 5.1–5.6, symulacja, walidacja, wnioski, odtworzenie | `docs/sprawozdanie/` |
| literatura | przegląd: projektowanie sieci TZ, ACO (AS, ACS, MMAS, Dorigo–Stützle), metodyka porównań, dane i graf | `docs/literatura.md` |
| walidacja terenowa | **pominięta** (świadomie, opisane w sprawozdaniu §7); narzędzie gotowe | `scripts/validate_field.py` |
| viewer | fazy 0–7, poprawki | `web/` |

### 1.2 Na `feat/aco-validation` (moja gałąź, commit e1bb26d)

Zrobione równolegle, na starszych danych z `main` (wyniki liczbowe stamtąd są **nieważne**).
Dużo pokrywa się z `feat/usos`, więc **nie jest przenoszone**: własne ACS, baseline'y, local
search, refaktoryzacja MMAS, runner i skrypt wykresów, klucze `aco.variant` / `aco.ls` /
`aco.max_evaluations`, plany w LaTeX-u. Przenosimy tylko to, czego `feat/usos` nie ma (§2).

### 1.3 Już na `feat/aco-merge`

- [x] P0-1 literatura: Goss 1989, Korzeń i Kruszyna 2023 / 2025, Mann–Whitney, Holm, A₁₂
      (`docs/literatura.md` §0, §1.1, §3; sprawozdanie §1, §4, §5.3).
- [x] P0-2 `docs/aco.md`: materiał do prezentacji (po polsku), z wynikami i pytaniami.
- [x] P0-3 prawdziwe replaye w viewerze (`06_export_web.py --campus --aco --metro --sim`:
      `aco-mmas-k5-s42`, `sim-mmas-k5-s42`; `web/public/data` nie jest w repo).
- [x] P0-5 README: roadmapa → ten plik.
- [x] P1-7…11 eksperymenty: dokładne optimum całego kampusu (k ≤ 4), heurystyka, linia vs
      pętla, wrażliwość, długość tunelu (`scripts/plot_extra.py`, `docs/aco.md` §9.7).
- [x] Wyniki P1 w sprawozdaniu (§5.7, wnioski 5–6, odtworzenie §9).
- [x] P0-4 konspekt dwóch prezentacji (1: demo wizualizacji i przykładowego przebiegu z metrem i bez; 2: wszystko), sekcje zwijane:
      `docs/prezentacja.md`; slajdy robimy poza repo.
- [x] Slajdy obu prezentacji w repo: `docs/prezentacje/prezentacja-1.html`, `prezentacja-2.html`
      (źródła obok, `scripts/build_slides.py`).
- [x] GitHub Pages: `.github/workflows/pages.yml`, `site/` (strona główna, etap 1, etap 2), viewer z
      prawdziwymi danymi, slajdy i wykresy; linki w slajdach. Do włączenia: Settings → Pages →
      Source: GitHub Actions (po merge do `main`).
- [x] P1-12 statystyka: `metro_agh/stats.py`, kolumny `p_mw`, `p_holm`, `a12`, `effect`
      (kolumna Kamila z Wilcoxonem sparowanym zostaje).

- [x] `/references/` w `.gitignore` (PDF-y tylko lokalnie).
- [x] Szybsza funkcja celu (`aco/objective.py`), zmiana addytywna: ta sama wartość co
      dotychczas (różnica 7·10⁻¹⁵), skompilowana pętla (numba): 0,35 → 0,23 ms na linię
      pojedynczo, ~0,05 ms w paczkach (`Objective.many`); stara implementacja zostaje jako
      `travel_numpy`. Dodatkowo `tunnel_m(line)` i opcjonalna kara za tunel (domyślnie 0,
      nic nie zmienia). Wszystkie 135 testów przechodzi.
- [x] Viewer, 2026-11-06: osobny kolor metra i autobusu / tramwaju (autobusy jadą po
      grafie zewnętrznym, nie w linii prostej), wykresy na żywo w doku (średni czas odcinka,
      zaoszczędzone godziny, kto co robi), liczniki czekających na peronach i pasażerów w
      pociągach, kamera pod ziemią i przezroczysty grunt (`X`), prawy przycisk przesuwa także
      nad etykietami, 4 prawdziwe symulacje tygodnia (k = 3, 5, pętla 7, 10:
      `05_simulate.py --showcase`) i 4 replaye ACO bez LS, w których linia się zmienia
      (`experiments/configs/showcase.yaml`), przejście z replayu ACO do symulacji linii.

## 2. Do zrobienia

### Zostało (stan po §1.3): uzupełnić nazwiska na okładkach, P0-6 PR do `main`, P2

### P0: żeby projekt był skończony

| # | co | jak (najmniejsza zmiana) |
|---|---|---|
| 1 | **Literatura z `references/`**: Goss i in. 1989 (biologiczna inspiracja), Korzeń i Kruszyna 2023 (tunel we Wrocławiu), 2025 (linia tramwajowa) | dopisać do `docs/literatura.md` i krótki akapit „powiązane prace” w sprawozdaniu (tabela: oni vs my) |
| 2 | **`docs/aco.md`**: jeden plik dla osoby prezentującej, bez czytania kodu: problem, funkcja celu, MMAS / ACS / LS / baseline'y w wersji z `feat/usos`, eksperymenty i ich wyniki (liczby z `docs/figures/*.csv`), odniesienie do trzech PDF-ów, pytania na prezentację | nowy plik; przepisać mój szkic na nazwy i wyniki z `feat/usos` |
| 3 | **Replaye w viewerze na prawdziwych danych**: w `web/public/data/replays` są tylko `fake` | `uv run scripts/06_export_web.py --campus --aco --metro --sim` (najpierw `04_optimize.py`, żeby był `trace.npz` najlepszej linii); bez zmian w kodzie |
| 4 | **Prezentacja**: slajdy + scenariusz demo (linki do viewera) | nowy plik `docs/prezentacja.md` (konspekt), slajdy poza repo |
| 5 | **README**: sekcja „Roadmapa” (tygodnie, wszystko odhaczone na „nie”) → link do tego pliku | jedna zmiana w README |
| 6 | **Merge do `main`**: `feat/usos` nie jest jeszcze w `main` | PR `feat/usos` → `main`, potem `feat/aco-merge` (lub jeden PR z `feat/aco-merge`) |

### P1: mocniejsza walidacja (addytywne eksperymenty, wyniki do sprawozdania)

| # | co | jak | zmiana w kodzie |
|---|---|---|---|
| 7 | **Dokładne optimum na pełnej instancji** dla k = 2, 3, 4 (1 485 / 78 705 / 4,1 mln linii) i czy MMAS + LS je znajduje | config `exact_full.yaml`; przegląd zupełny liczony paczkami przez `Objective.many` | mała: `brute_force.py` używa `many` (wynik ten sam), limit linii nadpisany w configu |
| 8 | **Heurystyka η**: nasza (popyt / odległość) vs „klasyczna” (tylko odległość, jak porównanie w Korzeń i Kruszyna 2025) vs tylko popyt vs brak | config `heuristic.yaml` (MMAS bez LS, 20 seedów) | mała: opcjonalny klucz `aco.heuristic` w `aco/common.heuristic`, domyślnie obecne zachowanie |
| 9 | **Linia vs pętla** (k = 5) | config `topology.yaml` | brak (topologia już jest) |
| 10 | **Wrażliwość na założenia**: postój 15/30/60 s, odstęp 120/180/300 s, prędkość 8/10/15 m/s; czy stacje się zmieniają | config `sensitivity.yaml` (tryb ablation), wykres przez istniejące `plot_experiments.py` | brak (najwyżej etykiety tekstowe w wykresie) |
| 11 | **Długość tunelu** najlepszych linii i (opcjonalnie) kara za tunel: front Pareto oszczędność vs km | kolumna w tabeli wyników / osobny skrypt `scripts/tunnel_pareto.py` | addytywna (`tunnel_m` już jest) |
| 12 | **Uwaga do statystyki**: test Wilcoxona *sparowany po seedzie* zakłada pary, a seed nie łączy przebiegów dwóch różnych algorytmów; poprawniej: test rangowy Manna–Whitneya + korekta Holma + A₁₂ | dodatkowe kolumny w tabeli porównania (nie zastępować bez zgody Kamila) | addytywna |

### P2: jeśli zostanie czas

| # | co |
|---|---|
| 13 | Pomiary terenowe (~10 tras × 3 przejścia) i `validate_field.py` → MAE; dziś opisane jako ograniczenie |
| 14 | Pomiar fps viewera na laptopie (faza 6 `viewer_plan.md`) |
| 15 | Równoległe uruchamianie eksperymentów (`--jobs`), jeśli P1 okaże się za wolne |
| 16 | Mapa najlepszej linii jako rysunek do sprawozdania (`best_line_map.png`) |

## 3. Kolejność

```
P0-1 literatura ─┐
P0-2 docs/aco.md ─┼─► P0-4 prezentacja ─► P0-5 README ─► P0-6 PR
P0-3 replaye ─────┘
P1-7 … P1-11 eksperymenty (liczą się w tle) ─► wyniki do docs/aco.md i sprawozdania §5
```

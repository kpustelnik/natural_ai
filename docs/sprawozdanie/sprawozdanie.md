# Metro na kampusie AGH: projekt linii algorytmem mrówkowym

Projekt z przedmiotu *Algorytmy inteligentne inspirowane naturą* (AGH, WEAIiIB).
Wersja robocza sprawozdania; liczby pochodzą z `docs/figures/*.csv` (dane USOS 26/27-Z,
pobrane 27–28.10.2026).

## 1. Cel

**Pytanie:** gdzie na kampusie AGH postawić linię metra z *k* stacjami, aby zminimalizować
łączny czas przejść studentów między budynkami w tygodniu zajęć, i ile stacji ma sens?

Linię projektuje algorytm mrówkowy (MAX-MIN Ant System, porównany z Ant Colony System,
losowym przeszukiwaniem, metodą zachłanną i przeglądem zupełnym na małych instancjach).
Wynik sprawdza symulacja każdego przejścia każdego studenta z prawdziwym rozkładem jazdy
metra, autobusów i tramwajów.

## 2. Dane

| źródło | co | skala |
|---|---|---|
| USOS AGH (publiczne API + katalog USOSweb) | plany sal, grupy zajęć, liczebności, kohorty (kierunek + semestr), daty spotkań | 13 881 zajęć tygodniowo, 15 395 grup, 539 kohort; cały semestr: 8 889 przedmiotów, 157 437 spotkań |
| OpenStreetMap | budynki, wejścia, chodniki, schody, bariery | graf: 5 358 węzłów, 6 523 krawędzie |
| model kampusu (`data/campus/`, ręcznie) | 89 budynków w YAML (LOD1–LOD3: piętra, korytarze, sale, schody), przejścia, 12 przystanków | |
| GTFS ZTP Kraków | autobusy i tramwaje między przystankami kampusu | kursy jednego dnia roboczego |
| akademiki | 20 domów studenckich, 6 997 miejsc | |

Z planów zajęć powstaje syntetyczna populacja (22 498 studentów w kohortach, mieszkańcy
akademików i dojeżdżający) i ich tygodniowe przejścia: **286 626 przejść** (zajęcia →
zajęcia, dom → zajęcia, zajęcia → dom), zagregowane do 4 840 par (skąd, dokąd).

## 3. Model

**Graf.** Chodniki z OSM połączone z grafami wnętrz budynków (korytarze, drzwi sal, schody,
wejścia) i z przystankami; czas krawędzi z prędkości pieszej 1,3 m/s i osobnych prędkości
na schodach w górę i w dół. Kandydat na stację to szyb pod wejściem budynku (głębokość
15 m): **N = 55 kandydatów**.

**Metro.** Tunel po prostej między stacjami, 10 m/s, postój 30 s na każdej stacji
pośredniej, pociąg co 180 s (oczekiwanie = połowa), zejście i wyjście szybem po schodach.

**Funkcja celu** (dla linii s₀ … s_{k−1}):

```
metro(a, b) = min po i ≠ j:  dojście(a, sᵢ) + szyb w dół + czekanie + jazda(i, j) + szyb w górę + dojście(sⱼ, b)
cel         = Σ po parach  liczba przejść × min(bez metra(a, b), metro(a, b))
```

„Bez metra” to szybsze z dojścia pieszo i przejazdu autobusem / tramwajem (GTFS), więc
porównanie jest uczciwe: metro musi wygrać z istniejącą komunikacją. Instancja zawiera
tylko tablice NumPy (N × E czasy dojść, E = 101 punktów końcowych), więc ocena linii to
arytmetyka bez Dijkstry: **0,46 ms** na linię.

**Granice (test 6).** Bez metra: 153,9 mln s (42 747 studento-godzin tygodniowo). Dolne
ograniczenie „teleportacji” (przejazd trwa 0 s, każda para ma swoje dwie najlepsze stacje):
90,9 mln s, czyli żadna linia nie da więcej niż **40,9 %** oszczędności. Każda znaleziona
linia mieści się między granicami (sprawdzane w `bounds.csv` i w każdym `best_line.json`).

## 4. Algorytmy

- **MMAS** (Stützle, Hoos 2000): mrówka wybiera następną stację z prawdopodobieństwem
  ∝ τ^α η^β; η = popyt w pobliżu kandydata / odległość; feromon w [τ_min, τ_max], odkłada
  najlepsza mrówka iteracji (co trzecią iterację najlepsza globalnie).
- **ACS** (Dorigo, Gambardella 1997): reguła q0 (z prawdopodobieństwem q0 najlepsza stacja),
  lokalne parowanie ξ po każdym kroku, globalnie wzmacnia tylko najlepsza dotąd linia.
  Literaturowe q0 = 0,9 sprawiało, że mrówki budowały wciąż te same ~790 linii; przyjęto 0,5.
- **Local search** (opcja wszystkich algorytmów poza przeglądem zupełnym): wymiana stacji
  na inną, zamiana dwóch, przestawienie jednej; najlepsza poprawa, aż żadna nie pomaga.
  Kolonie i losowe poprawiają najlepszą linię iteracji, zachłanny swoją końcową.
- **Losowe**: tyle losowych linii, ile zbudowałyby mrówki. **Zachłanny**: najlepsza para,
  potem k − 2 razy stacja i miejsce w linii, które najbardziej obniżają cel.
  **Przegląd zupełny**: każda linia raz (linia i jej odwrócenie to ta sama linia).
- **Uczciwe porównanie** (Derrac i in. 2011): wspólny budżet różnych ocenionych linii
  (`optimize.max_evaluations`, sprawdzany co linię), 30 seedów, test Wilcoxona dla prób
  sparowanych po seedzie.

## 5. Wyniki optymalizacji

### 5.1 Najlepsza linia (k = 5)

**H-D8 – C-4 – U-9 – D-10 – A-0**: cel 136,3 mln s, **11,4 % mniej** niż bez metra
(4 880 studento-godzin tygodniowo). Tę samą linię znajduje każdy algorytm z local search
przy każdym z 30 seedów.

### 5.2 Ile stacji (`k_sweep.png`)

| k | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|
| oszczędność % | 6,44 | 8,71 | 10,05 | 11,42 | 12,49 | 13,32 | 13,98 | 14,44 | 14,93 |
| przyrost (p.p.) | | +2,27 | +1,34 | +1,37 | +1,07 | +0,83 | +0,66 | +0,46 | +0,49 |

Krzywa ma malejące przyrosty: pierwsze stacje obsługują najliczniejsze pary budynków, kolejne
coraz rzadsze, a każdy postój spowalnia jadących dalej. Powyżej k ≈ 7 każda stacja dodaje
mniej niż 0,7 p.p.; to rozsądna górna granica, jeśli liczyć koszt budowy stacji.

### 5.3 Porównanie algorytmów (test 2, `compare_algorithms.png`)

k = 5, 5 000 linii na uruchomienie, 30 seedów:

| | z local search | bez |
|---|---|---|
| MMAS | 11,42 % (zawsze) | 11,22 % (11,02–11,42) |
| ACS | 11,42 % (zawsze) | 11,16 % (10,60–11,42) |
| losowe | 11,42 % (zawsze) | 9,52 % (9,02–10,18) |
| zachłanny | 11,42 % | 11,02 % |

Bez local search obie kolonie są istotnie lepsze od losowego przeszukiwania i od metody
zachłannej (Wilcoxon, p < 10⁻⁵): mrówki uczą się struktury problemu. Z local search przy
k = 5 instancja jest łatwa i każda metoda dochodzi do tej samej linii.

Trudniejsze ustawienie (`compare_algorithms_hard.png`, k = 10, 6 000 linii): ACS + LS
14,78 %, MMAS + LS 14,72 %, losowe + LS 14,69 %, zachłanny + LS 14,69 %; najlepsza znaleziona
linia 14,93 %. Różnice względem MMAS + LS nie są istotne (p = 0,08; 0,47; 0,15). Na tej
instancji o jakości decyduje local search, a strategia, która dostarcza mu punkty startowe,
ma drugorzędne znaczenie.

### 5.4 Odległość od optimum (test 1, `gap_to_optimum.png`)

5 podinstancji po 12 kandydatów (z 30 o największym popycie), k = 4 (5 940 linii), budżet
200 linii (≈ 3 % wszystkich), 10 seedów; luka = część optymalnej oszczędności, której
algorytm nie znalazł.

| | trafienie optimum | średnia luka | maks. luka |
|---|---|---|---|
| MMAS + LS | 92 % | 0,14 % | 2,78 % |
| ACS + LS | 90 % | 0,15 % | 2,78 % |
| losowe + LS | 88 % | 0,22 % | 2,78 % |
| zachłanny + LS | 4 / 5 | 0,41 % | 2,05 % |
| MMAS | 12 % | 5,23 % | 17,45 % |
| ACS | 18 % | 3,27 % | 12,06 % |
| losowe | 4 % | 8,23 % | 26,44 % |
| zachłanny | 3 / 5 | 1,52 % | 5,56 % |

Przy 3 % budżetu MMAS z local search znajduje dokładne optimum w 92 % uruchomień.

### 5.5 Zbieżność (test 3, `compare_algorithms_convergence.png`)

Bez local search MMAS i ACS rosną podobnie: ACS szybciej na początku (reguła q0
eksploatuje), MMAS dogania po ~1 000 linii i kończy nieco wyżej; obie wyraźnie ponad
losowym od ~300 ocenionych linii. Z local search pierwsze zejście zużywa ~2 500 linii i
od razu daje ~11,4 %.

### 5.6 Wrażliwość parametrów (test 4, `aco_ablation.png`)

MMAS bez local search, 20 mrówek × 100 iteracji, 10 seedów, po jednym parametrze:

| parametr | wartości → średnia oszczędność % |
|---|---|
| β (waga heurystyki) | 0 → 10,89; **1 → 11,08**; 3 → 9,79; 5 → 8,11 |
| α (waga feromonu) | 0,5 → 10,34; **1 → 11,08**; 2 → 10,74 |
| ρ (parowanie) | 0,05 → 10,95; **0,1 → 11,08**; 0,2 → 11,06 |
| mrówki | 10 → 10,84; 20 → 11,08; 50 → 11,27 |
| iteracje | 50 → 10,70; 100 → 11,08; 200 → 11,19 |

Najsilniej działa β: heurystyka „popyt w pobliżu / odległość” pomaga tylko słabo (β = 1
lepsze od β = 0), a silna (β = 3–5) prowadzi mrówki w złą stronę. Prawdopodobna przyczyna:
popyt blisko kandydata nie mówi, czy jego przejścia są długie, a krótkie i tak wygrywa
chodzenie, więc stacja przy popularnym budynku często niewiele daje. Dlatego
domyślne β zmieniono z 3 na 1. α i ρ mają optimum w wartościach domyślnych; więcej mrówek
i iteracji pomaga, ale coraz mniej.

## 6. Symulacja tygodnia (`simulation_metrics.csv`)

Każde z 286 626 przejść, bez metra i z linią z 5.1, z prawdziwym rozkładem (metro co 180 s
w obie strony, autobusy i tramwaje z GTFS). Student jedzie, gdy dotrze wcześniej niż
pieszo; na zajęcia wychodzi najpóźniej, jak może.

| | bez metra | z metrem |
|---|---|---|
| studento-godziny w tygodniu | 41 390 | 36 294 |
| oszczędność | | **305 731 studento-minut** (14,9 min na studenta) |
| przejścia dłuższe niż przerwa | 1,55 % | 1,34 % |
| spóźnione przejścia | 1 607 | 1 393 |
| spóźnione zajęcia (dzień, sala, godzina) | 519 | 469 |
| przejazdy metrem | | 29,1 % |
| przejazdy autobusem / tramwajem | 40,6 % | 23,1 % |

Symulacja daje 12,3 % mniej czasu, nieco więcej niż funkcja celu (11,4 %): z prawdziwym
rozkładem studenci jadący na zajęcia wychodzą później, a funkcja celu liczy średnie
czekanie (połowa odstępu). Metro przejmuje głównie przejazdy autobusami między przystankami
kampusu.

## 7. Walidacja modelu świata (test 5)

Pomiarów terenowych (czasy przejść mierzone stoperem vs graf) nie wykonano. Czasy dojść
wynikają z długości chodników OSM i przyjętych prędkości (1,3 m/s poziomo, osobne prędkości
na schodach w `config.yaml`), więc ich dokładność jest niezweryfikowana. Błąd prędkości
pieszej przesuwa wynik w przewidywalną stronę: jeśli studenci chodzą wolniej, metro (o stałej
prędkości) oszczędza więcej, jeśli szybciej, mniej. Narzędzie do porównania jest gotowe
(`scripts/validate_field.py`), gdyby pomiary powstały.

## 8. Wnioski

1. Linia **H-D8 – C-4 – U-9 – D-10 – A-0** oszczędza ok. **11–12 %** czasu przejść, około
   15 minut na studenta tygodniowo, i zmniejsza liczbę spóźnionych zajęć o 10 %.
2. Opłacalne jest 5–7 stacji; dalej każda stacja daje mniej niż 0,7 p.p.
3. Same mrówki (MMAS, ACS) są lepsze od losowego przeszukiwania i od metody zachłannej,
   ale dopiero z lokalnym przeszukiwaniem znajdują optimum niezawodnie (92 % przy 3 %
   budżetu); to zgodne z literaturą (Stützle, Hoos 2000).
4. Heurystyka popytu musi być słaba (β = 1): popyt blisko stacji nie mówi, czy metro się
   przyda, bo liczą się długie przejścia.

**Ograniczenia:** populacja syntetyczna (rozkład studentów na grupy z liczebności USOS),
jeden tydzień, brak tłoku i pojemności pociągów, brak kosztu budowy, tunel po prostej, część
budynków jako bryły bez wnętrz (LOD1), czasy przejść niezweryfikowane pomiarami w terenie.

## 9. Odtworzenie wyników

```bash
uv run scripts/01_fetch_usos.py          # USOS (kilka godzin pierwszy raz, potem z cache)
uv run scripts/03_build_demand.py
uv run scripts/04_optimize.py
uv run scripts/05_simulate.py
uv run scripts/06_export_web.py --campus --aco --metro --sim   # przeglądarka 3D
for e in compare_algorithms compare_algorithms_hard aco_ablation k_sweep; do
  uv run scripts/run_experiments.py --config experiments/configs/$e.yaml
  uv run scripts/plot_experiments.py $e
done
uv run scripts/validate_optimum.py
uv run scripts/report_metrics.py
```

Literatura: [`docs/literatura.md`](../literatura.md).

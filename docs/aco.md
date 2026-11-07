# Optymalizacja linii metra: jak działa, jak ją sprawdzamy, co wyszło

Jedyny plik, który trzeba przeczytać przed prezentacją części optymalizacyjnej: problem,
funkcja celu, wszystkie algorytmy i metody odniesienia, uczciwe porównanie, eksperymenty z
wynikami oraz związek z trzema pracami w `references/`. Nazwy z kodu podane są `tak`, żeby
dało się je znaleźć, ale do prezentacji kod nie jest potrzebny. Liczby pochodzą z plików w
`docs/figures/` (każdy wykres ma obok tabelę `.csv`). Konspekt obu prezentacji (pośredniej i
końcowej): [`docs/prezentacja.md`](prezentacja.md).

Spis: [1 Problem](#1-problem) · [2 Funkcja celu](#2-funkcja-celu) ·
[3 Heurystyka](#3-heurystyka-η) · [4 MMAS](#4-max-min-ant-system-mmas) ·
[5 ACS](#5-ant-colony-system-acs) · [6 Local search](#6-lokalne-przeszukiwanie) ·
[7 Metody odniesienia](#7-metody-odniesienia) · [8 Uczciwe porównanie](#8-uczciwe-porównanie) ·
[9 Wyniki](#9-wyniki) · [10 Literatura](#10-związek-z-pracami-w-references) ·
[11 Odtworzenie](#11-odtworzenie) · [12 Pytania](#12-pytania-na-prezentacji) ·
[13 Poziom 1: ruch pieszy z tłokiem](#13-aco-poziom-1-ruch-pieszy-z-tłokiem)

## 1. Problem

Z planu zajęć USOS wiemy, kto, kiedy i z którego budynku do którego musi przejść w danym
tygodniu: 286 tys. przejść, z nich 4 830 różnych par (skąd, dokąd). Szukamy linii metra z
**k stacji**, która najbardziej skraca łączny czas tych przejść.

- **Kandydaci**: jedna możliwa stacja przy każdym budynku, szyb pod głównym wejściem;
  na kampusie **N = 55**.
- **Rozwiązanie**: **uporządkowana** lista k różnych kandydatów, np. `H-D8 → C-4 → U-9 →
  D-10 → A-0`. Kolejność to przebieg: pociągi jeżdżą tam i z powrotem (`metro.topology:
  line`) albo w kółko (`loop`).
- **Ocena**: suma czasów wszystkich przejść, gdy każdy student wybiera szybszą z opcji
  (pieszo / autobus-tramwaj albo metro). Raportujemy **oszczędność** = 1 − cel / cel bez
  metra, w %.

Dlaczego trudny:

| k | liczba różnych linii przy N = 55 (linia i jej odwrócenie to ta sama linia) |
|---|---|
| 2 | 1 485 |
| 3 | 78 705 |
| 4 | 4 092 660 |
| 5 | ok. 2,1 · 10⁸ |
| 10 | ok. 5 · 10¹⁶ |

i funkcja celu nie rozkłada się na krawędzie: dodanie stacji zmienia, **kto** w ogóle jedzie
metrem, a każda stacja pośrednia to 30 s postoju dla wszystkich przejeżdżających. To nie jest
najkrótsza ścieżka ani TSP. ACO pasuje, bo buduje linię stacja po stacji (jak trasę w TSP) i
uczy się, które pary stacji występują w dobrych liniach.

## 2. Funkcja celu

`aco/objective.py`, `Objective`; kontrakt: `docs/data_contracts.md` §7.

**Instancja** (`instance/instance.npz`, `network/instance.py`) zamienia kampus w tablice, więc
ocena linii to sama arytmetyka:

| tablica | znaczenie |
|---|---|
| `access_s[a, i]` | czas dojścia z punktu a (wejście budynku lub przystanek) do szybu kandydata i (Dijkstra na grafie pieszym, ze schodami) |
| `egress_s[i, b]` | z szybu i do punktu b |
| `tunnel_m[i, j]` | tunel po prostej między peronami i oraz j |
| `od_from, od_to, od_weight` | 4 830 par i ile przejść tygodniowo na każdą |
| `od_walk_s` | czas bez metra: szybsze z pieszo i rozkładowego autobusu / tramwaju (GTFS) |

**Czas jednego przejścia** a → b z linią s₀ … s_{k−1}:

```
jazda(i, j) = (tunel wzdłuż linii od s_i do s_j) / 10 m/s
              + 30 s × (liczba stacji pomiędzy)          [pętla: krótszą stroną]

metro(a, b) = min po wejściu i ≠ wyjściu j:
              dojście[a, s_i] + zejście szybem + czekanie (90 s = połowa odstępu 180 s)
              + jazda(i, j) + wyjście szybem + dojście[s_j, b]

czas(a, b)  = min(bez_metra, metro(a, b))      student wybiera szybsze

cel         = Σ po parach  liczba_przejść × czas(a, b)     [studento-sekundy / tydzień]
```

Przykład (MAIN_IDEA.md): 30 osób D-17 → A-0 idzie 14 min albo jedzie 6 → jadą i oszczędzają
po 8 min; 20 osób C-2 → C-3 idzie 2 min, metrem byłoby 7 → idą i nic nie zyskują. Stacje
opłaca się stawiać tam, gdzie jest dużo **długich** przejść.

Liczby, które ustawiają skalę wszystkich wyników:

- **bez metra** (`baseline`): 42 521 studento-godzin tygodniowo;
- **granica „teleportacja”** (`teleport_bound`): każdy kandydat jest stacją, jazda trwa 0 s;
  każde przejście płaci tylko dojście do najlepszego szybu, szyby i czekanie. Żadna linia
  żadnego k nie zejdzie niżej. To 59,4 % celu bez metra, więc **żadna linia nie może dać
  więcej niż 40,6 % oszczędności**; najlepsza linia k = 5 daje 11,6 %, k = 10: 15,2 %.

Szczegóły techniczne ważne dla eksperymentów:

- *Pamięć podręczna*: linia i jej odwrócenie (a pętla od dowolnej stacji) to jeden klucz
  (`canonical`); każda linia jest liczona raz, `Objective.evaluations` liczy **różne** linie.
- *Szybka ocena*: wewnętrzna pętla (pary × wejście × wyjście) jest kompilowana (numba):
  0,23 ms na linię pojedynczo, ok. 0,05 ms w paczkach (`Objective.many`, używane przez
  przegląd zupełny). Wartości są identyczne z wersją w NumPy (`travel_numpy`, różnica
  ~10⁻¹⁴).
- *Długość tunelu* (`tunnel_m(line)`) i opcjonalna kara za tunel (`metro.tunnel_penalty_per_km`,
  domyślnie 0: nie zmienia niczego).

## 3. Heurystyka η

`aco/common.py`, `heuristic`. Mrówki łączą feromon (wyuczony) ze stałą podpowiedzią η[u, v]
„jak dobrze wygląda stacja v po u”. `demand(v)` = liczba przejść, które zaczynają się lub
kończą najbliżej szybu v, przeskalowana do maks. 1, + 0,05 (żaden kandydat nie jest
niemożliwy).

| `aco.heuristic` | η[u, v] | pierwsza stacja ∝ | znaczenie |
|---|---|---|---|
| `demand_distance` (domyślna) | demand(v) · 100 / (tunel(u, v) + 100 m) | demand | ruchliwe miejsca, niedaleko |
| `distance` | 100 / (tunel(u, v) + 100 m) | równo | „klasyczne” ACO jak w TSP |
| `demand` | demand(v) | demand | bez geometrii |
| `none` | 1 | równo | sam feromon (= β = 0) |

Ablacja pokazała, że heurystyka musi być **słaba** (β = 1, nie 3): popyt przy kandydacie
nie mówi, czy jego przejścia są długie, a krótkie i tak wygrywa chodzenie.

## 4. MAX-MIN Ant System (MMAS)

`aco/mmas.py`, `run_mmas`; Stützle i Hoos (2000), dostosowane do linii.

**Stan**: macierz feromonu τ[u, v] (symetryczna: linię czyta się w obie strony) i wektor
`start[v]` dla pierwszej stacji, oba na początku τ_max = 1 / ρ.

**Jedna iteracja**:

1. Każda z `n_ants` mrówek buduje linię: pierwsza stacja z prawdopodobieństwem ∝
   start^α · demand^β, każda następna (spośród jeszcze nieużytych) ∝ τ[u, v]^α · η[u, v]^β
   (reguła losowo-proporcjonalna Ant System), aż do k stacji (`common.pick`).
2. Ocena wszystkich linii (z pamięci podręcznej, jeśli już były).
3. Z `optimize.local_search`: najlepsza linia iteracji jest poprawiana (§6).
4. **Feromon**: parowanie wszędzie τ ← (1 − ρ) τ, potem **jedna** linia odkłada Δ = cel bez
   metra / jej cel (przy 11,6 % oszczędności Δ ≈ 1,13) na swoich krawędziach i na `start` obu
   końców. Odkłada najlepsza iteracji, a co trzecią iterację najlepsza dotąd.
5. **Ograniczenia**: τ_max = 1 / (ρ · najlepszy cel / cel bez metra), τ_min = τ_max ·
   `tau_min_ratio`; każde τ przycinane do [τ_min, τ_max]. Żadna krawędź nie staje się
   niemożliwa (τ_min > 0) ani nie dominuje całkowicie: kolonia nie utyka za wcześnie.
6. Wiersz zbieżności (najlepszy dotąd, najlepszy i średni w iteracji, granice τ, **entropia
   feromonu**: 1 = równomierny, → 0 = kolonia zgadza się co do jednej linii) i co
   `trace.every` iteracji próbka mrówek i τ do animacji w viewerze.

Koniec po `n_iterations` albo gdy budżet `optimize.max_evaluations` (różne linie) się wyczerpie.

**Parametry** (`config.yaml`): `n_ants` 50, `n_iterations` 200, α = 1, β = 1 (ablacja: 1 >
0 > 3 > 5), ρ = 0,1, `tau_min_ratio` = 0,01. W eksperymentach porównawczych 20 mrówek i
budżet 5 000 linii.

## 5. Ant Colony System (ACS)

`aco/acs.py`, `run_acs`; Dorigo i Gambardella (1997). Ta sama konstrukcja i heurystyka, trzy
różnice:

1. **Reguła pseudolosowo-proporcjonalna**: z prawdopodobieństwem q₀ mrówka bierze najlepszą
   następną stację (argmax τ^α η^β) zamiast losować. Literaturowe q₀ = 0,9 sprawiało, że
   mrówki budowały w kółko te same linie (~2 700 różnych na 10 000 mrówek; przy 0,5: ~7 900),
   więc **q₀ = 0,5**.
2. **Lokalna aktualizacja**: zaraz po przejściu krawędzi τ ← (1 − ξ) τ + ξ τ₀ (ξ = 0,1,
   τ₀ = 1 / N): użyta krawędź staje się *mniej* atrakcyjna dla następnych mrówek tej samej
   iteracji, co rozprasza kolonię.
3. **Globalnie odkłada tylko najlepsza dotąd linia**, z parowaniem tylko na jej krawędziach:
   τ ← (1 − ρ) τ + ρ Δ.

## 6. Lokalne przeszukiwanie

`aco/local_search.py`, `improve`: najlepsza poprawa w sąsiedztwie, aż żadna nie pomaga albo
skończy się budżet. Ruchy (N = 55, k = 5):

| ruch | sąsiedzi |
|---|---|
| **wymiana**: stacja zastąpiona nieużywanym kandydatem | k (N − k) = 250 |
| **zamiana**: dwie stacje zamieniają się miejscami | k (k − 1) / 2 = 10 |
| **przestawienie**: stacja w inne miejsce linii | k (k − 1) = 20 |

`optimize.local_search: true` włącza je **we wszystkich** algorytmach poza przeglądem
zupełnym: kolonie i losowe poprawiają najlepszą linię iteracji, zachłanny swoją końcową.
Dzięki temu porównanie z i bez LS pokazuje, co wnosi sama strategia przeszukiwania. To
klasyczna hybryda ACO + local search ze Stützle i Hoos (2000).

## 7. Metody odniesienia

`baselines/`; wybór: `optimize.algorithm` (`optimize.py`). Każda ma ten sam podpis
(instancja, config, rng) → `RunResult`.

| `optimize.algorithm` | co robi | ile ocen |
|---|---|---|
| `random` | tyle losowych linii, ile zbudowałyby mrówki; najlepsza wygrywa | budżet |
| `greedy` | najlepsza para stacji, potem k − 2 razy stacja i miejsce w linii, które najbardziej obniżają cel | N(N−1)/2 + Σ (N − m)(m + 1) ≈ 2 100 przy k = 5; deterministyczny |
| `brute_force` | każda linia raz (pierwsza < ostatnia; pętla od najmniejszej) | wszystkie (tabela w §1); domyślnie odmawia powyżej 200 000 (`optimize.brute_force_max_lines`) |
| `mmas`, `acs` | §4, §5 | budżet |

## 8. Uczciwe porównanie

- **Ten sam budżet różnych linii** (`optimize.max_evaluations`): ocena linii to jedyny
  kosztowny krok, a linia z pamięci podręcznej jest darmowa. Sprawdzany po każdej iteracji,
  więc przekroczony najwyżej o ~20 linii. Zachłanny i przegląd zupełny raportują, ile zużyły.
- **Wiele uruchomień**: 30 seedów w porównaniach, 10 w ablacji i podinstancjach.
- **Statystyka** (Derrac i in. 2011):
  - test Wilcoxona sparowany po seedzie (`p_vs_*` w tabelach, jak w sprawozdaniu);
  - ponieważ ten sam seed nie łączy przebiegów dwóch algorytmów w pary (każdy zużywa liczby
    losowe inaczej), także **test Manna–Whitneya dla prób niezależnych z korektą Holma** i
    **miara efektu A₁₂** (Vargha, Delaney 2000) = szansa, że losowy przebieg algorytmu
    odniesienia oszczędza więcej (0,5 = brak różnicy; ≥ 0,71 duży efekt), `metro_agh/stats.py`,
    kolumny `p_mw`, `p_holm`, `a12`, `effect`. Algorytm deterministyczny (zachłanny) to jeden
    wynik, więc dla niego nie ma testu, tylko A₁₂.
- **Optimum dokładne** tam, gdzie da się wyliczyć (podinstancje 12 kandydatów; pełny kampus
  dla k = 2, 3, 4): odsetek trafień optimum i luka.
- **Granice**: bez metra ≥ optimum ≥ teleportacja (`bounds.csv`).

## 9. Wyniki

### 9.1 Najlepsza linia (k = 5)

**H-D8 – C-4 – U-9 – D-10 – A-0**: 11,6 % mniej czasu przejść niż bez metra (4 916
studento-godzin tygodniowo). Znajdują ją MMAS + LS, ACS + LS i losowe + LS przy każdym z 30
seedów (obecny `runs.csv`). W symulacji tygodnia z prawdziwym rozkładem: **12,5 %**, ok. **15 minut na
studenta tygodniowo**, spóźnione zajęcia 496 → 452 (z 2 332), 29,0 % przejść metrem
(`simulation_metrics.csv`). Przebieg z etapu 1 (MMAS bez LS, `showcase-mmas-k5`) ma te same
stacje w innej kolejności (H-D8 – A-0 – C-4 – D-10 – U-9): 11,39 % w funkcji celu, ale
**12,87 %** w symulacji. Funkcja celu liczy średnie czekanie (połowa odstępu), symulacja
prawdziwy rozkład, więc różnice kilku dziesiątych p.p. między liniami o tych samych stacjach
są w granicy błędu modelu: wybór stacji jest pewny, kolejność mniej.

### 9.2 Ile stacji (`k_sweep.png`)

| k | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|
| oszczędność % | 6,62 | 8,94 | 10,25 | 11,59 | 12,68 | 13,49 | 14,16 | 14,72 | 15,16 |

Przyrosty maleją (pierwsze stacje obsługują najliczniejsze pary, każdy postój spowalnia
jadących dalej): powyżej k = 7 każda stacja daje < 0,7 p.p. Rozsądnie: 5–7 stacji.

### 9.3 Porównanie algorytmów (`compare_algorithms.png`, `.csv`)

k = 5, 5 000 linii, 30 seedów:

| | z local search | bez |
|---|---|---|
| MMAS | 11,60 % (zawsze) | 11,42 % (11,31–11,60) |
| ACS | 11,60 % | 11,36 % (11,02–11,60) |
| losowe | 11,60 % | 9,68 % (9,15–10,30) |
| zachłanny | 11,34 % | 11,25 % |

Testy dla prób niezależnych (Mann–Whitney, Holm, A₁₂):

- bez LS: MMAS > losowe (p_Holm ≈ 5·10⁻¹¹, A₁₂ = 1,00, efekt duży); MMAS vs ACS
  **nieistotnie** (p = 0,08, A₁₂ = 0,63, efekt mały); MMAS bije zachłanny we wszystkich 30
  przebiegach (A₁₂ = 1,00);
- z LS: MMAS, ACS i losowe dają ten sam wynik (A₁₂ = 0,50); zachłanny + LS zostaje w swoim
  lokalnym optimum (11,34 %).

Trudniej (`compare_algorithms_hard.png`, k = 10, 60 000 linii): MMAS + LS 15,14 %, losowe +
LS 15,13 %, ACS + LS 15,12 %, zachłanny + LS 14,85 %; różnice między trzema pierwszymi
nieistotne, każda bije zachłanny.

**Wniosek do powiedzenia wprost**: mrówki uczą się struktury problemu (wyraźnie lepsze od
losowego), ale na tej instancji o jakości decyduje lokalne przeszukiwanie, a strategia, która
dostarcza mu punkty startowe, ma znaczenie drugorzędne. To zgodne ze Stützle i Hoos (2000).

### 9.4 Odległość od optimum (`gap_to_optimum.png`)

5 podinstancji po 12 kandydatów, k = 4 (5 940 linii), budżet 200 linii (≈ 3 %), 10 seedów:
z LS kolonie trafiają optimum w 84 % (MMAS) i 94 % (ACS) uruchomień; bez LS tylko 16 % i
30 %, a zachłanny 3 z 5 (przy tak małym budżecie kolonia ma ~20–40 iteracji, za mało, by
feromon się czegoś nauczył).

### 9.5 Zbieżność (`compare_algorithms_convergence.png`)

Bez LS ACS rośnie szybciej na początku (reguła q₀), MMAS dogania; obie przeganiają
zachłanny po ~1 950 (MMAS) i ~2 870 (ACS) liniach. Z LS pierwsze zejście zużywa ~1 300–1 700
linii i od razu daje ~11,5 %.

### 9.6 Parametry (`aco_ablation.png`)

MMAS bez LS, 20 mrówek × 100 iteracji, 10 seedów: β: 0 → 10,77 %, **1 → 11,18 %**, 3 →
10,23 %, 5 → 8,61 %; α: 0,5 → 10,70 %, **1 → 11,18 %**, 2 → 11,05 %; ρ 0,2 i więcej mrówek /
iteracji pomagają nieznacznie. Najważniejsze: β, czyli siła heurystyki.

### 9.7 Dodatkowe eksperymenty (P1)

Tabele i wykresy: `scripts/plot_extra.py` → `docs/figures/exact_full`, `heuristic`, `topology`,
`sensitivity`, `tunnel` (`.png` i `.csv`). Testy: Mann–Whitney, Holm, A₁₂ względem pierwszego
wariantu.

**Dokładne optimum całego kampusu** (`exact_full.png`). Przegląd zupełny dla N = 55: k = 2
(1 485 linii, 6,56 %), k = 3 (78 705, 8,90 %), k = 4 (4,1 mln, 15 min, **10,23 %**). Budżet
5 000 linii, 10 seedów:

| k | MMAS + LS | MMAS | ACS + LS | ACS | zachłanny (+ LS) |
|---|---|---|---|---|---|
| 2, 3 | 100 % | 100 % | 100 % | 100 % | trafia |
| 4 (budżet = 0,12 % linii) | **100 %** | 80 % (luka śr. 0,29 %) | 70 % (0,02 %) | 50 % (0,24 %) | nie trafia (0,07 %) |

Na prawdziwej instancji, nie tylko na podinstancjach, MMAS + LS znajduje dokładne optimum
zawsze, mając do dyspozycji ułamek promila przestrzeni; zachłanny utyka w lokalnym optimum.
To też potwierdza, że wartość k = 4 z k-sweepu jest optymalna.

**Heurystyka η** (`heuristic.png`; MMAS bez LS, k = 5, 20 seedów):

| η | średnio | zakres | vs nasza (A₁₂ = P(nasza lepsza)) |
|---|---|---|---|
| popyt / odległość (nasza) | 11,43 % | 11,31–11,60 | — |
| 1 / odległość („klasyczna”) | 10,98 % | 10,15–11,60 | 0,87, duży efekt, p_Holm = 2·10⁻⁴ |
| tylko popyt | 11,52 % | 11,39–11,60 | 0,26, nasza **gorsza**, p_Holm = 0,013 |
| brak (β = 0) | 11,37 % | 10,97–11,60 | 0,56, nieistotnie |

Wniosek, odpowiednik „zmodyfikowane vs klasyczne ACO” u Korzenia i Kruszyny (2025): klasyczna
heurystyka odległości z TSP **szkodzi**: wypada gorzej niż brak heurystyki (p = 0,001,
A₁₂ = 0,80 na korzyść braku), bo pcha mrówki ku
krótkim odcinkom, a dobre linie mają długie przeskoki (najlepsza linia k = 5 ma 3,2 km
tunelu). Pomaga składnik popytu; nasza heurystyka łącząca oba jest lepsza od klasycznej, ale
nieco gorsza od samego popytu.

**Linia czy pętla** (`topology.png`; MMAS + LS, 10 seedów): pętla jest lepsza przy każdym
seedzie: k = 5: **11,98 %** vs 11,60 % (te same stacje C-4, U-9, H-D8, A-0, D-10 w innej
kolejności, tunel 3,85 km zamiast 3,22), k = 7: 13,88 % vs 13,37 %. Pętla nie ma końców, więc
każde dwie stacje dzieli co najwyżej połowa obwodu; płaci za to dłuższym tunelem.

**Wrażliwość na założenia** (`sensitivity.png`; MMAS + LS, k = 5, 10 seedów):

| parametr | wartości → oszczędność | stacje vs linia bazowa (Jaccard) |
|---|---|---|
| postój | 15 s → 12,0 %; **30 s → 11,6 %**; 60 s → 11,4 % | 0,94 / 1 / 1 |
| odstęp pociągów | 120 s → 13,3 %; **180 s → 11,6 %**; 300 s → 8,4 % | 0,97 / 1 / 1 |
| prędkość | 8 m/s → 10,2 %; **10 m/s → 11,6 %**; 15 m/s → 13,6 % | 1 / 1 / 1 |

**Wybór stacji praktycznie nie zależy od założeń o pociągach** (te same pięć stacji prawie
zawsze, czasem w innej kolejności); od nich zależy tylko, ile linia oszczędza. Najsilniej
działa częstotliwość: czekanie (połowa odstępu) płaci każdy pasażer.

**Długość tunelu** (`tunnel.png`, najlepsza linia dla każdego k z k-sweepu): k = 2: 1,1 km,
k = 4: 1,4 km, **k = 5: 3,2 km**, k = 7: 2,7 km, k = 10: 5,1 km. Funkcja celu nie liczy kosztu
budowy, więc linia może „zygzakować”: k = 4 daje 3 070 studento-godzin tygodniowo na km
tunelu, k = 5 tylko 1 530. Gdyby liczyć koszt tunelu, k = 4 lub k = 7 wypadają lepiej niż
k = 5 (opcja `metro.tunnel_penalty_per_km` pozwala to uwzględnić w optymalizacji).

## 10. Związek z pracami w `references/`

Trzy PDF-y to inspiracja (Goss i in. 1989) i dwa najbliższe zastosowania ACO do planowania
kolei i tramwajów (Korzeń, Kruszyna 2023, 2025). Pełne opisy: `docs/literatura.md` §0 i §1.1.

### 10.1 Goss, Aron, Deneubourg, Pasteels (1989): samoorganizujące się skróty mrówki argentyńskiej

Kolonia połączona z pokarmem mostkiem o dwóch gałęziach wybiera krótszą (14 z 14 kolonii przy
stosunku długości 2), choć żadna mrówka nie porównuje długości: mrówki znaczą szlak w obie
strony, ta z krótszej gałęzi wraca wcześniej i znaczy rozwidlenie drugi raz, przewaga się
wzmacnia (wybór ∝ (20 + S)²). Bez parowania kolonia, która utrwaliła dłuższą gałąź, **nie
przełącza się** na krótszą dodaną później (2 z 18).

| Goss i in. | u nas |
|---|---|
| wybór ∝ (20 + S)², tylko feromon | `pick`: ∝ τ^α · η^β; α pełni rolę wykładnika, η dodaje to, co mrówka „widzi” |
| krótsza gałąź znaczona częściej | lepsza linia odkłada więcej: Δ = cel bez metra / cel linii |
| znaczenie w obie strony | τ symetryczne; linia i jej odwrócenie to ta sama linia |
| brak parowania → brak przełączenia | parowanie ρ; w MMAS τ_min > 0, w ACS lokalne parowanie ξ |
| wybór zbiorowy, bez pamięci osobniczej | jedyna pamięć kolonii to τ; mrówka nic nie pamięta |

Spadek entropii feromonu na wykresach zbieżności to odpowiednik ich „jedna gałąź staje się
wyraźnie preferowana”.

### 10.2 Korzeń, Kruszyna (2023): warianty tunelu kolei miejskiej we Wrocławiu

Pięć ręcznie zaprojektowanych wariantów tunelu (3–9 stacji) oceniane zmodyfikowanym Ant System
(ρ = 0,5, α = 1, β = 2) z macierzą „wysiłku” E_ij = (L_ij / L_c) · (1 − I_ij / I_c) ·
(1 / A_ij) · (S_max / S_c): długość, mieszkańcy w promieniu 300 m, liczba linii autobusowych
i tramwajowych, nowe obszary z koleją. Wygrywa wariant o najmniejszym wysiłku.

| | oni | my |
|---|---|---|
| co przeszukujemy | kolejność stacji 5 gotowych wariantów | każdy uporządkowany wybór k z 55 (2·10⁸ przy k = 5) |
| popyt | mieszkańcy przy stacji; wszyscy jadą koleją | 286 tys. przejść z USOS; metro tylko gdy szybsze |
| inne środki | liczba linii jako atrakcyjność | rozkładowy autobus / tramwaj w funkcji celu |
| funkcja celu | suma wysiłku krawędzi (najkrótsza ścieżka) | łączny czas; wartość krawędzi zależy od całej linii |
| sprawdzenie | jedno uruchomienie, ranking | przegląd zupełny, 4 inne metody, 30 seedów, testy, symulacja |

Ich ograniczenia („ograniczona lista tras”, „wszyscy jadą koleją”, „można przetestować inne
metody”) to dokładnie to, co rozwiązuje nasze sformułowanie. Od nich: długość tunelu jako
wielkość raportowana przy linii (`tunnel_m`).

### 10.3 Korzeń, Kruszyna (2025): planowanie linii tramwajowej (linia 12)

Przebieg jednej linii między ustalonymi końcami, wysiłek odcinka z czasu rzeczywistego i
rozkładowego, długości, prędkości, niepewności D_ij (rozrzut **co najmniej trzech pomiarów**
w terenie), atrakcyjności i potencjału; porównanie z „klasycznym” ACO (sama odległość), trasa
o 11,5 % mniejszym wysiłku. U nas:

- ich „zmodyfikowane vs klasyczne” to nasz eksperyment `heuristic.yaml` (nasza heurystyka vs
  sama odległość vs sam popyt vs brak); u nas heurystyka jest tylko podpowiedzią, a cel zawsze
  pełnym czasem przejść, więc mierzymy, ile podpowiedź pomaga w przeszukiwaniu;
- ich protokół pomiarów (≥ 3 przejścia na odcinek, rozrzut) to protokół, którego użylibyśmy
  w walidacji czasów dojść (`validate_field.py`; pomiarów nie wykonano, sprawozdanie §7);
- sugerują porównanie z innymi heurystykami i analizę składników; u nas: §9.3, §9.6, §9.7.

### 10.4 Prace algorytmiczne, które implementujemy

| element | praca | kod |
|---|---|---|
| reguła ∝ τ^α η^β, parowanie, odkładanie ∝ jakości | Dorigo, Maniezzo, Colorni (1996), Ant System | `common.pick`, `mmas.py` |
| q₀, lokalna aktualizacja ξ, τ₀, globalnie najlepsza | Dorigo, Gambardella (1997), ACS | `acs.py` |
| jedna mrówka odkłada, [τ_min, τ_max], start w τ_max, + local search | Stützle, Hoos (2000), MMAS | `mmas.py`, `local_search.py` |
| równy budżet, wiele seedów, testy nieparametryczne | Derrac i in. (2011) | `compare_algorithms*.yaml`, `plot_experiments.py` |
| Mann–Whitney, Holm, A₁₂ | Mann, Whitney (1947); Holm (1979); Vargha, Delaney (2000) | `stats.py` |

## 11. Odtworzenie

```bash
uv run scripts/04_optimize.py                                  # najlepsza linia -> best_line.json
uv run scripts/run_experiments.py --config experiments/configs/compare_algorithms.yaml
uv run scripts/plot_experiments.py compare_algorithms           # + _convergence
uv run scripts/run_experiments.py --config experiments/configs/compare_algorithms_hard.yaml
uv run scripts/validate_optimum.py                              # gap_to_optimum, bounds
uv run scripts/run_experiments.py --config experiments/configs/aco_ablation.yaml
uv run scripts/run_experiments.py --config experiments/configs/k_sweep.yaml
# P1
uv run scripts/run_experiments.py --config experiments/configs/exact_full_brute.yaml
uv run scripts/run_experiments.py --config experiments/configs/exact_full.yaml
uv run scripts/run_experiments.py --config experiments/configs/heuristic.yaml
uv run scripts/run_experiments.py --config experiments/configs/topology.yaml
uv run scripts/run_experiments.py --config experiments/configs/sensitivity.yaml
uv run scripts/plot_extra.py all
# viewer: prawdziwe replaye (ACO i tydzień)
uv run scripts/06_export_web.py --campus --aco --metro --sim
```

## 12. Pytania na prezentacji

**Dlaczego algorytm mrówkowy, a nie np. genetyczny?** Linia to ciąg stacji budowany krok po
kroku, jak trasa w TSP, dla którego ACO powstało; feromon na parach stacji uczy się
„po stacji X dobrze wypada Y”. Nie twierdzimy, że ACO jest najlepsze: porównanie (§9.3)
pokazuje, że z lokalnym przeszukiwaniem nawet losowe punkty startowe wystarczają.

**Skąd wiadomo, że wynik jest dobry, skoro nie da się sprawdzić wszystkich linii?** Na
podinstancjach (12 kandydatów) i na całym kampusie dla k = 2, 3, 4 sprawdziliśmy wszystkie
linie przeglądem zupełnym (§9.4, §9.7); do tego dolna granica „teleportacja” i symulacja.

**Czemu MMAS bez local search przegrywa z zachłannym przy małym budżecie?** Przy 200 liniach
kolonia ma 20–40 iteracji, za mało, by feromon się czegoś nauczył; zachłanny mieści się w
budżecie w całości. Przy 5 000 liniach kolejność się odwraca (§9.3, §9.5).

**Czemu β = 1, a nie 3, jak w wielu pracach?** Heurystyka „popyt przy stacji” myli: popyt nie
mówi, czy przejścia są długie, a tylko długie korzystają z metra (§9.6).

**Czy wynik zależy od seeda?** Z local search nie: MMAS + LS daje tę samą linię we wszystkich
30 uruchomieniach. Bez LS rozrzut to 11,31–11,60 %.

**Jak się ma 11,6 % do 12,5 % z symulacji?** Funkcja celu zakłada średnie czekanie (połowa
odstępu); w symulacji z prawdziwym rozkładem studenci jadący na zajęcia wychodzą tak, żeby
nie czekać.

**Czemu test Manna–Whitneya, skoro sprawozdanie ma Wilcoxona sparowanego?** Ten sam seed nie
łączy przebiegów dwóch algorytmów w pary, więc poprawniej jest traktować je jako próby
niezależne; podajemy oba, wnioski są te same, a A₁₂ mówi, jak duża jest różnica.

**Co z kosztem budowy?** Nie ma go w funkcji celu; zamiast niego analiza liczby stacji (§9.2)
i długość tunelu najlepszej linii (§9.7). Linia k = 5 ma 3,2 km tunelu, więcej niż linia
k = 7 (2,7 km): bez kosztu tunelu linia może „zygzakować”. Opcja `metro.tunnel_penalty_per_km`
pozwala to uwzględnić.

**Czy optimum jest naprawdę optimum?** Dla k ≤ 4 tak, sprawdzone przeglądem wszystkich
4,1 mln linii (§9.7); dla k = 5 (2·10⁸ linii) nie da się, ale MMAS + LS, ACS + LS i losowe +
LS dochodzą do tej samej linii przy wszystkich 30 seedach.

**Czy pętla nie byłaby lepsza?** Tak, o ok. 0,4–0,5 p.p. (§9.7), kosztem dłuższego tunelu.

**Czy heurystyka popytu w ogóle pomaga?** Składnik popytu tak, składnik odległości nie:
klasyczna heurystyka 1 / odległość z TSP wypada najgorzej (§9.7).

**Czym to się różni od prac Korzenia i Kruszyny?** Oni oceniali gotowe warianty z popytem
szacowanym z liczby mieszkańców; my przeszukujemy całą przestrzeń z popytem z planu zajęć
i sprawdzamy wynik przeglądem zupełnym, innymi metodami i symulacją (§10).

**Najważniejsze ograniczenia?** Populacja syntetyczna (z liczebności grup USOS), jeden
tydzień, brak tłoku i pojemności pociągów, brak kosztu budowy, tunel po prostej, budynki bez
wnętrz, czasy dojść niesprawdzone pomiarami w terenie.

## 13. ACO poziom 1: ruch pieszy z tłokiem

`walk/assign.py`, `scripts/walk_aco.py`; wyniki: `docs/figures/walk_aco.png`, `.csv`,
`walk_aco_ablation.csv`, `walk_aco_convergence.csv`; replay `walk-s42`.

**Pytanie.** Model metra (poziom 2) i symulacja prowadzą każdego najkrótszą drogą, bez tłoku.
Jak bardzo tłok wydłuża przejścia w szczycie i jak rozkładają się ludzie, gdy chodnik się
korkuje?

**Popyt.** Piesze przejścia scenariusza bez metra wychodzące w najliczniejszym kwadransie
tygodnia: środa 9:30–9:45 (`walk_aco.window_*`), 5 381 przejść, 848 par węzłów, 76 celów;
81 % wychodzi w pierwszej minucie.

**Czas z tłokiem** (funkcja BPR, dla chodników: Lam, Cheung 2000):
`t = t₀ · (1 + 0,73 · (x / C)⁴)`, x = osoby na odcinku w okresie `period_s` = 5 min (oba
kierunki dzielą szerokość), C = 75 os./min/m (FHWA-RD-98-107) × szerokość × 5 min; przy x = C
prędkość spada z 1,3 do 0,75 m/s (FHWA). Szerokość z typu drogi OSM (`walk_aco.widths_m`:
chodnik 2 m, ścieżka 1,5, droga serwisowa 3, deptak 6, drzwi 1,8), bo OSM na kampusie nie ma
tagu `width`; schody 50 os./min/m (założenie).

**Kolonia** (`run_walk_aco`). W każdej z 60 iteracji każda para wysyła 8 mrówek; mrówka w
węźle u, idąc do celu d, wybiera odcinek u → v z prawdopodobieństwem
∝ τ_d(uv)^α · exp(−β · (c(uv) + h_d(v) − h_d(u)) / 20 s), gdzie c to obecny czas z tłokiem,
a h_d najkrótszy czas do d przy obecnym tłoku (heurystyka = ile krok nadkłada). Tylko kroki,
które zbliżają do celu (efektywne ścieżki, Dial 1971): mrówka nie krąży i nie utyka.
Ludzie pary dzielą się równo między ścieżki jej mrówek; przepływ jest uśredniany po
iteracjach krokiem 1/n (metoda kolejnych średnich, jak u D'Acierno i in. 2012). Feromon
osobny dla każdego celu, parowanie ρ = 0,1, każda mrówka odkłada (najkrótszy czas pary / czas
swojej ścieżki) / 8, przycinanie do [0,05; 5] jak w MMAS. Kompilowane numbą, ok. 5 s.

**Odniesienia.** `aon`: wszyscy najkrótszą drogą bez tłoku (to zakłada poziom 2), oceniane z
tłokiem; `run_msa`: równowaga użytkowników (Wardrop) metodą kolejnych średnich z
najkrótszymi ścieżkami; bez tłoku: dolna granica.

| przypisanie | średnie przejście | vs najkrótsza | odcinki ponad C |
|---|---|---|---|
| bez tłoku | 324,4 s | | |
| wszyscy najkrótszą, z tłokiem | 383,2 s | | 7 (maks. 1,45 C) |
| mrówki (5 ziaren) | 341,8–341,9 s | −10,8 % | 0 |
| MSA (równowaga) | 336,0 s | −12,3 % | 0 |

Feromon pomaga (`walk_aco_ablation.csv`, 5 ziaren): α = 0 → 344,6 s, α = 1 → 341,9 s,
α = 2 → 340,0 s. Mrówki są 1,7 % od równowagi deterministycznej, bo rozkład jest
stochastyczny (część ludzi idzie trasą trochę dłuższą od najkrótszej), czyli bliżej
równowagi stochastycznej niż Wardropa.

**Wnioski i ograniczenia.** W szczycie tłok dokłada ok. 18 % czasu przejścia, a najbardziej
obciążone są chodniki między budynkami B i D wzdłuż Czarnowiejskiej. Czas „bez metra” w
funkcji celu poziomu 2 jest więc w szczycie niedoszacowany, czyli metro realnie oszczędzałoby
więcej; poziomy nie są (jeszcze) połączone. Model jest statyczny (jeden okres 5 min, bez
fali w czasie), szerokości chodników są przyjęte z typu drogi, a do popytu nie weszły dojścia
do przystanków.

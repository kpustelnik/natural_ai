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

**Powiązane prace** (szczegóły w [`docs/literatura.md`](../literatura.md)). Algorytm mrówkowy
wywodzi się z eksperymentu Gossa i in. (1989): kolonia wybiera krótszą gałąź mostka dzięki
dodatniemu sprzężeniu przez feromon. Najbliższe zastosowania to prace Korzenia i Kruszyny:
ocena pięciu gotowych wariantów tunelu kolei miejskiej we Wrocławiu (2023) i przebieg jednej
linii tramwajowej (2025), obie z heurystyką „wysiłku” opartą na długości, liczbie mieszkańców
i atrakcyjności. My przeszukujemy całą przestrzeń linii (ok. 2·10⁸ przy k = 5), popyt
bierzemy z planu zajęć zamiast z liczby mieszkańców, autobus i tramwaj są alternatywą w
funkcji celu, a wynik weryfikujemy przeglądem zupełnym, innymi metodami i symulacją.

## 2. Dane

| źródło | co | skala |
|---|---|---|
| USOS AGH (publiczne API + katalog USOSweb) | plany sal, grupy zajęć, liczebności, kohorty (kierunek + semestr), daty spotkań | 13 881 zajęć tygodniowo, 15 395 grup, 544 kohorty; cały semestr: 8 889 przedmiotów, 157 437 spotkań |
| OpenStreetMap | budynki, wejścia, chodniki, schody, bariery | graf pieszy: 5 622 węzły, 6 832 krawędzie |
| model kampusu (`data/campus/`) | 89 budynków w YAML (szkielety LOD1 z OSM, uzupełnione ręcznie: obrys, wysokość, wejścia, aliasy USOS), 12 przystanków; bez przejść między budynkami | |
| GTFS ZTP Kraków | autobusy i tramwaje między przystankami kampusu | kursy jednego dnia roboczego |
| akademiki | 20 domów studenckich, 6 997 miejsc | |

Z planów zajęć powstaje syntetyczna populacja (22 571 studentów w kohortach, mieszkańcy
akademików i dojeżdżający) i ich tygodniowe przejścia: **286 265 przejść** (zajęcia →
zajęcia, dom → zajęcia, zajęcia → dom), zagregowane do 4 835 par (skąd, dokąd).

## 3. Model

**Graf.** Chodniki z OSM połączone z budynkami i przystankami; czas krawędzi z prędkości
pieszej 1,3 m/s i osobnych prędkości na schodach w górę i w dół. Wszystkie 89 budynków
kampusu jest w LOD1 (bryła bez wnętrza): budynek to jeden węzeł przy głównym wejściu,
połączony z każdym wejściem. Model obsługuje też wnętrza (LOD2: piętra, korytarze, schody;
LOD3: sale, wtedy przejścia kończą się w sali), ale sprawdzono je tylko na przykładowym
kampusie (`data/sample/campus`). Kandydat na stację to szyb pod wejściem budynku (głębokość
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

**Granice (test 6).** Bez metra: 152,7 mln s (42 407 studento-godzin tygodniowo). Dolne
ograniczenie „teleportacji” (przejazd trwa 0 s, każda para ma swoje dwie najlepsze stacje):
90,5 mln s, czyli żadna linia nie da więcej niż **40,7 %** oszczędności. Każda znaleziona
linia mieści się między granicami (sprawdzane w `bounds.csv` i w każdym `best_line.json`).

## 4. Algorytmy

- **MMAS** (Stützle, Hoos 2000): mrówka wybiera następną stację z prawdopodobieństwem
  ∝ τ^α η^β; η = popyt w pobliżu kandydata / odległość; feromon w [τ_min, τ_max], odkłada
  najlepsza mrówka iteracji (co trzecią iterację najlepsza globalnie).
- **ACS** (Dorigo, Gambardella 1997): reguła q0 (z prawdopodobieństwem q0 najlepsza stacja),
  lokalne parowanie ξ po każdym kroku, globalnie wzmacnia tylko najlepsza dotąd linia.
  Literaturowe q0 = 0,9 sprawiało, że mrówki budowały wciąż te same linie (50 × 200 mrówek:
  ~2 700 różnych, przy q0 = 0,5 ~7 900) i kończyły niżej; przyjęto 0,5.
- **Local search** (opcja wszystkich algorytmów poza przeglądem zupełnym): wymiana stacji
  na inną, zamiana dwóch, przestawienie jednej; najlepsza poprawa, aż żadna nie pomaga.
  Kolonie i losowe poprawiają najlepszą linię iteracji, zachłanny swoją końcową.
- **Losowe**: tyle losowych linii, ile zbudowałyby mrówki. **Zachłanny**: najlepsza para,
  potem k − 2 razy stacja i miejsce w linii, które najbardziej obniżają cel.
  **Przegląd zupełny**: każda linia raz (linia i jej odwrócenie to ta sama linia).
- **Uczciwe porównanie** (Derrac i in. 2011): wspólny budżet różnych ocenionych linii
  (`optimize.max_evaluations`, sprawdzany po każdej iteracji, więc przekroczony najwyżej
  o ~20 linii), 30 seedów, test Wilcoxona dla prób sparowanych po seedzie, a ponieważ
  ten sam seed nie łączy przebiegów dwóch algorytmów w pary, także test Manna–Whitneya dla
  prób niezależnych z korektą Holma i miarą efektu A₁₂ (Vargha, Delaney 2000;
  `metro_agh/stats.py`).

## 5. Wyniki optymalizacji

### 5.1 Najlepsza linia (k = 5)

**H-D8 – C-4 – U-9 – D-10 – A-0**: cel 135,0 mln s, **11,6 % mniej** niż bez metra
(4 916 studento-godzin tygodniowo). Tę linię znajdują MMAS + LS i losowe + LS przy każdym
z 30 seedów, ACS + LS przy 29.

### 5.2 Ile stacji (`k_sweep.png`)

| k | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|
| oszczędność % | 6,62 | 8,94 | 10,25 | 11,59 | 12,68 | 13,49 | 14,16 | 14,72 | 15,16 |
| przyrost (p.p.) | | +2,32 | +1,31 | +1,34 | +1,09 | +0,81 | +0,67 | +0,56 | +0,44 |

Przyrosty na ogół maleją (z drobnym wyjątkiem k = 5): pierwsze stacje obsługują
najliczniejsze pary budynków, kolejne coraz rzadsze, a każdy postój spowalnia jadących
dalej. Powyżej k = 7 każda stacja dodaje mniej niż 0,7 p.p.; to rozsądna górna granica,
jeśli liczyć koszt budowy stacji.

### 5.3 Porównanie algorytmów (test 2, `compare_algorithms.png`)

k = 5, 5 000 linii na uruchomienie, 30 seedów:

| | z local search | bez |
|---|---|---|
| MMAS | 11,59 % (zawsze) | 11,38 % (11,06–11,59) |
| ACS | 11,59 % (11,39–11,59) | 11,38 % (10,96–11,59) |
| losowe | 11,59 % (zawsze) | 9,71 % (9,18–10,32) |
| zachłanny | 11,26 % | 11,26 % |

Bez local search obie kolonie biją losowe przeszukiwanie przy każdym z 30 seedów
(Wilcoxon, p ≈ 2·10⁻⁹): mrówki uczą się struktury problemu. Metodę zachłanną MMAS bije
przy 28 seedach (1 porażka, 1 remis; p ≈ 2·10⁻⁵), ACS przy 23 (6 porażek; p ≈ 3·10⁻⁴);
MMAS i ACS nie różnią się istotnie (p = 0,96). Kolonie potrzebują na to budżetu: średnio
przeganiają zachłanny (11,26 %) dopiero po ~1 950 (MMAS) i ~2 870 (ACS) ocenionych liniach
(5.5), a zachłanny zużywa ich 2 107. Z local search przy k = 5 instancja jest łatwa:
kolonie i losowe dochodzą do tej samej linii, a zachłanny + LS zostaje przy swojej
(11,26 %), bo jest ona lokalnym optimum wymian, zamian i przestawień.

Te same porównania jako próby niezależne (Mann–Whitney, korekta Holma, A₁₂ = szansa, że
losowy przebieg MMAS oszczędza więcej; `compare_algorithms.csv`): bez local search MMAS jest
lepszy od losowego (p_Holm ≈ 5·10⁻¹¹, A₁₂ = 1,00, efekt duży), od ACS nieistotnie
(p = 0,08, A₁₂ = 0,63, efekt mały), a od zachłannego (jeden wynik, więc bez testu) we
wszystkich 30 przebiegach z obecnego `runs.csv` (A₁₂ = 1,00). Z local search MMAS, ACS i losowe dają identyczny wynik
(A₁₂ = 0,50).

Trudniejsze ustawienie (`compare_algorithms_hard.png`, k = 10, 60 000 linii): MMAS + LS
15,14 %, losowe + LS 15,13 %, ACS + LS 15,12 %, zachłanny + LS 14,85 %; najlepsza znaleziona
linia 15,16 % (MMAS + LS trafia ją przy 20 seedach, losowe + LS przy 19, ACS + LS przy 16).
Różnice między MMAS + LS, ACS + LS i losowym + LS nie są istotne (p = 0,10; 0,25; 0,53);
każda z tych trzech bije zachłanny + LS przy każdym seedzie (p < 10⁻⁵). Na tej instancji
o jakości decyduje local search, a strategia, która dostarcza mu punkty startowe, ma
drugorzędne znaczenie.

### 5.4 Odległość od optimum (test 1, `gap_to_optimum.png`)

5 podinstancji po 12 kandydatów (z 30 o największym popycie), k = 4 (5 940 linii), budżet
200 linii (≈ 3 % wszystkich), 10 seedów; luka = część optymalnej oszczędności, której
algorytm nie znalazł.

| | trafienie optimum | średnia luka | maks. luka |
|---|---|---|---|
| MMAS + LS | 84 % | 0,39 % | 2,50 % |
| ACS + LS | 94 % | 0,11 % | 2,38 % |
| losowe + LS | 88 % | 0,29 % | 2,50 % |
| zachłanny + LS | 4 / 5 | 0,48 % | 2,38 % |
| MMAS | 16 % | 3,72 % | 12,84 % |
| ACS | 30 % | 2,67 % | 15,29 % |
| losowe | 4 % | 7,65 % | 17,51 % |
| zachłanny | 3 / 5 | 0,48 % | 2,38 % |

Przy 3 % budżetu kolonie z local search znajdują dokładne optimum w 84–94 % uruchomień.
Bez local search zachłanny wypada tu lepiej od kolonii: 200 linii to tylko ~20 (MMAS) – 40 (ACS)
iteracji po 10 mrówek, za mało, żeby feromon się czegoś nauczył, a zachłanny mieści się w budżecie w całości
(~130 linii). Na pełnej instancji z 5 000 linii kolejność się odwraca (5.3).

### 5.5 Zbieżność (test 3, `compare_algorithms_convergence.png`)

Bez local search ACS rośnie szybciej na początku (reguła q0 eksploatuje): końcowy wynik
losowego przeszukiwania (9,71 %) osiąga po ~270 liniach, MMAS po ~480. Obie kolonie są
na 11 % po ~1 230 liniach, przeganiają zachłanny po ~1 950 (MMAS) i ~2 870 (ACS) i kończą
na tym samym poziomie (11,38 %). Z local search pierwsze zejście zużywa ~1 300–1 700 linii
i od razu daje ~11,5 %.

Przy k = 10 (`compare_algorithms_hard_convergence.png`) pierwsze zejście local search
zużywa ~5 700–6 600 linii; dalej wszystkie trzy warianty rosną powoli i podobnie, a połowa
uruchomień znajduje swoją najlepszą linię dopiero po ~25 000–27 000 liniach.

### 5.6 Wrażliwość parametrów (test 4, `aco_ablation.png`)

MMAS bez local search, 20 mrówek × 100 iteracji, 10 seedów, po jednym parametrze:

| parametr | wartości → średnia oszczędność % |
|---|---|
| β (waga heurystyki) | 0 → 10,77; **1 → 11,18**; 3 → 10,23; 5 → 8,61 |
| α (waga feromonu) | 0,5 → 10,70; **1 → 11,18**; 2 → 11,05 |
| ρ (parowanie) | 0,05 → 11,04; **0,1 → 11,18**; 0,2 → 11,37 |
| mrówki | 10 → 11,04; 20 → 11,18; 50 → 11,41 |
| iteracje | 50 → 10,85; 100 → 11,18; 200 → 11,33 |

Najsilniej działa β: heurystyka „popyt w pobliżu / odległość” pomaga tylko słabo (β = 1
lepsze od β = 0), a silna (β = 3–5) prowadzi mrówki w złą stronę. Prawdopodobna przyczyna:
popyt blisko kandydata nie mówi, czy jego przejścia są długie, a krótkie i tak wygrywa
chodzenie, więc stacja przy popularnym budynku często niewiele daje. Dlatego
domyślne β zmieniono z 3 na 1. α ma optimum w wartości domyślnej; szybsze parowanie
(ρ = 0,2) przy 100 iteracjach daje więcej niż domyślne 0,1. Więcej mrówek i iteracji
pomaga, ale coraz mniej; to także więcej ocenionych linii (budżet nie jest tu wyrównany).

### 5.7 Dodatkowe eksperymenty (`scripts/plot_extra.py`)

Testy jak w 5.3: Mann–Whitney względem pierwszego wariantu, korekta Holma, A₁₂.

**Dokładne optimum całego kampusu** (`exact_full.png`). Przegląd zupełny pełnej instancji
(N = 55): k = 2 (1 485 linii, optimum 6,56 %), k = 3 (78 705 linii, 8,90 %), k = 4 (4,1 mln
linii, 15 min, **10,23 %**). Budżet 5 000 linii (przy k = 4 to 0,12 % wszystkich), 10 seedów:

| k | MMAS + LS | MMAS | ACS + LS | ACS | zachłanny (z LS i bez) |
|---|---|---|---|---|---|
| 2, 3 | 100 % | 100 % | 100 % | 100 % | optimum |
| 4 | **100 %** | 80 % | 70 % | 50 % | brak (luka 0,07 %) |

Wynik z podinstancji (5.4) potwierdza się na prawdziwej instancji: MMAS + LS znajduje dokładne
optimum przy każdym seedzie, zachłanny utyka w lokalnym optimum. Wartość k = 4 z 5.2 jest
optymalna.

**Heurystyka η** (`heuristic.png`). MMAS bez local search, k = 5, 5 000 linii, 20 seedów;
odpowiednik porównania „zmodyfikowane vs klasyczne ACO” Korzenia i Kruszyny (2025):

| heurystyka η | średnio | zakres | względem naszej |
|---|---|---|---|
| popyt / odległość (nasza) | 11,43 % | 11,31–11,60 | — |
| 1 / odległość (klasyczna, jak w TSP) | 10,98 % | 10,15–11,60 | gorsza: A₁₂ = 0,87, p_Holm = 2·10⁻⁴ |
| tylko popyt | 11,52 % | 11,39–11,60 | lepsza: A₁₂ = 0,26, p_Holm = 0,013 |
| brak (β = 0) | 11,37 % | 10,97–11,60 | bez istotnej różnicy (A₁₂ = 0,56) |

Klasyczna heurystyka odległości szkodzi, i to bardziej niż brak heurystyki (p = 0,001,
A₁₂ = 0,80): pcha mrówki ku krótkim odcinkom, a dobre linie mają długie przeskoki. Pomaga
składnik popytu; to uzupełnia wniosek z 5.6 (β = 1).

**Linia czy pętla** (`topology.png`; MMAS + LS, 10 seedów). Pętla wygrywa przy każdym
seedzie: k = 5 **11,98 %** zamiast 11,60 % (te same stacje C-4, U-9, H-D8, A-0, D-10 w innej
kolejności), k = 7 13,88 % zamiast 13,37 %. Pętla nie ma końców, więc dwie stacje dzieli co
najwyżej połowa obwodu; płaci za to dłuższym tunelem (k = 5: 3,85 km zamiast 3,22 km).

**Wrażliwość na założenia o pociągach** (`sensitivity.png`; MMAS + LS, k = 5, 10 seedów,
jeden parametr naraz):

| parametr | wartości → oszczędność | podobieństwo stacji do linii bazowej (Jaccard) |
|---|---|---|
| postój | 15 s → 12,0 %; **30 s → 11,6 %**; 60 s → 11,4 % | 0,94; 1; 1 |
| odstęp pociągów | 120 s → 13,3 %; **180 s → 11,6 %**; 300 s → 8,4 % | 0,97; 1; 1 |
| prędkość | 8 m/s → 10,2 %; **10 m/s → 11,6 %**; 15 m/s → 13,6 % | 1; 1; 1 |

Wybór stacji praktycznie nie zależy od założeń, których nie da się sprawdzić; zależy od nich
tylko wielkość oszczędności. Najsilniej działa częstotliwość, bo czekanie płaci każdy pasażer.

**Długość tunelu** (`tunnel.png`, najlepsza linia z 5.2 dla każdego k): k = 2: 1,1 km, k = 4:
1,4 km, **k = 5: 3,2 km**, k = 7: 2,7 km, k = 10: 5,1 km. Funkcja celu nie zawiera kosztu
budowy, więc linia może „zygzakować”: k = 4 daje 3 070 studento-godzin tygodniowo na km tunelu,
k = 5 tylko 1 530. Przy koszcie tunelu k = 4 lub k = 7 byłyby lepsze od k = 5 (opcja
`metro.tunnel_penalty_per_km` pozwala uwzględnić to w optymalizacji).

## 6. Symulacja tygodnia (`simulation_metrics.csv`)

Każde z 286 265 przejść, bez metra i z linią z 5.1, z prawdziwym rozkładem (metro co 180 s
w obie strony, autobusy i tramwaje z GTFS). Student jedzie, gdy dotrze wcześniej niż
pieszo; z domu na zajęcia wychodzi najpóźniej, jak może (jedzie, gdy pozwala to wyjść
później), po zajęciach wychodzi od razu.

| | bez metra | z metrem |
|---|---|---|
| studento-godziny w tygodniu | 41 095 | 35 959 |
| oszczędność | | **308 135 studento-minut** (15,0 min na studenta) |
| spóźnione przejścia | 1 519 | 1 319 |
| spóźnione przejścia między zajęciami (dłuższe niż przerwa) | 1,47 % | 1,27 % |
| spóźnione zajęcia (dzień, budynek, godzina rozpoczęcia) | 503 z 2 335 | 450 z 2 335 |
| przejazdy metrem | | 28,8 % |
| przejazdy autobusem / tramwajem | 40,5 % | 23,1 % |

Minuty na studenta liczone są na 20 573 studentów, którzy mają w tygodniu choć jedno
przejście. Symulacja daje 12,5 % mniej czasu, nieco więcej niż funkcja celu (11,6 %):
z prawdziwym rozkładem studenci jadący na zajęcia wychodzą później, a funkcja celu liczy
średnie czekanie (połowa odstępu). Metro przejmuje głównie przejazdy autobusami między
przystankami kampusu.

## 7. Walidacja modelu świata (test 5)

Pomiarów terenowych (czasy przejść mierzone stoperem vs graf) nie wykonano. Czasy dojść
wynikają z długości chodników OSM i przyjętych prędkości (1,3 m/s poziomo, osobne prędkości
na schodach w `config.yaml`), więc ich dokładność jest niezweryfikowana. Błąd prędkości
pieszej przesuwa wynik w przewidywalną stronę: jeśli studenci chodzą wolniej, metro (o stałej
prędkości) oszczędza więcej, jeśli szybciej, mniej. Narzędzie do porównania jest gotowe
(`scripts/validate_field.py`), gdyby pomiary powstały.

## 8. Wnioski

1. Linia **H-D8 – C-4 – U-9 – D-10 – A-0** oszczędza ok. **12 %** czasu przejść (11,6 %
   w funkcji celu, 12,5 % w symulacji), około 15 minut na studenta tygodniowo, i zmniejsza
   liczbę spóźnionych zajęć o ok. 10 % (503 → 450).
2. Opłacalne jest 5–7 stacji; dalej każda stacja daje mniej niż 0,7 p.p.
3. Same mrówki (MMAS, ACS) są lepsze od losowego przeszukiwania, a przy wystarczającym
   budżecie (~2 000–3 000 linii) także od metody zachłannej; z małym budżetem zachłanny
   wygrywa. Dopiero z lokalnym przeszukiwaniem znajdują optimum niezawodnie (84–94 % przy
   3 % budżetu); to zgodne z literaturą (Stützle, Hoos 2000).
4. Heurystyka popytu musi być słaba (β = 1): popyt blisko stacji nie mówi, czy metro się
   przyda, bo liczą się długie przejścia. Klasyczna heurystyka odległości z TSP szkodzi
   (5.7).
5. Na całym kampusie dla k ≤ 4 (do 4,1 mln linii) MMAS + LS znajduje dokładne optimum przy
   każdym seedzie, mając 0,12 % przestrzeni; metoda zachłanna go nie znajduje (5.7).
6. Pętla zamiast linii daje ok. 0,4–0,5 p.p. więcej, kosztem dłuższego tunelu; wybór stacji
   nie zależy od założeń o postoju, częstotliwości i prędkości pociągów (5.7).

**Ograniczenia:** populacja syntetyczna (rozkład studentów na grupy z liczebności USOS),
jeden tydzień, brak tłoku i pojemności pociągów, brak kosztu budowy, tunel po prostej, wszystkie
budynki jako bryły bez wnętrz (LOD1: przejście kończy się przy głównym wejściu, nie w sali), czasy przejść niezweryfikowane pomiarami w terenie. Brak kosztu budowy widać w długości
tunelu: najlepsza linia k = 5 ma 3,2 km, więcej niż linia k = 7 (5.7).

## 9. Odtworzenie wyników

Dane po etapach 01–03 są w repozytorium (`data/processed/`), więc wystarczy zacząć od 04.
Pełne przeliczenie od zera:

```bash
uv run scripts/01_fetch_usos.py          # USOS (około godziny pierwszy raz, potem z cache)
uv run scripts/01_fetch_transit.py       # GTFS ZTP Kraków
uv run scripts/02_build_campus.py        # OSM + model kampusu -> graf pieszy
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
for e in exact_full_brute exact_full heuristic topology sensitivity; do   # 5.7, ok. 30 min
  uv run scripts/run_experiments.py --config experiments/configs/$e.yaml
done
uv run scripts/plot_extra.py all
```

Opis całej części optymalizacyjnej dla prezentującego: [`docs/aco.md`](../aco.md).

Literatura: [`docs/literatura.md`](../literatura.md).

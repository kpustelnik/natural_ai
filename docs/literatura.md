# Przegląd literatury

Notatki do sprawozdania: co mówi literatura i jak to wykorzystujemy w projekcie. Przed
oddaniem sprawdzić strony i numery tomów w bazie wydawcy (Scopus / IEEE Xplore / Elsevier).

## 0. Inspiracja biologiczna

- **Goss, Aron, Deneubourg, Pasteels (1989)**, *Self-organized shortcuts in the Argentine
  ant*, Naturwissenschaften 76, 579–581 (PDF w `references/`). Kolonia mrówek *Iridomyrmex
  humilis* połączona z pokarmem mostkiem o dwóch gałęziach wybiera krótszą (14 z 14 kolonii
  przy stosunku długości 2), choć żadna mrówka nie porównuje długości. Mrówki znaczą szlak
  w obie strony; ta z krótszej gałęzi wraca wcześniej i oznacza rozwidlenie drugi raz, zanim
  zrobią to mrówki z dłuższej, a przewaga się wzmacnia (wybór ∝ (20 + S)² / ((20 + S)² +
  (20 + L)²)). Feromon żyje dłużej niż eksperyment, więc parowanie pominięto, i kolonia,
  która utrwaliła dłuższą gałąź, **nie przełącza się** na krótszą dodaną później (2 z 18).
  U nas: reguła wyboru ∝ τ^α η^β to uogólnienie ich funkcji wyboru (α ≈ wykładnik 2, η
  dodaje to, co mrówka „widzi”); lepsza linia odkłada więcej feromonu (Δ = koszt bez metra
  / koszt linii), jak krótsza gałąź znaczona częściej; feromon jest symetryczny (znaczenie w
  obie strony); parowanie ρ i dolne ograniczenie τ_min w MMAS (a w ACS lokalne parowanie ξ)
  usuwają ich „nieodwracalność”, więc kolonia może porzucić gorszą linię. Spadek entropii
  feromonu na wykresach zbieżności to odpowiednik ich „jedna gałąź staje się wyraźnie
  preferowana”.

## 1. Projektowanie sieci transportu zbiorowego

- **Laporte, Mesa, Ortega (2000)**, *Optimization methods for the planning of rapid transit
  systems*, European Journal of Operational Research 122(1), 1–10.
  Przegląd metod planowania linii szybkiego transportu (metro, kolej miejska): wybór
  korytarza, rozmieszczenie stacji, kompromis między pokryciem popytu a kosztem budowy.
  U nas: wybór k stacji spośród kandydatów i ich kolejności na jednej linii, z celem
  „łączny czas podróży studentów”, bez kosztu budowy (k jest parametrem, por. `k_sweep`).
- **Guihaire, Hao (2008)**, *Transit network design and scheduling: A global review*,
  Transportation Research Part A 42(10), 1251–1273.
  Klasyfikacja problemów: projektowanie tras, częstotliwości, rozkładów, oraz metod
  (dokładne, heurystyki, metaheurystyki). Nasz problem to projektowanie jednej trasy przy
  stałej częstotliwości (`metro.headway_s`), z rozkładem wyznaczanym potem w symulacji.
- **Farahani, Miandoabchi, Szeto, Rashidi (2013)**, *A review of urban transportation
  network design problems*, European Journal of Operational Research 229(2), 281–302.
  Szerszy przegląd problemów projektowania sieci miejskich; pokazuje, że metaheurystyki
  (algorytmy genetyczne, mrówkowe, symulowane wyżarzanie) są standardem tam, gdzie przestrzeń
  rozwiązań jest kombinatoryczna, jak u nas (kampus: ok. 2·10⁸ linii przy k = 5).
- **Ceder, Wilson (1986)**, *Bus network design*, Transportation Research Part B 20(4),
  331–344. Klasyczne sformułowanie projektowania tras z perspektywy pasażera (czas podróży,
  przesiadki) i operatora; nasza funkcja celu to perspektywa pasażera.

### 1.1 Algorytm mrówkowy w planowaniu kolei i tramwajów (najbliższe prace)

- **Korzeń, Kruszyna (2023)**, *Modified Ant Colony Optimization as a Means for Evaluating
  the Variants of the City Railway Underground Section*, International Journal of
  Environmental Research and Public Health 20(6), 4960 (PDF w `references/`). Pięć
  zaprojektowanych ręcznie wariantów tunelu kolei miejskiej pod centrum Wrocławia (3–9
  stacji) oceniane zmodyfikowanym Ant System (ρ = 0,5, α = 1, β = 2). Heurystyka to macierz
  „wysiłku” E_ij = (L_ij / L_c) · (1 − I_ij / I_c) · (1 / A_ij) · (S_max / S_c): udział
  długości, mieszkańcy w promieniu 300 m od stacji, liczba linii autobusowych i tramwajowych
  oraz nowe obszary z dostępem do kolei. Wygrywa wariant o najmniejszym łącznym wysiłku.
- **Korzeń, Kruszyna (2025)**, *Public Transport Planning Using Modified Ant Colony
  Optimization*, Sustainability 17(6), 2468 (PDF w `references/`). Przebieg jednej linii
  tramwajowej (nr 12) między ustalonymi końcami na grafie skierowanym sieci Wrocławia; wysiłek
  odcinka e_ij = (t_R / t_S) · (L_ij / L_c) · (V_o / V_r) · D_ij · A_ij · I_ij (czas
  rzeczywisty / rozkładowy, długość, prędkość, niepewność czasu D_ij z rozrzutu **co najmniej
  trzech pomiarów terenowych**, atrakcyjność, potencjał pasażerski). Porównanie wersji
  zmodyfikowanej z „klasycznym” ACO (sama odległość): trasa o 11,5 % mniejszym wysiłku niż
  obecna.

Porównanie z naszym projektem:

| | Korzeń, Kruszyna 2023 | Korzeń, Kruszyna 2025 | ten projekt |
|---|---|---|---|
| zadanie | ocena 5 gotowych wariantów tunelu | przebieg jednej linii między stałymi końcami | wybór i kolejność k z 55 kandydatów (~2·10⁸ linii przy k = 5) |
| popyt | mieszkańcy w pobliżu stacji (wszyscy jadą koleją) | potencjał pasażerski z liczby mieszkańców | 286 tys. przejść tygodniowo z planu USOS; metro tylko gdy szybsze |
| inne środki | liczba linii autobusowych / tramwajowych jako atrakcyjność | — | rozkładowy autobus / tramwaj jako alternatywa w funkcji celu |
| funkcja celu | suma wysiłku krawędzi (najkrótsza ścieżka) | suma wysiłku odcinków | łączny czas wszystkich przejść; wartość odcinka zależy od całej linii |
| walidacja | brak (jedno uruchomienie, ranking) | vs obecna trasa i klasyczne ACO | przegląd zupełny, 4 inne metody, 30 seedów, testy statystyczne, symulacja |

Ich własne ograniczenia („ograniczona lista tras”, „ograniczona liczba kryteriów”,
„wszyscy mieszkańcy jadą tylko koleją”, „można przetestować inne metody optymalizacji”) to
dokładnie to, co rozwiązuje nasze sformułowanie. Co od nich bierzemy: długość tunelu jako
wielkość raportowana przy każdej linii (`Objective.tunnel_m`), porównanie naszej heurystyki
z klasyczną heurystyką odległości (eksperyment `heuristic.yaml`) i protokół pomiarów
terenowych (≥ 3 przejścia na trasę, rozrzut), gdyby pomiary powstały (`validate_field.py`).

## 2. Algorytmy mrówkowe

- **Dorigo, Maniezzo, Colorni (1996)**, *Ant System: optimization by a colony of
  cooperating agents*, IEEE Transactions on Systems, Man, and Cybernetics, Part B 26(1),
  29–41. Pierwotny Ant System: mrówki budują rozwiązania krok po kroku z prawdopodobieństwem
  ∝ τ^α η^β, feromon paruje i jest odkładany proporcjonalnie do jakości. Wzór wyboru
  następnej stacji w `aco/common.py` (`pick`) jest stąd.
- **Dorigo, Gambardella (1997)**, *Ant Colony System: A cooperative learning approach to
  the traveling salesman problem*, IEEE Transactions on Evolutionary Computation 1(1),
  53–66. ACS: reguła pseudolosowo-proporcjonalna (`q0`), lokalna aktualizacja feromonu
  (`xi`, powrót do τ0) i globalna tylko przez najlepsze rozwiązanie. Zaimplementowane w
  `aco/acs.py`; u nas `q0 = 0.9` z artykułu powodował budowanie wciąż tych samych linii,
  stąd `q0 = 0.5`.
- **Stützle, Hoos (2000)**, *MAX–MIN Ant System*, Future Generation Computer Systems 16(8),
  889–914. MMAS: feromon ograniczony do [τ_min, τ_max], odkłada tylko najlepsza mrówka
  (iteracji lub globalnie), inicjalizacja na τ_max; autorzy łączą MMAS z lokalnym
  przeszukiwaniem i pokazują, że to ono daje najlepsze wyniki. U nas (`aco/mmas.py`,
  `aco/local_search.py`) dokładnie to samo widać w porównaniu z i bez local search.
- **Dorigo, Stützle (2004)**, *Ant Colony Optimization*, MIT Press. Podręcznik: wspólny
  opis wariantów, wybór parametrów (α, β, ρ, liczba mrówek), rola heurystyki η i lokalnego
  przeszukiwania. Punkt odniesienia dla analizy wrażliwości (`aco_ablation.yaml`).

### 2.1 ACO poziom 1: rozkład ruchu pieszego

- **D'Acierno, Gallo, Montella (2012)**, *An Ant Colony Optimisation algorithm for solving
  the asymmetric traffic assignment problem*, European Journal of Operational Research
  217(2), 459–469. Mrówki generują ścieżki, a przepływy uśrednia się jak w metodzie
  kolejnych średnich (MSA); ta sama dokładność co MSA w krótszym czasie. U nas: przepływ
  poziomu 1 uśredniany krokiem 1/n (`walk/assign.py`, `run_walk_aco`).
- **Dial (1971)**, *A probabilistic multipath traffic assignment model which obviates path
  enumeration*, Transportation Research 5(2), 83–111. „Efektywne” kroki, które zbliżają do
  celu: mrówka poziomu 1 wybiera tylko takie, więc nie krąży.
- **Lam, Cheung (2000)**, *Pedestrian speed/flow relationships for walking facilities in Hong
  Kong*, Journal of Transportation Engineering 126(4), 343–349. Funkcja czasu przejścia
  typu BPR dla chodników.
- **Rouphail i in. / FHWA (1998)**, *Pedestrian and Bicycle Capacity Analysis*,
  FHWA-RD-98-107: przepustowość chodnika 75 os./min/m, prędkość przy przepustowości
  0,75 m/s (`walk_aco.capacity_ped_min_m`, `bpr_a`).

## 3. Metodyka porównań i statystyka

- **Derrac, García, Molina, Herrera (2011)**, *A practical tutorial on the use of
  nonparametric statistical tests as a methodology for comparing evolutionary and swarm
  intelligence algorithms*, Swarm and Evolutionary Computation 1(1), 3–18. Zalecenia:
  wiele niezależnych uruchomień (seedów), ten sam budżet ewaluacji, testy nieparametryczne
  zamiast t-testu. Stąd 30 seedów, wspólne `optimize.max_evaluations` i test Wilcoxona w
  `plot_experiments.py`.
- **Wilcoxon (1945)**, *Individual comparisons by ranking methods*, Biometrics Bulletin
  1(6), 80–83. Test rangowanych znaków dla prób sparowanych (u nas: ten sam seed, dwa
  algorytmy) oraz test sumy rang dla prób niezależnych.
- **Mann, Whitney (1947)**, *On a test of whether one of two random variables is
  stochastically larger than the other*, Annals of Mathematical Statistics 18(1), 50–60.
  Test U dla prób niezależnych: przebiegi dwóch algorytmów z tym samym seedem nie tworzą
  pary (każdy algorytm zużywa liczby losowe inaczej), więc obok testu sparowanego podajemy
  ten (`metro_agh/stats.py`, kolumna `p_mw`).
- **Holm (1979)**, *A simple sequentially rejective multiple test procedure*, Scandinavian
  Journal of Statistics 6(2), 65–70. Korekta wielu porównań z jednym algorytmem odniesienia
  (kolumna `p_holm`).
- **Vargha, Delaney (2000)**, *A critique and improvement of the CL common language effect
  size statistics of McGraw and Wong*, Journal of Educational and Behavioral Statistics 25(2),
  101–132. Miara efektu A₁₂ = P(przebieg X oszczędza więcej niż przebieg Y); 0,5 = brak
  różnicy, ≥ 0,71 duży efekt (kolumna `a12`). Przy 30 seedach nawet mała różnica bywa
  „istotna”, więc wielkość efektu mówi więcej niż samo p.

## 4. Dane i graf

- **Weidmann (1993)**, *Transporttechnik der Fussgänger*, IVT Schriftenreihe 90, ETH
  Zürich: średnia prędkość swobodna pieszego 1,34 m/s (u nas 1,3 m/s).
- **Fruin (1971)**, *Pedestrian Planning and Design*: prędkości na schodach 0,51–0,57 m/s
  w górę i 0,67–0,77 m/s w dół wzdłuż biegu (nasze prędkości w pionie, 0,35 / 0,45 m/s, są
  założeniem i raczej optymistyczne).
- **Stałe metra**: prędkość handlowa planowanego metra w Krakowie ok. 32–36 km/h (studium
  wariantów, stm.krakow.pl), u nas 10 m/s = 36 km/h; odstęp w szczycie w Warszawie: M2 co
  2 min 50 s, M1 co 2 min 20 s (komunikat WTP), u nas 180 s; postój typowo 15–45 s, u nas
  30 s; głębokość 15 m i godziny 7–21: założenia.
- **Akademiki**: Miasteczko Studenckie AGH ma ok. 7 tys. miejsc dla studentów w 20 domach
  (Radio Kraków), u nas `population.dorm_beds: 7000`.
- **Holliday, El-Geneidy, Dudek (2024)**, *Learning Heuristics for Transit Network Design
  and Improvement with Deep Reinforcement Learning*, arXiv:2404.05894. Projektowanie sieci
  linii; metody uczone z metaheurystykami (odniesienie z opisu etapu 0).


- **Boeing (2017)**, *OSMnx: New methods for acquiring, constructing, analyzing, and
  visualizing complex street networks*, Computers, Environment and Urban Systems 65,
  126–139. Pobieranie i budowa grafu pieszego z OpenStreetMap (`campus/osm.py`,
  `campus/osm_process.py`).
- **Dijkstra (1959)**, *A note on two problems in connexion with graphs*, Numerische
  Mathematik 1, 269–271. Najkrótsze ścieżki na grafie pieszym (czasy dojść w instancji i
  w symulacji; `scipy.sparse.csgraph.dijkstra`).
- Dane: USOS AGH (publiczne API i katalog USOSweb), GTFS ZTP Kraków, OpenStreetMap
  (licencja ODbL), ortofotomapa GUGiK (WMS).

## 5. Co z tego wynika dla projektu

1. Funkcja celu z perspektywy pasażera (łączny czas, min(pieszo / autobus, metro)) jest
   typowa dla projektowania tras; brak kosztu budowy zastępuje analiza k.
2. Sam algorytm mrówkowy bez lokalnego przeszukiwania przegrywa z prostą heurystyką
   zachłanną przy małym budżecie (podinstancje, 200 linii) i wygrywa z nią dopiero po
   ~2 000–3 000 ocenionych liniach, a optimum znajduje rzadko; literatura (Stützle, Hoos
   2000; Dorigo, Stützle 2004) przewiduje to i zaleca hybrydę ACO + local search, co
   potwierdzają nasze wyniki (84–94 % trafień optimum z local search).
3. Porównanie algorytmów wymaga równego budżetu ewaluacji i testów nieparametrycznych na
   wielu seedach (Derrac i in. 2011); tak zbudowane są `compare_algorithms*.yaml`. Dla prób
   niezależnych: Mann–Whitney z korektą Holma i A₁₂; bez local search MMAS jest wyraźnie
   lepszy od losowego (p_Holm ≈ 5·10⁻¹¹, A₁₂ = 1,00), ale od ACS tylko nieistotnie
   (p = 0,08, A₁₂ = 0,63, mały efekt).
4. W odróżnieniu od najbliższych prac (Korzeń, Kruszyna 2023, 2025) przeszukujemy całą
   przestrzeń linii zamiast oceniać gotowe warianty, popyt bierzemy z rzeczywistego planu
   zajęć zamiast z liczby mieszkańców, a wynik sprawdzamy przeglądem zupełnym, innymi
   metodami i symulacją.
5. Mechanizm z eksperymentu Gossa i in. (1989), dodatnie sprzężenie przez feromon, bez
   parowania prowadzi do utrwalenia pierwszego wyboru; dlatego MMAS ogranicza feromon z dołu
   (τ_min), a ACS stosuje lokalne parowanie.

# Przegląd literatury

Notatki do sprawozdania: co mówi literatura i jak to wykorzystujemy w projekcie. Przed
oddaniem sprawdzić strony i numery tomów w bazie wydawcy (Scopus / IEEE Xplore / Elsevier).

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

## 3. Metodyka porównań i statystyka

- **Derrac, García, Molina, Herrera (2011)**, *A practical tutorial on the use of
  nonparametric statistical tests as a methodology for comparing evolutionary and swarm
  intelligence algorithms*, Swarm and Evolutionary Computation 1(1), 3–18. Zalecenia:
  wiele niezależnych uruchomień (seedów), ten sam budżet ewaluacji, testy nieparametryczne
  zamiast t-testu. Stąd 30 seedów, wspólne `optimize.max_evaluations` i test Wilcoxona w
  `plot_experiments.py`.
- **Wilcoxon (1945)**, *Individual comparisons by ranking methods*, Biometrics Bulletin
  1(6), 80–83. Test rangowanych znaków dla prób sparowanych (u nas: ten sam seed, dwa
  algorytmy).

## 4. Dane i graf

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
2. Sam algorytm mrówkowy bez lokalnego przeszukiwania jest słabszy od prostej heurystyki
   zachłannej na naszej instancji; literatura (Stützle, Hoos 2000; Dorigo, Stützle 2004)
   przewiduje to i zaleca hybrydę ACO + local search, co potwierdzają nasze wyniki.
3. Porównanie algorytmów wymaga równego budżetu ewaluacji i testów nieparametrycznych na
   wielu seedach (Derrac i in. 2011); tak zbudowane są `compare_algorithms*.yaml`.

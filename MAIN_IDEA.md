## Pomysł w jednym zdaniu

Z USOS wiemy, kto, kiedy i między którymi budynkami musi przejść. Mrówki szukają takiego przebiegu linii metra przez kampus, żeby te przejścia trwały łącznie jak najkrócej.

## Trzy składniki

**1. Popyt (z USOS).** Lista przejść: grupa ISI-3-g2, poniedziałek 9:30, z D-17 do B-1, 15 osób. Bierze się ją z kolejnych zajęć tej samej grupy tego samego dnia. W tygodniu wyjdzie kilka tysięcy takich przejść.

**2. Kandydaci na stacje.** Zanim cokolwiek optymalizujemy, wybieramy N miejsc, gdzie stacja w ogóle może stanąć, np. N = 20–30 punktów przy budynkach (D-17, C-2, B-1, A-0, U-2…). To nasza „mapa możliwości”.

**3. Decyzja: linia z k stacji.** Wybieramy **k** kandydatów, np. k = 5, **i ustawiamy ich w kolejności**. Ta kolejność to przebieg linii, a metro jeździ tam i z powrotem po tej trasie:

```
D-17 ── C-2 ── B-1 ── A-0 ── U-2        (k = 5)
```

Wszystko, co robią mrówki, to szukanie najlepszej takiej sekwencji.

## Jak ocenić jedną linię (funkcja celu)

Dla każdego przejścia z popytu liczymy dwa czasy i bierzemy szybszy, bo student nie pojedzie metrem, jeśli pieszo jest szybciej:

```
pieszo  = dojście z A do B
metrem  = dojście z A do najlepszej stacji wejścia
        + kara za wejście (zejście na peron, czekanie)
        + jazda między stacjami (+ postój na każdej stacji po drodze)
        + dojście ze stacji wyjścia do B

czas = min(pieszo, metrem)
```

Wynik linii to **suma czasów wszystkich przejść × liczba osób**. Im mniej, tym lepiej. Porównujemy to z wariantem bez metra, a różnica to zaoszczędzone studento-minuty.

**Przykład z trzema przejściami:**

| Przejście | Osób | Pieszo | Metrem | Wybór |
|---|---|---|---|---|
| D-17 → A-0 | 30 | 14 min | 6 min | metro |
| C-2 → C-3 | 20 | 2 min | 7 min | pieszo |
| U-2 → B-1 | 15 | 11 min | 5 min | metro |

Zysk względem wariantu bez metra: 30·8 + 15·6 = 330 studento-minut. Krótkie przejścia nic nie zyskują, więc stacje opłaca się stawiać tam, gdzie jest dużo **długich** przejść.

## Dlaczego tu potrzebne są mrówki

Możliwych linii jest za dużo, żeby sprawdzić wszystkie. Dla N = 30 kandydatów i k = 6 stacji to około 30·29·28·27·26·25 / 2 ≈ **210 milionów** linii, a każdą trzeba ocenić na tysiącach przejść. Do tego problem jest „nieładny”: dodanie jednej stacji zmienia, które przejścia w ogóle korzystają z metra.

ACO pasuje tu idealnie, bo **buduje rozwiązanie krok po kroku**, tak jak w TSP:

1. Mrówka staje na losowym kandydacie, to pierwsza stacja.
2. Wybiera następną stację z prawdopodobieństwem ∝ τᵢⱼ^α · ηᵢⱼ^β, gdzie:
   - **τᵢⱼ (feromon)** to pamięć kolonii: „w dobrych liniach po stacji i często była stacja j”,
   - **ηᵢⱼ (heurystyka)** to podpowiedź „na oko”, np. ile przejść zaczyna się lub kończy blisko j, podzielone przez odległość i–j.
3. Powtarza krok 2, aż ma k stacji.
4. Każdą zbudowaną linię oceniamy funkcją celu.
5. Feromon paruje (× (1 − ρ)), a najlepsza mrówka wzmacnia krawędzie swojej linii (MMAS, z ograniczeniem τ_min…τ_max, żeby kolonia nie utknęła za wcześnie).
6. Powtarzamy przez kilkaset iteracji. Kolonia stopniowo „zbiega” do dobrej linii.

## Co z tym k

k to **parametr, nie wynik**. Uruchamiacie ACO osobno dla k = 2, 3, …, 10 i rysujecie wykres „zaoszczędzone minuty vs liczba stacji”. Prawdopodobnie wyjdzie krzywa z „kolanem”: pierwsze stacje dają dużo, kolejne coraz mniej, bo:
- popularne pary budynków są już obsłużone,
- każda dodatkowa stacja to postój na trasie (np. +30 s), który spowalnia wszystkich jadących dalej.

To jest bardzo dobry wniosek do sprawozdania: nie tylko „gdzie postawić metro”, ale też **„ile stacji ma sens”**. Postój na stacji koniecznie wrzućcie do modelu czasu. Bez niego więcej stacji zawsze wygrywa i wykres robi się nudny.

## Ważny trik wydajnościowy

Nie liczcie Dijkstry przy każdej ocenie linii. Raz, na początku, policzcie macierz czasów pieszych **budynek ↔ kandydat** (N kandydatów × liczba budynków, kilka sekund z `networkx`). Wtedy ocena linii to czysta arytmetyka na tablicach NumPy: dla każdego przejścia minimum po parach stacji wejście/wyjście. Tysiące ocen na sekundę, więc ACO z 50 mrówkami × 300 iteracji liczy się w kilka sekund. Jazdę metrem między stacjami liczcie po prostej (tunel), to uczciwe uproszczenie.

## Cały projekt w kolejności

1. **USOS** → lista przejść (popyt).
2. **OSM** → graf chodników, budynki 3D, kandydaci na stacje, macierz czasów pieszych.
3. **ACO** → najlepsza linia dla każdego k.
4. **Walidacja** → brute force na małej instancji, porównanie z losowym i zachłannym, wykres zysk vs k, pomiary w terenie.
5. **Wizualizacja** → kampus 3D i animacja studentów bez metra vs z metrem.

Zysk z tak sformułowanego problemu: każdy element ma jasne uzasadnienie i każdy wynik da się zmierzyć.

# Konspekt prezentacji

Dwie prezentacje:

- **Prezentacja 1 (demo, etap pośredni)**: wizualizacja i **jeden przykładowy przebieg**
  algorytmu mrówkowego, z symulacją tygodnia z metrem i bez metra. Mówimy wprost, że to
  przykładowy przebieg, a eksperymenty jeszcze trwają.
- **Prezentacja 2 (końcowa)**: wszystko, czyli eksperymenty, statystyka, optimum dokładne,
  liczba stacji, wrażliwość, symulacja, literatura i wnioski.

Dzięki temu prowadzący widzi postęp: najpierw działający system i pierwszy wynik, potem dowód,
że wynik jest dobry. Lista „czego nie pokazujemy” w prezentacji 1 mówi, co zostaje na drugą.

**Online** (GitHub Pages, po merge do `main`): [etap 1](https://kpustelnik.github.io/natural_ai/etap-1/) (slajdy + kroki demo jako linki do wizualizacji) i [etap 2](https://kpustelnik.github.io/natural_ai/etap-2/) (slajdy, wykresy, dokumentacja). Linki są też na okładkach slajdów, na slajdzie demo i na slajdach końcowych.

**Slajdy** (otwórz w przeglądarce, notatki do mówienia pod każdym slajdem):

- [`docs/prezentacje/prezentacja-1.html`](prezentacje/prezentacja-1.html): etap 1, 23 slajdy;
- [`docs/prezentacje/prezentacja-2.html`](prezentacje/prezentacja-2.html): etap 2, 19 slajdów.

Źródła są w `docs/prezentacje/prezentacja-1/` i `prezentacja-2/` (`deck.json` + jeden plik
HTML na slajd, format Slides z claude.ai; wykresy z `docs/figures/` przez `assets.json`). Po
zmianie źródła albo wykresu: `uv run scripts/build_slides.py`. Edytowalne wersje online
(eksport do PPTX / PDF) są na claude.ai u autora i trzeba je udostępnić z menu Share.

Notatki do mówienia w konspekcie poniżej są pod każdym slajdem (rozwiń). Liczby pochodzą z `docs/figures/*.csv` i
`docs/aco.md`; tam też są odpowiedzi na typowe pytania (§12).

**Przygotowanie viewera** (przed każdą prezentacją):

```bash
uv run scripts/06_export_web.py --campus --aco --metro --sim --showcase --walk   # prawdziwe replaye
cd web && npm run dev                                           # http://localhost:5173/
```

Linki demo poniżej to `http://localhost:5173/` + podany `#…`. `P` włącza tryb prezentacji
(tylko widok), `S` robi zrzut ekranu, `?` pokazuje skróty.

---

<details>
<summary><b>Prezentacja 1: etap 1</b> (dane i pochodzenie każdej liczby, założenia metra, mrówki na dwóch poziomach, demo)</summary>

### Cel tej prezentacji

Pokazać, skąd jest każda liczba i stała (USOS, OpenStreetMap, GTFS, akademiki, dojazdy,
stałe metra ze źródłami), jak zmodyfikowaliśmy algorytm mrówkowy na dwóch poziomach (ruch
pieszy z tłokiem; linia metra MMAS) i czym inspirowaliśmy się w pracach z `references/`,
a potem działający system na przykładowych przebiegach. Wizualizacja w wersji etapu 1:
`#stage=1` (bez wykresów na żywo, zakładki Stats i replayów z etapu 2).

### Czego nie pokazujemy (zostaje na etap 2)

ACS, lokalnego przeszukiwania, metod odniesienia, testów statystycznych, optimum, liczby
stacji, wrażliwości, wykresów z `docs/figures/` poza `walk_aco.png`.

### Slajdy (23; notatki do mówienia pod każdym, z odpowiedziami na pytania)

1. Tytuł · 2. Problem · 3. Skąd mrówki (Goss 1989)
4. Dane: 22 660 studentów, 286 169 przejść, 4 830 par, 55 kandydatów
5. OpenStreetMap → 89 budynków YAML i graf pieszy (5 622 węzły, 6 832 krawędzie)
6. USOS: crawl publicznego USOSweb + anonimowe API, 26/27-Z, 27–28.10.2026; liczebności grup (99,5 % z liczby zapisanych)
7. Ilu studentów (suma kohort, 75. percentyl), akademiki (7 000, Radio Kraków), dojazdy (12 przystanków ∝ miejsca 7–10)
8. Z planu do przejść: tydzień 16–20.11.2026, reguły, 286 169 przejść
9. Czas pieszo i autobusem: stałe i źródła (Weidmann, Fruin, GTFS)
10. Gdzie stacja: szyb pod wejściem, 15 m, schody 33 / 43 s, bez windy
11. Stałe metra i źródła: 10 m/s (studium Kraków), 30 s, 180 s (Warszawa), pojemność nie modelowana
12. Model i funkcja celu (42 521 h bez metra, granica 40,6 %)
13. Mrówki na dwóch poziomach
14. Poziom 1: BPR, FHWA 75 os./min/m, reguła mrówki, Dial, MSA (D'Acierno 2012)
15. Poziom 1: wynik (`walk_aco.png`): 383 → 342 s, równowaga 336 s, α = 0 / 1 / 2
16. Poziom 2: MMAS (wzory, parametry)
17. Modyfikacje względem klasycznego ACO (TSP)
18. Inspiracje: Goss, Korzeń i Kruszyna 2023 / 2025, Stützle i Hoos, D'Acierno
19. Implementacja · 20. Wizualizacja · 21. Demo
22. Przykładowy przebieg: H-D8 – A-0 – C-4 – D-10 – U-9, 11,4 % (cel), 12,9 % (symulacja)
23. Status i plan

### Demo (6–7 min)

Każdy link z `#stage=1&` na początku:

1. `ws=campus` → klik na A-0, Inspector.
2. `ws=network&from=stop:czarnowiejska&to=D-17` → trasa i jej części.
3. `ws=metro&replay=walk-s42&play=1` → poziom 1: kolor = obciążenie / przepustowość; przełączyć Congestion / Pheromone / Shortest path.
4. `ws=metro&replay=aco-showcase-mmas-k5-mmas-k5-s42&play=1` → poziom 2: kolonia, feromon.
5. To samo z `&view=trains` → linia, szyby, tunel, pociągi.
6. `ws=simulation&replay=sim-showcase-mmas-k5-mmas-k5-s42&day=1&t=29700&sc=no_metro&play=1&speed=60` → bez metra.
7. Bez `&sc=no_metro` → z metrem; 8. `&split=1` → obok siebie.

</details>

---

<details>
<summary><b>Prezentacja 2: końcowa</b> (wszystko: eksperymenty, statystyka, optimum, liczba stacji, wrażliwość, symulacja, literatura)</summary>

### Cel tej prezentacji

Na prezentacji 1 był działający system i jeden przykładowy przebieg. Teraz odpowiedzi na
pytania, które wtedy zostawiliśmy otwarte: czy ta linia jest dobra (porównanie metod, optimum
dokładne), ile stacji ma sens, czy wynik zależy od założeń, jak to się ma do literatury.

### Slajdy

<details>
<summary>1. Przypomnienie (1 min)</summary>

- Problem, dane, funkcja celu, MMAS i przykładowa linia k = 5 (11,6 %) w jednym slajdzie.
- „Od ostatniego razu”: ACS, lokalne przeszukiwanie, metody odniesienia, 9 eksperymentów
  walidacyjnych ze statystyką.
</details>

<details>
<summary>2. Nowe algorytmy (1,5 min)</summary>

- ACS (Dorigo, Gambardella 1997): częściej bierze najlepszą stację (q₀ = 0,5), feromon
  „zużywa się” na odcinkach, którymi właśnie przeszły mrówki.
- Lokalne przeszukiwanie: wymiana / zamiana / przestawienie stacji, aż nic nie poprawia.
- Metody odniesienia: losowe, zachłanne, przegląd zupełny.
</details>

<details>
<summary>3. Uczciwe porównanie (1 min)</summary>

- Ten sam budżet: 5 000 **różnych** ocenionych linii; 30 powtórzeń (seedów).
- Testy nieparametryczne (Derrac i in. 2011): Wilcoxon, Mann–Whitney z korektą Holma i
  miara efektu A₁₂ (szansa, że przebieg A jest lepszy od przebiegu B).
</details>

<details>
<summary>4. Porównanie algorytmów (2 min)</summary>

- `compare_algorithms.png`: bez LS MMAS 11,42 %, ACS 11,36 %, zachłanny 11,25 %, losowe 9,68 %;
  z LS wszystkie 11,60 %.
- MMAS > losowe (A₁₂ = 1,00); MMAS vs ACS: różnica nieistotna (p = 0,08).
- k = 10 (`compare_algorithms_hard.png`): MMAS + LS 15,14 %, zachłanny + LS 14,85 %.

Notatki: wniosek wprost: mrówki uczą się struktury problemu, ale o jakości decyduje lokalne
przeszukiwanie; tak samo jak w Stützle i Hoos (2000).
</details>

<details>
<summary>5. Czy to optimum? (2 min)</summary>

- Podinstancje 12 kandydatów (`gap_to_optimum.png`): z LS optimum w 84–94 % przebiegów przy
  3 % budżetu.
- **Cały kampus**, k = 4, sprawdzone wszystkie **4,1 mln linii** (`exact_full.png`): MMAS + LS
  trafia optimum w 10 na 10 przebiegów, mając 0,12 % przestrzeni; zachłanny nigdy.
- Granica dolna „teleportacja”: żadna linia nie da więcej niż 40,6 %.
- Linia z prezentacji 1 (k = 5) to ta, którą znajdują wszystkie metody z LS przy każdym z 30
  seedów.
</details>

<details>
<summary>6. Ile stacji (1,5 min)</summary>

- `k_sweep.png`: 2 → 6,6 %, 5 → 11,6 %, 7 → 13,5 %, 10 → 15,2 %.
- Malejące przyrosty: powyżej 7 stacji każda daje < 0,7 p.p.; rozsądnie 5–7.
</details>

<details>
<summary>7. Zbieżność i parametry (1,5 min)</summary>

- `compare_algorithms_convergence.png`: kolonie przeganiają zachłanny po ~2 000–3 000 liniach.
- `aco_ablation.png`: najważniejsze β (siła heurystyki): β = 1 najlepsze, β = 5 wyraźnie gorsze.
</details>

<details>
<summary>8. Heurystyka: „zmodyfikowane vs klasyczne” (1,5 min)</summary>

- `heuristic.png`: klasyczna heurystyka 1 / odległość (jak w TSP) 10,98 %, gorsza nawet od
  braku heurystyki (11,37 %); nasza 11,43 %, sam popyt 11,52 %.
- Wniosek: dobre linie mają długie przeskoki; podpowiedź „blisko” myli mrówki.

Notatki: to odpowiednik porównania z Korzeń i Kruszyna (2025), u nich wersja zmodyfikowana
dała 11,5 % mniej „wysiłku” niż obecna trasa.
</details>

<details>
<summary>9. Pętla, wrażliwość, tunel (2 min)</summary>

- Pętla zamiast linii: 11,98 % vs 11,60 % (te same stacje), ale tunel 3,85 km zamiast 3,22 km.
- Wrażliwość (`sensitivity.png`): postój, częstotliwość, prędkość zmieniają **ile** linia
  oszczędza (8,4–13,6 %), ale **nie które stacje** wybiera (Jaccard ≥ 0,94).
- Tunel (`tunnel.png`): bez kosztu budowy linia k = 5 „zygzakuje” (3,2 km, więcej niż k = 7).
</details>

<details>
<summary>10. Symulacja tygodnia (2 min)</summary>

- Każde z 286 tys. przejść z prawdziwym rozkładem metra, autobusów i tramwajów.
- **12,5 % mniej czasu, ok. 15 minut na studenta tygodniowo**; spóźnione zajęcia 496 → 452;
  29,0 % przejść metrem. Następny slajd: linia z etapu 1 (te same stacje, inna kolejność) ma
  w symulacji 12,9 %: funkcja celu to przybliżenie (średnie czekanie).
- Na prezentacji 1 była to „przykładowa linia”; teraz wiemy, że jest najlepsza dla k = 5 i że
  nie zależy od założeń o pociągach. Demo: zakładka Stats (widok obok siebie był na
  prezentacji 1).
</details>

<details>
<summary>11. Na tle literatury (1 min)</summary>

| | Korzeń, Kruszyna 2023 / 2025 | my |
|---|---|---|
| co przeszukujemy | 5 gotowych wariantów / jedna linia | cała przestrzeń, 2·10⁸ linii |
| popyt | liczba mieszkańców | 286 tys. przejść z USOS |
| sprawdzenie | ranking / vs obecna trasa | przegląd zupełny, 4 metody, testy, symulacja |
</details>

<details>
<summary>12. Wnioski i ograniczenia (1,5 min)</summary>

- Linia H-D8 – C-4 – U-9 – D-10 – A-0: ok. 12 %, 15 min na studenta tygodniowo; sensownie
  5–7 stacji; pętla nieco lepsza.
- Algorytm: MMAS + lokalne przeszukiwanie niezawodnie znajduje optimum.
- Ograniczenia: populacja syntetyczna, jeden tydzień, brak tłoku i kosztu budowy, czasy dojść
  niezweryfikowane w terenie.
</details>

### Demo (2–3 min)

1. `#ws=simulation&replay=sim-mmas-k5-s42&day=1&tab=stats` → zakładka Stats: oszczędność na
   godzinę, wykorzystanie stacji, największe oszczędności; klik w parę → trasa w 3D.
2. `#ws=simulation&replay=sim-mmas-k5-s42&day=1&t=29700&split=1&play=1&speed=60` → krótko
   poranny szczyt obok siebie, jako przypomnienie.

</details>

---

## Na wypadek problemów z demo

Nagrać wcześniej krótkie filmy (systemowym nagrywaniem ekranu): replay ACO, poranny szczyt bez
metra, z metrem i obok siebie, i wstawić je do slajdów zamiast demo na żywo.

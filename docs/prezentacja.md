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

- [`docs/prezentacje/prezentacja-1.html`](prezentacje/prezentacja-1.html): demo, 10 slajdów;
- [`docs/prezentacje/prezentacja-2.html`](prezentacje/prezentacja-2.html): końcowa, 18 slajdów.

Źródła są w `docs/prezentacje/prezentacja-1/` i `prezentacja-2/` (`deck.json` + jeden plik
HTML na slajd, format Slides z claude.ai; wykresy z `docs/figures/` przez `assets.json`). Po
zmianie źródła albo wykresu: `uv run scripts/build_slides.py`. Edytowalne wersje online
(eksport do PPTX / PDF) są na claude.ai u autora i trzeba je udostępnić z menu Share.

Notatki do mówienia w konspekcie poniżej są pod każdym slajdem (rozwiń). Liczby pochodzą z `docs/figures/*.csv` i
`docs/aco.md`; tam też są odpowiedzi na typowe pytania (§12).

**Przygotowanie viewera** (przed każdą prezentacją):

```bash
uv run scripts/06_export_web.py --campus --aco --metro --sim   # prawdziwe replaye
cd web && npm run dev                                           # http://localhost:5173/
```

Linki demo poniżej to `http://localhost:5173/` + podany `#…`. `P` włącza tryb prezentacji
(tylko widok), `S` robi zrzut ekranu, `?` pokazuje skróty.

---

<details>
<summary><b>Prezentacja 1: demo</b> (wizualizacja i przykładowy przebieg mrówek, z metrem i bez metra)</summary>

### Cel tej prezentacji

Pokazać działający system: prawdziwe dane, model kampusu, algorytm mrówkowy i wizualizację na
**jednym przykładowym przebiegu** (MMAS, k = 5, seed 42) oraz symulację tygodnia z tą linią i
bez niej. Główna część to demo w viewerze (ok. 6 min). Na koniec status: co działa, jakie
eksperymenty trwają.

### Czego nie pokazujemy (zostaje na prezentację 2)

- żadnych wykresów z eksperymentów: `k_sweep`, `compare_algorithms*`, `gap_to_optimum`,
  `exact_full`, zbieżność, `aco_ablation`, `heuristic`, `topology`, `sensitivity`, `tunnel`;
- ACS, lokalnego przeszukiwania, metod odniesienia (losowe, zachłanne, przegląd zupełny) i
  testów statystycznych;
- odpowiedzi na „czy to optimum?”, „ile stacji ma sens?”, „czy wynik zależy od założeń?”:
  stawiamy je na koniec jako plan;
- porównania z pracami Korzenia i Kruszyny.

Wynik przebiegu podajemy jako **przykład**, bez twierdzenia, że jest najlepszy.

### Slajdy

<details>
<summary>1. Tytuł (0,5 min)</summary>

„Metro na kampusie AGH: projekt linii algorytmem mrówkowym”, skład zespołu, przedmiot.
</details>

<details>
<summary>2. Problem (1,5 min)</summary>

- Kampus AGH: ok. 90 budynków, 15 minut przerwy między zajęciami w różnych budynkach.
- Pytanie: **gdzie postawić linię metra z k stacjami, żeby łączny czas przejść studentów był
  najmniejszy, i ile stacji ma sens?**
- Rysunek: mapa kampusu (zrzut z viewera, zakładka Campus).

Notatki: przykład z MAIN_IDEA: 30 osób D-17 → A-0 idzie 14 min, metrem 6 → oszczędzają po
8 min; krótkie przejścia nic nie zyskują, więc stacje opłaca się stawiać przy długich.
</details>

<details>
<summary>3. Skąd mrówki (1 min)</summary>

- Goss i in. (1989): mrówki argentyńskie na mostku z dwiema gałęziami wybierają krótszą,
  choć żadna nie porównuje długości: feromon na krótszej gałęzi przybywa szybciej.
- Rysunek: schemat mostka (z artykułu, z podpisem źródła).
</details>

<details>
<summary>4. Dane i model (2 min)</summary>

- USOS: plan zajęć → syntetyczna populacja **22 tys. studentów**, **286 tys. przejść
  tygodniowo**; OpenStreetMap: graf pieszy; GTFS: autobusy i tramwaje.
- 55 kandydatów na stacje (szyb pod wejściem budynku).
- Czas metrem = dojście + szyb + czekanie + jazda (10 m/s, 30 s postoju) + szyb + dojście;
  student wybiera szybsze: pieszo / autobus albo metro. Cel: suma czasów wszystkich przejść.

Notatki: ok. 2·10⁸ możliwych linii przy k = 5, dlatego potrzebny jest algorytm przybliżony;
nie mamy danych osobowych, studenci są syntetyczni, ale ich plany wynikają z grup USOS.
</details>

<details>
<summary>5. Jak mrówki budują linię (1,5 min)</summary>

- MAX-MIN Ant System: mrówka wybiera kolejne stacje z prawdopodobieństwem ∝ feromon^α ·
  podpowiedź^β; lepsza linia zostawia więcej feromonu, feromon paruje i jest ograniczony z
  dołu i z góry, żeby kolonia nie utknęła na pierwszym wyborze.
- Zaraz zobaczymy to na żywo w viewerze.
</details>

<details>
<summary>6. Wizualizacja (1 min, przed demo)</summary>

- Python liczy wszystko (dane, graf, optymalizacja, symulacja), przeglądarka tylko odtwarza
  gotowe pliki (React + three.js).
- Zakładki: kampus 3D, graf pieszy i trasy, metro z przebiegiem mrówek, symulacja tygodnia
  (ok. 20 tys. studentów).
</details>

<details>
<summary>7. Demo (6 min)</summary>

Scenariusz poniżej („Demo”).
</details>

<details>
<summary>8. Przykładowy przebieg: wynik (1 min)</summary>

- MMAS, k = 5, jeden przebieg: linia **H-D8 – C-4 – U-9 – D-10 – A-0**.
- Funkcja celu: **11,6 % mniej** czasu przejść; symulacja tygodnia z prawdziwym rozkładem:
  **12,5 % mniej**, ok. 15 min na studenta tygodniowo, 28,8 % przejść metrem.

Notatki: podkreślić „przykładowy przebieg”; jeszcze nie wiemy, czy to najlepsza linia ani ile
stacji ma sens.
</details>

<details>
<summary>9. Status i plan (1 min)</summary>

- Działa: dane, model kampusu, MMAS, symulacja tygodnia, wizualizacja.
- W toku (na prezentację 2): drugi algorytm (ACS) i lokalne przeszukiwanie; porównanie z
  metodami odniesienia przy równym budżecie i testami statystycznymi; czy to optimum (przegląd
  zupełny); ile stacji ma sens; wrażliwość na założenia; porównanie z literaturą.
</details>

### Demo (6 min)

1. `#ws=campus` → obrót kampusu, klik na A-0, Inspector.
2. `#ws=network&from=stop:czarnowiejska&to=D-17` → trasa z przystanku, z czasem i częściami
   (na zewnątrz, w budynku, schody).
3. `#ws=metro&replay=aco-mmas-k5-s42&play=1` → kolonia: mrówki, feromon się koncentruje,
   najlepsza linia rośnie.
4. `#ws=metro&replay=aco-mmas-k5-s42&view=trains` → linia, szyby, tunel, pociągi.
5. `#ws=simulation&replay=sim-mmas-k5-s42&day=1&t=29700&sc=no_metro&play=1&speed=60` →
   poranny szczyt (8:15) **bez metra**.
6. Ten sam link bez `&sc=no_metro` → **z metrem** (studenci: idą / czekają / jadą).
7. Dodać `&split=1` → bez metra i z metrem obok siebie; zostawić na chwilę.

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
- **12,5 % mniej czasu, ok. 15 minut na studenta tygodniowo**; spóźnione zajęcia 503 → 450;
  28,8 % przejść metrem.
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

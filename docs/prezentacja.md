# Konspekt prezentacji

Dwie prezentacje: **etap pośredni** (problem, dane, model, pierwszy wynik MMAS) i **etap
końcowy** (pełna walidacja, symulacja, porównanie z literaturą). Na pierwszej świadomie nie
pokazujemy wszystkiego, żeby było widać postęp między nimi; lista w sekcji „czego nie
pokazujemy” mówi, co zostaje na drugą.

Każda prezentacja: ok. 12–15 min + demo 3–4 min + pytania. Notatki do mówienia są pod każdym
slajdem (rozwiń). Wszystkie liczby pochodzą z `docs/figures/*.csv` i `docs/aco.md`; tam też są
odpowiedzi na typowe pytania (§12).

**Przygotowanie viewera** (przed każdą prezentacją):

```bash
uv run scripts/06_export_web.py --campus --aco --metro --sim   # prawdziwe replaye
cd web && npm run dev                                           # http://localhost:5173/
```

Linki demo poniżej to `http://localhost:5173/` + podany `#…`. `P` włącza tryb prezentacji
(tylko widok), `S` robi zrzut ekranu, `?` pokazuje skróty.

---

<details>
<summary><b>Prezentacja 1: etap pośredni</b> (problem, dane, model, MMAS, pierwszy wynik)</summary>

### Cel tej prezentacji

Pokazać, że problem jest dobrze postawiony, dane są prawdziwe, model działa, a algorytm
mrówkowy daje sensowną linię. Zakończyć planem na etap końcowy.

### Czego nie pokazujemy (zostaje na prezentację 2)

- ACS i lokalne przeszukiwanie, porównanie wszystkich algorytmów z testami statystycznymi
  (`compare_algorithms*.png`);
- optimum dokładne (`gap_to_optimum.png`, `exact_full.png`), zbieżność, ablacja parametrów;
- heurystyka, pętla, wrażliwość, długość tunelu (`heuristic`, `topology`, `sensitivity`,
  `tunnel`);
- symulacja tygodnia (15 min na studenta, spóźnienia, widok obok siebie w viewerze);
- porównanie z pracami Korzenia i Kruszyny.

W viewerze nie otwieramy replayu `sim-mmas-k5-s42` ani zakładki Simulation.

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
<summary>3. Skąd mrówki (1,5 min)</summary>

- Goss i in. (1989): mrówki argentyńskie na mostku z dwiema gałęziami wybierają krótszą,
  choć żadna nie porównuje długości: feromon na krótszej gałęzi przybywa szybciej.
- Algorytm mrówkowy: wiele prostych agentów + wspólna pamięć (feromon) = dobre rozwiązanie
  problemu kombinatorycznego.
- Rysunek: schemat mostka (z artykułu, rys. 1, z podpisem źródła).

Notatki: bez parowania kolonia nie przełącza się na krótszą gałąź dodaną później (2 z 18
kolonii); dlatego algorytm ma parowanie feromonu, wrócimy do tego przy MMAS.
</details>

<details>
<summary>4. Dane (2 min)</summary>

- USOS: plan zajęć, grupy, kohorty → syntetyczna populacja **22 tys. studentów**.
- Popyt: **286 tys. przejść tygodniowo**, 4 830 różnych par budynków / przystanków.
- OpenStreetMap: graf pieszy kampusu; GTFS: autobusy i tramwaje (alternatywa dla metra).
- Rysunek: viewer, zakładka Network, kolorowanie po obciążeniu (Demand).

Notatki: nie mamy danych osobowych; studenci są syntetyczni, ale ich plany wynikają z
prawdziwych grup i sal z USOS.
</details>

<details>
<summary>5. Model i funkcja celu (2 min)</summary>

- 55 kandydatów na stacje: szyb pod głównym wejściem każdego budynku.
- Czas przejścia metrem = dojście + szyb + czekanie (90 s) + jazda (10 m/s, 30 s postoju na
  stacji) + szyb + dojście.
- Student wybiera **szybsze**: pieszo / autobus albo metro.
- Cel: suma czasów wszystkich przejść w tygodniu (bez metra: 42,5 tys. studento-godzin).

Notatki: wzór jest w `docs/aco.md` §2; powiedzieć, że ocena jednej linii to sama arytmetyka
na macierzach czasów dojść (ułamek milisekundy).
</details>

<details>
<summary>6. Dlaczego to trudne (1 min)</summary>

- Linia = uporządkowany wybór k z 55: przy k = 5 to **ok. 2·10⁸ linii**, przy k = 10 ok. 5·10¹⁶.
- Wartość odcinka zależy od całej linii (nowa stacja zmienia, kto w ogóle jedzie metrem), więc
  to nie jest najkrótsza ścieżka ani TSP.
</details>

<details>
<summary>7. MAX-MIN Ant System (2 min)</summary>

- Mrówka buduje linię stacja po stacji: następna z prawdopodobieństwem ∝ τ^α · η^β
  (τ feromon, η popyt w pobliżu / odległość).
- Lepsza linia zostawia więcej feromonu; feromon paruje; MMAS ogranicza go do [τ_min, τ_max],
  żeby kolonia nie utknęła na pierwszym wyborze (to „mostek” z poprzedniego slajdu).
- Rysunek: demo ACO w viewerze (albo nagranie), feromon koncentruje się z iteracjami.
</details>

<details>
<summary>8. Pierwszy wynik (1,5 min)</summary>

- Najlepsza linia k = 5: **H-D8 – C-4 – U-9 – D-10 – A-0**, **11,6 % mniej** czasu przejść
  (ok. 4 900 studento-godzin tygodniowo).
- MMAS vs losowe przeszukiwanie przy tym samym budżecie (5 000 linii): 11,4 % vs 9,7 %.
- Rysunek: zrzut viewera, zakładka Metro (linia, szyby, tunel).

Notatki: nie wspominać jeszcze o ACS ani o lokalnym przeszukiwaniu.
</details>

<details>
<summary>9. Ile stacji (1,5 min)</summary>

- `k_sweep.png`: 2 → 6,6 %, 5 → 11,6 %, 7 → 13,5 %, 10 → 15,2 %.
- Malejące przyrosty: powyżej 7 stacji każda daje < 0,7 p.p.; rozsądnie 5–7.
</details>

<details>
<summary>10. Plan na etap końcowy (1 min)</summary>

- Drugi algorytm mrówkowy (ACS) i lokalne przeszukiwanie.
- Uczciwe porównanie: równy budżet, 30 powtórzeń, testy statystyczne.
- Czy to optimum? Sprawdzenie przeglądem zupełnym tam, gdzie się da.
- Symulacja całego tygodnia z prawdziwym rozkładem jazdy.
- Wrażliwość wyniku na założenia; porównanie z literaturą.
</details>

### Demo (3 min)

1. `#ws=campus` → obrót kampusu, klik na A-0, Inspector.
2. `#ws=network&from=stop:czarnowiejska&to=D-17` → trasa z przystanku z czasem i częściami.
3. `#ws=metro&replay=aco-mmas-k5-s42&play=1` → kolonia: mrówki, feromon, najlepsza linia.
4. `#ws=metro&replay=aco-mmas-k5-s42&view=trains` → linia, szyby, pociągi.

</details>

---

<details>
<summary><b>Prezentacja 2: etap końcowy</b> (walidacja, symulacja, literatura, wnioski)</summary>

### Cel tej prezentacji

Pokazać, co doszło od etapu pośredniego, i udowodnić, że wynik jest dobry: porównanie metod,
optimum dokładne, wrażliwość, symulacja tygodnia, odniesienie do literatury.

### Slajdy

<details>
<summary>1. Przypomnienie (1 min)</summary>

- Problem, dane, funkcja celu, MMAS i linia k = 5 (11,6 %) w jednym slajdzie.
- „Od ostatniego razu”: ACS, lokalne przeszukiwanie, 9 eksperymentów walidacyjnych,
  symulacja tygodnia.
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
</details>

<details>
<summary>6. Zbieżność i parametry (1,5 min)</summary>

- `compare_algorithms_convergence.png`: kolonie przeganiają zachłanny po ~2 000–3 000 liniach.
- `aco_ablation.png`: najważniejsze β (siła heurystyki): β = 1 najlepsze, β = 5 wyraźnie gorsze.
</details>

<details>
<summary>7. Heurystyka: „zmodyfikowane vs klasyczne” (1,5 min)</summary>

- `heuristic.png`: klasyczna heurystyka 1 / odległość (jak w TSP) 10,98 %, gorsza nawet od
  braku heurystyki (11,37 %); nasza 11,43 %, sam popyt 11,52 %.
- Wniosek: dobre linie mają długie przeskoki; podpowiedź „blisko” myli mrówki.

Notatki: to odpowiednik porównania z Korzeń i Kruszyna (2025), u nich wersja zmodyfikowana
dała 11,5 % mniej „wysiłku” niż obecna trasa.
</details>

<details>
<summary>8. Pętla, wrażliwość, tunel (2 min)</summary>

- Pętla zamiast linii: 11,98 % vs 11,60 % (te same stacje), ale tunel 3,85 km zamiast 3,22 km.
- Wrażliwość (`sensitivity.png`): postój, częstotliwość, prędkość zmieniają **ile** linia
  oszczędza (8,4–13,6 %), ale **nie które stacje** wybiera (Jaccard ≥ 0,94).
- Tunel (`tunnel.png`): bez kosztu budowy linia k = 5 „zygzakuje” (3,2 km, więcej niż k = 7).
</details>

<details>
<summary>9. Symulacja tygodnia (2 min)</summary>

- Każde z 286 tys. przejść z prawdziwym rozkładem metra, autobusów i tramwajów.
- **12,5 % mniej czasu, ok. 15 minut na studenta tygodniowo**; spóźnione zajęcia 503 → 450;
  28,8 % przejść metrem.
- Demo: widok obok siebie bez metra / z metrem w porannym szczycie.
</details>

<details>
<summary>10. Na tle literatury (1 min)</summary>

| | Korzeń, Kruszyna 2023 / 2025 | my |
|---|---|---|
| co przeszukujemy | 5 gotowych wariantów / jedna linia | cała przestrzeń, 2·10⁸ linii |
| popyt | liczba mieszkańców | 286 tys. przejść z USOS |
| sprawdzenie | ranking / vs obecna trasa | przegląd zupełny, 4 metody, testy, symulacja |
</details>

<details>
<summary>11. Wnioski i ograniczenia (1,5 min)</summary>

- Linia H-D8 – C-4 – U-9 – D-10 – A-0: ok. 12 %, 15 min na studenta tygodniowo; sensownie
  5–7 stacji; pętla nieco lepsza.
- Algorytm: MMAS + lokalne przeszukiwanie niezawodnie znajduje optimum.
- Ograniczenia: populacja syntetyczna, jeden tydzień, brak tłoku i kosztu budowy, czasy dojść
  niezweryfikowane w terenie.
</details>

### Demo (4 min)

1. `#ws=metro&replay=aco-mmas-k5-s42&play=1` → kolonia zbiega (przypomnienie z etapu 1).
2. `#ws=simulation&replay=sim-mmas-k5-s42&day=1&t=29700&play=1&speed=60` → poranny szczyt
   (8:15), studenci: idą / czekają / jadą.
3. Dodać `&split=1` → bez metra / z metrem obok siebie.
4. `#ws=simulation&replay=sim-mmas-k5-s42&day=1&tab=stats` → zakładka Stats: oszczędność na
   godzinę, stacje, największe oszczędności; klik w parę → trasa w 3D.

</details>

---

## Na wypadek problemów z demo

Nagrać wcześniej dwa krótkie filmy (systemowym nagrywaniem ekranu): replay ACO i poranny
szczyt w widoku obok siebie, i wstawić je do slajdów zamiast demo na żywo.

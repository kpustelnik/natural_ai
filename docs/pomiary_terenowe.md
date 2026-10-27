# Pomiary terenowe (walidacja 5)

Cel: sprawdzić, czy czasy przejść z grafu (chodniki OSM + wnętrza + schody) zgadzają się z
rzeczywistością. Wynik: MAE, średni błąd (czy model jest za szybki / za wolny) i MAPE z
`uv run scripts/validate_field.py`.

## Jak mierzyć

- Start i meta: **główne wejście** budynku (tam w grafie jest punkt budynku), przystanek:
  słupek przystanku. Stoper od przekroczenia drzwi do przekroczenia drzwi.
- Zwykłe tempo, bez biegu; trasa, którą naprawdę się chodzi (zapisać w `notes`, jeśli inna
  niż oczywista, np. „przez halę”, „dookoła ogrodzenia”).
- Każdą trasę **2 razy** (najlepiej dwie osoby lub dwa dni), także **w obie strony**, jeśli
  po drodze są schody lub wzniesienie (model ma inne czasy w górę i w dół).
- Godziny poza przerwami (bez tłumu) i notatka, jeśli był tłok, światła, deszcz.
- Wiersz do `data/validation/field_measurements.csv`:

```
route_id,from_key,to_key,measured_s,date,who,notes
r01,D-14A,D-14,95,2026-11-03,kp,
```

## Trasy (najczęstsze przejścia wg popytu z USOS, różne typy)

| route_id | z | do | czemu ta |
|---|---|---|---|
| r01 | D-14A | D-14 | najczęstsza para na kampusie (~2000 przejść / tydzień), sąsiednie budynki |
| r02 | B-2 | D-1 | przez ulicę, średni dystans |
| r03 | A-1 | A-4 | wnętrze kwartału A |
| r04 | C-7 | stop:plac_inwalidow | do przystanku, długa prosta |
| r05 | D-10 | stop:agh_ur | do przystanku, przez kampus |
| r06 | stop:plac_inwalidow | H-D8 | z przystanku do akademika / hali |
| r07 | C-6 | D-4 | przekątna kampusu |
| r08 | B-4 | B-5 | sąsiedzi, krótko (sprawdza stały narzut: drzwi, schody) |
| r09 | C-2 | C-3 | sąsiedzi w kwartale C |
| r10 | D-17 | A-0 | najdłuższa: przez cały kampus |

Po zebraniu: `uv run scripts/validate_field.py` zapisuje `docs/figures/field_validation.png`
i `.csv`. Systematyczny błąd (bias) można skorygować prędkością w `config.yaml`
(`time_model.walk_speed_mps`) i przebudować etapy 02-05.

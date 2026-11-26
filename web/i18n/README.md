# Polish catalogue

`pl.json` maps each English source string (exact, as the code or the data file writes it) to its Polish text. The browser (`web/js/i18n.js`) and the atlas builder (`pipeline/build/seo.py`) read it. `uv run python scripts/i18n-extract.py` lists the strings that have no Polish entry; `uv run python -m pipeline check` fails while any is missing.

## Glossary (binding)

Use these words every time. Write them in the case the sentence needs.

### Game words

| English | Polish | Notes |
|---|---|---|
| Yields (heading) | Zasoby miast | In running text: "zasoby" |
| Food | Żywność | |
| Production | Produkcja | |
| Gold | Złoto | |
| Science | Nauka | |
| Culture | Kultura | |
| Lens, lenses | Warstwa, Warstwy | "Wybierz warstwę" |
| Map menu, the map | Mapa | |
| City View | Widok miasta | |
| Advisors | Doradcy | The council: "Rada" |
| Almanac | Almanach | |
| Explorer | Kartograf | |
| Wonders, heritage | Dziedzictwo i obiekty wyjątkowe | One item: "obiekt wyjątkowy" |
| Memorial | Miejsce pamięci | Never game language for a memorial |
| Turn | Tura | "Tura 2026" |
| Resources (on tiles) | Surowce | Energy and mineral sites |
| Badge | Wyróżnik | A town's badge |
| District | Dzielnica | City View districts |
| Citizens | Mieszkańcy | City View tab |
| Share (button) | Udostępnij | |
| Search | Szukaj | |
| Text version | Wersja tekstowa | |
| Garrison | Garnizon | |
| Training area | Poligon | |

### Units and places

| English | Polish |
|---|---|
| gmina, gminas | gmina, gminy (gen. pl. gmin) |
| powiat, powiats | powiat, powiaty (gen. pl. powiatów) |
| voivodeship, voivodeships | województwo, województwa (gen. pl. województw) |
| city with powiat rights | miasto na prawach powiatu |
| town, towns | miasto, miasta |
| metro area (FUA) | miejski obszar funkcjonalny |
| Poland | Polska |
| złoty, PLN | zł |
| residents, people | mieszkańcy, osoby |

Voivodeship names stay as the data writes them ("Małopolskie"). In a sentence, decline the adjective: "w województwie małopolskim", "województwa małopolskiego".

### Advisors

| Name | Role (Polish) | Area |
|---|---|---|
| Podskarbi | Podskarbi koronny | Gospodarka |
| Ochmistrz | Ochmistrz | Dobrobyt i mieszkania |
| Kupiec gdański (EN "Gdańsk Merchant") | Kupiec gdański | Handel |
| Żupnik | Żupnik krakowski | Energia i surowce |
| Lustrator | Lustrator | Ludność |
| Rektor | Rektor Akademii | Wiedza |
| Kustosz | Kustosz | Kultura |
| Geometra | Geometra przysięgły | Ziemia |
| Hetman | Hetman wielki koronny | Wojsko |
| Kartograf | Kartograf | Eksplorator danych |

### Statistics (GUS names)

| English | Polish |
|---|---|
| Registered unemployment rate | Stopa bezrobocia rejestrowanego |
| Average gross monthly wage | Przeciętne miesięczne wynagrodzenie brutto |
| Population (on 30 June 2026) | Ludność (według stanu w dniu 30 czerwca 2026 r.); heading: "Ludność" |
| Net migration per 1,000 residents | Saldo migracji na 1000 ludności |
| Natural increase | Przyrost naturalny |
| Median age | Mediana wieku |
| PIT revenue per resident | Dochody z PIT na mieszkańca |
| Dwellings completed per 1,000 residents | Mieszkania oddane do użytkowania na 1000 ludności |
| Overnight stays per resident | Udzielone noclegi na 1 mieszkańca |
| Mass attendance (dominicantes) | Dominicantes (odsetek wiernych na niedzielnej mszy) |
| Life expectancy | Przeciętne dalsze trwanie życia (short: "Długość życia") |
| GDP | PKB |
| Gross value added | Wartość dodana brutto |
| Employed persons | Pracujący |
| PKD section | sekcja PKD |
| Location quotient | Wskaźnik lokalizacji |
| Census 2021 (NSP 2021) | NSP 2021 (Narodowy Spis Powszechny 2021) |
| Statistics Poland (GUS) | Główny Urząd Statystyczny (GUS) |
| National Electoral Commission (PKW) | Państwowa Komisja Wyborcza (PKW) |
| Ministry of Finance | Ministerstwo Finansów |
| Energy Regulatory Office (URE) | Urząd Regulacji Energetyki (URE) |

Election lenses stay neutral. Candidate and committee names are written as on the PKW ballot.

## Style

- Write natural Polish, as a careful editor would: correct cases after numbers and prepositions, natural word order, no calques, no filler.
- Numbers: decimal comma, a no-break space between thousands from 10 000 up (the code formats numbers; do not write them by hand in a key with `{n}`).
- Short scales: tys., mln, mld, bln. Money: "3,92 bln zł".
- Dates: "30 czerwca 2026" (genitive month); a month alone: "październik 2026". ISO dates in a text ("2026-06-30") are formatted by the code: keep them as ISO in the Polish text, or write the date in words when the sentence needs another case ("od maja 2026 r.").
- Plurals: `t.plural(n, {one, other})` in the code; the catalogue entry under the English "other" form holds `{"one", "few", "many"}` ("1 miasto", "2 miasta", "5 miast"), plus "other" for fractions when it differs from "few".
- Keep every `{placeholder}` of the key. Do not add HTML.
- Buttons and labels fit their slot: prefer the short word.
- Sentence case in headings and buttons ("Widok miasta", not "Widok Miasta").
- Proper names (towns, units, companies, source titles in Polish) stay as they are.

# Motion layer sources: trains and flights

## Conclusions

- `pl_rail_gtfs` gives `web/data/trains.json`: 7,366 train runs on Wednesday 2026-12-16 (7,228 that start that day plus 138 night trains from the evening before), 13 operators, 2,964 stations, 2,043 route lines. File size 2.95 MB (0.71 MB gzip), under the 4 MB target, so no split by operator.
- The timetable is the PKP PLK timetable converted to GTFS by Mikołaj Kuranowski. PKP PLK and Koleje Mazowieckie allow re-use, commercial or not, with attribution. The page must name PKP PLK, Koleje Mazowieckie and Mikołaj Kuranowski, the data date, and that the data was processed. The Almanac page "Moving layers" shows all three: the names, the feed creation and download times (UTC), and a sentence on the processing (`trains.json` `attribution`).
- `pl_air_routes` gives `web/data/flights.json`: 446 airport pairs from 12 Polish airports to 138 foreign airports, monthly passengers 2024-01 to 2024-12. File size 0.11 MB.
- The newest Eurostat month is still 2024-12 (data update 2025-10-22). ULC has 2025 figures, but only in PDF tables per foreign city, without the Polish airport. Eurostat stays the source.

## Critical learnings

- Night trains belong to the service day they leave on. A train that leaves Tuesday 18:35 and arrives Wednesday 08:48 is in the GTFS as Tuesday with times up to 32:48. `pl_rail_gtfs` adds Tuesday runs that pass midnight with their times shifted by -24 h, so the Wednesday clock shows them in the morning.
- The GTFS gives times to the half minute (`05:49:30`); PKP Intercity posters round down to the minute (5:49).
- The day changes the trip mix: Wednesdays before the 2026-12-13 timetable change have about 6,800 trains and 643 replacement buses; 2026-12-16 has 7,228 trains and 345 buses. The rule picks the Wednesday with the most trains outside holidays, so the new timetable wins.
- Train names: `plk_train_name` is sometimes an IC line code (`EX03` for the Warszawa-Kraków EIP trains) or a number. Those give `name: null`.
- The GTFS has stations abroad on international lines (Berlin, Wien, Praha, Budapest, Vilnius). 52 stations lie beyond the map edge; their lines are kept so trains leave the map at the right place.
- Wikidata Query Service limits anonymous clients to 1 request per minute (rule active 2026-11-27). `pl_air_routes` retries HTTP 429 after 65, 130 and 195 s.
- Airport names: OurAirports `municipality` is often the village of the airport (Ferno for Milan Malpensa, Gaziemir for Izmir), and Eurostat labels are capitals with local spellings. Wikidata airport labels by ICAO code give short English and Polish names ("London Heathrow" / "Londyn-Heathrow"). Wikidata still links EDDB to the closed Berlin Schönefeld airport, so `LABEL_FIX` names it Berlin Brandenburg, as Eurostat does. The served place (P931) is sometimes a region ("Greater Manchester", "Lombardy").
- Eurostat and gov.pl hosts need `SSL_CERT_FILE` with the macOS system roots on the build machine.

## Sources

| id | Publisher | Dataset | URL | Vintage | Licence | Level | Fields | Caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_rail_gtfs` | PKP PLK (timetable), Koleje Mazowieckie, GTFS by Mikołaj Kuranowski | Polish Trains GTFS (all operators on the PKP PLK network) | https://mkuran.pl/gtfs/polish_trains.zip | feed 2026-11-27, valid 2026-11-27 to 2026-12-27; day 2026-12-16 | PKP PLK and Koleje Mazowieckie public sector information re-use terms | trip, station | operator, category, number, name, stops, arrival and departure times, distance along the line, route line | Third-party converter run by one person; 1,767 of 29,771 trips in the 30 days are replacement buses (left out) |
| `pl_air_routes` | Eurostat; OurAirports; Wikidata | `avia_par_pl` passengers carried (PAS_CRD) per airport pair, monthly; airport positions; airport names and served place | https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/avia_par_pl ; https://davidmegginson.github.io/ourairports-data/airports.csv ; https://query.wikidata.org/sparql | 2024-01 to 2024-12 (Eurostat update 2025-10-22); OurAirports 2026-11-27 | Eurostat CC BY 4.0; OurAirports Unlicense (public domain); Wikidata CC0 | airport pair, month | passengers per month, partner airport, country, coordinates | Main partner airports only; domestic pairs appear once from each end; 23 months behind the run date |

### Licences (text read 2026-11-27)

- mkuran.pl/gtfs: "All feeds come with no major restrictions, but some of them require you to put an attribution." Polish Trains licences: "PKP PLK public sector data usage terms (Polish)" (https://bip.plk-sa.pl/ponowne-wykorzystywanie) and "Koleje Mazowieckie public sector data usage terms (Polish)".
- PKP PLK: re-use "w celach komercyjnych lub niekomercyjnych". Conditions: "zobowiązane do podania dokładnego źródła, czasu wytworzenia i pozyskania informacji oraz poinformowania PKP Polskie Linie Kolejowe S.A. o przetworzeniu informacji ponownie wykorzystywanej."
- Koleje Mazowieckie: users must state "o źródle, czasie wytworzenia i pozyskania informacji", pass the information on in its original form to other users, and inform "o przetworzeniu informacji sektora publicznego".
- `attributions.txt` in the feed: "Data: Koleje Mazowieckie - KM sp. z o.o. (2026-11-27 02:45:21)", "GTFS: Mikołaj Kuranowski", "Data: PKP Polskie linie Kolejowe S.A.". `trains.json` carries these lines in `attribution`.
- OurAirports data repository: The Unlicense (GitHub licence field). Eurostat: CC BY 4.0 under Decision 2011/833/EU.

### Spot checks against the publisher

- PKP Intercity departure poster, Włoszczowa Północ, valid 2026-10-25 to 2026-12-12 (intercity.pl, "zestawienia pociągów"), against the GTFS for 2026-12-02 and 2026-12-03:
  - TLK 31102/3 Marszałek Piłsudski: poster 5:49, GTFS 05:49:30.
  - IC 3820/1 Barbakan: poster 6:34, GTFS 06:34:00.
  - IC 142 Hańcza: poster 6:49, "w dniach 25 X - 04 XI, 03-12 XII 2026 odjazd o godzinie 7:16"; GTFS 06:49:30 on 2026-12-02 and 07:16:00 on 2026-12-03.
  - IC 406 Chopin (night train from Praha and Budapest): poster 6:41; GTFS 30:41:00 on the previous service day.
  - IC 116 Silesia 6:57 and IC 103 Polonia 7:13 match.
- In `trains.json` (2026-12-16, new timetable): EIP 1300/1 leaves Warszawa Wschodnia 06:33, Warszawa Centralna 06:44, arrives Kraków Główny 09:02. IC 13100/1 Malinowski leaves Warszawa Centralna 05:20, arrives Kraków Główny 07:54. PKP Intercity had not published posters for the 2026-12-13 timetable on 2026-11-27 (the URLs answer 403), so these two cannot be checked yet.
- Eurostat 2024 pairs match the earlier research: Warszawa-Antalya 657,567; Katowice-Antalya 643,042; Warszawa-Amsterdam 599,357; Warszawa-London Heathrow 579,372.

## Refresh

| Source | Cadence | Why |
|---|---|---|
| `pl_rail_gtfs` | monthly | The feed covers a rolling 30 days. A monthly run keeps one current Wednesday. |
| `pl_air_routes` | quarterly | Eurostat adds a quarter at a time, with a long delay. |

## Looked for, not used

- PKP PLK open data API (`pdp-api.plk-sa.pl`): needs registration and an API key. Not used.
- Real-time train positions: the GTFS-RT feed has predicted stop times, no positions, and no CORS header. Not used.
- ULC route statistics: quarterly PDF tables per foreign city (newest 2025 Q4), without the Polish airport, behind a bot-protection page. Not machine-readable route data.

# Sources: transport, energy and mines

## Conclusions

- Nine sources write interims for roads, rail, airports, seaports, freight, power plants, renewables by powiat, oil and gas, and mines. Every one reprocesses from cache with `--offline`.
- Newest vintages: OSM extract 2026-11-26; Eurostat airports, ports, TEU and road freight 2025; GUS seaports 2025 (preliminary); PGE power capacity 2025; URE renewables as of 2026-09-30; mining output 2025.
- Road freight has no published region-to-region matrix. Rail freight flows between voivodeships exist only for 2020 (Eurostat `tran_r_rago`).
- `pl_transport_osm` adds a `lines` key to the interim contract: `{id, kind, ref, name, coords: [[lon, lat], ...]}`. W5 must read it; BLUEPRINT section 6 does not list it yet.

## Critical learnings

- Overpass: some networks drop a request that sends no byte for 60 s. Roads and rail are fetched as 15 bbox tiles per layer; the helper rotates endpoints and backs off on 429/502/504.
- ULC (airport statistics) sits behind a bot-protection page. Eurostat `avia_paoa` carries the same airport data; Warszawa-Chopin 2025 is 24,079,757 in Eurostat against 24,082,472 in ULC's PDF.
- Port tonnage differs by counting method: GUS gives Gdańsk 75.3 Mt for 2025, the port authority 80.4 Mt.
- OSM tags lignite plants as `coal`; the three lignite plants are named in code.

## Sources

| id | Publisher | Dataset | Exact URL | Vintage | Licence | Level | Fields / content | Caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_transport_osm` | OpenStreetMap contributors | Overpass: `highway=motorway`, `highway=trunk` with S ref; `railway=rail` + `usage=main`, no `service` | `https://overpass-api.de/api/interpreter` (fallback `https://maps.mail.ru/osm/tools/overpass/api/interpreter`), 30 tile queries | OSM extract 2026-11-26 | ODbL 1.0 | country table, `lines` | `motorway_km`, `expressway_km`, `motorway_other_km`, `rail_main_line_km`, `rail_main_electrified_line_km`, `rail_main_track_km`, `cmk_line_km`; lines with ref, track, electrified, maxspeed, cmk | Road km counts a one-way carriageway as half; line km = longest track per PLK line number. Under-construction roads excluded. |
| `pl_transport_network` | Eurostat (GUS data) | `tran_r_net` | `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tran_r_net?geo=PL,...&unit=KM` | 2024 (newest with values) | Eurostat re-use, attribution | country, nuts2 | motorway, rail line, electrified, double-track, river and canal km | Motorways = A-roads only. |
| `pl_transport_airports` | Eurostat; OSM; Wikidata; Government of Poland | `avia_paoa` (PAS_CRD), `avia_gooa` (FRM_LD_NLD); OSM aerodromes `icao~^EP`; Wikidata Q48840381; Port Polska priority P32 | `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/avia_paoa?...&sinceTimePeriod=2023`, same for `avia_gooa`; `https://www.wikidata.org/wiki/Q48840381`; `https://www.gov.pl/web/priorytety/p32` | traffic 2025; plan status 2026-06-30 | Eurostat re-use; ODbL; CC0; public information | points, country table | passengers, passengers_prev, freight_t, icao, iata, status, opening_planned, ref | Zielona Góra and Radom are not in Eurostat (null). Port Polska is planned; its first stage is planned by 2032. |
| `pl_transport_ports` | GUS; Eurostat; Wikidata | GUS "Gospodarka morska w Polsce w 2025 r." tables; GUS "Rocznik Statystyczny Gospodarki Morskiej 2025" Tabl. I; `mar_go_am_pl`; `mar_go_qm_c2026` (TEU) | `https://publikacje.new.stat.gov.pl/sites/default/files/2026-04/maritime_economy_in_Poland_in_2025_tables.xlsx`; `https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5515/11/18/1/rocznikstatystycznygospodarkimorskiej2025tabliceexcel.zip` | 2025 (Kołobrzeg 2024) | GUS/Eurostat re-use; CC0 | points, country table | cargo_kt, transit_kt, international, loading, unloading, cargo_kt_eurostat, teu; LNG capacity | GUS 2025 is preliminary. Elbląg, Darłowo, Ustka, Władysławowo have no tonnage. FSRU Gdańsk has no position. |
| `pl_transport_freight` | Eurostat (GUS data) | `road_go_na_rl3g`, `road_go_na_ru3g`, `tran_r_rago` | `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/road_go_na_rl3g?nst07=TOTAL&unit=THS_T&lastTimePeriod=2` (same for `ru3g`); `.../tran_r_rago?geo=PL&unit=T&lastTimePeriod=1` | road 2025, rail 2020 | Eurostat re-use | nuts3, voivodeship, flows | loaded_kt, unloaded_kt; rail flows kt between voivodeships | Road: no OD matrix. Rail: 2020 is the newest year. |
| `pl_energy_plants` | OSM; PGE; TAURON; operators; URE | OSM `power=plant` / `construction:power=plant` (Poland area + Baltic bbox); PGE Group management report 2025; TAURON environmental declaration 2024 | Overpass as above; `https://www.gkpge.pl/content/download/1c17c9bb500a8cc7ea488bc573451f3e/file/pge_sz2025.pdf?contentId=231076&inLanguage=pol-PL&version=2`; `https://www.tauron-wytwarzanie.pl/-/media/offer-documents/wytwarzanie/wydawnictwa/deklaracja-srodowiskowa-za-2024.ashx`; `https://www.ure.gov.pl/download/9/16381/RaportKrajowy2026.pdf` | OSM 2026-11-26; PGE 2025; curated 2026-11 | ODbL; public pages | points, country table | fuel, mw, mw_source, mw_year, operator, status, status_note, ref | Bełchatów uses PGE's current 5,097 MW installed capacity. Most other MW values are OSM tags. |
| `pl_energy_res` | URE; GUS BDL | "Mapa OZE" installations list; BDL units level 5 | `https://www.ure.gov.pl/download/9/16535/MAPAOZEna30092026nastroneURE.xlsx` (found on the URE page each run); `https://bdl.stat.gov.pl/api/v1/units?level=5&page-size=100&format=json&lang=pl&page=0..3` | 2026-09-30 | Polish PSI re-use | powiat | wind, solar, biomass, biogas, hydro, waste, cofiring, hydrogen, res_mw, installations (MW) | No micro-installations. Co-firing kept apart. 2 URE rows (tczewski in śląskie) unmatched. |
| `pl_energy_oilgas` | ORLEN; Gaz-System (via Wikipedia); Wikidata; OSM | curated sites | refs per site, e.g. `https://raportzintegrowany2022.orlen.pl/en/operating-segments/operating-segments-in-2022/refining/` | 2026-11 | public pages; CC0; ODbL | points | capacity_bcm, capacity_mt, status | Field output null (PIG-PIB Bilans only as PDF, host unreachable). Refinery capacity from the 2022 report. |
| `pl_mines` | Ministry of Industry (EC report 2025); WUG; KGHM; Sejm | curated mines with output | `https://www.gov.pl/attachment/f83b64ed-0cc8-4e47-b952-21e95fc6dbc0` (EC report), WUG reports per mine (`ref`), KGHM production report Dec 2025 | 2025 (sulphur 2024) | public information; CC0; ODbL | points, country table, companies | commodity, status, output, output_unit, output_year, ref | Mine output is raw coal; KGHM has no per-mine output. |

## Datasets looked for and not obtained

- ULC airport statistics (ulc.gov.pl): bot-protection page blocks scripts. Eurostat used instead.
- Road freight origin-destination matrix by NUTS 3 or voivodeship: not published by Eurostat or GUS (GUS "Transport drogowy w Polsce w latach 2024 i 2025" has voivodeship balances only, PDF).
- Rail freight flows newer than 2020: `tran_r_rago` ends in 2020.
- PSE installed capacity file or API: no keyless endpoint for installed capacity; URE national report 2026 used for the total (77,331 MW, 31.12.2025).
- PIG-PIB "Bilans zasobów złóż kopalin" 2025: PDF only; host not reachable from the fetcher. No per-field oil and gas output.
- Small seaports 2025 tonnage (Elbląg, Kołobrzeg, Darłowo, Ustka, Władysławowo): GUS publishes Kołobrzeg only, 2024.
- Brine salt fields and Eko-Plus mine: no published output or position.

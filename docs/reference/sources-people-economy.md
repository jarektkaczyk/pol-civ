# People and economy sources

## 1. Conclusions

- Two new sources feed the towns and metros: `pl_geo_places` (1,026 towns) and `pl_geo_fua` (55 Eurostat functional urban areas, 2,477 LAU rows).
- The builders read the W2 statistics and W4 society interims. Every table is optional: a missing one leaves its fields null until the next build.
- The US people and economy sources are removed: `acs`, `bea_gdp`, `bls_qcew`, `pep`, `census_gazetteer`, `cbsa_delineation`, `usrc_2020`, `cdc_places`, `census_boundaries`.

## 2. Next steps

| Date (UTC+7) | Owner | Step |
|---|---|---|
| 2026-11-27 | lead | Merge `people-economy` after `layers`; rebuild `cities`, `states`, `counties`, `citizens`, `districts`, `lenses`, `catalog`. |
| 2026-11-27 | lead | Add a refinery and a car-factory dataset if the Refinery town and Auto city badges should be awarded. |

## 3. Critical learnings

- GUS Tabl. 20 lists towns with type 1 (own urban gmina, 302) and type 4 (town of an urban-rural gmina, 724). Statistics exist per gmina, so a type-4 town reports its whole urban-rural gmina.
- The GUGiK name register (PRNG) hosts do not resolve from the pipeline's network. Town positions come from OpenStreetMap place nodes.
- Eurostat's LAU 2025 workbook carries the FUA of every LAU, so no polygon overlay is needed. Gdynia is its own FUA; Sopot is in Gdańsk's.

## 4. Source register

| Source id | Publisher and dataset | Exact URL | Vintage | Licence | Level | Fields | Caveats |
|---|---|---|---|---|---|---|---|
| `pl_geo_places` | GUS, "Powierzchnia i ludność w przekroju terytorialnym w 2026 r.", Tabl. 20 (towns); OpenStreetMap place nodes (Overpass) | https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/7/23/1/powierzchnia_i_ludnosc_w_przekroju_terytorialnym_2026_2.xlsx ; https://overpass-api.de/api/interpreter (query `node[place~"^(city|town)$"]` in Poland) | Towns on 1 Jan 2026, population 30 Jun 2026 (GUS half-year balance, table 11; population_2025 = 31 Dec 2025); OSM as fetched 2026-11-26 | GUS CC BY 4.0; OSM ODbL | town (TERYT7 type 1 or 4) | population, area_km2, powiat_rights, gmina, lon/lat | 1 town without an OSM node (Włodowice, town rights since 2026): placed at its gmina centre by the builder. |
| `pl_geo_fua` | Eurostat, LAU 2025 - NUTS 2024 correspondence with city and FUA ids | https://ec.europa.eu/eurostat/documents/345175/501971/EU-27-LAU-2025-NUTS-2024.xlsx/574c9e4a-2dae-99fe-5510-3fd18d8e90c2?t=1771601900130 | LAU 2025 | Eurostat reuse policy | gmina (TERYT6), FUA | nuts3, fua, city per gmina; FUA name, member gminas | 775 gminas in 55 FUAs. Two metros are merged in `cities.py` (Trójmiasto; Górnośląsko-Zagłębiowska). |

## 5. Datasets looked for and not used

- GUGiK PRNG (official town coordinates): `opendata.geoportal.gov.pl`, `mapy.geoportal.gov.pl` and `integracja.gugik.gov.pl` do not resolve from this network.
- Dwelling price per m2 by powiat: the W2 interim has only national price indices; the price lens is left out.
- Employment by PKD division (car making) per powiat: GUS publishes sections only; Auto city is published as a rule but not awarded.
- A refinery list: none of the interims names refineries; Refinery town is published as a rule but not awarded.
- National higher-education share (NSP 2021): the census interim has powiat shares for 270 powiaty only, so the Citizens education row has no national comparison.

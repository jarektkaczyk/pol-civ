# Sources: additional statistical lenses

## 1. Conclusions

- Six source ids add education, housing, tourism, exams, local finance, vehicles, farms, and election history.
- The finest published level ranges from gmina to powiat. Each lens states its level and year.
- Fixed broadband remains unavailable as a public machine-readable gmina dataset.

## 2. Next steps

| Date | Owner | Step |
|---|---|---|
| 2027-01-15 | lead | Recheck SIDUSIS for a public, token-free gmina export. |
| 2027-09-30 | lead | Replace the 2026 exam workbooks when CKE publishes the final 2027 national files. |

## 3. Critical learnings

- BDL publishes 2025 tourist use at powiat level. DBW adds exact figures for 58 cities, including 11 below powiat level.
- BDL price series cover dwellings in multi-unit buildings. They exclude detached houses.
- CKE publishes exam results by school location. Suppressed small cohorts remain null.
- Historical PKW codes can map type changes exactly. The 2015 Ostrowice row cannot be split between its successors.
- Ministry finance files use dBASE. The source reads the official Rb-27S, Rb-28S, and Rb-Z records directly.

## 4. Sources

| id | Publisher | Dataset | Exact URL | Vintage | Licence | Level | Fields | Caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_census_2021` | Statistics Poland (GUS) | BDL NSP 2021 subject P4318; five final regional workbooks | `https://bdl.stat.gov.pl/api/v1/data/by-variable/1719968?unit-level=5&year=2021`; same endpoint for variable `1719969` and levels 5 and 6; regional URLs below | NSP reference date 2021-03-31 | GUS CC BY 4.0 | powiat, gmina | residents aged 13+, higher-education count and share; 11 regional category fields | The BDL denominator includes unknown education. Regional category counts use their workbook definitions. New gminas created after 2021 stay null. |
| `pl_stats_prosperity` | Statistics Poland (GUS); Ministry of Finance | BDL housing P3820, property P3787/P3788, tourism P2396; DBW city tourism; existing income tables | `https://bdl.stat.gov.pl/api/v1/data/by-variable/747060?unit-level=6&year=2025`; variables `633677`, `633682`, `633687`, `633692`, `633697`, `633702` at level 5; variable `60298` at level 5; `https://api-dbw.stat.gov.pl/api/variable/variable-data-section?id-zmienna=94&id-przekroj=1408&id-rok=2025&id-okres=282&ile-na-stronie=5000&numer-strony=0&lang=pl` | GUS 2025; Ministry 2026 | GUS CC BY 4.0; public sector reuse | gmina, powiat | dwellings completed per 1,000; median and average PLN/m2 overall, primary, secondary; tourist nights per resident | The gmina tourism table covers 77 cities and has 74 values. Prices omit detached houses. Zero prices with no transaction stay null. |
| `pl_more_exams` | Central Examination Commission (CKE); Centre for Education Informatics (CIE) | National exam map workbooks | `https://mapa.wyniki.edu.pl/MapaEgzaminow/assets/data/CSV/E8/2026/E8_2026_gminy_09.xlsx`; `https://mapa.wyniki.edu.pl/MapaEgzaminow/assets/data/CSV/EM2023/2026/EM2023_2026_powiaty_09.xlsx` | September 2026 | Public sector information; no separate file licence stated | gmina, powiat | grade 8 Polish, maths, English means; matura pass rate | Results follow school location. Siedlecki powiat has no matura row. Small E8 cohorts are suppressed. |
| `pl_more_finance` | Ministry of Finance; GUS; RIO Kraków | FY2025 Rb-27S, Rb-28S, Rb-Z; GUS population; RIO classification | `https://www.gov.pl/attachment/f98752f2-176a-4be1-910f-8aca6ffd9044`; `https://www.gov.pl/attachment/1eb59fb5-ab95-4f0d-8d62-4ef07c1a9910`; `https://www.gov.pl/attachment/7ed5e4aa-50a5-46f7-a32e-337675319a8b`; `https://bip-docrepo-api.krakow.rio.gov.pl/api/files/13668` | FY2025 Q4; population 2025-12-31 | MF public sector reuse; GUS CC BY 4.0 | gmina | own income, investment spending, debt per resident | Cities with powiat rights include both municipal and powiat functions. |
| `pl_more_gus` | Statistics Poland (GUS) | BDL transport P2420; Agricultural Census P4138/P4140 | `https://bdl.stat.gov.pl/api/v1/data/by-variable/60533?unit-level=5&year=2025`; `https://bdl.stat.gov.pl/api/v1/data/by-variable/1633207?unit-level=6&year=2020`; `https://bdl.stat.gov.pl/api/v1/data/by-variable/1645031?unit-level=6&year=2020` | vehicles 2025; PSR reference date 2020-06-01 | GUS CC BY 4.0 | powiat, gmina | passenger cars per 1,000; average farm area; land in farms | Farm land follows the holding seat and can cross gmina borders. Electric cars are unavailable by powiat. |
| `pl_soc_elections` | National Electoral Commission (PKW) | Presidential second rounds 2015 and 2020, plus existing 2025 and Sejm 2023 | `https://danewyborcze.kbw.gov.pl/dane/2015/prezydent/2/prez2015_2_tura_gm.xls`; `https://danewyborcze.kbw.gov.pl/dane/2020/prezydent/2/wyniki_gl_na_kand_po_gminach_csv.zip` | 2015-05-24; 2020-07-12 | Public information | gmina, country | candidate votes and shares, turnout, national totals | Ostrowice 2015 is unmatched and remains in totals. Historical boundaries apply. |

### Regional census workbooks

- Kujawsko-Pomorskie: `https://bydgoszcz.stat.gov.pl/download/gfx/bydgoszcz/pl/defaultaktualnosci/753/19/1/1/tablice_nsp2021_stan_i_struktura_dem-spol_w_woj._kuj-pom_w_swietle_wynikow_nsp_2021.xlsx`
- Łódzkie: `https://lodz.stat.gov.pl/download/gfx/lodz/pl/defaultaktualnosci/753/27/1/1/202401_p_nsp_stan_i_struktura_demog_spol_lodzkie.xlsx`
- Pomorskie: `https://gdansk.stat.gov.pl/download/gfx/gdansk/pl/defaultaktualnosci/753/15/1/1/nsp_2021_stan_i_struktura_demo-spol_ludnosci_pomorskie_-tablice_wynikowe-dodatkowe.xlsx`
- Warmińsko-Mazurskie: `https://olsztyn.stat.gov.pl/download/gfx/olsztyn/pl/defaultaktualnosci/753/32/1/1/2024_01_31_stan_i_struktura_demograficzno_spoleczna_ludnosci.xlsx`
- Zachodniopomorskie: `https://szczecin.stat.gov.pl/download/gfx/szczecin/pl/defaultaktualnosci/753/19/1/1/aneks_wojewodzki.xlsx`

## 5. Datasets checked but not obtained

- UKE 2025 market report: `https://uke.gov.pl/akt/raport-o-stanie-rynku-komunikacji-elektronicznej-w-2025-roku,670.html`. It offers PDFs only.
- Retired SIIS: `https://api.dane.gov.pl/1.4/datasets/588`. The metadata says SIIS is shut down and no longer updated.
- dane.gov.pl SIDUSIS search: `https://api.dane.gov.pl/1.4/datasets?q=SIDUSIS`. It returned zero datasets.
- SIDUSIS homepage, map, coverage endpoint, reports endpoint, and FAQ: `https://internet.gov.pl/`, `https://internet.gov.pl/map/`, `https://internet.gov.pl/api/voivodeships/12/network_ranges/`, `https://internet.gov.pl/api/reports/`, and `https://internet.gov.pl/static/docs/faq.pdf`. Automated requests returned HTTP 403. The API document at `https://internet.gov.pl/media/public/docs/api.pdf` requires a token.
- Q3 2026 SIDUSIS release: `https://www.gov.pl/web/instytut-lacznosci/wiecej-adresow-w-zasiegu-internetu-stacjonarnego--raport-za-iii-kwartal-2026-r`. It offers 17 PDFs and no data file. The regional PDFs print gmina rows, but the pipeline cannot reproduce them with standard-library parsing.
- CEPiK electric passenger cars by powiat: `https://api.cepik.gov.pl/doc` provides registration-period records, not a current stock table. Some records combine city and land powiats. GUS DBW variable 851 publishes fuel only by voivodeship: `https://api-dbw.stat.gov.pl/api/variable/variable-meta?id-zmiennej=851&lang=pl`.

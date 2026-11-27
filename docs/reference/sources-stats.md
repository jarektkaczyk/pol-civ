# Statistics sources

## Conclusions

Six cached sources cover population, labour, local income, education, GDP, and foreigners.
The population table contains 2,479 gminas and totals 37,332,510 people.
Bulk files replace BDL for the required labour, finance, housing, tourism, and census work.
The sources run offline after the first successful fetch.

## Critical learnings

- The 2026 division contains 2,479 whole gminas. The blueprint count of 2,477 was provisional.
- GUS labour bulk tables cover 380 powiats and 2,479 gminas without BDL requests.
- Ministry of Finance 2026 files cover 2,477 gminas and city counties.
- Regional NSP workbooks use different schemas. Unsupported education values stay null.
- Eurostat has 2024 voivodeship GDP. NUTS3 GDP and GVA end in 2023.
- The PESEL UKR powiat identifies the registering authority. It may differ from current residence.

## Source register

| Source id | Publisher and dataset | Exact URL | Vintage | Licence | Level | Fields | Caveats |
|---|---|---|---|---|---|---|---|
| `pl_stats_population` | GUS population, demography, life expectancy, and higher education | [30 June 2026 population][pop26], [2025 population][pop25], [2020 population][pop20], [2015 population][pop15], [2026 area][area26], [demography][demography], [life expectancy][life], [universities][universities] | Population, sex and five-year ages 2026-06-30; population_2025 and density 2025-12-31; area 2026-01-01; other annual data 2025 | CC BY 4.0 | gmina, voivodeship, country | Population, sex, five-year ages, broad ages, area, density, history, vital events, migration, working-age shares, median age, fertility, life expectancy, students, graduates | Change since 2015 compares 31 December 2025 with 31 December 2015. Births, deaths and migration stay full-year 2025 (the June edition has half-year flows). Migration rates exist only for total migration. Median age, fertility, and life expectancy are voivodeship data. Student city totals use institution locations. |
| `pl_stats_labour` | GUS monthly unemployment, employment, and wage distribution | [unemployment][unemployment], [employment][employment], [wages][wages] | October 2026; May 2026; December 2025 | CC BY 4.0 | gmina, powiat, country | Unemployed count and rate, average and median wage, total workers, PKD A-S, three gmina sectors | PKD A-S uses employer seat. The gmina workbook publishes only three broad sectors. Suppressed values stay null. |
| `pl_stats_prosperity` | Ministry of Finance local income; GUS housing, property, and tourism | [planned income][mf-income], [tax indicator][mf-indicator], [housing][housing], [property][property], [tourism][tourism] | Ministry 2026; GUS 2025 | Public sector reuse terms; GUS CC BY 4.0 | gmina, voivodeship, country | Planned PIT income, PIT per person, tax indicator, completions, completions per 1,000, beds, nights, property indices | GUS bulk tables limit housing and tourism to voivodeships. They omit powiat PLN/m2. REGON, useful floor area, and household income remain gaps. |
| `pl_census_2021` | GUS final and preliminary regional NSP education tables | [Kujawsko-Pomorskie final workbook][census-kuj], [Pomorskie final workbook][census-pom], other [regional office results][census-search], and [2026 TERYT][area26] | NSP 2021, reference date 2021-03-31 | CC BY 4.0 | powiat | Population aged 13+, full education categories where published, higher-education share | Regional workbooks have different schemas. The interim contains all 380 TERYT powiats. Final count fields cover 109 rows and higher share covers 270. Other values stay null. |
| `pl_gdp` | GUS regional accounts 2024 (revision of 30 September 2026); Eurostat regional and national accounts; ECB exchange rate | [GUS regional GDP 2024][gusgdp], [NUTS2 GDP][gdp2], [NUTS3 GDP][gdp3], [NUTS3 GVA][gva3], [national GDP][gdpn], [GDP per person][gdppc], [ECB rate][ecb] | National 2025; voivodeship 2024 (GUS, 30 September 2026); NUTS3 GDP and GVA 2023 | Eurostat reuse policy; ECB attribution terms | voivodeship, NUTS3, country | GDP in PLN (GUS) and EUR (Eurostat), GDP per person in PLN (GUS) and EUR, GVA by NACE A*6, national GDP in PLN, EUR, and USD | Voivodeship gdp_pln is GUS; Eurostat PLN is kept as gdp_pln_eurostat. Mazowieckie combines PL91 and PL92 (GUS: Warszawski stołeczny and Mazowiecki regionalny). USD uses the 2025 ECB annual rate. |
| `pl_foreigners` | Ministry of Digital Affairs PESEL UKR; GUS temporary protection | [PESEL UKR dataset][ukr-dataset], [November file][ukr-nov], [GUS annual file][ukr-gus] | PESEL UKR 2026-11-11, published 2026-11-16; GUS 2025-12-31 | dane.gov.pl CC0 1.0; GUS CC BY 4.0 | powiat, voivodeship | PESEL UKR total, men, and women | Powiat is the registering authority. Values below two would stay null. ZUS data remains unavailable to automated downloads. |

## Interim coverage

| Source id | Tables and row counts |
|---|---|
| `pl_stats_population` | population 2,479; vital migration 2,479; demographic indicators 16; university voivodeship 16; university city 93; headline 1 |
| `pl_stats_labour` | labour powiat 380; PKD employment powiat 380; sector employment gmina 2,479; headline 1 |
| `pl_stats_prosperity` | income gmina 2,477; housing voivodeship 16; tourism voivodeship 16; property and headline 1 each |
| `pl_census_2021` | education powiat 380 |
| `pl_gdp` | GDP voivodeship 16; GDP NUTS3 73; GVA NUTS3 73; GVA voivodeship 16; country 1 |
| `pl_foreigners` | PESEL UKR powiat 380; temporary protection voivodeship 16 |

## Missing datasets

- GUS bulk releases omit powiat dwelling prices in PLN/m2.
- GUS bulk releases omit gmina housing completions and tourism for 2025.
- REGON by PKD, useful floor area, and household disposable income remain unavailable here.
- Final NSP regional bulk files do not contain one consistent full powiat education breakdown.
- ZUS publishes foreign-insured data, but its server rejects automated downloads.
- Incomplete BDL pages are excluded. The BDL helper stops before request 91 per process.

[pop26]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/6/41/1/ludnosc_stan_i_struktura_30.06.2026.zip
[pop25]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/6/40/1/ludnosc.stan_i_struktura_31.12.2025.zip
[pop20]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/6/29/1/ludnosc.stan_i_struktura_31.12.2020.zip
[pop15]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/6/19/1/stan_i_struktura_ludnosci_oraz_ruch_naturalny_w_przekroju_terytorialnym_31-12-2015_-_tabele.zip
[area26]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/7/23/1/powierzchnia_i_ludnosc_w_przekroju_terytorialnym_2026_2.xlsx
[demography]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/40/6/1/sytuacjademograficznapolskido2025.xlsx
[life]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5470/2/20/1/tablica_b_srednie_dalsze_trwanie_zycia_wedlug_wojewodztw_w_2025_r..xlsx
[universities]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5488/8/12/1/szkolnictwo_wyzsze_w_roku_akademickim_2025-2026_tab2_2.xlsx
[unemployment]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5473/2/171/1/liczba_bezrobotnych_i_stopa_bezrobocia_pow_10_2026.xlsx
[employment]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5474/27/37/1/pracujacy_w_gospodarce_narodowej_w_polsce_w_grudniu_2025_tab.xlsx
[wages]: https://publikacje.new.stat.gov.pl/sites/default/files/2026-11/Rozk%C5%82ad%20wynagrodze%C5%84%20w%20gospodarce%20narodowej%20w%20maju%202026%20r%20Tablice.xlsx
[mf-income]: https://www.gov.pl/attachment/23e9b124-8545-4178-ab54-81a9df16ace6
[mf-indicator]: https://www.gov.pl/attachment/fd12e8c5-be53-40cf-a72b-c54be3f39f4b
[housing]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5478/5/171/1/budownictwo_mieszkaniowe_w_okresie_styczengrudzien_2025_r._wykresy.xlsx
[property]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5492/8/9/1/obrot_nieruchomosciami_w_2025_tab.xlsx
[tourism]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5494/1/23/1/turystykaw2025r._tablice.zip
[census-kuj]: https://bydgoszcz.stat.gov.pl/download/gfx/bydgoszcz/pl/defaultaktualnosci/753/19/1/1/tablice_nsp2021_stan_i_struktura_dem-spol_w_woj._kuj-pom_w_swietle_wynikow_nsp_2021.xlsx
[census-pom]: https://gdansk.stat.gov.pl/download/gfx/gdansk/pl/defaultaktualnosci/753/15/1/1/nsp_2021_stan_i_struktura_demo-spol_ludnosci_pomorskie_-tablice_wynikowe-dodatkowe.xlsx
[census-search]: https://warszawa.stat.gov.pl/wyszukiwarka/szukaj.html?query=demograficzno-spo%C5%82eczna
[gusgdp]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5482/7/9/1/produkt_krajowy_brutto_i_wartosc_dodana_brutto_w_przekroju_regionow_w_2024_r._tablice.xlsx
[gdp2]: https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/nama_10r_2gdp?format=TSV&compressed=true
[gdp3]: https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/nama_10r_3gdp?format=TSV&compressed=true
[gva3]: https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/nama_10r_3gva?format=TSV&compressed=true
[gdpn]: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10_gdp?lang=en&geo=PL&na_item=B1GQ&sinceTimePeriod=2024
[gdppc]: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10_pc?lang=en&geo=PL&na_item=B1GQ&sinceTimePeriod=2024
[ecb]: https://data-api.ecb.europa.eu/service/data/EXR/A.USD.EUR.SP00.A?startPeriod=2025&endPeriod=2025&format=csvdata
[ukr-dataset]: https://dane.gov.pl/pl/dataset/2715,zarejestrowane-wnioski-o-nadanie-statusu-ukr
[ukr-nov]: https://api.dane.gov.pl/media/resources/20261116/STATYSTYKI_POWIAT_UKR_20261116.xlsx
[ukr-gus]: https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5471/20/1/1/liczba_mieszkancow_ukrainy_31_12_2025.xlsx

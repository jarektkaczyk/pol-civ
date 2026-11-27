# Identity, history, flows and time sources

## Conclusions

- 5 new sources feed 7 new lenses, 3 new map layers and the year slider. Each one processes from cache with `--offline`.
- National and ethnic identity and home language exist per gmina (NSP 2021, 2,477 gminas of 2021). GUS lists an identity in a gmina only when 10 or more people declared it; fewer stays null.
- The 1914 partition borders and the interwar border come from CShapes 2.0 (ETH Zurich). Its licence is CC BY-NC-SA 4.0: free to share with attribution, non-commercial only, derived lines under the same licence.
- Commuting is the NSP 2021 gmina-to-gmina matrix (31 March 2021). It is the newest edition: GUS publishes it once per census.
- EU funds cover the 2021-2027 European Funds project list of 1 November 2026 (242.5 bn zł of EU co-financing, 66.5% of it placed in named gminas). KPO (the Recovery plan) has no open project list with places, so it is left out.
- Population by gmina exists for every 31 December 2015-2025 and for 30 June 2026 from the GUS bulk tables. No BDL requests are made.

## Critical learnings

- BDL (`bdl.stat.gov.pl/api`) answers this network with an HTML "blocked for security reasons" page (HTTP 500). Every source here uses bulk files instead.
- The GUS population ZIPs change layout between years (`tabela08.xls`, `Tabela_IV.xls`, `.xlsx` members). A table counts only if its whole-gmina rows add up to 36-39 million people; age tables have big numbers in the code column and fail that test.
- From 31 December 2021 GUS population counts are rebased on the 2021 census. Part of the 2020-2021 change on the slider is that rebasing (Warszawa +69,000), not migration. The slider note says so.
- The commuting matrix splits urban-rural gminas into a town (type 4) and a rural part (type 5). They are added into the whole gmina (type 3); flows between the two parts are dropped.
- The EU project list has no TERYT codes. Places are matched by voivodeship, powiat and gmina name; "X - Gmina wiejska" is the rural gmina. Only 6 names (cut off at the end of very long cells) did not match, worth 0.0 bn zł.

## Sources

| id | Publisher | Dataset | URL | Vintage | Licence | Level | Fields | Caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_identity` | GUS | NSP 2021 final results: national and ethnic identity, TABL. 5; language used at home, TABL. 5 | https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/6536/10/1/1/przynaleznosc_narodowo-etniczna_-_dane_nsp_2021_dla_kraju_i_jednostek_podzialu_terytorialnego_v2.xlsx and .../jezyk_uzywany_w_domu_-_dane_nsp_2021_dla_kraju_i_jednostek_podzialu_terytorialnego.xlsx | 31 March 2021, published 20 December 2023 | GUS CC BY 4.0 | gmina (2021 codes) | counts and shares of Silesian, Kashubian, German, Ukrainian, Belarusian, Lemko, Roma, Lithuanian, Russian, Jewish, Armenian, Czech, Slovak, Tatar, Karaim identity; largest identity other than Polish; Silesian, Kashubian, German, Lemko, Belarusian, Ukrainian at home | First or second declaration, so identities do not add up. Fewer than 10 people = null. "śląsko-cieszyńska" is a separate answer, not Silesian. |
| `pl_hist_population` | GUS | Ludność. Stan i struktura oraz ruch naturalny w przekroju terytorialnym, 12 editions | https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/6/{19,21,23,25,27,29,31,34,36,38,40,41}/1/... (exact files in the source) | 31 Dec 2015 to 31 Dec 2025, 30 June 2026 | GUS CC BY 4.0 | gmina | `pop_2015` ... `pop_2025`, `pop_2026_06` | Each year on its own borders. Szczawa (1207132) and Grabówka (2002162) have no figure before 2025. Census rebasing from 2021. |
| `pl_flows_commuting` | GUS | Macierz przepływów ludności związanych z zatrudnieniem, NSP 2021 | https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/6536/9/2/1/macierz_przeplywow_ludnosci_zwiazanych_z_zatrudnieniem.xlsx | 31 March 2021, published 31 January 2024 | GUS CC BY 4.0 (reuse with the source named) | gmina to gmina (75,557 flows), gmina totals | `commuters_in`, `commuters_out`, `commuters_net`; flows in persons | Wage employees only. Flows under 3 people are not published (the matrix holds 4.96 of 5.18 million commuters). |
| `pl_eu_funds` | Ministry of Funds and Regional Policy | Lista projektów realizowanych z Funduszy Europejskich w Polsce w latach 2021-2027 (dane.gov.pl dataset 13939) | https://api.dane.gov.pl/resources/2912686,lista-projektow-realizowanych-z-funduszy-europejskich-w-polsce-w-latach-2021-2027-1-listopada-2026-r/file | 1 November 2026 | CC0 1.0 | gmina | `eu_cofinancing` (zł), `projects` | A project in several gminas is split equally. Places named only as a powiat (9.6 bn zł), a voivodeship (30.0 bn zł) or the whole country (41.4 bn zł) are left out. Programmes: 16 regional FE programmes, FENG, FEnIKS, FERS, FEPW, FERC, technical assistance, FER, FAMI, FBW, IZZG, Interreg programmes managed in Poland. |
| `pl_hist_borders` | ETH Zurich, International Conflict Research | CShapes 2.0 (Schvitz, Rüegger, Girardin, Cederman, Weidmann and Gleditsch 2022, Journal of Conflict Resolution 66(1): 144-161) | https://icr.ethz.ch/data/cshapes/CShapes-2.0.geojson | 2022 release; borders on 1914-07-01 and 1930-01-01 | CC BY-NC-SA 4.0 | lines (lon/lat) | 1914 borders between the German Empire, the Russian Empire and Austria-Hungary; border of Poland 1921-1939 with Germany, Danzig, Lithuania, Latvia, the Soviet Union, Romania, Czechoslovakia | No stated scale; lines run within a few km of other historical maps. The 1938 and 1939 changes are not shown. |

## Lenses and layers built from them

| Item | Kind | Level | Rule |
|---|---|---|---|
| Silesian, Kashubian, German, Belarusian identity | lens (log scale) | gmina | Share of residents declaring the identity (first or second answer). |
| Largest minority identity | category lens | gmina | The identity other than Polish with the most people; named categories as in the census, "Another identity" for the rest. |
| Commuters in | lens (log scale) | gmina | Wage employees commuting in per 1,000 residents (both NSP 2021). |
| EU co-financing | lens (log scale) | gmina | EU co-financing of 2021-2027 projects per resident (population 30 June 2026). |
| Borders of 1914, Interwar border | map switches | lines | See `history.json` rules. |
| Commuters | map switch | arcs | The 12 most populous cities; into each, flows of 250 people or more, the largest 40. |
| Year slider | density and change lenses | hex | 2015-2025 (31 December) and June 2026; `#year=` in the URL. |

## Looked for and not used

- **Commuters per 1,000 jobs.** No gmina-level count of jobs by workplace exists for 2021 outside BDL, and BDL blocks this network. The NSP 2021 labour tables are per voivodeship. The GUS "Pracujący w gospodarce narodowej" series starts in December 2022. The lens uses residents (same census) as the base instead.
- **KPO (Recovery plan) by gmina.** dane.gov.pl has ARiMR measures per voivodeship (dataset 3190) and a CUPT list of 176 transport projects without places (dataset 4352). kpo.gov.pl and mapadotacji.gov.pl refused the TLS connection from this network.
- **Other 1914 border datasets.** Zenodo record 20119653 ("Map of Europe, c. 1914", CC BY 4.0) has no stated lineage. aourednik/historical-basemaps (GPL-3.0) is too coarse (it puts Katowice in Russia). The MPIDR Population History GIS Collection has 1900 and 1930, not 1914, and refuses anonymous requests. Thenmap starts in 1945.

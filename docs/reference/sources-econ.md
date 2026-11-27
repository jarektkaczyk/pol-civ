# Sources: enterprise and innovation lenses

## Conclusions

- Three source ids feed six lenses in the new group Enterprise (Przedsiębiorczość): tech firms, new firms, sole traders (gmina), patents (powiat), R&D spending (voivodeship) and new factories and warehouses (gmina).
- The REGON tables are GUS monthly XML files by gmina, state at the end of October 2026. They use PKD 2007 (the table headers say so).
- Patents are 2024 and 2025 together. R&D spending is 2024, the newest year in DBW (2025 is empty).
- The permit lens counts GUNB register decisions of 2024-11-26 to 2026-11-25 (the newest file date).

## Critical learnings

- The REGON XML has no national row. City rows with type 1 hold only the entities that no district or delegation holds: Warszawa, Kraków, Łódź, Poznań and Wrocław are the type 1 row plus the type 8 or 9 rows. Types 4 and 5 repeat type 3 and are not added.
- Sum of whole gminas, October 2026: 5,541,584 entities, of which 336,360 in section J (6.07%). The GUS headline for the month is 5,543.8 thousand: about 2,200 entities have no gmina. The PKD table 1 has 336,639 section J entities in Poland.
- DBW flag 42 ("zjawisko nie wystąpiło") is a true zero; flag 38 (no information) is null. Two powiaty are null: karkonoski (0206, flag 38 in both years) and Sopot (2264: 2024 is flagged 42 with the value 4, a contradictory record).
- A GUNB CSV row is one building object or one amendment. Lesznowola (1418032) has 67 matching rows and 36 unique decisions.
- The GUNB CSV holds investor and designer names. The source reads six columns only and never extracts the CSV.

## Sources

| id | Publisher | Dataset | Exact URL | Vintage | Licence | Level | Fields | Caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_econ_regon` | Statistics Poland (GUS) | Miesięczna informacja o podmiotach gospodarki narodowej w rejestrze REGON, tables 3, 4 and 6 (XML) | `https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5504/4/118/1/202610_t03_dane_teryt_pkd.xml`, `..._t04_dane_teryt_pkd_fizyczne.xml`, `..._t06_dane_teryt_sfp_nowe.xml`; table 6 also for 2025-11 to 2026-09 (release pages linked from `https://stat.gov.pl/obszary-tematyczne/podmioty-gospodarcze-wyniki-finansowe/zmiany-strukturalne-grup-podmiotow/`) | state at the end of 2026-10; new registrations 2025-11 to 2026-10 | GUS CC BY 4.0 | gmina, country | entities, section J entities and share, sole traders and per 1,000 residents, new entities in 12 months and per 1,000 residents | Registered entities, not active firms or jobs. A sole trader counts at the registered address. Rates use population on 2026-06-30. GUS has no 18-64 band by gmina in the pipeline, so sole traders are per 1,000 residents of all ages. Private farmers are not in REGON counts. |
| `pl_econ_innovation` | Statistics Poland (GUS), Dziedzinowe Bazy Wiedzy | Variable 463 "Udzielone patenty", section 169, position "Ogółem"; variable 406 "Nakłady wewnętrzne na działalność B+R", section 2 "na 1 mieszkańca" | `https://api-dbw.stat.gov.pl/api/variable/variable-data-section?id-zmienna=463&id-przekroj=169&id-rok=2025&id-okres=282&ile-na-stronie=5000&numer-strony=0&lang=pl` (and `id-rok=2024`); `https://api-dbw.stat.gov.pl/api/variable/variable-data-section?id-zmienna=406&id-przekroj=2&id-rok=2024&id-okres=282&ile-na-stronie=5000&numer-strony=0&lang=pl` | patents 2024 and 2025; R&D 2024 | GUS CC BY 4.0 | powiat, voivodeship, country | patents (2 years), patents per 100,000 residents, R&D spending per resident (PLN) | Powiat patents cover national applications in the national procedure, at the seat of the first applicant (DBW method note). Per 100,000 uses population on 2025-12-31. R&D follows the unit that does the research. |
| `pl_econ_permits` | Główny Urząd Nadzoru Budowlanego (GUNB) | Rejestr Wniosków, Decyzji i Zgłoszeń w sprawach budowlanych (dane.gov.pl dataset 3467), 16 voivodeship files | `https://wyszukiwarka.gunb.gov.pl/pliki_pobranie/wynik_<voivodeship>.zip` (ASCII names, for example `wynik_opolskie.zip`); `https://dane.gov.pl/pl/dataset/3467` | decisions 2024-11-26 to 2026-11-25 | CC0 1.0 | gmina, country | permit decisions for new category XVIII buildings in 24 months | Category XVIII of the Prawo budowlane annex (Dz.U. 2025 poz. 418): industrial and storage buildings, also sheds and railway buildings. First-instance decisions only; no approval or refusal flag; no closed (military) areas. 187 decisions without a usable TERC code are left out. Recent weeks can be incomplete. |

## Not available

| Dataset | Reason |
|---|---|
| REGON per 100 residents aged 18-64 | The pipeline population table has 5-year bands (15-19 includes 15-17), so 18-64 cannot be built by gmina. |
| CEIDG gmina aggregates | The CEIDG data warehouse needs an account and a Profil Zaufany login. Open CEIDG files on dane.gov.pl stop in 2019 and are by voivodeship. |
| Polska Strefa Inwestycji decisions by gmina | No open list of individual decisions; totals exist only by zone and year. |
| FDI by voivodeship (NBP) | The full NBP report is behind bot protection; the open note has no regional table. |
| Exports by voivodeship | Not in open GUS files; the tax administration data exist only in PDF reports. |
| GUS BDL REGON indicators | BDL was in maintenance (HTTP 503) on 2026-11-26; the monthly REGON XML gives the same counts by gmina. |

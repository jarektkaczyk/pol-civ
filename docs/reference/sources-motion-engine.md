# Motion layer sources: commuters, trade routes, new factories and warehouses

## Conclusions

- The motion engine adds no new source. It animates two existing files (`commuting.json`, `trade.json`) and adds one new file, `permits_monthly.json`, from the cached GUNB permit register (`pl_econ_permits`).
- `permits_monthly.json`: 36,734 gmina-decisions for new industrial and storage buildings in 2,325 gminas, 130 months from 2016-01 to 2026-10 (file of 2026-11-25), 439 kB.
- The counts do not show a boom. Decisions per year: 3,110 (2016, the register's first year), 3,849 (2017), 3,825 (2018), 3,602 (2019), 3,232 (2020), 3,719 (2021), 3,491 (2022), 3,193 (2023), 3,076 (2024), 3,047 (2025), 2,590 (2026 to October). The page therefore names the layer "New factories and warehouses", not "Investment boom".
- The hours of the commuters and the speed of the wagons are for show. Each file says so in its `rules`.

## Critical learnings

- A permit decision repeats on many CSV rows (one per building object and per amendment). Counting matching rows gives about 84,000 "permits"; counting unique (authority, decision number) pairs per gmina gives 36,734.
- The newest month in a file is never complete (authorities enter decisions late). The builder stops at the last full month before the file date.
- 1,701 decisions have no usable TERC code and are left out (4.4%).

## Sources

| id | Publisher | Dataset | URL | Vintage | Licence | Level | Fields | Caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_econ_permits` | Główny Urząd Nadzoru Budowlanego (GUNB) | Rejestr wniosków, decyzji i zgłoszeń (RWDZ), dane.gov.pl dataset 3467 | https://dane.gov.pl/pl/dataset/3467, files `https://wyszukiwarka.gunb.gov.pl/pliki_pobranie/wynik_<voivodeship>.zip` | file of 2026-11-25; decisions 2016-01 to 2026-10 | CC0 1.0 | gmina, month | decisions (unique authority and decision number) per gmina per month, category XVIII, works "budowa nowego" | First-instance decisions only; no flag for approval or refusal; no closed (military) areas; a permit does not mean the building was built. Investor and designer names are never read. |
| `pl_flows_commuting` | GUS | NSP 2021 commuting matrix (existing) | see `sources-more-b.md` | 2021-03-31 | as listed there | gmina pairs | wage employees per flow | No hours: the morning and afternoon shape on the map is for show. |
| `pl_transport_freight` | Eurostat | rail regional freight (existing) | see `sources-economy-infra.md` | 2020 | as listed there | voivodeship pairs | thousand tonnes per year | No routes, speeds or timetables: wagon counts follow tonnes, their speed is for show. |

## Refresh

| Output | Cadence | How |
|---|---|---|
| `permits_monthly.json` | monthly | After `pipeline fetch pl_econ_permits` and `process pl_econ_permits`: `pipeline build --deps permits_monthly` (17 s, reads the 16 zips). |
| `commuting.json`, `trade.json` | unchanged (static) | Only their `rules` text grew. |

## Looked for and not used

- Hourly commuter counts by gmina pair: the NSP 2021 matrix gives the flow, not the time of travel. The hours stay illustrative.
- Rail freight train counts by route: not searched in this task. Wagon counts stay proportional to tonnes.

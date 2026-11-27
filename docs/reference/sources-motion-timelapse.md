# Time-lapse sources (motion-timelapse)

## Conclusions

- Two new sources feed four lenses that play on the motion clock: tourist nights by month, the smog week, the presidential vote morph and the population years.
- Tourist nights exist per voivodeship and month from BDL subject P2882. The newest 36 months run from 2023-10 to 2026-09 (October 2026 is not published yet). The 16 voivodeships add up exactly to the BDL total for Poland.
- The smog week is 2026-01-18 00:00 to 2026-01-25 00:00 (UTC+1): the highest 7-day mean of the hourly national PM2.5 means between 2025-12-01 and 2026-02-28, 58.3 ug/m3 (runner-up windows start 2026-01-17 at 57.7 and 2026-01-19 at 57.5; the worst December week reaches 28.1). 128 automatic stations reported in the season, 117 in the chosen week. The worst day is 2026-01-22 (national mean 78.9).
- The vote morph and the population years need no new download: they reuse `lenses.json` (vote_2015, vote_2020, vote) and `timeline.json`.

## Critical learnings

- GIOŚ `metadata/sensors` is stale: 23 stations with hourly PM2.5 in December 2025 are missing or closed there. The current-data endpoint (`data/getData`, 1,500 requests per minute) names each position (`-1g` or `-24g`) and answers HTTP 400 (API-ERR-100003) for manual samplers, so it classifies a sensor cheaply.
- `archivalData/getDataBySensor` gives at most 500 rows per page at 2 requests per minute: 59 winter days of one hourly sensor take 3 requests. The documented maximum page size is 500, but `size=1500` works (tested 2026-11-27), so one request holds a sensor's whole January and February. The fetch is resumable; 123 sensors took about 80 minutes at 2 requests per minute.
- The GIOŚ yearly archive file ("Wyniki pomiarów z 2025 roku", 50 MB) covers December 2025 with no API calls.
- GIOŚ timestamps close the hour (01:00 is the hour 00:00-01:00) and stay UTC+1 all year.

## Sources

| id | Publisher | Dataset | URL | Vintage | Licence | Level | Fields | Caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_tourism_monthly` | GUS, Bank Danych Lokalnych | P2882 "Wykorzystanie turystycznych obiektów noclegowych według miesięcy": variable "udzielone noclegi ogółem" in "turystyczne obiekty noclegowe ogółem", one variable per month (201916 January ... 201783 December) | https://bdl.stat.gov.pl/api/v1/data/by-variable/201916?format=json&page=0&page-size=100&unit-level=2&year=2023&year=2024&year=2025&year=2026 (and the other 11 months) | 2023-10 to 2026-09 | CC BY 4.0 | voivodeship | `nights_YYYY_MM` (36 fields) | Establishments with 10 or more beds. BDL publishes no powiat or gmina monthly series (levels 5 and 6 are empty). A month appears about two months after it ends. |
| `pl_air_hourly` | GIOŚ | Hourly PM2.5 (1-hour automatic positions): archive file "Wyniki pomiarów z 2025 roku" (`2025_PM25_1g.xlsx`) for December 2025; API `archivalData/getDataBySensor` for January and February 2026; station list `station/findAll`; station metadata archive file | https://powietrze.gios.gov.pl/pjp/archives (file "Wyniki pomiarów z 2025 roku"); https://api.gios.gov.pl/pjp-api/v1/rest/archivalData/getDataBySensor/{sensor}?dateFrom=2026-01-01%2001:00&dateTo=2026-03-01%2000:00 | 2025-12-01 to 2026-02-28 | Public sector information; reuse must name GIOŚ (API terms) | station points | `pm25` (168 hourly values of the smog week), `max`, `mean`, `hours_with_data`; the week, its ranking and the daily national means | API data are not verified in real time. Manual (24-hour) samplers are left out. Stations without coordinates are left out. |

## Lenses built from them

| Item | Axis | Level | Rule |
|---|---|---|---|
| Tourist nights by month | month, 36 steps | voivodeship | Nights in a month / residents on 2025-12-31; log scale, 2nd to 98th percentile of all month-voivodeship values. |
| Smog week | hour, 168 steps | hex | Inverse-distance-weighted mean (power 2) of the stations within 40 km that report the hour; empty beyond 40 km. |
| Presidential vote over time | year: 2015, 2020, 2025 | gmina (hex) | The three runoff lenses share one ramp and domain; the browser blends colours between runoffs and shows numbers only for runoff years. |
| Population over time | year: 2015 to 2025, June 2026 | hex | `timeline.json`, unchanged. |

## Spot checks

- Tourist nights: Małopolskie January 2026 = 1,381,155 nights (BDL variable 201916). The sum of the 16 voivodeships equals the BDL total for Poland: July 2025 13,757,897 and July 2026 14,508,483 nights (`unit-level=0` request).
- Smog peak: Łomża, ul. Sikorskiego (PdLomSikorsk, sensor 32442), 503.1 ug/m3 in the hour 23:00-24:00 of 2026-01-20 (GIOŚ stamp 2026-01-21 00:00). A separate narrow API request returned the same value and the hours around it (284.1, 340.0, 413.9, 503.1, 413.4, 222.1). PM10 at the same station in that hour: 509.5 (PM2.5 below PM10, as it must be). The station's 24-hour gravimetric PM2.5 sampler (sensor 4081) gives 189.2 for 2026-01-20 and 200.3 for 2026-01-21; the hourly means of those days are 202.5 and 216.6 (automatic analysers read about 7% higher here).
- Other station maxima in the week: Żywiec, ul. Kopernika 407.4; Katowice, ul. Dudy-Gracza 214.9; Kraków, ul. Bulwarowa 207.8; Gdańsk, ul. Powstańców Warszawskich 172.7; Warszawa, ul. Bajkowa 106.8. The national hourly mean peaks at 96.6 in the hour 22:00-23:00 of 2026-01-21.

## Looked for and not used

- Tourist nights by powiat or gmina per month: BDL P2882 is voivodeship only. Spreading the voivodeship season over the annual powiat values would be a model, not a published figure.
- GIOŚ `archivalData/getDataForAllStations` (all stations, up to 31 days): it has no pollutant filter, so one week of all pollutants is about 480 pages. `getDataForAllStationsByYearAndVoivodeship` with `pollution=PM2.5` is also too many pages at 2 requests per minute.
- GIOŚ modelled concentration maps (`concentration/getDistributionsOfConcentrationsMap`): annual indicators only, no hourly field.

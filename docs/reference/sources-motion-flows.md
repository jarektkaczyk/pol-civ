# Motion-flow sources: power grid, migration, money for local governments

## Conclusions

- 3 sources feed 3 lazy files for the motion layers: `pl_power_pse` -> `power.json`, `pl_migration_od` -> `migration.json`, `pl_local_finance_flows` -> `money.json`.
- Power: PSE publishes generation by fuel, wind, solar, demand and cross-border flows every 15 minutes through an open API with CORS `*`. One request returns a whole day (`$first=2000`). The snapshot is the newest complete day (2026-11-26, 96 quarters); the browser asks PSE for today with the same request.
- 9 border lines from OpenStreetMap cover all 6 PSE neighbours: Germany 2 (Krajnik-Vierraden, Mikułowa-Hagenwerder), Czechia 2 (a 400 kV double circuit, ČEPS refs 444 and 449; 220 kV Bujaków-Lískovec), Slovakia 1 (Krosno-Lemešany), Ukraine 2 (Rzeszów-Chmielnicka 400 kV, Dobrotvir-Zamość 220 kV), Lithuania 1 (LitPol Link), Sweden 1 (SwePol HVDC cable, followed to the map edge).
- Migration: GUS BDL P1358 gives the full 16 x 16 voivodeship matrix for every year 1995-2025 in 18 requests. Mazowieckie 2025: 20,245 arrivals, 10,831 departures, net +9,414, the same as BDL "saldo migracji" (P1956, variable 72198).
- Money: the Ministry of Finance file for 2026 lists 2,807 units (2,411 gminas, 66 cities with powiat rights, 314 powiats, 16 voivodeships). The gmina totals equal the ministry's letter to the gminas to the zloty (subsidy 26,353,434,072 PLN, PIT 88,138,305,070 PLN, CIT 3,176,075,547 PLN).
- The layers "Power now", "Migration" and "Money for local governments" (`web/js/ext/power`, `migration`, `money`) read these files; the power layer first asks PSE for today (`api.raporty.pse.pl` is in the app's CSP `connect-src`).
- The wealth correction is not a payment into an equalisation pot. Under art. 32 of the act of 1 October 2024 it cuts the rich unit's own general subsidy, then its PIT share (voivodeships: CIT first). 294 units have one, 4,672,194,662 PLN in total; Warszawa 941,414,099 PLN.

## Next steps

| Date (2026) | Owner | Step |
|---|---|---|
| 12-01 | lead | Add `pl_power_pse` (monthly) and `pl_migration_od` (yearly, in June) to `scripts/refresh/plan.py`; keep `pl_local_finance_flows` static until the 2027 final file (see Refresh). |
| 12-07 | Jarek | Ask PSE for written reuse terms for the API data (no licence text found; `www.pse.pl` did not resolve from the build machine). |

## Critical learnings

- PSE accepts `$first=N` (not `$top`) and returns the whole day in one page; without it the API pages 100 rows at a time with a `$after` cursor. `$select` and `$orderby` work too.
- PSE `przeplywy-mocy` has two sections per neighbour (`DE-PL`, `PL-DE`). PSE's report page: import into Poland is "+", export from Poland is "-". Both can be non-zero in one quarter; the net is their sum.
- `his-gen-pal` (generation by fuel) is not in PSE's endpoint map (`api.raporty.pse.pl/EndpointsMap.pdf`) and not in the report site. Its codes are the ENTSO-E PsrType codes (code list v36); `B19` equals `his-wlk-cal` `wi` in most quarters, so values are MW.
- PSE data for day D is complete from about 03:00 on day D+1 (Warsaw time). Today's data lags by a few hours.
- BDL `by-variable` without a `year` parameter returns every year in one request. The value key is `val`, not `value`.
- 47 gminas in the MF file still carry the rural type digit (2) although they became towns (3) on 2026-01-01; the source moves them to the register code.
- Overpass answered slowly or with 502 (about 1 to 2 minutes per 1-degree tile on 2026-11-27); the 31 tiles are cached and `--force` does not re-fetch them. A failed tile does not stop the others; fetch again to fill it.
- Natural Earth 1:10m puts border substations on the wrong side (Hagenwerder sits about 0.5 km west of the Neisse). A crossing therefore accepts a line end on the far side as well as 1.5 km depth.
- The Czech 400 kV crossing has no OSM name on either side near the border (refs `444;449`); its `name` is null.

## Refresh

| Source | Cadence | Why |
|---|---|---|
| `pl_power_pse` | monthly | The snapshot is the fallback day; the live layer reads today from PSE. A new fetch takes the newest complete day (3 requests). OSM tiles stay cached. |
| `pl_migration_od` | yearly (June) | GUS adds one year to P1358 each spring. Re-fetch with `--force` (18 BDL requests). |
| `pl_local_finance_flows` | never until the 2027 final amounts | The 2026 amounts are final. When MF publishes the 2027 final file (after the 2027 budget act), change `URL` and `YEAR`. |

## Sources

| id | publisher | dataset | URL | vintage | licence | level | fields | caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_power_pse` | PSE S.A.; OpenStreetMap | Reports `his-gen-pal`, `his-wlk-cal`, `przeplywy-mocy`; OSM power lines of 220 kV and more | `https://api.raporty.pse.pl/api/<report>?$filter=business_date eq '<day>'&$first=2000`; Overpass API | PSE business day 2026-11-26 (96 quarters, 13 production types, 12 sections); OSM 2026-11-27 (9 crossings) | PSE: none published (public sector information, cite PSE S.A.); OSM ODbL 1.0 | country series; points (interconnector crossings) | generation by ENTSO-E code (MW), `wi`, `pv`, `demand`, `swm_p` + `swm_np`, flows per section (MW, + import); interconnector name, voltage, HVDC flag, path (Polish side first) | Flows are physical flows on trading sections without local 110 kV exchange. Lines to Belarus and Russia carry no PSE section and are left out. Crossings use Natural Earth 1:10m borders and a 1.5 km margin. |
| `pl_migration_od` | GUS | BDL P1358 "Migracje na pobyt stały międzywojewódzkie wg kierunku", variables 3798-3813 and 79243 | `https://bdl.stat.gov.pl/api/v1/data/by-variable/<id>?unit-level=2` | 1995-2025 | CC BY 4.0 | voivodeship pairs (240 per year, 7,440 flows) | persons per origin and destination; in, out, net for 2025 | Variable = destination, unit = origin (checked: column sums = BDL registrations, row sums = BDL total). Permanent residence only; moves inside a voivodeship and abroad are not included. |
| `pl_local_finance_flows` | Ministry of Finance | "Dochody jednostek samorządu terytorialnego na 2026 r." (sheet "Zestawienie") | `https://www.gov.pl/attachment/23e9b124-8545-4178-ab54-81a9df16ace6` (page linked in the source) | 2026, final (budget act for 2026; MF: unchanged from the letters of 2025-10-14) | Public sector information; gov.pl page text CC BY-SA 4.0 | gmina (2,477), powiat (314), voivodeship (16) | see the column table below | Cities with powiat rights are one row for both roles, keyed by their gmina code. "KWOTA KALKULACYJNA" is not used. |

### MF columns used

| field | ministry's column | meaning |
|---|---|---|
| `pit_calculated` | "Dochód PIT naliczony na 2026 r." | Share in personal income tax as calculated (art. 11), before the wealth correction. |
| `cit_calculated` | "Dochód CIT naliczony na 2026 r." | Share in corporate income tax as calculated (art. 12), before the wealth correction. |
| `needs_total` | "Potrzeby finansowe" | Financial needs (art. 23), the sum of the five parts below. |
| `needs_equalising` | "potrzeby wyrównawcze" | Equalising needs (art. 24). |
| `needs_ecological` | "potrzeby ekologiczne" | Ecological needs. |
| `needs_development` | "potrzeby rozwojowe" | Development needs. |
| `needs_education` | "potrzeby oświatowe" | Education needs. |
| `needs_supplementary` | "potrzeby uzupełniające" | Supplementary needs (art. 30). |
| `wealth_correction` | "Korekta z tytułu zamożności" | Art. 32: half of the excess of income per adjusted resident over 120% of the category's figure; cuts the subsidy first, then PIT (then CIT; voivodeships CIT then PIT). |
| `pit_due` | "PIT należny" | PIT share due after the correction. |
| `cit_due` | "CIT należny" | CIT share due after the correction. |
| `subsidy_due` | "Subwencja należna" | General subsidy due after the correction. |
| `total_due` | "RAZEM" | PIT + CIT + subsidy due. |

## Looked for and not used

| Dataset | Reason |
|---|---|
| PSE terms of use | The API, `raporty.pse.pl` and its script bundle publish no licence. The reuse page `https://www.pse.pl/bip/ponowne-wykorzystanie-informacji-publicznej` (linked from the report site) did not resolve from the build machine (DNS for `www.pse.pl` and TLS for `pse.pl` failed). A web search found no terms. |
| Powiat origin-destination migration | BDL P1356 has only in and out totals per powiat, no pair matrix. |
| Janosikowe payments (wpłaty do części równoważącej) | The act of 1 October 2024 (art. 120) repealed the act of 13 November 2003 that set these payments; the 2026 file has the wealth correction instead (above). |
| MF 2027 planned amounts | Published (`gov.pl/attachment/0d0546bf-b295-4e7f-870f-200bbc1bfb87`) but planned, from the 2027 budget bill, and without the correction column. |

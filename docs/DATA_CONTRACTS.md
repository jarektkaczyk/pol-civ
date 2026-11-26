# Data contracts (v2)

The pipeline (Python) and the browser (web/js) agree on these files in `web/data/`. Change a contract here first, then on
both sides. All coordinates are **map km**: Albers equal-area, origin top-left, y **down** (see `pipeline/core/geo.py`).
Per-cell arrays have length `grid.cols * grid.rows`, with index `row * cols + col` (pointy-top, odd-r layout, see
`pipeline/core/hexgrid.py` ⇄ `web/js/hex.js`). `null` always means "no data". Never write `0` as a stand-in for "unknown".

## Pipeline conventions

* **Sources** (`pipeline/sources/*.py`) are discovered automatically: any `Source` subclass with `info = SourceInfo(...)`.
  `process()` returns a dict. It may include `"vintage"` (str) and `"_files"` (list of raw-file paths relative to
  `data/raw/<id>/` that this processing actually used; the Almanac cites only those).
* **Builders** (`pipeline/build/*.py`) are discovered automatically: a module with `REQUIRES`, `PRODUCES` and `build()`.
  They run in dependency order. Interims made by builders start with `_`. Helpers without `build()` (e.g. `yields.py`) are fine.
* The **`_world` interim** (made by `world`) holds: `grid`, `projection` (`MapProjection` kwargs plus the Albers
  parameters), `owner`, `county`, `county_samples` (7 gmina indices per Polish land cell, `[]` for other cells; sample 0 =
  centre), `powiat` (per cell: index into `powiaty`, -1 if none; the powiat of the cell's gmina), `states` (TERYT
  2-digit voivodeship codes, same order as world.json states), `counties` (TERYT 7-digit gmina codes, same order as
  world.json counties), `powiaty` (TERYT 4-digit powiat codes, sorted), `water`, `cover`, `pct` (same as world.json),
  `notes` (code changes between the boundary year and the register year) and `gminy_without_samples`
  (`[{code, name, reason}]`: gminy that no sample point hits). Builders that need to know whether a cell is Polish land
  must use `owner[cell] >= 0`. The gmina of a cell is `counties[county[cell]]`; its powiat is the first 4 digits.
* Python is **standard library only**. Downloads go through `Source.download()` (or `Source.download_prefix()` for the
  leading block of a big sorted file), which cache them and record provenance in `data/raw/<id>/manifest.json`;
  `Source.discard(rel_path)` forgets a cached file that turned out to be bad. All three wrap `core.fetch`.
* Under `--offline` (`core.fetch.OFFLINE`, `Source.offline`) sources skip discovery requests and use the newest complete
  cached data; a download of a file that is not cached raises `OfflineError`.
* **Builder checks.** Any module in `pipeline/build/` may define `check(web_dir: Path) -> list[(level, message)]`, level one
  of `PASS`, `NOTE`, `WARN`, `FAIL`. `pipeline check` discovers and runs them after its own checks (section "builder
  checks", each line prefixed with the module name), so a new builder never edits `pipeline/check.py`. Rules: read only
  `web_dir` (tests point it at a tiny synthetic dataset); report a **missing output as a NOTE** (never WARN/FAIL: the unit
  tests run every discovered check against a dataset without your files); a check that raises is reported as a FAIL.
  Validate your file's shape against this document (keys, types, null rules, cell ranges against world.json) and add a
  short data-quality summary (counts, coverage) as PASS/NOTE lines.
* **ACS interims.** `acs_1yr` keeps every estimate line (`<TABLE>_<line>`, e.g. `C24010_007`) of its tables for the nation
  (`geos["0100000US"]`), the states (`geos["0400000USss"]`) and every CBSA (`cbsa["<5-digit code>"]`): `b01003 c24030 b19025
  b19013 b25064 b25077 b23025` plus, for citizens, `c24010` (occupation; male lines 002-037, female = male + 36), `b01001`
  (age; male 003-025, female = male + 24), `b01002` (median age), `c08301` (commute), `c15003` (education 25+) and `b05002`
  (place of birth). Sexes are **not** summed in the interim: builders add male + female lines. Census leaves some small
  CBSAs out of a table entirely (C24010 has 520 of 536 CBSAs, C08301 525, B05002 535): the CBSA's record then simply lacks
  those keys (treat as null). `acs_5yr` (`geos["0500000USsscc"]`, counties) adds `b21001` (veterans: `B21001_001` civilian
  population 18+, `_002` veterans) and `b23025` (`B23025_001` population 16+, `_006` in the armed forces, by residence).

## world.json

```jsonc
{
  "version": 2,
  "grid": {"radius": 5, "cols": 82, "rows": 94},
  "width": 699.0, "height": 695.3, "margin": 0,
  "projection": {"min_x": -362.2, "max_y": 350.3, "margin": 0,       // map km = Albers km shifted (y down)
                 "lat1": 50.0, "lat2": 54.0, "lat0": 52.0, "lon0": 19.3},  // spherical Albers (pipeline/core/geo.py)
  "owner":  [int],   // -1 water, -2 foreign land (Germany, Czechia, Slovakia, Ukraine, Belarus, Lithuania, Russia),
                     // >=0 index into states (voivodeships)
  "county": [int],   // index into counties (gminy), -1 if none
  "elev":   [int],   // metres. Land: mean of land samples only (ETOPO 2022 15", >= -30 m). Water: mean of the hex's
                     // samples below sea level (its depth, <= 0); lakes: min(mean, 0); -50 where ETOPO has no samples
  "elev_max": [int], // metres, the highest land sample in the hex (0 for water); the art uses it for snow
  "water":  [int],   // 0 land, 1 open sea, 2 coastal water (next to land, shallower than 40 m, or a lagoon), 3 lake
  "relief": [int],   // 0 flat, 1 hills, 2 mountains, 3 peaks (summits above the tree line). 0 for water.
                     // Rules in tables.relief (standard deviation 28 m hills, 110 m or mean 750 m mountains,
                     // highest sample 1,450 m peaks); a hill hex whose lower 60% of samples is flat lowland is eased
  "cover":  [int],   // land-cover id (see tables.cover). 0 = none (water, no WorldCover land points).
                     // Foreign land has a cover class too (for the art), but its pct stays 0
  "pct": {           // share of the cell's land samples, 0..100 ints (Polish cells; 0 elsewhere)
    "forest": [int], "crop": [int], "pasture": [int], "grass": [int], "shrub": [int],
    "wetland": [int], "developed": [int]
  },
  "tables": {
    "water":  [{"id": 0, "name": "Land"}, {"id": 1, "name": "Open sea", "color": "#1d3f63", "rule": "..."}, ...],
    "relief": [{"id": 0, "name": "Flat", "rule": "..."}, ...],
    "cover":  [{"id": 1, "key": "forest_deciduous", "name": "Deciduous forest", "color": "#4f7a35", "worldcover": [10], "rule": "..."}, ...],
    "notes":  {"water": "...", "relief": "...", "cover": "..."}
  },
  "states":   [{"fips": "12", "abbr": "MA", "name": "Małopolskie"}],   // the 16 voivodeships, by TERYT code
  "counties": [{"geoid": "1261011", "name": "Kraków", "powiat": "1261", "type": "urban"}],  // gminy, by TERYT7
  "rivers":   [{"name": "Wisła", "rank": 1, "upland_km2": 192632, "dis0_m3s": 202.5, "dis_m3s": 1102.6,
                "pts": [x0, y0, x1, y1, ...]}],
  "lakes":    [{"name": "Łebsko", "area_km2": 74.2, "rings": [[x0, y0, x1, y1, ...], ...]}],
  "spits":    [{"area_km2": 34.1, "rings": [[x0, y0, ...]], "foreign": true}]
}
```

* **Units.** `states` are the voivodeships: `fips` is the TERYT 2-digit code, `abbr` the two-letter ISO 3166-2:PL
  code used until 2018 (DS, KP, ... ZP), `name` the Polish name. `counties` are the gminy in force in the newest
  register year (2026: 2,479), `geoid` the TERYT 7-digit code (with the type digit), `powiat` its TERYT 4-digit code,
  `type` one of `urban`, `rural`, `urban-rural`. A gmina created after the boundary year (LAU 2024) is in the list but
  owns no hex (see `_world.gminy_without_samples`).
* **Cover ids (fixed):** 0 none, 1 forest_deciduous, 2 forest_evergreen (conifer), 3 forest_mixed, 4 scrub,
  5 grassland (mountain meadows, hexes at 900 m or more), 6 pasture (meadows and pastures), 7 cropland, 8 wetland,
  9 urban (built-up), 10 barren, 11 ice. Dominant cover = the largest WorldCover group among the land points; a cell is
  **urban** when WorldCover built-up (50) is 28% or more of its land points. A forest cell's type (deciduous, conifer,
  mixed) is the most common Copernicus forest type at its tree points. `pct.pasture` holds WorldCover grassland below
  900 m, `pct.grass` grassland and moss at 900 m or more.
* **`rivers`**: HydroRIVERS main stems (a river from its source to where it joins a larger one, following the larger
  catchment at each confluence) whose catchment at the mouth is 1,500 km2 or more, clipped to the map. Each reach is
  named after the Natural Earth river (Polish name where it has one) that runs within 3 km of most of its points, and a
  main stem is split where the name changes, so the lower Odra (which carries more Warta water) is the Odra. `pts`
  run source to mouth; `dis0_m3s` and `dis_m3s` are the long-term mean discharge at the first and last point,
  `upland_km2` the catchment at the last point, `rank` 1 (largest) to 9 from `dis_m3s`
  (`round(9 - 2.6 * log10(m3/s))`). `name` is `null` where no Natural Earth river matches.
* **`lakes`**: inland water bodies of ESA WorldCover (permanent water pixels, 1/375 degree) of 1 km2 or more in Poland
  (4 km2 or more abroad), that do not touch the sea and are not long thin river stretches; smoothed outlines in map km,
  holes (islands) included, fill even-odd. `name` from Natural Earth where its lake contains the lake, else `null`.
  Lakes too small for a lake hex still show on the map this way (the Masurian and Pomeranian lake districts).
* **`spits`**: Polish gmina and foreign country land (LAU, Natural Earth) that lies inside sea hexes, rasterised at
  100 m, 0.4 km2 or more: the Hel Peninsula, the Vistula Spit, the Curonian Spit and the shore fringe. `foreign: true`
  when it lies outside Poland (drawn under the fog).

## cities.json

Every town with town rights on 1 January 2026 (1,026), sorted by population, descending. Built by
`pipeline/build/cities.py` from `pl_geo_places` (GUS Tabl. 20 and OSM place nodes) and the statistics interims.

```jsonc
{
  "id": "1261011",                // TERYT7 of the town: type 1 (its own urban gmina) or 4 (town of an urban-rural gmina)
  "name": "Kraków", "full": "Kraków, Małopolskie",  // towns without powiat rights: "Bochnia, powiat bocheński, Małopolskie"
  "states": ["MA"], "voivodeship": "12", "powiat": "1261", "gmina": "1261011",  // gmina: type 1 or 3
  "kind": "city",                 // "city" = city with powiat rights (66), else "town"
  "city_view": true,              // the City View opens: a city with powiat rights or a town of 20,000+ (204)
  "metro": true,                  // same as city_view (kept for the usaciv UI: false greys a row)
  "fua": "PL003F",                // metros.json id of the metro the town's gmina belongs to, or null
  "capital": false,               // Warszawa only
  "x": 407.6, "y": 565.7, "cell": 6279,   // true position (map km); banner cell (Polish land, unique where possible)
  "scope": "city",                // what the economic fields describe: "city" | "gmina" | "urban-rural gmina"
  "gmina_population": 816614,     // the gmina's population (differs from population for "urban-rural gmina")
  /* the economic shape below */
  "footprint": [6196, 6197, "..."],  // cells where 4 of 7 samples are the town's own gmina (type 1), plus `cell`
  "ranks": {"population": 2, "gdp": 2, "gdp_per_capita": 19, "growth": 10, "food": 2, "...": 1},  // among all towns;
                                  // gdp_per_capita = gdp / gmina_population (GDP covers the whole gmina)
  "peers": ["0264011", "..."]     // City View towns: the 5 other City View towns closest in population; others []
}
```

**Economic shape** (a town, a metro, a voivodeship and nation.json `nation`; built by `pipeline/build/yields.py`):

```jsonc
"population": 816614,                 // residents, GUS 31 Dec 2025 (a town: the town itself, GUS Tabl. 20)
"employed": 535510,                   // workers by employer seat, GUS 31 Dec 2025 (PKD table for whole powiaty)
"yields": {"food": 2343, "production": 75800, "gold": 1.19e11, "science": 142498, "culture": 23519},  // any may be null
"jobs": {"agriculture": 2343, "...": null},  // PKD sections A-S (keys in nation.json industries); {} below the powiat
"wage": 11297, "wage_exact": true,    // average gross monthly wage, PLN (powiat; a set of powiaty: worker-weighted mean)
"unemployment": 0.028, "unemployment_exact": true,  // registered rate, 0..1 fraction (exact for whole powiaty)
"pit_per_person": 6787.05,            // PLN: planned 2026 PIT revenue of the gminas / their residents
"gdp": 1.19e11, "gdp_year": 2023, "gdp_estimated": true,  // PLN; estimated = a share of a published total
"growth": 0.073, "growth_years": [2015, 2025],  // population change, see pipeline/build/growth.py
"pop_series": {"2015": 761069, "2020": 779966, "2025": 816614}  // or null
```

* **Yield rules** are in `yields.py` and in nation.json `yields[].description`: Food = PKD A, Production = B-F,
  Science = J + M, Culture = I + R (workers); Gold = GDP in PLN (nation 2025, voivodeships 2024, powiaty the NUTS 3
  GDP 2023 shared by wage bill, gminas their powiat's GDP shared by workers). Whole powiaty use the PKD sections;
  other gminas use the GUS three-sector gmina table and get Science and Culture as a share of their powiat's by
  service workers.
* **Growth**: `population(2025) / population(2015) - 1` for the same gmina code (both GUS, each on its own year's
  borders: Opole 2017 and the 2025 splits of Kamienica and Supraśl show their border change). Null for a town inside an
  urban-rural gmina (no town series) and for the two gminas created in 2025. |growth| above 2.0 is nulled as an error.

### metros.json

`{"version": 1, "rule": "...", "ref": "https://metropoliagzm.pl/", "vintage": "...", "metros": [metro]}`, sorted by
population. A metro is a Eurostat functional urban area (`pl_geo_fua`, LAU 2025 correspondence) with two published
merges: Trójmiasto (`PL006F` = FUAs PL006F Gdańsk and PL053F Gdynia) and Górnośląsko-Zagłębiowska (`PL010F` = FUAs of
Katowice, Gliwice, Tychy, Dąbrowa Górnicza). Each metro: `id` (FUA code), `name`, `full`, `fuas`, `states`, `metro:
true`, `capital`, `core` (the largest member town's id), `cities` (member town ids), `x`, `y`, `cell` (the core town's),
the economic shape (sums over member gminas; `wage` and `unemployment` are population-weighted means of their
powiaty), `gminas` (TERYT7), `footprint` (cells with 4 of 7 samples in member gminas, plus `cell`), `ranks`, `peers`.

## states.json

The voivodeships. A list in the same order as world.json `states`, each with the economic shape of a city (see
cities.json) plus `fips` (TERYT 2-digit code), `abbr`, `name`, `ranks: {yieldKey: 1..16}` (1 = largest), and
`label: {x, y, angle, size}`. The `states` builder fills the economic fields (below). `label` is a suggested anchor for the voivodeship name: `angle` in degrees
clockwise, `size` a suggested font height in map km, clamped to 8..40 km.

Also, per voivodeship:

```jsonc
"capitals": [{"gmina": "0461011", "name": "Bydgoszcz", "role": "voivode"},
             {"gmina": "0463011", "name": "Toruń", "role": "sejmik"}],   // role "both" where one city has both seats
"capitals_ref": "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU19980960603",
"cells": 278,      // hexes the voivodeship owns
"land": {"forest": 0.312, "crop": 0.578, "pasture": 0.051, "grass": 0.0, "shrub": 0.0, "wetland": 0.002,
         "developed": 0.019},   // or null
"energy": null     // filled by the energy builder (shape below)
```

* **`capitals`**: the seats of the voivodeship authorities (1998 act on the three-tier division, art. 1). Kujawsko-
  Pomorskie and Lubuskie have two: the voivode in Bydgoszcz and Gorzów Wielkopolski, the sejmik in Toruń and Zielona
  Góra. Each `gmina` is checked against the TERYT register at build time.
* **`land`**: land-cover shares as **0..1 fractions**: the mean of world.json `pct` over the voivodeship's cells
  (`owner == index`) that have land-cover samples (`cover > 0`). Keys are world.json `pct` keys. WorldCover counts
  every patch with tree canopy as tree cover, so `forest` (about 42% for Poland) is higher than the official forest
  area (GUS, about 30%).
* **`energy`** (when built): `{"unit": "MW", "total", "by_type", "sites", "note"}`: MW summed from resources.json
  items in the voivodeship, for every resource type with unit `MW`; it counts only the mapped sites, so it is not the
  voivodeship's total generating capacity, and `note` says so.
* **Economic fields** (`pipeline/build/states.py`): the economic shape of cities.json over the voivodeship's whole
  powiaty (PKD jobs, exact unemployment from the powiat counts), with Gold = the published GDP 2024 (Eurostat NUTS 2;
  Mazowieckie = PL91 + PL92, `gdp_estimated: false`). `wage` is the worker-weighted mean of its powiaty (`wage_exact:
  false`). `ranks`: {yield key: 1..16}, 1 = largest.

## nation.json

```jsonc
{
  "vintage": "GUS population 31 December 2025; ...", "year": 2025,
  "gdp_vintage": "Eurostat national 2025; ...",
  "years": {"population": 2025, "workers": 2025, "gdp_nuts3": 2023, "gdp_voiv": 2024, "gdp_nation": 2025,
            "wage": 2026, "unemployment": 2026, "pit": 2026},   // the year of each figure (shown in the Almanac)
  "nation": { /* economic shape: population, GDP 2025, unemployment and wage are the published national figures */ },
  "yields": [{"key": "food", "icon": "y-food", "emoji": "🌾", "label": "Food", "color": "#7fbf3f",
              "unit": "workers|pln", "industries": ["agriculture"], "description": "..."}],
  "industries": {"agriculture": "Agriculture, forestry & fishing"}   // PKD section keys (yields.py SECTIONS)
}
```

## lenses.json

Produced by `pipeline/build/lenses.py` from the per-gmina metrics in `pipeline/build/counties.py` (`METRICS`), so a
lens, counties.json and the Explorer show the same numbers.

```jsonc
{
  "vintage": "...",
  "groups": [{"id": "people", "name": "People"}, {"id": "prosperity", "name": "Prosperity"},
             {"id": "knowledge", "name": "Knowledge"}, {"id": "life", "name": "Daily life"}, {"id": "faith", "name": "Faith"},
             {"id": "vote", "name": "Vote"}, {"id": "air", "name": "Air"}, {"id": "hazards", "name": "Hazards"},
             {"id": "land", "name": "Land"}],
  "lenses": [{
    "id": "income", "group": "prosperity", "name": "PIT revenue per person", "icon": "l-income", "emoji": "💰",
    "unit": "zł per resident", "format": "int|pln|pct|float|years|category",   // pct values are 0..1 fractions
    "scale": "log|linear", "domain": [1900, 5500], "ramp": ["#..."], "higher_is": "good|bad|neutral",
    "source": "pl_stats_prosperity", "description": "...",
    "values": [number|null],       // per cell; null off Polish land
    "note": "Per powiat."          // optional legend caveat: the unit level when it is not the gmina, and known limits
  }]
}
```

* A hex value is the population-weighted mean of the gminas of its 7 samples (each gmina's population shared over
  its sample hits); a gmina that no sample hits is placed whole in the hex under its LAU centre. Density is people
  per km² of the hex's land. Categorical lenses (`sejm`, `flood`) take the category with the most people. Land
  lenses read the hex's own WorldCover shares. Domains are the 2nd-98th percentile of hexes, except `vote`
  (fixed `[0.2, 0.8]`, a diverging teal-parchment-amber ramp centred on 50%: neutral hues, not party colours).
* Lenses (id: metric, level): density, age (median age interpolated from 5-year groups), growth (2015-2025, signed
  pct), migration, elderly, births (gmina); ukrainians (PESEL UKR per 1,000, powiat); income (PIT per person, gmina);
  wage, unemployment (powiat); dwellings (voivodeship); higher_ed (NSP 2021, powiat, null where GUS has no figure);
  students (gmina with a university, else null); tourism (voivodeship); doctors (powiat); life_f, life_m
  (voivodeship); catholic, no_religion (NSP 2021, gmina); mass (dominicantes, diocese of the gmina seat); vote
  (Nawrocki share, 2025 second round), turnout (gmina); sejm (largest committee 2023, category); pm25 (nearest GIOŚ
  station within 25 km of the gmina centre, else null); flood (2024 flood disaster area, category); forest,
  farmland, developed (hex). Missing source tables leave a lens out; it returns on the next build.
* `lenses.py` defines `check(web_dir)`: required notes, the neutral vote ramp, coverage per lens.

## resources.json

```jsonc
{
  "version": 1,
  "vintage": {"plants": "...", "renewables": "...", "oil_gas": "...", "mines": "..."},
  "sources": ["pl_energy_plants", "pl_energy_res", "pl_energy_oilgas", "pl_mines"],
  "types": [{"id": "hard_coal_plant", "name": "Hard-coal power plant", "category": "energy|mineral|agri",
             "emoji": "C", "icon": "r-coal_plant", "color": "#434343",
             "unit": "MW", "description": "...", "source": "pl_energy_plants"}],
  "items": [{"id": "plant:way/1583424363", "type": "nuclear", "name": "Lubiatowo-Kopalino nuclear power plant",
             "value": 3750, "status": "planned", "operator": "Polskie Elektrownie Jądrowe", "detail": "...", "year": null,
             "ref": "https://...", "x": 265.4, "y": 38.3, "cell": 441,
             "gmina": "2215042", "powiat": "2215", "state": "PM", "cbsa": null}],
  "summary": {
    "note": "Totals cover the mapped sites only...",
    "national": {"lignite_plant": {"count": 3, "value": 7912.8, "unit": "MW",
                   "by_status": {"operating": {"count": 3, "value": 7912.8}}}},
    "states": {"LD": {"lignite_plant": {"count": 1, "value": 5472, "unit": "MW"}}}
  },
  "renewables": {"as_of": "2026-09-30", "source": "pl_energy_res", "level": "powiat", "unit": "MW",
                 "fields": [{"key": "wind_mw", "label": "Wind", "unit": "MW", "year": 2026}],
                 "rows": [["0201", null, 14.164, "..."]]},
  "national_installed": {"mw": 77331, "date": "2025-12-31", "publisher": "...", "ref": "https://..."},
  "rules": {"plants": "Rule: ...", "oil_gas": "Rule: ...", "mines": "Rule: ..."}
}
```

`items` contains the mapped plants of 100 MW or more, solar plants of 50 MW or more, curated Baltic offshore wind
projects, the planned Lubiatowo-Kopalino nuclear site, oil and gas sites, refineries, and the mines in `pl_mines`.
Offshore wind can use a water cell;
other items use a Polish land cell. Mine types use unit `sites` and value 1 per mapped site. `output`, `output_unit`
and `year` carry published output; missing output stays `null`.
`summary.by_status` separates operating,
under-construction and planned capacity. `renewables` keeps every published URE powiat row and every source field;
missing capacity stays `null`.

## counties.json

One row per gmina (world.json `counties` order, 2,479), column-oriented, built by `pipeline/build/counties.py`:

```jsonc
{
  "vintage": "...",
  "fields": [{"key": "pit", "label": "PIT revenue per person", "format": "pln", "unit": "zł per resident",
              "higher_is": "good", "source": "pl_stats_prosperity", "description": "...", "level": "gmina|powiat|voivodeship|diocese|station",
              "group": "prosperity"}],
  "columns": ["geoid", "name", "type", "powiat", "state", "population", "area_km2", /* every METRICS key */,
              "workers", "gdp", "air_station", "cbsa", "cell"],
  "rows": [["1261011", "Kraków", "urban", "Kraków (city)", "MA", 816614, 326.87, ...]]
}
```

`geoid` = TERYT7, `type` urban | rural | urban-rural, `powiat` its label, `state` the voivodeship abbr. A metric
published per powiat, voivodeship or diocese repeats its unit's value and the field `description` says so.
`cbsa` = the metros.json id (or null), `cell` = the hex nearest the gmina's centre among the hexes its samples hit
(null for gminas no sample hits). `gdp` = the gmina's share of its powiat's GDP (see Gold). Categorical columns
(`sejm_2023`, `flood_2024`) are `text` category ids.

### powiaty.json

The same column format for the 380 powiaty: `code`, `name`, `state`, `population`, `area_km2`, a subset of the
metrics (powiat-level ones exact, gmina-level ones the population-weighted mean of the powiat's gminas, density and
growth recomputed from sums), `workers` (PKD total), `y_food` … `y_culture` (the powiat's yields) and `cell`.

## Optional map-layer files

Every file below is **optional**: the app and `check` work without it, and each owning builder validates its own file with
a `check(web_dir)` (see Pipeline conventions). Shared rules:

* Top level always has `"version": 1`, `"vintage"` (a human string, or `{part: string}`), and `"sources": [source ids]`
  (sources.json ids, so the Almanac can cite them).
* `cell` = a world.json cell index (pointy-top odd-r, `row * cols + col`); a site's `cell` is a US land cell (`owner >= 0`)
  unless stated. `x`, `y` = map km. `county` = 5-digit GEOID from world.json `counties` (or null), `cbsa` = a cities.json
  `id` (or null), `state` = postal abbr.
* Money is **US dollars** (not thousands or millions) unless the key says otherwise (`_musd`); shares are 0..1 fractions;
  `null` = unknown, never `0`. A value that is a **lower bound** (suppressed parts left out) says so (`lower_bound: true`
  or a `suppressed` count).
* Rules that pick things (districts, wonders, routes) are published inside the file as text (`rule` / `rules`) so the UI
  and the Almanac can quote them.
* **Loading** (browser): `infrastructure`, `military`, `wonders`, `trade` load eagerly right after the first frame (keep
  each **under ~300 kB**); `citizens`, `districts`, `disasters` load on demand with `app.loadData(name)`.

### citizens.json (lazy)

Per City View town, the citizen mix for the City View's person icons, built by `pipeline/build/citizens.py`.
Figures use largest-remainder rounding (each row's figures sum exactly to its `figures` count).

```jsonc
{
  "version": 1, "vintage": "...", "year": 2025,
  "sources": ["pl_stats_population", "pl_stats_labour", "pl_census_2021", "pl_foreigners"],
  "figures": {"workforce": 20, "age": 10, "sex": 10, "education": 10, "nativity": 10},
  "rows": {"workforce": "Workers by sector", "age": "Residents by age", "sex": "Residents by sex",
           "education": "Per 1,000 residents aged 13+ by education (census 2021)", "nativity": "Residents by origin"},
  "groups": {
    "workforce": [{"key": "farmer", "label": "Farming, forestry & fishing", "lines": "PKD A"}, "maker (B, C, D, E, H)",
                  "builder (F)", "clerk (G, K, L, N)", "engineer (J, M)", "scholar (P, R)", "healer (Q)", "service (I, O, S)"],
    "age": ["child 0-14", "young 15-29", "midlife 30-64", "elder 65+"],
    "sex": ["female", "male"],
    "education": ["bachelors (higher education)", "high_school (no higher education)"],
    "nativity": ["foreign_born (Ukrainians with PESEL UKR)", "born_in_state (other residents)"]
  },
  "rule": {"specialist_high": 1.5, "specialist_low": 0.67, "min_share": 0.01, "max_high": 4, "max_low": 2, "text": "..."},
  "national": { /* a row for Poland ("specialists": []); education is null (no national NSP share in the interim) */ },
  "cities": {"1261011": { /* a row */ }}   // every City View town id; null when no row has data
}
// a row: {"workforce": {"total", "counts", "shares", "figures", "scope"} | null, "age": {..., "median"} | null,
//         "sex": ..., "education": {..., "bachelors_plus"} | null, "nativity": {..., "foreign_born"} | null,
//         "specialists": [{"row", "key", "share", "national", "ratio"}], "reliable": true}
```

* Units: workforce, education and nativity describe the town's powiat (`scope` = the city itself for a city with
  powiat rights, else the powiat label); age and sex describe the town's gmina (the whole urban-rural gmina for a
  type-4 town). Education counts are per 1,000 residents aged 13+ (NSP 2021 share; total 1,000). Workforce groups
  are PKD sections, not occupations; the row is null when every section of a group is withheld. Gmina-level
  interims are matched on the first six TERYT digits (some sources still carry an old type digit).

### districts.json (lazy)

Districts and city badges of the City View towns, from location quotients (LQ) of PKD sections, built by
`pipeline/build/districts.py`. GUS publishes workers by PKD section per powiat: a town without powiat rights shows
its whole powiat (`scope`).

```jsonc
{
  "version": 1, "vintage": "...", "year": 2025,
  "sources": ["pl_stats_labour", "pl_stats_population", "pl_transport_ports", "pl_mines", "pl_soc_military"],
  "rule": {"min_lq": 1.25, "min_jobs": 1000, "min_share": 0.01, "specialty_lq": 3.0, "max_per_city": 5,
           "text": "...", "scope_note": "..."},
  "badges": [{"id": "port", "label": "Port city", "district": "harbor", "rule": "A seaport within 10 km ..."}],
  "catalog": [{"id": "campus", "name": "Campus", "icon": "d-campus", "color": "#4a7bd0", "sections": ["J", "M", "P"],
               "sub": {"J": "IT & telecoms", ...}, "badge": {"id": "scientific", "label": "Knowledge city", "labels": {"J": "Tech city"}},
               "description": "...", "caveat": null}],
  "industries": {"J": {"title": "Information & communication", "pl_emp": 547599}},
  "national": {"emp": 15125030},
  "cities": {"1261011": {
    "emp": 535510, "wage": 11297, "scope": "Kraków",
    "top": [{"pkd": "J", "emp": 74424, "lq": 3.84}],          // up to 8 sections by LQ (1,000+ workers)
    "districts": [{"id": "campus", "lq": 2.06, "emp": 193309, "share": 0.361, "sub": "J", "sub_lq": 3.84,
                   "sub_emp": 74424, "via": "broad|specialty", "strength": 99359, "suppressed": 0, "lower_bound": false}],
    "badge": {"id": "scientific", "rule": "tech", "label": "Tech city", "district": "campus", "basis": "rule",
              "text": "IT and telecoms: 3.8 times the national share of workers"} | null
  } | null}
}
```

Districts (fixed ids, in this order): campus (J, M, P), commercial_hub (G, K, L, N), industrial_zone (B, C), harbor
(H; only with a seaport within 10 km), theater_square (R), entertainment_complex (I), government_plaza (O), aqueduct
(D, E), encampment (no PKD sections: badge only). **Rule**: a district appears when its sections' LQ ≥ 1.25 with
≥ 1,000 workers or ≥ 1% of the powiat's workers, or one section alone has LQ ≥ 3 with ≥ 1,000 workers; ranked by
workers above the national norm; up to 5. A withheld section counts as absent (`lower_bound`). **Badges**, first rule
that holds: Capital city (Warszawa), Port city (seaport within 10 km), Copper town (copper mine or smelter within
15 km), Coal town (coal or lignite mine within 15 km), Refinery town and Auto city (published, not awarded: no
refinery dataset, no PKD division data per powiat), Tech city (J LQ ≥ 2 and ≥ 4% of workers), University town
(students ≥ 10% of residents), Spa town (official name with "Zdrój"), Tourist town (I LQ ≥ 2), Industrial town
(B + C LQ ≥ 1.5), Garrison town (a military unit or base within 5 km). null = diversified.

### infrastructure.json (eager)

Polish motorways, expressways and main railway lines rasterised onto hex links, plus ports and airports as sites.
`pipeline/build/infrastructure.py` reads the four `pl_transport_*` interims.

```jsonc
{
  "version": 1,
  "vintage": {"roads": "OpenStreetMap extract 2026-11-26", "rail": "...", "network": "...",
              "ports": "GUS and Eurostat 2025", "airports": "Eurostat 2025"},
  "sources": ["pl_transport_osm", "pl_transport_network", "pl_transport_ports", "pl_transport_airports"],
  "rules": {"roads": "...", "rail": "...", "ports": "...", "airports": "..."},
  "road_classes": [{"id": "motorway", "name": "Motorway"}, {"id": "expressway", "name": "Expressway"}],
  "rail_tiers": [{"id": "main", "name": "Main line"}, {"id": "secondary", "name": "Other mapped line"}],
  "roads": [[3721, 3722, 0, "A2"]],
  "rail": [[3721, 3845, 0]],
  "ports": [{"id": "port:PLGDN", "name": "Port of Gdańsk", "type": "seaport", "rank": 1,
             "cargo_kt": 75323.6, "international_kt": 71180.2, "teu": 2583139, "year": 2025,
             "status": "operating", "x": 321.0, "y": 85.0, "cell": 1021,
             "gmina": "2261011", "powiat": "2261", "state": "PM", "cbsa": null}],
  "airports": [{"id": "airport:EPWA", "name": "Warszawa-Chopin", "icao": "EPWA", "iata": "WAW", "rank": 1,
                "passengers": 24079757, "passengers_prev": 21256074, "freight_t": 146013.6, "year": 2025,
                "status": "operating", "x": 475.6, "y": 330.9, "cell": 3663,
                "gmina": "1465011", "powiat": "1465", "state": "MZ", "cbsa": null}],
  "totals": {"network": {}, "ports": {}, "airports": {}}
}
```

Links join neighbouring cells. A line is sampled every 2.5 km, and each cell pair appears once with its best class.
Road class 0 is an A-road or an unnumbered motorway link. Road class 1 is an S-road. Rail tier 0 marks CMK,
high-speed or 160 km/h links. Ports and airports use the closest Polish land cell and retain their true map position.
Missing traffic figures stay `null`.

### trade.json (eager)

The largest published rail freight flows between Polish voivodeships. The builder runs after infrastructure because
the drawn paths prefer mapped transport links.

```jsonc
{
  "version": 1, "vintage": "Eurostat road freight 2025, rail regional freight 2020", "year": 2020,
  "sources": ["pl_transport_freight"],
  "rule": "The 30 largest published rail freight flows between Polish voivodeships...",
  "path_note": "The source gives each shipment's origin and destination region, not its route...",
  "units": {"value_kt": "thousand tonnes"},
  "modes": [{"id": "rail", "name": "Rail"}],
  "national_kt": {"interregional_rail": 80569.8},
  "road_freight": {"level": "nuts3", "year": 2025,
                    "fields": [{"key": "loaded_kt", "label": "Loaded", "unit": "thousand tonnes", "year": 2025}],
                    "rows": [["PL213", 15515, 19152]]},
  "zones": [{"id": "02", "name": "Dolnośląskie", "short": "Dolnośląskie", "kind": "voivodeship",
             "states": ["DS"], "cities": [], "counties": 169,
             "anchor": {"cell": 4938, "x": 155.9, "y": 450.0, "city": null},
             "partners": [["30", 3940.1, "rail"]], "totals_kt": {"within": null, "other_zones": 19612.5}}],
  "routes": [{"a": "12", "b": "24", "rank": 1, "value_kt": 9046.9, "tons_k": 9046.9,
              "modes": {"rail": 1.0}, "top_mode": "rail", "dist_km": 105,
              "path": [6527, 6445, 6362, "..."]}]
}
```

The file contains 16 zones. The route rule keeps the largest 30 bidirectional pairs at least 100 km apart. Each path is
a neighbouring-cell chain and is a drawing aid. Eurostat does not publish a road origin-destination matrix. The 2025
road values stay as NUTS3 loading and unloading totals and never become invented routes.

### military.json (eager)

Built from `pl_soc_military`. One marker represents one garrison town and branch. The file also contains the main
training areas, national troop totals and the two named 2026 budget figures.

```jsonc
{
  "version": 1, "vintage": "Curated November 2026; MON March 2026; NATO July 2026",
  "sources": ["pl_soc_military"],
  "rule": "One map fort per garrison town and branch...",
  "rules": {"installations": "...", "tier": "...", "ranges": "..."},
  "caveats": "Installation-level personnel are not published...",
  "components": [{"id": "land", "name": "Land Forces"}, {"id": "air", "name": "Air Force"},
                 {"id": "navy", "name": "Navy"}, {"id": "territorial", "name": "Territorial Defence Force"},
                 {"id": "allied", "name": "US and NATO"}],
  "installations": [{"id": "garrison-joint-force-training-centre-jftc-allied", "name": "Bydgoszcz",
                     "component": "allied", "joint": false, "status": "act", "tier": "major",
                     "area_km2": null, "cells": null, "count": 4, "units": ["..."],
                     "source_ids": ["..."], "refs": ["https://..."], "voivodeship": "kujawsko-pomorskie",
                     "voivodeship_code": "04", "x": 275.7, "y": 224.5, "cell": 2492,
                     "county": "0461011", "state": "KP"}],
  "ranges": [{"id": "mil_centrum_szkolenia_bojowego_drawsko_poligon_drawski",
              "name": "Centrum Szkolenia Bojowego Drawsko (Poligon drawski)", "component": "land",
              "area_km2": 339.7, "cells": [1901], "cell": 1901, "x": 131.6, "y": 174.4,
              "state": "ZP", "county": "3203023", "garrison": "Drawsko Pomorskie",
              "ref": "https://...", "note": "33,968 ha"}],
  "states": {"DS": {"garrison_towns": 2, "units": 3, "bases": 0, "map_garrisons": 3}},
  "national": {
    "personnel": {"total_2025": 216271, "total_mid_2026": 220000, "professional": 156000,
                  "territorial_defence": 40000, "voluntary_service": 14600},
    "spending": {
      "budget_act": {"name": "The budget act", "total_pln": 124800000000, "pct_gdp": 3.0, "year": 2026},
      "with_support_fund": {"name": "The total with the Armed Forces Support Fund",
                            "total_pln": 200000000000, "pct_gdp": 4.81, "year": 2026},
      "nato_core": {"name": "NATO core defence expenditure", "total_pln": 193789000000, "pct_gdp": 4.68, "year": 2026}
    }
  },
  "cities": {}
}
```

The tier counts source entries in one town and branch. Four or more entries is `major`. Two or three is `base`.
One is `site`. Training areas have one point cell because the interim has no polygons. The budget values are PLN.

### wonders.json (eager)

Built from Polish heritage, park, university, transport and energy interims. It contains 34 selected cultural sites.

```jsonc
{
  "version": 1,
  "vintage": {"heritage": "...", "parks": "...", "universities": "...", "transport": "...", "energy": "..."},
  "sources": ["pl_soc_heritage", "pl_soc_parks", "pl_soc_universities", "pl_transport_ports",
              "pl_transport_airports", "pl_energy_plants"],
  "rules": [{"id": "unesco_property", "kind": "unesco", "text": "Every UNESCO World Heritage property..."},
            {"id": "national_park", "kind": "natural", "year": 2024, "text": "The six..."},
            {"id": "research_university", "kind": "university", "year": 2025, "text": "The six..."},
            {"id": "landmark", "kind": "landmark", "text": "Four stated national records..."}],
  "national": {"park_visits": 16390532, "park_visits_year": 2024, "national_parks": 23,
               "unesco_properties": 18, "memorials": 1},
  "wonders": [{"id": "whc_31", "name": "Auschwitz Birkenau German Nazi Concentration and Extermination Camp (1940-1945)",
               "short": "Auschwitz Birkenau German Nazi Concentration and Extermination Camp (1940-1945)",
               "kind": "memorial", "rule": "unesco_property", "rank": null, "curated": false,
               "metrics": {"inscribed": 1979, "category": "Cultural", "area_ha": 191.97},
               "ref": "https://whc.unesco.org/en/list/31", "component": "Auschwitz", "component_id": "whc_31-001",
               "x": 355.4, "y": 570.1, "cell": 6273, "cells": null,
               "county": "1213011", "cbsa": null, "state": "MA"}]
}
```

The list contains all 18 UNESCO properties, including one unranked `memorial`; 6 parks by 2024 visitors; 6 universities
by students among institutions with an A+ research category; and 4 record landmarks. Serial UNESCO properties use the
named component stored in the file. Consumer text must call the memorial a memorial or cultural site.

### disasters.json (lazy)

Built from `pl_soc_disasters`. It maps the administrative area declared after the September 2024 flood.

```jsonc
{
  "version": 1, "vintage": "Dz.U. 2024 poz. 1365 as amended", "sources": ["pl_soc_disasters"],
  "flood_2024": {
    "rule": "Every gmina named by the Council of Ministers' regulation...",
    "window": ["2024-09-16", "2024-09-25"],
    "gminas": {"columns": ["geoid", "declared", "partial", "date"],
               "rows": [["0201011", 1, 0, "2024-09-20"]]},
    "powiats": {"columns": ["teryt", "declared", "date"], "rows": [["0201", 1, "2024-09-20"]]},
    "cells": [null, 0, 1],
    "summary": {"gminas": 198, "powiats": 29, "partial_gminas": 1}
  }
}
```

`gminas.rows` follows `world.json` gmina order. `declared` is 1 for the 198 named gminas and 0 elsewhere. `partial` is 1
only for Małomice. `cells` is `null` outside Polish land, 1 in declared gminas and 0 in other Polish gminas.

## sources.json

A list of `{id, title, publisher, homepage, license, description, used_for, vintage, files: [{file, url, retrieved, sha256, bytes}]}`.
`files` lists only files the latest `process()` used (`_files`), or every manifest entry if the source didn't say. A file
saved by `download_prefix()` has a `partial` note in the manifest, and its `sha256`/`bytes` describe the saved part.

## Browser module boundaries (web/js)

* `world.js`: `prepareWorld(world, cities, extras) → w` with `w.grid`, `w.raw`, `w.stateColor[]`, `w.cityByCell: Map<cell, city>`;
  `applyLens(w, lens, band = null)` sets `w.colors`/`w.rgb`; exports `WATER = -1`, `FOREIGN = -2`.
* `camera.js`: `Camera` with `fit()`, `toScreen()`, `toWorld()`, `zoomAt()`, `panBy()`, `centerOn()`, `flyTo(x, y, scale, ms)`,
  `step(dt) → bool stillMoving`, `view()`.
* `render/*`: map drawing and banners. `main.js` owns input, state and wiring. `ui/*` owns DOM panels.
* The `state` object (owned by `main.js`, read by `render/*`): `cities`, `lens` (a lenses.json lens or null = terrain),
  `band` (`[t0, t1]` in normalised lens units 0..1, or null: cells outside are dimmed, see `applyLens`), `hoverCell`,
  `selectedCity` (a city object or null), `selectedState` (a state index, abbr, fips or `{index|abbr|fips}`, or null;
  resolved with `world.js` `stateIndex(w, ref)`), `showResources`.
* `render/snapshot.js`: `renderToCanvas(target, cam, w, state, nation, opts) → {cam, hits}` draws a full frame off-screen
  (share images, OG cards) without touching the on-screen cache. `target` is a canvas, OffscreenCanvas or 2D context;
  `opts`: `banners = true`, `overlay = true`, `dpr = 1`, `fit = "contain"|"cover"|"same"`, or an explicit `scale`, `x`, `y`.

## Browser extension API (window.__app; main.js "extension API", app/api.js)

Extensions live in `web/js/ext/<name>/index.js` and export `install(app)`; `ext/index.js` loads `cityView`, `advisors` and
`layers` (roads, rail, forts, ports, airports, wonders and trade routes). The API:

**Data.**
* `app.data.<name>`: the core files (`world`, `cities`, `states`, `nation`, `lenses`, `resources`, `sources`) are loaded
  before anything runs. Optional files: `undefined` until loaded, `null` when missing (404) or invalid.
* `app.loadData(name) → Promise<data | null>`: loads `data/<name>.json` once (cached promise; later calls return the same
  promise) and sets `app.data[name]`. Emits `"data"` `{name, data}` when it arrives. `infrastructure`, `military`,
  `wonders`, `trade` are requested automatically right after the first frame; `citizens`, `districts`, `disasters` (and
  `counties`) only when something calls `loadData`. `app.loadCounties()` = `app.loadData("counties")`.

**Static map layers** (art that belongs in the cached map, drawn once per cache render):

```js
const off = app.registerStaticLayer({
  id: "roads",                 // unique; registering the same id again replaces the layer
  z: 55,                       // where it draws among the built-in steps (app.layerZ / render/map.js Z)
  draw(ctx, vp, w, o) {},      // required. ctx starts in world km (saved/restored around the call)
  visible() { return on; },    // optional; false = not drawn, not hit-tested (part of the cache key)
  sig() { return "v1"; },      // optional; any string that changes when the art must re-render (cache key)
  minRpx: 6, maxRpx: Infinity, // optional zoom range in hex radius css px (drawn when minRpx <= Rpx < maxRpx)
  hit(xKm, yKm, Rpx) { return item | null; },   // optional hover / click test, pointer in world km
  tooltip(item) { return "<b>html</b>" | {text: "plain"} | null; },  // optional; a string is HTML: escape data yourself
  click(item, ev) { return true; },             // optional; true consumes the click (see below)
  warm(ctx, vp, w, o) {},      // optional; paint sprites for vp's zoom in idle time (stamps may land anywhere)
  snapshot: true,              // default true: drawn into share images too
});
off();   // or app.unregisterStaticLayer("roads" | layer)
```

* `o` = `{Rpx, s, dpr, lod, lens, selectedCity, showResources, snapshot, app, cells, range: {r0, r1, c0, c1},
  world(), screen(), toScreen(x, y) → [css px]}`. `cells` are the visible cell indices; `o.screen()` switches ctx to
  screen css px of the cache canvas (use `o.toScreen`), `o.world()` back. Use sprites (`render/art/sprites.js`
  getSprite/drawSprite) for anything richer than a few paths.
* Built-in z steps: `WATER 10`, `LAND 20` (land tiles), `GRID 30`, `GLYPHS 40` (terrain), `RIVERS_BORDERS 50`, `CITIES 60`
  (city tiles), `FOG 70` (edge mist), `RESOURCES 80` (screen-space icons), `LABELS 90` (state names). A layer with z
  between two steps draws after the lower one; equal to a step = right after it. Suggested slots: 45 terrain
  improvements, **55 roads and rail**, 58 restricted ground / protected land hatching, **65 sites** (ports, airports,
  forts, wonders, plaques), **85 trade routes** (above resources, under state names).
* The cache key includes every layer's id, `visible()` and `sig()`, so toggling or restyling re-renders the cache and
  nothing else does. Errors in `draw`/`hit`/`sig`/... are logged once per layer and the layer is skipped.
* **Performance**: nothing may animate continuously (an idle map draws no frames); keep each layer under ~3 ms per cache
  render at typical zooms (time it with `drawStatic(..., {layers: app.staticLayers(), timings: T})`: it reports
  `layer:<id>`); precompute geometry once (not per draw); cull to `vp`.
* `app.staticLayers()` lists the registered layers; `app.hitLayer(mx, my)` (screen css px) → `{layer: id, item} | null`.

**Hover and click.** The hover tooltip asks the layers (highest z first, only those drawn at the current zoom) after the
city banners: the first non-null `hit()` wins and its `tooltip(item)` is shown (the cell tooltip otherwise). The
`"hover"` event payload is `{cell, city, resource, x, y, layer, item}` (`layer` = id or null). A click builds
`ev = {cell, city, resource, state, x, y, pointerType, layer, item}`; outside a mode the layer's `click(item, ev)` goes
first (true consumes it), then the `"mapclick"` handlers, then the default (select city/state). While a mode is active
(City View, advisors) the `"mapclick"` handlers go first and the layer's `click` only after them.

**Map toggles.** `app.ui.addMapToggle({id, label, icon, get() → bool, set(on), title?, default?}) → remove()`: a switch
in the "Map" menu next to the Resources toggle in the lens dock (one button + a small menu, so it fits phones). `set` is
yours (flip the state your layer's `visible()` reads); main redraws. The hash key `layers` lists the switches that are on
(`#layers=roads,rail,military`, `layers=none`) and is written only while some switch differs from its default; switches
added after load are set from it, and ids whose extension has not loaded yet stay in the URL. `app.ui.mapToggles()` →
`[{id, label, on}]`. `app.ui.setMapToggle(id, on) → bool` switches one from code exactly as the menu would (redraw,
hash), e.g. an advisor's "show roads, rail and forts" button; false if no toggle has that id (yet).

**URL.** Core keys: `lens`, `city` (CBSA id), `state`, `at`, plus extension keys (`advisor`, `layers`, ...).
* `#state=` accepts a FIPS code (`48`, `6`), a postal code (`TX`, `tx`) or a state name; a link keeps the form it
  was opened with.
* `at=x,y,z`: `x`, `y` = the map-km point at the centre of the screen (rounded), and `z` = **log2(camera scale ÷
  home-fit scale)**, the zoom relative to the "whole country fits" view: `0` = home framing, `1` = twice as close,
  negative = zoomed out past it. It is relative so a link frames the same area on any screen size; it is *not* the
  absolute scale (css px per km) that `app.flyTo(x, y, scale)` and `camera.scale` use. Convert with
  `scale = fitScale × 2^z`. `at` is written only once the user (or an extension) has moved the camera.
* When the hash is written: during a fly-to the link names the **destination** right away (within one 350 ms debounce
  of the flight starting); after a pan or wheel zoom it catches up 350 ms after the camera settles; `app.setMode`
  writes it on the next task. Lens, selection and mode changes push a history entry (Back undoes them); camera moves
  replace the current one. `app.hash.flush()` writes immediately (Share calls it before copying).

**Optional state and debug handles** (not data contracts; don't rely on them from other extensions without asking):
* `state.cityBadges`: an optional `Map<city id, {label, color: "#rrggbb"}>` that `render/banners.js` reads to draw a
  city-type tab on banners that show their yield row. Filled by `ext/cityView` from districts.json; absent = no tabs.
* `app.cityView.model`: read-only getter on the City View's current model (debugging).
* `app.mapArt = {model, on, layers}`: added by `ext/layers` for debugging. `model` holds `installations`, `ports`,
  `airports`, `wonders`, each item `{data (the json row), cell, x, y}`. The layers' hit items have the shape
  `{kind: "fort"|"range"|"port"|"airport"|"wonder"|"route", data}` (route items: `data.route` with `a`/`b`); the
  advisors rely on that shape for map-to-dashboard links, so keep it.

**Who reads which fields.** The advisors read every counties.json column after `cell`, military.json `states`, districts.json
`cities` and `counties`, and citizens.json `cities`; the City View reads citizens.json, districts.json, military.json
`cities`, trade.json zones and infrastructure.json `cbsa`. Update `web/js/ext/advisors` and `web/js/ext/cityView`
when renaming a field in those files.

**Lenses.** Legend ticks print numbers only (plus short units: %, $, min, /km²); a longer `unit` is printed once under
the ticks, so keep `unit` a plain phrase ("adherents per 100 residents"), not part of the number. `lens.note` is shown in the legend; `format: "category"` lenses get a swatch legend (see lenses.json).

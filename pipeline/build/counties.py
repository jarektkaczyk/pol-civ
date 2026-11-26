"""Gminas (counties.json) and powiaty (powiaty.json), column-oriented, and the per-gmina metrics the lenses share.

Every metric is defined once in METRICS: its level (the unit GUS, PKW or GIOS publishes it for), its formula and
its text. A gmina takes the value of its powiat or voivodeship when the metric exists only at that level, and the
field description says so. lenses.py spreads the same gmina values onto the hexes, so the lens, the Explorer and
the tables show identical numbers.
"""

from __future__ import annotations

import math

from .growth import comparable
from ..core.geo import MapProjection
from ..core.hexgrid import HexGrid
from ..core.store import load_interim, write_web
from .plstats import Stats, Units, median_age, num, ratio, total
from .yields import Economy

REQUIRES = ["_world", "pl_geo_teryt", "pl_geo_fua", "pl_stats_population", "pl_stats_labour", "pl_stats_prosperity",
            "pl_gdp", "pl_foreigners", "pl_census_2021", "pl_soc_elections", "pl_soc_faith", "pl_soc_air",
            "pl_soc_health", "pl_soc_universities", "pl_soc_disasters", "metros.json"]
PRODUCES = ["counties.json", "powiaty.json"]

AIR_RADIUS_KM = 25.0
LEVEL_TEXT = {"gmina": "", "powiat": " Published per powiat: every gmina shows its powiat's value.",
              "voivodeship": " Published per voivodeship: every gmina shows its voivodeship's value.",
              "diocese": " Published per Catholic diocese: every gmina shows the diocese of its seat."}

# Sejm 2023 committees: field -> (category id, short name). Order = the categories of the lens.
SEJM = [
    ("komitet_wyborczy_prawo_i_sprawiedliwosc_share", "pis", "Prawo i Sprawiedliwość"),
    ("koalicyjny_komitet_wyborczy_koalicja_obywatelska_po_n_ipl_zieloni_share", "ko", "Koalicja Obywatelska"),
    ("koalicyjny_komitet_wyborczy_trzecia_droga_polska_2050_szymona_holowni_polskie_stronnictwo_ludowe_share",
     "td", "Trzecia Droga"),
    ("komitet_wyborczy_nowa_lewica_share", "lewica", "Nowa Lewica"),
    ("komitet_wyborczy_konfederacja_wolnosc_i_niepodleglosc_share", "konfederacja", "Konfederacja"),
    ("komitet_wyborczy_wyborcow_mniejszosc_niemiecka_share", "mn", "Mniejszość Niemiecka"),
    ("komitet_wyborczy_bezpartyjni_samorzadowcy_share", "bs", "Bezpartyjni Samorządowcy"),
]
# Neutral, distinct hues (not party colours).
SEJM_COLORS = ["#4f6d8f", "#c08a3e", "#5f9e7a", "#a15f86", "#8a8a5c", "#6aa6b8", "#9b7b63"]
FLOOD_CATS = [("none", "Not in the 2024 flood area", "#3a4a5a"), ("declared", "2024 flood disaster area", "#d9a441")]


def M(key, label, fmt, unit, level, source, higher_is, description, group, **extra):
    return {"key": key, "label": label, "format": fmt, "unit": unit, "level": level, "source": source,
            "higher_is": higher_is, "description": description, "group": group, **extra}


METRICS = [
    M("density", "Density", "float", "people / km²", "gmina", "pl_stats_population", "neutral",
      "Residents per km² (GUS, 30 June 2026; area on 1 January 2026).", "people"),
    M("median_age", "Median age", "years", "years", "gmina", "pl_stats_population", "neutral",
      "Median age of residents, worked out from the GUS five-year age groups of 30 June 2026 by linear "
      "interpolation inside the group that holds the middle resident.", "people"),
    M("growth", "Change 2015-2025", "pct", "population change", "gmina", "pl_stats_population", "neutral",
      "Population on 31 December 2025 ÷ population on 31 December 2015 - 1 (GUS). Each year is on its own "
      "borders, so gminas whose borders changed (Opole and four neighbours in 2017; Kamienica, Szczawa, Supraśl and "
      "Grabówka in 2025) show no change.",
      "people"),
    M("net_migration", "Net migration", "float", "per 1,000 residents", "gmina", "pl_stats_population", "neutral",
      "People who moved in minus people who moved out, within Poland and from abroad, per 1,000 residents (GUS, 2025).",
      "people"),
    M("elderly", "Aged 65+", "pct", "share of residents", "gmina", "pl_stats_population", "neutral",
      "Residents aged 65 or more ÷ all residents (GUS, 30 June 2026).", "people"),
    M("births", "Births", "float", "per 1,000 residents", "gmina", "pl_stats_population", "neutral",
      "Live births per 1,000 residents (GUS, 2025).", "people"),
    M("ukrainians", "Ukrainians (PESEL UKR)", "float", "per 1,000 residents", "powiat", "pl_foreigners", "neutral",
      "Ukrainian citizens with a PESEL UKR number (temporary protection) registered in the powiat, per 1,000 "
      "residents. The register shows where the number was issued, not where the person lives now.", "people"),
    M("pit", "PIT revenue per person", "pln", "zł per resident", "gmina", "pl_stats_prosperity", "good",
      "The gmina's share of personal income tax planned for 2026 ÷ residents (Ministry of Finance, GUS "
      "population of 31 December 2025). It follows residents' taxable incomes.", "prosperity"),
    M("wage", "Average wage", "pln", "zł gross per month", "powiat", "pl_stats_labour", "good",
      "Average gross monthly wage, by employer seat (GUS wage distribution, May 2026).", "prosperity"),
    M("unemployment", "Unemployment", "pct", "registered rate", "powiat", "pl_stats_labour", "bad",
      "Registered unemployment rate, end of October 2026 (GUS).", "prosperity"),
    M("dwellings", "New dwellings", "float", "per 1,000 residents", "gmina", "pl_stats_prosperity", "neutral",
      "Dwellings completed in 2025 per 1,000 residents (GUS).", "prosperity"),
    M("higher_ed", "Higher education", "pct", "of residents 13+", "gmina", "pl_census_2021", "good",
      "Residents aged 13 or more with a higher-education diploma (NSP 2021 census, 31 March 2021).", "knowledge"),
    M("students", "University students", "float", "per 1,000 residents", "gmina", "pl_stats_population", "neutral",
      "Students of the universities in the gmina, per 1,000 residents (GUS, 31 December 2025). A student on two "
      "programmes counts twice. Gminas without a university are blank.", "knowledge"),
    M("tourism", "Tourist nights", "float", "nights per resident", "powiat", "pl_stats_prosperity", "neutral",
      "Nights spent in tourist accommodation with 10 or more beds in 2025 ÷ residents (GUS).", "life"),
    M("doctors", "Doctors", "float", "per 10,000 residents", "powiat", "pl_soc_health", "good",
      "Doctors counted at their main place of work, per 10,000 residents (GUS, 2024). City powiats with big "
      "hospitals rank high, the rural powiats around them low.", "life"),
    M("life_f", "Life expectancy, women", "years", "years at birth", "voivodeship", "pl_stats_population", "good",
      "Life expectancy at birth of women (GUS, 2025).", "life"),
    M("life_m", "Life expectancy, men", "years", "years at birth", "voivodeship", "pl_stats_population", "good",
      "Life expectancy at birth of men (GUS, 2025).", "life"),
    M("catholic", "Roman Catholic", "pct", "of all residents", "gmina", "pl_soc_faith", "neutral",
      "Residents who declared the Roman Catholic Church, as a share of all residents (NSP 2021 census). About a "
      "fifth of residents (21% in Poland) did not answer the voluntary question.", "faith"),
    M("no_religion", "No religion", "pct", "of all residents", "gmina", "pl_soc_faith", "neutral",
      "Residents who declared no religion, as a share of all residents (NSP 2021 census).", "faith"),
    M("mass", "Mass attendance", "pct", "of Catholics obliged", "diocese", "pl_soc_faith", "neutral",
      "Dominicantes: the share of Catholics obliged to attend who were at Sunday Mass on the October 2024 count "
      "(ISKK, Annuarium Statisticum Ecclesiae in Polonia).", "faith"),
    M("president_2025", "President 2025", "pct", "Nawrocki share of valid votes", "gmina", "pl_soc_elections",
      "neutral", "Second round, 1 June 2025: Karol Nawrocki's share of valid votes (PKW). The rest went to Rafał "
      "Trzaskowski.", "vote"),
    M("turnout_2025", "Turnout 2025", "pct", "of eligible voters", "gmina", "pl_soc_elections", "neutral",
      "Valid ballot papers ÷ eligible voters, presidential election second round, 1 June 2025 (PKW).", "vote"),
    M("sejm_2023", "Sejm 2023", "text", None, "gmina", "pl_soc_elections", "neutral",
      "The committee with the most valid votes in the gmina, Sejm election of 15 October 2023 (PKW).", "vote"),
    M("pm25", "PM2.5", "float", "µg/m³ annual mean", "station", "pl_soc_air", "bad",
      "Annual mean of PM2.5 in 2025 at the nearest GIOŚ measuring station within 25 km of the gmina's centre. "
      "Gminas with no station that close are blank. A station measures its street or district, not the whole "
      "gmina.", "air"),
    M("flood_2024", "2024 flood", "text", None, "gmina", "pl_soc_disasters", "bad",
      "Gminas named in the state of natural disaster declared for the September 2024 flood (Dz.U. 2024 poz. 1365 "
      "and amendments).", "hazards"),
    M("forest", "Forest", "pct", "share of land", "gmina", "pl_geo_worldcover", "neutral",
      "Share of the land with tree cover (ESA WorldCover 2021), averaged over the gmina's hex samples.", "land"),
    M("farmland", "Farmland", "pct", "share of land", "gmina", "pl_geo_worldcover", "neutral",
      "Share of the land in cropland or meadow and pasture below 900 m (ESA WorldCover 2021).", "land"),
    M("developed", "Built-up", "pct", "share of land", "gmina", "pl_geo_worldcover", "neutral",
      "Share of the land that is built up (ESA WorldCover 2021).", "land"),
]
METRIC = {m["key"]: m for m in METRICS}


def description(m: dict) -> str:
    return m["description"] + LEVEL_TEXT.get(m["level"], "")


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def nearest_station(lon, lat, stations, radius=AIR_RADIUS_KM):
    """(value, station name, km) of the nearest station with a value within `radius`, or None."""
    best = None
    for s in stations:
        d = haversine_km(lon, lat, s["lon"], s["lat"])
        if d <= radius and (best is None or d < best[2]):
            best = (s["value"], s["name"], d)
    return best


def largest(rec: dict, fields) -> int | None:
    """Index of the field with the largest share in `rec` (None when all are missing)."""
    best = None
    for i, (f, *_rest) in enumerate(fields):
        v = num(rec.get(f))
        if v is not None and (best is None or v > best[0]):
            best = (v, i)
    return best[1] if best else None


class Metrics:
    """Every metric per gmina (aligned with Units.gminas), plus the gmina centre points used for air quality."""

    def __init__(self, world: dict, units: Units, stats: Stats, econ: Economy, proj: MapProjection, grid: HexGrid):
        self.u, self.s, self.e = units, stats, econ
        gms = units.gminas
        self.values: dict[str, list] = {}
        pop = stats.rows("pl_stats_population", "population")
        vital = stats.rows("pl_stats_population", "vital_migration")
        demo = stats.rows("pl_stats_population", "demographic_indicators")
        prosp = stats.rows("pl_stats_prosperity", "income_gmina")
        house = stats.rows("pl_stats_prosperity", "housing_gmina")
        tour = stats.rows("pl_stats_prosperity", "tourism_powiat")
        lab = stats.rows("pl_stats_labour", "labour_powiat")
        ukr = stats.rows("pl_foreigners", "pesel_ukr_powiat")
        edu = stats.rows("pl_census_2021", "education_gmina")
        health = stats.rows("pl_soc_health", "health_powiat")
        stud = stats.rows("pl_stats_population", "university_students_city")
        faith = stats.rows("pl_soc_faith", "religion_gmina")
        faith_d = stats.data("pl_soc_faith")
        mass = stats.rows("pl_soc_faith", "mass_attendance_diocese")
        dio_of = {stats.gmina_key(k): v for k, v in ((faith_d.get("diocese_of") or {}).get("gmina") or {}).items()}
        r2 = stats.rows("pl_soc_elections", "president_2025_r2")
        sejm = stats.rows("pl_soc_elections", "sejm_2023")
        flood = stats.rows("pl_soc_disasters", "flood_2024_gmina")
        powiat_pop = {}
        for g in gms:
            p = econ.pop.get(g) or 0
            powiat_pop[g[:4]] = powiat_pop.get(g[:4], 0) + p

        def col(key, f):
            self.values[key] = [f(g) for g in gms]

        def rec(rows, code):
            return rows.get(code) or {}

        def pct(v):
            return round(v / 100, 4) if num(v) is not None else None

        col("population", lambda g: econ.pop.get(g))
        col("area_km2", lambda g: ratio(rec(pop, g).get("area_ha"), 100, 1, 2))
        col("density", lambda g: ratio(econ.pop.get(g), ratio(rec(pop, g).get("area_ha"), 100), 1, 1))
        col("median_age", lambda g: median_age(rec(pop, g)))
        col("growth", lambda g: _growth(econ.pop2025.get(g), econ.pop2015.get(g)) if comparable([g]) else None)
        col("net_migration", lambda g: _r(rec(vital, g).get("total_migration_net_per_1000"), 2))
        col("elderly", lambda g: ratio(rec(pop, g).get("age_65_plus"), econ.pop.get(g), 1, 4))
        col("births", lambda g: _r(rec(vital, g).get("births_per_1000"), 2))
        col("ukrainians", lambda g: ratio(rec(ukr, g[:4]).get("pesel_ukr"), powiat_pop.get(g[:4]), 1000, 1))
        col("pit", lambda g: _r(rec(prosp, g).get("pit_revenue_per_person"), 0))
        col("wage", lambda g: _r(rec(lab, g[:4]).get("average_gross_monthly_wage"), 0))
        col("unemployment", lambda g: pct(rec(lab, g[:4]).get("registered_unemployment_rate")))
        col("dwellings", lambda g: _r(rec(house, g).get("dwellings_completed_per_1000"), 2))
        col("higher_ed", lambda g: pct(rec(edu, g).get("higher_share")))
        col("students", lambda g: ratio(rec(stud, g).get("students"), econ.pop2025.get(g), 1000, 1))
        col("tourism", lambda g: _r(rec(tour, g[:4]).get("overnight_stays_per_person"), 2))
        col("doctors", lambda g: _r(rec(health, g[:4]).get("doctors_per_10k"), 1))
        col("life_f", lambda g: _r(rec(demo, g[:2]).get("life_expectancy_female"), 1))
        col("life_m", lambda g: _r(rec(demo, g[:2]).get("life_expectancy_male"), 1))
        col("catholic", lambda g: pct(rec(faith, g).get("roman_catholic_share")))
        col("no_religion", lambda g: pct(rec(faith, g).get("none_share")))
        col("mass", lambda g: pct(rec(mass, dio_of.get(g)).get("dominicantes")) if dio_of.get(g) else None)
        col("president_2025", lambda g: pct(rec(r2, g).get("nawrocki_share")))
        col("turnout_2025", lambda g: pct(rec(r2, g).get("turnout")))
        col("sejm_2023", lambda g: (lambda i: SEJM[i][1] if i is not None else None)(largest(rec(sejm, g), SEJM)))
        has_flood = bool(flood)
        col("flood_2024", lambda g: ("declared" if num(rec(flood, g).get("declared_2024")) == 1 else "none")
            if has_flood else None)

        # Land: mean of the hex shares over the gmina's samples (a hex counts once per sample in the gmina).
        pctw = world.get("pct") or {}
        acc: dict[int, list] = {}
        for cell, smp in enumerate(world["county_samples"]):
            if not smp or not (world.get("cover") or [1] * len(smp))[cell]:
                continue
            for k in smp:
                if k >= 0 and pctw:
                    a = acc.setdefault(k, [0, 0, 0, 0])
                    a[0] += pctw["forest"][cell]
                    a[1] += pctw["crop"][cell] + pctw["pasture"][cell]
                    a[2] += pctw["developed"][cell]
                    a[3] += 1
        for j, key in enumerate(("forest", "farmland", "developed")):
            self.values[key] = [round(acc[i][j] / acc[i][3] / 100, 3) if i in acc else None for i in range(len(gms))]

        # Gmina centre (mean of its sample hexes) -> lon/lat, for the nearest air station.
        cx: dict[int, list] = {}
        for cell, smp in enumerate(world["county_samples"]):
            for k in smp or ():
                if k >= 0:
                    a = cx.setdefault(k, [0.0, 0.0, 0])
                    x, y = grid.center(*grid.col_row(cell))
                    a[0] += x
                    a[1] += y
                    a[2] += 1
        self.centre = {i: (a[0] / a[2], a[1] / a[2]) for i, a in cx.items()}
        air = stats.data("pl_soc_air").get("points") or []
        stations = [{"lon": p["lon"], "lat": p["lat"], "name": p["name"], "value": p["props"].get("pm25")}
                    for p in air if p.get("lon") is not None and num((p.get("props") or {}).get("pm25")) is not None]
        self.air_station = [None] * len(gms)
        pm = [None] * len(gms)
        for i in range(len(gms)):
            if i not in self.centre or not stations:
                continue
            lon, lat = proj.inverse(*self.centre[i])
            hit = nearest_station(lon, lat, stations)
            if hit:
                pm[i] = round(hit[0], 1)
                self.air_station[i] = f"{hit[1]} ({hit[2]:.0f} km)"
        self.values["pm25"] = pm
        self.stations = stations


def _r(v, digits):
    v = num(v)
    return None if v is None else (round(v) if digits == 0 else round(v, digits))


def _growth(a, b):
    from .growth import rate

    return rate(a, b)


def projection(world: dict) -> MapProjection:
    return MapProjection(**{k: world["projection"][k] for k in ("min_x", "max_y", "margin")})


def cells_by_gmina(world: dict) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for cell, smp in enumerate(world["county_samples"]):
        for k in set(smp or ()):
            if k >= 0:
                out.setdefault(k, []).append(cell)
    return out


def representative_cell(cells: list[int] | None, grid: HexGrid, centre) -> int | None:
    """The hex nearest the gmina's centre among the hexes its samples hit (or None)."""
    if centre is None or not cells:
        return None
    best = None
    for cell in cells:
        x, y = grid.center(*grid.col_row(cell))
        d = (x - centre[0]) ** 2 + (y - centre[1]) ** 2
        if best is None or d < best[0]:
            best = (d, cell)
    return best[1] if best else None


TYPE_TEXT = {"urban": "urban", "rural": "rural", "urban-rural": "urban-rural"}
GMINA_COLUMNS = ["geoid", "name", "type", "powiat", "state", "population", "area_km2"]
FIELD_KEYS = [m["key"] for m in METRICS]


def _field(key, label, fmt, unit=None, higher_is="neutral", source=None, description="", level="gmina", group=None):
    return {"key": key, "label": label, "format": fmt, "unit": unit, "higher_is": higher_is, "source": source,
            "description": description, "level": level, "group": group}


def gmina_fields() -> list[dict]:
    head = [
        _field("geoid", "TERYT", "text", description="TERYT 7-digit gmina code (2026), with the type digit."),
        _field("name", "Gmina", "text", source="pl_geo_teryt"),
        _field("type", "Type", "text", source="pl_geo_teryt", description="Urban, rural or urban-rural gmina."),
        _field("powiat", "Powiat", "text", source="pl_geo_teryt"),
        _field("state", "Voivodeship", "text", source="pl_geo_teryt"),
        _field("population", "Population", "int", "people", source="pl_stats_population",
               description="Residents on 30 June 2026 (GUS)."),
        _field("area_km2", "Area", "km2", "km²", source="pl_stats_population",
               description="Area on 1 January 2026 (GUS)."),
    ]
    body = [_field(m["key"], m["label"], m["format"], m["unit"], m["higher_is"], m["source"], description(m),
                   m["level"], m["group"]) for m in METRICS]
    tail = [
        _field("workers", "Workers", "int", "people", source="pl_stats_labour",
               description="People working, by employer seat (GUS, 31 December 2025, gmina sector table)."),
        _field("gdp", "GDP (share)", "pln", "zł per year", source="pl_gdp",
               description="The gmina's share of its powiat's GDP 2023 (see the Gold yield)."),
        _field("air_station", "Air station", "text", source="pl_soc_air",
               description="The GIOŚ station the PM2.5 value comes from, with its distance."),
        _field("cbsa", "Metro", "text", source="pl_geo_fua",
               description="The metro (Eurostat functional urban area) the gmina belongs to."),
        _field("cell", "Cell", "int", description="A representative hex of the gmina."),
    ]
    return head + body + tail


POWIAT_FIELDS = ["density", "growth", "net_migration", "elderly", "births", "ukrainians", "pit", "wage",
                 "unemployment", "higher_ed", "doctors", "catholic", "no_religion", "president_2025", "turnout_2025",
                 "forest", "farmland", "developed"]


def build() -> None:
    from .world import ABBR

    world = load_interim("_world")
    teryt = load_interim("pl_geo_teryt")
    units = Units(world, teryt)
    stats = Stats()
    econ = Economy(units, stats)
    grid = HexGrid(**world["grid"])
    proj = projection(world)
    m = Metrics(world, units, stats, econ, proj, grid)
    metros = (optional_web("metros.json") or {}).get("metros") or []
    metro_of = {g: mt["id"] for mt in metros for g in mt["gminas"]}

    cells_of = cells_by_gmina(world)
    fields = gmina_fields()
    columns = [f["key"] for f in fields]
    rows = []
    for i, g in enumerate(units.gminas):
        v = {k: m.values[k][i] for k in FIELD_KEYS}
        y = econ.gmina_yields(g)
        rows.append([
            g, units.gmina_name.get(g, g), TYPE_TEXT.get(units.gmina_type.get(g), units.gmina_type.get(g)),
            units.powiat_label(g[:4]), ABBR.get(g[:2], g[:2]), m.values["population"][i], m.values["area_km2"][i],
            *[v[k] for k in FIELD_KEYS],
            num(econ.sec[g].get("workers_total")), round(y["gold"]) if y["gold"] is not None else None,
            m.air_station[i], metro_of.get(g),
            representative_cell(cells_of.get(i), grid, m.centre.get(i)),
        ])
    vint = "; ".join(v for v in (stats.vintage(s) for s in ("pl_stats_population", "pl_stats_labour")) if v)
    write_web("counties.json", {"vintage": vint, "fields": fields, "columns": columns, "rows": rows})

    # Powiaty: sums and population-weighted means of their gminas (exact for counts and for powiat-level data).
    pfields = [
        _field("code", "TERYT", "text"), _field("name", "Powiat", "text", source="pl_geo_teryt"),
        _field("state", "Voivodeship", "text", source="pl_geo_teryt"),
        _field("population", "Population", "int", "people", source="pl_stats_population",
               description="Residents on 30 June 2026 (GUS)."),
        _field("area_km2", "Area", "km2", "km²", source="pl_stats_population"),
        *[_field(k, METRIC[k]["label"], METRIC[k]["format"], METRIC[k]["unit"], METRIC[k]["higher_is"],
                 METRIC[k]["source"], METRIC[k]["description"] + ("" if METRIC[k]["level"] in ("powiat", "voivodeship")
                 else " Powiat: the population-weighted mean of its gminas." if k not in ("density", "growth")
                 else ""), "powiat", METRIC[k]["group"]) for k in POWIAT_FIELDS],
        _field("workers", "Workers", "int", "people", source="pl_stats_labour",
               description="People working, by employer seat (GUS, 31 December 2025, PKD table)."),
        *[_field(f"y_{y}", y.capitalize(), "pln" if y == "gold" else "int", "zł per year" if y == "gold" else "workers",
                 source="pl_gdp" if y == "gold" else "pl_stats_labour", description=f"The {y.capitalize()} yield "
                 f"of the powiat (see the Yields page).") for y in ("food", "production", "gold", "science", "culture")],
        _field("cell", "Cell", "int"),
    ]
    prows = []
    idx = units.index
    for p in units.powiaty:
        gms = units.gminas_of_powiat.get(p, [])
        ii = [idx[g] for g in gms]
        pop = total(m.values["population"][i] for i in ii)
        area = total(m.values["area_km2"][i] for i in ii)
        vals = {}
        for k in POWIAT_FIELDS:
            if k == "density":
                vals[k] = round(pop / area, 1) if pop and area else None
            elif k == "growth":
                vals[k] = (_growth(total(econ.pop2025.get(g) for g in gms), total(econ.pop2015.get(g) for g in gms))
                           if comparable(gms) else None)
            elif METRIC[k]["level"] in ("powiat", "voivodeship"):
                vals[k] = m.values[k][ii[0]] if ii else None
            else:
                pairs = [(m.values[k][i], m.values["population"][i] or 0) for i in ii if m.values[k][i] is not None]
                w = sum(p_ for _, p_ in pairs)
                digits = {"pln": 0, "pct": 4, "years": 1}.get(METRIC[k]["format"], 2)
                vals[k] = round(sum(v * p_ for v, p_ in pairs) / w, digits) if w else None
        py = econ.powiat_yields(p)
        big = max(ii, key=lambda i: m.values["population"][i] or 0) if ii else None
        prows.append([p, units.powiat_label(p), ABBR.get(p[:2], p[:2]), pop, area, *[vals[k] for k in POWIAT_FIELDS],
                      econ.powiat_workers(p), *[py[y] if y != "gold" or py[y] is None else round(py[y])
                                                for y in ("food", "production", "gold", "science", "culture")],
                      representative_cell(cells_of.get(big), grid, m.centre.get(big)) if big is not None else None])
    write_web("powiaty.json", {"vintage": vint, "fields": pfields, "columns": [f["key"] for f in pfields],
                               "rows": prows})
    filled = {k: sum(1 for v in m.values[k] if v is not None) for k in FIELD_KEYS}
    print(f"    {len(rows)} gminas, {len(prows)} powiaty; metrics with data: "
          + ", ".join(f"{k} {n}" for k, n in filled.items()))


def optional_web(name: str):
    import json

    from ..core.paths import WEB_DATA

    path = WEB_DATA / name
    return json.loads(path.read_text()) if path.exists() else None

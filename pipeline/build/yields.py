"""The game-concept to real-data mapping for Poland, in one place (a helper, not a builder).

Each yield is defined once here and exported to the browser (nation.json `yields`), so the UI and the Almanac
always describe exactly what was computed.

Yield rules (blueprint section 8), all GUS workers counted where the employer is, on 31 December 2025:

* Food = workers in agriculture, forestry and fishing (PKD section A). Whole powiaty (and the cities with powiat
  rights) use the PKD sections; other gminas the GUS "agriculture" sector of the gmina table.
* Production = workers in industry and construction (PKD sections B-F; a withheld section counts as absent).
  Other gminas: the GUS "industry and construction" sector.
* Science = workers in information and communication (J) plus professional, scientific and technical activities
  (M). Published per powiat; a gmina gets its powiat's J + M in proportion to its share of the powiat's service
  workers (exact for the 66 cities with powiat rights, which are one gmina each).
* Culture = workers in accommodation and food service (I) plus arts, entertainment and recreation (R); shared to
  gminas like Science.
* Gold = GDP in current PLN. Poland: GDP 2025 (Eurostat). Voivodeship: GDP 2024 (GUS regional accounts, revision
  of 30 September 2026; Mazowieckie = both its NUTS 2 regions). Powiat: the GDP 2023 of its NUTS 3 subregion, shared among the subregion's powiaty by their wage
  bill (average gross monthly wage x workers). Gmina: its powiat's GDP in proportion to its workers.
  Town and metro: the sum of their gminas.
"""

from __future__ import annotations

from .growth import comparable, rate
from .plstats import Stats, Units, num, ratio, total

# PKD 2007 sections -> (jobs key, label). GUS publishes them per powiat (pl_stats_labour employment_pkd_powiat).
SECTIONS = {
    "A": ("agriculture", "Agriculture, forestry & fishing"),
    "B": ("mining", "Mining & quarrying"),
    "C": ("manufacturing", "Manufacturing"),
    "D": ("energy", "Electricity, gas & heat supply"),
    "E": ("water", "Water supply & waste"),
    "F": ("construction", "Construction"),
    "G": ("trade", "Trade & vehicle repair"),
    "H": ("transport", "Transport & storage"),
    "I": ("accommodation", "Accommodation & food service"),
    "J": ("information", "Information & communication"),
    "K": ("finance", "Finance & insurance"),
    "L": ("real_estate", "Real estate"),
    "M": ("professional", "Professional, scientific & technical"),
    "N": ("admin", "Administrative & support services"),
    "O": ("public_admin", "Public administration & defence"),
    "P": ("education", "Education"),
    "Q": ("health", "Health & social work"),
    "R": ("arts", "Arts, entertainment & recreation"),
    "S": ("other", "Other services"),
}
JOB_KEYS = [k for k, _ in SECTIONS.values()]
SECTION_OF = {k: s for s, (k, _) in SECTIONS.items()}

YIELDS = [
    {
        "key": "food", "icon": "y-food", "emoji": "🌾", "label": "Food", "color": "#7fbf3f", "unit": "workers",
        "industries": ["agriculture"],
        "description": "Workers in agriculture, forestry and fishing (PKD section A), counted where the employer is "
        "(GUS, 31 December 2025). Powiaty and cities with powiat rights: PKD section A; other gminas: the GUS "
        "agriculture sector of the gmina table.",
    },
    {
        "key": "production", "icon": "y-production", "emoji": "⚙️", "label": "Production", "color": "#d9823b",
        "unit": "workers", "industries": ["mining", "manufacturing", "energy", "water", "construction"],
        "description": "Workers in industry and construction (PKD sections B-F), counted where the employer is "
        "(GUS, 31 December 2025). Powiaty and cities with powiat rights: the PKD sections (a section GUS withholds "
        "counts as absent); other gminas: the GUS industry and construction sector of the gmina table.",
    },
    {
        "key": "gold", "icon": "y-gold", "emoji": "💰", "label": "Gold", "color": "#f2c94c", "unit": "pln",
        "industries": [],
        "description": "Gross domestic product per year in current złoty. Poland: 2025 (GUS, through Eurostat). "
        "Voivodeships: 2024 (GUS regional accounts). Powiaty: the 2023 GDP of their NUTS 3 subregion, shared among the "
        "subregion's powiaty by their wage bill (average wage x workers). Gminas: their powiat's GDP in proportion "
        "to their workers. Towns and metros: the sum of their gminas. Below the voivodeship level the figure is "
        "a share of a published total, not a published GDP.",
    },
    {
        "key": "science", "icon": "y-science", "emoji": "🔬", "label": "Science", "color": "#4fa3e0",
        "unit": "workers", "industries": ["information", "professional"],
        "description": "Workers in information and communication (J) and in professional, scientific and technical "
        "activities (M), counted where the employer is (GUS, 31 December 2025). Published per powiat; a gmina "
        "gets its powiat's figure in proportion to its service workers (exact for cities with powiat rights).",
    },
    {
        "key": "culture", "icon": "y-culture", "emoji": "🎭", "label": "Culture", "color": "#b07ce0",
        "unit": "workers", "industries": ["accommodation", "arts"],
        "description": "Workers in accommodation and food service (I) and in arts, entertainment and recreation "
        "(R), counted where the employer is (GUS, 31 December 2025). Shared to gminas like Science.",
    },
]
YIELD_KEYS = [y["key"] for y in YIELDS]
INDUSTRIES = {k: label for k, label in SECTIONS.values()}


class Economy:
    """Per-gmina yields and profiles, and sums over any set of gminas (town, metro, powiat, voivodeship, nation)."""

    def __init__(self, units: Units, stats: Stats):
        self.u, self.s = units, stats.rekey(units)
        pop = stats.rows("pl_stats_population", "population")
        self.pop = {g: num((pop.get(g) or {}).get("population")) for g in units.gminas}
        # 31 December 2025: compared with 31 December 2015 and 2020 for change, and the base of 2025 per-person rates.
        self.pop2025 = {g: num((pop.get(g) or {}).get("population_2025")) for g in units.gminas}
        self.pop2015 = {g: num((pop.get(g) or {}).get("population_2015")) for g in units.gminas}
        self.pop2020 = {g: num((pop.get(g) or {}).get("population_2020")) for g in units.gminas}
        sec = stats.rows("pl_stats_labour", "employment_sectors_gmina")
        self.sec = {g: sec.get(g) or {} for g in units.gminas}
        self.pkd = stats.rows("pl_stats_labour", "employment_pkd_powiat")
        self.lab = stats.rows("pl_stats_labour", "labour_powiat")
        self.pit = stats.rows("pl_stats_prosperity", "income_gmina")
        self.years = {
            "population": stats.field_year("pl_stats_population", "population", "population"),
            "population_2025": stats.field_year("pl_stats_population", "population", "population_2025"),
            "workers": stats.field_year("pl_stats_labour", "employment_pkd_powiat", "workers_total"),
            "gdp_nuts3": stats.field_year("pl_gdp", "gdp_nuts3", "gdp_pln"),
            "gdp_voiv": stats.field_year("pl_gdp", "gdp_voivodeship", "gdp_pln"),
            "gdp_nation": stats.field_year("pl_gdp", "gdp_country", "gdp_pln"),
            "wage": stats.field_year("pl_stats_labour", "labour_powiat", "average_gross_monthly_wage"),
            "unemployment": stats.field_year("pl_stats_labour", "labour_powiat", "registered_unemployment_rate"),
            "pit": stats.field_year("pl_stats_prosperity", "income_gmina", "pit_revenue_per_person"),
        }
        self._shares()
        self._gdp()

    # -- gmina shares of powiat totals -------------------------------------------------------------------------
    def _shares(self):
        self.sci, self.cul = {}, {}
        for p, gms in self.u.gminas_of_powiat.items():
            rec = self.pkd.get(p) or {}
            jm = _sum_sections(rec, "JM")
            ir = _sum_sections(rec, "IR")
            serv = [num(self.sec[g].get("workers_services")) for g in gms]
            st = sum(v for v in serv if v is not None)
            for g, sv in zip(gms, serv):
                if len(gms) == 1:
                    self.sci[g], self.cul[g] = jm, ir
                elif sv is None or not st:
                    self.sci[g] = self.cul[g] = None
                else:
                    self.sci[g] = round(jm * sv / st) if jm is not None else None
                    self.cul[g] = round(ir * sv / st) if ir is not None else None

    def _gdp(self):
        """GDP 2023 per powiat (NUTS 3 by wage bill) and per gmina (powiat by workers)."""
        fua = self.s.data("pl_geo_fua").get("gminas") or {}
        nuts3_of_p: dict[str, str] = {}
        for g in self.u.gminas:
            n3 = (fua.get(g[:6]) or {}).get("nuts3")
            if n3:
                nuts3_of_p.setdefault(g[:4], n3)
        gdp3 = self.s.rows("pl_gdp", "gdp_nuts3")
        members: dict[str, list[str]] = {}
        for p, n3 in nuts3_of_p.items():
            members.setdefault(n3, []).append(p)
        self.powiat_gdp: dict[str, float | None] = {p: None for p in self.u.gminas_of_powiat}
        self.by_workers_only: list[str] = []
        for n3, ps in members.items():
            g3 = num((gdp3.get(n3) or {}).get("gdp_pln"))
            if g3 is None:
                continue
            workers = {p: self.powiat_workers(p) for p in ps}
            wage = {p: num((self.lab.get(p) or {}).get("average_gross_monthly_wage")) for p in ps}
            if all(workers[p] and wage[p] for p in ps):
                w = {p: workers[p] * wage[p] for p in ps}
            elif all(workers[p] for p in ps):
                w = dict(workers)
                self.by_workers_only.append(n3)
            else:
                continue
            tw = sum(w.values())
            for p in ps:
                self.powiat_gdp[p] = g3 * w[p] / tw
        self.gmina_gdp: dict[str, float | None] = {}
        for p, gms in self.u.gminas_of_powiat.items():
            pg = self.powiat_gdp.get(p)
            wk = [num(self.sec[g].get("workers_total")) for g in gms]
            tw = sum(v for v in wk if v is not None)
            for g, v in zip(gms, wk):
                self.gmina_gdp[g] = round(pg * v / tw) if pg is not None and v is not None and tw else None

    def powiat_workers(self, p: str) -> float | None:
        v = num((self.pkd.get(p) or {}).get("workers_total"))
        if v is not None:
            return v
        return total(self.sec[g].get("workers_total") for g in self.u.gminas_of_powiat.get(p, []))

    # -- profiles ----------------------------------------------------------------------------------------------
    def powiat_yields(self, p: str) -> dict:
        """Yields of a whole powiat from the PKD sections (a withheld section counts as absent)."""
        rec = self.pkd.get(p) or {}
        sec = lambda letters: total(rec.get(f"workers_{x}") for x in letters)
        return {"food": sec("A"), "production": sec("BCDEF"), "gold": self.powiat_gdp.get(p),
                "science": _sum_sections(rec, "JM"), "culture": _sum_sections(rec, "IR")}

    def gmina_yields(self, g: str) -> dict:
        if len(self.u.gminas_of_powiat.get(g[:4], [])) == 1 and g[:4] in self.pkd:  # a city with powiat rights
            return self.powiat_yields(g[:4])
        s = self.sec[g]
        return {
            "food": num(s.get("workers_agriculture")),
            "production": num(s.get("workers_industry")),
            "gold": self.gmina_gdp.get(g),
            "science": self.sci.get(g),
            "culture": self.cul.get(g),
        }

    def jobs_of_powiaty(self, powiaty: list[str]) -> dict:
        """PKD jobs summed over whole powiaty; a section is null when it is withheld in every one of them."""
        return {k: total((self.pkd.get(p) or {}).get(f"workers_{s}") for p in powiaty) for s, (k, _) in SECTIONS.items()}

    def profile(self, gminas: list[str], *, powiaty: list[str] | None = None) -> dict:
        """Economic fields of a set of gminas. `powiaty`: the set is exactly these whole powiaty (PKD jobs exact,
        wage and unemployment from the powiat totals)."""
        ys = [self.powiat_yields(p) for p in powiaty] if powiaty else [self.gmina_yields(g) for g in gminas]
        yields = {k: _round(total(y[k] for y in ys)) if any(y[k] is not None for y in ys) else None for k in YIELD_KEYS}
        pop = total(self.pop.get(g) for g in gminas)
        # Whole powiaty: a gmina created since 2015 is covered by the 2015 figure of the gmina it was split from.
        past = (lambda d: total(d.get(g) for g in gminas)) if powiaty else (lambda d: full(d, gminas))
        pop_end = past(self.pop2025)
        growth = rate(pop_end, past(self.pop2015)) if comparable(gminas) else None
        pit = total((self.pit.get(g) or {}).get("pit_revenue_total") for g in gminas)
        pit_pop = total(self.pop2025.get(g) for g in gminas
                        if num((self.pit.get(g) or {}).get("pit_revenue_total")) is not None)
        # Powiat-level labour figures, weighted by the population each powiat contributes to the set.
        weight: dict[str, float] = {}
        for g in gminas:
            weight[g[:4]] = weight.get(g[:4], 0) + (self.pop.get(g) or 0)
        ps = powiaty or list(weight)
        unemployed = [num((self.lab.get(p) or {}).get("registered_unemployed")) for p in ps]
        rates = [num((self.lab.get(p) or {}).get("registered_unemployment_rate")) for p in ps]
        if powiaty and all(u is not None and r for u, r in zip(unemployed, rates)):
            force = sum(u / (r / 100) for u, r in zip(unemployed, rates))
            unemployment = round(sum(unemployed) / force, 4) if force else None
        else:
            unemployment = _wmean({p: (r / 100 if r is not None else None) for p, r in zip(ps, rates)}, weight, 4)
        wages = {p: num((self.lab.get(p) or {}).get("average_gross_monthly_wage")) for p in ps}
        wk = {p: self.powiat_workers(p) for p in ps} if powiaty else weight
        wage = _wmean(wages, wk, 0)
        exact_one = powiaty is not None and len(powiaty) == 1
        return {
            "population": _round(pop),
            "employed": _round(total(self.powiat_workers(p) for p in powiaty) if powiaty
                               else total(self.powiat_workers(g[:4]) if len(self.u.gminas_of_powiat[g[:4]]) == 1
                                          else self.sec[g].get("workers_total") for g in gminas)),
            "yields": yields,
            "jobs": self.jobs_of_powiaty(powiaty) if powiaty else {},
            "wage": wage,
            "wage_exact": exact_one,
            "unemployment": unemployment,
            "unemployment_exact": powiaty is not None,
            "pit_per_person": round(pit / pit_pop, 2) if pit is not None and pit_pop else None,
            "gdp": yields["gold"],
            "gdp_year": self.years["gdp_nuts3"] if yields["gold"] is not None else None,
            "gdp_estimated": yields["gold"] is not None,
            "growth": growth,
            "growth_years": [2015, self.years["population_2025"] or 2025],
            "pop_series": {
                "2015": _round(past(self.pop2015)),
                "2020": _round(past(self.pop2020)),
                str(self.years["population_2025"] or 2025): _round(pop_end),
            },
        }


def full(d: dict, keys) -> float | None:
    vals = [d.get(k) for k in keys]
    return None if not vals or any(v is None for v in vals) else sum(vals)


def _sum_sections(rec: dict, letters: str) -> float | None:
    vals = [num(rec.get(f"workers_{s}")) for s in letters]
    return None if any(v is None for v in vals) else sum(vals)


def _wmean(values: dict, weights: dict, digits: int):
    pairs = [(v, weights.get(k) or 0) for k, v in values.items() if v is not None]
    w = sum(p for _, p in pairs)
    if not pairs or not w:
        return None
    v = sum(x * p for x, p in pairs) / w
    return round(v, digits) if digits else round(v)


def _round(v):
    return None if v is None else round(v)


def share(a, b):
    return ratio(a, b, 1, 4)

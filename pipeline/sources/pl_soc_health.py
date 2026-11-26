"""Health care by powiat from GUS BDL: doctors and general-hospital beds, per 10,000 people.

BDL publishes counts by powiat; the rates are computed here from the counts and the BDL
population of the same year (31 Dec). Each variable's metadata (/variables/<id>) is cached
and checked against the expected name, so a renumbered variable fails loudly.

Life expectancy is left to the stats worker (BDL variables by powiat exist only for some years
and the blueprint assigns it to W2).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.source import Source, SourceInfo
from .pl_soc_common import bdl_download, slug

API = "https://bdl.stat.gov.pl/api/v1"
YEARS = (2025, 2024, 2023)  # newest first; the newest year with full powiat coverage is used
# key -> (variable id, words its slugged name must contain, label)
VARIABLES = {
    "doctors": ("74067", ("lekarze", "podstawowego"),
                "Doctors working (by main place of work)"),
    "hospital_beds": ("152354", ("szpitale_ogolne", "lozka"), "Beds in general hospitals"),
    "population": ("72305", ("ogolem",), "Population on 31 December"),
}


def unit_to_powiat(unit_id: str) -> str | None:
    """BDL level-5 unit id (12 digits) -> TERYT4 powiat code."""
    if len(unit_id) != 12 or not unit_id.isdigit():
        return None
    return unit_id[2:4] + unit_id[7:9]


def values_by_year(pages: list[dict]) -> dict[int, dict[str, float]]:
    """BDL /data/by-variable pages -> {year: {powiat: value}}."""
    out: dict[int, dict[str, float]] = {}
    for page in pages:
        for unit in page.get("results", []):
            code = unit_to_powiat(unit["id"])
            if code is None:
                continue
            for v in unit.get("values", []):
                if v.get("val") is not None:
                    out.setdefault(int(v["year"]), {})[code] = float(v["val"])
    return out


def per_10k(count: float | None, population: float | None) -> float | None:
    if count is None or not population:
        return None
    return round(count / population * 10000, 1)


class PlSocHealth(Source):
    info = SourceInfo(
        id="pl_soc_health",
        title="Doctors and hospital beds by powiat",
        publisher="Główny Urząd Statystyczny (GUS), Bank Danych Lokalnych",
        homepage="https://bdl.stat.gov.pl/bdl/start",
        license="GUS: reuse with attribution",
        description="Doctors working in health care (by main place of work) and beds in general hospitals in "
        "each powiat, as counts and per 10,000 people.",
        used_for=["Health lens", "People advisor"],
    )

    def _pages(self, var: str) -> list[Path]:
        query = "&".join(f"year={y}" for y in YEARS)
        url0 = f"{API}/data/by-variable/{var}?unit-level=5&{query}&page-size=100&format=json"
        first = bdl_download(self, url0 + "&page=0", f"data/{var}_p0.json", pause=6)
        total = json.loads(Path(first).read_text(encoding="utf-8"))["totalRecords"]
        paths = [first]
        for page in range(1, (total + 99) // 100):
            paths.append(bdl_download(self, f"{url0}&page={page}", f"data/{var}_p{page}.json", pause=6))
        return paths

    def _meta(self, var: str) -> dict:
        p = bdl_download(self, f"{API}/variables/{var}?format=json", f"meta/{var}.json", pause=6)
        return json.loads(Path(p).read_text(encoding="utf-8"))

    def fetch(self, force=False):
        for var, _, _ in VARIABLES.values():
            self._meta(var)
            self._pages(var)

    def process(self):
        data, files, labels = {}, [], {}
        for key, (var, words, label) in VARIABLES.items():
            meta = self._meta(var)
            name = " | ".join(meta.get(k, "") for k in ("n1", "n2", "n3", "n4", "n5") if meta.get(k))
            if not all(w in slug(name) for w in words):
                raise RuntimeError(f"BDL variable {var} is now {name!r}; expected {words}")
            labels[key] = name
            paths = self._pages(var)
            data[key] = values_by_year([json.loads(p.read_text(encoding="utf-8")) for p in paths])
            files += [f"meta/{var}.json"] + [f"data/{p.name}" for p in paths]
        years = {}
        for key in ("doctors", "hospital_beds"):
            full = [y for y in sorted(data[key], reverse=True) if len(data[key][y]) >= 370]
            if not full:
                raise RuntimeError(f"{key}: no year with powiat coverage")
            years[key] = full[0]
        rows: dict[str, dict] = {}
        for key, year in years.items():
            pop = data["population"].get(year, {})
            for code, count in data[key][year].items():
                r = rows.setdefault(code, {})
                r[key] = count
                r[key + "_per_10k"] = per_10k(count, pop.get(code))
        for r in rows.values():
            for key in years:
                r.setdefault(key, None)
                r.setdefault(key + "_per_10k", None)
        fields = {}
        for key, year in years.items():
            var = VARIABLES[key][0]
            fields[key] = {"label": VARIABLES[key][2], "unit": "persons" if key == "doctors" else "beds",
                           "year": year, "note": f"BDL variable {var}: {labels[key]}"}
            fields[key + "_per_10k"] = {"label": VARIABLES[key][2] + " per 10,000 people", "unit": "per 10000",
                                        "year": year,
                                        "note": f"{key} / BDL population (variable {VARIABLES['population'][0]}) "
                                                f"of 31 Dec {year} x 10,000"}
        return {
            "vintage": "GUS BDL: " + ", ".join(f"{k} {y}" for k, y in years.items()),
            "tables": {"health_powiat": {"level": "powiat", "fields": fields, "rows": dict(sorted(rows.items()))}},
            "notes": [
                "Rates per 10,000 people are computed from the BDL counts and the BDL population of the same year.",
                "Doctors are counted at their main place of work, in the powiat of that workplace: city powiats "
                "with big hospitals have high rates, their surrounding rural powiats low ones.",
                "Life expectancy by powiat is left to the stats worker (pl_stats_* sources).",
            ],
            "_files": files,
        }

"""Towns of Poland: every place with town rights, its TERYT code, population and position.

* The list, the TERYT code (type 1 = urban gmina, 4 = the town of an urban-rural gmina), the area and the population
  on 31 December 2025 come from GUS "Powierzchnia i ludnosc w przekroju terytorialnym w 2026 r.", Tabl. 20 (towns).
* The population on 30 June 2026 comes from the GUS half-year balance, table 11: the total of an urban gmina, or
  the urban total of an urban-rural gmina for its town.
* The position is the OpenStreetMap place node of the town (place=city|town), matched by its TERYT TERC code
  (`teryt:terc`, the town's 7-digit unit) or, failing that, by name within the town's gmina. OSM is used because
  the GUGiK name register (PRNG) hosts do not answer from the pipeline's network.
"""

from __future__ import annotations

import json
import unicodedata
import urllib.parse

from ..core.source import Source, SourceInfo
from ._pl_xlsx import read_xlsx
from .pl_stats_population import POPULATION_JUNE_PAGE, POPULATION_JUNE_URL, _sex_xlsx

GUS_URL = ("https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/7/23/1/"
           "powierzchnia_i_ludnosc_w_przekroju_terytorialnym_2026_2.xlsx")
GUS_PAGE = ("https://stat.gov.pl/obszary-tematyczne/ludnosc/ludnosc/"
            "powierzchnia-i-ludnosc-w-przekroju-terytorialnym-w-2026-r-,7,23.html")
GUS_FILE = "area-population-2026.xlsx"
JUNE_FILE = "population-2026-06-30.zip"
OVERPASS = "https://overpass-api.de/api/interpreter"
OSM_QUERY = ('[out:json][timeout:180];area["ISO3166-1"="PL"][admin_level=2]->.pl;'
             'node[place~"^(city|town)$"](area.pl);out;')
OSM_FILE = "osm_towns.json"


def fold(name: str) -> str:
    """Lower-case ASCII key: 'Łódź' -> 'lodz' (l-stroke folded before NFD, which does not decompose it)."""
    s = str(name or "").replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def parse_teryt(cell) -> str | None:
    """'126101 1' -> '1261011'."""
    s = str(cell or "").replace(" ", "")
    return s if len(s) == 7 and s.isdigit() else None


def gus_towns(rows: list[list]) -> list[dict]:
    out = []
    for r in rows:
        if not r or len(r) < 7:
            continue
        code = parse_teryt(r[0])
        if not code or code[-1] not in "14":
            continue
        name = str(r[1]).strip()
        if name.startswith("m.st. "):
            name = name[len("m.st. "):]
        out.append({
            "code": code,
            "name": name,
            "gmina": code if code[-1] == "1" else code[:6] + "3",
            "powiat": code[:4],
            "powiat_rights": int(code[2:4]) >= 61,
            "area_km2": r[4] if isinstance(r[4], (int, float)) else None,
            "population": r[5] if isinstance(r[5], (int, float)) else None,
        })
    return out


def june_population(towns: list[dict], by_gmina: dict[str, dict]) -> dict[str, int | float | None]:
    """{town code: population on 30 June 2026}; type 4 takes the urban total of its type 3 gmina."""
    out = {}
    for t in towns:
        row = by_gmina.get(t["code"] if t["code"][-1] == "1" else t["code"][:6] + "3") or {}
        out[t["code"]] = row.get("population" if t["code"][-1] == "1" else "urban")
    return out


def match_osm(towns: list[dict], nodes: list[dict]) -> tuple[dict[str, tuple[float, float]], list[str]]:
    """{town code: (lon, lat)} and the names left without a position."""
    by_terc: dict[str, list] = {}
    by_name: dict[str, list] = {}
    for n in nodes:
        t = n.get("tags", {})
        terc = str(t.get("teryt:terc", "")).strip()
        if len(terc) == 7:
            by_terc.setdefault(terc[:6], []).append(n)
        by_name.setdefault(fold(t.get("name:pl") or t.get("name")), []).append(n)
    pos, missing = {}, []
    for town in towns:
        key = fold(town["name"])
        cands = [n for n in by_terc.get(town["code"][:6], []) if fold(n["tags"].get("name:pl") or n["tags"].get("name")) == key]
        if not cands:
            cands = [n for n in by_terc.get(town["code"][:6], [])]
            cands = cands if len(cands) == 1 else []
        if not cands:
            # Name match inside the same voivodeship (OSM's is_in tags are not reliable enough to test powiats).
            cands = [n for n in by_name.get(key, []) if str(n["tags"].get("teryt:terc", town["code"]))[:2] == town["code"][:2]]
            cands = cands if len(cands) == 1 else []
        if cands:
            pos[town["code"]] = (round(cands[0]["lon"], 5), round(cands[0]["lat"], 5))
        else:
            missing.append(f"{town['code']} {town['name']}")
    return pos, missing


class PlGeoPlaces(Source):
    info = SourceInfo(
        id="pl_geo_places",
        title="Towns of Poland: population on 30 June 2026 and position",
        publisher="Główny Urząd Statystyczny (GUS); OpenStreetMap contributors",
        homepage=GUS_PAGE,
        license="GUS: CC BY 4.0; OpenStreetMap: ODbL",
        description="Every town with town rights on 1 January 2026 (GUS Tabl. 20 of 'Area and population in the "
        "territorial profile in 2026': TERYT code, area, population on 31 December 2025), the population on 30 June "
        "2026 (GUS half-year balance, table 11), and the position of its OpenStreetMap place node.",
        used_for=["City banners", "City View towns"],
    )

    def fetch(self, force=False):
        self.download(GUS_URL, GUS_FILE, force=force, expect_binary=True)
        self.download(POPULATION_JUNE_URL, JUNE_FILE, force=force, expect_binary=True)
        url = OVERPASS + "?" + urllib.parse.urlencode({"data": OSM_QUERY})
        self.download(url, OSM_FILE, force=force)

    def process(self):
        towns = gus_towns(read_xlsx(self.raw_dir / GUS_FILE, "Tabl. 20"))
        june = june_population(towns, _sex_xlsx(self.raw_dir / JUNE_FILE))
        for t in towns:
            t["population_2025"] = t["population"]
            t["population"] = june.get(t["code"])
        no_june = [t["code"] for t in towns if t["population"] is None]
        if no_june:
            raise RuntimeError(f"{len(no_june)} towns have no 30 June 2026 population: {no_june[:5]}")
        osm = json.loads((self.raw_dir / OSM_FILE).read_text(encoding="utf-8"))
        pos, missing = match_osm(towns, osm.get("elements", []))
        points = []
        for t in towns:
            lon, lat = pos.get(t["code"], (None, None))
            points.append({
                "id": t["code"], "name": t["name"], "kind": "town", "lon": lon, "lat": lat,
                "props": {k: t[k] for k in ("gmina", "powiat", "powiat_rights", "area_km2", "population", "population_2025")},
            })
        print(f"    {len(points)} towns ({sum(t['powiat_rights'] for t in towns)} with powiat rights), "
              f"{len(pos)} placed from OSM; without a position: {missing[:6]}")
        return {
            "vintage": "GUS population 30 June 2026; towns on 1 January 2026, population 31 December 2025; "
                       "OSM place nodes as fetched",
            "_files": [JUNE_FILE, GUS_FILE, OSM_FILE],
            "tables": {
                "towns": {
                    "level": "town",
                    "fields": {
                        "population": {"label": "Population", "unit": "persons", "year": 2026, "note": "30 June 2026"},
                        "population_2025": {"label": "Population", "unit": "persons", "year": 2025,
                                            "note": "31 December 2025"},
                        "area_km2": {"label": "Area", "unit": "km2", "year": 2026, "note": "1 January 2026"},
                    },
                    "rows": {t["code"]: {"population": t["population"], "population_2025": t["population_2025"],
                                         "area_km2": t["area_km2"]} for t in towns},
                }
            },
            "points": points,
            "notes": [
                "rule: every town in GUS Tabl. 20 (towns with town rights on 1 January 2026).",
                "population: 30 June 2026 (" + POPULATION_JUNE_PAGE + "); a town of an urban-rural gmina takes the "
                "gmina's urban total. population_2025: 31 December 2025, Tabl. 20.",
                "Town code: TERYT7 of the town (type 1 = urban gmina, 4 = the town part of an urban-rural gmina); "
                "props.gmina is the gmina the town belongs to (type 1, or type 3 for the urban-rural gmina).",
                "powiat_rights: the town is a city with powiat rights (TERYT powiat number 61 or more).",
                f"Position: OSM place node (teryt:terc, else the name in the same voivodeship); "
                f"{len(missing)} towns without a match keep lon/lat null: {', '.join(missing) or 'none'}.",
            ],
        }

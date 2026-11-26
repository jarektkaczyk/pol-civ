"""Power plants of Poland: OpenStreetMap plants with curated official figures, offshore wind and nuclear.

Selection rule: every plant of 100 MW or more, and every solar farm of 50 MW or more, mapped in OSM as
`power=plant` (operating) or `construction:power=plant` (under construction or planned), with the
capacity in `plant:output:electricity`. Battery storage sites of that size are kept as `battery`
(storage, not generation). The offshore wind farms in the Polish Baltic lie outside the territorial
sea, so they are added from the curated list below with coordinates from Wikidata.

Curated overrides (OVERRIDES, keyed by OSM object) replace OSM's capacity, fuel, operator or status with
the figure the operator or regulator publishes; each carries its `ref` page. OSM tags lignite plants as
`coal`, so the lignite plants are named in LIGNITE.
"""

from __future__ import annotations

from collections import defaultdict

from ..core.source import Source, SourceInfo
from .pl_transport_util import (
    ODBL_NOTE, POLAND_AREA, el_lonlat, osm_elements, osm_timestamp, overpass, parse_mw, wikidata_entities,
)

OSM_QUERY = (f"[out:json][timeout:120];{POLAND_AREA}"
             '(nwr["power"="plant"](area.pl);nwr["construction:power"="plant"](area.pl););out center tags qt;')
# The Polish offshore wind areas lie beyond the territorial sea, outside OSM's Poland area: a bbox query
# (west edge 14.5 E keeps out the German farms off Rügen). Baltica 3 is mapped only as a tagged outline.
OFFSHORE_QUERY = ('[out:json][timeout:120];('
                  'nwr["power"="plant"]["plant:source"="wind"](54.6,14.5,55.6,19.5);'
                  'nwr["construction:power"="plant"]["plant:source"="wind"](54.6,14.5,55.6,19.5);'
                  'way(1560193204););out center tags qt;')
MIN_MW = 100.0
MIN_SOLAR_MW = 50.0

FUELS = {  # OSM plant:source (first value) -> fuel
    "coal": "hard_coal", "gas": "gas", "oil": "oil", "hydro": "hydro", "wind": "onshore_wind",
    "solar": "solar", "biomass": "biomass", "biogas": "biogas", "waste": "waste", "nuclear": "nuclear",
    "battery": "battery", "geothermal": "geothermal",
}
LIGNITE = {"way/592157961", "relation/13268627", "way/448844031"}  # Bełchatów, Turów, Pątnów

TAURON_2024 = ("https://www.tauron-wytwarzanie.pl/-/media/offer-documents/wytwarzanie/wydawnictwa/"
               "deklaracja-srodowiskowa-za-2024.ashx")
PGE_2025_REPORT = ("https://www.gkpge.pl/content/download/1c17c9bb500a8cc7ea488bc573451f3e/file/"
                   "pge_sz2025.pdf?contentId=231076&inLanguage=pol-PL&version=2")
_TAURON = {"operator": "TAURON Wytwarzanie S.A.", "ref": TAURON_2024, "mw_year": 2024}

# OSM object -> fields that replace OSM's, from operator and regulator pages (see `ref`).
OVERRIDES: dict[str, dict] = {
    "way/592157961": {
        "operator": "PGE G\u00f3rnictwo i Energetyka Konwencjonalna S.A.", "fuel": "lignite", "mw": 5097.0,
        "mw_year": 2025, "mw_note": "installed electrical capacity in the PGE Group management report for 2025",
        "ref": PGE_2025_REPORT,
    },
    "relation/9399159": {**_TAURON, "fuel": "hard_coal", "mw": 2255.0,
                         "mw_note": "Jaworzno III 1,345 MW plus the Nowe Jaworzno 910 MW unit, achievable capacity "
                                    "31 Dec 2024 (Jaworzno II, 189 MW, not included)"},
    "way/85146997": {**_TAURON, "fuel": "hard_coal", "mw": 905.0, "mw_note": "achievable capacity 31 Dec 2024"},
    "way/187420594": {**_TAURON, "fuel": "hard_coal", "mw": 306.0, "mw_note": "achievable capacity 31 Dec 2024"},
    "way/40157613": {**_TAURON, "fuel": "hard_coal", "mw": 460.0, "mw_note": "achievable capacity 31 Dec 2024"},
    "way/1583424363": {
        "name": "Lubiatowo-Kopalino nuclear power plant", "fuel": "nuclear", "mw": 3750.0, "status": "planned",
        "operator": "Polskie Elektrownie Jądrowe",
        "status_note": "3 x AP1000. Construction licence applied for (April 2026); early-works permit applied for "
                       "(November 2026); construction start planned 2028, unit 1 operation 2036.",
        "ref": "https://world-nuclear-news.org/articles/pej-applies-for-early-works-permit-for-nuclear-power-plant"},
    "relation/21402440": {
        "name": "Baltic Power offshore wind farm", "fuel": "offshore_wind", "status": "under_construction",
        "operator": "Baltic Power (ORLEN 51%, Northland Power 49%)",
        "status_note": "First power to the grid 10 July 2026; the last of 76 turbines installed 7 October 2026; "
                       "commercial operation being prepared (3 November 2026). Operator: up to 1.2 GW.",
        "ref": "https://balticpower.pl/en/"},
    "relation/21410256": {
        "name": "Baltica 2 offshore wind farm", "fuel": "offshore_wind", "status": "under_construction",
        "operator": "PGE and Ørsted",
        "status_note": "Offshore construction since May 2026; first power expected in the first half of 2027, full "
                       "commercial operation planned by the end of 2027.",
        "ref": "https://www.gov.pl/web/climate/baltica-2-enters-the-offshore-construction-phase--a-key-step-for-"
               "polands-energy-security"},
    "relation/21409513": {
        "name": "Bałtyk 2 offshore wind farm", "fuel": "offshore_wind", "status": "under_construction",
        "operator": "Equinor and Polenergia (50/50)", "mw": 720.0,
        "status_note": "Foundations about half complete (July 2026); first power 2027, full operation 2028.",
        "ref": "https://www.polenergia.pl/en/baltyk-2-3-turbine-foundations-halfway-complete/"},
    "relation/21409512": {
        "name": "Bałtyk 3 offshore wind farm", "fuel": "offshore_wind", "status": "under_construction",
        "operator": "Equinor and Polenergia (50/50)", "mw": 720.0,
        "status_note": "Built together with Bałtyk 2: first power 2027, full operation 2028.",
        "ref": "https://www.equinor.com/news/20250522-financial-close-for-baltyk-2-and-baltyk-3"},
    "way/1560193204": {
        "name": "Baltica 3 offshore wind farm", "fuel": "offshore_wind", "status": "planned", "mw": None,
        "operator": "PGE", "mw_note": "about 1 GW (no final investment decision)",
        "status_note": "Planned; no final investment decision; first-power deadline moved to the end of 2032.",
        "ref": "https://www.gramwzielone.pl/?p=20379857"},
    "way/1252341917": {
        "status_note": "Energa CCGT: first power to the grid July 2026; PSE confirmed its operational milestone "
                       "on 29 October 2026.",
        "ref": "https://www.biznesradar.pl/a/164970"},
    "way/377839973": {"status_note": "Energa CCGT under construction; turbine delivery planned for 2027.",
                      "ref": "https://grupa.energa.pl/en/publications/870609/"},
}
# OSM objects kept despite the size rule (outlines without a capacity tag).
ALWAYS = {"way/1560193204"}

# Plants not mapped in OSM; positions from Wikidata (P625) or a cited lonlat.
ADDITIONS: list[dict] = []

# Poland's total installed capacity, for the comparison note.
NATIONAL = {"mw": 77331, "date": "2025-12-31", "publisher": "URE national report 2026, data PSE S.A.",
            "ref": "https://www.ure.gov.pl/download/9/16381/RaportKrajowy2026.pdf"}


def fuel_of(tags: dict, osm_id: str) -> str:
    if osm_id in LIGNITE:
        return "lignite"
    if (tags.get("plant:method") or "") == "water-pumped-storage":
        return "pumped_storage"
    src = (tags.get("plant:source") or "").split(";")[0].strip()
    if not src:
        method = tags.get("plant:method") or ""
        src = "hydro" if "pumped" in method or "water" in method else ""
    return FUELS.get(src, src or "unknown")


def status_of(tags: dict) -> str:
    if tags.get("power") == "plant":
        return "operating"
    name = (tags.get("name") or "").lower()
    if "planned" in name or "planowan" in name or tags.get("proposed:power"):
        return "planned"
    return "under_construction"


def _dedupe_key(p: dict) -> tuple:
    return ((p["name"] or "").strip().lower(), p["props"]["mw"])


def select_plants(elements: list[dict], always: set[str] = frozenset()) -> list[dict]:
    """OSM plants that pass the size rule, as points (before overrides).

    A plant mapped twice (an outline way and a relation with the same name and capacity) is kept once,
    the relation winning."""
    out = []
    for el in elements:
        tags = el.get("tags") or {}
        osm_id = f"{el['type']}/{el['id']}"
        mw = parse_mw(tags.get("plant:output:electricity"))
        fuel = fuel_of(tags, osm_id)
        limit = MIN_SOLAR_MW if fuel == "solar" else MIN_MW
        if (mw is None or mw < limit) and osm_id not in always:
            continue
        ll = el_lonlat(el)
        if ll is None:
            continue
        sources = [s.strip() for s in (tags.get("plant:source") or "").split(";") if s.strip()]
        out.append({
            "id": f"plant:{osm_id}", "name": tags.get("name") or tags.get("operator") or f"Power plant {osm_id}",
            "kind": f"{fuel}_plant", "lon": round(ll[0], 5), "lat": round(ll[1], 5),
            "props": {"fuel": fuel, "fuels_osm": sources or None, "mw": round(mw, 1) if mw is not None else None,
                      "mw_source": "osm", "operator": tags.get("operator"), "status": status_of(tags),
                      "storage": fuel == "battery", "osm_id": osm_id, "ref": None,
                      "wikidata": tags.get("wikidata")},
        })
    best: dict[tuple, dict] = {}
    for p in out:
        k = _dedupe_key(p)
        if k not in best or p["props"]["osm_id"].startswith("relation/"):
            best[k] = p
    return [p for p in out if best[_dedupe_key(p)] is p]


def apply_overrides(points: list[dict], overrides: dict[str, dict]) -> list[str]:
    """Replace props from the curated table; returns the override keys that matched nothing."""
    by_osm = {p["props"]["osm_id"]: p for p in points}
    missing = []
    for osm_id, o in overrides.items():
        p = by_osm.get(osm_id)
        if p is None:
            missing.append(osm_id)
            continue
        for k, v in o.items():
            if k == "name":
                p["name"] = v
            else:
                p["props"][k] = v
        if "mw" in o:
            p["props"]["mw_source"] = "ref"
        if "fuel" in o:
            p["kind"] = f"{o['fuel']}_plant"
    return missing


def totals_by_fuel(points: list[dict]) -> dict[str, dict]:
    acc: dict[str, dict] = defaultdict(lambda: {"count": 0, "mw": 0.0})
    for p in points:
        if p["props"]["status"] != "operating" or p["props"]["mw"] is None:
            continue
        a = acc[p["props"]["fuel"]]
        a["count"] += 1
        a["mw"] += p["props"]["mw"]
    return {k: {"count": v["count"], "mw": round(v["mw"], 1)} for k, v in sorted(acc.items())}


class PlEnergyPlants(Source):
    info = SourceInfo(
        id="pl_energy_plants",
        title="Power plants of Poland (100 MW or more; solar 50 MW or more), offshore wind and nuclear",
        publisher="OpenStreetMap contributors; operators (PGE, Enea, Tauron, Orlen, Energa, Polenergia, PEJ), PSE",
        homepage="https://www.openstreetmap.org/",
        license="OSM: ODbL 1.0. " + ODBL_NOTE + " Curated figures: public operator and regulator pages (see ref).",
        description="Every power plant of 100 MW or more (solar farms from 50 MW) with fuel, installed capacity, "
        "operator and status, plus the Baltic offshore wind farms and the first nuclear plant site.",
        used_for=["Resources on the map (power plants)", "Energy advisor"],
    )

    OSM = "osm_power_plants.json"
    OFFSHORE = "osm_offshore_wind.json"
    WD = "wikidata.json"

    def _qids(self) -> list[str]:
        return [a["qid"] for a in ADDITIONS if a.get("qid")]

    def fetch(self, force=False):
        overpass(self, OSM_QUERY, self.OSM, force=force)
        overpass(self, OFFSHORE_QUERY, self.OFFSHORE, force=force)
        if self._qids():
            wikidata_entities(self, self._qids(), self.WD, force=force)

    def process(self):
        path = self.raw_dir / self.OSM
        points = select_plants(osm_elements([path, self.raw_dir / self.OFFSHORE]), ALWAYS)
        missing = apply_overrides(points, OVERRIDES)
        wd = wikidata_entities(self, self._qids(), self.WD) if self._qids() else {}
        notes = []
        for a in ADDITIONS:
            ll = a.get("lonlat") or (wd.get(a.get("qid"), {}) or {}).get("lonlat")
            if ll is None:
                notes.append(f"{a['name']}: no coordinates; position null")
            props = {k: v for k, v in a.items() if k not in ("id", "name", "kind", "lonlat")}
            props.setdefault("storage", False)
            props.setdefault("mw_source", "ref")
            points.append({"id": a["id"], "name": a["name"], "kind": f"{a['fuel']}_plant",
                           "lon": round(ll[0], 5) if ll else None, "lat": round(ll[1], 5) if ll else None,
                           "props": props})
        points.sort(key=lambda p: -(p["props"]["mw"] or 0))
        stamp = osm_timestamp([path, self.raw_dir / self.OFFSHORE])
        totals = totals_by_fuel(points)
        gen_total = round(sum(v["mw"] for k, v in totals.items() if k != "battery"), 1)
        if missing:
            notes.append("Overrides that matched no OSM plant (check the OSM ids): " + ", ".join(missing))
        nat = NATIONAL
        compare = (f"Operating plants listed here total {gen_total:,.0f} MW of generation; Poland's installed "
                   f"capacity was {nat['mw']:,.0f} MW on {nat['date']} ({nat['publisher']}, {nat['ref']}). The "
                   "difference is mostly small wind and solar farms, rooftop solar and industrial plants under the "
                   "size rule." if nat["mw"] else f"Operating plants listed here total {gen_total:,.0f} MW.")
        return {
            "vintage": f"OpenStreetMap extract {stamp[:10] if stamp else '?'}, PGE report 2025, other curated figures as of 2026-11",
            "tables": {"plants_by_fuel": {
                "level": "country",
                "fields": {f"{k}_mw": {"label": f"Operating plants in this list: {k}", "unit": "MW", "year": 2026}
                           for k in totals},
                "rows": {"PL": {f"{k}_mw": v["mw"] for k, v in totals.items()}},
            }},
            "points": points,
            "totals_by_fuel": totals,
            "national_installed": nat,
            "notes": [
                f"Rule: OSM power=plant or construction:power=plant in Poland with plant:output:electricity of "
                f"{MIN_MW:g} MW or more ({MIN_SOLAR_MW:g} MW for solar), plus the curated offshore wind farms and "
                "nuclear site. mw_source 'osm' = OSM tag, 'ref' = the operator or regulator page in ref.",
                "Fuel: the first value of plant:source (pumped_storage when plant:method=water-pumped-storage); OSM "
                "'coal' is hard coal except the lignite plants "
                "(Bełchatów, Turów, Pątnów). Multi-fuel plants keep all values in fuels_osm.",
                "Status: operating = power=plant; under_construction or planned = construction:power=plant or the "
                "curated status. battery = storage (storage: true), left out of generation totals.",
                compare,
                f"OSM data as of {stamp}. {ODBL_NOTE}",
            ] + notes,
            "_files": [self.OSM, self.OFFSHORE] + ([self.WD] if self._qids() else []),
        }

"""Oil and gas in Poland: Baltic Pipe landfall, main gas and oil fields, refineries (curated).

Selection rule: the Baltic Pipe landfall, the largest domestic gas fields of the Carpathian foreland
(Przemyśl) and of Wielkopolska (Kościan-Brońsko), the two largest oil fields in the Polish Lowlands
(Lubiatów-Międzychód-Grotów, Barnówko-Mostno-Buszewo) and the two crude oil refineries (Płock, Gdańsk).
The LNG terminals are in `pl_transport_ports`.

Positions: Wikidata P625 by QID, or the centre of an OSM object (the field's production site or the
pipeline's receiving station) where Wikidata has no coordinate.
"""

from __future__ import annotations

from ..core.source import Source, SourceInfo
from .pl_mines import osm_query
from .pl_transport_util import (
    ODBL_NOTE, curated_points, el_lonlat, osm_elements, osm_timestamp, overpass, wikidata_entities,
)

ORLEN_2022 = "https://raportzintegrowany2022.orlen.pl/en/operating-segments/operating-segments-in-2022/refining/"
ORLEN_GAS = ("https://www.orlen.pl/en/about-the-company/media/press-releases/current/2024/December-2024/"
             "increasing-domestic-natural-gas-production-orlen-enhances-extraction-capacity")

SITES: list[dict] = [
    {"id": "gas:baltic_pipe", "name": "Baltic Pipe landfall (Niechorze-Pogorzelica)", "kind": "gas_pipeline_landfall",
     "osm": "way/971293355", "operator": "Gaz-System", "status": "operating", "capacity_bcm": 10.0,
     "status_note": "Norway-Denmark-Poland gas pipeline, in service since 2022; capacity 10 bcm a year. "
                    "Placed at its receiving station by the landfall.",
     "ref": "https://en.wikipedia.org/wiki/Baltic_Pipe"},
    {"id": "gas:przemysl", "name": "Przemyśl gas field", "kind": "gas_field", "osm": "way/236316973",
     "operator": "ORLEN", "status": "operating", "output": None,
     "position_note": "placed at the Przemyśl Wschód production site", "ref": None},
    {"id": "gas:koscian_bronsko", "name": "Kościan-Brońsko gas field", "kind": "gas_field", "osm": "way/543270730",
     "operator": "ORLEN", "status": "operating", "output": None,
     "status_note": "reserves originally about 35 bcm; a new compressor station added in 2024", "ref": ORLEN_GAS},
    {"id": "oil:lmg", "name": "Lubiatów-Międzychód-Grotów oil and gas field", "kind": "oil_field",
     "osm": "way/180685424", "operator": "ORLEN", "status": "operating", "output": None,
     "position_note": "placed at the Lubiatów production site", "ref": None},
    {"id": "oil:bmb", "name": "Barnówko-Mostno-Buszewo oil field", "kind": "oil_field", "qid": "Q4862040",
     "expect": "Barnówko", "operator": "ORLEN", "status": "operating", "output": None, "ref": None},
    {"id": "refinery:plock", "name": "ORLEN refinery Płock", "kind": "refinery", "qid": "Q7265108",
     "expect": "Płock", "operator": "ORLEN S.A.", "status": "operating", "capacity_mt": 16.3,
     "capacity_note": "crude processing capacity, million tonnes a year", "ref": ORLEN_2022},
    {"id": "refinery:gdansk", "name": "Gdańsk refinery", "kind": "refinery", "qid": "Q5529384",
     "expect": "Gda", "operator": "ORLEN (70%), Saudi Aramco (30%)", "status": "operating", "capacity_mt": 10.5,
     "capacity_note": "crude processing capacity, million tonnes a year", "ref": ORLEN_2022},
]


class PlEnergyOilGas(Source):
    info = SourceInfo(
        id="pl_energy_oilgas",
        title="Oil and gas in Poland: Baltic Pipe, main fields, refineries (curated)",
        publisher="ORLEN, Gaz-System (via the cited pages); positions from Wikidata and OpenStreetMap",
        homepage="https://www.orlen.pl/en",
        license="Public company information (see ref per site); Wikidata CC0; OSM ODbL 1.0",
        description="The Baltic Pipe landfall, the main domestic gas and oil fields and the two crude oil refineries.",
        used_for=["Resources on the map (oil, gas)", "Energy and Resources advisor"],
    )

    WD = "wikidata.json"
    OSM = "osm_sites.json"

    def _qids(self):
        return [s["qid"] for s in SITES if s.get("qid")]

    def _osm_ids(self):
        return [s["osm"] for s in SITES if s.get("osm")]

    def fetch(self, force=False):
        wikidata_entities(self, self._qids(), self.WD, force=force)
        overpass(self, osm_query(self._osm_ids()), self.OSM, force=force)

    def process(self):
        wd = wikidata_entities(self, self._qids(), self.WD)
        osm = {f"{e['type']}/{e['id']}": e for e in osm_elements([self.raw_dir / self.OSM])}
        items = []
        for s in SITES:
            s = dict(s)
            if s.get("osm"):
                el = osm.get(s["osm"])
                s["lonlat"] = el_lonlat(el) if el else None
                s["osm_id"] = s.pop("osm")
            items.append(s)
        points, problems = curated_points(items, wd)
        for p in points:
            p["props"]["wikidata"] = p["props"].pop("qid", None)
        return {
            "vintage": "Curated as of 2026-11 (ORLEN, Gaz-System)",
            "points": points,
            "notes": [
                "Rule: Baltic Pipe landfall; the largest domestic gas fields (Przemyśl, Kościan-Brońsko); the two "
                "largest oil fields (LMG, BMB); the Płock and Gdańsk refineries.",
                "Field output: ORLEN does not publish output per field; PIG-PIB's 'Bilans zasobów złóż kopalin' (data "
                "2025) has it, but only as PDF on a host that was not reachable; output stays null. ORLEN produces "
                "about 3.5 bcm of gas a year from Polish fields.",
                "Baltic Pipe: Gaz-System's pages could not be read by script; the capacity and landfall come from the "
                "Wikipedia article (ref).",
                f"Positions: Wikidata P625 (refineries, BMB) or OSM object centres. {ODBL_NOTE}",
                f"OSM data as of {osm_timestamp([self.raw_dir / self.OSM])}.",
            ] + problems,
            "_files": [self.WD, self.OSM],
        }

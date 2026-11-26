"""Eurostat GISCO Local Administrative Units (LAU) 2024: the outlines of the Polish gminy."""

from __future__ import annotations

import json

from ..core.geo import topojson_arcs, topojson_rings
from ..core.source import Source, SourceInfo

YEAR = 2024
BASE = "https://gisco-services.ec.europa.eu/distribution/v2/lau"
NAME = f"LAU_RG_01M_{YEAR}_4326"
URL = f"{BASE}/topojson/{NAME}.json"
FILE = f"{YEAR}/{NAME}.json"
NOTES_URL = f"{BASE}/lau-{YEAR}-release-notes.txt"
NOTES_FILE = f"{YEAR}/lau-{YEAR}-release-notes.txt"


def teryt6_of_lau(lau: str) -> str:
    """TERYT voivodeship + powiat + gmina numbers (6 digits, no type digit) of a Polish LAU id.

    LAU id = "10" + region (2) + voivodeship (2) + subregion (2) + powiat (3) + gmina (2), e.g. 1001121216101
    (Krakow) -> 126101.
    """
    return lau[4:6] + lau[9:11] + lau[11:13]


class PlGeoLau(Source):
    info = SourceInfo(
        id="pl_geo_lau",
        title=f"Local Administrative Units (LAU) {YEAR}, 1:1 million",
        publisher="Eurostat GISCO",
        homepage="https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/local-administrative-units",
        license="(c) EuroGeographics for the administrative boundaries. Free reuse with attribution (Eurostat "
        "GISCO terms of use).",
        description=f"Outlines of the 2,477 Polish gminy as of 1 January {YEAR}, at 1:1 million. For Poland the LAU "
        "code is '10' plus the GUS statistical unit id without its last digit, so it holds the gmina's TERYT "
        "voivodeship, powiat and gmina numbers but not the TERYT type digit (that comes from the GUS unit "
        "register, source pl_geo_teryt). Powiat and voivodeship borders on the map are the outer edges of "
        "their gminy.",
        used_for=["Land of Poland vs sea and neighbours", "Gmina, powiat and voivodeship of each hex"],
    )

    def fetch(self, force=False):
        self.download(URL, FILE, force=force)
        self.download(NOTES_URL, NOTES_FILE, force=force)

    def process(self):
        topo = json.loads((self.raw_dir / FILE).read_text(encoding="utf-8"))
        arcs = topojson_arcs(topo)
        gminy = []
        for obj in topo["objects"].values():
            for geom in obj.get("geometries", []):
                p = geom.get("properties") or {}
                if p.get("CNTR_CODE") != "PL":
                    continue
                rings = [[(round(x, 5), round(y, 5)) for x, y in r] for r in topojson_rings(arcs, geom)]
                lau = str(p.get("LAU_ID") or p.get("GISCO_ID", "")).removeprefix("PL_")
                gminy.append({
                    "lau": lau,
                    "teryt6": teryt6_of_lau(lau),
                    "name": p.get("LAU_NAME"),
                    "area_km2": p.get("AREA_KM2"),
                    "rings": rings,
                })
        gminy.sort(key=lambda g: g["teryt6"])
        bad = [g["lau"] for g in gminy if len(g["lau"]) != 13 or not g["lau"].isdigit() or not g["lau"].startswith("10")]
        if bad:
            raise ValueError(f"LAU {YEAR}: {len(bad)} Polish LAU ids are not 13-digit codes '10...': {bad[:5]}")
        if len({g["teryt6"] for g in gminy}) != len(gminy):
            raise ValueError(f"LAU {YEAR}: duplicate TERYT voivodeship+powiat+gmina numbers")
        print(f"    {len(gminy)} Polish gminy in LAU {YEAR}")
        return {
            "vintage": f"LAU {YEAR} (1 January {YEAR}), 1:1 million",
            "_files": [FILE, NOTES_FILE],
            "year": YEAR,
            "gminy": gminy,
        }

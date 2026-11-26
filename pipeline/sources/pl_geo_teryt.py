"""The territorial units of Poland in force in the newest year, from the GUS Local Data Bank (BDL) unit register.

BDL unit ids are 12 digits: level/region (2), voivodeship (2), subregion (2), powiat (3), gmina (2), type (1).
The TERYT code is voivodeship + the last two powiat digits (+ gmina + type for a gmina).
"""

from __future__ import annotations

import json
import re
import time

from ..core.source import Source, SourceInfo

YEAR = 2026
API = "https://bdl.stat.gov.pl/api/v1/units/search"
PAGE = 100
LEVELS = {2: "voivodeship", 5: "powiat", 6: "gmina"}
# BDL "kind" of a level-6 unit: 1 urban gmina, 2 rural gmina, 3 urban-rural gmina (the TERYT type digit);
# 4 and 5 are the town and rural parts of an urban-rural gmina, 8 and 9 city districts (not gminy).
GMINA_KINDS = {"1": "urban", "2": "rural", "3": "urban-rural"}
PAUSE_S = 3.0  # stay well inside the anonymous BDL limits (its firewall blocks bursts)
# The search endpoint stops at 2,000 records (page * size), so gminy are fetched one kind at a time.
QUERIES = [(2, None), (5, None)] + [(6, k) for k in GMINA_KINDS]


def teryt_of(bdl_id: str, level: int) -> str:
    woj, pow_, gm, typ = bdl_id[2:4], bdl_id[7:9], bdl_id[9:11], bdl_id[11]
    return woj if level == 2 else woj + pow_ if level == 5 else woj + pow_ + gm + typ


def clean_name(raw: str) -> str:
    """BDL labels a few units with their history: 'Walbrzych od 2013', 'M.st.Warszawa od 2002'."""
    name = re.sub(r"\s+od \d{4}$", "", raw.strip())
    return "Warszawa" if name == "M.st.Warszawa" else name


def voivodeship_name(raw: str) -> str:
    """'KUJAWSKO-POMORSKIE' -> 'Kujawsko-Pomorskie'."""
    return "-".join(p[:1].upper() + p[1:].lower() for p in raw.strip().split("-"))


class PlGeoTeryt(Source):
    info = SourceInfo(
        id="pl_geo_teryt",
        title=f"Territorial units of Poland in {YEAR} (TERYT codes)",
        publisher="Statistics Poland (GUS), Local Data Bank (BDL) API",
        homepage="https://bdl.stat.gov.pl/bdl/start",
        license="Public data (GUS terms of use: free reuse with attribution)",
        description=f"The voivodeships, powiaty and gminy in force in {YEAR}, with names and the gmina type "
        "(urban, rural, urban-rural), from the BDL unit register. Gives every gmina its 7-digit TERYT code "
        "(the type digit changes when a village gets town rights).",
        used_for=["TERYT codes and names of gminy, powiaty and voivodeships"],
    )

    def _page(self, level: int, kind: str | None, page: int) -> str:
        return f"{YEAR}/level{level}{'_kind' + kind if kind else ''}_page{page:03d}.json"

    def fetch(self, force=False):
        for level, kind in QUERIES:
            page = 0
            while True:
                rel = self._page(level, kind, page)
                cached = (self.raw_dir / rel).exists() and not force
                url = (f"{API}?level={level}&year={YEAR}{'&kind=' + kind if kind else ''}"
                       f"&page-size={PAGE}&page={page}&format=json")
                path = self.download(url, rel, force=force, headers={"Accept": "application/json"})
                if not cached:
                    time.sleep(PAUSE_S)
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    self.discard(rel)
                    raise RuntimeError(f"BDL answered {url} with something other than JSON (blocked or busy?)")
                if (page + 1) * PAGE >= doc["totalRecords"]:
                    break
                page += 1

    def process(self):
        units = {lv: [] for lv in LEVELS}
        files = []
        for level, kind in QUERIES:
            pattern = f"level{level}{'_kind' + kind if kind else ''}_page*.json"
            for path in sorted((self.raw_dir / str(YEAR)).glob(pattern)):
                files.append(f"{YEAR}/{path.name}")
                units[level] += json.loads(path.read_text(encoding="utf-8"))["results"]
        voivodeships = sorted(
            ({"code": teryt_of(u["id"], 2), "name": voivodeship_name(u["name"])} for u in units[2]),
            key=lambda u: u["code"],
        )
        powiaty = sorted(({"code": teryt_of(u["id"], 5), "name": clean_name(u["name"])} for u in units[5]), key=lambda u: u["code"])
        gminy = sorted(
            ({"code": teryt_of(u["id"], 6), "name": clean_name(u["name"]), "type": GMINA_KINDS[u["kind"]]}
             for u in units[6] if u["kind"] in GMINA_KINDS),
            key=lambda u: u["code"],
        )
        if len({g["code"][:6] for g in gminy}) != len(gminy):
            raise ValueError("BDL: two gminy share voivodeship+powiat+gmina numbers")
        print(f"    {YEAR}: {len(voivodeships)} voivodeships, {len(powiaty)} powiaty, {len(gminy)} gminy")
        return {
            "vintage": f"BDL unit register, units in force in {YEAR}",
            "_files": files,
            "year": YEAR,
            "voivodeships": voivodeships,
            "powiaty": powiaty,
            "gminy": gminy,
        }

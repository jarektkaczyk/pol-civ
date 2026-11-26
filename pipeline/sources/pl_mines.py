"""Active mines of Poland, with smelters and heritage mines (curated).

Selection rule: every hard coal mine active on 31 Dec 2025 (Ministry of Industry report to the European
Commission on state aid to hard coal mining in 2025), mines closed during 2025, the lignite mines with
2025 output, KGHM's copper and silver mines and smelters, the Kłodawa rock salt mine, the sulphur mines,
and the historic mines on the UNESCO list (Wieliczka, Bochnia, Tarnowskie Góry).

Output per mine is raw coal (węgiel surowy) or lignite mined in 2025, from the 2025 methane reports that
mine operators file with the State Mining Authority (WUG) under Regulation (EU) 2024/1787, art. 20.
Company totals (saleable coal, copper, silver) are in `companies`. Positions: Wikidata P625 by QID, or the
centre of an OSM object where Wikidata has no coordinate.
"""

from __future__ import annotations

import re
import unicodedata

from ..core.source import Source, SourceInfo
from .pl_transport_util import (
    ODBL_NOTE, curated_points, el_lonlat, osm_elements, osm_timestamp, overpass, wikidata_entities,
)

EC_2025 = "https://www.gov.pl/attachment/f83b64ed-0cc8-4e47-b952-21e95fc6dbc0"
WUG_KWK = "https://www.gov.pl/web/wug/kwk"
KGHM_2025 = ("https://kghm.com/sites/default/files/2026-01/"
             "Raport%20produkcyjno-sprzeda%C5%BCowy_grudzie%C5%84%202025.pdf")
SEJM_SULPHUR = "https://api.sejm.gov.pl/sejm/term10/interpellations/attachment/ATTDRZKMK/i15281-o1.pdf"
JSW_WUG = "https://www.gov.pl/attachment/534d338f-2c01-40d3-9a47-52762b9a79c4"


def _slug(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _coal(qid, name, expect, operator, company, raw_t, ref, **kw):
    return {"id": "mine:" + _slug(name.replace("KWK ", "").replace("ZG ", "")), "name": name, "kind": "coal_mine", "qid": qid,
            "expect": expect, "commodity": kw.pop("commodity", "hard_coal"), "operator": operator,
            "company": company, "status": kw.pop("status", "operating"),
            "output": round(raw_t / 1e6, 3) if raw_t is not None else None,
            "output_unit": "Mt raw coal" if raw_t is not None else None,
            "output_year": 2025 if raw_t is not None else None, "ref": ref, **kw}


MINES: list[dict] = [
    # PGG S.A.: seven mines (EC 2025 report); raw coal from each mine's WUG report.
    _coal("Q11743352", "KWK ROW", "Chwałowice", "Polska Grupa Górnicza S.A.", "pgg", 8009573,
          "https://www.gov.pl/attachment/738951c6-77e1-45f4-aad0-ede6d2e3eccf",
          position_note="four sections (Marcel, Chwałowice, Rydułtowy, Jankowice); placed at Ruch Chwałowice"),
    _coal("Q26877518", "KWK Ruda", "Ruda", "Polska Grupa Górnicza S.A.", "pgg", 2656946,
          "https://www.gov.pl/attachment/4e146748-980e-4f45-98d3-190bc4f299a6"),
    _coal("Q4939277", "KWK Bolesław Śmiały", "Bolesław", "Polska Grupa Górnicza S.A.", "pgg", 1820341,
          "https://www.gov.pl/attachment/f6e3b5e6-1975-47b6-9fa7-dd865227c8a0"),
    _coal("Q7190349", "KWK Piast-Ziemowit", "Piast", "Polska Grupa Górnicza S.A.", "pgg", 3298816,
          "https://www.gov.pl/attachment/476d246b-81b7-4b62-8349-e10e99cff125",
          position_note="two sections (Piast, Ziemowit); placed at Ruch Piast"),
    _coal("Q111080642", "KWK Staszic-Wujek", "Staszic", "Polska Grupa Górnicza S.A.", "pgg", 1848551,
          "https://www.gov.pl/attachment/6c1603c1-9e7f-4b2f-9c38-ed2784f9cf3e"),
    _coal("Q48840663", "KWK Mysłowice-Wesoła", "Mysłowice", "Polska Grupa Górnicza S.A.", "pgg", 1924049,
          "https://www.gov.pl/attachment/e6af6fb8-ba61-41da-9272-2b114c3a58c0"),
    _coal("Q21169771", "KWK Sośnica", "Sośnica", "Polska Grupa Górnicza S.A.", "pgg", 1504184,
          "https://www.gov.pl/attachment/6b852c54-8dfa-4ae4-8565-689be16669f7"),
    # JSW S.A.: coking coal; raw coal from JSW's WUG report (two-section mines summed).
    _coal("Q11743345", "KWK Borynia-Zofiówka", "Borynia", "Jastrzębska Spółka Węglowa S.A.", "jsw", 3830039 + 4056284,
          JSW_WUG, commodity="coking_coal", output_note="Ruch Borynia 3,830,039 t + Ruch Zofiówka 4,056,284 t"),
    _coal("Q11743372", "KWK Knurów-Szczygłowice", "Knurów", "Jastrzębska Spółka Węglowa S.A.", "jsw",
          3715364 + 2537644, JSW_WUG, commodity="coking_coal",
          output_note="Ruch Knurów 3,715,364 t + Ruch Szczygłowice 2,537,644 t"),
    _coal("Q3507220", "KWK Pniówek", "Pniówek", "Jastrzębska Spółka Węglowa S.A.", "jsw", 7140255, JSW_WUG,
          commodity="coking_coal"),
    _coal("Q4985173", "KWK Budryk", "Budryk", "Jastrzębska Spółka Węglowa S.A.", "jsw", 3907825, JSW_WUG,
          commodity="coking_coal"),
    _coal("Q3507237", "LW Bogdanka", "Bogdanka", "Lubelski Węgiel Bogdanka S.A.", "bogdanka", 11555522.5,
          "https://www.gov.pl/attachment/f4ab8270-571a-4274-82bd-542e1072fdaa"),
    # PKW S.A. (ex-Tauron Wydobycie): one mine, three mining plants; no per-plant output published.
    _coal("Q7550044", "ZG Sobieski", "Sobieski", "Południowy Koncern Węglowy S.A.", "pkw", None, EC_2025),
    _coal("Q6154491", "ZG Janina", "Janina", "Południowy Koncern Węglowy S.A.", "pkw", None, EC_2025),
    _coal("Q11743346", "ZG Brzeszcze", "Brzeszcze", "Południowy Koncern Węglowy S.A.", "pkw", None, EC_2025),
    _coal("Q11743403", "KWK Silesia", "Silesia", "PG Silesia Sp. z o.o.", None, None, EC_2025),
    _coal("Q9912077", "KWK Bobrek", "Bobrek", "Węglokoks Kraj S.A.", "weglokoks", None, EC_2025, status="closed",
          status_note="last coal hoisted on 30 Dec 2025"),
    # Lignite: tonnage from the WUG 2025 reports of the open-pit mines.
    {"id": "mine:belchatow", "name": "KWB Bełchatów (fields Bełchatów and Szczerców)", "kind": "lignite_mine",
     "qid": "Q4900408", "expect": "Bełchatów", "commodity": "lignite", "operator": "PGE GiEK S.A.",
     "status": "operating", "output": 31.059, "output_unit": "Mt lignite", "output_year": 2025,
     "output_note": "Pole Bełchatów 0.601 Mt + Pole Szczerców 30.458 Mt",
     "position_note": "placed at the Bełchatów field; the Szczerców field lies to its west",
     "ref": "https://www.gov.pl/attachment/4d224113-dc30-4865-a45b-de240b46397c"},
    {"id": "mine:turow", "name": "KWB Turów", "kind": "lignite_mine", "qid": "Q7856623", "expect": "Turów",
     "commodity": "lignite", "operator": "PGE GiEK S.A.", "status": "operating", "output": 7.014,
     "output_unit": "Mt lignite", "output_year": 2025,
     "ref": "https://www.gov.pl/attachment/1d7765e6-54da-455d-a7c1-83f13d05ee12"},
    {"id": "mine:konin", "name": "KWB Konin (open pit Tomisławice)", "kind": "lignite_mine",
     "qid": "Q6429370", "expect": "Konin", "position_note": "placed at the KWB Konin item", "commodity": "lignite", "operator": "PAK KWB Konin S.A.",
     "status": "closing", "status_note": "the only Konin open pit mined in 2025", "output": 1.754,
     "output_unit": "Mt lignite", "output_year": 2025,
     "ref": "https://www.gov.pl/attachment/9e75960f-ca77-45ef-abe2-a7cff84fdf56"},
    {"id": "mine:sieniawa", "name": "KWB Sieniawa", "kind": "lignite_mine", "osm": "way/469447518",
     "commodity": "lignite", "operator": "Kopalnia Węgla Brunatnego Sieniawa S.A.", "status": "operating",
     "output": None, "output_unit": None, "output_year": None, "ref": "https://www.gov.pl/web/wug/kwb",
     "output_note": "no 2025 WUG report found"},
    # KGHM: per-mine output is not published; company output in `companies`.
    {"id": "mine:lubin", "name": "ZG Lubin", "kind": "copper_mine", "qid": "Q6695325", "expect": "Lubin",
     "commodity": "copper_ore", "operator": "KGHM Polska Miedź S.A.", "company": "kghm", "status": "operating",
     "output": None, "output_unit": None, "output_year": None, "ref": "https://kghm.com/en/node/1368"},
    {"id": "mine:rudna", "name": "ZG Rudna", "kind": "copper_mine", "qid": "Q7377054", "expect": "Rudna",
     "commodity": "copper_ore", "operator": "KGHM Polska Miedź S.A.", "company": "kghm", "status": "operating",
     "output": None, "output_unit": None, "output_year": None, "ref": "https://kghm.com/en/node/1368"},
    {"id": "mine:polkowice_sieroszowice", "name": "ZG Polkowice-Sieroszowice", "kind": "copper_mine",
     "qid": "Q11794512", "expect": "Polkowice", "commodity": "copper_ore", "operator": "KGHM Polska Miedź S.A.",
     "company": "kghm", "status": "operating", "output": None, "output_unit": None, "output_year": None,
     "ref": "https://kghm.com/en/node/1368"},
    {"id": "mine:glogow_gleboki", "name": "Głogów Głęboki-Przemysłowy (shaft GG-1)", "kind": "copper_mine",
     "osm": "way/142416873", "commodity": "copper_ore", "operator": "KGHM Polska Miedź S.A.", "company": "kghm",
     "status": "operating", "status_note": "deposit mined from the Rudna and Polkowice-Sieroszowice workings",
     "output": None, "output_unit": None, "output_year": None, "ref": "https://kghm.com/en/node/1368"},
    {"id": "smelter:glogow", "name": "Huta Miedzi Głogów", "kind": "copper_smelter", "qid": "Q11710329",
     "expect": "Głogów", "commodity": "copper_smelter", "operator": "KGHM Polska Miedź S.A.", "company": "kghm",
     "status": "operating", "output": None, "output_unit": None, "output_year": None, "ref": KGHM_2025},
    {"id": "smelter:legnica", "name": "Huta Miedzi Legnica", "kind": "copper_smelter", "qid": "Q9295176",
     "expect": "Legnica", "commodity": "copper_smelter", "operator": "KGHM Polska Miedź S.A.", "company": "kghm",
     "status": "operating", "output": None, "output_unit": None, "output_year": None, "ref": None},
    {"id": "smelter:cedynia", "name": "Huta Miedzi Cedynia", "kind": "copper_smelter", "osm": "way/104903018",
     "commodity": "copper_wire_rod", "operator": "KGHM Polska Miedź S.A.", "company": "kghm",
     "status": "operating", "output": None, "output_unit": None, "output_year": None, "ref": None},
    # Salt and sulphur.
    {"id": "mine:klodawa", "name": "Kopalnia Soli Kłodawa", "kind": "salt_mine", "qid": "Q6454933",
     "expect": "Kłodawa", "commodity": "salt", "operator": "Kopalnia Soli Kłodawa S.A.", "status": "operating",
     "output": None, "output_unit": None, "output_year": None, "ref": "https://sol-klodawa.com.pl/"},
    {"id": "mine:osiek", "name": "Kopalnia Siarki Osiek", "kind": "sulphur_mine", "osm": "way/307915964",
     "commodity": "sulphur", "operator": "Grupa Azoty Siarkopol S.A.", "status": "operating",
     "output": 293.4, "output_unit": "kt sulphur", "output_year": 2024, "ref": SEJM_SULPHUR},
    {"id": "mine:basznia", "name": "Kopalnia Siarki Basznia", "kind": "sulphur_mine", "osm": "way/281345264",
     "commodity": "sulphur", "operator": "Polska Siarka sp. z o.o.", "status": "operating",
     "output": 40.65, "output_unit": "kt sulphur", "output_year": 2024, "ref": SEJM_SULPHUR},
    # Historic mines kept as heritage (UNESCO).
    {"id": "mine:wieliczka", "name": "Kopalnia Soli Wieliczka", "kind": "historic_mine", "qid": "Q454019",
     "expect": "Wieliczka", "commodity": "salt", "operator": "Kopalnia Soli Wieliczka S.A.", "status": "historic",
     "output": None, "output_unit": None, "output_year": None, "ref": "https://www.wieliczka-saltmine.com/"},
    {"id": "mine:bochnia", "name": "Kopalnia Soli Bochnia", "kind": "historic_mine", "qid": "Q4936252",
     "expect": "Bochnia", "commodity": "salt", "operator": "Kopalnia Soli Bochnia Sp. z o.o.", "status": "historic",
     "output": None, "output_unit": None, "output_year": None, "ref": "https://kopalnia-bochnia.pl/"},
    {"id": "mine:tarnowskie_gory", "name": "Zabytkowa Kopalnia Srebra w Tarnowskich Górach", "kind": "historic_mine",
     "qid": "Q48841031", "expect": "Tarnowskich", "commodity": "silver_lead_zinc",
     "operator": "Stowarzyszenie Miłośników Ziemi Tarnogórskiej", "status": "historic",
     "output": None, "output_unit": None, "output_year": None, "ref": "https://kopalniasrebra.pl/"},
]

# Company output 2025 (saleable coal; KGHM metal), from the EC report and KGHM's production report.
COMPANIES = {
    "pgg": {"name": "Polska Grupa Górnicza S.A.", "commodity": "hard_coal", "output": 16100.0, "unit": "kt coal",
            "year": 2025, "ref": EC_2025},
    "jsw": {"name": "Jastrzębska Spółka Węglowa S.A.", "commodity": "coking_coal", "output": 13006.1,
            "unit": "kt coal", "year": 2025, "ref": EC_2025},
    "bogdanka": {"name": "Lubelski Węgiel Bogdanka S.A.", "commodity": "hard_coal", "output": 7569.4,
                 "unit": "kt coal", "year": 2025, "ref": EC_2025},
    "pkw": {"name": "Południowy Koncern Węglowy S.A.", "commodity": "hard_coal", "output": 4531.9,
            "unit": "kt coal", "year": 2025, "ref": EC_2025},
    "weglokoks": {"name": "Węglokoks Kraj S.A.", "commodity": "hard_coal", "output": 641.0, "unit": "kt coal",
                  "year": 2025, "ref": EC_2025},
    "kghm": {"name": "KGHM Polska Miedź S.A.", "commodity": "copper", "output": 570.9,
             "unit": "kt electrolytic copper", "year": 2025, "ref": KGHM_2025,
             "other": {"copper_in_concentrate_kt": 401.1, "metallic_silver_t": 1323.3}},
}
NATIONAL = {"hard_coal_kt": 41848.4, "year": 2025, "ref": EC_2025,
            "note": "hard coal output of the reporting companies (PGG, JSW, Bogdanka, PKW, Węglokoks)"}


def osm_query(ids: list[str]) -> str:
    parts = "".join(f"{t}({n});" for t, n in (i.split("/") for i in ids))
    return f"[out:json][timeout:60];({parts});out center tags qt;"


class PlMines(Source):
    info = SourceInfo(
        id="pl_mines",
        title="Mines of Poland: coal, lignite, copper and silver, salt, sulphur (curated)",
        publisher="Ministry of Industry (report on hard coal mining 2025), State Mining Authority (WUG), KGHM, "
                  "Sejm; positions from Wikidata and OpenStreetMap",
        homepage=WUG_KWK,
        license="Public information (official reports, see ref per site); Wikidata CC0; OSM ODbL 1.0",
        description="Every hard coal mine active at the end of 2025 and the lignite, copper, salt and sulphur mines, "
                    "with the newest published output, plus copper smelters and the historic UNESCO mines.",
        used_for=["Resources on the map (mines)", "Energy and Resources advisor"],
    )

    WD = "wikidata.json"
    OSM = "osm_sites.json"

    def _qids(self):
        return [m["qid"] for m in MINES if m.get("qid")]

    def _osm_ids(self):
        return [m["osm"] for m in MINES if m.get("osm")]

    def fetch(self, force=False):
        wikidata_entities(self, self._qids(), self.WD, force=force)
        overpass(self, osm_query(self._osm_ids()), self.OSM, force=force)

    def process(self):
        wd = wikidata_entities(self, self._qids(), self.WD)
        osm = {f"{e['type']}/{e['id']}": e for e in osm_elements([self.raw_dir / self.OSM])}
        items = []
        for m in MINES:
            m = dict(m)
            if m.get("osm"):
                el = osm.get(m["osm"])
                m["lonlat"] = el_lonlat(el) if el else None
                m["osm_id"] = m.pop("osm")
            items.append(m)
        points, problems = curated_points(items, wd)
        for p in points:
            p["props"]["wikidata"] = p["props"].pop("qid", None)
        by_commodity: dict[str, int] = {}
        for p in points:
            by_commodity[p["props"]["commodity"]] = by_commodity.get(p["props"]["commodity"], 0) + 1
        return {
            "vintage": "Mining output 2025 (WUG reports, EC hard coal report, KGHM); sulphur 2024",
            "tables": {"mining_country": {
                "level": "country",
                "fields": {"hard_coal_kt": {"label": "Hard coal output", "unit": "kt", "year": 2025,
                                            "note": NATIONAL["note"]}},
                "rows": {"PL": {"hard_coal_kt": NATIONAL["hard_coal_kt"]}},
            }},
            "points": points,
            "companies": COMPANIES,
            "counts_by_commodity": by_commodity,
            "notes": [
                "Rule: hard coal mines active on 31 Dec 2025 per the Ministry's 2025 report to the European "
                "Commission (17 mines; Siltech and Eko-Plus have no published position or output and are left out), "
                "plus Bobrek (closed 30 Dec 2025); lignite mines with 2025 output; KGHM mines and smelters; Kłodawa "
                "salt; Osiek and Basznia sulphur; the UNESCO heritage mines (status historic).",
                "Mine output = raw coal or lignite mined in 2025 (WUG methane reports under Regulation (EU) "
                "2024/1787); raw coal is more than the saleable coal in `companies`. Sulphur: 2024, from the Ministry's "
                "answer to a Sejm interpellation. KGHM does not publish output per mine.",
                "Not covered: brine salt fields (Góra, Mogilno, Barycz, Łężkowice) and Eko-Plus, for lack of a published "
                "output or position; Sieniawa 2025 output.",
                "Positions: Wikidata P625 by QID (checked against the label); OSM object centres for Sieniawa, GG-1, "
                f"Cedynia, Osiek and Basznia. {ODBL_NOTE}",
                f"OSM data as of {osm_timestamp([self.raw_dir / self.OSM])}.",
            ] + problems,
            "_files": [self.WD, self.OSM],
        }

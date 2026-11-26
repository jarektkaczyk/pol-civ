"""National parks of Poland: area and yearly visitors (GUS), centre points (Wikidata).

GUS publishes the parks' area (table 5(171)) and tourist numbers (table 9(175), from the Ministry
of Climate and Environment) in the yearly "Ochrona srodowiska" (Environment) tables. The newest
edition is "Ochrona srodowiska 2025" with 2024 data; the 2026 edition (2025 data) is not out.
A park that publishes its own newer yearly count (Tatra National Park, 2025) carries it as
visitors_latest, with the report URL; the ranking stays on the GUS year so every park is compared
on the same year and the same method.
Centre points and WDPA ids come from Wikidata (the GDOS park outlines WFS refuses automated reads,
so outlines are not included). GUS names are joined to Wikidata labels by their ASCII slug.
"""

from __future__ import annotations

import io
import json
import re
import urllib.parse
import zipfile
from pathlib import Path

from ..core.source import Source, SourceInfo
from ._resource_util import xlsx_rows
from .pl_soc_common import num, slug

GUS_ZIP = ("https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5484/1/26/1/"
           "ochrona_srodowiska_2025_tablice.zip")
GUS_PAGE = "https://stat.gov.pl/obszary-tematyczne/srodowisko-energia/srodowisko/ochrona-srodowiska-2025,1,26.html"
SHEET_AREA = "TABL. 5(171)"
SHEET_TOURISM = "TABL. 9(175)"
YEAR = 2024
# Newer counts published by a park itself, read from its report (ASCII park key -> year, visitors, report).
# Tatra National Park, 2025: the "RAZEM" total of the 2025 table (tickets, exempt visitors and the park's
# estimates for unticketed entrances). Its 2024 total in the same report is 5,081,842; GUS gives 5,091,772.
TPN_REPORT = "https://tpn.gov.pl/pliki-do-pobrania/otworz/0a6cc2f2-09c2-4420-a950-db728236b09d.pdf"
TPN_FILE = "tpn_visitors_2020_2025.pdf"
PARK_REPORTS = {
    "tatrzanski": {"year": 2025, "visitors": 5_266_672, "ref": TPN_REPORT, "file": TPN_FILE},
}

SPARQL = """SELECT ?p ?pLabel ?coord ?wdpa WHERE {
  VALUES ?c { wd:Q1317754 wd:Q46169 }
  ?p wdt:P31 ?c ; wdt:P17 wd:Q36 .
  OPTIONAL { ?p wdt:P625 ?coord }
  OPTIONAL { ?p wdt:P809 ?wdpa }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "pl". }
}"""
WIKIDATA_URL = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": SPARQL, "format": "json"})


def park_key(name: str) -> str:
    """'Park Narodowy Gor Stolowych' / 'Gor Stolowych' / 'Slowinskia ......' -> 'gor_stolowych' / 'slowinski'.

    GUS marks footnotes with a letter glued to the name and a run of dots; Wikidata labels carry
    'Park Narodowy' and quotes. Both reduce to the distinctive part of the name.
    """
    text = re.sub(r"([^\s.])[a-z]\s*[.…]{2,}.*$", r"\1", name.strip())  # footnote letter + dot leader
    s = slug(text)
    s = re.sub(r"(^|_)park_narodowy(_|$)", r"\1", s).strip("_")
    return s


def parse_point(wkt: str) -> tuple[float, float] | None:
    """'Point(19.93 49.25)' -> (lon, lat)."""
    m = re.fullmatch(r"\s*Point\(\s*([-\d.eE]+)\s+([-\d.eE]+)\s*\)\s*", wkt or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def gus_table(rows, value_col: str) -> dict[str, float | None]:
    """park key -> number from a GUS park table: rows whose column A is a park name and whose
    `value_col` holds a number (or a dash, which GUS uses for zero / not applicable -> None)."""
    out: dict[str, float | None] = {}
    for r in rows:
        name = r.get("A", "")
        key = park_key(name)
        val = r.get(value_col, "")
        if not key or key in {"o_g_o_l_e_m", "ogolem", "t_o_t_a_l", "total"}:
            continue
        v = num(val)
        if v is None and val.strip() not in {"–", "-"}:
            continue  # header, note or blank row
        out[key] = v
    return out


def _member(z: zipfile.ZipFile, chapter: str) -> zipfile.ZipInfo:
    for info in z.infolist():
        if slug(info.filename).startswith(f"dzia_{chapter}_") or slug(info.filename).startswith(f"dzial_{chapter}_"):
            return info
    raise KeyError(f"no 'Dzial {chapter}' workbook in the GUS zip")


class PlSocParks(Source):
    info = SourceInfo(
        id="pl_soc_parks",
        title="National parks: area and visitors",
        publisher="Główny Urząd Statystyczny (GUS); Wikidata",
        homepage=GUS_PAGE,
        license="GUS: reuse with attribution; Wikidata: CC0",
        description="The 23 national parks of Poland with their area and the number of tourists in 2024 "
        "(Ministry of Climate and Environment data in GUS 'Ochrona srodowiska 2025'), at the park's centre point.",
        used_for=["Wonders (most visited national parks)", "Culture advisor", "Land advisor"],
    )

    def fetch(self, force=False):
        self.download(GUS_ZIP, "ochrona_srodowiska_2025_tablice.zip", force=force, expect_binary=True)
        self.download(WIKIDATA_URL, "wikidata_parks.json", force=force,
                      headers={"Accept": "application/sparql-results+json"})
        for report in PARK_REPORTS.values():
            self.download(report["ref"], report["file"], force=force, expect_binary=True)

    def process(self):
        z = zipfile.ZipFile(self.raw_dir / "ochrona_srodowiska_2025_tablice.zip")
        xlsx = io.BytesIO(z.read(_member(z, "5")))  # the chapter workbook, read in memory
        area = gus_table(xlsx_rows(xlsx, SHEET_AREA), "B")
        visitors_k = gus_table(xlsx_rows(xlsx, SHEET_TOURISM), "M")
        total_k = None
        for r in xlsx_rows(xlsx, SHEET_TOURISM):
            if slug(r.get("A", "")) == "o_g_o_l_e_m":
                total_k = num(r.get("M"))
        wd = json.loads(Path(self.raw_dir / "wikidata_parks.json").read_text(encoding="utf-8"))
        parks: dict[str, dict] = {}
        for b in wd["results"]["bindings"]:
            qid = b["p"]["value"].rsplit("/", 1)[1]
            p = parks.setdefault(qid, {"qid": qid, "name": b["pLabel"]["value"], "coord": None, "wdpa": None})
            if "coord" in b and p["coord"] is None:
                p["coord"] = parse_point(b["coord"]["value"])
            if "wdpa" in b and p["wdpa"] is None:
                p["wdpa"] = b["wdpa"]["value"]
        by_key = {park_key(p["name"]): p for p in parks.values()}
        missing = sorted(set(area) - set(by_key)) + sorted(set(visitors_k) - set(by_key))
        if missing or len(area) != len(by_key):
            raise RuntimeError(f"park join failed: GUS {sorted(area)} vs Wikidata {sorted(by_key)}")
        visitors = {k: (round(v * 1000) if v is not None else None) for k, v in visitors_k.items()}
        ranked = sorted((k for k in visitors if visitors[k] is not None), key=lambda k: -visitors[k])
        unknown = sorted(set(PARK_REPORTS) - set(by_key))
        if unknown:
            raise RuntimeError(f"park report keys not in the GUS list: {unknown}")
        points = []
        for key, p in sorted(by_key.items(), key=lambda kv: kv[1]["name"]):
            report = PARK_REPORTS.get(key) or {}
            lon, lat = p["coord"] if p["coord"] else (None, None)
            points.append({
                "id": f"np_{key}", "name": p["name"], "kind": "national_park", "lon": lon, "lat": lat,
                "props": {
                    "area_ha": area.get(key),
                    "visitors": visitors.get(key),
                    "visitors_year": YEAR,
                    "visitors_rank": ranked.index(key) + 1 if key in ranked else None,
                    "visitors_latest": report.get("visitors"),
                    "visitors_latest_year": report.get("year"),
                    "visitors_latest_ref": report.get("ref"),
                    "wikidata": p["qid"],
                    "wdpa_id": p["wdpa"],
                    "ref": f"https://www.wikidata.org/wiki/{p['qid']}",
                },
            })
        total = round(total_k * 1000) if total_k is not None else None
        return {
            "vintage": "GUS Ochrona srodowiska 2025 (data for 2024); Tatra National Park report for 2025; "
                       "Wikidata centre points",
            "tables": {
                "national_parks": {
                    "level": "country",
                    "fields": {
                        "parks": {"label": "National parks", "unit": "parks", "year": YEAR},
                        "visitors": {"label": "Tourists in national parks", "unit": "persons", "year": YEAR,
                                     "note": "GUS table 9(175), thousands x 1000; source: Ministry of Climate "
                                             "and Environment"},
                        "area_ha": {"label": "Area of national parks", "unit": "ha", "year": YEAR,
                                    "note": "GUS table 5(171); Slowinski and Wolinski without Baltic coastal water"},
                    },
                    "rows": {"PL": {"parks": len(points), "visitors": total,
                                    "area_ha": round(sum(v for v in area.values() if v is not None), 2)}},
                },
            },
            "points": points,
            "notes": [
                "rule: every national park of Poland (23 in 2026; the Lower Oder park statute was vetoed in 2025).",
                "Visitors: tourists in 2024 in GUS 'Ochrona srodowiska 2025' table 9(175), given in thousands; "
                "the 2026 edition with 2025 data is not published yet.",
                "visitors_latest: a newer yearly count published by the park itself, with its report URL in "
                "visitors_latest_ref: Tatra National Park 2025, 5,266,672 (" + TPN_REPORT + "). No other park's "
                "2025 count is in a GUS table; parks are ranked on the 2024 GUS count.",
                "Area: GUS table 5(171), hectares, 2024; Slowinski and Wolinski exclude Baltic coastal water.",
                "Positions are the park centre points from Wikidata (P625); outlines are not included because the "
                "GDOS WFS (sdi.gdos.gov.pl) refuses automated requests.",
            ],
            "_files": ["ochrona_srodowiska_2025_tablice.zip", "wikidata_parks.json"]
            + [report["file"] for report in PARK_REPORTS.values()],
        }

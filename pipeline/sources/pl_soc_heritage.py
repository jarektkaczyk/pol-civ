"""Heritage of Poland: UNESCO World Heritage properties and Pomniki Historii (Historic Monuments).

* UNESCO: the World Heritage List as open data (data.unesco.org, dataset whc001, refined to
  properties with Poland among their states). whc.unesco.org itself answers scripts with a
  JavaScript challenge, so the list comes from the UNESCO open-data portal. One point per
  property at the mean of its Polish components (UNESCO's own centroid for transboundary
  sites lies outside Poland), plus one point per Polish component of serial properties.
* Pomniki Historii: the National Heritage Board (NID) list on dane.gov.pl (dataset 168, CSV,
  cp1250, decimal commas, one row per component). One point per monument at the mean of its
  components. Monuments recognised after the CSV's data date are added from the regulation
  in Dziennik Ustaw (ADDED_MONUMENTS) with a ref.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ..core.source import Source, SourceInfo
from .pl_soc_common import num, slug, voivodeship_code

WHC_URL = "https://data.unesco.org/api/explore/v2.1/catalog/datasets/whc001/exports/json?refine=iso_codes:PL"
WHC_META = "https://data.unesco.org/api/explore/v2.1/catalog/datasets/whc001"
PH_RESOURCES = "https://api.dane.gov.pl/1.4/datasets/168/resources?per_page=50"

MEMORIAL_IDS = {"31"}  # Auschwitz Birkenau: a memorial, never a "wonder"
# Polish components of transboundary serial properties (other states' components are left out).
# 1424 tserkvas: the 8 Polish ones by village name; 1133 beech forests: the 4 Bieszczady parts.
PL_COMPONENTS = {
    "1424": {"1424-001", "1424-002", "1424-004", "1424-007", "1424-009", "1424-010", "1424-012", "1424-013"},
    "1133": {"1133quinquies-085", "1133quinquies-086", "1133quinquies-087", "1133quinquies-088"},
}
# Transboundary properties whose components are not split by state in the data: UNESCO's point is used.
UNSPLIT = {"33", "1127"}

# Monuments recognised after the dane.gov.pl data date. Coordinates: the Wikidata item of the site.
ADDED_MONUMENTS = [
    {
        "name": "Szczecin - Cmentarz Centralny",
        "date": "2026-09-28",
        "voivodeship": "zachodniopomorskie",
        "lon": 14.5233, "lat": 53.4206,
        "ref": "https://api.sejm.gov.pl/eli/acts/DU/2026/1334",
        "coord_ref": "https://www.wikidata.org/wiki/Q1589477",
    },
]


def mean_point(pts: list[tuple[float, float]]) -> tuple[float, float]:
    return (round(sum(p[0] for p in pts) / len(pts), 5), round(sum(p[1] for p in pts) / len(pts), 5))


def unesco_points(records: list[dict]) -> tuple[list[dict], list[str]]:
    """Site points (kind unesco_site / memorial) and component points (unesco_component)."""
    points, notes = [], []
    for r in sorted(records, key=lambda r: (r["date_inscribed"], int(r["id_no"]))):
        sid = str(r["id_no"])
        comps = json.loads(r.get("components_list") or "[]")
        if sid in PL_COMPONENTS:
            comps = [c for c in comps if c["ref"].strip() in PL_COMPONENTS[sid]]
            if len(comps) != len(PL_COMPONENTS[sid]):
                raise RuntimeError(f"UNESCO {sid}: expected {len(PL_COMPONENTS[sid])} Polish components")
        elif len(r.get("iso_codes") or []) > 1 and sid not in UNSPLIT:
            raise RuntimeError(f"UNESCO {sid} is transboundary and has no Polish component list")
        if sid in UNSPLIT or not comps:
            lon, lat = r["geo_point_2d"]["lon"], r["geo_point_2d"]["lat"]
        else:
            lon, lat = mean_point([(c["longitude"], c["latitude"]) for c in comps])
        year = int(str(r["date_inscribed"])[:4])
        kind = "memorial" if sid in MEMORIAL_IDS else "unesco_site"
        points.append({
            "id": f"whc_{sid}", "name": r["name_en"].strip(), "kind": kind, "lon": round(lon, 5), "lat": round(lat, 5),
            "props": {
                "unesco_id": sid, "inscribed": year, "extensions": r.get("secondary_dates"),
                "category": r.get("category"), "states": r.get("iso_codes"),
                "transboundary": len(r.get("iso_codes") or []) > 1,
                "components_in_poland": None if sid in UNSPLIT else len(comps),
                "area_ha": num(r.get("area_hectares")), "in_danger": r.get("danger") == "true",
                "ref": f"https://whc.unesco.org/en/list/{sid}",
            },
        })
        if len(comps) > 1 and sid not in UNSPLIT:
            for c in comps:
                points.append({
                    "id": f"whc_{c['ref'].strip()}", "name": c["name"].strip(),
                    "kind": "memorial_component" if sid in MEMORIAL_IDS else "unesco_component",
                    "lon": round(c["longitude"], 5), "lat": round(c["latitude"], 5),
                    "props": {"unesco_id": sid, "parent": f"whc_{sid}", "component_ref": c["ref"].strip()},
                })
    return points, notes


def ph_monuments(text: str) -> list[dict]:
    """Group the NID CSV rows (one per component) into monuments keyed by name."""
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    groups: dict[str, list[dict]] = {}
    for r in rows:
        name = " ".join((r.get("NAZWA") or "").split())
        if name:
            groups.setdefault(name, []).append(r)
    out = []
    for name, rs in groups.items():
        pts = [(num(r["E"]), num(r["N"])) for r in rs]
        pts = [p for p in pts if p[0] is not None and p[1] is not None]
        dates = sorted({r["DATA_WPISU"].strip() for r in rs if r.get("DATA_WPISU")})
        lon, lat = mean_point(pts) if pts else (None, None)
        out.append({
            "name": name, "lon": lon, "lat": lat, "components": len(rs),
            "kind_pl": rs[0].get("RODZAJ_POMNIKA_HISTORII", "").strip(),
            "date": _iso(dates[0]) if dates else None,
            "voivodeship": rs[0].get("WOJEWODZTWO", "").strip(),
            "gmina": rs[0].get("GMINA", "").strip(),
            "inspire_id": rs[0].get("INSPIRE_ID", "").strip(),
            "link": (rs[0].get("LINK") or "").strip() or None,
        })
    return out


def _iso(d: str) -> str:
    """'15.03.2017' -> '2017-03-15'."""
    dd, mm, yyyy = d.split(".")
    return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"


class PlSocHeritage(Source):
    info = SourceInfo(
        id="pl_soc_heritage",
        title="UNESCO World Heritage in Poland and Pomniki Historii",
        publisher="UNESCO World Heritage Centre (data.unesco.org); Narodowy Instytut Dziedzictwa (dane.gov.pl)",
        homepage="https://data.unesco.org/explore/dataset/whc001/",
        license="UNESCO data CC BY-SA 4.0; NID data CC BY 4.0",
        description="The World Heritage properties in Poland with inscription year and components, and the "
        "Historic Monuments of Poland (Pomniki Historii) recognised by the President, with coordinates.",
        used_for=["Wonders", "Culture advisor"],
    )

    def _ph_url(self) -> tuple[str, str]:
        listing = self.download(PH_RESOURCES, "ph/resources.json")
        res = [r for r in json.loads(Path(listing).read_text(encoding="utf-8"))["data"]
               if (r["attributes"].get("format") or "").lower() == "csv"]
        newest = max(res, key=lambda r: r["attributes"].get("data_date") or "")
        return newest["attributes"]["download_url"], newest["attributes"]["data_date"]

    def fetch(self, force=False):
        self.download(WHC_URL, "unesco/whc001_pl.json", force=force)
        self.download(WHC_META, "unesco/whc001_meta.json", force=force)
        url, date = self._ph_url()
        self.download(url, f"ph/pomniki_historii_{date}.csv", force=force)

    def process(self):
        records = json.loads((self.raw_dir / "unesco/whc001_pl.json").read_text(encoding="utf-8"))
        meta = json.loads((self.raw_dir / "unesco/whc001_meta.json").read_text(encoding="utf-8"))
        modified = (meta.get("metas", {}).get("default", {}).get("modified") or "")[:10]
        points, notes = unesco_points(records)
        n_sites = sum(1 for p in points if p["kind"] in ("unesco_site", "memorial"))

        url, date = self._ph_url()
        rel = f"ph/pomniki_historii_{date}.csv"
        monuments = ph_monuments((self.raw_dir / rel).read_bytes().decode("cp1250"))
        known = {slug(m["name"]) for m in monuments}
        for add in ADDED_MONUMENTS:
            if slug(add["name"]) in known:
                notes.append(f"{add['name']} is now in the NID CSV; drop it from ADDED_MONUMENTS.")
                continue
            monuments.append({"name": add["name"], "lon": add["lon"], "lat": add["lat"], "components": 1,
                              "kind_pl": None, "date": add["date"], "voivodeship": add["voivodeship"],
                              "gmina": None, "inspire_id": None, "link": None,
                              "ref": add["ref"], "coord_ref": add["coord_ref"]})
        for m in sorted(monuments, key=lambda m: (m["date"] or "", m["name"])):
            props = {k: m.get(k) for k in ("date", "components", "kind_pl", "voivodeship", "gmina", "inspire_id")}
            props["voivodeship_code"] = voivodeship_code(m["voivodeship"])
            props["ref"] = m.get("ref") or m.get("link") or url
            if m.get("coord_ref"):
                props["coord_ref"] = m["coord_ref"]
            points.append({"id": "ph_" + slug(m["name"])[:60], "name": m["name"], "kind": "historic_monument",
                           "lon": m["lon"], "lat": m["lat"], "props": props})
        ids = [p["id"] for p in points]
        if len(ids) != len(set(ids)):
            raise RuntimeError("duplicate point ids")
        notes += [
            f"rule: every World Heritage property with Poland among its states ({n_sites}); every Pomnik Historii "
            f"on the NID list ({len(monuments)}).",
            "UNESCO properties: one point per property at the mean of its Polish components; serial properties also "
            "get one point per Polish component (kind unesco_component). Bialowieza Forest (33) and Muskauer Park "
            "(1127) use UNESCO's own point (components not split by state).",
            "Wooden Tserkvas (1424): the 8 Polish components; Beech Forests (1133): the 4 Bieszczady components.",
            "Auschwitz Birkenau (31) has kind 'memorial' (components 'memorial_component'): a memorial, not a wonder.",
            f"UNESCO dataset modified {modified}; Gdynia Modernist City Centre (1715) was inscribed in 2026. "
            "The 2023, 2024 and 2025 sessions added no Polish property.",
            f"Pomniki Historii: NID CSV data date {date}; one point per monument at the mean of its component rows. "
            "Added from Dziennik Ustaw after that date: " + ", ".join(a["name"] for a in ADDED_MONUMENTS) + ".",
            "Gdynia appears in both lists (Pomnik Historii 2015, UNESCO 2026); do not count it twice.",
        ]
        return {
            "vintage": f"UNESCO whc001 ({modified}); NID Pomniki Historii {date} + Dz.U. 2026 poz. 1334",
            "points": points,
            "notes": notes,
            "_files": ["unesco/whc001_pl.json", "unesco/whc001_meta.json", "ph/resources.json", rel],
        }

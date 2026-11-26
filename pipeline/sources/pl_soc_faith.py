"""Faith: NSP 2021 religious affiliation by gmina and powiat, ISKK Mass attendance by diocese,
and the Roman Catholic diocese of every gmina and powiat.

* GUS, NSP 2021 final results "Przynaleznosc wyznaniowa" (xlsx, added 29 Apr 2024):
  TABL.7 (gminas by denomination) and TABL.4 (powiats by group of denominations).
  GUS publishes a denomination for a gmina only when at least 10 people declared it; a missing
  row is therefore "fewer than 10", which this source keeps as null (never 0).
* ISKK (Instytut Statystyki Kosciola Katolickiego), Annuarium Statisticum Ecclesiae in Polonia
  2025 (data 2024), Tab. 16: dominicantes and communicantes by diocese, count of October 2024.
* Diocese of each unit: the unit's point (centre of its OSM boundary, tagged teryt:terc) is placed
  in a diocese. First choice: the OSM outline (boundary=religious_administration,
  admin_level 6) when OSM has a complete outline for that diocese. Otherwise: the majority
  diocese (Wikidata P708) of the 7 nearest Roman Catholic parishes with coordinates.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

from ..core.source import Source, SourceInfo
from ._resource_util import xlsx_rows
from .pl_soc_common import num, slug

NSP_URL = ("https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/6536/10/1/1/"
           "przynaleznosc_wyznaniowa_-_dane_nsp_2021_dla_kraju_i_jednostek_podzialu_terytorialnego_1.xlsx")
NSP_FILE = "nsp2021_wyznania.xlsx"
ISKK_URL = "https://iskk.pl/wp-content/uploads/2025/12/Annuarium_Statisticum_dane_2024_25.11.25.docx"
ISKK_FILE = "iskk_annuarium_2024.docx"
OVERPASS = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
OVERPASS_QUERY = ('[out:json][timeout:180];rel["boundary"="religious_administration"]["admin_level"="6"]'
                  '["denomination"="roman_catholic"](49.0,14.1,54.9,24.2);out geom;')
OSM_FILE = "osm_dioceses.json"
WIKIDATA = "https://query.wikidata.org/sparql"
# Roman Catholic parishes in Poland with coordinates and a diocese (P708) that is a Latin diocese
# (Q3146899) or archdiocese (Q105390172, Q2072238) of the Catholic Church.
PARISH_QUERY = """SELECT ?p ?coord ?dio ?dioLabel WHERE {
  ?p wdt:P31/wdt:P279* wd:Q102496; wdt:P17 wd:Q36; wdt:P708 ?dio; wdt:P625 ?coord.
  ?dio wdt:P31 ?t. VALUES ?t { wd:Q3146899 wd:Q105390172 wd:Q2072238 }
  ?dio rdfs:label ?dioLabel. FILTER(LANG(?dioLabel) = "pl")
}"""
PARISH_FILE = "wikidata_parishes.json"
# Gminas (admin_level 7) and powiats (6) of Poland with their TERYT code (teryt:terc), the centre of
# their bounding box, and right after each one its admin_centre node (the seat). Also gives the
# current gmina codes.
UNITS_QUERY = ('[out:json][timeout:240];area["ISO3166-1"="PL"]["admin_level"="2"]->.pl;'
               'rel["boundary"="administrative"]["admin_level"~"^(6|7)$"]["teryt:terc"](area.pl)->.u;'
               'foreach.u->.r(.r out tags center;node(r.r:"admin_centre");out;);')
UNITS_FILE = "osm_units_centres.json"
KNN = 7

# NSP label slug -> field. Labels are matched on their ASCII slug (see pl_soc_common.slug).
GMINA_LABELS = {
    "ogolem": "total",
    "udzielajacy_odpowiedzi_na_pytanie_o_wyznanie": "answered",
    "nalezacy_do_wyznania_w_tym": "religious",
    "kosciol_katolicki_obrzadek_lacinski_kosciol_rzymskokatolicki": "roman_catholic",
    "kosciol_katolicki_obrzadek_bizantyjsko_ukrainski_kosciol_greckokatolicki": "greek_catholic",
    "kosciol_prawoslawny": "orthodox",
    "kosciol_ewangelicko_augsburski": "lutheran",
    "swiadkowie_jehowy": "jehovahs_witnesses",
    "nienalezacy_do_zadnego_wyznania": "none",
    "odmawiajacy_odpowiedzi_na_pytanie_o_wyznanie": "refused",
    "nie_ustalono": "not_stated",
}
POWIAT_LABELS = {
    "ogolem": "total",
    "kosciol_katolicki": "catholic",
    "chrzescijanstwo_wschodnie_ortodoksyjne": "eastern_orthodox",
    "protestantyzm_i_tradycja_protestancka": "protestant",
    "nurt_badaczy_pisma_swietego": "bible_students",
    "nienalezacy_do_zadnego_wyznania": "none",
    "odmawiajacy_odpowiedzi_na_pytanie_o_wyznanie": "refused",
}
FIELD_LABELS = {
    "total": "Population (NSP 2021)", "answered": "Answered the religion question",
    "religious": "Belonging to a denomination", "roman_catholic": "Roman Catholic",
    "greek_catholic": "Greek Catholic", "orthodox": "Polish Orthodox Church", "lutheran": "Lutheran (Evangelical-Augsburg)",
    "jehovahs_witnesses": "Jehovah's Witnesses", "none": "No denomination", "refused": "Refused to answer",
    "not_stated": "Not established", "catholic": "Catholic Church (all rites)",
    "eastern_orthodox": "Eastern Orthodox Christianity", "protestant": "Protestantism and Protestant tradition",
    "bible_students": "Bible Student movement (incl. Jehovah's Witnesses)",
}
ALWAYS_PUBLISHED = {"total", "answered", "religious", "roman_catholic", "catholic", "none", "refused"}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# ------------------------------------------------------------------ NSP


def _col_index(letter: str) -> int:
    n = 0
    for ch in letter:
        n = n * 26 + ord(ch) - 64
    return n


def nsp_rows(rows, code_header: str, labels: dict[str, str]) -> dict[str, dict]:
    """Group a GUS NSP table into {unit code: {field: (count, pct of population)}}.

    `rows` are {column letter: text} dicts (xlsx_rows). The header row is the one holding a cell
    whose slug is `code_header` ("kod_gminy" / "kod_powiatu"). The label of a data row is its first
    non-empty cell between the code column and the count column (the level-of-classification column
    is skipped). Unknown labels are ignored.
    """
    header = None
    out: dict[str, dict] = {}
    for row in rows:
        if header is None:
            slugs = {col: slug(v) for col, v in row.items() if v}
            if code_header in slugs.values():
                header = slugs
                code_col = next(c for c, s in slugs.items() if s == code_header)
                count_col = next(c for c, s in slugs.items() if s == "w_liczbach_bezwzglednych")
                pct_col = next(c for c, s in slugs.items() if s == "procent_ogolu_ludnosci")
                skip = {c for c, s in slugs.items() if s == "poziom_klasyfikacji"}
                label_cols = sorted((c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                                     if _col_index(code_col) < _col_index(c) < _col_index(count_col)
                                     and c not in skip), key=_col_index)
            continue
        code = (row.get(code_col) or "").strip()
        if not code.isdigit():
            continue
        label = next((row[c] for c in label_cols if (row.get(c) or "").strip()), "")
        field = labels.get(slug(label))
        if field is None:
            continue
        out.setdefault(code, {})[field] = (num(row.get(count_col)), num(row.get(pct_col)))
    return out


def nsp_names(rows, code_header: str, name_header: str) -> dict[str, str]:
    """Unit code -> name from the first row of each unit (the name cell is blank on later rows)."""
    names: dict[str, str] = {}
    header = None
    for row in rows:
        if header is None:
            slugs = {col: slug(v) for col, v in row.items() if v}
            if code_header in slugs.values():
                header = slugs
                code_col = next(c for c, s in slugs.items() if s == code_header)
                name_col = next(c for c, s in slugs.items() if s == name_header)
            continue
        code, name = (row.get(code_col) or "").strip(), (row.get(name_col) or "").strip()
        if code.isdigit() and name and code not in names:
            names[code] = name
    return names


def nsp_table(units: dict[str, dict], fields: list[str]) -> dict[str, dict]:
    """{code: {field: count, field_share: % of population}}; a missing category -> null (suppressed)."""
    out = {}
    for code, vals in units.items():
        total = vals.get("total", (None, None))[0]
        row = {}
        for f in fields:
            count, share = vals.get(f, (None, None))
            if share is None and count is not None and total:
                share = 100.0 * count / total
            row[f] = int(count) if count is not None else None
            if f != "total":
                row[f + "_share"] = round(share, 3) if share is not None else None
        out[code] = row
    return out


# ------------------------------------------------------------------ ISKK


def docx_tables(path) -> list[tuple[str, list[list[str]]]]:
    """[(caption, rows)] for every table in a .docx: caption = the last non-empty paragraph
    before the table; rows = cell texts (runs joined, so words split over runs come back whole)."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    out, caption = [], ""
    for el in root.find(_W + "body"):
        if el.tag == _W + "p":
            text = "".join(t.text or "" for t in el.iter(_W + "t")).strip()
            if text:
                caption = text
        elif el.tag == _W + "tbl":
            rows = [["".join(t.text or "" for t in tc.iter(_W + "t")).strip() for tc in tr.findall(_W + "tc")]
                    for tr in el.iter(_W + "tr")]
            out.append((caption, rows))
    return out


def diocese_key(name: str) -> str:
    """'Archidiecezja Krakowska' / 'krakowska' -> 'krakowska' (the adjective ISKK uses)."""
    s = slug(name)
    for prefix in ("archidiecezja_", "diecezja_"):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def iskk_attendance(tables) -> tuple[dict[str, dict], dict[str, str]]:
    """Rows of Tab. 16 (dominicantes and communicantes by diocese) -> ({key: values}, {key: name}).

    Keys: "PL" for the total, the diocese adjective for the 41 Latin dioceses, "ordynariat_polowy_wp"
    and "eastern_<name>" for the Eastern-rite eparchies listed after "Obrzadki wschodnie". "bd" -> null.
    """
    for caption, rows in tables:
        c = slug(caption)
        if "dominicantes_i_communicantes" in c and "diecezji" in c:
            break
    else:
        raise RuntimeError("ISKK: no table 'dominicantes i communicantes ... wedlug diecezji' in the docx")
    values, names, eastern = {}, {}, False
    for cells in rows[1:]:
        cells = [x for x in cells if x != ""] or [""]
        if len(cells) == 1:
            eastern = eastern or slug(cells[0]) == "obrzadki_wschodnie"
            continue
        name = cells[0]
        key = "PL" if slug(name) == "ogolem" else ("eastern_" if eastern else "") + diocese_key(name)
        values[key] = {"dominicantes": num(cells[1]), "communicantes": num(cells[2])}
        names[key] = name
    return values, names


# ------------------------------------------------------------------ geometry


def point_in_segments(lon: float, lat: float, segments) -> bool:
    """Even-odd ray casting over a bag of segments (outer and inner rings, any order)."""
    inside = False
    for (x1, y1, x2, y2) in segments:
        if (y1 > lat) != (y2 > lat):
            x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if x > lon:
                inside = not inside
    return inside


def segments_closed(segments, digits: int = 7) -> bool:
    """True when every segment endpoint is shared by an even number of segment ends (closed rings)."""
    deg: Counter = Counter()
    for (x1, y1, x2, y2) in segments:
        deg[(round(x1, digits), round(y1, digits))] += 1
        deg[(round(x2, digits), round(y2, digits))] += 1
    return bool(deg) and all(v % 2 == 0 for v in deg.values())


def osm_outlines(data: dict) -> dict[str, dict]:
    """Diocese key -> {"name", "segments", "bbox", "closed"} from Overpass `out geom` relations.

    Only relations named "Archidiecezja ..." / "Diecezja ..." are kept (drops the foreign dioceses
    and the Ordynariat Polowy). A relation without its own outer/inner ways has no outline here.
    """
    out = {}
    for el in data.get("elements", []):
        name = (el.get("tags") or {}).get("name") or ""
        if not re.match(r"(Archidiecezja|Diecezja) ", name):
            continue
        segs = []
        for m in el.get("members", []):
            if m.get("type") == "way" and m.get("role") in ("outer", "inner") and m.get("geometry"):
                g = m["geometry"]
                segs += [(a["lon"], a["lat"], b["lon"], b["lat"]) for a, b in zip(g, g[1:])]
        if not segs:
            continue
        xs = [s[0] for s in segs] + [s[2] for s in segs]
        ys = [s[1] for s in segs] + [s[3] for s in segs]
        out[diocese_key(name)] = {"name": name, "segments": segs, "bbox": (min(xs), min(ys), max(xs), max(ys)),
                                  "closed": segments_closed(segs)}
    return out


def unit_points(data: dict) -> tuple[dict[str, tuple[float, float]], int]:
    """TERYT code -> (lon, lat) of the unit's seat from the Overpass `foreach` answer, where each
    relation (out tags center) is followed by its admin_centre node(s). Falls back to the bbox centre.
    Returns (points, number of units placed at their seat)."""
    points, seats, code = {}, set(), None
    for el in data.get("elements", []):
        if el.get("type") == "relation":
            code = (el.get("tags") or {}).get("teryt:terc", "")
            c = el.get("center")
            if not re.fullmatch(r"\d{4}|\d{7}", code):
                code = None
            elif c:
                points[code] = (c["lon"], c["lat"])
        elif el.get("type") == "node" and code and code not in seats:
            points[code] = (el["lon"], el["lat"])
            seats.add(code)
    return points, len(seats)


def parse_wkt_point(text: str) -> tuple[float, float] | None:
    m = re.match(r"\s*Point\(\s*([-0-9.eE]+)\s+([-0-9.eE]+)\s*\)", text or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def nearest_vote(lon: float, lat: float, parishes: list[tuple[float, float, str]], k: int = KNN) -> str | None:
    """Majority diocese among the k nearest parishes (ties: the nearer parish wins)."""
    coslat = math.cos(math.radians(lat))
    best = sorted(((((p[0] - lon) * coslat) ** 2 + (p[1] - lat) ** 2, p[2]) for p in parishes))[:k]
    if not best:
        return None
    counts = Counter(d for _, d in best)
    top = max(counts.values())
    return next(d for _, d in best if counts[d] == top)


def assign(lon, lat, outlines, parishes, k: int = KNN):
    """(diocese key, method) for a point: a complete OSM outline that contains it, else the vote."""
    vote = nearest_vote(lon, lat, parishes, k)
    hits = [k for k, o in outlines.items() if o["closed"]
            and o["bbox"][0] <= lon <= o["bbox"][2] and o["bbox"][1] <= lat <= o["bbox"][3]
            and point_in_segments(lon, lat, o["segments"])]
    if len(hits) == 1:
        return hits[0], "osm", vote
    if len(hits) > 1:
        return (vote if vote in hits else hits[0]), "osm", vote
    return vote, "parishes", vote


# ------------------------------------------------------------------ source


class PlSocFaith(Source):
    info = SourceInfo(
        id="pl_soc_faith",
        title="Religious affiliation (NSP 2021), Mass attendance by diocese (ISKK) and dioceses",
        publisher="Główny Urząd Statystyczny (GUS); Instytut Statystyki Kościoła "
                  "Katolickiego (ISKK); OpenStreetMap; Wikidata",
        homepage="https://stat.gov.pl/spisy-powszechne/nsp-2021/nsp-2021-wyniki-ostateczne/",
        license="GUS: reuse with attribution; ISKK: cite the Annuarium; OSM: ODbL; Wikidata: CC0",
        description="Declared religion in the 2021 census for every gmina (Roman Catholic, Orthodox, Lutheran, "
        "Jehovah's Witnesses, none, refused) and Protestant share by powiat; the share of Catholics at Sunday "
        "Mass (dominicantes) and at Communion (communicantes) in each diocese; the diocese of each gmina.",
        used_for=["Faith lens", "Culture advisor"],
    )

    def _sparql(self, query: str, rel: str, force: bool = False):
        url = WIKIDATA + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
        return self.download(url, rel, force=force, headers={"Accept": "application/sparql-results+json"})

    def fetch(self, force=False):
        self.download(NSP_URL, NSP_FILE, force=force, expect_binary=True)
        self.download(ISKK_URL, ISKK_FILE, force=force, expect_binary=True)
        self.download(OVERPASS + "?" + urllib.parse.urlencode({"data": OVERPASS_QUERY}), OSM_FILE, force=force)
        self._sparql(PARISH_QUERY, PARISH_FILE, force=force)
        self.download(OVERPASS + "?" + urllib.parse.urlencode({"data": UNITS_QUERY}), UNITS_FILE, force=force)

    @staticmethod
    def remap_codes(codes, current: set[str]) -> dict[str, str]:
        """NSP 2021 TERYT7 -> current TERYT7: unchanged if current, else the only current code with the
        same first 6 digits (a gmina whose type digit changed, e.g. rural 2 -> urban-rural 3)."""
        by6: dict[str, list[str]] = {}
        for c in current:
            by6.setdefault(c[:6], []).append(c)
        out = {}
        for c in codes:
            if c in current:
                out[c] = c
            elif len(by6.get(c[:6], [])) == 1:
                out[c] = by6[c[:6]][0]
        return out

    def process(self):
        notes = [
            "NSP 2021 (31 Mar 2021) final results, GUS xlsx of 29 Apr 2024: TABL.7 gminas, TABL.4 powiats.",
            "GUS lists a denomination in a gmina only if 10+ people declared it: a null share means under 10 "
            "people (suppressed), not zero. Shares are % of the whole population (GUS 'Procent ogolu ludnosci').",
            "Gminas Szczawa (1207132) and Grabowka (2002162) were created on 1 Jan 2025 and have no NSP 2021 "
            "row; their 2021 population is inside the gminas they were split from.",
        ]
        nsp_path = self.raw_dir / NSP_FILE
        g_units = nsp_rows(xlsx_rows(nsp_path, "TABL.7"), "kod_gminy", GMINA_LABELS)
        g_names = nsp_names(xlsx_rows(nsp_path, "TABL.7"), "kod_gminy", "gmina")
        p_units = nsp_rows(xlsx_rows(nsp_path, "TABL.4"), "kod_powiatu", POWIAT_LABELS)
        centres, seat_count = unit_points(json.loads((self.raw_dir / UNITS_FILE).read_text(encoding="utf-8")))
        current = {c for c in centres if len(c) == 7}
        mapping = self.remap_codes(g_units, current)
        changed = sorted(f"{a}->{b}" for a, b in mapping.items() if a != b)
        missing = sorted(set(g_units) - set(mapping))
        g_units = {mapping.get(c, c): v for c, v in g_units.items()}
        g_names = {mapping.get(c, c): v for c, v in g_names.items()}
        notes.append(f"NSP 2021 gmina codes checked against the {len(current)} current gmina codes in OSM "
                     "(teryt:terc)" + (f"; changed type digit: {', '.join(changed)}" if changed else
                                       "; no code changed")
                     + (f"; no current match (kept): {', '.join(missing)}" if missing else "") + ".")
        g_fields = list(dict.fromkeys(GMINA_LABELS.values()))
        p_fields = list(dict.fromkeys(POWIAT_LABELS.values()))

        def fields(names, year=2021):
            out = {}
            for f in names:
                if f == "total":
                    out[f] = {"label": FIELD_LABELS[f], "unit": "persons", "year": year}
                    continue
                out[f] = {"label": FIELD_LABELS[f], "unit": "persons", "year": year}
                out[f + "_share"] = {"label": FIELD_LABELS[f], "unit": "%", "year": year,
                                     "note": "% of population; null = not published (under 10 people)"
                                     if f not in ALWAYS_PUBLISHED else "% of population"}
            return out

        gmina_rows = nsp_table(g_units, g_fields)
        tables = {
            "religion_gmina": {"level": "gmina", "fields": fields(g_fields), "rows": gmina_rows},
            "religion_powiat": {"level": "powiat", "fields": fields(p_fields),
                                "rows": nsp_table(p_units, p_fields)},
        }

        # Census-based highlights (Orthodox Podlasie, Lutheran Cieszyn Silesia), computed here.
        highlights = {}
        for f in ("orthodox", "lutheran"):
            ranked = sorted(((r[f + "_share"], c) for c, r in gmina_rows.items() if r.get(f + "_share") is not None),
                            reverse=True)[:10]
            highlights[f + "_top10"] = [{"gmina": c, "name": g_names.get(c, ""), "share": s} for s, c in ranked]
            notes.append(f"Top gminas by {f} share (NSP 2021): " + "; ".join(
                f"{g_names.get(c, c)} {c} {s:.1f}%" for s, c in ranked[:5]) + " ...")

        # ISKK
        iskk, iskk_names = iskk_attendance(docx_tables(self.raw_dir / ISKK_FILE))
        tables["mass_attendance_diocese"] = {
            "level": "diocese",
            "fields": {
                "dominicantes": {"label": "Catholics attending Sunday Mass", "unit": "%", "year": 2024,
                                 "note": "ISKK count of October 2024, % of Catholics obliged to attend"},
                "communicantes": {"label": "Catholics receiving Communion", "unit": "%", "year": 2024,
                                  "note": "ISKK count of October 2024"},
            },
            "rows": iskk,
        }
        notes.append("ISKK: Annuarium Statisticum Ecclesiae in Polonia (published Dec 2025), Tab. 16, count "
                     "of October 2024; 'bd' (no data) is null. The 2025 count is not yet published.")

        # Dioceses of gminas and powiats
        osm = osm_outlines(json.loads((self.raw_dir / OSM_FILE).read_text(encoding="utf-8")))
        parishes = []
        for b in json.loads((self.raw_dir / PARISH_FILE).read_text(encoding="utf-8"))["results"]["bindings"]:
            pt = parse_wkt_point(b["coord"]["value"])
            if pt:
                parishes.append((pt[0], pt[1], diocese_key(b["dioLabel"]["value"])))
        parish_dioceses = {p[2] for p in parishes}
        latin = {k for k in iskk if k not in ("PL", "ordynariat_polowy_wp") and not k.startswith("eastern_")}
        if parish_dioceses - latin:
            raise RuntimeError(f"Wikidata parish dioceses not in the ISKK list: {sorted(parish_dioceses - latin)}")
        unknown_osm = set(osm) - latin
        for k in unknown_osm:
            del osm[k]
        diocese_of = {"gmina": {}, "powiat": {}}
        methods: Counter = Counter()
        agree = Counter()
        missing_pts = []

        def place(level, code, pt):
            if pt is None:
                missing_pts.append(code)
                diocese_of[level][code] = None
                return
            key, method, vote = assign(pt[0], pt[1], osm, parishes)
            diocese_of[level][code] = key
            methods[(level, method)] += 1
            if method == "osm":
                agree[key == vote] += 1

        for code in sorted(current | set(gmina_rows)):
            place("gmina", code, centres.get(code))
        for code in sorted({c for c in centres if len(c) == 4} | set(tables["religion_powiat"]["rows"])):
            place("powiat", code, centres.get(code))
        complete = sorted(k for k, o in osm.items() if o["closed"])
        notes += [
            "Diocese of a gmina/powiat: the point of the unit's seat in OSM (admin_centre of the boundary "
            "relation with teryt:terc; the centre of its bounding box when OSM names no seat: "
            f"{len(centres) - seat_count} units). A unit split between dioceses (e.g. Warsaw: warszawska and "
            "warszawsko-praska) gets the diocese of its seat.",
            f"OSM has complete outlines for {len(complete)} of 41 Latin dioceses ({', '.join(complete)}); others "
            "are missing or have only some deaneries. Points outside those outlines get the majority diocese "
            f"(Wikidata P708) of the {KNN} nearest Roman Catholic parishes ({len(parishes)} parishes with "
            "coordinates). The Sosnowiec diocese has no OSM relation and is placed this way.",
            "Assignments: " + ", ".join(f"{lvl} {m}: {n}" for (lvl, m), n in sorted(methods.items()))
            + f"; where OSM decides, the parish vote agrees in {agree[True]} of {agree[True] + agree[False]}.",
        ]
        if missing_pts:
            notes.append(f"No Wikidata point (diocese null): {', '.join(missing_pts)}")
        wd_names = {}
        for b in json.loads((self.raw_dir / PARISH_FILE).read_text(encoding="utf-8"))["results"]["bindings"]:
            label = b["dioLabel"]["value"]
            wd_names.setdefault(diocese_key(label), label[:1].upper() + label[1:])
        dioceses = []
        for k in sorted(latin):
            dioceses.append({"key": k, "name": wd_names.get(k) or osm.get(k, {}).get("name") or iskk_names.get(k),
                             "iskk_name": iskk_names.get(k),
                             "osm_outline": bool(osm.get(k, {}).get("closed")), **iskk.get(k, {})})
        files = [NSP_FILE, ISKK_FILE, OSM_FILE, PARISH_FILE, UNITS_FILE]
        return {
            "vintage": "NSP 2021 (31 Mar 2021); ISKK count of October 2024 (Annuarium 2025); "
                       "OSM and Wikidata as fetched",
            "tables": tables,
            "diocese_of": diocese_of,
            "dioceses": dioceses,
            "highlights": highlights,
            "notes": notes,
            "_files": files,
        }

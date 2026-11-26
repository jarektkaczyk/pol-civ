"""Universities of Poland: students (GUS 2025/26), official records (RAD-on), research categories
(RAD-on evaluations) and main-campus positions (Wikidata).

* GUS "Szkolnictwo wyzsze w roku akademickim 2025/2026", table 2_2 (state on 31 Dec 2025): students
  by voivodeship, institution, city and field. The institution-city totals are the rows with every
  breakdown column at "ogolem" and level code "a". GUS repeats Mazowieckie split into its two NUTS2
  regions ("REGION ..."); those rows are dropped. GUS counts enrolments: a person on two programmes
  counts twice.
* RAD-on (radon.nauka.gov.pl, the POL-on open data API): institution records (official name, kind,
  address, www) and the results of the evaluation of scientific activity (category per discipline).
  The newest period is used per institution: 2022-2025 where published (2026, partial), else 2017-2021.
* Wikidata: coordinates (P625) of Polish higher-education institutions. Wikidata has no POL-on id, so
  the join is by website domain, then by normalized name.

Joins are by name: GUS upper-case names -> RAD-on names (current and former) by ASCII slug.
"""

from __future__ import annotations

import io
import json
import re
import urllib.parse
from pathlib import Path

from ..core.source import Source, SourceInfo
from ._resource_util import xlsx_rows
from .pl_soc_common import slug, voivodeship_code

GUS_XLSX = ("https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5488/8/12/1/"
            "szkolnictwo_wyzsze_w_roku_akademickim_2025-2026_tab2_2.xlsx")
GUS_SHEET = "Ogółem"
RADON = "https://radon.nauka.gov.pl/opendata/polon/{what}?resultNumbers=100"
# Roots: higher-education institution, medical school, academic institution, institute of technology
# (Polish medical universities are 'medical school' items outside the Q38723 tree).
SPARQL = """SELECT DISTINCT ?u ?uLabel ?coord ?www WHERE {
  VALUES ?root { wd:Q38723 wd:Q494230 wd:Q4671277 wd:Q1371037 }
  ?u wdt:P31/wdt:P279* ?root ; wdt:P17 wd:Q36 .
  OPTIONAL { ?u wdt:P625 ?coord }
  OPTIONAL { ?u wdt:P856 ?www }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "pl,en". }
}"""
WIKIDATA_URL = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": SPARQL, "format": "json"})

KINDS = {"uczelnia_publiczna": "public", "uczelnia_niepubliczna": "private", "uczelnia_koscielna": "church"}

# GUS spellings that differ from RAD-on by a typo (slug -> corrected slug).
ALIASES = {
    "akademia_medyczna_nauk_stosowanych_i_holistycznych_warszawie":
        "akademia_medyczna_nauk_stosowanych_i_holistycznych_w_warszawie",
}

# Official RAD-on names (ASCII slug) -> common abbreviation. Matched at run time; misses are noted.
ABBR = {
    "uniwersytet_warszawski": "UW",
    "uniwersytet_jagiellonski_w_krakowie": "UJ",
    "politechnika_warszawska": "PW",
    "akademia_gorniczo_hutnicza_im_stanislawa_staszica_w_krakowie": "AGH",
    "politechnika_wroclawska": "PWr",
    "politechnika_gdanska": "PG",
    "uniwersytet_im_adama_mickiewicza_w_poznaniu": "UAM",
    "uniwersytet_wroclawski": "UWr",
    "politechnika_lodzka": "PŁ",
    "uniwersytet_medyczny_w_lodzi": "UMed",
    "gdanski_uniwersytet_medyczny": "GUMed",
    "warszawski_uniwersytet_medyczny": "WUM",
    "uniwersytet_mikolaja_kopernika_w_toruniu": "UMK",
    "uniwersytet_lodzki": "UŁ",
    "uniwersytet_gdanski": "UG",
    "politechnika_poznanska": "PP",
    "politechnika_slaska": "Polśl",
    "uniwersytet_slaski_w_katowicach": "UŚ",
    "politechnika_krakowska_im_tadeusza_kosciuszki": "PK",
    "szkola_glowna_handlowa_w_warszawie": "SGH",
    "szkola_glowna_gospodarstwa_wiejskiego_w_warszawie": "SGGW",
    "uniwersytet_marii_curie_sklodowskiej_w_lublinie": "UMCS",
    "katolicki_uniwersytet_lubelski_jana_pawla_ii": "KUL",
    "uniwersytet_medyczny_im_karola_marcinkowskiego_w_poznaniu": "UMP",
    "uniwersytet_medyczny_im_piastow_slaskich_we_wroclawiu": "UMW",
    "slaski_uniwersytet_medyczny_w_katowicach": "SUM",
    "uniwersytet_medyczny_w_lublinie": "UML",
    "uniwersytet_medyczny_w_bialymstoku": "UMB",
    "pomorski_uniwersytet_medyczny_w_szczecinie": "PUM",
}


def name_keys(name: str) -> list[str]:
    """Join keys for an institution name: the full slug, then the slug without a trailing
    ' w/we <city>' (Wikidata labels often drop the seat), without 'im. <patron>', and both."""
    s = slug(name)
    s = ALIASES.get(s, s)
    for old, new in (("_imienia_", "_im_"), ("_generala_", "_gen_"), ("_z_siedziba_w_", "_w_"),
                     ("_z_siedziba_we_", "_we_"), ("_wlkp", "_wielkopolskim")):
        s = s.replace(old, new)
    s = re.sub(r"_(w_likwidacji|wykreslona)$", "", s)
    s = re.sub(r"(_(?:w|we)_[a-z_]+)\1$", r"\1", s)  # '... w Legnicy z siedziba w Legnicy'
    keys = [s]
    no_city = re.sub(r"_(w|we)_[a-z_]+$", "", s)
    no_patron = re.sub(r"_im_[a-z_]+?(?=_(w|we)_|$)", "", s)
    for k in (no_city, no_patron, re.sub(r"_(w|we)_[a-z_]+$", "", no_patron)):
        if k and k not in keys:
            keys.append(k)
    return keys


def unique_index(items) -> dict[str, dict]:
    """key -> record from (record, [names]) pairs. Full-name keys win; a shortened key (no city,
    no patron) is kept only when it points to a single record, and must have 2+ words."""
    full: dict[str, dict] = {}
    short: dict[str, list] = {}
    for rec, names in items:
        for n in names:
            keys = name_keys(n)
            full.setdefault(keys[0], rec)
            for k in keys[1:]:
                if "_" in k and all(rec is not o for o in short.get(k, [])):
                    short.setdefault(k, []).append(rec)
    out = dict(full)
    for k, recs in short.items():
        if len(recs) == 1:
            out.setdefault(k, recs[0])
    return out


UNIT_PREFIXES = ("wydzial", "kolegium_", "instytut_", "filia", "zamiejscow", "osrodek", "katedra", "centrum_",
                 "zaklad_", "oddzial")


def is_unit_label(label: str) -> bool:
    """True for a Wikidata item that is a faculty, branch or institute of a university."""
    return slug(label).startswith(UNIT_PREFIXES)


def city_ok(label: str, cities) -> bool:
    """False when a label names a seat ('... w Inowroclawiu') that is none of the GUS cities.

    Polish locatives change the ending (Krakow -> Krakowie, Pila -> Pile), so the first three
    letters are compared. A label without a seat passes.
    """
    seats = re.findall(r"(?:^|_)(?:w|we)_([a-z]+)", slug(label))
    if not seats:
        return True
    stems = {slug(c)[:3] for c in cities}
    return any(seat[:3] in stems for seat in seats)


def domain(url: str | None) -> str | None:
    """'https://www.uj.edu.pl/' -> 'uj.edu.pl'."""
    if not url:
        return None
    host = urllib.parse.urlparse(url if "//" in url else "http://" + url).hostname or ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host or None


def gus_institutions(rows) -> tuple[dict[str, dict], int]:
    """Institution name -> {"voivodeship", "campuses": {city: students|None}} from GUS table 2_2.

    Keeps the institution-city totals (all breakdowns 'ogolem', level 'a'), drops the NUTS2
    'REGION ...' duplicates of Mazowieckie and institutions with no students ('-'). A '.'
    (value withheld) is kept as None. Returns (institutions, national total from the 'Polska' row).
    """
    out: dict[str, dict] = {}
    national = None
    for r in rows:
        if r.get("H") != "a":
            continue
        if any(slug(r.get(c, "")) != "ogolem" for c in "DEFG"):
            continue
        voiv, inst, city, val = r.get("A", ""), r.get("B", "").strip(), r.get("C", "").strip(), r.get("I", "").strip()
        if slug(voiv) == "polska" and slug(inst) == "ogolem":
            national = int(val)
            continue
        if slug(inst) == "ogolem" or slug(voiv).startswith("region"):
            continue
        if val == "-":
            continue
        students = int(val) if val.isdigit() else None
        rec = out.setdefault(inst, {"voivodeship": voiv, "campuses": {}})
        if students is None:
            rec["campuses"].setdefault(city, None)
        else:
            rec["campuses"][city] = (rec["campuses"].get(city) or 0) + students
    return {k: v for k, v in out.items() if v["campuses"]}, national


def newest_categories(records: list[dict]) -> dict[str, dict[str, tuple[str, str]]]:
    """institutionUuid -> {discipline: (category, period)}, the newest evaluation per discipline.

    The 2022-2025 results (evaluation year 2026) are published discipline by discipline, so an
    institution can have some disciplines graded for 2022-2025 and the rest only for 2017-2021.
    """
    best: dict[str, dict[str, tuple[int, str, str]]] = {}
    for r in records:
        u = r.get("institutionUuid")
        if not u:
            continue
        for d in r.get("disciplines") or []:
            cur = best.setdefault(u, {}).get(d["disciplineName"])
            if cur is None or r["evaluationYear"] > cur[0]:
                best[u][d["disciplineName"]] = (r["evaluationYear"], d["category"], r["evaluationPeriod"])
    return {u: {k: (v[1], v[2]) for k, v in ds.items()} for u, ds in best.items()}


def parse_point(wkt: str) -> tuple[float, float] | None:
    m = re.fullmatch(r"\s*Point\(\s*([-\d.eE]+)\s+([-\d.eE]+)\s*\)\s*", wkt or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


class PlSocUniversities(Source):
    info = SourceInfo(
        id="pl_soc_universities",
        title="Universities: students, research categories, main campus",
        publisher="Główny Urząd Statystyczny (GUS); Ministry of Science (RAD-on / POL-on); Wikidata",
        homepage="https://radon.nauka.gov.pl/dane",
        license="GUS: reuse with attribution; RAD-on open data: reuse with attribution; Wikidata: CC0",
        description="Every higher-education institution with students in the academic year 2025/26, with its "
        "official name and kind, the number of students (enrolments) and the newest scientific categories of its "
        "disciplines, at the main campus.",
        used_for=["Knowledge advisor", "Wonders (universities)", "City badges"],
    )

    def _pages(self, what: str, force: bool = False) -> list[dict]:
        """All records of a RAD-on list endpoint; page n is cached as radon/<what>_p<n>.json."""
        out: list[dict] = []
        token, page = None, 0
        while True:
            url = RADON.format(what=what) + (f"&token={urllib.parse.quote(token, safe='')}" if token else "")
            path = self.download(url, f"radon/{what}_p{page}.json", force=force)
            d = json.loads(Path(path).read_text(encoding="utf-8"))
            out += d.get("results") or []
            total = d.get("pagination", {}).get("maxCount") or 0
            token = d.get("pagination", {}).get("token")
            page += 1
            if not d.get("results") or len(out) >= total or not token or page > 50:
                return out

    def fetch(self, force=False):
        self.download(GUS_XLSX, "gus_studenci_2025_2026_tab2_2.xlsx", force=force, expect_binary=True)
        self._pages("institutions", force)
        self._pages("evaluations", force)
        self.download(WIKIDATA_URL, "wikidata_hei.json", force=force,
                      headers={"Accept": "application/sparql-results+json"})

    def process(self):
        xlsx = self.raw_dir / "gus_studenci_2025_2026_tab2_2.xlsx"
        gus, national = gus_institutions(xlsx_rows(io.BytesIO(xlsx.read_bytes()), GUS_SHEET))
        radon = [r for r in self._pages("institutions") if slug(r.get("iKindName", "")) in KINDS]
        evals = newest_categories(self._pages("evaluations"))
        wd_raw = json.loads((self.raw_dir / "wikidata_hei.json").read_text(encoding="utf-8"))

        # RAD-on index: current name first, then former names; active institutions win a tie.
        radon.sort(key=lambda r: (slug(r.get("status", "")) != "dzialajaca", r["name"]))
        r_index = unique_index((r, [r["name"]] + [x["name"] for x in r.get("names") or []]) for r in radon)

        wd: dict[str, dict] = {}
        for b in wd_raw["results"]["bindings"]:
            q = b["u"]["value"].rsplit("/", 1)[1]
            if is_unit_label(b["uLabel"]["value"]):
                continue  # faculties and branches sit away from the main seat
            it = wd.setdefault(q, {"qid": q, "label": b["uLabel"]["value"], "coord": None, "domains": set()})
            if it["coord"] is None and "coord" in b:
                it["coord"] = parse_point(b["coord"]["value"])
            if "www" in b and domain(b["www"]["value"]):
                it["domains"].add(domain(b["www"]["value"]))
        wd_dom: dict[str, dict] = {}
        ordered = sorted(wd.values(), key=lambda i: (i["coord"] is None, i["qid"]))
        dom_items: dict[str, list] = {}
        for it in ordered:
            for d in it["domains"]:
                dom_items.setdefault(d, []).append(it)
        radon_doms: dict[str, int] = {}
        for r in radon:
            if domain(r.get("www")):
                radon_doms[domain(r.get("www"))] = radon_doms.get(domain(r.get("www")), 0) + 1
        # A website domain joins only when one Wikidata item and one RAD-on institution use it
        # (WSB Merito schools in several cities share merito.pl).
        wd_dom = {d: its[0] for d, its in dom_items.items() if len(its) == 1 and radon_doms.get(d, 0) <= 1}
        wd_name = unique_index((it, [it["label"]]) for it in ordered)

        points, no_radon, no_coord = [], [], []
        abbr_found = set()
        for gname, g in sorted(gus.items()):
            r = next((r_index[k] for k in name_keys(gname) if k in r_index), None)
            official = r["name"] if r else gname
            cands = []
            if r and domain(r.get("www")) in wd_dom:
                cands.append(wd_dom[domain(r.get("www"))])
            for n in ([official] + ([x["name"] for x in r.get("names") or []] if r else []) + [gname]):
                cands += [wd_name[k] for k in name_keys(n) if k in wd_name]
            w = next((c for c in cands if city_ok(c["label"], g["campuses"])), None)
            lon, lat = w["coord"] if w and w["coord"] else (None, None)
            ev = evals.get(r["institutionUuid"]) if r else None
            cats = {k: v[0] for k, v in sorted(ev.items())} if ev else {}
            ev_periods: dict[str, int] = {}
            for _, period in (ev or {}).values():
                ev_periods[period] = ev_periods.get(period, 0) + 1
            abbr = ABBR.get(slug(official))
            if abbr:
                abbr_found.add(slug(official))
            students = [v for v in g["campuses"].values() if v is not None]
            props = {
                "official_name": official,
                "gus_name": gname,
                "abbr": abbr,
                "kind": KINDS.get(slug(r.get("iKindName", ""))) if r else None,
                "profile": r.get("uTypeName") if r else None,
                "status": r.get("status") if r else None,
                "students_total": sum(students) if students else None,
                "campuses": g["campuses"],
                "voivodeship": g["voivodeship"],
                "voivodeship_code": voivodeship_code(g["voivodeship"].replace(" ", "")),
                "address": (", ".join(x for x in [" ".join(y for y in [r.get("street"), r.get("bNumber")] if y),
                                                   " ".join(y for y in [r.get("postalCd"), r.get("city")] if y)] if x)
                            if r else None),
                "www": r.get("www") if r else None,
                "radon_uuid": r.get("institutionUuid") if r else None,
                "wikidata": w["qid"] if w else None,
                "evaluation_periods": dict(sorted(ev_periods.items())) or None,
                "categories": cats or None,
                "count_a_plus": sum(1 for c in cats.values() if c == "A+") if ev else None,
                "count_a": sum(1 for c in cats.values() if c == "A") if ev else None,
                "ref": "https://radon.nauka.gov.pl/dane/instytucje" if r else GUS_XLSX,
            }
            if r is None:
                no_radon.append(gname)
            if lon is None:
                no_coord.append(official)
            points.append({"id": "uni_" + (r["institutionUuid"] if r else slug(gname)), "name": official,
                           "kind": "university", "lon": lon, "lat": lat, "props": props})
        points.sort(key=lambda p: -(p["props"]["students_total"] or 0))
        total = sum(p["props"]["students_total"] or 0 for p in points)
        with_cat = sum(1 for p in points if p["props"]["categories"])
        periods: dict[str, int] = {}
        for p in points:
            for period, n in (p["props"]["evaluation_periods"] or {}).items():
                periods[period] = periods.get(period, 0) + n
        notes = [
            "rule: every higher-education institution with at least one student in GUS table 2_2 for 2025/26 "
            "(state on 31 Dec 2025). Students = sum of the institution's city rows.",
            "GUS counts enrolments (a person on two programmes counts twice). Sum over institutions "
            f"{total:,}; GUS national total {national:,} (the difference is values withheld as '.').",
            f"RAD-on join by name: {len(points) - len(no_radon)} of {len(points)} matched. Unmatched: "
            + "; ".join(no_radon) if no_radon else f"RAD-on join by name: all {len(points)} matched.",
            f"Coordinates (Wikidata P625, main seat): {len(points) - len(no_coord)} of {len(points)}. "
            "Without a position (lon/lat null): " + "; ".join(no_coord) if no_coord else
            f"Coordinates (Wikidata P625): all {len(points)}.",
            f"Research categories (RAD-on evaluation, newest grade per discipline): {with_cat} institutions; "
            f"discipline grades by period {dict(sorted(periods.items()))}. The 2022-2025 results (published "
            "2026) are partial, so other disciplines keep their 2017-2021 grade (props.evaluation_periods).",
            "Abbreviations not matched to an institution: "
            + (", ".join(sorted(set(ABBR) - abbr_found)) or "none"),
        ]
        return {
            "vintage": "GUS academic year 2025/26 (31 Dec 2025); RAD-on evaluations 2017-2021 and 2022-2025; "
                       "Wikidata positions",
            "tables": {
                "students": {
                    "level": "country",
                    "fields": {"students": {"label": "Students (enrolments)", "unit": "persons", "year": 2025,
                                            "note": "GUS, 31 Dec 2025, academic year 2025/26"},
                               "institutions": {"label": "Institutions with students", "unit": "institutions",
                                                "year": 2025}},
                    "rows": {"PL": {"students": national, "institutions": len(points)}},
                },
            },
            "points": points,
            "notes": notes,
            "_files": ["gus_studenci_2025_2026_tab2_2.xlsx", "wikidata_hei.json"]
            + sorted(str(p.relative_to(self.raw_dir)) for p in (self.raw_dir / "radon").glob("*.json")),
        }

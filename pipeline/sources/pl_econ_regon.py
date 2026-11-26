"""GUS monthly REGON tables by gmina: firms by PKD section, sole traders and new registrations.

GUS publishes "Miesieczna informacja o podmiotach gospodarki narodowej w rejestrze REGON" every month with XML
tables by voivodeship, subregion, powiat and gmina. This source uses three of them:

* t03: entities by PKD 2007 section (state at the end of the month),
* t04: natural persons running a business, by PKD section (sole traders),
* t06: entities newly registered in the month (12 monthly files are summed).

XML rows are gminas (type 1, 2, 3), the town and rural parts of urban-rural gminas (type 4, 5, which repeat
type 3) and, for Warszawa, Krakow, Lodz, Poznan and Wroclaw, the districts and delegations (type 8, 9). For those
five cities the type 1 row holds only the entities not assigned to a district, so the city is the type 1 row
plus its districts.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from pipeline.core.source import Source, SourceInfo
from pipeline.core.store import load_interim

SECTION_URL = (
    "https://stat.gov.pl/obszary-tematyczne/podmioty-gospodarcze-wyniki-finansowe/zmiany-strukturalne-grup-podmiotow/"
)
BASE = "https://stat.gov.pl"
RELEASE_RE = re.compile(
    r"/obszary-tematyczne/podmioty-gospodarcze-wyniki-finansowe/zmiany-strukturalne-grup-podmiotow/"
    r"miesieczna-informacja-o-podmiotach-gospodarki-narodowej-w-rejestrze-regon-([a-z]+)-(\d{4}),\d+,\d+\.html"
)
MONTHS = {
    "styczen": 1, "luty": 2, "marzec": 3, "kwiecien": 4, "maj": 5, "czerwiec": 6, "lipiec": 7, "sierpien": 8,
    "wrzesien": 9, "pazdziernik": 10, "listopad": 11, "grudzien": 12,
}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]
TABLES = {"t03": "t03_dane_teryt_pkd", "t04": "t04_dane_teryt_pkd_fizyczne", "t06": "t06_dane_teryt_sfp_nowe"}
WINDOW = 12
LICENCE = "Statistics Poland (GUS), reuse with attribution (Creative Commons Attribution 4.0)."


def ym(year: int, month: int) -> str:
    return f"{year:04d}{month:02d}"


def shift(month: str, back: int) -> str:
    n = int(month[:4]) * 12 + int(month[4:]) - 1 - back
    return ym(n // 12, n % 12 + 1)


def month_label(month: str) -> str:
    return f"{MONTH_NAMES[int(month[4:]) - 1]} {month[:4]}"


def release_links(html: str) -> dict[str, str]:
    """YYYYMM -> absolute release page URL for every monthly REGON release linked on a page."""
    out = {}
    for m in RELEASE_RE.finditer(html):
        month = MONTHS.get(m.group(1))
        if month:
            out[ym(int(m.group(2)), month)] = BASE + m.group(0)
    return out


def table_link(html: str, month: str, table: str) -> str | None:
    m = re.search(r'href="([^"]*/' + month + "_" + TABLES[table] + r'\.xml)"', html)
    if not m:
        return None
    return m.group(1) if m.group(1).startswith("http") else BASE + m.group(1)


def read_table(path: Path) -> tuple[str, dict[str, dict[str, int]]]:
    """(header comment, {TERYT7 code of the XML row: {column: int}}) of one REGON XML table."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<!--(.*?)-->", text, re.S)
    header = " ".join(m.group(1).split()) if m else ""
    root = ET.fromstring(text[m.end():] if m else text)
    rows = {}
    for item in root:
        rec = {c.tag: (c.text or "").strip() for c in item}
        code = rec.get("TERYT_WO_kod", "") + rec.get("TERYT_POW_kod", "") + rec.get("TERYT_GMI_kod", "")
        if len(code) != 7 or not code.isdigit():
            raise ValueError(f"{path.name}: bad TERYT code {code!r}")
        if code in rows:
            raise ValueError(f"{path.name}: duplicate row {code}")
        values = {}
        for k, v in rec.items():
            if k.startswith("TERYT_"):
                continue
            if not v.isdigit():
                raise ValueError(f"{path.name}: {code} {k} is not a count: {v!r}")
            values[k.upper()] = int(v)
        rows[code] = values
    return header, rows


def whole_gminas(rows: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Gmina totals: types 1, 2, 3 as published, plus districts and delegations (8, 9) added to their city.
    Town and rural parts (4, 5) repeat their type 3 gmina and are skipped."""
    out: dict[str, dict[str, int]] = {}
    for code, values in rows.items():
        kind = code[-1]
        if kind in "123":
            target = code
        elif kind in "89":
            target = code[:4] + "011"
        elif kind in "45":
            continue
        else:
            raise ValueError(f"unexpected TERYT type digit in {code}")
        acc = out.setdefault(target, {})
        for k, v in values.items():
            acc[k] = acc.get(k, 0) + v
    return out


def on_current(rows: dict[str, dict[str, int]], gminas: list[str]) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Rows keyed by today's TERYT7 code (matched on the first six digits). Returns the rows and unmatched codes."""
    by6 = {g[:6]: g for g in gminas}
    out, lost = {}, []
    for code, values in rows.items():
        target = by6.get(code[:6])
        if target is None:
            lost.append(code)
            continue
        acc = out.setdefault(target, {})
        for k, v in values.items():
            acc[k] = acc.get(k, 0) + v
    return out, sorted(lost)


def per(count: int | None, population: int | float | None, scale: int, digits: int) -> float | None:
    if count is None or not population or population <= 0:
        return None
    return round(count * scale / population, digits)


class PlEconRegonSource(Source):
    info = SourceInfo(
        id="pl_econ_regon",
        title="REGON register by gmina: firms by PKD section, sole traders, new registrations",
        publisher="Statistics Poland (GUS)",
        homepage=SECTION_URL,
        description="Monthly REGON tables 3, 4 and 6 by gmina (newest month, and 12 months of new registrations).",
        license="Creative Commons Attribution 4.0",
        used_for=["Lenses"],
    )

    def fetch(self, force: bool = False) -> None:
        listing = self.download(SECTION_URL, "pages/list.html", force=force).read_text(encoding="utf-8")
        links = release_links(listing)
        if not links:
            raise RuntimeError("no monthly REGON release linked on the GUS section page")
        newest = max(links)
        page = self.download(links[newest], f"pages/{newest}.html", force=force).read_text(encoding="utf-8")
        links.update(release_links(page))
        for back in range(WINDOW):
            month = shift(newest, back)
            if month not in links:
                raise RuntimeError(f"REGON release {month} is not linked from {links[newest]}")
            html = page if back == 0 else self.download(links[month], f"pages/{month}.html").read_text(
                encoding="utf-8")
            for table in (("t03", "t04", "t06") if back == 0 else ("t06",)):
                url = table_link(html, month, table)
                if url is None:
                    raise RuntimeError(f"REGON {month}: no {table} XML on {links[month]}")
                self.download(url, f"{month}/{table}.xml", force=force and back == 0, expect_binary=True)

    def newest_month(self) -> str:
        months = sorted(p.name for p in self.raw_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{6}", p.name))
        for month in reversed(months):
            if all((self.raw_dir / month / f"{t}.xml").exists() for t in ("t03", "t04", "t06")):
                return month
        raise FileNotFoundError(f"no complete REGON month in {self.raw_dir}")

    def process(self) -> dict:
        teryt = load_interim("pl_geo_teryt")
        gminas = [g["code"] for g in teryt["gminy"]]
        pop_data = load_interim("pl_stats_population")["tables"]["population"]
        population = {code: (row or {}).get("population") for code, row in pop_data["rows"].items()}
        pop_date = ((pop_data["fields"].get("population") or {}).get("note") or "").split(",")[0]
        newest = self.newest_month()
        months = [shift(newest, back) for back in range(WINDOW)]
        files = [f"{newest}/t03.xml", f"{newest}/t04.xml"] + [f"{m}/t06.xml" for m in months]
        missing = [f for f in files if not (self.raw_dir / f).exists()]
        if missing:
            raise FileNotFoundError(f"REGON files missing: {', '.join(missing)} (run fetch)")

        header3, t03 = read_table(self.raw_dir / f"{newest}/t03.xml")
        header4, t04 = read_table(self.raw_dir / f"{newest}/t04.xml")
        for header in (header3, header4):
            if "PKD 2007" not in header:
                raise ValueError(f"REGON table header does not name PKD 2007: {header!r}")
        firms, lost3 = on_current(whole_gminas(t03), gminas)
        sole, lost4 = on_current(whole_gminas(t04), gminas)
        new: dict[str, int] = {}
        lost6: list[str] = []
        for m in months:
            _, t06 = read_table(self.raw_dir / f"{m}/t06.xml")
            rows, lost = on_current(whole_gminas(t06), gminas)
            lost6 += lost
            for code, values in rows.items():
                new[code] = new.get(code, 0) + values["OGOLEM"]

        out = {}
        for code in gminas:
            f, s = firms.get(code), sole.get(code)
            total = f["OGOLEM"] if f else None
            ict = f["DZIAL_J"] if f else None
            sole_n = s["OGOLEM"] if s else None
            new_n = new.get(code)
            pop = population.get(code)
            out[code] = {
                "entities": total,
                "ict_entities": ict,
                "ict_share": round(ict * 100 / total, 3) if total else None,
                "sole_traders": sole_n,
                "sole_traders_per_1000": per(sole_n, pop, 1000, 2),
                "new_entities_12m": new_n,
                "new_entities_per_1000": per(new_n, pop, 1000, 2),
            }
        national = {
            "entities": sum(v["OGOLEM"] for v in firms.values()),
            "ict_entities": sum(v["DZIAL_J"] for v in firms.values()),
            "sole_traders": sum(v["OGOLEM"] for v in sole.values()),
            "new_entities_12m": sum(new.values()),
        }
        national["ict_share"] = round(national["ict_entities"] * 100 / national["entities"], 3)
        xml_total = sum(v["OGOLEM"] for c, v in t03.items() if c[-1] in "12389")
        if xml_total != national["entities"]:
            raise ValueError(f"REGON t03: gmina sum {national['entities']} != XML sum {xml_total}")

        state = f"End of {month_label(newest)}"
        span = f"{month_label(months[-1])} to {month_label(newest)}"
        year = int(newest[:4])
        fields = {
            "entities": {"label": "Entities in REGON", "unit": "entities", "year": year,
                         "note": f"{state}, GUS REGON table 3 (without private farmers)."},
            "ict_entities": {"label": "Entities in PKD 2007 section J (information and communication)",
                             "unit": "entities", "year": year, "note": f"{state}, GUS REGON table 3."},
            "ict_share": {"label": "Share of entities in information and communication", "unit": "%",
                          "year": year, "note": f"{state}, section J entities / all entities (PKD 2007)."},
            "sole_traders": {"label": "Natural persons running a business", "unit": "persons", "year": year,
                             "note": f"{state}, GUS REGON table 4 (without private farmers)."},
            "sole_traders_per_1000": {"label": "Sole traders per 1,000 residents", "unit": "per 1,000 residents",
                                      "year": year,
                                      "note": f"{state}; population on {pop_date}."},
            "new_entities_12m": {"label": "Entities newly registered in REGON in 12 months", "unit": "entities",
                                 "year": year, "note": f"{span}, sum of 12 monthly GUS REGON tables 6."},
            "new_entities_per_1000": {"label": "New entities per 1,000 residents in 12 months",
                                      "unit": "per 1,000 residents", "year": year,
                                      "note": f"{span}; population on {pop_date}."},
        }
        lost = sorted(set(lost3 + lost4 + lost6))
        return {
            "vintage": f"GUS REGON, state at the end of {month_label(newest)}; new registrations {span}",
            "tables": {
                "regon_gmina": {"level": "gmina", "fields": fields, "rows": out},
                "regon_country": {
                    "level": "country",
                    "fields": {k: fields[k] for k in national},
                    "rows": {"PL": national},
                },
            },
            "notes": [
                LICENCE,
                f"Monthly REGON information, {month_label(newest)}: {SECTION_URL}",
                "Classification: PKD 2007 (the table headers say so). Section J is information and communication.",
                "Gmina = type 1, 2 or 3 row plus, for Warszawa, Kraków, Łódź, Poznań and Wrocław, the district "
                "and delegation rows (types 8, 9); town and rural parts (types 4, 5) are not added again.",
                f"The XML has no national row. The sum of whole gminas is {national['entities']} entities; the GUS "
                "headline for the month is slightly higher because a few thousand entities have no gmina.",
                "ICT share = section J / all entities. A few entities have no PKD section, so sections do not "
                "add up to the total.",
                "Counts are registered entities, not active firms or jobs. A sole trader is counted at the "
                "registered address, often the home address.",
                "Per 1,000 residents uses the newest population in the pipeline (pl_stats_population). GUS has "
                "no 18-64 age band by gmina in that table, so sole traders are per 1,000 residents of all ages.",
                "New registrations: 12 monthly files summed. Older months are matched to today's TERYT on the first "
                "six digits." + (f" Codes without a match: {', '.join(lost)}." if lost else ""),
            ],
            "_files": files + ["pages/list.html", f"pages/{newest}.html"],
        }

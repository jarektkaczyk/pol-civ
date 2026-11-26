"""Installed renewable capacity by powiat (URE "Mapa OZE").

URE (Urząd Regulacji Energetyki) lists every licensed and registered renewable installation (not
micro-installations under 50 kW) with its powiat, gmina and electrical capacity, a few times a year.
The newest list on the URE page is found and downloaded; powiat names are turned into TERYT codes with
GUS's BDL unit list (level 5 = powiats).
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
from collections import defaultdict

from ..core.source import Source, SourceInfo
from ._resource_util import download_checked, num, xlsx_rows

URE_PAGE = ("https://www.ure.gov.pl/pl/oze/potencjal-krajowy-oze/8108,"
            "Instalacje-odnawialnych-zrodel-energii-stan-na-30-wrzesnia-2026-r.html")
URE_BASE = "https://www.ure.gov.pl"
BDL_UNITS = "https://bdl.stat.gov.pl/api/v1/units?level=5&page-size=100&format=json&lang=pl&page={page}"

VOIV = {  # voivodeship name (lower case, as in URE) -> TERYT
    "dolnośląskie": "02", "kujawsko-pomorskie": "04", "lubelskie": "06", "lubuskie": "08", "łódzkie": "10",
    "małopolskie": "12", "mazowieckie": "14", "opolskie": "16", "podkarpackie": "18", "podlaskie": "20",
    "pomorskie": "22", "śląskie": "24", "świętokrzyskie": "26", "warmińsko-mazurskie": "28",
    "wielkopolskie": "30", "zachodniopomorskie": "32",
}
TYPES = {  # URE "Rodzaj OZE" -> field
    "WIL": "wind_mw", "PVA": "solar_mw", "BM": "biomass_mw", "BG": "biogas_mw", "WO": "hydro_mw",
    "ITPO": "waste_mw", "WS": "cofiring_mw", "H2": "hydrogen_mw",
}
LABELS = {
    "wind_mw": "Wind (onshore)", "solar_mw": "Solar PV", "biomass_mw": "Biomass", "biogas_mw": "Biogas",
    "hydro_mw": "Hydro", "waste_mw": "Waste-to-energy (renewable part)", "cofiring_mw": "Co-firing with biomass",
    "hydrogen_mw": "Renewable hydrogen", "res_mw": "Renewables, dedicated installations (without co-firing)",
}


def _file_date(name: str) -> str | None:
    """'...30092026...' or '...30-09-2026...' in a URE file name -> '2026-09-30'."""
    m = re.search(r"(\d{2})[.-]?(\d{2})[.-]?(\d{4})", name)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def norm_name(text: str) -> str:
    """Comparable powiat name: 'Powiat m. Kraków' / 'm. Kraków' / 'Kraków' -> 'krakow'."""
    t = (text or "").strip().lower()
    t = re.sub(r"^powiat\s+", "", t)
    t = re.sub(r"^m\.\s*(st\.\s*)?", "", t)
    t = t.replace("ł", "l")
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return re.sub(r"[^a-z]+", " ", t).strip()


def is_city(text: str) -> bool:
    """A city with powiat rights: 'm. Kraków', or a capitalised name without '-ski/-cki' ending."""
    t = (text or "").strip()
    t = re.sub(r"^Powiat\s+", "", t)
    return t.startswith("m.") or (t[:1].isupper() and not re.search(r"(ski|cki|dzki)$", t))


def bdl_powiats(pages: list[dict]) -> dict[tuple[str, str, bool], str]:
    """{(voivodeship TERYT, normalised name, is city): powiat TERYT} from BDL level-5 unit pages."""
    out: dict[tuple[str, str, bool], str] = {}
    for doc in pages:
        for u in doc.get("results", []):
            uid, name = u["id"], u["name"]
            if re.search(r"\sdo \d{4}$", name):
                continue  # a former unit ('Powiat m. Wałbrzych do 2002')
            name = re.sub(r"\s+od \d{4}$", "", name)
            teryt = uid[2:4] + uid[7:9]
            key = (uid[2:4], norm_name(name), u.get("kind") == "2" or " m. " in f" {name} ")
            prev = out.get(key)
            if prev and prev != teryt:
                raise ValueError(f"BDL powiat name {u['name']!r} maps to {prev} and {teryt}")
            out[key] = teryt
    return out


def aggregate(rows, powiats: dict) -> tuple[dict[str, dict[str, float]], list[str], int]:
    """Sum MW per powiat and type. Returns (rows by TERYT, unmatched names, installation count)."""
    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    count: dict[str, int] = defaultdict(int)
    unmatched, n = set(), 0
    for r in rows:
        if not (r.get("A") or "").strip().isdigit():
            continue
        voiv = VOIV.get((r.get("D") or "").strip().lower())
        mw, kind = num(r.get("G")), (r.get("H") or "").strip()
        if voiv is None or mw is None or kind not in TYPES:
            unmatched.add(f"row {r.get('A')}: {r.get('D')!r} {r.get('E')!r} {r.get('H')!r}")
            continue
        name = (r.get("E") or "").strip()
        key = (voiv, norm_name(name), is_city(name))
        teryt = powiats.get(key) or powiats.get((voiv, norm_name(name), not key[2]))
        if teryt is None:
            unmatched.add(f"{voiv} {name}")
            continue
        acc[teryt][TYPES[kind]] += mw
        count[teryt] += 1
        n += 1
    out = {}
    for teryt, d in acc.items():
        row = {f: round(d[f], 3) if f in d else None for f in TYPES.values()}
        row["res_mw"] = round(sum(v for k, v in d.items() if k != "cofiring_mw"), 3)
        row["installations"] = count[teryt]
        out[teryt] = row
    return out, sorted(unmatched), n


class PlEnergyRes(Source):
    info = SourceInfo(
        id="pl_energy_res",
        title="Installed renewable capacity by powiat (URE Mapa OZE)",
        publisher="Urząd Regulacji Energetyki (Energy Regulatory Office); powiat codes from GUS BDL",
        homepage=URE_PAGE,
        license="Public information (Polish re-use of public sector information act); cite URE",
        description="Electrical capacity of licensed and registered renewable installations (wind, solar, biomass, "
        "biogas, hydro, waste) per powiat. Micro-installations such as rooftop solar are not included.",
        used_for=["Energy advisor", "renewables lens by powiat"],
    )

    PAGE = "ure_page.html"
    BDL = "bdl_units_level5_p{page}.json"

    def _xlsx_name(self) -> str | None:
        cached = sorted(self.raw_dir.glob("mapa_oze_*.xlsx"), key=lambda p: _file_date(p.name) or "")
        return cached[-1].name if cached else None

    def fetch(self, force=False):
        if force or not self._xlsx_name():
            page = self.download(URE_PAGE, self.PAGE, force=True)
            links = re.findall(r'href="(/download/9/(\d+)/[^"]+\.xlsx)"', page.read_text(encoding="utf-8",
                                                                                     errors="replace"))
            if not links:
                raise RuntimeError(f"no xlsx link on {URE_PAGE}")
            href, _ = max(links, key=lambda h: int(h[1]))  # the newest upload has the highest id
            name = "mapa_oze_" + href.rsplit("/", 1)[-1]
            if not download_checked(self, urllib.parse.urljoin(URE_BASE, href), name, force=force, magic=b"PK"):
                raise RuntimeError(f"URE file {href} is not an xlsx")
        for page in range(4):
            self.download(BDL_UNITS.format(page=page), self.BDL.format(page=page), force=force)

    def process(self):
        name = self._xlsx_name()
        if not name:
            raise FileNotFoundError("no URE Mapa OZE xlsx - run: uv run python -m pipeline fetch pl_energy_res")
        path = self.raw_dir / name
        rows = list(xlsx_rows(path))
        header = next((r for r in rows if "Rodzaj OZE" in r.values()), None)
        if header is None or header.get("G", "").find("Moc") < 0 or header.get("E", "").find("Powiat") < 0:
            raise ValueError(f"{name}: unexpected header {header}")
        sheet_date = _file_date(name)
        pages = [json.loads((self.raw_dir / self.BDL.format(page=p)).read_text(encoding="utf-8")) for p in range(4)]
        powiats = bdl_powiats(pages)
        table, unmatched, n = aggregate(rows, powiats)
        if unmatched:
            print(f"    ! {len(unmatched)} unmatched rows/names: {unmatched[:5]}")
        year = int(sheet_date[:4]) if sheet_date else None
        fields = {f: {"label": LABELS[f], "unit": "MW", "year": year, "note": f"URE Mapa OZE as of {sheet_date}"}
                  for f in list(TYPES.values()) + ["res_mw"]}
        fields["installations"] = {"label": "Installations listed", "unit": "count", "year": year}
        totals = defaultdict(float)
        for r in table.values():
            for f in TYPES.values():
                totals[f] += r[f] or 0.0
        return {
            "vintage": f"URE Mapa OZE {sheet_date}",
            "as_of": sheet_date,
            "tables": {"res_capacity_powiat": {"level": "powiat", "fields": fields, "rows": table}},
            "notes": [
                f"URE list of renewable installations as of {sheet_date}: {n} installations matched to powiats. "
                "Micro-installations (rooftop PV and others under 50 kW) are not in the list.",
                "A powiat with no installation of a type has null for that type (absent from the list, not zero).",
                "cofiring_mw is the capacity of coal or gas units licensed to co-fire biomass; it is kept apart and "
                "left out of res_mw.",
                "An installation licensed in several towns is listed by URE under one powiat.",
                "Powiat codes: GUS BDL level-5 units (TERYT = id[2:4] + id[7:9]), matched by voivodeship and name.",
                "National sums (MW): " + ", ".join(f"{k} {v:.0f}" for k, v in sorted(totals.items())),
            ] + ([f"Left out (voivodeship and powiat do not match any GUS powiat, a URE data error): "
                  f"{', '.join(unmatched[:20])}"] if unmatched else []),
            "_files": [name] + [self.BDL.format(page=p) for p in range(4)],
        }

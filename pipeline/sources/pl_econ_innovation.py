"""GUS DBW (Dziedzinowe Bazy Wiedzy): patents granted by powiat and R&D spending per resident by voivodeship.

* Variable 463 "Udzielone patenty", section 169 (Poland, voivodeships, powiaty; applicant type), position
  "Ogolem" (all applicants). The two newest published years are added together.
* Variable 406 "Naklady wewnetrzne na dzialalnosc B+R", section 2 "na 1 mieszkanca" (per resident, PLN),
  voivodeships, the newest published year.

DBW unit symbols are 14 digits; the TERYT code is symbol[4:6] (voivodeship) + symbol[9:11] (powiat).
DBW marks each value: 253 a published value, 42 "zjawisko nie wystapilo" (zero), 38 no information
(confidential or not applicable), so 38 stays null.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
from pathlib import Path

from pipeline.core.source import Source, SourceInfo
from pipeline.core.store import load_interim

API = "https://api-dbw.stat.gov.pl/api"
DATA_URL = (API + "/variable/variable-data-section?id-zmienna={var}&id-przekroj={section}&id-rok={year}"
            "&id-okres=282&ile-na-stronie=5000&numer-strony=0&lang=pl")
POSITIONS_URL = API + "/variable/variable-section-position?id-przekroj={section}&lang=pl"
PATENTS = (463, 169)
RD = (406, 2)
ALL_APPLICANTS = 2541630  # section 169, dimension 203 "Podmioty zglaszajace": "Ogolem"
UNIT_COUNT = 94  # "sztuka"
UNIT_PLN_PER_RESIDENT = 122  # "na 1 mieszkanca [zl]", current prices
VALUE, ZERO, NO_INFO = 253, 42, 38
LICENCE = "Statistics Poland (GUS), Creative Commons Attribution 4.0."
FIRST_YEAR_BACK = 3  # years tried: run year and the 3 before it


def data_file(var: int, section: int, year: int) -> str:
    return f"dbw/{var}-{section}-{year}.json"


def positions_file(section: int) -> str:
    return f"dbw/positions-{section}.json"


def teryt(symbol: str) -> str:
    """14-digit DBW unit symbol -> TERYT ('PL' for Poland, 2 digits voivodeship, 4 digits powiat)."""
    if len(symbol) != 14 or not symbol.isdigit():
        raise ValueError(f"invalid DBW unit symbol {symbol!r}")
    if symbol == "10000000000000":
        return "PL"
    voiv, powiat = symbol[4:6], symbol[9:11]
    return voiv if powiat == "00" else voiv + powiat


def units(positions: list[dict], dimension: int) -> dict[int, str]:
    """DBW position id -> TERYT code for the territorial units that still exist."""
    out = {}
    for p in positions:
        if p["id-wymiar"] != dimension or not str(p.get("data-konca", "")).startswith("9999"):
            continue
        out[p["id-pozycja"]] = teryt(p["symbol"])
    return out


def cell_value(row: dict) -> float | None:
    """The published value of one DBW cell; null when GUS gives no information or the record contradicts itself."""
    flag, value = row.get("id-brak-wartosci"), row.get("wartosc")
    if flag == VALUE:
        return value
    if flag == ZERO:
        return 0 if not value else None  # a "did not occur" flag with a non-zero value is contradictory
    return None


def read_rows(raw: Path, rel: str) -> list[dict]:
    doc = json.loads((raw / rel).read_text())
    if doc.get("page-count", 1) > 1:
        raise ValueError(f"{rel}: more than one page")
    return doc.get("data") or []


def has_values(rows: list[dict]) -> bool:
    return any(r.get("id-brak-wartosci") == VALUE for r in rows)


def patents_by_unit(rows: list[dict], codes: dict[int, str]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for r in rows:
        if r["id-pozycja-2"] != ALL_APPLICANTS or r["id-pozycja-1"] not in codes:
            continue
        if r["id-sposob-prezentacji-miara"] != UNIT_COUNT:
            raise ValueError("DBW patents: unexpected unit")
        out[codes[r["id-pozycja-1"]]] = cell_value(r)
    return out


class PlEconInnovationSource(Source):
    info = SourceInfo(
        id="pl_econ_innovation",
        title="Patents granted and R&D spending",
        publisher="Statistics Poland (GUS), Dziedzinowe Bazy Wiedzy",
        homepage="https://dbw.stat.gov.pl/",
        description="Patents granted by powiat (all applicants) and gross domestic R&D spending per resident by "
                    "voivodeship.",
        license="Creative Commons Attribution 4.0",
        used_for=["Lenses"],
    )

    def years(self) -> list[int]:
        now = dt.date.today().year
        return list(range(now, now - FIRST_YEAR_BACK - 1, -1))

    def fetch(self, force: bool = False) -> None:
        for _var, section in (PATENTS, RD):
            self.download(POSITIONS_URL.format(section=section), positions_file(section), force=force)
        for (var, section), need in ((PATENTS, 2), (RD, 1)):
            found = 0  # newest published years in a row
            for year in self.years():
                rel = data_file(var, section, year)
                if self.offline and not (self.raw_dir / rel).exists():
                    continue
                try:
                    self.download(DATA_URL.format(var=var, section=section, year=year), rel, force=force)
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:  # DBW answers 404 for a year it does not know yet
                        raise
                    continue
                found = found + 1 if has_values(read_rows(self.raw_dir, rel)) else 0 if found else found
                if found == need:
                    break

    def done_years(self, var: int, section: int) -> set[int]:
        out = set()
        for path in (self.raw_dir / "dbw").glob(f"{var}-{section}-*.json"):
            year = int(path.stem.rsplit("-", 1)[1])
            if has_values(read_rows(self.raw_dir, f"dbw/{path.name}")):
                out.add(year)
        return out

    def process(self) -> dict:
        pat_years = sorted(self.done_years(*PATENTS), reverse=True)
        pair = next(((y, y - 1) for y in pat_years if (y - 1) in pat_years), None)
        if pair is None:
            raise FileNotFoundError("DBW patents: no two consecutive published years cached (run fetch)")
        rd_years = sorted(self.done_years(*RD), reverse=True)
        if not rd_years:
            raise FileNotFoundError("DBW R&D: no published year cached (run fetch)")
        rd_year = rd_years[0]

        pat_codes = units(json.loads((self.raw_dir / positions_file(PATENTS[1])).read_text()), 10)
        per_year = [patents_by_unit(read_rows(self.raw_dir, data_file(*PATENTS, y)), pat_codes) for y in pair]

        pop = load_interim("pl_stats_population")["tables"]["population"]
        pop_field = "population_2025"
        pop_date = ((pop["fields"].get(pop_field) or {}).get("note") or "").split(",")[0]
        powiat_pop: dict[str, float] = {}
        for code, row in pop["rows"].items():
            v = (row or {}).get(pop_field)
            if v is not None:
                powiat_pop[code[:4]] = powiat_pop.get(code[:4], 0) + v
        powiaty = [p["code"] for p in load_interim("pl_geo_teryt")["powiaty"]]

        pat_rows = {}
        for code in powiaty:
            vals = [y.get(code) for y in per_year]
            total = None if any(v is None for v in vals) else int(sum(vals))
            people = powiat_pop.get(code)
            pat_rows[code] = {
                "patents": total,
                "patents_per_100k": round(total * 100000 / people, 1) if total is not None and people else None,
            }
        national = [y.get("PL") for y in per_year]

        rd_codes = units(json.loads((self.raw_dir / positions_file(RD[1])).read_text()), 4)
        rd_rows: dict[str, dict] = {}
        for r in read_rows(self.raw_dir, data_file(*RD, rd_year)):
            code = rd_codes.get(r["id-pozycja-1"])
            if code is None:
                continue
            if r["id-sposob-prezentacji-miara"] != UNIT_PLN_PER_RESIDENT:
                raise ValueError("DBW R&D: unexpected unit")
            rd_rows[code] = {"rd_spending_per_resident": cell_value(r)}
        rd_national = rd_rows.pop("PL", {}).get("rd_spending_per_resident")

        y1, y0 = pair[1], pair[0]
        years = f"{y1} and {y0}"
        missing = sorted(c for c, v in pat_rows.items() if v["patents"] is None)
        return {
            "vintage": f"GUS DBW: patents granted {years}; R&D spending {rd_year}",
            "tables": {
                "patents_powiat": {
                    "level": "powiat",
                    "fields": {
                        "patents": {"label": "Patents granted", "unit": "patents", "year": y0,
                                    "note": f"{years} together, all applicants, by the applicant's seat (GUS DBW "
                                            f"variable 463)."},
                        "patents_per_100k": {"label": "Patents granted per 100,000 residents",
                                             "unit": "per 100,000 residents", "year": y0,
                                             "note": f"{years} together; population on {pop_date}."},
                    },
                    "rows": pat_rows,
                },
                "rd_voivodeship": {
                    "level": "voivodeship",
                    "fields": {
                        "rd_spending_per_resident": {
                            "label": "Gross domestic R&D expenditure per resident", "unit": "PLN", "year": rd_year,
                            "note": f"{rd_year}, current prices (GUS DBW variable 406, per resident)."},
                    },
                    "rows": rd_rows,
                },
                "innovation_country": {
                    "level": "country",
                    "fields": {
                        "patents": {"label": "Patents granted", "unit": "patents", "year": y0,
                                    "note": f"{years} together, all applicants."},
                        "rd_spending_per_resident": {
                            "label": "Gross domestic R&D expenditure per resident", "unit": "PLN", "year": rd_year,
                            "note": f"{rd_year}, current prices."},
                    },
                    "rows": {"PL": {
                        "patents": None if None in national else int(sum(national)),
                        "rd_spending_per_resident": rd_national,
                    }},
                },
            },
            "notes": [
                LICENCE,
                "Patents: " + DATA_URL.format(var=PATENTS[0], section=PATENTS[1], year=y0) + " (and the year before).",
                "R&D: " + DATA_URL.format(var=RD[0], section=RD[1], year=rd_year) + ".",
                "Powiat data cover national applications filed in the national procedure. A patent counts at the "
                "seat of its first applicant, so university and research-institute cities rank high.",
                "DBW flag 42 ('did not occur') is 0; flag 38 (no information) is null."
                + (f" Null powiaty: {', '.join(missing)}." if missing else ""),
                "A record flagged 'did not occur' with a non-zero value is contradictory and stays null.",
                f"Per 100,000 residents uses the powiat population on {pop_date} (sum of its gminas).",
                "R&D spending is gross domestic expenditure on R&D (GERD) of all sectors, by the voivodeship "
                "of the unit that does the research.",
            ],
            "_files": [positions_file(PATENTS[1]), positions_file(RD[1]), data_file(*PATENTS, y0),
                       data_file(*PATENTS, y1), data_file(*RD, rd_year)],
        }

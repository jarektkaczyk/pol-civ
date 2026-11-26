"""GUNB building permit register: new industrial and storage buildings per gmina.

The register (RWDZ, dane.gov.pl dataset 3467, CC0) is published as 16 zipped CSV files, one per voivodeship,
about 300 MB together. Each CSV row is one building object or one amendment of a permit decision, so a decision
is the unique pair (issuing authority, decision number).

The CSV holds the names of investors and designers. process() streams each zip member and keeps only six
columns (authority, decision number, decision date, TERC code, building category, kind of works). Names are never
read into the interim and no CSV is extracted to disk.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from pipeline.core.source import Source, SourceInfo
from pipeline.core.store import load_interim

DATASET_URL = "https://dane.gov.pl/pl/dataset/3467"
DATASET_API = "https://api.dane.gov.pl/1.4/datasets/3467"
ZIP_URL = "https://wyszukiwarka.gunb.gov.pl/pliki_pobranie/wynik_{slug}.zip"
LAW_URL = "https://eli.gov.pl/api/acts/DU/2025/418/text/U/D20250418Lj.pdf"
SLUGS = [
    "dolnoslaskie", "kujawsko-pomorskie", "lubelskie", "lubuskie", "lodzkie", "malopolskie", "mazowieckie",
    "opolskie", "podkarpackie", "podlaskie", "pomorskie", "slaskie", "swietokrzyskie", "warminsko-mazurskie",
    "wielkopolskie", "zachodniopomorskie",
]
CATEGORY = "XVIII"  # Prawo budowlane annex: industrial buildings and storage buildings (warehouses, cold stores)
NEW_BUILD = "budowa nowego"  # "budowa nowego/nowych obiektow budowlanych"
WINDOW_MONTHS = 24
# The only columns read from the CSV. Investor and designer names are never kept.
KEEP = ("nazwa_organu", "numer_decyzji_urzedu", "data_wydania_decyzji", "terc", "kategoria", "nazwa_zamierzenia_bud")
FIELD = "new_industrial_decisions"


def zip_file(slug: str) -> str:
    return f"wynik_{slug}.zip"


def months_before(day: dt.date, months: int) -> dt.date:
    """The same day `months` earlier (clamped to the month's last day)."""
    y, m = divmod(day.year * 12 + day.month - 1 - months, 12)
    return dt.date(y, m + 1, min(day.day, calendar.monthrange(y, m + 1)[1]))


def whole_gmina(code: str) -> str | None:
    """A TERC/TERYT7 code of a gmina part as the code of its whole gmina (the type digit may still be old).

    4 and 5 (town and rural area of an urban-rural gmina) become 3; 8 and 9 (Warsaw districts and city
    delegations) become the city, NNNN011."""
    code = (code or "").strip()
    if len(code) != 7 or not code.isdigit():
        return None
    kind = code[-1]
    if kind in "123":
        return code
    if kind in "45":
        return code[:6] + "3"
    if kind in "89":
        return code[:4] + "011"
    return None


def current_code(code: str | None, by6: dict[str, str]) -> str | None:
    """The gmina code in today's TERYT, matched on the first six digits (a type-only change keeps them)."""
    return None if code is None else by6.get(code[:6])


def iter_rows(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    """The KEEP columns of each CSV row (';' separated, header first). Other columns are dropped at once."""
    reader = csv.reader(lines, delimiter=";")
    header = [h.lstrip("\ufeff").strip() for h in next(reader)]
    idx = {}
    for name in KEEP:
        if name not in header:
            raise ValueError(f"GUNB CSV: column {name!r} missing")
        idx[name] = header.index(name)
    width = len(header)
    for row in reader:
        if len(row) != width:
            continue
        yield {name: row[i] for name, i in idx.items()}


def zip_lines(path: Path) -> tuple[Iterator[str], dt.date]:
    """Streamed text lines of the single CSV member, and the member's file date."""
    archive = zipfile.ZipFile(path)
    members = [m for m in archive.infolist() if m.filename.lower().endswith(".csv")]
    if len(members) != 1:
        raise ValueError(f"{path.name}: expected one CSV member")
    member = members[0]
    day = dt.date(*member.date_time[:3])
    stream = io.TextIOWrapper(archive.open(member), encoding="utf-8-sig", newline="")
    return stream, day


def parse_day(text: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat((text or "").strip()[:10])
    except ValueError:
        return None


def count_decisions(rows: Iterable[dict[str, str]], start: dt.date, end: dt.date, by6: dict[str, str],
                    decisions: dict[str, set], stats: dict[str, int]) -> None:
    """Add the unique (authority, decision number) pairs of new category XVIII buildings decided in
    (start, end] to `decisions[gmina]`. `stats` counts rows and unmapped decisions."""
    for row in rows:
        if row["kategoria"].strip() != CATEGORY or not row["nazwa_zamierzenia_bud"].strip().startswith(NEW_BUILD):
            continue
        day = parse_day(row["data_wydania_decyzji"])
        if day is None or not (start < day <= end):
            continue
        stats["rows"] = stats.get("rows", 0) + 1
        key = (row["nazwa_organu"].strip(), row["numer_decyzji_urzedu"].strip())
        code = current_code(whole_gmina(row["terc"]), by6)
        if code is None:
            stats.setdefault("unmapped", set()).add(key)
            continue
        decisions.setdefault(code, set()).add(key)


class PlEconPermitsSource(Source):
    info = SourceInfo(
        id="pl_econ_permits",
        title="Building permit register: new industrial and storage buildings",
        publisher="Główny Urząd Nadzoru Budowlanego (GUNB)",
        homepage=DATASET_URL,
        description="Building permit decisions for new industrial and storage buildings (category XVIII) per gmina.",
        license="CC0 1.0",
        used_for=["Lenses"],
    )

    def fetch(self, force: bool = False) -> None:
        self.download(DATASET_API, "dataset-3467.json", force=force)
        for slug in SLUGS:
            self.download(ZIP_URL.format(slug=slug), zip_file(slug), force=force, expect_binary=True)

    def process(self) -> dict:
        teryt = load_interim("pl_geo_teryt")
        gminas = [g["code"] for g in teryt["gminy"]]
        by6 = {g[:6]: g for g in gminas}
        streams = []
        for slug in SLUGS:
            lines, day = zip_lines(self.raw_dir / zip_file(slug))
            streams.append((slug, lines, day))
        end = max(day for _, _, day in streams)
        start = months_before(end, WINDOW_MONTHS)
        decisions: dict[str, set] = {}
        stats: dict = {}
        voiv: dict[str, int] = {}
        for slug, lines, _day in streams:
            before = sum(len(v) for v in decisions.values())
            count_decisions(iter_rows(lines), start, end, by6, decisions, stats)
            voiv[slug] = sum(len(v) for v in decisions.values()) - before
            lines.close()
        rows = {code: {FIELD: len(decisions.get(code, ()))} for code in gminas}
        total = sum(r[FIELD] for r in rows.values())
        unmapped = len(stats.get("unmapped", ()))
        period = f"{start + dt.timedelta(days=1)} to {end}"
        return {
            "vintage": f"GUNB permit register, decisions {period}",
            "tables": {
                "industrial_permits_gmina": {
                    "level": "gmina",
                    "fields": {
                        FIELD: {
                            "label": "Permit decisions for new industrial and storage buildings",
                            "unit": "decisions",
                            "year": end.year,
                            "note": (
                                f"Decisions issued {period} (24 months to the newest file date). Building category "
                                "XVIII, works 'budowa nowego'; unique pairs of issuing authority and decision number."
                            ),
                        },
                    },
                    "rows": rows,
                },
                "industrial_permits_country": {
                    "level": "country",
                    "fields": {
                        FIELD: {
                            "label": "Permit decisions for new industrial and storage buildings",
                            "unit": "decisions",
                            "year": end.year,
                            "note": f"Decisions issued {period}; sum of the gmina counts.",
                        },
                    },
                    "rows": {"PL": {FIELD: total}},
                },
            },
            "notes": [
                f"Source: {DATASET_URL} (CC0 1.0), 16 voivodeship files {ZIP_URL.format(slug='<voivodeship>')}.",
                f"Newest file date {end}; window {period}.",
                "Category XVIII of the Prawo budowlane annex: industrial buildings (production, energy, assembly, "
                f"slaughterhouses) and storage buildings (warehouses, cold stores, hangars, sheds), railway buildings. {LAW_URL}",
                "One CSV row is one building or amendment; a decision is counted once per gmina by (authority, "
                f"decision number). {stats.get('rows', 0)} matching rows give {total} gmina-decisions.",
                "TERC codes of town and rural parts (type 4, 5) count for the urban-rural gmina; Warsaw districts and "
                "city delegations (type 8, 9) count for the city. Codes match today's TERYT on the first six digits.",
                f"{unmapped} decisions have an empty or unknown TERC code and are left out.",
                "The register holds first-instance decisions entered since 2016-01-01, without closed (military) "
                "areas. It has no approval or refusal flag.",
                "Recent weeks may be incomplete: authorities enter decisions with a delay.",
                "Investor and designer names in the CSV are never read into this interim.",
                "Decisions per voivodeship file: " + ", ".join(f"{s} {n}" for s, n in voiv.items()) + ".",
            ],
            "_files": ["dataset-3467.json", *(zip_file(s) for s in SLUGS)],
        }

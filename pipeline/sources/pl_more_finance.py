"""Municipal finance for FY2025 from Ministry of Finance reports and GUS population."""

from __future__ import annotations

import struct
import zipfile
from decimal import Decimal
from typing import BinaryIO

from ..core.source import Source, SourceInfo
from .pl_stats_population import AREA_FILE, AREA_URL, POPULATION_FILE, POPULATION_URL, _area, _best_population_table

HOMEPAGE = "https://www.gov.pl/web/finanse/bazy-danych8"
ATTACHMENT = "https://www.gov.pl/attachment/"
REUSE = "https://www.gov.pl/web/finanse/ponowne-wykorzystywanie"
METHOD_URL = "https://bip-docrepo-api.krakow.rio.gov.pl/api/files/13668"
FILES = {
    "rb27s.zip": ATTACHMENT + "f98752f2-176a-4be1-910f-8aca6ffd9044",
    "rb28s.zip": ATTACHMENT + "1eb59fb5-ab95-4f0d-8d62-4ef07c1a9910",
    "rbz.zip": ATTACHMENT + "7ed5e4aa-50a5-46f7-a32e-337675319a8b",
    "rio-2025-method.pdf": METHOD_URL,
    AREA_FILE: AREA_URL,
    POPULATION_FILE: POPULATION_URL,
}
# RIO Krakow FY2025 methodology, p. 3. Codes use the first three paragraph digits.
TRANSFERS = frozenset("""
    200 201 202 203 204 205 206 207 208 209 210 211 212 213 216 217
    218 221 222 223 231 232 233 238 244 246 253 268 269 270 271 273
    275 276 277 278 287 288 290 292 609 610 620 625 626 628 629 630
    631 632 633 634 635 637 638 639 641 642 643 644 651 652 653 656
    661 662 663 664 665 670 671 672 681 682 683 684
""".split())
REPORTS = {
    "own_income_per_resident": ("rb27s.zip", "Rb27S.dbf"),
    "investment_spending_per_resident": ("rb28s.zip", "Rb28S.dbf"),
    "debt_per_resident": ("rbz.zip", "RbZ.dbf"),
}
UNIT_COLUMNS = ("WK", "PK", "GK", "GT", "PT", "KODMSWIA", "ROK", "KWARTAL", "WERSJA")


def dbf_rows(stream: BinaryIO, columns):
    """Stream the requested ASCII fields of the ministry's dBASE III reports."""
    header = stream.read(32)
    count, header_size, record_size = struct.unpack_from("<IHH", header, 4)
    descriptor = stream.read(header_size - 32)
    if descriptor[-1:] != b"\r" or (len(descriptor) - 1) % 32:
        raise ValueError("Invalid finance DBF field descriptors")
    fields = {}
    offset = 1
    for start in range(0, len(descriptor) - 1, 32):
        field = descriptor[start:start + 32]
        name = field[:11].split(b"\0", 1)[0].decode("ascii")
        end = offset + field[16]
        fields[name] = slice(offset, end)
        offset = end
    if offset != record_size:
        raise ValueError("Invalid finance DBF record size")
    selected = [(name, fields[name]) for name in columns]
    for _ in range(count):
        record = stream.read(record_size)
        if len(record) != record_size:
            raise ValueError("Truncated finance DBF record")
        if record[:1] == b" ":
            yield {name: record[section].strip().decode("ascii") for name, section in selected}


def municipal_code(row):
    """The ministry represents a city with powiat rights as PT 2, with GK/GT zero."""
    if row["KODMSWIA"]:
        return None
    powiat = row["WK"] + row["PK"]
    if row["PT"] == "2":
        return powiat + "011"
    if row["PT"] == "0" and row["GT"] in {"1", "2", "3"}:
        return powiat + row["GK"] + row["GT"]
    return None


def _included(row, report):
    if report == "rb27s.zip":
        return row["PAR"].isdigit() and row["PAR"] not in TRANSFERS
    if report == "rb28s.zip":
        return row["GRUPA"].startswith("16") and row["PAR"] not in {"601", "602", "603"}
    return True


def aggregate_report(rows, report):
    """Sum executed line items from the latest report for each municipal unit."""
    totals = {}
    versions = {}
    for row in rows:
        code = municipal_code(row)
        if code is None or (row["ROK"], row["KWARTAL"]) != ("25", "4"):
            continue
        version = int(row["WERSJA"])
        previous = versions.get(code, -1)
        if version < previous:
            continue
        if version > previous:
            totals[code] = Decimal(0)
            versions[code] = version
        elif report == "rbz.zip":
            raise ValueError(f"Duplicate Rb-Z total for {code}")
        if not _included(row, report):
            continue
        value = row["E"] if report == "rbz.zip" else row["R4"]
        if not value or set(value) == {"*"} or totals[code] is None:
            totals[code] = None
        else:
            totals[code] += Decimal(value)
    return totals


def _read_totals(path, member):
    if path.name == "rbz.zip":
        columns = (*UNIT_COLUMNS, "E")
    elif path.name == "rb28s.zip":
        columns = (*UNIT_COLUMNS, "PAR", "GRUPA", "R4")
    else:
        columns = (*UNIT_COLUMNS, "PAR", "R4")
    with zipfile.ZipFile(path) as archive, archive.open(member) as stream:
        return aggregate_report(dbf_rows(stream, columns), path.name)


def calculate_rates(totals, population, current_codes):
    """Join numerator and denominator on their 2025 code before applying the 2026 type digit."""
    by_prefix = {code[:6]: code for code in current_codes}
    result = {code: dict.fromkeys(totals) for code in sorted(current_codes)}
    unmatched = set()
    recoded = set()
    for field, by_code in totals.items():
        seen = set()
        for old, amount in by_code.items():
            current = by_prefix.get(old[:6])
            if current is None:
                unmatched.add(old)
                continue
            if current in seen:
                raise ValueError(f"Multiple municipal totals for {current} in {field}")
            seen.add(current)
            if current != old:
                recoded.add((old, current))
            denominator = population.get(old)
            if amount is not None and denominator:
                result[current][field] = round(float(amount / Decimal(denominator)), 2)
    return result, unmatched, recoded


class PlMoreFinance(Source):
    info = SourceInfo(
        id="pl_more_finance",
        title="Municipal budgets and debt in 2025",
        publisher="Ministry of Finance (MF); Statistics Poland (GUS); RIO Krakow methodology",
        homepage=HOMEPAGE,
        license="MF public sector reuse terms (attribute source, dates and processing); GUS CC BY 4.0",
        description="Municipal own income, investment spending and debt per resident from the FY2025 reports.",
        used_for=["Local finance by gmina"],
    )

    def fetch(self, force=False):
        for name, url in FILES.items():
            self.download(url, name, force=force, expect_binary=True)

    def process(self):
        current = set(_area(self.raw_dir / AREA_FILE))
        population = _best_population_table(self.raw_dir / POPULATION_FILE)
        totals = {
            field: _read_totals(self.raw_dir / name, member)
            for field, (name, member) in REPORTS.items()
        }
        rows, unmatched, recoded = calculate_rates(totals, population, current)
        notes = [
            "The denominator is the GUS gmina population on 31 December 2025.",
            "Cities with powiat rights include both their municipal and powiat functions.",
            "Executed own income and investment spending follow the RIO Krakow FY2025 classification.",
            "Debt covers municipal debt titles in Rb-Z item E, including overdue liabilities.",
            "Missing reports or population figures stay null.",
            "MF public sector reuse terms: " + REUSE,
        ]
        notes.extend(f"Finance TERYT code change: {old} to {new}." for old, new in sorted(recoded))
        if unmatched:
            notes.append("Unmatched finance TERYT codes: " + ", ".join(sorted(unmatched)))
        fields = {
            key: {"label": label, "unit": "PLN", "year": 2025, "note": note}
            for key, label, note in (
                ("own_income_per_resident", "Own income per resident",
                 "Executed FY2025 own income (Rb-27S R4), divided by end-year population."),
                ("investment_spending_per_resident", "Investment spending per resident",
                 "Executed FY2025 capital spending (Rb-28S R4), except paragraphs 601-603, "
                 "divided by end-year population."),
                ("debt_per_resident", "Debt per resident",
                 "31 December 2025, nominal obligations by debt title (Rb-Z E), divided by end-year population."),
            )
        }
        return {
            "vintage": "FY2025, Q4 Ministry of Finance database; GUS population 31 December 2025",
            "_files": list(FILES),
            "tables": {"local_finance": {"level": "gmina", "fields": fields, "rows": rows}},
            "notes": notes,
        }

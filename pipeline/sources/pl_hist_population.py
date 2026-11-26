"""Population of every gmina for each year 2015 to 2025 (31 December) and on 30 June 2026 (GUS bulk tables).

GUS publishes "Ludnosc. Stan i struktura oraz ruch naturalny w przekroju terytorialnym" twice a year as a ZIP of
workbooks (legacy .xls in most years, .xlsx in some). Each edition has a table of residents by gmina (TERYT7 in
column B, total population in column C). This source reads the table with the most whole-gmina rows from each
edition and keys every year by today's gmina code. Each year is on its own borders: a gmina whose borders changed
shows that change too (Opole 2017, Kamienica and Suprasl 2025); gminas created later are null in earlier years.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from ..core.bdl import is_whole_gmina
from ..core.source import Source, SourceInfo
from ._pl_xlsx import read_xlsx
from .pl_stats_population import read_xls

BASE = "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/6/"
# (reference date, edition path under BASE). Edition pages: stat.gov.pl/obszary-tematyczne/ludnosc/ludnosc/ (archive).
EDITIONS = [
    ("2015-12-31", "19/1/stan_i_struktura_ludnosci_oraz_ruch_naturalny_w_przekroju_terytorialnym_31-12-2015_-_tabele.zip"),
    ("2016-12-31", "21/1/stan_i_struktura_ludno_oraz_ruch_naturalny_w_przekroju_teryt_stan-na-31-12-2016_-_tablice.zip"),
    ("2017-12-31", "23/1/ludnosc_stan_i_struktura_oraz_ruch_naturalny_31122017.zip"),
    ("2018-12-31", "25/1/ludnosc_stan_i_struktura_oraz_ruch_naturalny_w_przekroju_terytorialnym_na_31.12.2018-tablice.zip"),
    ("2019-12-31", "27/1/ludnosc_31.12.2019-tablice.zip"),
    ("2020-12-31", "29/1/ludnosc.stan_i_struktura_31.12.2020.zip"),
    ("2021-12-31", "31/1/ludnosc.stan_i_struktura_31.12.2021.zip"),
    ("2022-12-31", "34/1/ludnosc.stan_i_struktura_31.12.2022.zip"),
    ("2023-12-31", "36/1/ludnosc.stan_i_struktura_31.12.2023.zip"),
    ("2024-12-31", "38/1/ludnosc_stan_i_struktura_oraz_ruch_naturalny_w_przekroju_terytorialnym_na_31-12-2024.zip"),
    ("2025-12-31", "40/1/ludnosc.stan_i_struktura_31.12.2025.zip"),
    ("2026-06-30", "41/1/ludnosc_stan_i_struktura_30.06.2026.zip"),
]
HOMEPAGE = "https://stat.gov.pl/obszary-tematyczne/ludnosc/ludnosc/"
PLAUSIBLE_TOTAL = (36_000_000, 39_000_000)
MONTHS = {"06-30": "30 June", "12-31": "31 December"}


def file_name(date: str) -> str:
    return f"population-{date}.zip"


def field_key(date: str) -> str:
    """'2019-12-31' -> 'pop_2019'; '2026-06-30' -> 'pop_2026_06'."""
    return f"pop_{date[:4]}" if date.endswith("12-31") else f"pop_{date[:4]}_{date[5:7]}"


def _gmina_code(value) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not float(value).is_integer():
            return None
        digits = str(int(value)).zfill(7)
    else:
        digits = "".join(re.findall(r"\d", str(value or "")))
    return digits if len(digits) == 7 and is_whole_gmina(digits) else None


def gmina_rows(sheets: list[list[list]]) -> dict[str, int]:
    """{TERYT7: residents} from the sheets of one workbook: rows with a whole-gmina code in column B and a
    positive count in column C."""
    found: dict[str, int] = {}
    for sheet in sheets:
        for row in sheet:
            if len(row) < 3:
                continue
            code = _gmina_code(row[1])
            v = row[2]
            if code and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                found[code] = int(v)
    return found


def best_table(zip_path: Path) -> tuple[str, dict[str, int]]:
    """(member name, {TERYT7: residents}) of the workbook in the ZIP with the most whole-gmina rows."""
    best: tuple[str, dict[str, int]] = ("", {})
    with zipfile.ZipFile(zip_path) as archive:
        for member in sorted(archive.namelist()):
            low = member.lower()
            if low.endswith(".xls"):
                sheets = read_xls(archive.read(member))
            elif low.endswith(".xlsx"):
                tmp = zip_path.with_name(zip_path.name + ".member.xlsx")
                tmp.write_bytes(archive.read(member))
                try:
                    from ._pl_xlsx import sheet_names

                    sheets = [read_xlsx(tmp, n) for n in sheet_names(tmp)]
                finally:
                    tmp.unlink(missing_ok=True)
            else:
                continue
            found = gmina_rows(sheets)
            # A gmina table covers the whole country: its total is a plausible population of Poland. (Age
            # tables have big numbers in column B that look like codes; they fail this test.)
            if not PLAUSIBLE_TOTAL[0] <= sum(found.values()) <= PLAUSIBLE_TOTAL[1]:
                continue
            if len(found) > len(best[1]):
                best = (member, found)
    if len(best[1]) < 2_000:
        raise RuntimeError(f"{zip_path.name}: found only {len(best[1])} gmina population rows")
    return best


def on_current_codes(year_rows: dict[str, int], current: list[str]) -> dict[str, int | None]:
    """Values keyed by today's codes: exact code, else the only old code with the same first six digits (a gmina
    whose type digit changed, e.g. a rural gmina that became urban-rural). Others are None."""
    by6: dict[str, list[str]] = {}
    for code in year_rows:
        by6.setdefault(code[:6], []).append(code)
    out: dict[str, int | None] = {}
    for code in current:
        if code in year_rows:
            out[code] = year_rows[code]
        else:
            old = by6.get(code[:6]) or []
            out[code] = year_rows[old[0]] if len(old) == 1 else None
    return out


class PolandPopulationHistory(Source):
    info = SourceInfo(
        id="pl_hist_population",
        title="Population by gmina, 2015 to 2026",
        publisher="Statistics Poland (GUS)",
        homepage=HOMEPAGE,
        license="GUS CC BY 4.0",
        description="Residents of every gmina on 31 December of each year 2015 to 2025 and on 30 June 2026, from "
                    "the GUS bulk tables 'Ludnosc. Stan i struktura oraz ruch naturalny w przekroju terytorialnym'.",
        used_for=["Time slider of the density and change lenses"],
    )

    def fetch(self, force: bool = False) -> None:
        for date, path in EDITIONS:
            self.download(BASE + path, file_name(date), force=force, expect_binary=True)

    def process(self) -> dict:
        years: dict[str, dict[str, int]] = {}
        members: dict[str, str] = {}
        for date, _path in EDITIONS:
            members[date], years[date] = best_table(self.raw_dir / file_name(date))
        newest = EDITIONS[-1][0]
        current = sorted(years[newest])
        mapped = {date: on_current_codes(rows, current) for date, rows in years.items()}
        rows = {code: {field_key(d): mapped[d][code] for d, _ in EDITIONS} for code in current}
        fields = {
            field_key(d): {"label": "Population", "unit": "persons", "year": int(d[:4]),
                           "note": f"{MONTHS[d[5:]]} {d[:4]}, GUS bulk table ({members[d]})."}
            for d, _ in EDITIONS
        }
        missing = {d: [c for c in current if mapped[d][c] is None] for d, _ in EDITIONS}
        notes = [
            "From 31 December 2021 GUS counts are based on the 2021 census; earlier years are based on the 2011 "
            "census. Part of the change between 2020 and 2021 comes from that rebasing (for example +69,000 in "
            "Warszawa), not from people moving.",
            "Each year is on that year's borders. A gmina whose borders changed shows the change in its count "
            "(for example Opole in 2017, Kamienica and Suprasl in 2025, Slupsk and Kobylnica on 1 January 2026).",
            "Codes are those of the newest edition; an older code is matched on its first six digits when only "
            "the type digit changed.",
        ]
        for d, codes in missing.items():
            if codes:
                notes.append(f"{d}: no figure for {', '.join(codes)} (gmina created later or code not matched).")
        return {
            "vintage": "GUS population 31 December 2015 to 2025 and 30 June 2026",
            "dates": [d for d, _ in EDITIONS],
            "tables": {"population_years": {"level": "gmina", "fields": fields, "rows": rows}},
            "notes": notes,
            "_files": [file_name(d) for d, _ in EDITIONS],
        }

"""People under temporary protection and people with PESEL UKR status."""

from __future__ import annotations

from ..core.bdl import read_xlsx
from ..core.source import Source, SourceInfo

UKRAINE_ANNUAL_FILE = "ukraine_temporary_protection_2025.xlsx"
UKRAINE_ANNUAL_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5471/20/1/1/"
    "liczba_mieszkancow_ukrainy_31_12_2025.xlsx"
)
UKRAINE_POWIAT_FILE = "ukraine_status_2026-11-11.xlsx"
UKRAINE_POWIAT_URL = "https://api.dane.gov.pl/media/resources/20261116/STATYSTYKI_POWIAT_UKR_20261116.xlsx"
SEPTEMBER_POWIAT_FILE = "ukraine_status_2026-09-08.xlsx"
SEPTEMBER_POWIAT_URL = "https://api.dane.gov.pl/media/resources/20260908/STATYSTYKI_POWIAT_UKR_20260908.xlsx"
LEGACY_POWIAT_FILE = "ukraine_status_2026-02-10.xlsx"
LEGACY_POWIAT_URL = "https://api.dane.gov.pl/media/resources/20260210/STATYSTYKI_POWIAT_UKR_20260210.xlsx"
POWIAT_RELEASES = (
    ("2026-11-11", UKRAINE_POWIAT_URL, UKRAINE_POWIAT_FILE),
    ("2026-09-08", SEPTEMBER_POWIAT_URL, SEPTEMBER_POWIAT_FILE),
    ("2026-02-10", LEGACY_POWIAT_URL, LEGACY_POWIAT_FILE),
)

VOIVODESHIPS = {
    "dolno\u015bl\u0105skie": "02", "kujawsko-pomorskie": "04", "lubelskie": "06", "lubuskie": "08",
    "\u0142\u00f3dzkie": "10", "ma\u0142opolskie": "12", "mazowieckie": "14", "opolskie": "16",
    "podkarpackie": "18", "podlaskie": "20", "pomorskie": "22", "\u015bl\u0105skie": "24",
    "\u015bwi\u0119tokrzyskie": "26", "warmi\u0144sko-mazurskie": "28", "wielkopolskie": "30",
    "zachodniopomorskie": "32",
}


def _field(label, unit, year, note):
    return {"label": label, "unit": unit, "year": year, "note": note}


def parse_powiat_rows(sheet_rows):
    result = {}
    for row in sheet_rows:
        code = str(row[0]).strip() if row else ""
        if len(code) == 4 and code.isdigit():
            result[code] = {
                "pesel_ukr": row[5] if isinstance(row[5], (int, float)) else None,
                "pesel_ukr_men": row[4] if isinstance(row[4], (int, float)) else None,
                "pesel_ukr_women": row[3] if isinstance(row[3], (int, float)) else None,
            }
    return result


def parse_voivodeship_rows(sheet_rows):
    result = {}
    for row in sheet_rows:
        if not row or not isinstance(row[0], str):
            continue
        code = VOIVODESHIPS.get(row[0].strip().lower())
        if code:
            result[code] = {"pesel_ukr": row[1], "pesel_ukr_men": row[2], "pesel_ukr_women": row[3]}
    return result


class PolandForeigners(Source):
    info = SourceInfo(
        id="pl_foreigners",
        title="Temporary protection and PESEL UKR status",
        publisher="Statistics Poland (GUS) and dane.gov.pl",
        homepage="https://stat.gov.pl/obszary-tematyczne/ludnosc/migracje-zagraniczne-ludnosci/",
        license="GUS CC BY 4.0; dane.gov.pl CC0 1.0",
        description="Ukrainian residents under temporary protection and people with PESEL UKR status.",
        used_for=["People advisor", "Foreigners lens"],
    )

    def fetch(self, force=False):
        self.download(UKRAINE_ANNUAL_URL, UKRAINE_ANNUAL_FILE, force=force, expect_binary=True)
        if self.offline:
            for _date, url, filename in POWIAT_RELEASES:
                if (self.raw_dir / filename).exists():
                    self.download(url, filename, expect_binary=True)
                    return
            raise FileNotFoundError(f"{self.id}: no PESEL UKR powiat workbook is cached")
        self.download(UKRAINE_POWIAT_URL, UKRAINE_POWIAT_FILE, force=force, expect_binary=True)

    def process(self):
        powiat_release = next(
            ((date, filename) for date, _url, filename in POWIAT_RELEASES if (self.raw_dir / filename).exists()),
            None,
        )
        if powiat_release is None:
            raise FileNotFoundError(f"{self.id}: no PESEL UKR powiat workbook is cached")
        powiat_date, powiat_file = powiat_release
        powiat_rows = parse_powiat_rows(read_xlsx(self.raw_dir / powiat_file))
        if len(powiat_rows) != 380:
            raise RuntimeError(f"expected 380 powiats in {powiat_file}, got {len(powiat_rows)}")

        voiv_rows = parse_voivodeship_rows(read_xlsx(self.raw_dir / UKRAINE_ANNUAL_FILE))
        if len(voiv_rows) != 16:
            raise RuntimeError(f"expected 16 voivodeships in {UKRAINE_ANNUAL_FILE}, got {len(voiv_rows)}")

        powiat_note = (
            "dane.gov.pl dataset 2715. The place is the powiat of the registering authority, "
            "not necessarily the person's current residence. Values below 2 are suppressed and remain null."
        )
        annual_note = "GUS PESEL register, residents with active UKR status on 31 December 2025."
        return {
            "vintage": f"PESEL UKR {powiat_date}; GUS resident stock 2025-12-31",
            "tables": {
                "pesel_ukr_powiat": {
                    "level": "powiat",
                    "fields": {
                        "pesel_ukr": _field("People with PESEL UKR status", "persons", 2026, powiat_note),
                        "pesel_ukr_men": _field("Men with PESEL UKR status", "persons", 2026, powiat_note),
                        "pesel_ukr_women": _field("Women with PESEL UKR status", "persons", 2026, powiat_note),
                    },
                    "rows": powiat_rows,
                },
                "pesel_ukr_voivodeship": {
                    "level": "voivodeship",
                    "fields": {
                        "pesel_ukr": _field("Ukrainian residents under temporary protection", "persons", 2025, annual_note),
                        "pesel_ukr_men": _field("Men under temporary protection", "persons", 2025, annual_note),
                        "pesel_ukr_women": _field("Women under temporary protection", "persons", 2025, annual_note),
                    },
                    "rows": voiv_rows,
                },
            },
            "notes": [
                "The detailed dane.gov.pl file is available at powiat level, not gmina level.",
                *(
                    ["A newer 11 November 2026 powiat file is known but is not present in this cache."]
                    if powiat_date != "2026-11-11" else []
                ),
                "The ZUS August 2026 voivodeship workbook is published but its server rejects automated downloads.",
            ],
            "_files": [powiat_file, UKRAINE_ANNUAL_FILE],
        }

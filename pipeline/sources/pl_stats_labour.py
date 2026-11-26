"""GUS bulk labour statistics for Polish local government units."""

from __future__ import annotations

import os
import ssl
import tempfile
from contextlib import contextmanager
from pathlib import Path

from pipeline.core.bdl import read_xlsx
from pipeline.core.source import Source, SourceInfo


UNEMPLOYMENT_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5473/2/171/1/liczba_bezrobotnych_i_stopa_bezrobocia_pow_10_2026.xlsx"
)
EMPLOYMENT_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5474/27/37/1/pracujacy_w_gospodarce_narodowej_w_polsce_w_grudniu_2025_tab.xlsx"
)
WAGES_URL = (
    "https://publikacje.new.stat.gov.pl/sites/default/files/2026-11/"
    "Rozk%C5%82ad%20wynagrodze%C5%84%20w%20gospodarce%20narodowej%20w%20maju%202026%20r%20Tablice.xlsx"
)

UNEMPLOYMENT_FILE = "unemployment-2026-10.xlsx"
EMPLOYMENT_FILE = "employment-2025-12.xlsx"
WAGES_FILE = "wages-2026-05.xlsx"

# GUS currently omits this intermediate from its TLS chain. The certificate is
# fetched from its issuer and is still verified against the system trust roots.
CERTUM_INTERMEDIATE_URL = (
    "https://repository.certum.pl/certumovtlsg2r39ca.cer"
)
CERTUM_INTERMEDIATE_FILE = "certumovtlsg2r39ca.cer"
CERTUM_CROSS_URL = "https://repository.certum.pl/ctnca-ctrca.pem"
CERTUM_CROSS_FILE = "ctnca-ctrca.pem"

PKD_SECTIONS = tuple("ABCDEFGHIJKLMNOPQRS")


def _number(value: object) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _code_part(value: object) -> str | None:
    if isinstance(value, int):
        return f"{value:02d}"
    if isinstance(value, str) and value.strip().isdigit():
        return value.strip().zfill(2)
    return None


def _powiat_code(row: list[object | None], woj_col: int, pow_col: int) -> str | None:
    woj = _code_part(row[woj_col]) if len(row) > woj_col else None
    powiat = _code_part(row[pow_col]) if len(row) > pow_col else None
    if woj is None or powiat is None or woj == "00" or powiat == "00":
        return None
    return woj + powiat


def _gmina_code(row: list[object | None]) -> str | None:
    if len(row) < 13:
        return None
    woj = _code_part(row[2])
    powiat = _code_part(row[5])
    gmina = _code_part(row[6])
    kind = str(row[7]).strip() if row[7] is not None else ""
    if woj is None or powiat is None or gmina is None or kind not in {"1", "2", "3"}:
        return None
    return woj + powiat + gmina + kind


def _field(label: str, unit: str, year: int, note: str) -> dict:
    return {"label": label, "unit": unit, "year": year, "note": note}


def _fill_rows(table: dict) -> None:
    names = tuple(table["fields"])
    for row in table["rows"].values():
        for name in names:
            row.setdefault(name, None)


def parse_unemployment(rows: list[list[object | None]]) -> tuple[dict[str, dict], dict]:
    """Return October 2026 powiat observations and the country headline."""
    powiats: dict[str, dict] = {}
    headline = {"registered_unemployed": None, "registered_unemployment_rate": None}
    for row in rows:
        if len(row) < 5:
            continue
        code = _powiat_code(row, 0, 1)
        count_thousands = _number(row[3])
        rate = _number(row[4])
        if code is not None:
            powiats[code] = {
                "registered_unemployed": (
                    round(count_thousands * 1000) if count_thousands is not None else None
                ),
                "registered_unemployment_rate": rate,
            }
        elif _code_part(row[0]) == "00" and _code_part(row[1]) == "00":
            headline = {
                "registered_unemployed": (
                    round(count_thousands * 1000) if count_thousands is not None else None
                ),
                "registered_unemployment_rate": rate,
            }
    return powiats, headline


def parse_wages(rows: list[list[object | None]]) -> tuple[dict[str, dict], dict]:
    """Return May 2026 average wages by employer seat."""
    powiats: dict[str, dict] = {}
    headline = {
        "average_gross_monthly_wage": None,
        "median_gross_monthly_wage": None,
    }
    for row in rows:
        if len(row) < 8:
            continue
        code = _powiat_code(row, 2, 5)
        if code is not None:
            powiats.setdefault(code, {})["average_gross_monthly_wage"] = _number(row[7])
        elif all(row[index] is None for index in range(6)) and _number(row[7]) is not None:
            headline["average_gross_monthly_wage"] = _number(row[7])
    return powiats, headline


def parse_median_wages(rows: list[list[object | None]], powiats: dict[str, dict], headline: dict) -> None:
    for row in rows:
        if len(row) < 8:
            continue
        code = _powiat_code(row, 2, 5)
        if code is not None:
            powiats.setdefault(code, {})["median_gross_monthly_wage"] = _number(row[7])
        elif all(row[index] is None for index in range(6)) and _number(row[7]) is not None:
            headline["median_gross_monthly_wage"] = _number(row[7])


def parse_pkd_powiat(rows: list[list[object | None]]) -> dict[str, dict]:
    """Return workers by PKD 2007 section and employer-seat powiat."""
    result: dict[str, dict] = {}
    for row in rows:
        code = _powiat_code(row, 2, 5) if len(row) > 5 else None
        if code is None:
            continue
        values = {"workers_total": _number(row[7]) if len(row) > 7 else None}
        for index, section in enumerate(PKD_SECTIONS):
            column = 9 + index * 2
            values[f"workers_{section}"] = _number(row[column]) if len(row) > column else None
        result[code] = values
    return result


def parse_sectors_gmina(rows: list[list[object | None]]) -> dict[str, dict]:
    """Return the three published broad sectors by residence gmina."""
    result: dict[str, dict] = {}
    for row in rows:
        code = _gmina_code(row)
        if code is None:
            continue
        result[code] = {
            "workers_total": _number(row[9]),
            "workers_agriculture": _number(row[10]),
            "workers_industry": _number(row[11]),
            "workers_services": _number(row[12]),
        }
    return result


def build_tables(raw_dir: Path) -> tuple[dict, list[str]]:
    unemployment_rows = read_xlsx(raw_dir / UNEMPLOYMENT_FILE, 1)
    wage_rows = read_xlsx(raw_dir / WAGES_FILE, "Tabl. 12.A")
    median_rows = read_xlsx(raw_dir / WAGES_FILE, "Tabl. 12.B")
    employment_powiat_rows = read_xlsx(raw_dir / EMPLOYMENT_FILE, "Tabl. 27")
    employment_gmina_rows = read_xlsx(raw_dir / EMPLOYMENT_FILE, "Tabl. 3")

    labour_rows, unemployment_headline = parse_unemployment(unemployment_rows)
    wage_values, wage_headline = parse_wages(wage_rows)
    parse_median_wages(median_rows, wage_values, wage_headline)
    for code, values in wage_values.items():
        labour_rows.setdefault(code, {}).update(values)

    labour_fields = {
        "registered_unemployed": _field(
            "Registered unemployed", "people", 2026,
            "GUS monthly release, end of October 2026; source values are published in thousands.",
        ),
        "registered_unemployment_rate": _field(
            "Registered unemployment rate", "%", 2026,
            "GUS monthly release, end of October 2026.",
        ),
        "average_gross_monthly_wage": _field(
            "Average gross monthly wage", "PLN/month", 2026,
            "GUS wage distribution, May 2026, by employer seat.",
        ),
        "median_gross_monthly_wage": _field(
            "Median gross monthly wage", "PLN/month", 2026,
            "GUS wage distribution, May 2026, by employer seat.",
        ),
    }
    pkd_fields = {
        "workers_total": _field(
            "People working, total", "people", 2025,
            "GUS, 31 December 2025, by employer seat.",
        )
    }
    for section in PKD_SECTIONS:
        pkd_fields[f"workers_{section}"] = _field(
            f"People working, PKD 2007 section {section}", "people", 2025,
            "GUS, 31 December 2025, by employer seat; suppressed values remain null.",
        )
    sector_fields = {
        "workers_total": _field(
            "People working, total", "people", 2025,
            "GUS, 31 December 2025, by place of residence.",
        ),
        "workers_agriculture": _field(
            "People working in agriculture", "people", 2025,
            "GUS agricultural sector, 31 December 2025, by place of residence.",
        ),
        "workers_industry": _field(
            "People working in industry", "people", 2025,
            "GUS industrial sector, 31 December 2025, by place of residence.",
        ),
        "workers_services": _field(
            "People working in services", "people", 2025,
            "GUS service sector, 31 December 2025, by place of residence.",
        ),
    }
    headline = {**unemployment_headline, **wage_headline}
    tables = {
        "labour_powiat": {"level": "powiat", "fields": labour_fields, "rows": labour_rows},
        "employment_pkd_powiat": {
            "level": "powiat", "fields": pkd_fields, "rows": parse_pkd_powiat(employment_powiat_rows),
        },
        "employment_sectors_gmina": {
            "level": "gmina", "fields": sector_fields, "rows": parse_sectors_gmina(employment_gmina_rows),
        },
        "national_headlines": {
            "level": "country", "fields": labour_fields, "rows": {"PL": headline},
        },
    }
    for table in tables.values():
        _fill_rows(table)
    return tables, [UNEMPLOYMENT_FILE, EMPLOYMENT_FILE, WAGES_FILE]


@contextmanager
def _gus_trust_chain(intermediate_path: Path, cross_path: Path | None = None):
    """Add the publisher's missing intermediate without disabling TLS checks."""
    default_ca = ssl.get_default_verify_paths().cafile
    if not default_ca:
        raise RuntimeError("system TLS trust bundle is unavailable")
    certificate = intermediate_path.read_bytes()
    if certificate.startswith(b"-----BEGIN CERTIFICATE-----"):
        intermediate_pem = certificate.decode("ascii")
    else:
        intermediate_pem = ssl.DER_cert_to_PEM_cert(certificate)
    previous = os.environ.get("SSL_CERT_FILE")
    with tempfile.NamedTemporaryFile("w", encoding="ascii") as bundle:
        bundle.write(Path(default_ca).read_text(encoding="ascii"))
        bundle.write("\n")
        bundle.write(intermediate_pem)
        if cross_path is not None:
            bundle.write("\n")
            bundle.write(cross_path.read_text(encoding="ascii"))
        bundle.flush()
        ssl.create_default_context(cafile=bundle.name)
        os.environ["SSL_CERT_FILE"] = bundle.name
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = previous


class PlStatsLabourSource(Source):
    info = SourceInfo(
        id="pl_stats_labour",
        title="GUS labour publication tables",
        publisher="Statistics Poland (GUS)",
        homepage="https://stat.gov.pl/obszary-tematyczne/rynek-pracy/",
        description="Registered unemployment, wages, and employment by sector.",
        license="CC BY 4.0",
        used_for=["Yields", "City View", "Advisors", "Lenses"],
    )

    def fetch(self, force: bool = False) -> None:
        intermediate = self.download(
            CERTUM_INTERMEDIATE_URL, CERTUM_INTERMEDIATE_FILE,
            force=force, expect_binary=True,
        )
        cross = self.download(
            CERTUM_CROSS_URL, CERTUM_CROSS_FILE,
            force=force, expect_binary=True,
        )
        with _gus_trust_chain(intermediate, cross):
            self.download(UNEMPLOYMENT_URL, UNEMPLOYMENT_FILE, force=force, expect_binary=True)
            self.download(EMPLOYMENT_URL, EMPLOYMENT_FILE, force=force, expect_binary=True)
            self.download(WAGES_URL, WAGES_FILE, force=force, expect_binary=True)

    def process(self) -> dict:
        tables, files = build_tables(self.raw_dir)
        return {
            "vintage": "GUS, October 2026, May 2026, and December 2025",
            "tables": tables,
            "notes": [
                "Monthly unemployment supplies both count and rate at powiat level.",
                "Employment supplies PKD 2007 sections A-S at powiat level by employer seat.",
                "The bulk employment workbook publishes three broad sectors at gmina level.",
                "Suppressed and unavailable workbook values remain null.",
                "Working-age population is supplied by the population statistics source.",
            ],
            "_files": files,
        }

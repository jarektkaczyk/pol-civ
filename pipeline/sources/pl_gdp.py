"""Eurostat regional accounts for Polish GDP and GVA.

The two regional files are small bulk TSV downloads. The national query is a
bounded JSON-stat request for Poland and GDP only. An ECB annual exchange rate
converts the national euro value to US dollars.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
from collections import defaultdict

from ..core.source import Source, SourceInfo

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination"
REGIONAL_FILES = {
    "nuts2_gdp.tsv.gz": f"{EUROSTAT}/sdmx/2.1/data/nama_10r_2gdp?format=TSV&compressed=true",
    "nuts3_gdp.tsv.gz": f"{EUROSTAT}/sdmx/2.1/data/nama_10r_3gdp?format=TSV&compressed=true",
    "nuts3_gva.tsv.gz": f"{EUROSTAT}/sdmx/2.1/data/nama_10r_3gva?format=TSV&compressed=true",
}
NATIONAL_FILE = "national_gdp.json"
NATIONAL_URL = (
    f"{EUROSTAT}/statistics/1.0/data/nama_10_gdp"
    "?lang=en&geo=PL&na_item=B1GQ&sinceTimePeriod=2024"
)
NATIONAL_PC_FILE = "national_gdp_per_capita.json"
NATIONAL_PC_URL = (
    f"{EUROSTAT}/statistics/1.0/data/nama_10_pc"
    "?lang=en&geo=PL&na_item=B1GQ&sinceTimePeriod=2024"
)
ECB_FILE = "ecb_usd_eur_2025.csv"
ECB_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/A.USD.EUR.SP00.A"
    "?startPeriod=2025&endPeriod=2025&format=csvdata"
)

# NUTS 2024 level 2 regions. Mazowieckie is split into PL91 and PL92.
NUTS2_TERYT = {
    "PL21": "12", "PL22": "24", "PL41": "30", "PL42": "32", "PL43": "08",
    "PL51": "02", "PL52": "16", "PL61": "04", "PL62": "28", "PL63": "22",
    "PL71": "10", "PL72": "26", "PL81": "06", "PL82": "18", "PL84": "20",
    "PL91": "14", "PL92": "14",
}


def _number(cell: str) -> float | None:
    """Return a Eurostat TSV value, ignoring observation flags."""
    raw = cell.strip()
    if not raw or raw.startswith(":"):
        return None
    match = re.match(r"[-+]?\d+(?:\.\d+)?", raw.replace(",", "."))
    return float(match.group()) if match else None


def read_eurostat_tsv(path):
    """Yield (dimensions, year, value) from a compressed Eurostat TSV file."""
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        dimensions = header[0].split("\\")[0].split(",")
        years = [h.strip() for h in header[1:]]
        for row in reader:
            if not row:
                continue
            keys = row[0].split(",")
            if len(keys) != len(dimensions):
                continue
            dims = dict(zip(dimensions, keys))
            for year, cell in zip(years, row[1:]):
                value = _number(cell)
                if value is not None and year.isdigit():
                    yield dims, int(year), value


def jsonstat_rows(payload: dict):
    """Yield dimension dictionaries and values from a JSON-stat 2 response."""
    dim_ids = payload["id"]
    sizes = payload["size"]
    codes = []
    for dim in dim_ids:
        index = payload["dimension"][dim]["category"]["index"]
        if isinstance(index, list):
            codes.append(index)
        else:
            codes.append([k for k, _ in sorted(index.items(), key=lambda item: item[1])])
    values = payload.get("value", {})
    total = 1
    for size in sizes:
        total *= size
    for flat in range(total):
        value = values.get(str(flat)) if isinstance(values, dict) else values[flat]
        if value is None:
            continue
        rest = flat
        positions = [0] * len(sizes)
        for i in range(len(sizes) - 1, -1, -1):
            positions[i] = rest % sizes[i]
            rest //= sizes[i]
        yield {dim: codes[i][positions[i]] for i, dim in enumerate(dim_ids)}, float(value)


def _field(label, unit, year, note):
    return {"label": label, "unit": unit, "year": year, "note": note}


class PolandGdp(Source):
    info = SourceInfo(
        id="pl_gdp",
        title="Polish national and regional accounts",
        publisher="Eurostat and European Central Bank",
        homepage="https://ec.europa.eu/eurostat/web/national-accounts/data/database",
        license="Eurostat reuse policy; ECB data may be reused with attribution",
        description="GDP for Polish voivodeships and NUTS 3 regions, regional GVA by NACE, and national GDP.",
        used_for=["Gold yield", "Economy advisor", "National headline GDP"],
    )

    def fetch(self, force=False):
        for filename, url in REGIONAL_FILES.items():
            self.download(url, filename, force=force, expect_binary=True)
        self.download(NATIONAL_URL, NATIONAL_FILE, force=force)
        self.download(NATIONAL_PC_URL, NATIONAL_PC_FILE, force=force)
        self.download(ECB_URL, ECB_FILE, force=force)

    def process(self):
        nuts2_series = defaultdict(lambda: defaultdict(list))
        for dims, year, value in read_eurostat_tsv(self.raw_dir / "nuts2_gdp.tsv.gz"):
            geo = dims.get("geo", "")
            if geo in NUTS2_TERYT and dims.get("unit") in {"MIO_EUR", "EUR_HAB", "MIO_NAC"}:
                nuts2_series[geo][dims["unit"]].append((year, value))

        nuts2_year = max(
            year for by_unit in nuts2_series.values() for rows in by_unit.values() for year, _ in rows
        )
        voiv_parts = defaultdict(list)
        for nuts, by_unit in nuts2_series.items():
            values = {unit: dict(rows).get(nuts2_year) for unit, rows in by_unit.items()}
            if values.get("MIO_EUR") is not None:
                voiv_parts[NUTS2_TERYT[nuts]].append(values)
        voiv_rows = {}
        for code, parts in voiv_parts.items():
            eur_m = sum(part["MIO_EUR"] for part in parts)
            populations = [part["MIO_EUR"] * 1_000_000 / part["EUR_HAB"] for part in parts
                           if part.get("EUR_HAB")]
            row = {
                "gdp_eur": eur_m * 1_000_000,
                "gdp_per_person_eur": eur_m * 1_000_000 / sum(populations) if populations else None,
            }
            if all(part.get("MIO_NAC") is not None for part in parts):
                row["gdp_pln"] = sum(part["MIO_NAC"] for part in parts) * 1_000_000
            else:
                row["gdp_pln"] = None
            voiv_rows[code] = row

        nuts3_series = defaultdict(lambda: defaultdict(list))
        for dims, year, value in read_eurostat_tsv(self.raw_dir / "nuts3_gdp.tsv.gz"):
            geo = dims.get("geo", "")
            if geo.startswith("PL") and len(geo) == 5 and dims.get("unit") in {"MIO_EUR", "EUR_HAB", "MIO_NAC"}:
                nuts3_series[geo][dims["unit"]].append((year, value))
        nuts3_year = max(year for units in nuts3_series.values() for rows in units.values() for year, _ in rows)
        nuts3_rows = {}
        for geo, units in nuts3_series.items():
            eur = dict(units.get("MIO_EUR", [])).get(nuts3_year)
            per = dict(units.get("EUR_HAB", [])).get(nuts3_year)
            nac = dict(units.get("MIO_NAC", [])).get(nuts3_year)
            nuts3_rows[geo] = {
                "gdp_eur": eur * 1_000_000 if eur is not None else None,
                "gdp_pln": nac * 1_000_000 if nac is not None else None,
                "gdp_per_person_eur": per,
            }

        gva_series = defaultdict(lambda: defaultdict(list))
        for dims, year, value in read_eurostat_tsv(self.raw_dir / "nuts3_gva.tsv.gz"):
            geo = dims.get("geo", "")
            if geo.startswith("PL") and len(geo) == 5 and dims.get("unit") == "CP_MEUR":
                gva_series[geo][dims.get("nace_r2", "TOTAL")].append((year, value))
        gva_year = max(year for sections in gva_series.values() for rows in sections.values() for year, _ in rows)
        section_codes = sorted({section for sections in gva_series.values() for section in sections if section != "TOTAL"})
        gva_rows = {}
        for geo, sections in gva_series.items():
            gva_rows[geo] = {
                f"gva_{section.lower().replace('-', '_')}_eur":
                    (dict(rows).get(gva_year) * 1_000_000 if dict(rows).get(gva_year) is not None else None)
                for section, rows in sections.items() if section != "TOTAL"
            }
        gva_voiv_rows = defaultdict(dict)
        for geo, row in gva_rows.items():
            code = NUTS2_TERYT.get(geo[:4])
            if not code:
                continue
            for field, value in row.items():
                if value is not None:
                    gva_voiv_rows[code][field] = gva_voiv_rows[code].get(field, 0) + value

        national_payload = json.loads((self.raw_dir / NATIONAL_FILE).read_text(encoding="utf-8"))
        national = defaultdict(list)
        for dims, value in jsonstat_rows(national_payload):
            if dims.get("geo") == "PL" and dims.get("na_item") == "B1GQ" and dims.get("time", "").isdigit():
                national[dims.get("unit")].append((int(dims["time"]), value))
        national_year = max(year for rows in national.values() for year, _ in rows)
        national_values = {unit: dict(rows).get(national_year) for unit, rows in national.items()}
        pln_m = national_values.get("CP_MNAC")
        eur_m = national_values.get("CP_MEUR")
        per_capita_payload = json.loads((self.raw_dir / NATIONAL_PC_FILE).read_text(encoding="utf-8"))
        per_capita = defaultdict(list)
        for dims, value in jsonstat_rows(per_capita_payload):
            if dims.get("geo") == "PL" and dims.get("na_item") == "B1GQ" and dims.get("time", "").isdigit():
                per_capita[dims.get("unit")].append((int(dims["time"]), value))
        per_values = {unit: dict(rows).get(national_year) for unit, rows in per_capita.items()}
        per_pln = per_values.get("CP_NAC_HAB")
        per_eur = per_values.get("CP_EUR_HAB") or per_values.get("EUR_HAB")

        with open(self.raw_dir / ECB_FILE, newline="", encoding="utf-8-sig") as f:
            rate_rows = list(csv.DictReader(f))
        rate = float(rate_rows[-1]["OBS_VALUE"])
        national_row = {
            "gdp_pln": pln_m * 1_000_000 if pln_m is not None else None,
            "gdp_eur": eur_m * 1_000_000 if eur_m is not None else None,
            "gdp_usd": eur_m * 1_000_000 * rate if eur_m is not None else None,
            "gdp_per_person_pln": per_pln,
            "gdp_per_person_eur": per_eur,
        }

        regional_note = "Eurostat dataset variable ids: nama_10r_2gdp and nama_10r_3gdp."
        gva_note = "Eurostat dataset variable id: nama_10r_3gva; NACE Rev. 2 A*6 breakdown."
        return {
            "vintage": (
                f"Eurostat national {national_year}; voivodeship GDP {nuts2_year}; "
                f"NUTS3 GDP {nuts3_year}; GVA {gva_year}"
            ),
            "tables": {
                "gdp_voivodeship": {
                    "level": "voivodeship",
                    "fields": {
                        "gdp_pln": _field("GDP", "PLN", nuts2_year, regional_note),
                        "gdp_eur": _field("GDP", "EUR", nuts2_year, regional_note),
                        "gdp_per_person_eur": _field("GDP per person", "EUR per person", nuts2_year, regional_note),
                    },
                    "rows": voiv_rows,
                },
                "gdp_nuts3": {
                    "level": "nuts3",
                    "fields": {
                        "gdp_pln": _field("GDP", "PLN", nuts3_year, regional_note),
                        "gdp_eur": _field("GDP", "EUR", nuts3_year, regional_note),
                        "gdp_per_person_eur": _field("GDP per person", "EUR per person", nuts3_year, regional_note),
                    },
                    "rows": nuts3_rows,
                },
                "gva_nuts3": {
                    "level": "nuts3",
                    "fields": {
                        f"gva_{section.lower().replace('-', '_')}_eur":
                            _field(f"GVA, NACE {section}", "EUR", gva_year, gva_note)
                        for section in section_codes
                    },
                    "rows": gva_rows,
                },
                "gva_voivodeship": {
                    "level": "voivodeship",
                    "fields": {
                        f"gva_{section.lower().replace('-', '_')}_eur":
                            _field(f"GVA, NACE {section}", "EUR", gva_year, gva_note)
                        for section in section_codes
                    },
                    "rows": dict(gva_voiv_rows),
                },
                "gdp_country": {
                    "level": "country",
                    "fields": {
                        "gdp_pln": _field("GDP", "PLN", national_year, "Eurostat nama_10_gdp, B1GQ, current prices."),
                        "gdp_eur": _field("GDP", "EUR", national_year, "Eurostat nama_10_gdp, B1GQ, current prices."),
                        "gdp_usd": _field("GDP", "USD", national_year, "Converted from EUR with ECB annual USD per EUR rate."),
                        "gdp_per_person_pln": _field("GDP per person", "PLN per person", national_year, "Eurostat nama_10_gdp."),
                        "gdp_per_person_eur": _field("GDP per person", "EUR per person", national_year, "Eurostat nama_10_gdp."),
                    },
                    "rows": {"PL": national_row},
                },
            },
            "notes": [
                "Mazowieckie combines NUTS 2 regions PL91 and PL92; per-person GDP uses their implied populations.",
                f"National USD conversion uses the ECB {rate:g} USD per EUR annual average for 2025.",
            ],
            "_files": list(REGIONAL_FILES) + [NATIONAL_FILE, NATIONAL_PC_FILE, ECB_FILE],
        }

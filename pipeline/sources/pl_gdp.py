"""Polish GDP and GVA: GUS regional accounts for voivodeships, Eurostat for NUTS 3 and GVA.

The voivodeship GDP in zloty comes from the GUS regional accounts for 2024 (revision of
30 September 2026), which are newer than the Eurostat NUTS 2 values of the same year.
The Eurostat regional files are small bulk TSV downloads. The national query is a
bounded JSON-stat request for Poland and GDP only. An ECB annual exchange rate
converts the national euro value to US dollars.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
from collections import defaultdict

from ..core.bdl import read_xlsx
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

GUS_REGIONAL_PAGE = (
    "https://stat.gov.pl/obszary-tematyczne/rachunki-narodowe/rachunki-regionalne/"
    "produkt-krajowy-brutto-i-wartosc-dodana-brutto-w-przekroju-regionow-w-2024-r-,7,9.html"
)
GUS_REGIONAL_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5482/7/9/1/"
    "produkt_krajowy_brutto_i_wartosc_dodana_brutto_w_przekroju_regionow_w_2024_r._tablice.xlsx"
)
GUS_REGIONAL_FILE = "gus_regional_gdp_2024.xlsx"
GUS_REGIONAL_YEAR = 2024
GUS_REGIONAL_RELEASE = "30 September 2026"
# GUS region names (ASCII-folded) to voivodeship TERYT. Mazowieckie is published as two NUTS 2 regions.
GUS_REGION_TERYT = {
    "dolnoslaskie": "02", "kujawsko-pomorskie": "04", "lubelskie": "06", "lubuskie": "08", "lodzkie": "10",
    "malopolskie": "12", "mazowiecki regionalny": "14", "warszawski stoleczny": "14", "opolskie": "16",
    "podkarpackie": "18", "podlaskie": "20", "pomorskie": "22", "slaskie": "24", "swietokrzyskie": "26",
    "warminsko-mazurskie": "28", "wielkopolskie": "30", "zachodniopomorskie": "32",
}

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


def _fold(text) -> str:
    letters = "\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c"
    folded = str(text or "").lower().translate(str.maketrans(letters, "acelnoszz"))
    return " ".join(re.sub(r"\s*-\s*", "-", folded).split())


def gus_regional_gdp(rows: list[list]) -> tuple[dict[str, dict], float | None]:
    """{voivodeship TERYT: {gdp_pln, population}} and the Poland total in PLN from GUS Tabl. 1.

    Columns: region, GDP in million PLN, share, index, GDP per capita in PLN. The implied population
    (GDP / GDP per capita) weights the two Mazowieckie regions when their per-capita values are combined.
    """
    out: dict[str, dict] = {}
    poland = None
    for row in rows:
        if len(row) < 5 or not isinstance(row[1], (int, float)):
            continue
        name = _fold(row[0])
        if name.replace(" ", "").startswith("polskapoland"):
            poland = float(row[1]) * 1_000_000
            continue
        code = GUS_REGION_TERYT.get(name)
        if not code:
            continue
        gdp = float(row[1]) * 1_000_000
        per = row[4] if isinstance(row[4], (int, float)) and row[4] else None
        rec = out.setdefault(code, {"gdp_pln": 0.0, "population": 0.0, "parts": 0})
        rec["gdp_pln"] += gdp
        rec["population"] = (rec["population"] + gdp / per) if per and rec["population"] is not None else None
        rec["parts"] += 1
    return out, poland


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
        publisher="Statistics Poland (GUS), Eurostat and European Central Bank",
        homepage="https://ec.europa.eu/eurostat/web/national-accounts/data/database",
        license="Eurostat reuse policy; ECB data may be reused with attribution",
        description="GDP for Polish voivodeships (GUS regional accounts) and NUTS 3 regions (Eurostat), regional "
        "GVA by NACE, and national GDP.",
        used_for=["Gold yield", "Economy advisor", "National headline GDP"],
    )

    def fetch(self, force=False):
        for filename, url in REGIONAL_FILES.items():
            self.download(url, filename, force=force, expect_binary=True)
        self.download(NATIONAL_URL, NATIONAL_FILE, force=force)
        self.download(NATIONAL_PC_URL, NATIONAL_PC_FILE, force=force)
        self.download(ECB_URL, ECB_FILE, force=force)
        self.download(GUS_REGIONAL_URL, GUS_REGIONAL_FILE, force=force, expect_binary=True)

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

        gus_rows, gus_poland = gus_regional_gdp(read_xlsx(self.raw_dir / GUS_REGIONAL_FILE, "Tabl. 1."))
        if len(gus_rows) != 16:
            raise RuntimeError(f"GUS regional GDP: found {len(gus_rows)} voivodeships, expected 16")
        eurostat_pln = {code: row.get("gdp_pln") for code, row in voiv_rows.items()}
        for code, rec in gus_rows.items():
            row = voiv_rows.setdefault(code, {"gdp_eur": None, "gdp_per_person_eur": None})
            row["gdp_pln"] = rec["gdp_pln"]
            row["gdp_per_person_pln"] = round(rec["gdp_pln"] / rec["population"]) if rec["population"] else None
            row["gdp_pln_eurostat"] = eurostat_pln.get(code)
        voiv_year = GUS_REGIONAL_YEAR

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
        gus_note = (
            f"GUS regional accounts {GUS_REGIONAL_YEAR}, Tabl. 1, revision of {GUS_REGIONAL_RELEASE} "
            f"({GUS_REGIONAL_PAGE}). Mazowieckie is the sum of Warszawski stoleczny and Mazowiecki regionalny."
        )
        gva_note = "Eurostat dataset variable id: nama_10r_3gva; NACE Rev. 2 A*6 breakdown."
        return {
            "vintage": (
                f"Eurostat national {national_year}; voivodeship GDP {voiv_year} (GUS, revision of "
                f"{GUS_REGIONAL_RELEASE}); "
                f"NUTS3 GDP {nuts3_year}; GVA {gva_year}"
            ),
            "tables": {
                "gdp_voivodeship": {
                    "level": "voivodeship",
                    "fields": {
                        "gdp_pln": _field("GDP", "PLN", voiv_year, gus_note),
                        "gdp_per_person_pln": _field("GDP per person", "PLN per person", voiv_year, gus_note),
                        "gdp_pln_eurostat": _field(
                            "GDP, Eurostat", "PLN", nuts2_year, regional_note + " Earlier vintage, kept for comparison."
                        ),
                        "gdp_eur": _field("GDP", "EUR", nuts2_year, regional_note + " Earlier vintage than gdp_pln."),
                        "gdp_per_person_eur": _field(
                            "GDP per person", "EUR per person", nuts2_year, regional_note + " Earlier vintage than gdp_pln."
                        ),
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
                f"Voivodeship gdp_pln is GUS {GUS_REGIONAL_YEAR} (revision of {GUS_REGIONAL_RELEASE}); GUS total for "
                f"Poland {GUS_REGIONAL_YEAR}: {gus_poland:,.0f} PLN. NUTS 3 GDP and GVA stay on Eurostat.",
                f"National USD conversion uses the ECB {rate:g} USD per EUR annual average for 2025.",
            ],
            "_files": [GUS_REGIONAL_FILE] + list(REGIONAL_FILES) + [NATIONAL_FILE, NATIONAL_PC_FILE, ECB_FILE],
        }

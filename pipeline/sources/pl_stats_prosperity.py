"""Ministry of Finance income and GUS bulk housing and tourism data."""

from __future__ import annotations

import json
import tempfile
import zipfile
from collections.abc import Collection
from pathlib import Path

from pipeline.core.bdl import is_whole_gmina, read_xlsx, teryt_from_bdl
from pipeline.core.source import Source, SourceInfo
from pipeline.sources.pl_more_gus import BDL_LICENCE, bdl_note, fetch_bdl_series, read_bdl_series
from pipeline.sources.pl_stats_population import (
    AREA_FILE,
    AREA_URL,
    POPULATION_URL,
    _area,
    _ascii_name,
    _best_population_table,
    _on_current_code,
)


MF_INCOME_URL = "https://www.gov.pl/attachment/23e9b124-8545-4178-ab54-81a9df16ace6"
MF_INDICATORS_URL = "https://www.gov.pl/attachment/fd12e8c5-be53-40cf-a72b-c54be3f39f4b"
HOUSING_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5478/5/171/1/"
    "budownictwo_mieszkaniowe_w_okresie_styczengrudzien_2025_r._wykresy.xlsx"
)
PROPERTY_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5492/8/9/1/"
    "obrot_nieruchomosciami_w_2025_tab.xlsx"
)
TOURISM_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5494/1/23/1/"
    "turystykaw2025r._tablice.zip"
)
TOURISM_CITIES_DIMENSIONS_URL = (
    "https://api-dbw.stat.gov.pl/api/variable/variable-section-position?id-przekroj=1408&lang=pl"
)
TOURISM_CITIES_URL = (
    "https://api-dbw.stat.gov.pl/api/variable/variable-data-section?"
    "id-zmienna=94&id-przekroj=1408&id-rok=2025&id-okres=282&ile-na-stronie=5000&numer-strony=0&lang=pl"
)

MF_INCOME_FILE = "mf-income-2026.xlsx"
MF_INDICATORS_FILE = "mf-tax-indicators-2026.xlsx"
POPULATION_FILE = "population-2025-12-31.zip"
HOUSING_FILE = "housing-2025.xlsx"
PROPERTY_FILE = "property-market-2025.xlsx"
TOURISM_FILE = "tourism-2025.zip"
TOURISM_CITIES_DIMENSIONS_FILE = "dbw/tourism-city-dimensions.json"
TOURISM_CITIES_FILE = "dbw/tourism-city-2025.json"
ANNUAL_YEAR = 2025
HOUSING_RATE = 747060
TOURISM_RATE = 60298
PRICE_VARIABLES = {
    "median_dwelling_price_m2": (633677, "Median dwelling sale price"),
    "median_dwelling_price_m2_primary": (633682, "Median primary-market dwelling sale price"),
    "median_dwelling_price_m2_secondary": (633687, "Median secondary-market dwelling sale price"),
    "average_dwelling_price_m2": (633692, "Average dwelling sale price"),
    "average_dwelling_price_m2_primary": (633697, "Average primary-market dwelling sale price"),
    "average_dwelling_price_m2_secondary": (633702, "Average secondary-market dwelling sale price"),
}


def positive_price(value):
    """A sale price exists only when at least one transaction produced a positive price."""
    return value if type(value) in (int, float) and value > 0 else None

VOIVODESHIPS = {
    "dolnoslaskie": "02",
    "kujawsko-pomorskie": "04",
    "lubelskie": "06",
    "lubuskie": "08",
    "lodzkie": "10",
    "malopolskie": "12",
    "mazowieckie": "14",
    "opolskie": "16",
    "podkarpackie": "18",
    "podlaskie": "20",
    "pomorskie": "22",
    "slaskie": "24",
    "swietokrzyskie": "26",
    "warminsko-mazurskie": "28",
    "wielkopolskie": "30",
    "zachodniopomorskie": "32",
}


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if float(value).is_integer() else float(value)


def _mf_gmina_code(value: object, unit_type: object) -> str | None:
    number = _number(value)
    if not isinstance(number, int):
        return None
    code = str(number).zfill(7)
    if unit_type == "M" and code.endswith("000"):
        code = f"{code[:4]}011"
    return code if is_whole_gmina(code) else None


def _voivodeship_code(value: object) -> str | None:
    normalized = _ascii_name(value).replace("\u2013", "-").strip()
    return VOIVODESHIPS.get(normalized)


def _read_zip_xlsx(path: Path, member_suffix: str, sheet: int | str) -> list[list[object | None]]:
    with zipfile.ZipFile(path) as archive:
        matches = [name for name in archive.namelist() if name.endswith(member_suffix)]
        if len(matches) != 1:
            raise RuntimeError(f"{path.name}: expected one member ending in {member_suffix!r}")
        data = archive.read(matches[0])
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as work:
        work.write(data)
        work.flush()
        return read_xlsx(work.name, sheet)


def build_income_table(
    income_rows: list[list[object | None]],
    indicator_rows: list[list[object | None]],
    populations: dict[str, int | float],
) -> dict:
    indicators: dict[str, int | float | None] = {}
    for row in indicator_rows:
        if len(row) <= 7 or row[4] not in {"G", "M"}:
            continue
        code = _mf_gmina_code(row[5], row[4])
        if code is not None:
            indicators[code] = _number(row[7])

    rows: dict[str, dict] = {}
    for row in income_rows:
        if len(row) <= 7 or row[4] not in {"G", "M"}:
            continue
        code = _mf_gmina_code(row[5], row[4])
        pit = _number(row[7])
        if code is None:
            continue
        population = _on_current_code(populations, code)
        rows[code] = {
            "pit_revenue_total": pit,
            "pit_revenue_per_person": round(pit / population, 2)
            if pit is not None and population is not None and population > 0
            else None,
            "tax_income_indicator_per_person": indicators.get(code),
        }

    return {
        "level": "gmina",
        "fields": {
            "pit_revenue_total": {
                "label": "Gmina share of PIT revenue",
                "unit": "PLN",
                "year": 2026,
                "note": "Ministry of Finance 2026 JST income workbook, calculated PIT income column.",
            },
            "pit_revenue_per_person": {
                "label": "Gmina share of PIT revenue per person",
                "unit": "PLN/person",
                "year": 2026,
                "note": "Derived from official 2026 PIT income and GUS population on 31 December 2025.",
            },
            "tax_income_indicator_per_person": {
                "label": "Individual tax income indicator",
                "unit": "PLN/person",
                "year": 2026,
                "note": "Ministry individual wealth indicator for 2026; successor to the former G indicator.",
            },
        },
        "rows": rows,
    }


def build_housing_table(
    housing_rows: list[list[object | None]], populations: dict[str, int | float]
) -> dict:
    population_by_voivodeship: dict[str, int | float] = {}
    for code, population in populations.items():
        population_by_voivodeship[code[:2]] = population_by_voivodeship.get(code[:2], 0) + population

    rows = {}
    for row in housing_rows:
        if len(row) <= 4:
            continue
        code = _voivodeship_code(row[1])
        completed = _number(row[4])
        population = population_by_voivodeship.get(code or "")
        if code is not None and completed is not None:
            rows[code] = {
                "dwellings_completed": completed,
                "dwellings_completed_per_1000": round(completed * 1000 / population, 2)
                if population is not None and population > 0
                else None,
            }
    return {
        "level": "voivodeship",
        "fields": {
            "dwellings_completed": {
                "label": "Dwellings completed",
                "unit": "dwellings",
                "year": 2025,
                "note": "GUS Housing construction January-December 2025, chart 2 source table.",
            },
            "dwellings_completed_per_1000": {
                "label": "Dwellings completed per 1,000 people",
                "unit": "dwellings/1,000 people",
                "year": 2025,
                "note": "Derived from GUS 2025 completions and population on 31 December 2025.",
            },
        },
        "rows": rows,
    }


def build_tourism_table(
    bed_rows: list[list[object | None]], night_rows: list[list[object | None]]
) -> dict:
    rows: dict[str, dict] = {}
    for source_rows, field in ((bed_rows, "tourist_beds"), (night_rows, "overnight_stays")):
        for row in source_rows:
            if len(row) <= 2:
                continue
            code = _voivodeship_code(row[0])
            value = _number(row[2])
            if code is not None and value is not None:
                rows.setdefault(code, {})[field] = value
    for row in rows.values():
        row.setdefault("tourist_beds", None)
        row.setdefault("overnight_stays", None)
    return {
        "level": "voivodeship",
        "fields": {
            "tourist_beds": {
                "label": "Tourist accommodation beds",
                "unit": "beds",
                "year": 2025,
                "note": "GUS Tourism in 2025, table I/2, state on 31 July.",
            },
            "overnight_stays": {
                "label": "Overnight stays in tourist accommodation",
                "unit": "nights",
                "year": 2025,
                "note": "GUS Tourism in 2025, table II/13, January to December.",
            },
        },
        "rows": rows,
    }


def build_property_tables(property_rows: list[list[object | None]]) -> dict:
    values = next((row for row in property_rows if row and row[0] == "Ogolem"), None)
    if values is None:
        values = next((row for row in property_rows if row and _ascii_name(row[0]) == "ogolem"), None)
    current = values or []
    row = {
        "average_dwelling_price_m2": None,
        "dwelling_price_index_2024_100": _number(current[1]) if len(current) > 1 else None,
        "dwelling_price_index_2015_100": _number(current[2]) if len(current) > 2 else None,
    }
    fields = {
        "average_dwelling_price_m2": {
            "label": "Average price per m2 of dwellings sold",
            "unit": "PLN/m2",
            "year": 2025,
            "note": "Not published in the 2025 GUS bulk property-market release; value remains null.",
        },
        "dwelling_price_index_2024_100": {
            "label": "Dwelling price index",
            "unit": "2024=100",
            "year": 2025,
            "note": "GUS Property market in 2025, table 3, all residential premises.",
        },
        "dwelling_price_index_2015_100": {
            "label": "Dwelling price index",
            "unit": "2015=100",
            "year": 2025,
            "note": "GUS Property market in 2025, table 3, all residential premises.",
        },
    }
    return {
        "housing_prices_country": {"level": "country", "fields": fields, "rows": {"PL": row}},
        "national_headlines": {"level": "country", "fields": fields, "rows": {"PL": dict(row)}},
    }


def tourism_city_rates(
    dimensions: list[dict], values: list[dict], populations: dict[str, int | float]
) -> dict[str, float | None]:
    codes = {}
    for dimension in dimensions:
        if dimension["id-wymiar"] != 1101:  # selected cities
            continue
        symbol = dimension["symbol"]
        if len(symbol) != 14 or not symbol.startswith("10"):
            raise ValueError(f"invalid DBW city code {symbol!r}")
        code = teryt_from_bdl(symbol[2:], 6)
        if is_whole_gmina(code):
            codes[dimension["id-pozycja"]] = code

    rates = {}
    for row in values:
        if row["id-pozycja-2"] != 6874517:  # all tourist origins
            continue
        code = codes.get(row["id-pozycja-1"])
        if code is None:
            continue
        if row["id-sposob-prezentacji-miara"] != 39:  # thousands of nights
            raise ValueError(f"DBW city {code} tourist nights use an unexpected unit")
        population = _on_current_code(populations, code)
        nights_thousands = _number(row.get("wartosc"))
        # DBW dictionaries mark 253 as a present value and 43 as public.
        published = row["id-brak-wartosci"] == 253 and row["id-tajnosci"] == 43
        rate = None
        if published and nights_thousands is not None and population and population > 0:
            rate = round(nights_thousands * 1000 / population, 4)
        rates[code] = rate
    return rates


def build_local_tourism(
    rates: dict[str, int | float | None],
    gmina_codes: Collection[str],
    city_rates: dict[str, float | None],
) -> dict:
    field = "overnight_stays_per_person"
    powiat = {
        code: {field: value / 1000 if value is not None else None}
        for code, value in rates.items()
    }
    gmina = {
        code: {field: powiat[code[:4]][field]}
        for code in gmina_codes
        if code.endswith("011") and int(code[2:4]) > 60 and code[:4] in powiat
    }
    for code, rate in city_rates.items():
        if code in gmina_codes and (code not in gmina or gmina[code][field] is None):
            gmina[code] = {field: rate}
    fields = {
        field: {
            "label": "Tourist nights per resident",
            "unit": "nights/person",
            "year": ANNUAL_YEAR,
            "note": (
                "Annual stays in tourist accommodation with at least 10 beds. "
                f"BDL rate per 1,000 people divided by 1,000. {bdl_note(TOURISM_RATE, 5, ANNUAL_YEAR)}"
            ),
        },
    }
    return {
        "tourism_powiat": {"level": "powiat", "fields": fields, "rows": powiat},
        "tourism_gmina": {
            "level": "gmina",
            "fields": {
                field: {
                    **fields[field],
                    "note": (
                        f"{fields[field]['note']} Cities with powiat rights use the same-area powiat rate. "
                        "Other published city rates divide DBW nights by population on 31 December 2025. "
                        f"See {TOURISM_CITIES_URL}."
                    ),
                },
            },
            "rows": gmina,
        },
    }


def build_local_tables(raw_dir: Path, populations: dict[str, int | float]) -> tuple[dict, list[str]]:
    gmina_codes = _area(raw_dir / AREA_FILE)
    housing, housing_files = read_bdl_series(raw_dir, HOUSING_RATE, 6, ANNUAL_YEAR)
    tourism, tourism_files = read_bdl_series(raw_dir, TOURISM_RATE, 5, ANNUAL_YEAR)
    field = "dwellings_completed_per_1000"
    tables = {
        "housing_gmina": {
            "level": "gmina",
            "fields": {
                field: {
                    "label": "Dwellings completed per 1,000 people",
                    "unit": "dwellings/1,000 people",
                    "year": ANNUAL_YEAR,
                    "note": f"Annual housing construction indicators. {bdl_note(HOUSING_RATE, 6, ANNUAL_YEAR)}",
                },
            },
            "rows": {code: {field: _on_current_code(housing, code)} for code in gmina_codes},
        },
    }
    city_dimensions = json.loads((raw_dir / TOURISM_CITIES_DIMENSIONS_FILE).read_text(encoding="utf-8"))
    city_values = json.loads((raw_dir / TOURISM_CITIES_FILE).read_text(encoding="utf-8"))["data"]
    city_rates = tourism_city_rates(city_dimensions, city_values, populations)
    tables.update(build_local_tourism(tourism, gmina_codes, city_rates))
    files = [AREA_FILE, TOURISM_CITIES_DIMENSIONS_FILE, TOURISM_CITIES_FILE, *housing_files, *tourism_files]
    price_fields = {}
    price_rows = {}
    for field, (variable, label) in PRICE_VARIABLES.items():
        values, series_files = read_bdl_series(raw_dir, variable, 5, ANNUAL_YEAR)
        price_fields[field] = {
            "label": label,
            "unit": "PLN/m2",
            "year": ANNUAL_YEAR,
            "note": f"Market sales of dwellings in multi-unit buildings. {bdl_note(variable, 5, ANNUAL_YEAR)}",
        }
        for code, value in values.items():
            price_rows.setdefault(code, {})[field] = positive_price(value)
        files.extend(series_files)
    for row in price_rows.values():
        for field in price_fields:
            row.setdefault(field, None)
    tables["housing_prices_powiat"] = {"level": "powiat", "fields": price_fields, "rows": price_rows}
    return tables, files


def build_tables(raw_dir: Path) -> tuple[dict, list[str]]:
    populations = _best_population_table(raw_dir / POPULATION_FILE)
    tables = {
        "income_gmina": build_income_table(
            read_xlsx(raw_dir / MF_INCOME_FILE, 0),
            read_xlsx(raw_dir / MF_INDICATORS_FILE, 0),
            populations,
        ),
        "housing_voivodeship": build_housing_table(
            read_xlsx(raw_dir / HOUSING_FILE, 1), populations
        ),
        "tourism_voivodeship": build_tourism_table(
            _read_zip_xlsx(raw_dir / TOURISM_FILE, "tablice_dzial_I.xlsx", "I.2"),
            _read_zip_xlsx(raw_dir / TOURISM_FILE, "tablice_dzial_II.xlsx", "II.13"),
        ),
    }
    tables.update(build_property_tables(read_xlsx(raw_dir / PROPERTY_FILE, 3)))
    local_tables, local_files = build_local_tables(raw_dir, populations)
    tables.update(local_tables)
    return tables, [
        MF_INCOME_FILE,
        MF_INDICATORS_FILE,
        POPULATION_FILE,
        HOUSING_FILE,
        PROPERTY_FILE,
        TOURISM_FILE,
        *local_files,
    ]


class PlStatsProsperitySource(Source):
    info = SourceInfo(
        id="pl_stats_prosperity",
        title="Polish local income, housing, and tourism statistics",
        publisher="Ministry of Finance and Statistics Poland (GUS)",
        homepage=(
            "https://www.gov.pl/web/finanse/kwoty-dochodow-jednostek-samorzadu-"
            "terytorialnego-na-rok-2026-potrzeby-finansowe-podlegajace-sfinansowaniu-"
            "oraz-szczegolowe-dane-wykorzystane-do-ich-obliczenia"
        ),
        description="Gmina PIT income and housing completions. Powiat dwelling prices and tourist nights.",
        license="Public sector information reuse terms and CC BY 4.0",
        used_for=["Yields", "City View", "Advisors", "Lenses"],
    )

    def fetch(self, force: bool = False) -> None:
        for url, filename in (
            (MF_INCOME_URL, MF_INCOME_FILE),
            (MF_INDICATORS_URL, MF_INDICATORS_FILE),
            (POPULATION_URL, POPULATION_FILE),
            (HOUSING_URL, HOUSING_FILE),
            (PROPERTY_URL, PROPERTY_FILE),
            (TOURISM_URL, TOURISM_FILE),
            (AREA_URL, AREA_FILE),
        ):
            path = self.download(url, filename, force=force, expect_binary=True)
            if not zipfile.is_zipfile(path):
                self.discard(filename)
                raise RuntimeError(f"{url} did not return an XLSX or ZIP file")
        self.download(TOURISM_CITIES_DIMENSIONS_URL, TOURISM_CITIES_DIMENSIONS_FILE, force=force)
        self.download(TOURISM_CITIES_URL, TOURISM_CITIES_FILE, force=force)
        fetch_bdl_series(self, HOUSING_RATE, 6, ANNUAL_YEAR, force=force)
        fetch_bdl_series(self, TOURISM_RATE, 5, ANNUAL_YEAR, force=force)
        for variable, _ in PRICE_VARIABLES.values():
            fetch_bdl_series(self, variable, 5, ANNUAL_YEAR, force=force)

    def process(self) -> dict:
        tables, files = build_tables(self.raw_dir)
        return {
            "vintage": "Ministry of Finance 2026; GUS annual 2025",
            "tables": tables,
            "notes": [
                "Ministry amounts are planned JST income for budget year 2026.",
                "The 2026 individual wealth indicator replaces the former G indicator under the new JST income law.",
                "PIT per person uses GUS population on 31 December 2025, including city counties.",
                BDL_LICENCE,
                "Gmina housing uses the BDL annual rate and maps type-only changes to the 2026 TERYT register.",
                "Gmina completions: https://bdl.stat.gov.pl/BDL/metadane/metryka/3820.",
                "GUS published the 2025 powiat dwelling prices on 22 October 2026. See "
                "https://bdl.stat.gov.pl/bdl/metadane/metryka/3787 and "
                "https://bdl.stat.gov.pl/bdl/metadane/metryka/3788.",
                "The annual GUS property workbook supplies the national price indices.",
                "GUS uses the value divided by total floor area for average prices. Primary-market prices include VAT.",
                "Sales of detached houses are outside the BDL dwelling price series. Unreported prices remain null.",
                "A zero price means no priced transaction and remains null.",
                "GUS reports incomplete price records for Szczecin from 2020 onward.",
                "Tourist nights: https://bdl.stat.gov.pl/BDL/metadane/metryka/2396.",
                "Since 2015, GUS publishes nationwide annual tourist nights starting at powiat level "
                "for confidentiality. Cities with powiat rights have matching gmina values. "
                "See https://bdl.stat.gov.pl/BDL/metadane/podgrupy/240.",
                "Statistics Poland DBW publishes extra city totals. "
                f"See {TOURISM_CITIES_URL} and {TOURISM_CITIES_DIMENSIONS_URL}.",
                "GUS withholds use figures for areas with fewer than three reporting establishments.",
                "Tourism counts cover establishments with at least 10 beds.",
                "REGON entities by PKD, useful floor area, and household disposable income remain gaps.",
            ],
            "_files": files,
        }

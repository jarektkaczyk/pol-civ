"""Statistics Poland vehicle registration and agricultural census tables."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pipeline.core.bdl import (
    bdl_url,
    download_pages,
    is_whole_gmina,
    load_pages,
    read_xlsx,
    teryt_from_bdl,
    value_for_year,
)
from pipeline.core.source import Source, SourceInfo
from pipeline.sources.pl_stats_population import AREA_FILE, AREA_URL, _area, _on_current_code


CARS = 60533
AVERAGE_FARM_AREA = 1633207
FARM_AREA = 1645031
AREA_2020_FILE = "area-population-2020.xlsx"
AREA_2020_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5468/7/17/1/"
    "powierzchnia_i_ludnosc_w_przekroju_terytorialnym_w_2020_roku_tablice.xlsx"
)
CARS_SUBJECT = "https://bdl.stat.gov.pl/BDL/metadane/metryka/2420"
AVERAGE_FARM_SUBJECT = "https://bdl.stat.gov.pl/bdl/dane/podgrup/temat/34/637/4138"
FARM_AREA_SUBJECT = "https://bdl.stat.gov.pl/bdl/dane/podgrup/temat/34/637/4140"
BDL_LICENCE = "Statistics Poland (GUS), Creative Commons Attribution 4.0."


def fetch_bdl_series(source: Source, variable: int, level: int, year: int, *, force: bool) -> list[str]:
    rel_dir = f"bdl/{variable}-{level}-{year}"
    files = download_pages(
        source, f"data/by-variable/{variable}", rel_dir,
        {"unit-level": level, "year": year}, force=force,
    )
    if force:
        cached_files = {
            path.relative_to(source.raw_dir).as_posix()
            for path in (source.raw_dir / rel_dir).glob("page-*.json")
        }
        for stale_file in sorted(cached_files.difference(files)):
            source.discard(stale_file)
    return files


def parse_bdl_series(records: list[dict], level: int, year: int) -> dict[str, int | float | None]:
    """Keep whole administrative units and observations with usable BDL flags."""
    rows = {}
    for record in records:
        unit_id = record["id"]
        code = teryt_from_bdl(unit_id, level)
        if level == 6 and not is_whole_gmina(code):
            continue
        if code in rows:
            raise ValueError(f"duplicate BDL TERYT code {code}")
        observations = [
            {**item, "value": item.get("val", item.get("value"))}
            for item in record.get("values", [])
        ]
        rows[code] = value_for_year({"values": observations}, year)
    return rows


def read_bdl_series(
    raw_dir: Path, variable: int, level: int, year: int
) -> tuple[dict[str, int | float | None], list[str]]:
    rel_dir = f"bdl/{variable}-{level}-{year}"
    records = load_pages(raw_dir, rel_dir)
    if not records:
        raise ValueError(f"BDL variable {variable} has no level {level} observations for {year}")
    files = [
        path.relative_to(raw_dir).as_posix()
        for path in sorted((raw_dir / rel_dir).glob("page-*.json"))
    ]
    return parse_bdl_series(records, level, year), files


def bdl_note(variable: int, level: int, year: int) -> str:
    url = bdl_url(f"data/by-variable/{variable}", {"unit-level": level, "year": year})
    return f"BDL variable {variable} at {url}."


def farm_area_denominators(rows: list[list]) -> dict[str, int | float]:
    areas = {}
    for row in rows:
        if len(row) < 3:
            continue
        code = str(row[0]).replace(" ", "")
        area = row[2]
        if is_whole_gmina(code) and type(area) in (int, float) and area > 0:
            areas[code] = area
    return areas


def farm_rows(
    codes: Iterable[str],
    average: dict[str, int | float | None],
    farm_area: dict[str, int | float | None],
    land_area: dict[str, int | float],
) -> dict:
    rows = {}
    for code in codes:
        # Match the numerator to its 2020 territory before mapping to the 2026
        # gmina code. A type-only change does not alter the key's first six digits.
        area = _on_current_code(land_area, code)
        total = _on_current_code(farm_area, code)
        average_value = _on_current_code(average, code)
        rows[code] = {
            "average_farm_area_ha": average_value if average_value and average_value > 0 else None,
            "farm_land_share": round(total * 100 / area, 2)
            if area and total is not None and 0 <= total <= area
            else None,
        }
    return rows


class PlMoreGusSource(Source):
    info = SourceInfo(
        id="pl_more_gus",
        title="Passenger car registrations and agricultural holdings",
        publisher="Statistics Poland (GUS)",
        homepage="https://bdl.stat.gov.pl/bdl/start",
        description="Powiat passenger cars and PSR 2020 agricultural holdings by gmina.",
        license="Creative Commons Attribution 4.0",
        used_for=["Advisors", "Lenses"],
    )

    def fetch(self, force: bool = False) -> None:
        self.download(AREA_URL, AREA_FILE, force=force, expect_binary=True)
        self.download(AREA_2020_URL, AREA_2020_FILE, force=force, expect_binary=True)
        for variable, level, year in ((CARS, 5, 2025), (AVERAGE_FARM_AREA, 6, 2020), (FARM_AREA, 6, 2020)):
            fetch_bdl_series(self, variable, level, year, force=force)

    def process(self) -> dict:
        cars, car_files = read_bdl_series(self.raw_dir, CARS, 5, 2025)
        average, average_files = read_bdl_series(self.raw_dir, AVERAGE_FARM_AREA, 6, 2020)
        farm_area, farm_files = read_bdl_series(self.raw_dir, FARM_AREA, 6, 2020)
        areas = farm_area_denominators(read_xlsx(self.raw_dir / AREA_2020_FILE, "tabl. 21"))
        current = _area(self.raw_dir / AREA_FILE)
        return {
            "vintage": "GUS BDL 2025 vehicle registrations; PSR 2020, 1 June 2020",
            "tables": {
                "vehicles_powiat": {
                    "level": "powiat",
                    "fields": {
                        "passenger_cars_per_1000": {
                            "label": "Registered passenger cars per 1,000 people",
                            "unit": "cars/1,000 people",
                            "year": 2025,
                            "note": f"31 December 2025, Statistics Poland vehicle registrations. {bdl_note(CARS, 5, 2025)}",
                        },
                    },
                    "rows": {code: {"passenger_cars_per_1000": value} for code, value in cars.items()},
                },
                "farms_gmina": {
                    "level": "gmina",
                    "fields": {
                        "average_farm_area_ha": {
                            "label": "Average agricultural holding area",
                            "unit": "ha/holding",
                            "year": 2020,
                            "note": (
                                "1 June 2020, all land in a holding, attributed by its seat. "
                                f"{bdl_note(AVERAGE_FARM_AREA, 6, 2020)}"
                            ),
                        },
                        "farm_land_share": {
                            "label": "Land in agricultural holdings as a share of gmina area",
                            "unit": "%",
                            "year": 2020,
                            "note": (
                                "All land in holdings assigned to their seat, divided by gmina area on 1 January 2020. "
                                "The land itself can cross gmina borders. Ratios above 100% remain null. "
                                f"{bdl_note(FARM_AREA, 6, 2020)}"
                            ),
                        },
                    },
                    "rows": farm_rows(current, average, farm_area, areas),
                },
            },
            "notes": [
                BDL_LICENCE,
                f"Registered passenger cars: {CARS_SUBJECT}.",
                "GUS DBW publishes fuel types at voivodeship level. "
                "See https://api-dbw.stat.gov.pl/api/variable/variable-meta?id-zmiennej=851&lang=pl.",
                "The 2025 CEPiK statistics cover first registrations by region. The open vehicle API uses "
                "registration periods and sometimes combines city and land powiat records. "
                "See https://api.cepik.gov.pl/doc.",
                f"PSR 2020 holding area: {AVERAGE_FARM_SUBJECT} and {FARM_AREA_SUBJECT}.",
                "A zero average with no agricultural holding remains null.",
                f"The 2020 geographic denominator is GUS area and population table 21: {AREA_2020_URL}.",
                "The source matches type-only gmina changes to 2026 TERYT. "
                "The area statistics retain the 2020 boundaries.",
                "Statistical confidentiality and absent figures remain null.",
            ],
            "_files": [AREA_FILE, AREA_2020_FILE, *car_files, *average_files, *farm_files],
        }

"""NSP 2021 resident education from BDL and final regional workbooks."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from pipeline.core.bdl import read_xlsx
from pipeline.core.source import Source, SourceInfo
from pipeline.sources.pl_more_gus import BDL_LICENCE, bdl_note, fetch_bdl_series, read_bdl_series
from pipeline.sources.pl_stats_labour import CERTUM_CROSS_URL, CERTUM_INTERMEDIATE_URL, _gus_trust_chain
from pipeline.sources.pl_stats_population import AREA_FILE, AREA_URL, _area, _on_current_code


YEAR = 2021
POPULATION_13_PLUS = 1719968
HIGHER_EDUCATION = 1719969
SUBJECT_URL = "https://bdl.stat.gov.pl/bdl/dane/podgrup/temat/31/640/4318"

CERTUM_INTERMEDIATE_FILE = "certumovtlsg2r39ca.cer"
CERTUM_CROSS_FILE = "ctnca-ctrca.pem"
REGIONAL_WORKBOOKS = {
    "04": (
        "regional/04-final-direct.xlsx", "Tabl. 8",
        "https://bydgoszcz.stat.gov.pl/download/gfx/bydgoszcz/pl/defaultaktualnosci/753/19/1/1/"
        "tablice_nsp2021_stan_i_struktura_dem-spol_w_woj._kuj-pom_w_swietle_wynikow_nsp_2021.xlsx",
    ),
    "10": (
        "regional/10-final-00.xlsx", "Tabl. 16",
        "https://lodz.stat.gov.pl/download/gfx/lodz/pl/defaultaktualnosci/753/27/1/1/"
        "202401_p_nsp_stan_i_struktura_demog_spol_lodzkie.xlsx",
    ),
    "22": (
        "regional/22-final-direct.xlsx", "7",
        "https://gdansk.stat.gov.pl/download/gfx/gdansk/pl/defaultaktualnosci/753/15/1/1/"
        "nsp_2021_stan_i_struktura_demo-spol_ludnosci_pomorskie_-tablice_wynikowe-dodatkowe.xlsx",
    ),
    "28": (
        "regional/28-final-00.xlsx", "3.5.",
        "https://olsztyn.stat.gov.pl/download/gfx/olsztyn/pl/defaultaktualnosci/753/32/1/1/"
        "2024_01_31_stan_i_struktura_demograficzno_spoleczna_ludnosci.xlsx",
    ),
    "32": (
        "regional/32-final-00.xlsx", "Tabl. 14",
        "https://szczecin.stat.gov.pl/download/gfx/szczecin/pl/defaultaktualnosci/753/19/1/1/aneks_wojewodzki.xlsx",
    ),
}
REGIONAL_LABELS = {
    "post_secondary": "Post-secondary education",
    "secondary_vocational": "Vocational secondary education",
    "secondary_general": "General secondary education",
    "basic_vocational": "Basic vocational or sectoral education",
    "lower_secondary": "Lower secondary education",
    "primary_completed": "Completed primary education",
    "primary_incomplete": "Primary incomplete or no school education",
    "unknown": "Education level unknown",
    "secondary_post_secondary": "Secondary and post-secondary education",
    "primary_combined": "Primary completed, primary incomplete, or no school education",
    "lower_primary_combined": "Lower secondary or completed primary education",
}


def _plain(value: object) -> str:
    text = str(value or "").lower().translate(str.maketrans({"\u0142": "l"}))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _powiat_lookup(path: Path) -> dict[tuple[str, str], str]:
    result = {}
    for row in read_xlsx(path, "Tabl. 2"):
        code = str(row[0] or "").strip() if row else ""
        if len(code) == 4 and code.isdigit() and len(row) > 1:
            name = _plain(row[1])
            result[(code[:2], name)] = code
            if name.startswith("m st "):
                result[(code[:2], name[5:])] = code
    return result


def _number(value: object) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _powiat_code(value: object, known: set[str]) -> str | None:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    if len(text) == 7 and text.isdigit():
        text = text[:4]
    return text if len(text) == 4 and text.isdigit() and text in known else None


def _name_code(value: object, voivode: str, lookup: dict[tuple[str, str], str]) -> str | None:
    name = _plain(value)
    key = re.sub(
        r"^(?:powiat )?(?:(?:miasto na prawach powiatu|m st|m) )?",
        "",
        name,
    )
    return lookup.get((voivode, key))


def parse_final_education_rows(
    rows, voivode: str, lookup: dict[tuple[str, str], str]
) -> dict[str, dict]:
    known = set(lookup.values())
    data_index = next(
        (
            i for i, row in enumerate(rows)
            if row and (_powiat_code(row[0], known) or _name_code(row[0], voivode, lookup))
        ),
        None,
    )
    if data_index is None:
        return {}
    header_end = next(
        (
            i for i, row in enumerate(rows[:data_index])
            if sum(_number(value) is not None for value in row) >= 3
        ),
        data_index,
    )
    width = max(len(row) for row in rows[:header_end])
    headers = [
        _plain(" ".join(str(row[index]) for row in rows[:header_end] if index < len(row) and row[index] is not None))
        for index in range(width)
    ]
    columns = {}
    higher_columns = []
    for index, text in enumerate(headers):
        if index > 0 and "ogolem" in text and ("total" in text or index in {1, 2}):
            columns.setdefault("population_13_plus", index)
        if ("wyzsz" in text or "dyplom ukonczenia kolegium" in text) and "zmiana" not in text:
            higher_columns.append(index)
        if "policealne" in text and "srednie" not in text:
            columns.setdefault("post_secondary", index)
        if "srednie zawodowe" in text:
            columns.setdefault("secondary_vocational", index)
        elif "srednie ogolno" in text:
            columns.setdefault("secondary_general", index)
        elif "srednie" in text and ("razem" in text or "policealne" in text or "secondary" in text):
            columns.setdefault("secondary_post_secondary", index)
        if "zasadnicze zawodowe" in text or "zasadnicze branzowe" in text:
            columns.setdefault("basic_vocational", index)
        if "gimnazjalne" in text and "podstawowe" in text:
            columns.setdefault("lower_primary_combined", index)
        elif "gimnazjalne" in text:
            columns.setdefault("lower_secondary", index)
        if "podstawowe" in text and ("nieukonczone" in text or "bez wyksztalcenia" in text):
            if (
                "podstawowe ukonczone" in text or text.count("podstawowe") >= 2
            ) and "nieukonczone" in text:
                columns.setdefault("primary_combined", index)
            else:
                columns.setdefault("primary_incomplete", index)
        elif "podstawowe ukonczone" in text and "gimnazjalne" not in text:
            columns.setdefault("primary_completed", index)
        if "nieustalon" in text:
            columns.setdefault("unknown", index)
    total_higher = [index for index in higher_columns if "razem" in headers[index]]
    if total_higher:
        columns["higher"] = total_higher[0]
    elif higher_columns:
        columns["higher"] = higher_columns
    required = {"population_13_plus", "higher"}
    if not required.issubset(columns):
        return {}
    result = {}
    pending_code = None
    for row in rows[data_index:]:
        block_label = _plain(" ".join(str(value) for value in row[:2] if value is not None))
        if result and (block_label.startswith("mezczyzni") or block_label.startswith("kobiety")):
            break
        code = _powiat_code(row[0] if row else None, known)
        code = code or _name_code(row[0] if row else None, voivode, lookup)
        if code is not None and code in result:
            break
        if code:
            pending_code = code
        year = _number(row[1]) if len(row) > 1 else None
        if year == 2011:
            continue
        if code is None and year == 2021:
            code = pending_code
        if code is None:
            continue
        values = {}
        for field, index in columns.items():
            if isinstance(index, list):
                numbers = [_number(row[item]) if item < len(row) else None for item in index]
                values[field] = (
                    sum(number for number in numbers if number is not None)
                    if any(number is not None for number in numbers)
                    else None
                )
            else:
                values[field] = _number(row[index]) if index < len(row) else None
        result[code] = values
    totals = [values.get("population_13_plus") for values in result.values()]
    numeric_totals = [value for value in totals if _number(value) is not None]
    if numeric_totals and all(99.99 <= value <= 100.01 for value in numeric_totals):
        return {}
    return result

def read_regional_counts(raw_dir: Path) -> tuple[dict[str, dict], list[str]]:
    lookup = _powiat_lookup(raw_dir / AREA_FILE)
    rows = {}
    files = []
    for voivodeship, (filename, sheet, _) in REGIONAL_WORKBOOKS.items():
        parsed = parse_final_education_rows(read_xlsx(raw_dir / filename, sheet), voivodeship, lookup)
        if not parsed:
            raise ValueError(f"{filename}: no supported education counts in {sheet}")
        rows.update(parsed)
        files.append(filename)
    return rows, files


def education_rows(
    codes: Iterable[str],
    total: dict[str, int | float | None],
    higher: dict[str, int | float | None],
    *,
    map_gminas: bool = False,
) -> dict:
    rows = {}
    for code in sorted(codes):
        count = _on_current_code(total, code) if map_gminas else total.get(code)
        graduates = _on_current_code(higher, code) if map_gminas else higher.get(code)
        rows[code] = {
            "population_13_plus": count,
            "higher": graduates,
            "higher_share": round(graduates * 100 / count, 4)
            if count and graduates is not None and 0 <= graduates <= count
            else None,
        }
    return rows


class PolandCensus2021(Source):
    info = SourceInfo(
        id="pl_census_2021",
        title="NSP 2021 education by powiat and gmina",
        publisher="Statistics Poland (GUS)",
        homepage=SUBJECT_URL,
        license="Creative Commons Attribution 4.0",
        description="Population aged 13 and older and residents with higher education at the 2021 census.",
        used_for=["Knowledge advisor", "Education lens", "City View citizens"],
    )

    def fetch(self, force: bool = False) -> None:
        self.download(AREA_URL, AREA_FILE, force=force, expect_binary=True)
        intermediate = self.download(CERTUM_INTERMEDIATE_URL, CERTUM_INTERMEDIATE_FILE, force=force, expect_binary=True)
        cross = self.download(CERTUM_CROSS_URL, CERTUM_CROSS_FILE, force=force, expect_binary=True)
        with _gus_trust_chain(intermediate, cross):
            for filename, _, url in REGIONAL_WORKBOOKS.values():
                self.download(url, filename, force=force, expect_binary=True)
        for level in (5, 6):
            for variable in (POPULATION_13_PLUS, HIGHER_EDUCATION):
                fetch_bdl_series(self, variable, level, YEAR, force=force)

    def process(self) -> dict:
        current_gminas = _area(self.raw_dir / AREA_FILE)
        regional, regional_files = read_regional_counts(self.raw_dir)
        tables = {}
        files = [AREA_FILE, *regional_files]
        for level, label, codes in (
            (5, "powiat", {code[:4] for code in current_gminas}),
            (6, "gmina", current_gminas),
        ):
            total, total_files = read_bdl_series(self.raw_dir, POPULATION_13_PLUS, level, YEAR)
            higher, higher_files = read_bdl_series(self.raw_dir, HIGHER_EDUCATION, level, YEAR)
            rows = education_rows(codes, total, higher, map_gminas=level == 6)
            fields = {
                "population_13_plus": {
                    "label": "Resident population aged 13 and older",
                    "unit": "persons",
                    "year": YEAR,
                    "note": f"31 March 2021, NSP 2021 resident population. {bdl_note(POPULATION_13_PLUS, level, YEAR)}",
                },
                "higher": {
                    "label": "Residents with higher education",
                    "unit": "persons",
                    "year": YEAR,
                    "note": (
                        "31 March 2021, NSP 2021 resident population aged 13 and older. "
                        f"{bdl_note(HIGHER_EDUCATION, level, YEAR)}"
                    ),
                },
                "higher_share": {
                    "label": "Share of residents with higher education",
                    "unit": "%",
                    "year": YEAR,
                    "note": "31 March 2021, share of all NSP 2021 residents aged 13 and older, including unknown education.",
                },
            }
            if level == 5:
                for name, field_label in REGIONAL_LABELS.items():
                    fields[name] = {
                        "label": field_label,
                        "unit": "persons",
                        "year": YEAR,
                        "note": "31 March 2021, regional NSP 2021 workbook and its population definition.",
                    }
                for code, row in rows.items():
                    categories = regional.get(code, {})
                    row.update({name: categories.get(name) for name in REGIONAL_LABELS})
            tables[f"education_{label}"] = {"level": label, "fields": fields, "rows": rows}
            files.extend(total_files + higher_files)
        return {
            "vintage": "NSP 2021 final results, 31 March 2021; BDL P4318 and five regional workbooks",
            "tables": tables,
            "notes": [
                BDL_LICENCE,
                f"NSP 2021 resident population ages 13 and older: {SUBJECT_URL}.",
                "The denominator includes all residents aged 13 and older, including people with unknown education.",
                f"Final regional workbooks supply additional education counts for {len(regional)} powiats.",
                "The regional category counts and BDL resident total use different population definitions.",
                "The source matches type-only gmina changes to 2026 TERYT. "
                "The counts retain the 2021 census boundaries.",
                "Statistical confidentiality and absent figures remain null.",
            ],
            "_files": files,
        }

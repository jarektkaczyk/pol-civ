"""NSP 2021 education by powiat from final and preliminary GUS workbooks."""

from __future__ import annotations

import re
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin

from ..core.bdl import _sheet_paths, read_xlsx
from ..core.fetch import OfflineError
from ..core.source import Source, SourceInfo
from .pl_stats_labour import CERTUM_CROSS_URL, CERTUM_INTERMEDIATE_URL, _gus_trust_chain

YEAR = 2021
CERTUM_INTERMEDIATE_FILE = "certumovtlsg2r39ca.cer"
CERTUM_CROSS_FILE = "ctnca-ctrca.pem"
TERYT_FILE = "area-population-2026.xlsx"
TERYT_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5468/7/23/1/powierzchnia_i_ludnosc_w_przekroju_terytorialnym_2026_2.xlsx"
)
OFFICES = {
    "02": "wroclaw", "04": "bydgoszcz", "06": "lublin", "08": "zielonagora",
    "10": "lodz", "12": "krakow", "14": "warszawa", "16": "opole",
    "18": "rzeszow", "20": "bialystok", "22": "gdansk", "24": "katowice",
    "26": "kielce", "28": "olsztyn", "30": "poznan", "32": "szczecin",
}
FALLBACK_PAGES = {
    "06": (
        "https://lublin.stat.gov.pl/opracowania-biezace/opracowania-sygnalne/"
        "spisy-powszechne/stan-i-struktura-demograficzno-spoleczna-ludnosci-w-"
        "wojewodztwie-lubelskim-wyniki-wstepne-nsp-2021,5,1.html"
    ),
    "22": (
        "https://gdansk.stat.gov.pl/opracowania-biezace/opracowania-sygnalne/"
        "ludnosc/stan-i-struktura-demograficzno-spoleczna-ludnosci-w-"
        "wojewodztwie-pomorskim-wyniki-wstepne-nsp-2021,8,1.html"
    ),
    "26": (
        "https://kielce.stat.gov.pl/opracowania-biezace/opracowania-sygnalne/"
        "ludnosc/stan-i-struktura-demograficzno-spoleczna-ludnosci-w-"
        "wojewodztwie-swietokrzyskim-wyniki-wstepne-nsp-2021,7,1.html"
    ),
    "28": (
        "https://olsztyn.stat.gov.pl/opracowania-biezace/opracowania-sygnalne/"
        "ludnosc/"
        "stan-i-struktura-demograficzno-spoleczna-ludnosci-w-wojewodztwie-"
        "warminsko-mazurskim-wyniki-wstepne-nsp-2021,28,1.html"
    ),
    "30": (
        "https://poznan.stat.gov.pl/opracowania-biezace/opracowania-sygnalne/"
        "ludnosc/stan-i-struktura-demograficzno-spoleczna-ludnosci-w-"
        "wojewodztwie-wielkopolskim-wyniki-wstepne-nsp-2021,6,1.html"
    ),
    "32": (
        "https://szczecin.stat.gov.pl/opracowania-biezace/opracowania-sygnalne/"
        "ludnosc/stan-i-struktura-demograficzno-spoleczna-ludnosci-w-"
        "wojewodztwie-zachodniopomorskim-wyniki-wstepne-nsp-2021,6,1.html"
    ),
}
FINAL_WORKBOOKS = {
    "04": (
        "https://bydgoszcz.stat.gov.pl/download/gfx/bydgoszcz/pl/"
        "defaultaktualnosci/753/19/1/1/"
        "tablice_nsp2021_stan_i_struktura_dem-spol_w_woj._kuj-pom_w_swietle_wynikow_nsp_2021.xlsx"
    ),
    "22": (
        "https://gdansk.stat.gov.pl/download/gfx/gdansk/pl/defaultaktualnosci/"
        "753/15/1/1/nsp_2021_stan_i_struktura_demo-spol_ludnosci_pomorskie_-"
        "tablice_wynikowe-dodatkowe.xlsx"
    ),
}
LABELS = {
    "population_13_plus": "Population aged 13 and older",
    "higher": "Higher education or college diploma",
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
SHARE_LABELS = {
    "higher_share": "Share with higher education or college diploma",
}
AGGREGATE_FIELDS = {"secondary_post_secondary", "primary_combined", "lower_primary_combined"}


class PublicationNotFoundError(RuntimeError):
    pass


def _plain(value: object) -> str:
    text = str(value or "").lower().translate(str.maketrans({"\u0142": "l"}))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            values = dict(attrs)
            self.href = values.get("href")
            self.text = [values.get("title", "")]

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href is not None:
            self.links.append((self.href, " ".join(self.text)))
            self.href = None
            self.text = []


def _links(path: Path, base_url: str) -> list[tuple[str, str]]:
    parser = _LinkParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return [(urljoin(base_url, href), text) for href, text in parser.links]


def _publication_url(index_path: Path, index_url: str) -> str:
    candidates = []
    for url, text in _links(index_path, index_url):
        plain = _plain(f"{url} {text}")
        if (
            "/publikacje-i-foldery/spisy-powszechne/" in url
            and "2021" in plain
            and "demograficzno spoleczna" in plain
            and "2011" not in plain
        ):
            candidates.append(url.split("?", 1)[0])
    unique = list(dict.fromkeys(candidates))
    if not unique:
        raise PublicationNotFoundError(
            f"no final NSP 2021 demographic-social publication found in {index_path}"
        )
    return unique[0]


def _workbook_urls(page_path: Path, page_url: str) -> list[str]:
    urls = [
        url for url, _text in _links(page_path, page_url)
        if url.lower().split("?", 1)[0].endswith((".xlsx", ".xls"))
    ]
    return list(dict.fromkeys(urls))


def _preliminary_url(search_path: Path, search_url: str) -> str | None:
    candidates = []
    for url, text in _links(search_path, search_url):
        plain = _plain(f"{url} {text}")
        if (
            url.lower().split("?", 1)[0].endswith(".html")
            and "wyniki wstepne nsp 2021" in plain
            and "demograficzno spoleczna" in plain
        ):
            candidates.append(url.split("?", 1)[0])
    return next(iter(dict.fromkeys(candidates)), None)


def _sheet_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as book:
        return [name for name, _target in _sheet_paths(book)]


def _education_sheet(path: Path) -> list[list[object | None]] | None:
    for name in _sheet_names(path):
        rows = read_xlsx(path, name)
        title = _plain(" ".join(str(value) for row in rows[:4] for value in row if value is not None))
        if (
            "ludnosc w wieku 13 lat i wiecej" in title
            and "wyksztalcen" in title
            and "powiat" in title
            and "niepelnosprawn" not in title
        ):
            return rows
    return None


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


def _category_columns(header: list[object | None]) -> dict[str, list[int]]:
    columns: dict[str, list[int]] = {
        name: [] for name in LABELS if name not in AGGREGATE_FIELDS
    }
    for index, raw in enumerate(header):
        text = _plain(raw)
        if index == 1 and ("ogolem" in text or "total" in text):
            columns["population_13_plus"].append(index)
        elif text.startswith("wyzsze") or "dyplom ukonczenia kolegium" in text:
            columns["higher"].append(index)
        elif text.startswith("policealne"):
            columns["post_secondary"].append(index)
        elif "srednie zawodowe" in text:
            columns["secondary_vocational"].append(index)
        elif "srednie ogolnoksztalcace" in text:
            columns["secondary_general"].append(index)
        elif "zasadnicze zawodowe" in text or "zasadnicze branzowe" in text:
            columns["basic_vocational"].append(index)
        elif text.startswith("gimnazjalne"):
            columns["lower_secondary"].append(index)
        elif "podstawowe ukonczone" in text:
            columns["primary_completed"].append(index)
        elif "podstawowe nieukonczone" in text or "bez wyksztalcenia szkolnego" in text:
            columns["primary_incomplete"].append(index)
        elif "nieustalon" in text or "unknown" in text:
            columns["unknown"].append(index)
    return columns


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


def parse_education_map(rows, voivode: str, lookup: dict[tuple[str, str], str]) -> dict[str, dict]:
    known = set(lookup.values())
    header_index = None
    columns = {}
    total_column = None
    for index, row in enumerate(rows[:15]):
        candidate = {}
        candidate_total = None
        for column, raw in enumerate(row):
            text = _plain(raw)
            if text in {"ogolem", "ogolem total"}:
                candidate_total = column
            if "wyzsz" in text:
                candidate["higher_share"] = column
        if len(candidate) >= len(columns):
            header_index, columns = index, candidate
            total_column = candidate_total
    if header_index is None or "higher_share" not in columns:
        return {}
    result = {}
    for row in rows[header_index + 1:]:
        if not row:
            continue
        code = next((_powiat_code(value, known) for value in row[:2] if _powiat_code(value, known)), None)
        name_column = 1 if code and _powiat_code(row[0], known) else 0
        if code is None:
            name = _plain(row[name_column] if name_column < len(row) else None)
            key = re.sub(
                r"^(?:powiat )?(?:(?:miasto na prawach powiatu|m st|m) )?",
                "",
                name,
            )
            code = lookup.get((voivode, key))
        if code is None:
            continue
        values = {}
        for field, column in columns.items():
            value = _number(row[column]) if column < len(row) else None
            if field == "higher_share" and total_column is not None:
                total = _number(row[total_column]) if total_column < len(row) else None
                value = value * 100 / total if total and value is not None else None
            if value is not None and 0 <= value <= 100:
                values[field] = value
        if values:
            result[code] = values
    return result


def parse_education_rows(rows, voivode: str, lookup: dict[tuple[str, str], str]) -> dict[str, dict]:
    header_index = next((i for i, row in enumerate(rows) if row and "wyszczegolnienie" in _plain(row[0])), None)
    if header_index is None:
        raise RuntimeError("education worksheet has no header")
    columns = _category_columns(rows[header_index])
    missing = [field for field, indexes in columns.items() if not indexes]
    if missing:
        raise RuntimeError(f"education worksheet lacks categories: {missing}")
    result = {}
    in_total = False
    for row in rows[header_index + 1:]:
        name = _plain(row[0] if row else None)
        if name in {"mezczyzni males", "mezczyzni", "kobiety females", "kobiety"}:
            break
        if name.startswith("powiaty"):
            in_total = True
            continue
        if not in_total or len(row) < 2 or _number(row[1]) is None:
            continue
        key = re.sub(
            r"^(?:powiat )?(?:(?:miasto na prawach powiatu|m st|m) )?",
            "",
            name,
        )
        code = lookup.get((voivode, key))
        if code is None:
            continue
        values = {}
        for field, indexes in columns.items():
            numbers = [_number(row[index]) if index < len(row) else None for index in indexes]
            values[field] = sum(number for number in numbers if number is not None) if any(
                number is not None for number in numbers
            ) else None
        result[code] = values
    return result


class PolandCensus2021(Source):
    info = SourceInfo(
        id="pl_census_2021",
        title="NSP 2021 education by powiat",
        publisher="Statistics Poland (GUS), regional statistical offices",
        homepage="https://stat.gov.pl/spisy-powszechne/nsp-2021/nsp-2021-wyniki-ostateczne/",
        license="Creative Commons Attribution 4.0",
        description="Population aged 13 and older by completed education level at powiat level.",
        used_for=["Knowledge advisor", "Education lens", "City View citizens"],
    )

    def fetch(self, force=False):
        intermediate = self.download(CERTUM_INTERMEDIATE_URL, CERTUM_INTERMEDIATE_FILE, force=force, expect_binary=True)
        cross = self.download(CERTUM_CROSS_URL, CERTUM_CROSS_FILE, force=force, expect_binary=True)
        with _gus_trust_chain(intermediate, cross):
            self.download(TERYT_URL, TERYT_FILE, force=force, expect_binary=True)
            for code, office in OFFICES.items():
                if code in FINAL_WORKBOOKS:
                    self.download(
                        FINAL_WORKBOOKS[code], f"regional/{code}-final-direct.xlsx",
                        force=force, expect_binary=True,
                    )
                search_url = (
                    f"https://{office}.stat.gov.pl/wyszukiwarka/szukaj.html?"
                    "query=demograficzno-spo%C5%82eczna"
                )
                search_path = self.download(search_url, f"discovery/{code}-search.html", force=force)
                try:
                    final_url = _publication_url(search_path, search_url)
                    final_path = self.download(
                        final_url, f"discovery/{code}-final.html", force=force
                    )
                    for index, url in enumerate(_workbook_urls(final_path, final_url)):
                        suffix = Path(url.split("?", 1)[0]).suffix.lower()
                        self.download(
                            url, f"regional/{code}-final-{index:02d}{suffix}",
                            force=force, expect_binary=True,
                        )
                except (FileNotFoundError, HTTPError, OfflineError, PublicationNotFoundError):
                    pass
                preliminary_url = FALLBACK_PAGES.get(code) or _preliminary_url(search_path, search_url)
                if not preliminary_url:
                    raise RuntimeError(f"{code}: preliminary NSP 2021 education page not found")
                try:
                    preliminary_path = self.download(
                        preliminary_url, f"discovery/{code}-preliminary.html", force=force
                    )
                except (FileNotFoundError, HTTPError, OfflineError):
                    if code == "28":
                        continue
                    raise
                workbook_urls = _workbook_urls(preliminary_path, preliminary_url)
                if not workbook_urls:
                    raise RuntimeError(f"{code}: preliminary page has no XLSX workbook")
                for index, url in enumerate(workbook_urls):
                    suffix = Path(url.split("?", 1)[0]).suffix.lower()
                    self.download(
                        url, f"regional/{code}-pre-{index:02d}{suffix}",
                        force=force, expect_binary=True,
                    )

    def process(self):
        lookup = _powiat_lookup(self.raw_dir / TERYT_FILE)
        known = set(lookup.values())
        rows = {
            code: {field: None for field in [*LABELS, *SHARE_LABELS]}
            for code in sorted(known)
        }
        used = []
        for code in OFFICES:
            final_paths = [
                *sorted((self.raw_dir / "regional").glob(f"{code}-final-*.xlsx")),
            ]
            for path in final_paths:
                sheet = _education_sheet(path)
                if sheet is None:
                    continue
                parsed = parse_final_education_rows(sheet, code, lookup)
                if parsed:
                    for powiat, values in parsed.items():
                        rows[powiat].update(values)
                        total, higher = values.get("population_13_plus"), values.get("higher")
                        if total and higher is not None:
                            rows[powiat]["higher_share"] = higher * 100 / total
                    used.append(str(path.relative_to(self.raw_dir)))
                    break
            for path in sorted((self.raw_dir / "regional").glob(f"{code}-pre-*.xlsx")):
                parsed = {}
                for name in _sheet_names(path):
                    sheet_rows = read_xlsx(path, name)
                    parsed.update(parse_education_map(sheet_rows, code, lookup))
                if not parsed:
                    continue
                for powiat, values in parsed.items():
                    for field, value in values.items():
                        if rows[powiat][field] is None:
                            rows[powiat][field] = value
                used.append(str(path.relative_to(self.raw_dir)))
        if len(rows) != 380:
            raise RuntimeError(f"NSP education: expected 380 powiats, got {len(rows)}")
        final_coverage = {
            code for code, row in rows.items()
            if row["population_13_plus"] is not None and row["higher"] is not None
        }
        share_coverage = {code for code, row in rows.items() if row["higher_share"] is not None}
        fields = {
            name: {"label": label, "unit": "persons", "year": YEAR,
                   "note": "Final regional NSP 2021 table where published; reference date 31 March 2021."}
            for name, label in LABELS.items()
        }
        fields.update({
            name: {
                "label": label, "unit": "%", "year": YEAR,
                "note": "Final regional table where available; otherwise December 2022 preliminary powiat map.",
            }
            for name, label in SHARE_LABELS.items()
        })
        return {
            "vintage": "NSP 2021 final regional results with December 2022 preliminary map fallback",
            "tables": {"education_powiat": {"level": "powiat", "fields": fields, "rows": rows}},
            "notes": [
                f"Full or partial final education counts cover {len(final_coverage)} of 380 powiats.",
                f"Higher-education share covers {len(share_coverage)} of 380 powiats.",
                "December 2022 preliminary regional maps supply shares where final bulk tables are absent.",
                "Higher education includes doctorate, master, bachelor, engineer, and college diplomas.",
                "Powiat names are matched to official TERYT codes from the GUS 2026 area workbook.",
                "Unsupported category splits remain null; regional tables aggregate categories differently.",
                "The official Warminsko-Mazurskie preliminary page returns HTTP 404 as of 2026-11-26.",
            ],
            "_files": [TERYT_FILE, *dict.fromkeys(used)],
        }

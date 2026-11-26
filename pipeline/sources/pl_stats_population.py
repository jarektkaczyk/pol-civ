"""GUS population, age, vital statistics, migration, area, and density.

The main GUS publication ZIP files contain legacy BIFF8 ``.xls`` workbooks,
despite the 2025 download link describing them as XLSX. This module includes a
small read-only OLE/BIFF reader for the cell types used by those workbooks.
"""

from __future__ import annotations

import io
import re
import struct
import zipfile
from pathlib import Path

from ..core.bdl import is_whole_gmina, read_xlsx
from ..core.source import Source, SourceInfo

POPULATION_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5468/6/40/1/ludnosc.stan_i_struktura_31.12.2025.zip"
)
AREA_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5468/7/23/1/powierzchnia_i_ludnosc_w_przekroju_terytorialnym_2026_2.xlsx"
)
POPULATION_2020_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5468/6/29/1/ludnosc.stan_i_struktura_31.12.2020.zip"
)
POPULATION_2015_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5468/6/19/1/stan_i_struktura_ludnosci_oraz_ruch_naturalny_w_przekroju_terytorialnym_31-12-2015_-_tabele.zip"
)

POPULATION_JUNE_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5468/6/41/1/ludnosc_stan_i_struktura_30.06.2026.zip"
)
POPULATION_JUNE_PAGE = (
    "https://stat.gov.pl/obszary-tematyczne/ludnosc/ludnosc/"
    "ludnosc-stan-i-struktura-oraz-ruch-naturalny-w-przekroju-terytorialnym-w-2026-r-"
    "stan-w-dniu-30-czerwca,6,41.html"
)

POPULATION_FILE = "population-2025-12-31.zip"
POPULATION_JUNE_FILE = "population-2026-06-30.zip"
AREA_FILE = "area-population-2026.xlsx"
POPULATION_2020_FILE = "population-2020-12-31.zip"
POPULATION_2015_FILE = "population-2015-12-31.zip"

DEMOGRAPHY_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5468/40/6/1/sytuacjademograficznapolskido2025.xlsx"
)
DEMOGRAPHY_FILE = "demographic-situation-2025.xlsx"
LIFE_EXPECTANCY_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5470/2/20/1/tablica_b_srednie_dalsze_trwanie_zycia_wedlug_wojewodztw_w_2025_r..xlsx"
)
LIFE_EXPECTANCY_FILE = "life-expectancy-2025-voivodeships.xlsx"
UNIVERSITY_URL = (
    "https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/"
    "5488/8/12/1/szkolnictwo_wyzsze_w_roku_akademickim_2025-2026_tab2_2.xlsx"
)
UNIVERSITY_FILE = "university-students-2025-12-31.xlsx"

_FREE = 0xFFFFFFFF
_END = 0xFFFFFFFE
_VOIVODESHIPS = {
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


def _ascii_name(value: object) -> str:
    """Fold the Polish letters used in voivodeship names for stable matching."""
    letters = "\u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c"
    text = str(value).lower().translate(str.maketrans(letters, "acelnoszz")).strip()
    return re.sub(r"\s*-\s*", "-", text)


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if float(value).is_integer() else float(value)


def _teryt(value: object) -> str | None:
    """Read TERYT7 from numeric BIFF cells or the ``020101 1`` XLSX form."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            code = str(int(value)).zfill(7)
            return code if is_whole_gmina(code) else None
        return None
    digits = "".join(re.findall(r"\d", str(value or "")))
    return digits if is_whole_gmina(digits) else None


def _territorial_code(value: object) -> str | None:
    """Return any seven-digit territorial code, including type 4, 5, or 8."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
        digits = str(int(value)).zfill(7)
    else:
        digits = "".join(re.findall(r"\d", str(value or "")))
    return digits if len(digits) == 7 else None


class _OleBook:
    """Read normal-size streams from an OLE compound document."""

    def __init__(self, data: bytes):
        if data[:8] != bytes.fromhex("d0cf11e0a1b11ae1"):
            raise ValueError("not an OLE compound document")
        self.data = data
        self.sector_size = 1 << struct.unpack_from("<H", data, 30)[0]
        difat = list(struct.unpack_from("<109I", data, 76))
        next_sector = struct.unpack_from("<I", data, 68)[0]
        for _ in range(struct.unpack_from("<I", data, 72)[0]):
            sector = self._sector(next_sector)
            entries = struct.unpack(f"<{self.sector_size // 4}I", sector)
            difat.extend(entries[:-1])
            next_sector = entries[-1]
        fat: list[int] = []
        for sector_id in difat:
            if sector_id not in {_FREE, _END}:
                fat.extend(struct.unpack(f"<{self.sector_size // 4}I", self._sector(sector_id)))
        self.fat = fat
        directory = self._chain(struct.unpack_from("<I", data, 48)[0])
        self.entries: dict[str, tuple[int, int]] = {}
        for offset in range(0, len(directory), 128):
            entry = directory[offset : offset + 128]
            if len(entry) < 128:
                continue
            name_length = struct.unpack_from("<H", entry, 64)[0]
            name = entry[: max(0, name_length - 2)].decode("utf-16le", "replace")
            start = struct.unpack_from("<I", entry, 116)[0]
            size = struct.unpack_from("<Q", entry, 120)[0]
            if name:
                self.entries[name] = (start, size)

    def _sector(self, sector_id: int) -> bytes:
        start = (sector_id + 1) * self.sector_size
        return self.data[start : start + self.sector_size]

    def _chain(self, sector_id: int) -> bytes:
        result = bytearray()
        seen: set[int] = set()
        while sector_id not in {_FREE, _END} and sector_id < len(self.fat) and sector_id not in seen:
            seen.add(sector_id)
            result.extend(self._sector(sector_id))
            sector_id = self.fat[sector_id]
        return bytes(result)

    def stream(self, name: str) -> bytes:
        start, size = self.entries[name]
        return self._chain(start)[:size]


class _SstReader:
    """Read a BIFF shared string table across CONTINUE records."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.chunk = 0
        self.offset = 0

    def take(self, size: int) -> bytes:
        result = bytearray()
        while size:
            if self.offset >= len(self.chunks[self.chunk]):
                self.chunk += 1
                self.offset = 0
            count = min(size, len(self.chunks[self.chunk]) - self.offset)
            result.extend(self.chunks[self.chunk][self.offset : self.offset + count])
            self.offset += count
            size -= count
        return bytes(result)

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def text(self, characters: int, wide: bool) -> str:
        result = []
        while characters:
            if self.offset >= len(self.chunks[self.chunk]):
                self.chunk += 1
                self.offset = 0
                wide = bool(self.u8() & 1)
            width = 2 if wide else 1
            count = min(characters, (len(self.chunks[self.chunk]) - self.offset) // width)
            if not count:
                self.chunk += 1
                self.offset = 0
                wide = bool(self.u8() & 1)
                continue
            raw = self.take(count * width)
            result.append(raw.decode("utf-16le" if wide else "latin-1", "replace"))
            characters -= count
        return "".join(result)


def _shared_strings(records: list[tuple[int, bytes]]) -> list[str]:
    for index, (record_id, data) in enumerate(records):
        if record_id != 0x00FC:
            continue
        chunks = [data]
        cursor = index + 1
        while cursor < len(records) and records[cursor][0] == 0x003C:
            chunks.append(records[cursor][1])
            cursor += 1
        reader = _SstReader(chunks)
        reader.u32()
        unique = reader.u32()
        result = []
        for _ in range(unique):
            length = reader.u16()
            flags = reader.u8()
            rich_runs = reader.u16() if flags & 0x08 else 0
            extension_size = reader.u32() if flags & 0x04 else 0
            result.append(reader.text(length, bool(flags & 0x01)))
            reader.take(rich_runs * 4 + extension_size)
        return result
    return []


def _decode_rk(raw: int) -> int | float:
    if raw & 0x02:
        value: int | float = struct.unpack("<i", struct.pack("<I", raw))[0] >> 2
    else:
        value = struct.unpack("<d", struct.pack("<II", 0, raw & 0xFFFFFFFC))[0]
    if raw & 0x01:
        value /= 100
    return int(value) if float(value).is_integer() else value


def _put_cell(cells: dict[tuple[int, int], object], record_id: int, data: bytes, strings: list[str]) -> None:
    if record_id == 0x00FD:
        row, column, _xf, index = struct.unpack_from("<HHHI", data)
        cells[row, column] = strings[index]
    elif record_id == 0x0203:
        row, column, _xf = struct.unpack_from("<HHH", data)
        cells[row, column] = struct.unpack_from("<d", data, 6)[0]
    elif record_id == 0x027E:
        row, column, _xf, raw = struct.unpack_from("<HHHI", data)
        cells[row, column] = _decode_rk(raw)
    elif record_id == 0x00BD:
        row, first_column = struct.unpack_from("<HH", data)
        last_column = struct.unpack_from("<H", data, len(data) - 2)[0]
        for column in range(first_column, last_column + 1):
            _xf, raw = struct.unpack_from("<HI", data, 4 + (column - first_column) * 6)
            cells[row, column] = _decode_rk(raw)
    elif record_id == 0x0204:
        row, column, _xf, length = struct.unpack_from("<HHHH", data)
        cells[row, column] = data[8 : 8 + length].decode("cp1250", "replace")
    elif record_id == 0x0006:
        row, column, _xf = struct.unpack_from("<HHH", data)
        cached = data[6:14]
        if cached[6:8] != b"\xff\xff":
            cells[row, column] = struct.unpack("<d", cached)[0]


def read_xls(data: bytes) -> list[list[list[object | None]]]:
    """Read values from every BIFF8 worksheet in an in-memory XLS file."""
    ole = _OleBook(data)
    stream_name = "Workbook" if "Workbook" in ole.entries else "Book"
    workbook = ole.stream(stream_name)
    records: list[tuple[int, bytes]] = []
    offset = 0
    while offset + 4 <= len(workbook):
        record_id, length = struct.unpack_from("<HH", workbook, offset)
        offset += 4
        records.append((record_id, workbook[offset : offset + length]))
        offset += length
    strings = _shared_strings(records)
    sheets: list[list[list[object | None]]] = []
    cells: dict[tuple[int, int], object] | None = None
    for record_id, record in records:
        if record_id == 0x0809 and len(record) >= 4 and struct.unpack_from("<H", record, 2)[0] == 0x0010:
            cells = {}
        elif record_id == 0x000A and cells is not None:
            by_row: dict[int, dict[int, object]] = {}
            for (row, column), value in cells.items():
                by_row.setdefault(row, {})[column] = value
            rows = []
            for row_number in sorted(by_row):
                row = [None] * (max(by_row[row_number]) + 1)
                for column, value in by_row[row_number].items():
                    row[column] = value
                rows.append(row)
            sheets.append(rows)
            cells = None
        elif cells is not None:
            _put_cell(cells, record_id, record, strings)
    return sheets


def _xls_member(zip_path: Path, member: str) -> list[list[list[object | None]]]:
    with zipfile.ZipFile(zip_path) as archive:
        return read_xls(archive.read(member))


def _row_value(row: list[object | None], column: int) -> object | None:
    return row[column] if column < len(row) else None


def _best_population_table(zip_path: Path) -> dict[str, int | float]:
    """Find the workbook with the broadest set of whole-gmina population rows."""
    best: dict[str, int | float] = {}
    with zipfile.ZipFile(zip_path) as archive:
        members = sorted(name for name in archive.namelist() if name.lower().endswith(".xls"))
        for member in members:
            found: dict[str, int | float] = {}
            for sheet in read_xls(archive.read(member)):
                for row in sheet:
                    code = _teryt(_row_value(row, 1))
                    value = _number(_row_value(row, 2))
                    if code and value is not None and value > 0:
                        found[code] = value
            if len(found) > len(best):
                best = found
    if len(best) < 2_000:
        raise RuntimeError(f"{zip_path.name}: found only {len(best)} gmina population rows")
    return best


def _on_current_code(records: dict[str, object], code: str) -> object | None:
    """Find a historic gmina after a type-only TERYT change."""
    if code in records:
        return records[code]
    matches = [value for old_code, value in records.items() if old_code[:6] == code[:6]]
    return matches[0] if len(matches) == 1 else None


def _age_key(label: object) -> tuple[int, int | None] | None:
    text = " ".join(str(label or "").replace("\u2013", "-").split()).lower()
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text)
    if match:
        start, end = map(int, match.groups())
        return (start, end) if end - start == 4 else None
    match = re.fullmatch(r"(\d+).*?(?:i wiecej|and more|lat i wiecej)", _ascii_name(text))
    return (int(match.group(1)), None) if match and int(match.group(1)) >= 85 else None


def _ages(zip_path: Path) -> dict[str, dict[str, int | float | None]]:
    rows: dict[str, dict[str, int | float | None]] = {}
    current = None
    for sheet in _xls_member(zip_path, "tabela12.xls"):
        current = None
        for row in sheet:
            territorial_code = _territorial_code(_row_value(row, 1))
            if territorial_code:
                current = territorial_code if is_whole_gmina(territorial_code) else None
                if current:
                    rows.setdefault(current, {})
                continue
            age = _age_key(_row_value(row, 0))
            value = _number(_row_value(row, 2))
            if current and age and value is not None:
                key = f"age_{age[0]}_{age[1]}" if age[1] is not None else f"age_{age[0]}_plus"
                rows[current][key] = value
    for record in rows.values():
        groups = [(key, int(key.split("_")[1]), value) for key, value in record.items()]
        record["age_0_14"] = sum(value for _key, start, value in groups if start < 15)
        record["age_15_64"] = sum(value for _key, start, value in groups if 15 <= start < 65)
        record["age_65_plus"] = sum(value for _key, start, value in groups if start >= 65)
    return rows


def _sex(zip_path: Path) -> dict[str, dict[str, int | float | None]]:
    result = {}
    for sheet in _xls_member(zip_path, "tabela11.xls"):
        for row in sheet:
            code = _teryt(_row_value(row, 1))
            if code:
                result[code] = {
                    "population": _number(_row_value(row, 2)),
                    "male": _number(_row_value(row, 3)),
                    "female": _number(_row_value(row, 4)),
                }
    return result


def _sex_xlsx(zip_path: Path) -> dict[str, dict[str, int | float | None]]:
    """Read population by sex for whole gminas from table 11 (XLSX in the June 2026 edition).

    For an urban-rural gmina (type 3) the urban total, column 5, is the population of its town (type 4).
    """
    with zipfile.ZipFile(zip_path) as archive:
        member = next(name for name in archive.namelist() if name.lower() == "tabela11.xlsx")
        rows = read_xlsx(io.BytesIO(archive.read(member)), 0)
    result = {}
    for row in rows:
        code = _teryt(_row_value(row, 1))
        if code:
            result[code] = {
                "population": _number(_row_value(row, 2)),
                "male": _number(_row_value(row, 3)),
                "female": _number(_row_value(row, 4)),
                "urban": _number(_row_value(row, 5)),
            }
    return result


def _vital(zip_path: Path) -> tuple[dict[str, dict[str, int | float | None]], dict[str, int | float | None]]:
    rows = {}
    country = {}
    for sheet in _xls_member(zip_path, "Tabela_IV.xls"):
        for row in sheet:
            code = _teryt(_row_value(row, 1))
            target = rows.setdefault(code, {}) if code else None
            if str(_row_value(row, 1) or "").strip() == "PL":
                target = country
            if target is None:
                continue
            target.update(
                births=_number(_row_value(row, 4)),
                deaths=_number(_row_value(row, 5)),
                natural_increase=_number(_row_value(row, 7)),
                internal_migration_net=_number(_row_value(row, 10)),
                foreign_migration_net=_number(_row_value(row, 13)),
                total_migration_net=_number(_row_value(row, 14)),
                births_per_1000=_number(_row_value(row, 16)),
                deaths_per_1000=_number(_row_value(row, 17)),
                natural_increase_per_1000=_number(_row_value(row, 18)),
                total_migration_net_per_1000=_number(_row_value(row, 19)),
            )
    return rows, country


def _area(path: Path) -> dict[str, dict[str, int | float | None]]:
    result = {}
    for row in read_xlsx(path, "Tabl. 19"):
        code = _teryt(_row_value(row, 0))
        if code:
            result[code] = {
                "area_ha": _number(_row_value(row, 2)),
                "area_km2": _number(_row_value(row, 3)),
                "population": _number(_row_value(row, 4)),
                "density": _number(_row_value(row, 5)),
            }
    return result


def _voivodeships(zip_path: Path) -> dict[str, dict[str, int | float | None]]:
    result = {}
    for sheet in _xls_member(zip_path, "Tabela_V.xls"):
        for row in sheet:
            code = _VOIVODESHIPS.get(_ascii_name(_row_value(row, 0)))
            if code and code not in result:
                result[code] = {
                    "population": _number(_row_value(row, 1)),
                    "density": _number(_row_value(row, 4)),
                    "preworking_share": _number(_row_value(row, 8)),
                    "working_age_share": _number(_row_value(row, 9)),
                    "postworking_share": _number(_row_value(row, 12)),
                    "age_0_14_share": _number(_row_value(row, 13)),
                    "age_65_plus_share": _number(_row_value(row, 14)),
                    "median_age_male": _number(_row_value(row, 15)),
                    "median_age_female": _number(_row_value(row, 16)),
                }
    return result


def _demographic_rates(path: Path) -> dict[str, dict[str, int | float | None]]:
    """Read the 2025 replacement rates from the total voivodeship block."""
    result = {}
    for row in read_xlsx(path, "Tablica 2B"):
        code = _VOIVODESHIPS.get(_ascii_name(_row_value(row, 0)))
        if code and code not in result:
            result[code] = {
                "total_fertility_rate": _number(_row_value(row, 10)),
                "life_expectancy_male": _number(_row_value(row, 8)),
                "life_expectancy_female": _number(_row_value(row, 9)),
            }
    return result


def _life_expectancy(path: Path) -> dict[str, dict[str, int | float | None]]:
    """Read life expectancy at birth from the total voivodeship block."""
    result = {}
    for row in read_xlsx(path, "Tabl. B"):
        code = str(_row_value(row, 0) or "").zfill(2)
        if code in _VOIVODESHIPS.values() and code not in result:
            result[code] = {
                "life_expectancy_male": _number(_row_value(row, 2)),
                "life_expectancy_female": _number(_row_value(row, 7)),
            }
    return result


def _university_city_lookup(area_path: Path) -> dict[tuple[str, str], str | None]:
    """Map a voivodeship and town name to its whole-gmina TERYT code."""
    candidates: dict[tuple[str, str], list[str]] = {}
    for row in read_xlsx(area_path, "Tabl. 19"):
        raw_code = _territorial_code(_row_value(row, 0))
        if not raw_code or raw_code[-1] not in {"1", "3"}:
            continue
        name = " ".join(str(_row_value(row, 1) or "").split())
        if name.lower().startswith("mst "):
            name = name[4:]
        key = (raw_code[:2], _ascii_name(name))
        candidates.setdefault(key, []).append(raw_code)
    return {key: values[0] if len(values) == 1 else None for key, values in candidates.items()}


def _university_students(path: Path, area_path: Path) -> tuple[dict, dict]:
    """Aggregate official institution totals to voivodeships and TERYT-keyed cities."""
    lookup = _university_city_lookup(area_path)
    voivodeships = {}
    cities: dict[str, dict[str, int | float]] = {}
    for row in read_xlsx(path, "Og\u00f3\u0142em"):
        if len(row) < 10 or str(_row_value(row, 7) or "").strip() != "a":
            continue
        voiv_code = _VOIVODESHIPS.get(_ascii_name(_row_value(row, 0)))
        institution = " ".join(str(_row_value(row, 1) or "").split())
        city = " ".join(str(_row_value(row, 2) or "").split())
        dimensions = [_ascii_name(_row_value(row, index)) for index in range(3, 7)]
        if not voiv_code or dimensions != ["ogolem"] * 4:
            continue
        students = _number(_row_value(row, 8))
        graduates = _number(_row_value(row, 9))
        if _ascii_name(institution) == "ogolem" and _ascii_name(city) == "ogolem":
            voivodeships[voiv_code] = {"students": students, "graduates": graduates}
            continue
        code = lookup.get((voiv_code, _ascii_name(city)))
        if code is None or students is None:
            continue
        target = cities.setdefault(code, {"students": 0, "graduates": None})
        target["students"] += students
        if graduates is not None:
            target["graduates"] = (target["graduates"] or 0) + graduates
    return voivodeships, cities


def _field(label: str, unit: str, year: int, note: str) -> dict:
    return {"label": label, "unit": unit, "year": year, "note": note}


class PlStatsPopulation(Source):
    info = SourceInfo(
        id="pl_stats_population",
        title="Population, demography, life expectancy, and university students",
        publisher="Statistics Poland (GUS)",
        homepage=(
            "https://stat.gov.pl/obszary-tematyczne/ludnosc/ludnosc/"
            "ludnosc-stan-i-struktura-oraz-ruch-naturalny-w-przekroju-terytorialnym-w-2025-r-"
            "stan-w-dniu-31-grudnia,6,40.html"
        ),
        license="Creative Commons Attribution 4.0",
        description=(
            "Official GUS bulk tables for gmina population, vital statistics, migration, area and density, "
            "plus voivodeship fertility and life expectancy and university students by region and city."
        ),
        used_for=[
            "Population and growth", "City View age citizens", "People advisor", "Population lenses",
            "Education lens",
        ],
    )

    def fetch(self, force: bool = False) -> None:
        for url, filename in (
            (POPULATION_URL, POPULATION_FILE),
            (POPULATION_JUNE_URL, POPULATION_JUNE_FILE),
            (AREA_URL, AREA_FILE),
            (POPULATION_2020_URL, POPULATION_2020_FILE),
            (POPULATION_2015_URL, POPULATION_2015_FILE),
            (DEMOGRAPHY_URL, DEMOGRAPHY_FILE),
            (LIFE_EXPECTANCY_URL, LIFE_EXPECTANCY_FILE),
            (UNIVERSITY_URL, UNIVERSITY_FILE),
        ):
            path = self.download(url, filename, force=force, expect_binary=True)
            if filename.endswith(".zip") and not zipfile.is_zipfile(path):
                self.discard(filename)
                raise RuntimeError(f"{url} did not return a ZIP file")
            if filename.endswith(".xlsx") and not zipfile.is_zipfile(path):
                self.discard(filename)
                raise RuntimeError(f"{url} did not return an XLSX file")

    def process(self) -> dict:
        current_zip = self.raw_dir / POPULATION_FILE
        june_zip = self.raw_dir / POPULATION_JUNE_FILE
        area = _area(self.raw_dir / AREA_FILE)
        june_sex = _sex_xlsx(june_zip)
        june_ages = _ages(june_zip)
        vital, country_vital = _vital(current_zip)
        population_2020 = _best_population_table(self.raw_dir / POPULATION_2020_FILE)
        population_2015 = _best_population_table(self.raw_dir / POPULATION_2015_FILE)
        university_voivodeships, university_cities = _university_students(
            self.raw_dir / UNIVERSITY_FILE, self.raw_dir / AREA_FILE
        )
        gmina_rows = {}
        for code, base in area.items():
            sex = dict(june_sex.get(code) or {})
            sex.pop("urban", None)
            record = {
                **base,
                "population": None,
                "male": None,
                "female": None,
                **sex,
                **(june_ages.get(code) or {}),
            }
            # Table 19 population and density are the 31 December 2025 balance.
            record["population_2025"] = base.get("population")
            record["population_2015"] = _on_current_code(population_2015, code)
            record["population_2020"] = _on_current_code(population_2020, code)
            gmina_rows[code] = record
        missing = [code for code, row in gmina_rows.items() if row["population"] is None]
        if len(missing) > 0:
            raise RuntimeError(f"{len(missing)} gminas have no 30 June 2026 population: {missing[:5]}")
        current_vital = {code: _on_current_code(vital, code) or {} for code in area}
        age_fields = {}
        for start in range(0, 85, 5):
            age_fields[f"age_{start}_{start + 4}"] = _field(
                f"Population age {start}-{start + 4}", "persons", 2026, "30 June 2026, GUS table 12"
            )
        age_fields["age_85_plus"] = _field("Population age 85+", "persons", 2026, "30 June 2026, GUS table 12")
        population_fields = {
            "population": _field("Population", "persons", 2026, "30 June 2026, GUS half-year balance table 11"),
            "male": _field("Male population", "persons", 2026, "30 June 2026, GUS table 11"),
            "female": _field("Female population", "persons", 2026, "30 June 2026, GUS table 11"),
            "age_0_14": _field(
                "Population age 0-14", "persons", 2026, "30 June 2026, sum of GUS table 12 five-year groups"
            ),
            "age_15_64": _field(
                "Population age 15-64", "persons", 2026, "30 June 2026, sum of GUS table 12 five-year groups"
            ),
            "age_65_plus": _field(
                "Population age 65+", "persons", 2026, "30 June 2026, sum of GUS table 12 five-year groups"
            ),
            "population_2025": _field(
                "Population", "persons", 2025, "31 December 2025, GUS area and population table 19"
            ),
            "area_ha": _field("Area", "ha", 2026, "Area on 1 January 2026, GUS table 19"),
            "area_km2": _field("Area", "km2", 2026, "Area on 1 January 2026, GUS table 19"),
            "density": _field(
                "Population density", "persons per km2", 2025, "31 December 2025, GUS table 19"
            ),
            "population_2015": _field("Population", "persons", 2015, "GUS 2015 bulk publication"),
            "population_2020": _field("Population", "persons", 2020, "GUS 2020 bulk publication"),
            **age_fields,
        }
        vital_fields = {
            key: _field(label, unit, 2025, "GUS review table IV")
            for key, label, unit in (
                ("births", "Live births", "persons"),
                ("deaths", "Deaths", "persons"),
                ("natural_increase", "Natural increase", "persons"),
                ("internal_migration_net", "Net internal migration", "persons"),
                ("foreign_migration_net", "Net foreign migration", "persons"),
                ("total_migration_net", "Total net migration", "persons"),
                ("births_per_1000", "Live births per 1000", "per 1000"),
                ("deaths_per_1000", "Deaths per 1000", "per 1000"),
                ("natural_increase_per_1000", "Natural increase per 1000", "per 1000"),
                ("total_migration_net_per_1000", "Total net migration per 1000", "per 1000"),
            )
        }
        voivodeship_fields = {
            key: _field(label, unit, 2025, "GUS review table V")
            for key, label, unit in (
                ("population", "Population", "persons"),
                ("density", "Population density", "persons per km2"),
                ("preworking_share", "Pre-working-age population", "%"),
                ("working_age_share", "Working-age population", "%"),
                ("postworking_share", "Post-working-age population", "%"),
                ("age_0_14_share", "Population age 0-14", "%"),
                ("age_65_plus_share", "Population age 65+", "%"),
                ("median_age_male", "Median age, men", "years"),
                ("median_age_female", "Median age, women", "years"),
            )
        }
        demographic_rows = _voivodeships(current_zip)
        for code, values in _demographic_rates(self.raw_dir / DEMOGRAPHY_FILE).items():
            demographic_rows.setdefault(code, {}).update(values)
        for code, values in _life_expectancy(self.raw_dir / LIFE_EXPECTANCY_FILE).items():
            demographic_rows.setdefault(code, {}).update(values)
        voivodeship_fields.update({
            "total_fertility_rate": _field(
                "Total fertility rate", "children per woman", 2025,
                "GUS Sytuacja demograficzna Polski do 2025 r., table 2B",
            ),
            "life_expectancy_male": _field(
                "Life expectancy at birth, men", "years", 2025,
                "GUS Trwanie zycia w 2025 r., table B",
            ),
            "life_expectancy_female": _field(
                "Life expectancy at birth, women", "years", 2025,
                "GUS Trwanie zycia w 2025 r., table B",
            ),
        })
        university_fields = {
            "students": _field(
                "University students", "persons", 2025,
                "GUS higher education table, state on 31 December 2025; a person is counted once per course.",
            ),
            "graduates": _field(
                "University graduates", "persons", 2025,
                "GUS higher education table; diplomas completed during 2025.",
            ),
        }
        national_population = sum(row["population"] for row in gmina_rows.values() if row["population"] is not None)
        national_population_2025 = sum(
            row["population_2025"] for row in gmina_rows.values() if row["population_2025"] is not None
        )
        return {
            "vintage": (
                "GUS population 30 June 2026; population 31 December 2025 for change since 2015, density, "
                "births, deaths and migration; demographic rates and life expectancy 2025; "
                "university students 31 December 2025; territorial division 1 January 2026"
            ),
            "tables": {
                "population": {"level": "gmina", "fields": population_fields, "rows": gmina_rows},
                "vital_migration": {"level": "gmina", "fields": vital_fields, "rows": current_vital},
                "demographic_indicators": {
                    "level": "voivodeship",
                    "fields": voivodeship_fields,
                    "rows": demographic_rows,
                },
                "university_students_voivodeship": {
                    "level": "voivodeship", "fields": university_fields, "rows": university_voivodeships,
                },
                "university_students_city": {
                    "level": "gmina", "fields": university_fields, "rows": university_cities,
                },
                "headline": {
                    "level": "country",
                    "fields": {
                        "population": _field(
                            "Population", "persons", 2026, "30 June 2026, sum of whole gminas; GUS table 11"
                        ),
                        "population_2025": _field(
                            "Population", "persons", 2025, "31 December 2025, sum of whole gminas; GUS table 19"
                        ),
                        **vital_fields,
                    },
                    "rows": {"PL": {
                        "population": national_population,
                        "population_2025": national_population_2025,
                        **country_vital,
                    }},
                },
            },
            "notes": [
                "Population, sex and five-year age groups are the GUS half-year balance at 30 June 2026 "
                "(" + POPULATION_JUNE_PAGE + ").",
                "population_2025 and density are the balance at 31 December 2025, recalculated to the "
                "1 January 2026 division; change since 2015 compares 31 December with 31 December.",
                "Births, deaths and migration are full-year 2025 flows; the June 2026 edition has only half-year flows.",
                "The 2026 territorial division contains 2,479 whole gminas; the blueprint's provisional count is 2,477.",
                "A gmina whose type digit changed is matched across vintages by its unchanged first six TERYT digits.",
                "Population in 2015 and 2020 is null for 1207132 and 2002162 because those gminas were created in 2025.",
                "GUS publishes median age, fertility and life expectancy at voivodeship level.",
                "The bulk table publishes internal and foreign migration net counts, but only total migration per 1000.",
                "University city rows sum institution totals and use whole-gmina TERYT codes from the area workbook.",
                "University students are counted once for every course studied, as specified by GUS.",
            ],
            "_files": [
                POPULATION_JUNE_FILE, POPULATION_FILE, AREA_FILE, POPULATION_2020_FILE, POPULATION_2015_FILE,
                DEMOGRAPHY_FILE, LIFE_EXPECTANCY_FILE, UNIVERSITY_FILE,
            ],
        }

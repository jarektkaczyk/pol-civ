"""Helpers for Statistics Poland BDL API data and GUS XLSX workbooks.

BDL uses a 12-digit statistical unit id. Administrative TERYT codes are
embedded in that id, but their digits are not contiguous. This module also
keeps BDL pagination consistent across the Polish statistics sources.
"""

from __future__ import annotations

import json
import math
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

BDL_BASE = "https://bdl.stat.gov.pl/api/v1"
PAGE_SIZE = 100
REQUEST_INTERVAL = 0.22
MAX_REQUESTS_PER_RUN = 90
_request_count = 0

# BDL attribute ids with no qualification in the publisher's attribute table.
# Missing, confidential, provisional, low-reliability, break, and incomplete
# values stay null because the interim contract has no observation flags.
# Attribute 0 is a published zero with no qualifier. See the BDL attributes dictionary.
UNQUALIFIED_ATTRIBUTES = {0, 1, 7, 94, 97}

_CELL_REF = re.compile(r"([A-Z]+)([0-9]+)$")
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def teryt_from_bdl(unit_id: str, level: int) -> str:
    """Return the administrative code embedded in a 12-digit BDL unit id.

    Supported levels are voivodeship (2), powiat (5), and gmina (6). The
    caller must pass the level because a BDL id can be ambiguous at NUTS
    levels when a component ends in zero.
    """
    unit_id = str(unit_id)
    if len(unit_id) != 12 or not unit_id.isdigit():
        raise ValueError(f"invalid BDL unit id {unit_id!r}")
    if level == 2:
        code = unit_id[2:4]
    elif level == 5:
        code = unit_id[2:4] + unit_id[7:9]
    elif level == 6:
        code = unit_id[2:4] + unit_id[7:12]
    else:
        raise ValueError(f"BDL level {level} has no administrative TERYT conversion")
    if not code.strip("0"):
        raise ValueError(f"BDL unit id {unit_id!r} has no TERYT code at level {level}")
    return code


def is_whole_gmina(code: str) -> bool:
    """True for a whole urban, rural, or urban-rural gmina TERYT7 code."""
    code = str(code)
    return len(code) == 7 and code.isdigit() and code[-1] in "123"


def bdl_url(endpoint: str, params: dict | None = None) -> str:
    """Build a stable BDL API URL with JSON output."""
    query = {**(params or {})}
    query.setdefault("format", "json")
    endpoint = endpoint.lstrip("/")
    return f"{BDL_BASE}/{endpoint}?{urlencode(sorted(query.items()), doseq=True)}"


def download_pages(source, endpoint: str, rel_dir: str, params: dict | None = None, *, force: bool = False) -> list[str]:
    """Download every page of a BDL endpoint through ``Source.download``.

    The first response supplies ``totalRecords`` and ``pageSize``. Files use
    zero-based page numbers, matching the BDL API. The return value contains
    raw paths relative to the source directory for interim provenance.
    """
    base_params = {**(params or {}), "page-size": PAGE_SIZE}
    files: list[str] = []

    def get(page: int) -> tuple[str, dict]:
        global _request_count
        rel = f"{rel_dir}/page-{page:03d}.json"
        existed = (source.raw_dir / rel).exists() and not force
        if not existed and _request_count >= MAX_REQUESTS_PER_RUN:
            raise RuntimeError(
                f"BDL request limit reached: stopped before request {MAX_REQUESTS_PER_RUN + 1}"
            )
        if not existed:
            _request_count += 1
        path = source.download(bdl_url(endpoint, {**base_params, "page": page}), rel, force=force)
        if not existed:
            time.sleep(REQUEST_INTERVAL)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            source.discard(rel)
            raise RuntimeError(f"{source.id}/{rel}: invalid BDL JSON") from exc
        files.append(rel)
        return rel, payload

    _, first = get(0)
    total = first.get("totalRecords")
    page_size = first.get("pageSize") or PAGE_SIZE
    if not isinstance(total, int) or total < 0 or not isinstance(page_size, int) or page_size < 1:
        raise RuntimeError(f"{source.id}/{rel_dir}: BDL response has invalid pagination")
    for page in range(1, math.ceil(total / page_size)):
        get(page)
    return files


def load_pages(raw_dir: Path, rel_dir: str) -> list[dict]:
    """Load and join the ``results`` arrays from cached BDL pages."""
    paths = sorted((Path(raw_dir) / rel_dir).glob("page-*.json"))
    if not paths:
        raise FileNotFoundError(f"no cached BDL pages in {Path(raw_dir) / rel_dir}")
    rows: list[dict] = []
    expected_total = None
    for index, path in enumerate(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("page") not in (None, index):
            raise RuntimeError(f"{path}: expected BDL page {index}, got {payload.get('page')!r}")
        if expected_total is None:
            expected_total = payload.get("totalRecords")
        results = payload.get("results")
        if not isinstance(results, list):
            raise RuntimeError(f"{path}: BDL response has no results list")
        rows.extend(results)
    if isinstance(expected_total, int) and len(rows) != expected_total:
        raise RuntimeError(f"{Path(raw_dir) / rel_dir}: cached {len(rows)} of {expected_total} BDL records")
    return rows


def value_for_year(record: dict, year: int | str) -> int | float | None:
    """Return one BDL unit value for ``year``, or None when it is absent."""
    wanted = str(year)
    for item in record.get("values") or []:
        if str(item.get("year")) == wanted:
            attr_id = item.get("attrId")
            if attr_id is not None and attr_id not in UNQUALIFIED_ATTRIBUTES:
                return None
            value = item.get("value")
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return None


def latest_value(record: dict) -> tuple[int, int | float] | None:
    """Return the newest numeric ``(year, value)`` pair in a BDL unit row."""
    found = []
    for item in record.get("values") or []:
        year, value = item.get("year"), item.get("value")
        attr_id = item.get("attrId")
        unqualified = attr_id is None or attr_id in UNQUALIFIED_ATTRIBUTES
        if unqualified and str(year).isdigit() and isinstance(value, (int, float)) and not isinstance(value, bool):
            found.append((int(year), value))
    return max(found, default=None)


def _column_index(cell_ref: str) -> int:
    match = _CELL_REF.fullmatch(cell_ref)
    if not match:
        raise ValueError(f"invalid XLSX cell reference {cell_ref!r}")
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - 64
    return result - 1


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    ns = {"x": _MAIN_NS}
    return ["".join(node.text or "" for node in item.findall(".//x:t", ns)) for item in root.findall("x:si", ns)]


def _sheet_paths(book: zipfile.ZipFile) -> list[tuple[str, str]]:
    ns = {"x": _MAIN_NS, "r": _DOC_REL_NS}
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall(f"{{{_PKG_REL_NS}}}Relationship")}
    result = []
    for sheet in workbook.findall("x:sheets/x:sheet", ns):
        rel_id = sheet.attrib[f"{{{_DOC_REL_NS}}}id"]
        target = targets[rel_id].lstrip("/")
        path = target if target.startswith("xl/") else f"xl/{target}"
        result.append((sheet.attrib["name"], path))
    return result


def read_xlsx(path: str | Path, sheet: int | str = 0) -> list[list[object | None]]:
    """Read cell values from one XLSX worksheet using the standard library.

    This intentionally reads values, not formatting. It supports shared and
    inline strings, numeric cells, booleans, and cached formula results.
    """
    with zipfile.ZipFile(path) as book:
        sheets = _sheet_paths(book)
        if isinstance(sheet, str):
            matches = [item for item in sheets if item[0] == sheet]
            if not matches:
                raise KeyError(f"worksheet {sheet!r} not found")
            sheet_path = matches[0][1]
        else:
            try:
                sheet_path = sheets[sheet][1]
            except IndexError as exc:
                raise IndexError(f"worksheet index {sheet} out of range") from exc
        shared = _shared_strings(book)
        root = ET.fromstring(book.read(sheet_path))

    ns = {"x": _MAIN_NS}
    rows: list[list[object | None]] = []
    for row in root.findall("x:sheetData/x:row", ns):
        values: list[object | None] = []
        for cell in row.findall("x:c", ns):
            index = _column_index(cell.attrib["r"])
            while len(values) <= index:
                values.append(None)
            cell_type = cell.attrib.get("t")
            value_node = cell.find("x:v", ns)
            raw = value_node.text if value_node is not None else None
            if cell_type == "inlineStr":
                value: object | None = "".join(node.text or "" for node in cell.findall(".//x:t", ns))
            elif raw is None:
                value = None
            elif cell_type == "s":
                value = shared[int(raw)]
            elif cell_type in {"str", "e"}:
                value = raw
            elif cell_type == "b":
                value = raw == "1"
            else:
                number = float(raw)
                value = int(number) if number.is_integer() else number
            values[index] = value
        rows.append(values)
    return rows

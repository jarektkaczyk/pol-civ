"""Build the gmina-level area covered by Poland's September 2024 flood emergency."""

from __future__ import annotations

import json
from pathlib import Path

from ..core.store import load_interim, load_interim_payload, write_web

REQUIRES = ["_world", "pl_soc_disasters"]
PRODUCES = ["disasters.json"]

RULE = ("Every gmina named by the Council of Ministers' regulation on the state of natural disaster of 16 September "
        "2024 and its amendments. A named powiat covers all its gminas. Malomice is partial because the act named "
        "only the town. The area is an administrative declaration, not a measure of flood depth or damage.")


def _iso_date(value) -> str | None:
    if value is None:
        return None
    text = str(int(value))
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 else None


def county_declarations(source: dict, counties: list[str]) -> dict[str, dict]:
    """Return a declaration count for each gmina, for shared lens and county builders."""
    rows = ((source.get("tables") or {}).get("flood_2024_gmina") or {}).get("rows") or {}
    out = {}
    for geoid in counties:
        row = rows.get(geoid)
        declared = 1 if row and row.get("declared_2024") == 1 else 0
        out[geoid] = {"total": declared, "flood": declared,
                      "last_date": _iso_date(row.get("declared_2024_date")) if row else None}
    return out


def build() -> None:
    world = load_interim("_world")
    payload = load_interim_payload("pl_soc_disasters")
    data = payload["data"]
    tables = data.get("tables") or {}
    source_gminas = (tables.get("flood_2024_gmina") or {}).get("rows") or {}
    source_powiats = (tables.get("flood_2024_powiat") or {}).get("rows") or {}
    columns = ["geoid", "declared", "partial", "date"]
    rows = []
    for geoid in world["counties"]:
        source = source_gminas.get(geoid)
        rows.append([geoid, 1 if source else 0, source.get("declared_2024_partial", 0) if source else 0,
                     _iso_date(source.get("declared_2024_date")) if source else None])
    powiats = [[code, 1, _iso_date(row.get("declared_2024_date"))]
               for code, row in sorted(source_powiats.items())]
    county_codes = world["counties"]
    declared = set(source_gminas)
    cells = [1 if county_index >= 0 and county_codes[county_index] in declared else
             0 if county_index >= 0 else None for county_index in world["county"]]
    doc = {
        "version": 1, "vintage": payload.get("vintage"), "sources": ["pl_soc_disasters"],
        "flood_2024": {
            "rule": RULE, "window": ["2024-09-16", "2024-09-25"],
            "gminas": {"columns": columns, "rows": rows},
            "powiats": {"columns": ["teryt", "declared", "date"], "rows": powiats},
            "cells": cells,
            "summary": {"gminas": len(source_gminas), "powiats": len(source_powiats),
                        "partial_gminas": sum(row.get("declared_2024_partial") == 1
                                              for row in source_gminas.values())},
        },
    }
    write_web("disasters.json", doc)
    print(f"    2024 flood emergency: {len(source_gminas)} gminas in {len(source_powiats)} powiats")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "disasters.json"
    if not path.exists():
        return [("NOTE", "disasters.json not built (optional)")]
    doc = json.loads(path.read_text())
    flood = doc.get("flood_2024") or {}
    problems = []
    columns = (flood.get("gminas") or {}).get("columns")
    rows = (flood.get("gminas") or {}).get("rows")
    if columns != ["geoid", "declared", "partial", "date"] or not isinstance(rows, list):
        problems.append("gmina columns or rows are missing")
        rows = []
    declared = [row for row in rows if len(row) == 4 and row[1] == 1]
    if len(declared) != 198:
        problems.append(f"expected 198 declared gminas, found {len(declared)}")
    if sum(row[2] == 1 for row in declared) != 1:
        problems.append("expected one partial gmina")
    powiats = (flood.get("powiats") or {}).get("rows") or []
    if len(powiats) != 29:
        problems.append(f"expected 29 powiats, found {len(powiats)}")
    cells = flood.get("cells")
    if not isinstance(cells, list) or any(value not in (None, 0, 1) for value in cells):
        problems.append("cells must contain only null, 0 or 1")
    out = [("FAIL", f"disasters.json: {problem}") for problem in problems]
    if not problems:
        out.append(("PASS", "disasters.json: 2024 flood emergency covers 198 gminas in 29 powiats"))
    size = path.stat().st_size
    out.append(("PASS" if size < 600_000 else "WARN", f"disasters.json {size / 1e3:.0f} kB (lazy budget ~600 kB)"))
    return out

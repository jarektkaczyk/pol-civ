"""Internal migration between voivodeships, origin by destination, every year since 1995 (GUS BDL P1358).

BDL subject P1358 "Migracje na pobyt staly miedzywojewodzkie wg kierunku" has one variable per voivodeship
(ids 3798-3813, named after the voivodeship) plus 79243 "ogolem". The data is read at unit level 2
(voivodeships). The variable is the destination and the unit is the origin: the column sums equal the BDL
registrations from other voivodeships (checked for Mazowieckie 2024: 21,467). The diagonal (a voivodeship to
itself) is published as 0 with attribute 0 and is left out: moves inside one voivodeship are not in this table.

One BDL request per variable returns every year (17 requests in all, plus 1 for the variable list).
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from ..core.bdl import UNQUALIFIED_ATTRIBUTES, bdl_url, teryt_from_bdl
from ..core.source import Source, SourceInfo
from .pl_soc_common import bdl_download

SUBJECT = "P1358"
TOTAL_VAR = "79243"
PAGE = "https://bdl.stat.gov.pl/bdl/dane/podgrup/temat/3/" + SUBJECT
VARS_FILE = "variables.json"


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c)).replace(" ", "")


def parse_variables(doc: dict) -> dict[str, str]:
    """{variable id: voivodeship name (lower case, as BDL writes it)} without the total."""
    return {str(v["id"]): v.get("n1") for v in doc.get("results") or [] if str(v["id"]) != TOTAL_VAR}


def value(item: dict) -> int | float | None:
    """A BDL value, or None when absent or qualified (any attribute other than a plain published value)."""
    v = item.get("val", item.get("value"))
    if item.get("attrId") not in UNQUALIFIED_ATTRIBUTES and item.get("attrId") is not None:
        return None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse_matrix(var_docs: dict[str, dict], var_names: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """{year: {(origin, destination): persons}} and {code: name} from the per-variable BDL answers."""
    units: dict[str, str] = {}
    for doc in var_docs.values():
        for r in doc.get("results") or []:
            units[teryt_from_bdl(r["id"], 2)] = r["name"]
    by_name = {_fold(n): c for c, n in units.items()}
    matrix: dict[int, dict[tuple[str, str], int | float]] = {}
    for var, doc in var_docs.items():
        dest = by_name.get(_fold(var_names[var]))
        if dest is None:
            raise RuntimeError(f"BDL variable {var} ({var_names[var]!r}) matches no voivodeship")
        for r in doc.get("results") or []:
            orig = teryt_from_bdl(r["id"], 2)
            if orig == dest:
                continue
            for item in r.get("values") or []:
                v = value(item)
                if v is not None:
                    matrix.setdefault(int(item["year"]), {})[(orig, dest)] = v
    return matrix, units


def balances(cells: dict[tuple[str, str], int | float]) -> dict[str, dict]:
    """{code: {in, out, net}} for one year."""
    out: dict[str, dict] = {}
    for (a, b), v in cells.items():
        out.setdefault(a, {"in": 0, "out": 0})["out"] += v
        out.setdefault(b, {"in": 0, "out": 0})["in"] += v
    for row in out.values():
        row["net"] = row["in"] - row["out"]
    return out


class PolandMigrationOD(Source):
    info = SourceInfo(
        id="pl_migration_od",
        title="Internal migration between voivodeships by origin and destination, every year since 1995",
        publisher="Statistics Poland (GUS), Local Data Bank (BDL) API",
        homepage=PAGE,
        license="GUS CC BY 4.0 (reuse with the source named)",
        description="Moves of permanent residence between the 16 voivodeships, as a 16 x 16 origin-destination "
                    "matrix for every year, BDL subject P1358.",
        used_for=["Migration map layer"],
    )

    def fetch(self, force: bool = False) -> None:
        url = bdl_url("variables", {"subject-id": SUBJECT, "page-size": 100})
        if force:
            self.discard(VARS_FILE)
        doc = json.loads(Path(bdl_download(self, url, VARS_FILE)).read_text(encoding="utf-8"))
        ids = sorted(parse_variables(doc)) + [TOTAL_VAR]
        if len(ids) != 17:
            raise RuntimeError(f"BDL {SUBJECT}: expected 16 voivodeship variables and a total, got {ids}")
        for var in ids:
            rel = f"var_{var}.json"
            if force:
                self.discard(rel)
            bdl_download(self, bdl_url(f"data/by-variable/{var}", {"unit-level": 2, "page-size": 100}), rel)

    def process(self) -> dict:
        names = parse_variables(json.loads((self.raw_dir / VARS_FILE).read_text(encoding="utf-8")))
        docs = {v: json.loads((self.raw_dir / f"var_{v}.json").read_text(encoding="utf-8")) for v in names}
        matrix, units = parse_matrix(docs, names)
        years = sorted(matrix)
        if len(units) != 16 or any(len(matrix[y]) < 200 for y in years):
            raise RuntimeError(f"unexpected matrix: {len(units)} units, sizes {[len(matrix[y]) for y in years]}")
        # Check: the BDL total per origin equals the sum of its row.
        total = json.loads((self.raw_dir / f"var_{TOTAL_VAR}.json").read_text(encoding="utf-8"))
        notes = []
        for r in total.get("results") or []:
            orig = teryt_from_bdl(r["id"], 2)
            for item in r.get("values") or []:
                v, y = value(item), int(item["year"])
                got = sum(val for (a, _), val in matrix.get(y, {}).items() if a == orig)
                if v is not None and y in matrix and abs(v - got) > 0:
                    notes.append(f"{y} {orig}: BDL total {v} differs from the row sum {got}")
        latest = years[-1]
        bal = balances(matrix[latest])
        note = f"{latest}, moves of permanent residence between voivodeships (GUS BDL P1358)."
        flows = [{"from": a, "to": b, "level": "voivodeship", "value": v, "unit": "persons", "year": y}
                 for y in years for (a, b), v in sorted(matrix[y].items())]
        return {
            "vintage": f"GUS BDL P1358, years {years[0]} to {latest}",
            "years": [years[0], latest],
            "names": {c: units[c] for c in sorted(units)},
            "tables": {
                "migration_voivodeship": {
                    "level": "voivodeship",
                    "fields": {
                        "migration_in": {"label": "Arrivals from other voivodeships", "unit": "persons",
                                         "year": latest, "note": note},
                        "migration_out": {"label": "Departures to other voivodeships", "unit": "persons",
                                          "year": latest, "note": note},
                        "migration_net": {"label": "Net internal migration", "unit": "persons", "year": latest,
                                          "note": note + " Arrivals minus departures."},
                    },
                    "rows": {c: {"migration_in": b["in"], "migration_out": b["out"], "migration_net": b["net"]}
                             for c, b in sorted(bal.items())},
                }
            },
            "flows": flows,
            "notes": [
                "Variable = destination voivodeship, unit = origin voivodeship (column sums match BDL registrations "
                "from other voivodeships).",
                "Permanent residence only (registered moves); temporary stays and moves abroad are not in the matrix.",
                "The diagonal (moves inside one voivodeship) is not part of this table and is left out.",
                *(notes[:20] or [f"Row sums match the BDL total (variable {TOTAL_VAR}) for every origin and year."]),
            ],
            "_files": [VARS_FILE, *[f"var_{v}.json" for v in sorted(names)], f"var_{TOTAL_VAR}.json"],
        }

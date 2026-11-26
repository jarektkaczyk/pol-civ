"""Commuting to work between gminas: NSP 2021 census matrix of employment-related flows (GUS).

"Macierz przeplywow ludnosci zwiazanych z zatrudnieniem - NSP 2021" (xlsx, 31 January 2024): wage employees
(pracownicy najemni) who work in another gmina than the one they live in, on 31 March 2021. GUS leaves out flows of
fewer than 3 people (the matrix sums to 4.96 million; the per-gmina totals, which include them, to 5.18 million).
No newer edition exists: GUS publishes the matrix after each census (2006, 2011, 2016, 2021).

GUS splits each urban-rural gmina (type 3) into its town (type 4) and its rural area (type 5). This source adds
the parts into the whole gmina (type 3) and drops the flows between the two parts of one gmina.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.source import Source, SourceInfo
from ._pl_xlsx import read_xlsx

URL = ("https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/6536/9/2/1/"
       "macierz_przeplywow_ludnosci_zwiazanych_z_zatrudnieniem.xlsx")
FILE = "nsp2021_commuting_matrix.xlsx"
PAGE = ("https://stat.gov.pl/spisy-powszechne/nsp-2021/nsp-2021-wyniki-ostateczne/"
        "macierz-przeplywow-ludnosci-zwiazanych-z-zatrudnieniem-nsp-2021,9,2.html")
SHEETS = ("Macierz przepływów", "Wyjeżdżający z gmin", "Przyjeżdżający do gmin")
NOTE = "31 March 2021 (NSP 2021): wage employees who work in another gmina than they live in."


def gmina_code(code: str) -> str:
    """TERYT7 of the whole gmina: a town part (4) or rural part (5) of an urban-rural gmina -> type 3."""
    return code[:6] + "3" if code[6] in "45" else code


def _code(value) -> str | None:
    s = str(value or "").strip()
    return s if re.fullmatch(r"\d{7}", s) else None


def parse_matrix(rows: list[list]) -> dict[tuple[str, str], int]:
    """{(home gmina, work gmina): commuters} on whole-gmina codes, without flows inside one gmina."""
    out: dict[tuple[str, str], int] = {}
    for r in rows:
        if len(r) < 5:
            continue
        a, b, v = _code(r[0]), _code(r[2]), r[4]
        if not a or not b or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        a, b = gmina_code(a), gmina_code(b)
        if a != b:
            out[(a, b)] = out.get((a, b), 0) + int(v)
    return out


def internal_flows(rows: list[list]) -> dict[str, int]:
    """{whole gmina: commuters between its town part and its rural part} (both directions)."""
    out: dict[str, int] = {}
    for r in rows:
        if len(r) < 5:
            continue
        a, b, v = _code(r[0]), _code(r[2]), r[4]
        if a and b and a != b and gmina_code(a) == gmina_code(b) and isinstance(v, (int, float)):
            out[gmina_code(a)] = out.get(gmina_code(a), 0) + int(v)
    return out


def parse_totals(rows: list[list]) -> dict[str, int]:
    """{whole gmina: commuters} from the outgoing or incoming sheet (parts added up)."""
    out: dict[str, int] = {}
    for r in rows:
        if len(r) < 3:
            continue
        c, v = _code(r[0]), r[2]
        if c and isinstance(v, (int, float)) and not isinstance(v, bool):
            g = gmina_code(c)
            out[g] = out.get(g, 0) + int(v)
    return out


class PolandCommuting(Source):
    info = SourceInfo(
        id="pl_flows_commuting",
        title="Commuting to work between gminas, NSP 2021",
        publisher="Statistics Poland (GUS)",
        homepage=PAGE,
        license="GUS CC BY 4.0 (reuse with the source named)",
        description="Wage employees who live in one gmina and work in another, census of 31 March 2021: the "
                    "gmina-to-gmina matrix (flows of 3 or more people) and the incoming and outgoing totals.",
        used_for=["Commuters map layer", "Commuters lens"],
    )

    def fetch(self, force: bool = False) -> None:
        self.download(URL, FILE, force=force, expect_binary=True)

    def process(self) -> dict:
        path = Path(self.raw_dir / FILE)
        matrix_rows = read_xlsx(path, SHEETS[0])
        flows = parse_matrix(matrix_rows)
        inner = internal_flows(matrix_rows)
        out_tot = parse_totals(read_xlsx(path, SHEETS[1]))
        in_tot = parse_totals(read_xlsx(path, SHEETS[2]))
        if len(flows) < 50_000 or len(in_tot) < 2_400:
            raise RuntimeError(f"unexpected matrix size: {len(flows)} flows, {len(in_tot)} gminas")
        rows = {}
        for g in sorted(set(out_tot) | set(in_tot)):
            # The part totals count the trips between the two parts of one urban-rural gmina: take them out
            # (the matrix has those of 3 or more people; smaller ones, at most 2 per direction, stay in).
            cin = in_tot.get(g)
            cout = out_tot.get(g)
            cin = cin - inner.get(g, 0) if cin is not None else None
            cout = cout - inner.get(g, 0) if cout is not None else None
            rows[g] = {"commuters_in": cin, "commuters_out": cout,
                       "commuters_net": cin - cout if cin is not None and cout is not None else None}
        flow_list = [{"from": a, "to": b, "level": "gmina", "value": v, "unit": "persons", "year": 2021}
                     for (a, b), v in sorted(flows.items(), key=lambda kv: (-kv[1], kv[0]))]
        return {
            "vintage": "NSP 2021 (31 March 2021), matrix published 31 January 2024",
            "tables": {
                "commuting_gmina": {
                    "level": "gmina",
                    "fields": {
                        "commuters_in": {"label": "Commuters in", "unit": "persons", "year": 2021,
                                         "note": NOTE + " Living in another gmina, working here."},
                        "commuters_out": {"label": "Commuters out", "unit": "persons", "year": 2021,
                                          "note": NOTE + " Living here, working in another gmina."},
                        "commuters_net": {"label": "Net commuting", "unit": "persons", "year": 2021,
                                          "note": NOTE + " Commuters in minus commuters out."},
                    },
                    "rows": rows,
                }
            },
            "flows": flow_list,
            "notes": [
                "Wage employees only: the self-employed and farmers are not in the matrix.",
                "The matrix leaves out flows of fewer than 3 people; the in and out totals include them.",
                "Urban-rural gminas: GUS publishes the town and the rural area separately; they are added into the "
                "whole gmina here, and flows between the two parts are dropped.",
                "Gmina codes are those of 2021; builders match them on the first six digits.",
            ],
            "_files": [FILE],
        }

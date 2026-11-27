"""State money to local governments in 2026: PIT and CIT shares, the general subsidy and the wealth correction (MF).

The Ministry of Finance file "Dochody jednostek samorzadu terytorialnego na 2026 r." (one sheet "Zestawienie",
amounts in zloty) lists every gmina (typ G), city with powiat rights (M), powiat (P) and voivodeship (W) with the
amounts set under the act of 1 October 2024 on the revenue of local government units (Dz.U. 2024 poz. 1572). The
ministry's page says the amounts in the 2026 budget act did not change from the letters of 14 October 2025.

Columns used (the ministry's names, in the order of the sheet):

* "Dochod PIT naliczony na 2026 r." / "Dochod CIT naliczony na 2026 r.": the unit's share in personal and corporate
  income tax as calculated, before the wealth correction.
* "Potrzeby finansowe" and its parts "potrzeby wyrownawcze", "potrzeby ekologiczne", "potrzeby rozwojowe",
  "potrzeby oswiatowe", "potrzeby uzupelniajace": the financial needs set by the act (art. 23).
* "Korekta z tytulu zamoznosci": the wealth correction (art. 32). A unit whose income per adjusted resident is
  above 120% of its category's figure has its revenue cut by half of the excess: first its general subsidy, then
  its PIT share (then CIT; voivodeships: CIT first, then PIT). It is not a payment by the unit: the amounts due
  are simply lower.
* "2026 KWOTY NALEZNE": "PIT nalezny", "CIT nalezny", "Subwencja nalezna", "RAZEM": the amounts due to the unit
  after the correction, transferred by the state.

"KWOTA KALKULACYJNA" (a step of the subsidy formula, art. 31) is not used.
"""

from __future__ import annotations

from ..core.source import Source, SourceInfo
from ..core.store import load_interim
from ._pl_xlsx import read_xlsx

PAGE = ("https://www.gov.pl/web/finanse/kwoty-dochodow-jednostek-samorzadu-terytorialnego-na-rok-2026-potrzeby-"
        "finansowe-podlegajace-sfinansowaniu-oraz-szczegolowe-dane-wykorzystane-do-ich-obliczenia")
URL = "https://www.gov.pl/attachment/23e9b124-8545-4178-ab54-81a9df16ace6"
FILE = "dochody_jst_2026.xlsx"
ACT = "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20240001572"
YEAR = 2026

# column index -> (field, unit label, ministry's column name)
COLUMNS = {
    7: ("pit_calculated", "PIT share as calculated", "Dochód PIT naliczony na 2026 r."),
    8: ("cit_calculated", "CIT share as calculated", "Dochód CIT naliczony na 2026 r."),
    10: ("needs_total", "Financial needs", "Potrzeby finansowe"),
    11: ("needs_equalising", "Equalising needs", "potrzeby wyrównawcze"),
    12: ("needs_ecological", "Ecological needs", "potrzeby ekologiczne"),
    13: ("needs_development", "Development needs", "potrzeby rozwojowe"),
    14: ("needs_education", "Education needs", "potrzeby oświatowe"),
    15: ("needs_supplementary", "Supplementary needs", "potrzeby uzupełniające"),
    16: ("wealth_correction", "Wealth correction", "Korekta z tytułu zamożności"),
    17: ("pit_due", "PIT share due", "PIT należny"),
    18: ("cit_due", "CIT share due", "CIT należny"),
    19: ("subsidy_due", "General subsidy due", "Subwencja należna"),
    20: ("total_due", "Total due", "RAZEM"),
}
LEVELS = {"G": "gmina", "M": "gmina", "P": "powiat", "W": "voivodeship"}


def _norm(text) -> str:
    return " ".join(str(text or "").lower().replace("\n", " ").split())


def check_header(rows: list[list]) -> None:
    """Fail loudly if the ministry moved a column."""
    head = [_norm(c) for c in (rows[1] + [None] * 21)[:21]]
    sub = [_norm(c) for c in (rows[2] + [None] * 21)[:21]]
    want = {5: "kodgus", 6: "nazwa jst", 7: "dochód pit naliczony", 8: "dochód cit naliczony",
            10: "potrzeby finansowe", 16: "korekta z tytułu zamożno"}
    for i, text in want.items():
        if not head[i].startswith(text):
            raise RuntimeError(f"MF 2026 file: column {i} is {head[i]!r}, expected {text!r}")
    want_sub = {11: "potrzeby wyrównawcze", 12: "potrzeby ekologiczne", 13: "potrzeby rozwojowe",
                14: "potrzeby oświatowe", 15: "potrzeby uzupełniające", 17: "pit należny", 18: "cit należny",
                19: "subwencja należna", 20: "razem"}
    for i, text in want_sub.items():
        if sub[i] != text:
            raise RuntimeError(f"MF 2026 file: sub-column {i} is {sub[i]!r}, expected {text!r}")


def unit_code(row: list) -> tuple[str, str] | None:
    """(level, TERYT code) of a data row, or None. Cities with powiat rights -> their gmina (powiat + '011')."""
    kind = str(row[4] or "").strip()
    try:
        wk, pk, kod = int(row[0]), int(row[1]), int(row[5])
    except (TypeError, ValueError):
        return None
    if kind == "G":
        return "gmina", str(kod).zfill(7)
    if kind == "M":
        return "gmina", f"{wk:02d}{pk:02d}011"
    if kind == "P":
        return "powiat", f"{wk:02d}{pk:02d}"
    if kind == "W":
        return "voivodeship", f"{wk:02d}"
    return None


def remap_gminas(rows: dict[str, dict], register: set[str]) -> tuple[dict[str, dict], list[str]]:
    """Move gmina rows whose type digit changed (a village became a town) to the register's code (same 6 digits)."""
    by6: dict[str, list[str]] = {}
    for c in register:
        by6.setdefault(c[:6], []).append(c)
    out, moved = {}, []
    for code, row in rows.items():
        if code not in register and len(by6.get(code[:6], [])) == 1:
            new = by6[code[:6]][0]
            moved.append(f"{code}->{new}")
            code = new
        if code in out:
            raise RuntimeError(f"MF 2026 file: two rows for gmina {code}")
        out[code] = row
    return out, moved


def money(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value))


def parse(rows: list[list]) -> dict[str, dict[str, dict]]:
    """{level: {code: {field: zloty, 'name', 'kind'}}}."""
    check_header(rows)
    out: dict[str, dict[str, dict]] = {"gmina": {}, "powiat": {}, "voivodeship": {}}
    for r in rows[3:]:
        r = (r + [None] * 21)[:21]
        uc = unit_code(r)
        if uc is None:
            continue
        level, code = uc
        if code in out[level]:
            raise RuntimeError(f"MF 2026 file: {level} {code} listed twice")
        row = {f: money(r[i]) for i, (f, _, _) in COLUMNS.items()}
        row["name"] = str(r[6]).strip()
        row["kind"] = str(r[4]).strip()
        out[level][code] = row
    return out


class PolandLocalFinanceFlows(Source):
    info = SourceInfo(
        id="pl_local_finance_flows",
        title="Revenue of local governments set by the state: PIT and CIT shares, general subsidy, wealth correction",
        publisher="Ministry of Finance (MF)",
        homepage=PAGE,
        license="Public sector information; the gov.pl page text is CC BY-SA 4.0 (no separate licence for the file)",
        description="For every gmina, city with powiat rights, powiat and voivodeship: the PIT and CIT shares, the "
                    "financial needs, the wealth correction and the amounts due, under the 2024 act on local "
                    "government revenue.",
        used_for=["Money flows map layer"],
    )

    def fetch(self, force: bool = False) -> None:
        self.download(URL, FILE, force=force, expect_binary=True)

    def process(self) -> dict:
        rows = read_xlsx(self.raw_dir / FILE)
        units = parse(rows)
        register = {g["code"] for g in load_interim("pl_geo_teryt")["gminy"]}
        units["gmina"], moved = remap_gminas(units["gmina"], register)
        unknown = sorted(set(units["gmina"]) - register)
        n = {k: len(v) for k, v in units.items()}
        if n["gmina"] < 2470 or n["powiat"] < 310 or n["voivodeship"] != 16:
            raise RuntimeError(f"MF 2026 file: unexpected unit counts {n}")
        for level, rows_ in units.items():
            for code, row in rows_.items():
                parts = [row["pit_due"], row["cit_due"], row["subsidy_due"]]
                if None not in parts and row["total_due"] is not None and abs(sum(parts) - row["total_due"]) > 2:
                    raise RuntimeError(f"MF 2026 file: {level} {code} amounts due do not add up to RAZEM")
        tables = {}
        for level, rows_ in units.items():
            fields = {f: {"label": label, "unit": "PLN", "year": YEAR, "note": f"MF column '{col}'"}
                      for f, label, col in COLUMNS.values()}
            tables[f"local_finance_{level}"] = {
                "level": level,
                "fields": fields,
                "rows": {c: {k: v for k, v in r.items() if k not in ("name", "kind")} for c, r in sorted(rows_.items())},
            }
        corrected = sorted(((r["wealth_correction"], lvl, c, r["name"]) for lvl, rr in units.items()
                            for c, r in rr.items() if r["wealth_correction"]), reverse=True)
        return {
            "vintage": f"MF, amounts for {YEAR} (final, budget act)",
            "year": YEAR,
            "names": {lvl: {c: r["name"] for c, r in sorted(rr.items())} for lvl, rr in units.items()},
            "kinds": {c: r["kind"] for c, r in units["gmina"].items() if r["kind"] == "M"},
            "tables": tables,
            "notes": [
                f"Amounts in zloty for {YEAR}, as set by the Minister of Finance under the act of 1 October 2024 on "
                f"the revenue of local government units ({ACT}).",
                "Cities with powiat rights (typ M, 66) are one row that covers both their gmina and powiat roles; "
                "they are keyed by their gmina code (powiat code + 011).",
                "Wealth correction (art. 32): half of the amount by which the unit's income per adjusted resident "
                "exceeds 120% of its category's figure. It cuts the general subsidy first, then the PIT share "
                "(then CIT; voivodeships CIT first). The amounts due already include the cut.",
                f"{len(corrected)} units have a wealth correction, {sum(c[0] for c in corrected):,} zloty in total; "
                f"largest: " + "; ".join(f"{c[3]} {c[0]:,}" for c in corrected[:3]) + ".",
                f"Gmina codes: {len(moved)} rows use the type digit before the 2026-01-01 register (a town since); "
                f"moved to the register code: {', '.join(moved)}." if moved else "Gmina codes match the register.",
                *([f"Not in the gmina register: {', '.join(unknown)}"] if unknown else []),
                "Not used: 'KWOTA KALKULACYJNA' (a step of the subsidy formula, art. 31).",
            ],
            "_files": [FILE],
        }

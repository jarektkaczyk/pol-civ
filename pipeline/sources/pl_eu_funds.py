"""EU co-financing of 2021-2027 projects by gmina (Ministry of Funds and Regional Policy, dane.gov.pl).

"Lista projektow realizowanych z Funduszy Europejskich w Polsce w latach 2021-2027" (dane.gov.pl dataset 13939,
CC0 1.0), a monthly snapshot of every signed project: programme, EU co-financing in zloty and the place where the
project is carried out ("WOJ.: X, POW.: y, GM.: z", several places joined with " | ").

Rule: a project's EU co-financing goes to the gminas it names; a project in several gminas is split equally between
them. Places named only as a powiat, a voivodeship or the whole country ("Caly Kraj") are left out of the gmina
totals (their sums are in `notes`). Gmina names are matched to TERYT within their powiat; "X - Gmina wiejska" is the
rural gmina of that name, a plain name the urban or urban-rural one.

KPO (the Recovery plan) is not included: no national project list with locations is published as open data
(dane.gov.pl has ARiMR voivodeship totals and a CUPT list of transport projects without places).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.store import load_interim
from ..core.source import Source, SourceInfo
from ._pl_xlsx import read_xlsx
from .pl_soc_common import slug, voivodeship_code

DATASET = "https://dane.gov.pl/pl/dataset/13939"
SNAPSHOT = "2026-11-01"
URL = ("https://api.dane.gov.pl/resources/2912686,lista-projektow-realizowanych-z-funduszy-europejskich-w-polsce-"
       "w-latach-2021-2027-1-listopada-2026-r/file")
FILE = f"lista_projektow_2021_2027_{SNAPSHOT}.xlsx"
COL_PROGRAMME, COL_EU, COL_PLACE = 8, 13, 15
RURAL = " - gmina wiejska"


def parse_place(text: str) -> dict | None:
    """'WOJ.: LUBELSKIE, POW.: bialski, GM.: Biala Podlaska - Gmina wiejska' -> {voiv, powiat, gmina}."""
    m = re.match(r"\s*WOJ\.:\s*([^,]+?)\s*(?:,\s*POW\.:\s*([^,]+?)\s*)?(?:,\s*GM\.:\s*(.+?)\s*)?$", text)
    if not m:
        return None
    return {"voiv": voivodeship_code(m.group(1)), "powiat": m.group(2), "gmina": m.group(3)}


def split_places(cell) -> list[str]:
    return [p for p in str(cell or "").split(" | ") if p.strip()]


class GminaIndex:
    """(voivodeship code, powiat key, gmina key) -> TERYT7 from the TERYT register (pl_geo_teryt)."""

    def __init__(self, teryt: dict):
        pow_name = {p["code"]: p["name"] for p in teryt["powiaty"]}
        self.by_key: dict[tuple, list[tuple[str, str]]] = {}
        for g in teryt["gminy"]:
            pname = pow_name.get(g["code"][:4], "")
            pkey = slug(re.sub(r"^Powiat (m\. st\. |m\. )?", "", pname))
            self.by_key.setdefault((g["code"][:2], pkey, slug(g["name"])), []).append((g["code"], g.get("type")))

    def find(self, voiv: str | None, powiat: str | None, gmina: str | None) -> str | None:
        if not (voiv and powiat and gmina):
            return None
        rural = gmina.lower().endswith(RURAL)
        name = gmina[: -len(RURAL)] if rural else gmina
        cands = self.by_key.get((voiv, slug(powiat), slug(name))) or []
        if rural:
            cands = [c for c in cands if c[1] == "rural"] or cands
        elif len(cands) > 1:
            cands = [c for c in cands if c[1] != "rural"] or cands
        return cands[0][0] if len(cands) == 1 else None


def allocate(rows: list[list], index: GminaIndex) -> tuple[dict[str, float], dict[str, float], dict]:
    """({TERYT7: EU zloty}, {TERYT7: projects}, stats) from the project rows (header rows skipped by the caller)."""
    eu: dict[str, float] = {}
    count: dict[str, float] = {}
    stats = {"rows": 0, "total": 0.0, "gmina": 0.0, "powiat_only": 0.0, "voiv_only": 0.0, "country": 0.0,
             "unmatched": 0.0, "unmatched_names": set(), "programmes": set()}
    for r in rows:
        if len(r) <= COL_PLACE:
            continue
        v = r[COL_EU]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        stats["rows"] += 1
        stats["total"] += v
        if r[COL_PROGRAMME]:
            stats["programmes"].add(str(r[COL_PROGRAMME]).strip())
        places = split_places(r[COL_PLACE])
        if not places or any("kraj" in slug(p) and "woj" not in slug(p) for p in places):
            stats["country"] += v
            continue
        parsed = [parse_place(p) for p in places]
        gm = [p for p in parsed if p and p["gmina"]]
        if not gm:
            stats["powiat_only" if any(p and p["powiat"] for p in parsed) else "voiv_only"] += v
            continue
        share = v / len(gm)
        for p in gm:
            code = index.find(p["voiv"], p["powiat"], p["gmina"])
            if code is None:
                stats["unmatched"] += share
                stats["unmatched_names"].add(f"{p['powiat']}/{p['gmina']}")
                continue
            eu[code] = eu.get(code, 0.0) + share
            count[code] = count.get(code, 0.0) + 1 / len(gm)
            stats["gmina"] += share
        # Places of the row that name only a powiat or voivodeship next to gminas get nothing (rare).
    return eu, count, stats


class EuFunds(Source):
    info = SourceInfo(
        id="pl_eu_funds",
        title="EU-funded projects 2021-2027",
        publisher="Ministry of Funds and Regional Policy (dane.gov.pl)",
        homepage=DATASET,
        license="CC0 1.0",
        description="Every signed project of the 2021-2027 European Funds in Poland with its programme, EU "
                    f"co-financing and place, snapshot of {SNAPSHOT}.",
        used_for=["EU co-financing lens"],
    )

    def fetch(self, force: bool = False) -> None:
        self.download(URL, FILE, force=force, expect_binary=True)

    def process(self) -> dict:
        rows = read_xlsx(Path(self.raw_dir / FILE), 0)
        index = GminaIndex(load_interim("pl_geo_teryt"))
        eu, count, st = allocate(rows[2:], index)
        if st["rows"] < 20_000:
            raise RuntimeError(f"only {st['rows']} project rows in {FILE}")
        bn = lambda x: f"{x / 1e9:.1f} bn zl"
        pct = lambda x: f"{x / st['total'] * 100:.1f}%"
        table_rows = {c: {"eu_cofinancing": round(eu[c]), "projects": round(count[c], 2)} for c in sorted(eu)}
        programmes = sorted(st["programmes"])
        note = (f"{SNAPSHOT}, signed projects of the 2021-2027 European Funds (Ministry of Funds and Regional Policy). "
                "A project in several gminas is split equally.")
        return {
            "vintage": f"European Funds 2021-2027 project list, {SNAPSHOT}",
            "tables": {
                "eu_funds_gmina": {
                    "level": "gmina",
                    "fields": {
                        "eu_cofinancing": {"label": "EU co-financing", "unit": "PLN", "year": int(SNAPSHOT[:4]),
                                           "note": note},
                        "projects": {"label": "Projects", "unit": "projects", "year": int(SNAPSHOT[:4]),
                                     "note": note + " A shared project counts as a fraction."},
                    },
                    "rows": table_rows,
                }
            },
            "programmes": programmes,
            "lens_text": {
                "eu_funds": {
                    "description": (
                        f"EU co-financing of the 2021-2027 European Funds projects carried out in the gmina, per "
                        f"resident (project list of {SNAPSHOT}, Ministry of Funds and Regional Policy; residents on "
                        "30 June 2026, GUS). Includes the 16 regional programmes and the national ones (FENG, "
                        "FEnIKS, FERS, FEPW, FERC, technical assistance), fisheries (FER), the home-affairs funds and "
                        "the Interreg programmes managed in Poland. A project in several gminas is split equally. "
                        f"Projects placed only in a powiat, a voivodeship or the whole country ({pct(st['total'] - st['gmina'] - st['unmatched'])} "
                        "of the money) are left out. The Recovery plan (KPO) is not included."),
                    "note": f"Per gmina, signed projects on {SNAPSHOT}. A project counts in the gminas where it is "
                            "carried out. The Recovery plan (KPO) is not included.",
                }
            },
            "notes": [
                f"{st['rows']} projects, EU co-financing {bn(st['total'])}: in gminas {bn(st['gmina'])} "
                f"({pct(st['gmina'])}); powiat only {bn(st['powiat_only'])}; voivodeship only "
                f"{bn(st['voiv_only'])}; whole country {bn(st['country'])}; gmina names not matched "
                f"{bn(st['unmatched'])} ({len(st['unmatched_names'])} names).",
                "Programmes: " + "; ".join(programmes),
                "Unmatched gmina names: " + ", ".join(sorted(st["unmatched_names"])[:40]),
                "KPO (Recovery and Resilience plan) is not included: no national project list with places is "
                "published as open data.",
            ],
            "_files": [FILE],
        }

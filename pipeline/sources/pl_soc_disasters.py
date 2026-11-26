"""Disasters: the area of the state of natural disaster declared after the September 2024 flood.

The Council of Ministers' regulation of 16 September 2024 (Dz.U. 2024 poz. 1365) and its
amendments (poz. 1380, 1392, 1394, 1412) list the area by voivodeship as whole powiats, cities
with powiat rights and named gminas. The consolidated text (poz. 1395) and the last amendment
(poz. 1412) are downloaded from the Sejm ELI API. The list of units is curated in
pl_soc_disasters.json, each with the exact phrase of the act; process() checks that every
phrase is in the downloaded text, so a wrong transcription fails loudly.

Units are resolved to codes with the PKW 2025 gmina table (powiat names, gmina names and
6-digit codes) and the GUS BDL unit list (TERYT7 type digit), as in pl_soc_elections.
The 1997 and 2010 flood lists exist only as scanned PDFs (1997 in the pre-1999 voivodeships)
and the ISOK flood-hazard maps only as WFS polygons, so they are not included.
"""

from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

from ..core.source import Source, SourceInfo
from .pl_soc_common import gmina_units, load_curated, read_semicolon_csv, slug, teryt6_index, teryt7_from6
from .pl_soc_elections import PRES_BASE, PRES_FILES, PlSocElections, blob_timestamp

ACT_TEXTS = {
    "consolidated": "https://api.sejm.gov.pl/eli/acts/DU/2024/1395/text.html",
    "DU/2024/1412": "https://api.sejm.gov.pl/eli/acts/DU/2024/1412/text.html",
}


def act_text(raw: str) -> str:
    """HTML of an act -> plain text with single spaces."""
    t = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(html.unescape(t).split())


def phrase_in(phrase: str, text: str) -> bool:
    """True if `phrase` occurs in `text` as whole words ('opolski' does not match 'opolskim')."""
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def resolve(areas: list[dict], pkw_rows: list[dict]) -> tuple[dict, dict, list]:
    """Curated areas -> ({teryt6: (date, part)}, {powiat4: date}, problems).

    pkw_rows: PKW rows with "TERYT Gminy", "Gmina", "Powiat", "Wojewodztwo" (ASCII slug keys
    are matched by the caller). A powiat area covers every gmina whose code starts with it.
    """
    by_powiat: dict[tuple[str, str], set] = {}
    by_gmina: dict[tuple[str, str, str], str] = {}
    for r in pkw_rows:
        code = r["teryt"].zfill(6)
        key = (slug(r["woj"]), slug(r["powiat"]))
        by_powiat.setdefault(key, set()).add(code[:4])
        by_gmina[key + (slug(r["gmina"]),)] = code
    gminas: dict[str, tuple[str, bool]] = {}
    powiats: dict[str, str] = {}
    problems = []
    for a in areas:
        key = (slug(a["voivodeship"]), slug(a["pkw_powiat"]))
        date = a["date"]
        if a["unit"] == "powiat":
            codes = by_powiat.get(key, set())
            if len(codes) != 1:
                problems.append(f"powiat {a['pkw_powiat']}: {len(codes)} matches")
                continue
            p4 = next(iter(codes))
            powiats[p4] = min(date, powiats.get(p4, date))
            for (w, p, g), code in by_gmina.items():
                if code[:4] == p4:
                    prev = gminas.get(code)
                    gminas[code] = (min(date, prev[0]) if prev else date, False)
        else:
            code = by_gmina.get(key + (slug(a["pkw_gmina"]),))
            if code is None:
                problems.append(f"gmina {a['pkw_gmina']} ({a['pkw_powiat']}): no match")
                continue
            prev = gminas.get(code)
            part = a["unit"] == "gmina_part"
            gminas[code] = (date, part) if prev is None else (min(date, prev[0]), prev[1] and part)
    return gminas, powiats, problems


class PlSocDisasters(Source):
    info = SourceInfo(
        id="pl_soc_disasters",
        title="Area of the 2024 flood state of natural disaster",
        publisher="Rada Ministrów (Dziennik Ustaw, via the Sejm ELI API); PKW and GUS for unit codes",
        homepage="https://api.sejm.gov.pl/eli/acts/DU/2024/1395",
        license="Legal acts are not subject to copyright (Polish copyright act, art. 4)",
        description="Gminas and powiats under the state of natural disaster declared after the flood of "
        "September 2024 in Lower Silesia, Lubusz, Opole and Silesia, with the date each was added.",
        used_for=["Disasters lens"],
    )

    def _pkw_rel(self, force=False) -> str:
        blob = self.download(f"{PRES_BASE}/config.blob", "pkw/config.blob", force=force)
        name = PRES_FILES["r2"]
        ts = blob_timestamp(Path(blob).read_bytes(), f"{name}_csv.zip")
        rel = f"pkw/{name}_csv.{ts}.zip"
        self.download(f"{PRES_BASE}/csv/{name}_csv.{ts}.zip", rel, force=force, expect_binary=True)
        return rel

    def fetch(self, force=False):
        for key, url in ACT_TEXTS.items():
            self.download(url, f"acts/{key.replace('/', '_')}.html", force=force)
        self._pkw_rel(force=force)
        gmina_units(PlSocElections())  # the BDL unit list is cached once, by pl_soc_elections

    def process(self):
        cur = load_curated(__file__, "pl_soc_disasters.json")["flood_2024"]
        texts = " ".join(act_text((self.raw_dir / f"acts/{k.replace('/', '_')}.html").read_text(encoding="utf-8"))
                         for k in ACT_TEXTS)
        missing = [a["phrase"] for a in cur["areas"] if not phrase_in(a["phrase"], texts)]
        if missing:
            raise RuntimeError(f"phrases not found in the act texts: {missing}")
        areas = [dict(a, date=cur["acts"][a["act"]]["date"]) for a in cur["areas"]]

        rel = self._pkw_rel()
        with zipfile.ZipFile(self.raw_dir / rel) as z:
            rows = read_semicolon_csv(z.read(z.namelist()[0]).decode("utf-8"))
        cols = {slug(k): k for k in rows[0]}
        pkw = [{"teryt": r[cols["teryt_gminy"]], "gmina": r[cols["gmina"]], "powiat": r[cols["powiat"]],
                "woj": r[cols["wojewodztwo"]]} for r in rows if r[cols["teryt_gminy"]].strip()]
        gminas6, powiats, problems = resolve(areas, pkw)
        if problems:
            raise RuntimeError("; ".join(problems))
        index = teryt6_index(gmina_units(PlSocElections()))
        g_rows, unmatched = {}, []
        for code6, (date, part) in sorted(gminas6.items()):
            t7 = teryt7_from6(code6, index)
            if t7 is None:
                unmatched.append(code6)
                continue
            g_rows[t7] = {"declared_2024": 1, "declared_2024_partial": 1 if part else 0,
                          "declared_2024_date": int(date.replace("-", ""))}
        if unmatched:
            raise RuntimeError(f"no TERYT7 for {unmatched}")
        p_rows = {p: {"declared_2024": 1, "declared_2024_date": int(d.replace("-", ""))} for p, d in sorted(powiats.items())}
        fields = {
            "declared_2024": {"label": "State of natural disaster, September 2024 flood", "unit": "flag", "year": 2024,
                              "note": "1 = in the declared area; gminas outside it are absent (not declared)"},
            "declared_2024_partial": {"label": "Only part of the gmina declared", "unit": "flag", "year": 2024},
            "declared_2024_date": {"label": "Date the unit was added", "unit": "yyyymmdd", "year": 2024},
        }
        acts = "; ".join(f"Dz.U. {k[3:7]} poz. {k[8:]} ({v['date']})" for k, v in cur["acts"].items())
        return {
            "vintage": "Dz.U. 2024 poz. 1365 as amended (consolidated text poz. 1395, last change poz. 1412)",
            "tables": {
                "flood_2024_gmina": {"level": "gmina", "fields": fields, "rows": g_rows},
                "flood_2024_powiat": {"level": "powiat", "fields": {k: fields[k] for k in ("declared_2024",
                                                                                             "declared_2024_date")},
                                      "rows": p_rows,
                                      "note": "whole powiats and cities with powiat rights named in the act"},
            },
            "notes": [
                "rule: every unit named in the Council of Ministers' regulation on the state of natural disaster of "
                f"16 Sep 2024 and its amendments: {acts}.",
                f"{len(g_rows)} gminas in {len(p_rows)} whole powiats plus named gminas; a powiat named in the act "
                "covers all its gminas.",
                "TERYT7 codes: PKW 6-digit codes with the type digit from the GUS BDL unit list cached by "
                "pl_soc_elections (one copy of the list for both sources).",
                "Malomice (lubuskie): only the town was named, so the gmina is flagged declared_2024_partial = 1.",
                "Not included: the 1997 and 2010 flood gmina lists (scanned PDFs; 1997 uses the pre-1999 "
                "voivodeships), the separate list of gminas eligible for flood aid (Dz.U. 2024 poz. 1371, "
                "consolidated Dz.U. 2026 poz. 948, PDF only), and ISOK flood-hazard shares (WFS polygons only).",
            ],
            "_files": [f"acts/{k.replace('/', '_')}.html" for k in ACT_TEXTS] + [rel, "pkw/config.blob"],
        }

"""PKW election results by gmina: presidential election 2025 (both rounds) and Sejm 2023.

The PKW result sites (prezydent2025.pkw.gov.pl, sejmsenat2023.pkw.gov.pl) publish one CSV
per election and level. The 2025 site adds a timestamp to every data file name; the
timestamps live in its protobuf `data/config.blob`, which this source reads first.

PKW keys gminas by the 6-digit TERYT code without the type digit and splits Warsaw into its
18 districts; rows abroad ("zagranica") and on ships ("statki") have no code. The GUS BDL
unit list gives the TERYT7 code (see pl_soc_common). Warsaw districts are summed into
1465011. Abroad and ships are left out of the gmina tables and reported in a totals table.
Candidate and committee names are kept exactly as PKW prints them; no colours are assigned.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from ..core.source import Source, SourceInfo
from .pl_soc_common import gmina_units, num, pct, read_semicolon_csv, slug, teryt6_index, teryt7_from6

PRES_BASE = "https://prezydent2025.pkw.gov.pl/prezydent2025/data"
PRES_FILES = {
    "r1": "wyniki_gl_na_kandydatow_po_gminach",
    "r2": "wyniki_gl_na_kandydatow_po_gminach_w_drugiej_turze",
}
SEJM_URL = "https://sejmsenat2023.pkw.gov.pl/sejmsenat2023/data/csv/wyniki_gl_na_listy_po_gminach_sejm_csv.zip"

# Standard PKW columns, matched by their ASCII slug (pl_soc_common.slug) so the code stays ASCII.
S_ELIGIBLE = "liczba_wyborcow_uprawnionych_do_glosowania"
S_VALID_CARDS = "liczba_kart_waznych"
S_ISSUED = ("liczba_wyborcow_ktorym_wydano_karty_do_glosowania_w_lokalu_wyborczym_oraz_w_glosowaniu_"
            "korespondencyjnym_lacznie")
S_VALID_PRES = "liczba_glosow_waznych_oddanych_lacznie_na_wszystkich_kandydatow"
S_VALID_SEJM = "liczba_glosow_waznych_oddanych_lacznie_na_wszystkie_listy_kandydatow"


def find_col(header: list[str], wanted: str) -> str:
    """The header whose slug is `wanted`."""
    for h in header:
        if slug(h) == wanted:
            return h
    raise KeyError(f"PKW column {wanted!r} not found")


def blob_timestamp(blob: bytes, filename: str) -> int | None:
    """Timestamp (protobuf varint, field 2) stored right after `filename` in config.blob."""
    m = re.search(re.escape(filename.encode()) + rb"\x10", blob)
    if not m:
        return None
    value, shift, i = 0, 0, m.end()
    while True:
        b = blob[i]
        value |= (b & 0x7F) << shift
        i += 1
        if not b & 0x80:
            return value
        shift += 7


def aggregate(rows: list[dict], index: dict[str, str], value_cols: list[str]) -> tuple[dict, dict, list]:
    """Sum PKW rows into TERYT7 gminas.

    Returns (gminas, outside, unmatched): gminas = TERYT7 -> {col: sum or None},
    outside = {"abroad"|"ships": {col: sum}}, unmatched = PKW codes with no TERYT7.
    A blank cell (committee not on the ballot there) stays None unless another part of the
    same gmina has a number.
    """
    gminas: dict[str, dict] = {}
    outside: dict[str, dict] = {}
    unmatched: list[str] = []
    for r in rows:
        code = r.get("TERYT Gminy", "").strip()
        if not code:
            where = r.get("Powiat", "").strip().lower()
            key = "ships" if where == "statki" else "abroad" if where == "zagranica" else None
            if key is None:
                unmatched.append(r.get("Gmina", "?"))
                continue
            target = outside.setdefault(key, {})
        else:
            t7 = teryt7_from6(code, index)
            if t7 is None:
                unmatched.append(code)
                continue
            target = gminas.setdefault(t7, {})
        for c in value_cols:
            v = num(r.get(c))
            if v is None:
                target.setdefault(c, None)
            else:
                target[c] = (target.get(c) or 0) + v
    return gminas, outside, unmatched


def _read_zip_csv(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if n.endswith(".csv"))
        return read_semicolon_csv(z.read(member).decode("utf-8"))


def _candidate_cols(header: list[str], valid_col: str) -> list[str]:
    """The candidate/committee columns: everything after the valid-votes column."""
    return header[header.index(valid_col) + 1:]


class PlSocElections(Source):
    info = SourceInfo(
        id="pl_soc_elections",
        title="Election results by gmina (presidential 2025, Sejm 2023)",
        publisher="Pa\u0144stwowa Komisja Wyborcza (PKW)",
        homepage="https://wybory.gov.pl/prezydent2025/pl/dane_w_arkuszach",
        license="Public information (PKW official results); cite as Pa\u0144stwowa Komisja Wyborcza",
        description="Votes, shares and turnout by gmina in both rounds of the 2025 presidential election "
        "and the 2023 Sejm election. Votes cast abroad and on ships are counted in the national totals only.",
        used_for=["Elections lenses", "Culture advisor"],
    )

    def _pres_files(self, force: bool = False) -> dict[str, str]:
        blob = self.download(f"{PRES_BASE}/config.blob", "prezydent2025/config.blob", force=force)
        data = Path(blob).read_bytes()
        out = {}
        for key, name in PRES_FILES.items():
            ts = blob_timestamp(data, f"{name}_csv.zip")
            if ts is None:
                raise RuntimeError(f"PKW config.blob has no timestamp for {name}_csv.zip")
            rel = f"prezydent2025/{name}_csv.{ts}.zip"
            self.download(f"{PRES_BASE}/csv/{name}_csv.{ts}.zip", rel, force=force, expect_binary=True)
            out[key] = rel
        return out

    def fetch(self, force=False):
        self._pres_files(force=force)
        self.download(SEJM_URL, "sejm2023/wyniki_gl_na_listy_po_gminach_sejm_csv.zip", force=force, expect_binary=True)
        gmina_units(self)

    def process(self):
        units = gmina_units(self)
        index = teryt6_index(units)
        files = self._pres_files()
        notes = [
            "Gmina codes: PKW 6-digit TERYT mapped to TERYT7 with the GUS BDL unit list (level 6, current division).",
            "Warsaw: PKW reports 18 districts (1465xx); they are summed into 1465011 Warszawa.",
            "Turnout = valid ballot papers (karty wazne) / eligible voters, as PKW computes it (gives 71.63% for 1 June 2025).",
            "Shares are % of valid votes. Abroad and ships are excluded from gmina rows; see the *_totals tables.",
            "Names are exactly as PKW prints them. No party or candidate colours are part of this data.",
            "2025 files are PKW's updated release of 23 Sep 2025 (after Supreme Court recounts): R2 totals differ "
            "from the 2 June 2025 announcement (Dz.U. 2025 poz. 714: Nawrocki 10,606,877, Trzaskowski 10,237,286) "
            "by under 300 votes; shares 50.89/49.11 and turnout 71.63% are unchanged.",
            "Gminas Szczawa (1207132) and Grabowka (2002162) exist since 1 Jan 2025: they are in the 2025 tables "
            "(2,479 gminas) but not in sejm_2023 (2,477), whose figures for that area sit in the former gminas.",
        ]
        tables: dict = {}
        used = []
        for key, rel in files.items():
            rows = _read_zip_csv(self.raw_dir / rel)
            tname = f"president_2025_{key}"
            tables[tname], tables[tname + "_totals"], unmatched = self._build(
                rows, index, S_VALID_PRES, 2025,
                "Presidential election 2025, " + ("first round (18 May 2025)" if key == "r1" else
                                                   "second round (1 June 2025)"), with_votes=key == "r2")
            if unmatched:
                notes.append(f"{tname}: PKW codes without a TERYT7 match (dropped): {', '.join(unmatched)}")
            used.append(rel)
        sejm_rel = "sejm2023/wyniki_gl_na_listy_po_gminach_sejm_csv.zip"
        rows = _read_zip_csv(self.raw_dir / sejm_rel)
        tables["sejm_2023"], tables["sejm_2023_totals"], unmatched = self._build(
            rows, index, S_VALID_SEJM, 2023, "Sejm election, 15 October 2023", with_votes=False)
        if unmatched:
            notes.append(f"sejm_2023: PKW codes without a TERYT7 match (dropped): {', '.join(unmatched)}")
        notes.append("sejm_2023: a committee share is null where its list was not registered in that district.")
        used.append(sejm_rel)
        used += [f"bdl_units/{p.name}" for p in sorted((self.raw_dir / "bdl_units").glob("p*.json"))]
        return {
            "vintage": "PKW: presidential election 2025 (rounds of 18 May and 1 June 2025); Sejm 2023 (15 Oct 2023)",
            "tables": tables,
            "notes": notes,
            "_files": used + ["prezydent2025/config.blob"],
        }

    @staticmethod
    def _build(rows, index, valid_slug, year, title, with_votes):
        header = list(rows[0].keys())
        col_eligible, col_issued = find_col(header, S_ELIGIBLE), find_col(header, S_ISSUED)
        col_cards = find_col(header, S_VALID_CARDS)
        valid_col = find_col(header, valid_slug)
        cands = _candidate_cols(header, valid_col)
        value_cols = [col_eligible, col_issued, col_cards, valid_col] + cands
        gminas, outside, unmatched = aggregate(rows, index, value_cols)
        keys = {c: slug(c.split(" ")[0]) if year == 2025 else slug(c) for c in cands}
        if len(set(keys.values())) != len(keys):
            raise RuntimeError(f"{title}: candidate keys collide")
        fields = {
            "eligible": {"label": "Eligible voters", "unit": "persons", "year": year, "note": title},
            "ballots_issued": {"label": "Voters given ballots", "unit": "persons", "year": year},
            "valid_votes": {"label": "Valid votes", "unit": "votes", "year": year},
            "valid_ballots": {"label": "Valid ballot papers", "unit": "ballots", "year": year},
            "turnout": {"label": "Turnout", "unit": "%", "year": year, "note": "valid ballot papers / eligible voters (PKW)"},
        }
        for c, k in keys.items():
            if with_votes:
                fields[f"{k}_votes"] = {"label": c, "unit": "votes", "year": year}
            fields[f"{k}_share"] = {"label": c, "unit": "%", "year": year, "note": "share of valid votes"}

        def row(g: dict) -> dict:
            out = {
                "eligible": g.get(col_eligible),
                "ballots_issued": g.get(col_issued),
                "valid_votes": g.get(valid_col),
                "valid_ballots": g.get(col_cards),
                "turnout": pct(g.get(col_cards), g.get(col_eligible)),
            }
            for c, k in keys.items():
                if with_votes:
                    out[f"{k}_votes"] = g.get(c)
                out[f"{k}_share"] = pct(g.get(c), g.get(valid_col))
            return {k: (int(v) if isinstance(v, float) and v.is_integer() and not k.endswith(("_share", "turnout"))
                        else v) for k, v in out.items()}

        domestic: dict = {}
        for g in gminas.values():
            for c, v in g.items():
                if v is not None:
                    domestic[c] = domestic.get(c, 0) + v
        total = dict(domestic)
        for part in outside.values():
            for c, v in part.items():
                if v is not None:
                    total[c] = total.get(c, 0) + v
        totals_rows = {"PL": row(total), "PL_domestic": row(domestic)}
        for k, part in outside.items():
            totals_rows[k] = row(part)
        table = {"level": "gmina", "title": title, "fields": fields,
                 "rows": {code: row(g) for code, g in sorted(gminas.items())}}
        totals = {"level": "country", "title": title + ": national totals",
                  "fields": fields,
                  "note": "PL = all votes (domestic + abroad + ships); PL_domestic = sum of gminas; "
                          "abroad and ships as PKW reports them.",
                  "rows": totals_rows}
        return table, totals, unmatched

"""Helpers shared by the pl_soc_* sources (society: elections, faith, air, health, heritage, ...).

Not a source itself (no Source subclass), so the registry ignores it.

* TERYT codes: PKW and other publishers use the 6-digit gmina code (WWPPGG) without the
  type digit. `gmina_units()` reads the GUS BDL unit list (level 6) once per source and
  returns the current TERYT7 code of every gmina, so `teryt7_from6()` can add the digit.
* Small parsers (numbers with Polish decimal commas, semicolon CSV) with unit tests.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import unicodedata
import urllib.error
from pathlib import Path

BDL_UNITS = "https://bdl.stat.gov.pl/api/v1/units?level=6&page-size=100&format=json&page={page}"
WARSAW = "1465011"
GMINA_KINDS = {"1", "2", "3"}  # urban, rural, urban-rural (4/5 are parts, 8/9 districts)


def bdl_id_to_teryt7(unit_id: str) -> str:
    """BDL 12-digit unit id -> TERYT7 (woj 2 + powiat 2 + gmina 2 + kind 1).

    011212001011 -> 1201011: positions 2-3 voivodeship, 7-8 powiat, 9-10 gmina, 11 kind.
    """
    if not re.fullmatch(r"\d{12}", unit_id):
        raise ValueError(f"not a BDL unit id: {unit_id!r}")
    return unit_id[2:4] + unit_id[7:9] + unit_id[9:11] + unit_id[11]


def bdl_download(source, url: str, rel: str, *, attempts: int = 4, pause: float = 1.5) -> Path:
    """source.download for the GUS BDL API, polite to its anonymous limits.

    A cached file is returned at once. Otherwise waits `pause` seconds before the request and, on
    HTTP 429, waits the server's Retry-After (at most 15 minutes) and tries again.
    """
    dest = source.raw_dir / rel
    if dest.exists() or source.offline:
        return source.download(url, rel)
    for n in range(attempts):
        time.sleep(pause)
        try:
            return source.download(url, rel)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or n == attempts - 1:
                raise
            m = re.search(r"\d+", exc.headers.get("Retry-After") or "")
            wait = min(int(m.group()) if m else 60, 900) + 2
            exc.close()
            print(f"      BDL limit reached; waiting {wait} s")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def gmina_units(source, folder: str = "bdl_units") -> dict[str, dict]:
    """TERYT7 -> {"name", "kind"} for every level-6 BDL unit (current territorial division).

    Downloads every page of /units?level=6 through `source.download` into
    data/raw/<source>/<folder>/ (about 42 pages). Offline, the cached pages are used.
    """
    first = bdl_download(source, BDL_UNITS.format(page=0), f"{folder}/p0.json")
    head = json.loads(Path(first).read_text(encoding="utf-8"))
    last = int(re.search(r"page=(\d+)", head["links"]["last"]).group(1))
    out: dict[str, dict] = {}
    for page in range(last + 1):
        path = bdl_download(source, BDL_UNITS.format(page=page), f"{folder}/p{page}.json")
        for u in json.loads(Path(path).read_text(encoding="utf-8"))["results"]:
            out[bdl_id_to_teryt7(u["id"])] = {"name": u["name"], "kind": u["kind"]}
    if len(out) != head["totalRecords"]:
        raise RuntimeError(f"BDL units: got {len(out)} of {head['totalRecords']}")
    return out


def teryt6_index(units: dict[str, dict]) -> dict[str, str]:
    """6-digit gmina code -> TERYT7 for the gminas proper (kinds 1, 2, 3).

    The BDL list keeps old units: a gmina whose type changed (a village got town rights, so
    rural 2 or urban 1 became urban-rural 3) is listed under both codes. The urban-rural code
    is the newer one (checked on /units/<id> "years", e.g. Swiatniki Gorne 1206142 ends in
    1996, 1206143 runs to 2026), so kind 3 wins a tie. Warsaw districts (kind 8, 1465xx8)
    map to Warsaw 1465011. City delegatury (kind 9) are not gminas and are left out.
    """
    idx: dict[str, str] = {}
    for code, u in sorted(units.items()):
        if u["kind"] in GMINA_KINDS:
            prev = idx.get(code[:6])
            if prev is None or (prev[6] != "3" and code[6] == "3"):
                idx[code[:6]] = code
        elif u["kind"] == "8" and code.startswith("1465"):
            idx[code[:6]] = WARSAW
    return idx


def teryt7_from6(code6: str, index: dict[str, str]) -> str | None:
    """PKW style code (5 or 6 digits, leading zero may be missing) -> TERYT7, or None."""
    code6 = code6.strip()
    if not code6.isdigit():
        return None
    return index.get(code6.zfill(6))


def num(text) -> float | None:
    """'1 234,5' / '1234.5' / '' -> float or None. Dashes and 'x' (GUS 'no data') are None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    t = str(text).strip().replace(" ", "").replace(" ", "")
    if t in {"", "-", "x", "X", ".", "#", "b.d.", "n/a"}:
        return None
    t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def read_semicolon_csv(text: str) -> list[dict[str, str]]:
    """Semicolon CSV (PKW style, BOM allowed) -> list of dicts keyed by header."""
    text = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = [h.strip() for h in next(reader)]
    return [dict(zip(header, (c.strip() for c in row))) for row in reader if any(c.strip() for c in row)]


def slug(text: str) -> str:
    """ASCII snake_case key from a Polish name (diacritics dropped, l-stroke -> l)."""
    t = unicodedata.normalize("NFKD", text.replace("\u0142", "l").replace("\u0141", "L"))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def pct(part: float | None, whole: float | None, digits: int = 2) -> float | None:
    if part is None or not whole:
        return None
    return round(100.0 * part / whole, digits)


VOIVODESHIPS = {  # ASCII slug of the Polish name -> TERYT 2-digit code
    "dolnoslaskie": "02", "kujawsko_pomorskie": "04", "lubelskie": "06", "lubuskie": "08",
    "lodzkie": "10", "malopolskie": "12", "mazowieckie": "14", "opolskie": "16",
    "podkarpackie": "18", "podlaskie": "20", "pomorskie": "22", "slaskie": "24",
    "swietokrzyskie": "26", "warminsko_mazurskie": "28", "wielkopolskie": "30", "zachodniopomorskie": "32",
}


def voivodeship_code(name: str | None) -> str | None:
    """Voivodeship name (with or without diacritics or the word "wojewodztwo") -> TERYT code, or None."""
    if not name:
        return None
    s = slug(name)
    s = s[len("wojewodztwo_"):] if s.startswith("wojewodztwo_") else s
    return VOIVODESHIPS.get(s)


def load_curated(module_file: str, name: str) -> dict:
    """A curated UTF-8 JSON list stored next to the source module (pl_soc_<name>.json)."""
    path = Path(module_file).with_name(name)
    return json.loads(path.read_text(encoding="utf-8"))

"""Helpers shared by the curated economy point sources (pl_econ_champions, pl_tech_sites).

Not a source itself (no Source subclass), so the registry ignores it.

* check_item(): the fields every curated fact must have (one-line fact, its year, a fetched `ref`, a point in Poland).
* cache_refs(): caches the page behind every `ref` through Source.download(), so the Almanac lists each page with its
  retrieval date. A publisher that refuses automated reads is reported in `notes`, never fatal: the fact was read by
  hand from that page (see docs/reference/sources-econ-sites.md).
* to_point(): the interim point of a curated item.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Poland's extent (BLUEPRINT section 4).
LON = (13.6, 24.6)
LAT = (48.75, 55.15)
REQUIRED = ("id", "name", "place", "kind", "lon", "lat", "fact", "year", "ref")
MAX_FACT_WORDS = 32


def load_json(module_file: str, name: str) -> dict:
    return json.loads(Path(module_file).with_name(name).read_text(encoding="utf-8"))


def check_item(it: dict, kinds: set[str]) -> list[str]:
    """Problems with one curated item ([] when it is complete)."""
    out = [f"{it.get('id')}: missing {k}" for k in REQUIRED if it.get(k) in (None, "")]
    if out:
        return out
    if it["kind"] not in kinds:
        out.append(f"{it['id']}: unknown kind {it['kind']!r}")
    if not (LON[0] < it["lon"] < LON[1] and LAT[0] < it["lat"] < LAT[1]):
        out.append(f"{it['id']}: point outside Poland")
    if not str(it["ref"]).startswith("https://"):
        out.append(f"{it['id']}: ref is not an https URL")
    if not isinstance(it["year"], int) or not 1700 < it["year"] <= 2026:
        out.append(f"{it['id']}: year {it['year']!r} is not a year")
    if len(it["fact"].split()) > MAX_FACT_WORDS:
        out.append(f"{it['id']}: fact longer than {MAX_FACT_WORDS} words")
    if any(ch in it["fact"] + it.get("fact_pl", "") for ch in "\u2014\u2013\u201c\u201d\u2018\u2019\u2192"):
        out.append(f"{it['id']}: fact has a dash, curly quote or arrow glyph")
    if not it.get("fact_pl"):
        out.append(f"{it['id']}: missing fact_pl")
    if it.get("label") and not it.get("label_pl"):
        out.append(f"{it['id']}: label without label_pl")
    return out


def ref_file(item_id: str, url: str, n: int = 1) -> str:
    ext = ".pdf" if re.search(r"[.-]pdf($|\?)", url, re.I) else ".html"
    return f"refs/{item_id}{'' if n == 1 else f'_{n}'}{ext}"


def item_refs(it: dict) -> list[tuple[str, str]]:
    """(url, cache path) of an item's sources: `ref` and the optional `ref2`."""
    out = [(it["ref"], ref_file(it["id"], it["ref"]))]
    if it.get("ref2"):
        out.append((it["ref2"], ref_file(it["id"], it["ref2"], 2)))
    return out


def cache_refs(source, items: list[dict], force: bool = False) -> list[str]:
    """Download every ref page once (cached); returns one note per page that could not be fetched."""
    failed = []
    for it in items:
        for url, rel in item_refs(it):
            if (source.raw_dir / rel).exists() and not force:
                continue
            if source.offline:
                continue
            try:
                source.download(url, rel, force=force, expect_binary=rel.endswith(".pdf"))
            except Exception as exc:  # a refused automated read is not fatal: the fact was read by hand
                failed.append(f"{it['id']}: {url} refused the automated read ({type(exc).__name__})")
    return failed


def cached_refs(source, items: list[dict]) -> tuple[list[str], list[str]]:
    """(cached ref files, notes for refs with no cached copy)."""
    files, notes = [], []
    for it in items:
        for url, rel in item_refs(it):
            if (source.raw_dir / rel).exists():
                files.append(rel)
            else:
                how = it.get("note") or "read by hand"
                notes.append(f"{it['id']}: no cached copy of {url} (publisher refuses automated reads; {how})")
    return files, notes


def to_point(it: dict, extra: tuple[str, ...] = ()) -> dict:
    props = {"place": it["place"], "fact": it["fact"], "year": it["year"], "ref": it["ref"]}
    for key in ("label", "ref2", "scope", "office") + extra:
        if it.get(key) not in (None, "", False):
            props[key] = it[key]
    return {"id": it["id"], "name": it["name"], "kind": it["kind"], "lon": it["lon"], "lat": it["lat"],
            "props": props}

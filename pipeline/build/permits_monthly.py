"""Permits for new factories and warehouses month by month (permits_monthly.json), for the map time-lapse.

Reads the cached GUNB permit register zips through the pl_econ_permits source code (only the six columns that
source keeps; investor and designer names are never read). A decision counts in the month of its earliest decision
date, once per gmina (authority plus decision number), from January 2016 (the register's first month) to the newest
month the files cover in full. Each gmina is drawn at the area centroid of its LAU outline, in map km.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.hexgrid import HexGrid
from ..core.paths import RAW
from ..core.store import load_interim, load_interim_payload, write_web
from ..sources import pl_econ_permits as src
from .commuting import gmina_centres
from .counties import projection

REQUIRES = ["pl_econ_permits", "pl_geo_teryt", "pl_geo_lau", "_world"]
PRODUCES = ["permits_monthly.json"]

FIRST_MONTH = "2016-01"
RULES = [
    "Each marker is one building permit decision for a new industrial or storage building (category XVIII of the "
    "building law: factories, plants, warehouses, cold stores), shown in the gmina and the month of the decision.",
    "A decision is counted once per gmina by its issuing authority and decision number; a decision for buildings in "
    "two gminas counts in each.",
    "The register holds first-instance decisions entered since January 2016, without closed (military) areas; it "
    "does not say whether the building was built.",
    "Each gmina is drawn at the centre of its area.",
]


def month_list(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def ring_centroid(rings, proj) -> tuple[float, float] | None:
    """Area centroid (map km) of a set of rings in lon/lat; holes subtract when wound the other way."""
    a_sum = cx = cy = 0.0
    for ring in rings:
        pts = [proj(lon, lat) for lon, lat in ring]
        a = x = y = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            c = x0 * y1 - x1 * y0
            a += c
            x += (x0 + x1) * c
            y += (y0 + y1) * c
        a_sum += a / 2
        cx += x / 6
        cy += y / 6
    if abs(a_sum) < 1e-9:
        return None
    return cx / a_sum, cy / a_sum


def pack(counts: dict[tuple[str, str], int], months: list[str], gminas: list[dict]) -> tuple[list[int], list[int]]:
    """Flat [month index, gmina index, count, ...] sorted by month then gmina, and the national count per month."""
    m_idx = {m: k for k, m in enumerate(months)}
    g_idx = {g["code"]: k for k, g in enumerate(gminas)}
    trip = sorted((m_idx[m], g_idx[c], n) for (c, m), n in counts.items() if m in m_idx and c in g_idx)
    national = [0] * len(months)
    flat: list[int] = []
    for mi, gi, n in trip:
        flat += [mi, gi, n]
        national[mi] += n
    return flat, national


def build() -> None:
    payload = load_interim_payload("pl_econ_permits")
    teryt = load_interim("pl_geo_teryt")
    lau = load_interim("pl_geo_lau")
    world = load_interim("_world")
    codes = [g["code"] for g in teryt["gminy"]]
    names = {g["code"]: g["name"] for g in teryt["gminy"]}
    by6 = {c[:6]: c for c in codes}

    first: dict = {}
    stats: dict = {}
    newest = None
    raw = RAW / "pl_econ_permits"
    for slug in src.SLUGS:
        lines, day = src.zip_lines(raw / src.zip_file(slug))
        newest = day if newest is None or day > newest else newest
        src.first_decisions(src.iter_rows(lines), by6, first, stats)
        lines.close()
    end = src.last_full_month(newest)
    months = month_list(FIRST_MONTH, end)
    counts = src.monthly_counts(first, FIRST_MONTH, end)

    proj = projection(world)
    centre = {}
    for g in lau["gminy"]:
        code = by6.get(g.get("teryt6"))
        c = ring_centroid(g.get("rings") or [], proj) if code else None
        if c:
            centre[code] = c
    hexes = gmina_centres(world, HexGrid(**world["grid"]))
    used = sorted({c for c, _m in counts})
    gminas, no_place = [], 0
    for code in used:
        pos = centre.get(code) or hexes.get(code[:6])
        if pos is None:
            no_place += 1
            continue
        gminas.append({"code": code, "name": names.get(code, code), "x": round(pos[0], 1), "y": round(pos[1], 1)})
    flat, national = pack(counts, months, gminas)
    total = sum(national)
    write_web("permits_monthly.json", {
        "version": 1,
        "vintage": f"GUNB permit register, file of {newest}; decisions {FIRST_MONTH} to {end}",
        "sources": ["pl_econ_permits"],
        "rules": RULES,
        "unit": "decisions",
        "months": months,
        "gminas": gminas,
        "counts": flat,
        "national": national,
        "total": total,
        "notes": [
            f"{len(stats.get('unmapped', ()))} decisions without a usable TERC code and {stats.get('undated', 0)} "
            "rows without a decision date are left out.",
            f"{no_place} gminas have no outline or hex to stand on and are left out.",
            f"The file of {newest} covers {end} in full; later decisions wait for the next file.",
        ],
    })
    print(f"    {total} decisions in {len(gminas)} gminas, {months[0]} to {months[-1]}"
          f" (source vintage: {payload.get('vintage')})")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "permits_monthly.json"
    if not path.exists():
        return [("NOTE", "permits_monthly.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    if doc.get("version") != 1 or not doc.get("rules") or not isinstance(doc.get("sources"), list):
        out.append(("FAIL", "permits_monthly.json: version 1, rules and a sources list are required"))
    months, gminas, flat = doc.get("months") or [], doc.get("gminas") or [], doc.get("counts") or []
    if len(flat) % 3:
        out.append(("FAIL", "permits_monthly.json: counts must be [month, gmina, n] triples"))
    bad = [k for k in range(0, len(flat) - 2, 3)
           if not (0 <= flat[k] < len(months) and 0 <= flat[k + 1] < len(gminas) and flat[k + 2] >= 1)]
    if bad:
        out.append(("FAIL", f"permits_monthly.json: {len(bad)} triples out of range"))
    if any(flat[k] > flat[k + 3] for k in range(0, len(flat) - 3, 3)):
        out.append(("FAIL", "permits_monthly.json: counts must be sorted by month"))
    if sum(doc.get("national") or []) != doc.get("total"):
        out.append(("FAIL", "permits_monthly.json: national counts do not add up to total"))
    if any(not (isinstance(g.get("x"), (int, float)) and isinstance(g.get("y"), (int, float))) for g in gminas):
        out.append(("FAIL", "permits_monthly.json: every gmina needs x and y"))
    size = path.stat().st_size
    if size > 3e6:
        out.append(("WARN", f"permits_monthly.json: {size / 1e6:.1f} MB, over the 3 MB budget"))
    out.append(("PASS", f"permits_monthly.json: {doc.get('total')} decisions, {len(gminas)} gminas, "
                        f"{months[0] if months else '?'} to {months[-1] if months else '?'}, {size / 1e3:.0f} kB"))
    return out

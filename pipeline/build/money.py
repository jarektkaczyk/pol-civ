"""State money for local governments in 2026 (money.json), from the Ministry of Finance file (pl_local_finance_flows).

One row per gmina, city with powiat rights, powiat and voivodeship: the PIT and CIT shares and the general subsidy
due for 2026, the wealth correction that lowered them, and the financial needs. A unit's point is its town banner
(cities.json) or the centre of its hexes; a voivodeship's point is the seat of its self-government (the sejmik).
The state's point is Warszawa. Lazy file for the motion layer.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload, write_web
from .flowgeo import projection, unit_centres

REQUIRES = ["_world", "pl_local_finance_flows", "pl_geo_teryt", "pl_geo_lau", "states.json", "cities.json"]
PRODUCES = ["money.json"]

FIELDS = [  # key in money.json, field in the interim, label
    ("pit", "pit_due", "PIT share"),
    ("cit", "cit_due", "CIT share"),
    ("subsidy", "subsidy_due", "General subsidy"),
    ("total", "total_due", "Total from the state"),
    ("correction", "wealth_correction", "Wealth correction"),
    ("pit_calc", "pit_calculated", "PIT share before correction"),
    ("cit_calc", "cit_calculated", "CIT share before correction"),
    ("needs", "needs_total", "Financial needs"),
]
NEEDS = [("needs_equalising", "Equalising"), ("needs_education", "Education"), ("needs_development", "Development"),
         ("needs_ecological", "Ecological"), ("needs_supplementary", "Supplementary")]
RULES = [
    "The state transfers to every gmina, powiat and voivodeship its share in personal income tax (PIT), its share in "
    "corporate income tax (CIT) and the general subsidy, in the amounts the Minister of Finance set for the year.",
    "Wealth correction (korekta z tytułu zamożności, article 32 of the act on the revenue of local government units of "
    "2024-10-01): a local government whose income per adjusted resident is above 120% of the figure for its kind "
    "receives less, first from its general subsidy, then from its tax shares. The shares, the subsidy and the total "
    "shown already include the cut; the correction is shown to say how much less, not to be subtracted again.",
    "A city with powiat rights is one local government that covers both its gmina and its powiat.",
    "Each moving dot stands for the same amount of money on every flow.",
]


def build() -> None:
    payload = load_interim_payload("pl_local_finance_flows")
    data = payload["data"]
    world = load_interim("_world")
    teryt = load_interim("pl_geo_teryt")
    states = json.loads((WEB_DATA / "states.json").read_text())
    cities = json.loads((WEB_DATA / "cities.json").read_text())
    g_names = {g["code"]: g["name"] for g in teryt["gminy"]}
    p_names = {p["code"]: p["name"] for p in teryt["powiaty"]}
    banner = {c["gmina"]: (c["x"], c["y"]) for c in cities if c.get("gmina") and c.get("kind") in ("city", "town")}
    g_ctr, p_ctr = unit_centres(world)
    # gminas too small for a hex sample: the mean of their LAU outline's vertices
    proj = projection(world)
    lau = {}
    for g in load_interim("pl_geo_lau")["gminy"]:
        pts = [p for ring in g.get("rings") or [] for p in ring]
        if pts:
            lau[g["teryt6"]] = proj(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    seat = {}
    by_gmina = {c["gmina"]: c for c in cities if c.get("gmina")}
    for s in states:
        caps = s.get("capitals") or []
        cap = next((c for c in caps if c.get("role") in ("both", "sejmik")), None)
        city = by_gmina.get(cap["gmina"]) if cap else None
        if city is None:
            raise RuntimeError(f"no seat for {s['name']}")
        seat[s["fips"]] = (city["x"], city["y"])
    warsaw = by_gmina["1465011"]
    kinds = data.get("kinds") or {}
    units, missing = [], []
    for level in ("voivodeship", "powiat", "gmina"):
        table = data["tables"][f"local_finance_{level}"]
        for code, row in table["rows"].items():
            if level == "gmina":
                pos = banner.get(code) or g_ctr.get(code) or lau.get(code[:6])
                name = g_names.get(code) or data["names"]["gmina"].get(code)
                kind = "city_powiat" if code in kinds else "gmina"
            elif level == "powiat":
                pos = p_ctr.get(code)
                name = p_names.get(code) or data["names"]["powiat"].get(code)
                kind = "powiat"
            else:
                pos = seat.get(code)
                name = next((s["name"] for s in states if s["fips"] == code), data["names"]["voivodeship"][code])
                kind = "voivodeship"
            if pos is None:
                missing.append(code)
            u = {"code": code, "level": level, "kind": kind, "name": name,
                 "x": round(pos[0], 1) if pos else None, "y": round(pos[1], 1) if pos else None}
            for key, field, _ in FIELDS:
                u[key] = row.get(field)
            u["needs_parts"] = [row.get(f) for f, _ in NEEDS]
            units.append(u)
    if len(missing) > 5:
        raise RuntimeError(f"money.json: no map point for {missing}")
    write_web("money.json", {
        "version": 1,
        "vintage": payload.get("vintage"),
        "sources": ["pl_local_finance_flows"],
        "rules": RULES,
        "year": data["year"],
        "unit": "PLN",
        "period": "year",
        "state": {"name": "State budget", "x": warsaw["x"], "y": warsaw["y"]},
        "fields": [{"key": k, "label": label} for k, _, label in FIELDS],
        "needs_parts": [label for _, label in NEEDS],
        "units": units,
    })
    corr = [u for u in units if u["correction"]]
    if missing:
        print(f"    no map point (x, y null): {missing}")
    print(f"    {len(units)} units, {len(corr)} with a wealth correction ({sum(u['correction'] for u in corr):,} PLN)")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "money.json"
    if not path.exists():
        return [("NOTE", "money.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    if doc.get("version") != 1 or not doc.get("rules") or not isinstance(doc.get("sources"), list):
        out.append(("FAIL", "money.json: version 1, rules and a sources list are required"))
    units = doc.get("units") or []
    keys = [f["key"] for f in doc.get("fields") or []]
    bad = [u.get("code") for u in units
           if any(u.get(k) is not None and (not isinstance(u[k], int) or u[k] < 0) for k in keys)]
    if bad:
        out.append(("FAIL", f"money.json: amounts must be whole zloty >= 0 or null: {bad[:5]}"))
    sums = [u.get("code") for u in units if None not in (u.get("pit"), u.get("cit"), u.get("subsidy"), u.get("total"))
            and abs(u["pit"] + u["cit"] + u["subsidy"] - u["total"]) > 2]
    if sums:
        out.append(("FAIL", f"money.json: PIT + CIT + subsidy differs from the total: {sums[:5]}"))
    levels = {}
    for u in units:
        levels[u.get("level")] = levels.get(u.get("level"), 0) + 1
    corr = [u for u in units if u.get("correction")]
    total = sum(u.get("total") or 0 for u in units)
    out.append(("PASS", f"money.json: {len(units)} units {levels}; {total / 1e9:.1f} bn PLN due; "
                        f"{len(corr)} with a wealth correction"))
    return out

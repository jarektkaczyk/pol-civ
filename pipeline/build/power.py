"""Power grid snapshot for the "Power now" layer (power.json), from PSE 15-minute data (pl_power_pse) plus the wind
and solar sites of pl_energy_plants and the installed capacity by powiat of pl_energy_res.

The file holds the newest complete day (the layer's fallback when the live PSE call fails), the interconnector
geometry per neighbour, and the request the browser sends for today's data (`live`). Lazy file.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload, write_web
from ..sources.pl_power_pse import section_pair
from .flowgeo import bearing_deg, clip_to_rect, flat, projection, unit_centres

REQUIRES = ["_world", "pl_power_pse", "pl_energy_plants", "pl_energy_res", "pl_geo_teryt", "world.json"]
PRODUCES = ["power.json"]

# Display groups of the ENTSO-E production types (codes as in the PSE report his-gen-pal).
GROUPS = [
    ("hard_coal", "Hard coal", ["B05"]),
    ("lignite", "Lignite", ["B02"]),
    ("gas", "Gas", ["B04"]),
    ("wind", "Wind", ["B18", "B19"]),
    ("solar", "Solar", ["B16"]),
    ("biomass", "Biomass", ["B01"]),
    ("hydro", "Hydro", ["B11", "B12"]),
    ("storage", "Pumped storage", ["B10"]),
    ("oil", "Oil", ["B06"]),
    ("other", "Other", ["B03", "B15", "B20"]),
]
LIVE = {
    "base": "https://api.raporty.pse.pl/api/",
    "reports": {"mix": "his-gen-pal", "totals": "his-wlk-cal", "flows": "przeplywy-mocy"},
    "filter": "business_date eq '{day}'",  # sent as ?$filter=<this, URL-encoded>&$first=2000
    "first": 2000,
    "timezone": "Europe/Warsaw",
    "timeout_ms": 4000,
}
PROCESSED = ("Fuel types grouped for this map and the two directions of each border added up; values are PSE's "
             "15-minute figures. When the live request fails, the map shows the newest complete day.")
RULES = [
    "Power figures are the mean output in megawatts over each quarter of an hour, as published by PSE, the "
    "operator of the national grid.",
    "Cross-border flows are physical flows on each border; a positive value is power flowing into Poland.",
    "Border lines are the overhead lines and cables of 220 kV or more that cross the border; Sweden is reached by "
    "an undersea cable.",
    "Wind farms and solar parks are the largest ones by capacity; turbines and panels by powiat show the installed "
    "capacity there.",
    "Turbines turn faster as national wind output rises; solar parks glow brighter as national solar output rises.",
    "A border with two lines has its flow drawn half on each, because PSE publishes one figure per border.",
    "The map asks PSE for today's figures when the layer opens; if that fails, it shows the newest complete day.",
]


def seconds(start: str | None) -> int | None:
    """'14:15' -> 51300."""
    if not start or ":" not in start:
        return None
    h, m = start.split(":")[:2]
    return int(h) * 3600 + int(m) * 60


def group_mix(generation: dict[str, list], n: int) -> dict[str, list]:
    """{group key: [MW per quarter]}; a group whose codes are all absent is left out; a gap gives null."""
    out = {}
    known = {c for _, _, codes in GROUPS for c in codes}
    extra = [c for c in generation if c not in known]
    for key, _, codes in GROUPS:
        codes = codes + (extra if key == "other" else [])
        present = [c for c in codes if c in generation]
        if not present:
            continue
        vals = []
        for i in range(n):
            parts = [generation[c][i] for c in present]
            vals.append(round(sum(parts), 1) if None not in parts else None)
        out[key] = vals
    return out


def build() -> None:
    payload = load_interim_payload("pl_power_pse")
    pse = payload["data"]
    world = load_interim("_world")
    web_world = json.loads((WEB_DATA / "world.json").read_text())
    width, height = web_world["width"], web_world["height"]
    proj = projection(world)
    s = pse["series"]
    n = len(s["utc"])
    mix = group_mix(s["generation"], n)

    def rnd(vals):
        return [round(v, 1) if v is not None else None for v in vals]

    neighbours = {}
    for p in pse["points"]:
        pr = p["props"]
        nb = neighbours.setdefault(pr["neighbour"], {
            "code": pr["neighbour"], "name": pr["country"], "unit": "MW",
            "sections": sorted(k for k in s["sections"] if pr["neighbour"] in (section_pair(k) or ())),
            "net": rnd(s["net"].get(pr["neighbour"], [None] * n)),
            "lines": [],
        })
        pts = [proj(lon, lat) for lon, lat in pr["path"]]
        bx, by = proj(p["lon"], p["lat"])
        pts, edge = clip_to_rect(pts, width, height)
        nb["lines"].append({
            "id": p["id"], "name": p.get("name"), "voltage_kv": pr.get("voltage_kv"), "hvdc": pr.get("hvdc"),
            "x": round(bx, 1), "y": round(by, 1), "path": flat(pts), "edge": edge,
            "bearing": bearing_deg((bx, by), pts[-1]),
        })
    plants = load_interim("pl_energy_plants")
    sites = {"wind": [], "solar": []}
    for p in plants["points"]:
        kind = {"onshore_wind_plant": ("wind", "onshore"), "offshore_wind_plant": ("wind", "offshore"),
                "solar_plant": ("solar", "solar")}.get(p["kind"])
        if not kind:
            continue
        x, y = proj(p["lon"], p["lat"])
        sites[kind[0]].append({"id": p["id"], "name": p["name"], "kind": kind[1], "status": p["props"].get("status"),
                               "mw": p["props"].get("mw"), "x": round(x, 1), "y": round(y, 1)})
    res = load_interim_payload("pl_energy_res")
    res_rows = res["data"]["tables"]["res_capacity_powiat"]["rows"]
    _, p_ctr = unit_centres(world)
    p_names = {p["code"]: p["name"] for p in load_interim("pl_geo_teryt")["powiaty"]}
    res_powiat = []
    for code, row in sorted(res_rows.items()):
        if code not in p_ctr or (row.get("wind_mw") is None and row.get("solar_mw") is None):
            continue
        x, y = p_ctr[code]
        res_powiat.append({"code": code, "name": p_names.get(code), "x": round(x, 1), "y": round(y, 1),
                           "wind_mw": row.get("wind_mw"), "solar_mw": row.get("solar_mw")})
    write_web("power.json", {
        "version": 1,
        "vintage": payload.get("vintage"),
        "sources": ["pl_power_pse", "pl_energy_plants", "pl_energy_res"],
        "rules": RULES,
        "unit": "MW",
        "period": "15 min",
        "day": pse["day"],
        "timezone": pse["timezone"],
        "step": 900,
        "t": [seconds(x) for x in s["start"]],
        "utc": s["utc"],
        "groups": [{"key": k, "label": label, "codes": codes} for k, label, codes in GROUPS if k in mix],
        "mix": mix,
        "wind": rnd(s["wind"]),
        "solar": rnd(s["solar"]),
        "demand": rnd(s["demand"]),
        "neighbours": [neighbours[k] for k in sorted(neighbours)],
        "wind_farms": sorted(sites["wind"], key=lambda r: -(r["mw"] or 0)),
        "solar_farms": sorted(sites["solar"], key=lambda r: -(r["mw"] or 0)),
        "res_powiat": res_powiat,
        "res_as_of": res["data"].get("as_of"),
        "live": LIVE,
        "attribution": {
            "credit": ["PSE S.A."],
            "created": pse.get("published_utc"),
            "retrieved": (pse.get("retrieved_utc") or "")[:16].replace("+00:00", "") + "Z" if pse.get("retrieved_utc") else None,
            "processed": PROCESSED,
        },
    })
    print(f"    {pse['day']}: {n} quarters, {len(neighbours)} neighbours, "
          f"{sum(len(v['lines']) for v in neighbours.values())} border lines, {len(res_powiat)} powiats")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "power.json"
    if not path.exists():
        return [("NOTE", "power.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    if doc.get("version") != 1 or not doc.get("rules") or not isinstance(doc.get("sources"), list):
        out.append(("FAIL", "power.json: version 1, rules and a sources list are required"))
    n = len(doc.get("t") or [])
    if n < 92:
        out.append(("FAIL", f"power.json: {n} quarters, expected a full day"))
    series = [doc.get("wind"), doc.get("solar"), doc.get("demand"), *(doc.get("mix") or {}).values(),
              *[nb.get("net") for nb in doc.get("neighbours") or []]]
    if any(not isinstance(v, list) or len(v) != n for v in series):
        out.append(("FAIL", "power.json: every series needs one value per quarter"))
    codes = {nb.get("code") for nb in doc.get("neighbours") or []}
    if codes != {"DE", "CZ", "SK", "LT", "UA", "SE"}:
        out.append(("FAIL", f"power.json: neighbours {sorted(codes)}, expected DE CZ SK LT UA SE"))
    for nb in doc.get("neighbours") or []:
        for ln in nb.get("lines") or []:
            p = ln.get("path") or []
            if len(p) < 4 or len(p) % 2:
                out.append(("FAIL", f"power.json {ln.get('id')}: path must be a flat x, y array"))
    lines = sum(len(nb.get("lines") or []) for nb in doc.get("neighbours") or [])
    out.append(("PASS", f"power.json: {doc.get('day')}, {n} quarters, {len(codes)} neighbours, {lines} border lines, "
                        f"{len(doc.get('wind_farms') or [])} wind and {len(doc.get('solar_farms') or [])} solar sites"))
    return out

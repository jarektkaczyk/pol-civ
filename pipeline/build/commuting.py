"""Commuter flows into the largest cities (commuting.json), from the NSP 2021 commuting matrix (pl_flows_commuting).

Rule (also written into the file): the 12 most populous cities of cities.json; into each, the flows from other
gminas of at least MIN_FLOW wage employees, the largest MAX_ARCS of them. An arc runs from the centre of the home
gmina (the mean of its hexes) to the city's banner point.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.hexgrid import HexGrid
from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload, write_web

REQUIRES = ["_world", "pl_flows_commuting", "pl_geo_teryt", "cities.json"]
PRODUCES = ["commuting.json"]

N_CITIES = 12
MIN_FLOW = 250
MAX_ARCS = 40
RULE = (f"The {N_CITIES} most populous cities (30 June 2026). Into each: the flows of wage employees from other "
        f"gminas of {MIN_FLOW} people or more, the largest {MAX_ARCS}. NSP 2021 census, 31 March 2021 (GUS); "
        "flows of fewer than 3 people are not published.")

MOTION_RULE = ("On the moving map, dots travel into each city in the morning and home in the afternoon, more of them on "
               "the larger flows. The census counts commuters but not when they travel, so the hours are for show only.")


def gmina_centres(world: dict, grid: HexGrid) -> dict[str, tuple[float, float]]:
    acc: dict[int, list] = {}
    for cell, smp in enumerate(world["county_samples"]):
        for k in smp or ():
            if k >= 0:
                a = acc.setdefault(k, [0.0, 0.0, 0])
                x, y = grid.center(*grid.col_row(cell))
                a[0] += x
                a[1] += y
                a[2] += 1
    return {world["counties"][k][:6]: (a[0] / a[2], a[1] / a[2]) for k, a in acc.items()}


def pick(flows: list[dict], city6: str) -> list[dict]:
    into = [f for f in flows if f["to"][:6] == city6 and f["from"][:6] != city6 and f["value"] >= MIN_FLOW]
    return sorted(into, key=lambda f: (-f["value"], f["from"]))[:MAX_ARCS]


def build() -> None:
    world = load_interim("_world")
    grid = HexGrid(**world["grid"])
    payload = load_interim_payload("pl_flows_commuting")
    data = payload["data"]
    teryt = load_interim("pl_geo_teryt")
    names = {g["code"][:6]: g["name"] for g in teryt["gminy"]}
    tot = {c[:6]: r for c, r in data["tables"]["commuting_gmina"]["rows"].items()}
    centres = gmina_centres(world, grid)
    cities = json.loads((WEB_DATA / "cities.json").read_text())
    big = [c for c in cities if c.get("kind") == "city" and c.get("population")]
    big = sorted(big, key=lambda c: -c["population"])[:N_CITIES]
    out = []
    for c in big:
        g6 = c["gmina"][:6]
        arcs = []
        for f in pick(data["flows"], g6):
            pos = centres.get(f["from"][:6])
            if pos is None:
                continue
            arcs.append({"from": f["from"], "name": names.get(f["from"][:6], f["from"]), "value": f["value"],
                         "x": round(pos[0], 1), "y": round(pos[1], 1)})
        t = tot.get(g6) or {}
        out.append({"id": c["id"], "name": c["name"], "x": c["x"], "y": c["y"], "commuters_in": t.get("commuters_in"),
                    "commuters_out": t.get("commuters_out"), "arcs": arcs})
    write_web("commuting.json", {
        "version": 1,
        "vintage": payload.get("vintage"),
        "sources": ["pl_flows_commuting"],
        "rule": RULE,
        "rules": [RULE, MOTION_RULE],
        "cities": out,
    })
    print(f"    {len(out)} cities, {sum(len(c['arcs']) for c in out)} arcs")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "commuting.json"
    if not path.exists():
        return [("NOTE", "commuting.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    if doc.get("version") != 1 or not doc.get("rule") or not isinstance(doc.get("sources"), list):
        out.append(("FAIL", "commuting.json: version 1, a rule and a sources list are required"))
    for c in doc.get("cities") or []:
        if any(not isinstance(a.get("value"), int) or a["value"] < MIN_FLOW for a in c.get("arcs") or []):
            out.append(("FAIL", f"commuting.json {c.get('name')}: arc values must be whole counts >= {MIN_FLOW}"))
    n = sum(len(c.get("arcs") or []) for c in doc.get("cities") or [])
    top = max(((a["value"], a["name"], c["name"]) for c in doc.get("cities") or [] for a in c.get("arcs") or []),
              default=None)
    out.append(("PASS", f"commuting.json: {len(doc.get('cities') or [])} cities, {n} arcs"
                        + (f"; largest {top[1]} to {top[2]} {top[0]}" if top else "")))
    return out

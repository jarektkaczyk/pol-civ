"""Migration between voivodeships, 1995-2025 (migration.json), from the GUS BDL P1358 matrix (pl_migration_od).

Each of the 240 origin-destination pairs is an arc between the two voivodeship capitals (the voivode's seat where
the seats are split: Bydgoszcz, Gorzow Wielkopolski), with one value per year. Lazy file for the motion layer.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.paths import WEB_DATA
from ..core.store import load_interim_payload, write_web
from .flowgeo import arc, flat

REQUIRES = ["pl_migration_od", "states.json", "cities.json"]
PRODUCES = ["migration.json"]

RULES = [
    "Moves of permanent residence from one voivodeship to another, counted by GUS each year; moves inside a "
    "voivodeship and moves abroad are not included.",
    "Each arc joins two voivodeship capitals; where the seats are split, the voivode's seat is used.",
    "Net migration is arrivals from other voivodeships minus departures to them.",
    "Each moving dot stands for the same number of people on every arc.",
]


def capitals(states: list[dict], cities: list[dict]) -> dict[str, dict]:
    """{voivodeship code: {"name", "x", "y"}} for the voivode's seat."""
    by_gmina = {c["gmina"]: c for c in cities if c.get("gmina")}
    out = {}
    for s in states:
        caps = s.get("capitals") or []
        cap = next((c for c in caps if c.get("role") in ("both", "voivode")), caps[0] if caps else None)
        city = by_gmina.get(cap["gmina"]) if cap else None
        if city is None:
            raise RuntimeError(f"no city point for the capital of {s['name']}")
        out[s["fips"]] = {"name": city["name"], "x": city["x"], "y": city["y"]}
    return out


def build() -> None:
    payload = load_interim_payload("pl_migration_od")
    data = payload["data"]
    states = json.loads((WEB_DATA / "states.json").read_text())
    cities = json.loads((WEB_DATA / "cities.json").read_text())
    caps = capitals(states, cities)
    y0, y1 = data["years"]
    years = list(range(y0, y1 + 1))
    yi = {y: i for i, y in enumerate(years)}
    pairs: dict[tuple[str, str], list] = {}
    for f in data["flows"]:
        pairs.setdefault((f["from"], f["to"]), [None] * len(years))[yi[f["year"]]] = f["value"]
    codes = sorted(caps)
    regions = []
    for s in sorted(states, key=lambda s: s["fips"]):
        c = s["fips"]
        ins = [None] * len(years)
        outs = [None] * len(years)
        for i in range(len(years)):
            vi = [v[i] for (a, b), v in pairs.items() if b == c]
            vo = [v[i] for (a, b), v in pairs.items() if a == c]
            ins[i] = sum(vi) if vi and None not in vi else None
            outs[i] = sum(vo) if vo and None not in vo else None
        net = [a - b if a is not None and b is not None else None for a, b in zip(ins, outs)]
        regions.append({"code": c, "abbr": s["abbr"], "name": s["name"], "capital": caps[c]["name"],
                        "x": caps[c]["x"], "y": caps[c]["y"], "in": ins, "out": outs, "net": net})
    flows = []
    for (a, b), values in sorted(pairs.items()):
        if a not in caps or b not in caps:
            continue
        pa, pb = (caps[a]["x"], caps[a]["y"]), (caps[b]["x"], caps[b]["y"])
        flows.append({"from": a, "to": b, "unit": "persons", "values": values, "path": flat(arc(pa, pb), tol=0)})
    write_web("migration.json", {
        "version": 1,
        "vintage": payload.get("vintage"),
        "sources": ["pl_migration_od"],
        "rules": RULES,
        "unit": "persons",
        "period": "year",
        "years": years,
        "regions": regions,
        "flows": flows,
    })
    print(f"    {len(regions)} voivodeships, {len(flows)} pairs, {years[0]}-{years[-1]}")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "migration.json"
    if not path.exists():
        return [("NOTE", "migration.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    if doc.get("version") != 1 or not doc.get("rules") or not isinstance(doc.get("sources"), list):
        out.append(("FAIL", "migration.json: version 1, rules and a sources list are required"))
    years = doc.get("years") or []
    regions = doc.get("regions") or []
    flows = doc.get("flows") or []
    if len(regions) != 16:
        out.append(("FAIL", f"migration.json: {len(regions)} voivodeships, expected 16"))
    for f in flows:
        vals = f.get("values") or []
        if len(vals) != len(years) or any(v is not None and (not isinstance(v, int) or v < 0) for v in vals):
            out.append(("FAIL", f"migration.json {f.get('from')}->{f.get('to')}: values must be whole counts per year"))
            break
        p = f.get("path") or []
        if len(p) < 4 or len(p) % 2:
            out.append(("FAIL", f"migration.json {f.get('from')}->{f.get('to')}: path must be a flat x, y array"))
            break
    if regions and years:
        last = len(years) - 1
        top = max((r for r in regions if r["net"][last] is not None), key=lambda r: r["net"][last], default=None)
        out.append(("PASS", f"migration.json: {len(flows)} pairs, {years[0]}-{years[-1]}"
                            + (f"; largest net gain {years[-1]}: {top['name']} {top['net'][last]:+d}" if top else "")))
    return out

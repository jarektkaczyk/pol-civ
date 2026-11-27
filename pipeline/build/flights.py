"""Air routes from Polish airports for the Flights motion layer (lazy web/data/flights.json).

Every route carries its monthly passengers (`value`, one number or null per month of `months`) and an end
point `end` in map km: the partner airport itself when it lies on the map, otherwise the point where the
great circle from the Polish airport leaves the map (its initial true bearing is in `bearing`).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from ..core.fetch import read_manifest
from ..core.geo import MapProjection
from ..core.store import load_interim, load_interim_payload, write_web

REQUIRES = ["_world", "pl_air_routes"]
PRODUCES = ["flights.json"]

R_KM = 6371.0088
TOP_N = 10

# Eurostat re-use notice (ec.europa.eu/eurostat/help/copyright-notice): credit Eurostat, state the changes and that
# Eurostat is not responsible for them. The Almanac's "Moving layers" page shows this object.
PROCESSED = "We selected the 12 latest months, matched airports to OurAirports positions and drew routes as arcs."
EUROSTAT_DISCLAIMER = "Eurostat is not responsible for the changes."


def attribution(retrieved: str | None) -> dict:
    """Credit, download time (UTC), the changes made and Eurostat's disclaimer."""
    return {"credit": ["Eurostat (avia_par_pl)"], "created": None, "retrieved": utc_minute(retrieved),
            "processed": PROCESSED, "disclaimer": EUROSTAT_DISCLAIMER}


def utc_minute(text: str | None) -> str | None:
    """'2026-11-27T07:00:17+00:00' -> '2026-11-27T07:00Z' (manifest times are UTC)."""
    return f"{text[:16]}Z" if text else None


RULES = [
    "Routes between the main Polish airports and their partner airports with passengers in the newest 12 months "
    "Eurostat publishes.",
    "Passengers are those carried on the route in both directions in each month.",
    "Routes to airports beyond the map end at the map edge, in the true direction of the destination.",
    "Each domestic route is reported by both of its airports and is listed from each end.",
]


def _proj(world: dict) -> MapProjection:
    cfg = world["projection"]
    return MapProjection(min_x=cfg["min_x"], max_y=cfg["max_y"], margin=cfg["margin"])


def bearing_deg(lon1, lat1, lon2, lat2) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def gc_km(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * R_KM * math.asin(min(1.0, math.sqrt(h)))


def destination(lon, lat, brg, km) -> tuple[float, float]:
    """Point `km` along the great circle from (lon, lat) on initial bearing `brg`."""
    d, b = km / R_KM, math.radians(brg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(l2), math.degrees(p2)


def edge_point(x0, y0, dx, dy, w, h) -> tuple[float, float]:
    """Where the ray from (x0, y0) in direction (dx, dy) leaves the rectangle [0, w] x [0, h]."""
    ts = []
    if dx > 0:
        ts.append((w - x0) / dx)
    elif dx < 0:
        ts.append(-x0 / dx)
    if dy > 0:
        ts.append((h - y0) / dy)
    elif dy < 0:
        ts.append(-y0 / dy)
    t = min(t for t in ts if t >= 0) if ts else 0.0
    return x0 + t * dx, y0 + t * dy


def r1(v: float) -> float:
    return round(v, 1) + 0.0  # + 0.0 turns -0.0 into 0.0


def build_doc(data: dict, proj, w: float, h: float, vintage: str | None, retrieved: str | None = None) -> dict:
    pts = {p["props"]["icao"]: p for p in data["points"]}
    used = {r["from"] for r in data["routes"]} | {r["to"] for r in data["routes"]}
    order = sorted(used, key=lambda c: (not pts[c]["props"]["polish"], pts[c]["name"] or c))
    index = {c: i for i, c in enumerate(order)}
    airports = []
    for c in order:
        p, pr = pts[c], pts[c]["props"]
        on_map = False
        x = y = None
        if p["lon"] is not None:
            px, py = proj(p["lon"], p["lat"])
            on_map = 0 <= px <= w and 0 <= py <= h
            if on_map:
                x, y = r1(px), r1(py)
        airports.append({
            "icao": c, "iata": pr.get("iata"), "name": p["name"],
            # short names for cards: Polish airports keep their Polish name in both languages
            "label": p["name"] if pr["polish"] else (pr.get("label") or p["name"]),
            "label_pl": p["name"] if pr["polish"] else (pr.get("label_pl") or pr.get("label") or p["name"]),
            "city": pr.get("city") or pr.get("municipality"), "city_pl": pr.get("city_pl"),
            "country": pr.get("country"), "country_name": pr.get("country_name"), "polish": pr["polish"],
            "x": x, "y": y, "on_map": on_map,
        })

    routes, by_airport = [], defaultdict(list)
    for r in data["routes"]:
        a, b = pts[r["from"]], pts[r["to"]]
        if a["lon"] is None or b["lon"] is None:
            end = brg = km = None
        else:
            brg = bearing_deg(a["lon"], a["lat"], b["lon"], b["lat"])
            km = gc_km(a["lon"], a["lat"], b["lon"], b["lat"])
            dest = airports[index[r["to"]]]
            if dest["on_map"]:
                end = [dest["x"], dest["y"]]
            else:
                x0, y0 = proj(a["lon"], a["lat"])
                x1, y1 = proj(*destination(a["lon"], a["lat"], brg, 50.0))
                ex, ey = edge_point(x0, y0, x1 - x0, y1 - y0, w, h)
                end = [r1(ex), r1(ey)]
        total = sum(v for v in r["passengers"] if v is not None)
        by_airport[r["from"]].append((total, len(routes)))
        routes.append({
            "from": index[r["from"]], "to": index[r["to"]], "domestic": r["domestic"],
            "value": [None if v is None else int(round(v)) for v in r["passengers"]], "unit": "passengers",
            "total": int(round(total)), "end": end, "bearing": None if brg is None else round(brg, 1),
            "km": None if km is None else int(round(km)),
        })

    for i, a in enumerate(airports):
        if a["polish"]:
            ranked = sorted(by_airport[a["icao"]], key=lambda t: (-t[0], t[1]))
            a["routes"] = len(ranked)
            a["top"] = [k for _, k in ranked[:TOP_N]]
            months = len(data["months"])
            a["value"] = [sum(routes[k]["value"][m] or 0 for _, k in ranked) or None for m in range(months)]

    return {
        "version": 1,
        "vintage": vintage,
        "sources": ["pl_air_routes"],
        "months": data["months"],
        "period": f"{data['months'][0]}/{data['months'][-1]}",
        "unit": "passengers",
        "rules": RULES,
        "attribution": attribution(retrieved),
        "airports": airports,
        "routes": routes,
    }


def build() -> None:
    world = load_interim("_world")
    w, h = world.get("width"), world.get("height")
    if w is None or h is None:
        wj = json.loads((Path(__file__).resolve().parents[2] / "web" / "data" / "world.json").read_text())
        w, h = wj["width"], wj["height"]
    payload = load_interim_payload("pl_air_routes")
    retrieved = (read_manifest("pl_air_routes").get("avia_par_pl_monthly.json") or {}).get("retrieved")
    write_web("flights.json", build_doc(payload["data"], _proj(world), w, h, payload.get("vintage"), retrieved))


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "flights.json"
    if not path.exists():
        return [("NOTE", "flights.json not built (optional)")]
    doc = json.loads(path.read_text())
    problems = []
    for key in ("version", "vintage", "sources", "rules", "months", "airports", "routes"):
        if key not in doc:
            problems.append(f"missing key {key}")
    months, na = doc.get("months") or [], len(doc.get("airports") or [])
    for i, r in enumerate(doc.get("routes") or []):
        if not (0 <= r.get("from", -1) < na and 0 <= r.get("to", -1) < na):
            problems.append(f"route {i}: bad airport index")
            continue
        if len(r.get("value") or []) != len(months):
            problems.append(f"route {i}: {len(r.get('value') or [])} values for {len(months)} months")
        if any(v is not None and v < 0 for v in r.get("value") or []):
            problems.append(f"route {i}: negative value")
        if r.get("end") is None:
            problems.append(f"route {i}: no end point")
        if not doc["airports"][r["from"]].get("polish"):
            problems.append(f"route {i}: starts at a foreign airport")
    out = [("FAIL", f"flights.json: {p}") for p in problems[:12]]
    if not problems:
        pl = sum(1 for a in doc["airports"] if a.get("polish"))
        out.append(("PASS", f"flights.json: {len(doc['routes'])} routes from {pl} Polish airports to "
                            f"{na - pl} partners, months {months[0]} to {months[-1]}"))
    kb = path.stat().st_size / 1e3
    out.append(("PASS" if kb < 3000 else "WARN", f"flights.json {kb:.0f} kB (lazy)"))
    return out

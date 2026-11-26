"""Polish regional freight flows drawn as caravan routes between voivodeships."""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from pathlib import Path

from ..core.hexgrid import HexGrid
from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload, write_web
from .infrastructure import STATE_ABBR

REQUIRES = ["_world", "pl_geo_teryt", "pl_transport_freight", "infrastructure.json", "states.json", "cities.json"]
PRODUCES = ["trade.json"]

TOP_N = 30
MIN_KM = 100
PARTNERS = 5
STEP_COST = {"motorway": 1.0, "expressway": 1.25, "rail": 1.4, "land": 4.0, "water": 10.0}

RULE = (
    "The 30 largest published rail freight flows between Polish voivodeships whose capital-city anchors are at least 100 km "
    "apart, ranked by tonnes and summed in both directions. Eurostat publishes road freight loaded and unloaded by "
    "NUTS 3 region, but no road origin-destination matrix, so those road figures appear as regional totals and are "
    "not turned into routes."
)
PATH_NOTE = (
    "The source gives each shipment's origin and destination region, not its route. The drawn path follows mapped "
    "motorways, expressways, and rail links as a visual guide only."
)


def build_zones(world: dict, teryt: dict, states: list[dict], cities: list[dict]) -> dict[str, dict]:
    names = {row["code"]: row["name"] for row in teryt["voivodeships"]}
    state_by_code = {row["fips"]: row for row in states}
    city_by_id = {str(row["id"]): row for row in cities}
    gmina_count = defaultdict(int)
    for code in world["counties"]:
        gmina_count[code[:2]] += 1
    zones = {}
    for state_index, code in enumerate(world["states"]):
        cells = [cell for cell, owner in enumerate(world["owner"]) if owner == state_index]
        if not cells:
            continue
        capitals = state_by_code.get(code, {}).get("capitals") or []
        seat = next((row for row in capitals if row.get("role") in {"voivode", "both"}), None)
        capital = city_by_id.get(str(seat.get("gmina"))) if seat else None
        if capital is None:
            raise ValueError(f"missing voivode capital for voivodeship {code}")
        cell = int(capital["cell"])
        x, y = float(capital["x"]), float(capital["y"])
        zones[code] = {
            "id": code, "name": names.get(code, code), "short": names.get(code, code),
            "kind": "voivodeship", "states": [STATE_ABBR.get(code)], "cities": [capital["id"]],
            "counties": gmina_count[code],
            "anchor": {"cell": cell, "x": round(x, 1), "y": round(y, 1), "city": capital["name"]},
        }
    return zones


def aggregate_flows(flows: list[dict], zones: dict[str, dict]) -> dict[tuple[str, str], float]:
    pairs = defaultdict(float)
    for flow in flows:
        if flow.get("mode") != "rail" or flow.get("level") != "voivodeship":
            continue
        a, b = str(flow.get("from")), str(flow.get("to"))
        value = flow.get("value")
        if a not in zones or b not in zones or a == b or not isinstance(value, (int, float)):
            continue
        pairs[tuple(sorted((a, b)))] += value
    return dict(pairs)


def road_graph(infrastructure: dict | None) -> dict[tuple[int, int], float]:
    costs = {}
    if not infrastructure:
        return costs
    classes = [row["id"] for row in infrastructure.get("road_classes") or []]
    for a, b, tier, *_ in infrastructure.get("rail") or []:
        costs[(a, b)] = STEP_COST["rail"] + 0.2 * int(tier)
    for a, b, cls, *_ in infrastructure.get("roads") or []:
        kind = classes[cls] if 0 <= cls < len(classes) else "expressway"
        costs[(a, b)] = min(costs.get((a, b), math.inf), STEP_COST.get(kind, STEP_COST["expressway"]))
    return costs


def shortest_path(grid: HexGrid, owner: list[int], links: dict, src: int, dst: int) -> list[int]:
    """Return the cheapest neighbouring-cell path, preferring mapped transport links."""
    def heuristic(cell: int) -> float:
        x0, y0 = grid.center(*grid.col_row(cell))
        x1, y1 = grid.center(*grid.col_row(dst))
        return math.hypot(x1 - x0, y1 - y0) / (math.sqrt(3) * grid.radius)

    best = {src: 0.0}
    previous = {}
    heap = [(heuristic(src), 0.0, src)]
    while heap:
        _, distance, cell = heapq.heappop(heap)
        if cell == dst:
            break
        if distance > best.get(cell, math.inf):
            continue
        for near in grid.neighbours(cell):
            pair = (cell, near) if cell < near else (near, cell)
            step = links.get(pair)
            if step is None:
                step = STEP_COST["land"] if owner[near] >= 0 else STEP_COST["water"]
            candidate = distance + step
            if candidate < best.get(near, math.inf):
                best[near] = candidate
                previous[near] = cell
                heapq.heappush(heap, (candidate + heuristic(near), candidate, near))
    if dst not in best:
        return []
    path = [dst]
    while path[-1] != src:
        path.append(previous[path[-1]])
    return path[::-1]


def road_freight_table(data: dict) -> dict:
    table = (data.get("tables") or {}).get("road_freight_nuts3") or {}
    fields = table.get("fields") or {}
    keys = list(fields)
    rows = table.get("rows") or {}
    year = next((meta.get("year") for meta in fields.values() if meta.get("year") is not None), None)
    return {
        "level": "nuts3", "year": year,
        "fields": [{"key": key, **fields[key]} for key in keys],
        "rows": [[code, *(values.get(key) for key in keys)] for code, values in sorted(rows.items())],
    }


def build() -> None:
    world = load_interim("_world")
    teryt = load_interim("pl_geo_teryt")
    freight_payload = load_interim_payload("pl_transport_freight")
    freight = freight_payload["data"]
    infrastructure_path = WEB_DATA / "infrastructure.json"
    infrastructure = json.loads(infrastructure_path.read_text()) if infrastructure_path.exists() else None
    states = json.loads((WEB_DATA / "states.json").read_text())
    cities = json.loads((WEB_DATA / "cities.json").read_text())
    grid = HexGrid(**world["grid"])
    zones = build_zones(world, teryt, states, cities)
    pairs = aggregate_flows(freight.get("flows") or [], zones)
    candidates = []
    for (a, b), value in pairs.items():
        za, zb = zones[a], zones[b]
        distance = math.dist((za["anchor"]["x"], za["anchor"]["y"]), (zb["anchor"]["x"], zb["anchor"]["y"]))
        if distance >= MIN_KM and value > 0:
            candidates.append((value, distance, a, b))
    candidates.sort(key=lambda row: (-row[0], row[2], row[3]))

    links = road_graph(infrastructure)
    routes = []
    partners = defaultdict(list)
    totals = defaultdict(float)
    year = max((flow.get("year") or 0 for flow in freight.get("flows") or []), default=None)
    for a, b in pairs:
        value = pairs[(a, b)]
        partners[a].append([b, round(value, 1), "rail"])
        partners[b].append([a, round(value, 1), "rail"])
        totals[a] += value
        totals[b] += value
    for rank, (value, distance, a, b) in enumerate(candidates[:TOP_N], 1):
        path = shortest_path(grid, world["owner"], links, zones[a]["anchor"]["cell"], zones[b]["anchor"]["cell"])
        routes.append({
            "a": a, "b": b, "rank": rank, "value_kt": round(value, 1), "tons_k": round(value, 1),
            "modes": {"rail": 1.0}, "top_mode": "rail", "dist_km": round(distance), "path": path,
        })
    for code, zone in zones.items():
        zone["partners"] = sorted(partners[code], key=lambda row: (-row[1], row[0]))[:PARTNERS]
        zone["totals_kt"] = {"within": None, "other_zones": round(totals[code], 1)}

    write_web("trade.json", {
        "version": 1,
        "vintage": freight_payload.get("vintage"),
        "year": year,
        "sources": ["pl_transport_freight"],
        "rule": RULE,
        "path_note": PATH_NOTE,
        "units": {"value_kt": "thousand tonnes"},
        "modes": [{"id": "rail", "name": "Rail"}],
        "national_kt": {"interregional_rail": round(sum(pairs.values()), 1)},
        "road_freight": road_freight_table(freight),
        "zones": [zones[code] for code in sorted(zones)],
        "routes": routes,
    })
    print(f"    {len(zones)} voivodeships, {len(candidates)} pairs at least {MIN_KM} km apart, {len(routes)} routes")


def check(web_dir) -> list[tuple[str, str]]:
    web_dir = Path(web_dir)
    path = web_dir / "trade.json"
    if not path.exists():
        return [("NOTE", "trade.json not built")]
    out = []
    fail = lambda message: out.append(("FAIL", f"trade.json: {message}"))
    try:
        doc = json.loads(path.read_text())
        world = json.loads((web_dir / "world.json").read_text())
    except (OSError, ValueError) as exc:
        return [("FAIL", f"trade.json: cannot read output: {exc}")]
    size = int(world["grid"]["cols"]) * int(world["grid"]["rows"])
    grid = HexGrid(**world["grid"])
    zones = {zone.get("id") for zone in doc.get("zones") or []}
    routes = doc.get("routes") or []
    for route in routes:
        if route.get("a") not in zones or route.get("b") not in zones or route.get("value_kt", 0) <= 0:
            fail("route has an unknown zone or non-positive value")
            break
        path_cells = route.get("path") or []
        if not path_cells or any(not isinstance(cell, int) or not 0 <= cell < size for cell in path_cells):
            fail("route has an empty or invalid path")
            break
        if any(b not in grid.neighbours(a) for a, b in zip(path_cells, path_cells[1:])):
            fail("route path contains non-neighbouring cells")
            break
    if len(routes) > TOP_N:
        fail(f"more than {TOP_N} routes")
    if not any(level == "FAIL" for level, _ in out):
        out.append(("PASS", f"trade: {len(routes)} routes between {len(zones)} voivodeships; "
                            f"{len(doc.get('road_freight', {}).get('rows') or [])} road-freight regional totals"))
    return out

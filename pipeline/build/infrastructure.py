"""Poland's motorways, expressways, railways, ports, and airports on the hex map."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ..core.geo import MapProjection
from ..core.hexgrid import HexGrid
from ..core.store import load_interim, load_interim_payload, write_web

REQUIRES = [
    "_world",
    "pl_transport_network",
    "pl_transport_osm",
    "pl_transport_airports",
    "pl_transport_ports",
]
PRODUCES = ["infrastructure.json"]

SAMPLE_KM = 2.5
SITE_RINGS = 3

ROAD_CLASSES = [
    {"id": "motorway", "name": "Motorway"},
    {"id": "expressway", "name": "Expressway"},
]
RAIL_TIERS = [
    {"id": "main", "name": "Main line"},
    {"id": "secondary", "name": "Other mapped line"},
]

RULES = {
    "roads": (
        "Every open Polish A-road and S-road in the OpenStreetMap extract, plus motorway-class links without an "
        "A or S number. Each line is sampled every 2.5 km and snapped to neighbouring hex-centre links."
    ),
    "rail": (
        "Every main railway line in the OpenStreetMap extract. Central Rail Line links, high-speed links, and "
        "lines tagged for at least 160 km/h use the main tier; the other mapped lines use the secondary tier."
    ),
    "ports": (
        "The five main seaports reported by GUS and Eurostat, the named smaller commercial ports, and the LNG "
        "terminals in the source list. Ports with no published coordinates stay out of the map."
    ),
    "airports": "The Polish airports with scheduled passenger traffic in the source list, plus the planned CPK hub.",
}

STATE_ABBR = {
    "02": "DS", "04": "KP", "06": "LU", "08": "LB", "10": "LD", "12": "MA", "14": "MZ", "16": "OP",
    "18": "PK", "20": "PD", "22": "PM", "24": "SL", "26": "SK", "28": "WN", "30": "WP", "32": "ZP",
}


def map_projection(config: dict) -> MapProjection:
    """Build the shifted map projection from the shared interim metadata."""
    return MapProjection(**{key: config[key] for key in ("min_x", "max_y", "margin")})


def _axial(grid: HexGrid, cell: int) -> tuple[int, int]:
    col, row = grid.col_row(cell)
    return col - (row - (row & 1)) // 2, row


def _from_axial(grid: HexGrid, q: int, r: int) -> int:
    col = q + (r - (r & 1)) // 2
    if 0 <= col < grid.cols and 0 <= r < grid.rows:
        return grid.index(col, r)
    return -1


def hex_distance(grid: HexGrid, a: int, b: int) -> int:
    (q1, r1), (q2, r2) = _axial(grid, a), _axial(grid, b)
    return (abs(q1 - q2) + abs(r1 - r2) + abs((q1 + r1) - (q2 + r2))) // 2


def hex_walk(grid: HexGrid, a: int, b: int) -> list[int]:
    """Return the cells on the straight hex line from a to b, including both ends."""
    n = hex_distance(grid, a, b)
    if n <= 1:
        return [a, b] if a != b else [a]
    (q1, r1), (q2, r2) = _axial(grid, a), _axial(grid, b)
    out = []
    for i in range(n + 1):
        t = i / n
        x = q1 + (q2 - q1) * t + 1e-6
        z = r1 + (r2 - r1) * t + 1e-6
        y = -x - z
        rx, ry, rz = round(x), round(y), round(z)
        dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
        if dx > dy and dx > dz:
            rx = -ry - rz
        elif dy <= dz:
            rz = -rx - ry
        cell = _from_axial(grid, rx, rz)
        if cell >= 0 and (not out or out[-1] != cell):
            out.append(cell)
    return out


def sample_cells(grid: HexGrid, pts: list[tuple[float, float]]) -> list[list[int]]:
    """Sample a projected line and return runs of distinct cells."""
    runs, run = [], []

    def add(x: float, y: float) -> None:
        cell = grid.cell_at(x, y)
        if cell >= 0 and (not run or run[-1] != cell):
            run.append(cell)

    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / SAMPLE_KM))
        for i in range(steps):
            t = i / steps
            add(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
    if pts:
        add(*pts[-1])
    if len(run) > 1:
        runs.append(run)
    return runs


def straighten(grid: HexGrid, run: list[int]) -> list[int]:
    """Remove corner-clipping detours that make a line zigzag between two rows."""
    out = []
    for cell in run:
        while len(out) >= 2 and cell in grid.neighbours(out[-2]):
            out.pop()
        if not out or out[-1] != cell:
            out.append(cell)
    return out


def links_of(grid: HexGrid, run: list[int]) -> list[tuple[int, int]]:
    if len(run) < 2:
        return []
    filled = [run[0]]
    for a, b in zip(run, run[1:]):
        filled.extend(hex_walk(grid, a, b)[1:])
    filled = straighten(grid, filled)
    out = []
    for a, b in zip(filled, filled[1:]):
        path = hex_walk(grid, a, b)
        for u, v in zip(path, path[1:]):
            if u != v:
                out.append((u, v) if u < v else (v, u))
    return out


def _route_key(name: str) -> tuple:
    digits = "".join(ch for ch in name if ch.isdigit())
    return (int(digits) if digits else 99999, name)


def build_roads(grid: HexGrid, proj: MapProjection, owner: list[int], lines: list[dict]) -> list[list]:
    class_of: dict[tuple[int, int], int] = {}
    names: dict[tuple[int, int], Counter] = defaultdict(Counter)
    for feature in lines:
        kind = feature.get("kind")
        if kind not in {"motorway", "expressway", "motorway_other"}:
            continue
        cls = 0 if kind in {"motorway", "motorway_other"} else 1
        name = feature.get("ref") or feature.get("name")
        pts = [proj(lon, lat) for lon, lat in feature.get("coords") or []]
        for run in sample_cells(grid, pts):
            for pair in links_of(grid, run):
                a, b = pair
                if owner[a] < 0 and owner[b] < 0:
                    continue
                previous = class_of.get(pair, 9)
                if cls < previous:
                    class_of[pair] = cls
                    names[pair].clear()
                if cls == class_of.get(pair) and name:
                    names[pair][name] += 1
    out = []
    for (a, b), cls in sorted(class_of.items()):
        name = min(names[(a, b)], key=_route_key) if names[(a, b)] else None
        out.append([a, b, cls, name])
    return out


def build_rail(grid: HexGrid, proj: MapProjection, owner: list[int], lines: list[dict]) -> list[list]:
    tier_of: dict[tuple[int, int], int] = {}
    for feature in lines:
        if feature.get("kind") != "rail_main":
            continue
        tier = 0 if feature.get("cmk") or feature.get("highspeed") or (feature.get("maxspeed") or 0) >= 160 else 1
        pts = [proj(lon, lat) for lon, lat in feature.get("coords") or []]
        for run in sample_cells(grid, pts):
            for pair in links_of(grid, run):
                a, b = pair
                if owner[a] < 0 and owner[b] < 0:
                    continue
                tier_of[pair] = min(tier, tier_of.get(pair, 9))
    return [[a, b, tier] for (a, b), tier in sorted(tier_of.items())]


class Locator:
    """Place a lon/lat point and attach its Polish administrative codes."""

    def __init__(self, world: dict):
        self.world = world
        self.grid = HexGrid(**world["grid"])
        self.proj = map_projection(world["projection"])
        self.owner = world["owner"]
        self.county = world["county"]
        self.gminy = world["counties"]
        self.states = world["states"]

    def nearest_land(self, cell: int, rings: int = SITE_RINGS) -> int:
        if cell < 0:
            return -1
        if self.owner[cell] >= 0:
            return cell
        seen, frontier = {cell}, [cell]
        for _ in range(rings):
            nxt = []
            for current in frontier:
                for near in self.grid.neighbours(current):
                    if near not in seen:
                        seen.add(near)
                        nxt.append(near)
            land = [near for near in nxt if self.owner[near] >= 0]
            if land:
                x, y = self.grid.center(*self.grid.col_row(cell))
                return min(land, key=lambda near: math.dist(self.grid.center(*self.grid.col_row(near)), (x, y)))
            frontier = nxt
        return -1

    def place(self, lon, lat, *, keep_water: bool = False, rings: int = SITE_RINGS) -> dict | None:
        if lon is None or lat is None:
            return None
        x, y = self.proj(float(lon), float(lat))
        true_cell = self.grid.cell_at(x, y)
        land_cell = self.nearest_land(true_cell, rings)
        if land_cell < 0:
            return None
        cell = true_cell if keep_water and true_cell >= 0 else land_cell
        state_index = self.owner[land_cell]
        county_index = self.county[land_cell]
        gmina = self.gminy[county_index] if county_index >= 0 else None
        state_code = self.states[state_index] if state_index >= 0 else None
        return {
            "x": round(x, 1), "y": round(y, 1), "cell": cell,
            "gmina": gmina, "county": gmina, "powiat": gmina[:4] if gmina else None,
            "cbsa": None, "state": STATE_ABBR.get(state_code),
        }


def build_ports(locator: Locator, points: list[dict]) -> list[dict]:
    ranked = sorted(points, key=lambda p: (-(p.get("props", {}).get("cargo_kt") or -1), p.get("name") or ""))
    out = []
    for point in ranked:
        props = point.get("props") or {}
        at = locator.place(point.get("lon"), point.get("lat"))
        if at is None:
            continue
        kind = point.get("kind")
        out.append({
            "id": point["id"], "name": point["name"],
            "type": "seaport" if kind == "seaport" else kind,
            "rank": len(out) + 1,
            "cargo_kt": props.get("cargo_kt"), "international_kt": props.get("international_kt"),
            "unloading_kt": props.get("unloading_kt"), "loading_kt": props.get("loading_kt"),
            "transit_kt": props.get("transit_kt"), "teu": props.get("teu"),
            "year": props.get("cargo_year") or props.get("teu_year"),
            "status": props.get("status") or "operating", "operator": props.get("operator"),
            "capacity_bcm": props.get("capacity_bcm"), "ref": props.get("ref"),
            **at,
        })
    return out


def build_airports(locator: Locator, points: list[dict]) -> list[dict]:
    ranked = sorted(points, key=lambda p: (-(p.get("props", {}).get("passengers") or -1), p.get("name") or ""))
    out = []
    for point in ranked:
        props = point.get("props") or {}
        at = locator.place(point.get("lon"), point.get("lat"))
        if at is None:
            continue
        out.append({
            "id": point["id"], "name": point["name"], "icao": props.get("icao"), "iata": props.get("iata"),
            "rank": len(out) + 1, "passengers": props.get("passengers"),
            "passengers_prev": props.get("passengers_prev"), "freight_t": props.get("freight_t"),
            "year": props.get("passengers_year") or props.get("freight_year"),
            "status": props.get("status"), "status_note": props.get("status_note"),
            "opening_planned": props.get("opening_planned"), "ref": props.get("ref"),
            "wikidata": props.get("wikidata"),
            **at,
        })
    return out


def _country_row(data: dict, table: str) -> dict:
    return ((data.get("tables") or {}).get(table, {}).get("rows") or {}).get("PL", {})


def build() -> None:
    world = load_interim("_world")
    osm_payload = load_interim_payload("pl_transport_osm")
    network_payload = load_interim_payload("pl_transport_network")
    airport_payload = load_interim_payload("pl_transport_airports")
    port_payload = load_interim_payload("pl_transport_ports")
    osm = osm_payload["data"]
    network = network_payload["data"]
    airport_data = airport_payload["data"]
    port_data = port_payload["data"]

    grid = HexGrid(**world["grid"])
    proj = map_projection(world["projection"])
    roads = build_roads(grid, proj, world["owner"], osm.get("lines") or [])
    rail = build_rail(grid, proj, world["owner"], osm.get("lines") or [])
    locator = Locator(world)
    ports = build_ports(locator, port_data.get("points") or [])
    airports = build_airports(locator, airport_data.get("points") or [])

    write_web("infrastructure.json", {
        "version": 1,
        "vintage": {
            "roads": osm_payload.get("vintage"), "rail": osm_payload.get("vintage"),
            "network": network_payload.get("vintage"), "ports": port_payload.get("vintage"),
            "airports": airport_payload.get("vintage"),
        },
        "sources": ["pl_transport_osm", "pl_transport_network", "pl_transport_ports", "pl_transport_airports"],
        "rules": RULES,
        "road_classes": ROAD_CLASSES,
        "rail_tiers": RAIL_TIERS,
        "roads": roads,
        "rail": rail,
        "ports": ports,
        "airports": airports,
        "totals": {
            "network": _country_row(network, "network_country"),
            "ports": _country_row(port_data, "ports_country"),
            "airports": _country_row(airport_data, "airports_country"),
        },
    })
    print(f"    {len(roads)} road links, {len(rail)} rail links, {len(ports)} ports, {len(airports)} airports")


def check(web_dir) -> list[tuple[str, str]]:
    web_dir = Path(web_dir)
    path = web_dir / "infrastructure.json"
    if not path.exists():
        return [("NOTE", "infrastructure.json not built")]
    out = []
    fail = lambda message: out.append(("FAIL", f"infrastructure.json: {message}"))
    try:
        doc = json.loads(path.read_text())
        world = json.loads((web_dir / "world.json").read_text())
    except (OSError, ValueError) as exc:
        return [("FAIL", f"infrastructure.json: cannot read output: {exc}")]
    size = int(world["grid"]["cols"]) * int(world["grid"]["rows"])
    grid = HexGrid(**world["grid"])
    for key in ("version", "vintage", "sources", "rules", "roads", "rail", "ports", "airports"):
        if key not in doc:
            fail(f"missing key {key}")
    for label, rows in (("roads", doc.get("roads") or []), ("rail", doc.get("rail") or [])):
        bad = [row for row in rows if len(row) < 3 or not (0 <= row[0] < row[1] < size) or row[1] not in grid.neighbours(row[0])]
        if bad:
            fail(f"{len(bad)} malformed or non-neighbouring {label} links")
    for label in ("ports", "airports"):
        bad = [site.get("id") for site in doc.get(label) or [] if not isinstance(site.get("cell"), int) or not 0 <= site["cell"] < size]
        if bad:
            fail(f"{len(bad)} {label} have invalid cells")
    if not any(level == "FAIL" for level, _ in out):
        out.append(("PASS", f"infrastructure: {len(doc['roads'])} road links, {len(doc['rail'])} rail links, "
                            f"{len(doc['ports'])} ports, {len(doc['airports'])} airports"))
    return out

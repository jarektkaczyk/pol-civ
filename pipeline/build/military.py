"""Build Poland's garrisons, training areas, troop totals and 2026 defence budget."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ..core.geo import MapProjection
from ..core.hexgrid import HexGrid
from ..core.store import load_interim, load_interim_payload, write_web

REQUIRES = ["_world", "pl_soc_military"]
PRODUCES = ["military.json"]

STATE_ABBR = {
    "02": "DS", "04": "KP", "06": "LU", "08": "LB", "10": "LD", "12": "MA", "14": "MZ", "16": "OP",
    "18": "PK", "20": "PD", "22": "PM", "24": "SL", "26": "SK", "28": "WN", "30": "WP", "32": "ZP",
}
BRANCH = {"land": "land", "special": "land", "air": "air", "navy": "navy",
          "territorial": "territorial", "allied": "allied"}
COMPONENTS = [
    {"id": "land", "name": "Land Forces", "branches": ["land", "special"]},
    {"id": "air", "name": "Air Force", "branches": ["air"]},
    {"id": "navy", "name": "Navy", "branches": ["navy"]},
    {"id": "territorial", "name": "Territorial Defence Force", "branches": ["territorial"]},
    {"id": "allied", "name": "US and NATO", "branches": ["allied"]},
]
INSTALLATION_RULE = (
    "One map fort per garrison town and branch. Land Forces include Special Forces. The source list includes every "
    "division and brigade active or forming in 2026, Air Force wings and brigades, Navy flotillas and naval aviation, "
    "Special Forces units, Territorial Defence brigades, listed air and naval bases, and named US or NATO sites."
)
TIER_RULE = ("A garrison is major when the branch has at least four listed units or bases in the town, base with two "
             "or three, and site with one. The tier measures entries in the published list, not personnel.")
RANGE_RULE = ("Every main training area in the source is shown as restricted ground at its published point. "
              "Published area is included when available; the source has no boundary polygons.")


class Locator:
    """Place a Polish point on the nearest Polish land cell."""

    def __init__(self, world: dict):
        self.world = world
        self.grid = HexGrid(**world["grid"])
        projection = world["projection"]
        self.proj = MapProjection(**{key: projection[key] for key in ("min_x", "max_y", "margin")})
        self.owner = world["owner"]
        self.county = world["county"]
        self.counties = world["counties"]
        self.states = world["states"]

    def land_cell(self, x: float, y: float, rings: int = 3) -> int:
        cell = self.grid.cell_at(x, y)
        if cell < 0:
            return -1
        if self.owner[cell] >= 0:
            return cell
        seen, frontier = {cell}, [cell]
        for _ in range(rings):
            nxt = []
            for current in frontier:
                for neighbour in self.grid.neighbours(current):
                    if neighbour not in seen:
                        seen.add(neighbour)
                        nxt.append(neighbour)
            land = [candidate for candidate in nxt if self.owner[candidate] >= 0]
            if land:
                return min(land, key=lambda candidate: math.dist(
                    self.grid.center(*self.grid.col_row(candidate)), (x, y)))
            frontier = nxt
        return -1

    def place(self, lon: float | None, lat: float | None) -> dict | None:
        if lon is None or lat is None:
            return None
        x, y = self.proj(float(lon), float(lat))
        cell = self.land_cell(x, y)
        if cell < 0:
            return None
        county_index = self.county[cell]
        state_index = self.owner[cell]
        return {
            "x": round(x, 1), "y": round(y, 1), "cell": cell,
            "county": self.counties[county_index] if county_index >= 0 else None,
            "state": STATE_ABBR.get(self.states[state_index]) if state_index >= 0 else None,
        }


def _tier(count: int) -> str:
    return "major" if count >= 4 else "base" if count >= 2 else "site"


def build_installations(points: list[dict], loc: Locator) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for point in points:
        if point.get("kind") == "training_area":
            continue
        props = point.get("props") or {}
        component = BRANCH.get(props.get("branch"))
        garrison = props.get("garrison")
        if component and garrison:
            grouped[(garrison, component)].append(point)
    out = []
    for (garrison, component), members in sorted(grouped.items()):
        at = loc.place(members[0].get("lon"), members[0].get("lat"))
        if at is None:
            continue
        statuses = {str((point.get("props") or {}).get("status") or "active") for point in members}
        names = [point.get("name") for point in members if point.get("name")]
        refs = sorted({(point.get("props") or {}).get("ref") for point in members
                       if (point.get("props") or {}).get("ref")})
        ids = [point.get("id") for point in members if point.get("id")]
        out.append({
            "id": "garrison-" + "-".join(str(ids[0]).split("_")[1:]) + "-" + component,
            "name": garrison, "component": component,
            "joint": len({(p.get("props") or {}).get("branch") for p in members}) > 1,
            "status": "forming" if statuses == {"forming"} else "act",
            "tier": _tier(len(members)), "curated": False, "area_km2": None, "cells": None,
            "count": len(members), "units": names, "source_ids": ids, "refs": refs,
            "voivodeship": (members[0].get("props") or {}).get("voivodeship"),
            "voivodeship_code": (members[0].get("props") or {}).get("voivodeship_code"),
            **at,
        })
    out.sort(key=lambda item: (("major", "base", "site").index(item["tier"]), -item["count"], item["name"],
                               item["component"]))
    return out


def build_ranges(points: list[dict], loc: Locator) -> list[dict]:
    out = []
    for point in points:
        if point.get("kind") != "training_area":
            continue
        at = loc.place(point.get("lon"), point.get("lat"))
        if at is None:
            continue
        props = point.get("props") or {}
        out.append({
            "id": point.get("id"), "name": point.get("name"), "component": "land",
            "area_km2": props.get("area_km2"), "cells": [at["cell"]], "cell": at["cell"],
            "x": at["x"], "y": at["y"], "state": at["state"], "county": at["county"],
            "garrison": props.get("garrison"), "ref": props.get("ref"), "note": props.get("note"),
        })
    out.sort(key=lambda item: (-(item["area_km2"] or 0), item["name"] or ""))
    return out


def _state_rows(table: dict, installations: list[dict]) -> dict:
    rows = table.get("rows") or {}
    by_code = Counter(item.get("voivodeship_code") for item in installations)
    out = {}
    for code in sorted(set(rows) | set(by_code)):
        row = rows.get(code) or {}
        out[STATE_ABBR.get(code, code)] = {
            "garrison_towns": row.get("garrison_towns"), "units": row.get("units"),
            "bases": row.get("bases"), "map_garrisons": by_code.get(code, 0),
        }
    return out


def _national(headline: dict) -> dict:
    return {
        "personnel": {
            "total_2025": headline.get("strength_total"),
            "total_mid_2026": headline.get("strength_total_mid_2026"),
            "professional": headline.get("professional_soldiers"),
            "territorial_defence": headline.get("territorial_defence"),
            "voluntary_service": headline.get("voluntary_service"),
        },
        "spending": {
            "budget_act": {"name": "The budget act", "total_pln": headline.get("defence_budget_2026"),
                           "pct_gdp": headline.get("defence_budget_2026_pct_gdp"), "year": 2026},
            "with_support_fund": {"name": "The total with the Armed Forces Support Fund",
                                  "total_pln": headline.get("defence_total_2026_with_fwsz"),
                                  "pct_gdp": headline.get("defence_total_2026_with_fwsz_pct_gdp"), "year": 2026},
            "nato_core": {"name": "NATO core defence expenditure", "total_pln": headline.get("nato_core_defence_2026"),
                          "pct_gdp": headline.get("nato_core_defence_2026_pct_gdp"), "year": 2026},
        },
    }


def build() -> None:
    world = load_interim("_world")
    payload = load_interim_payload("pl_soc_military")
    data = payload["data"]
    loc = Locator(world)
    installations = build_installations(data.get("points") or [], loc)
    ranges = build_ranges(data.get("points") or [], loc)
    tables = data.get("tables") or {}
    headline = (tables.get("headline", {}).get("rows") or {}).get("PL") or {}
    doc = {
        "version": 1, "vintage": payload.get("vintage"), "sources": ["pl_soc_military"],
        "rule": INSTALLATION_RULE,
        "rules": {"installations": INSTALLATION_RULE, "tier": TIER_RULE, "ranges": RANGE_RULE},
        "caveats": "Installation-level personnel are not published. Garrison markers count listed formations and bases.",
        "components": COMPONENTS, "installations": installations, "ranges": ranges,
        "states": _state_rows(tables.get("garrisons") or {}, installations),
        "national": _national(headline), "cities": {},
    }
    write_web("military.json", doc)
    tiers = Counter(item["tier"] for item in installations)
    print(f"    {len(installations)} garrison/branch markers ({dict(tiers)}); {len(ranges)} training areas")


def _is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _load(web_dir: Path, name: str):
    path = Path(web_dir) / name
    return json.loads(path.read_text()) if path.exists() else None


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "military.json"
    if not path.exists():
        return [("NOTE", "military.json not built (optional)")]
    doc = json.loads(path.read_text())
    world = _load(Path(web_dir), "world.json") or {}
    cell_count = (world.get("grid", {}).get("cols") or 0) * (world.get("grid", {}).get("rows") or 0)
    problems = []
    components = {item.get("id") for item in doc.get("components") or []}
    ids = set()
    for item in doc.get("installations") or []:
        if not item.get("id") or item["id"] in ids:
            problems.append("installation id is missing or duplicated")
        ids.add(item.get("id"))
        if item.get("component") not in components:
            problems.append(f"{item.get('id')}: unknown component")
        cell = item.get("cell")
        if not isinstance(cell, int) or (cell_count and not 0 <= cell < cell_count):
            problems.append(f"{item.get('id')}: invalid cell")
        if item.get("tier") not in ("major", "base", "site") or item.get("status") not in ("act", "forming"):
            problems.append(f"{item.get('id')}: invalid tier or status")
    for item in doc.get("ranges") or []:
        if not item.get("cells") or item.get("area_km2") is not None and not _is_num(item["area_km2"]):
            problems.append(f"{item.get('id')}: invalid training area")
    spending = doc.get("national", {}).get("spending", {})
    for key, expected, pct in (("budget_act", 124_800_000_000, 3.0),
                               ("with_support_fund", 200_000_000_000, 4.81)):
        row = spending.get(key) or {}
        if row.get("total_pln") != expected or row.get("pct_gdp") != pct:
            problems.append(f"national.spending.{key} does not match the 2026 source headline")
    out = [("FAIL", f"military.json: {problem}") for problem in problems[:12]]
    if not problems:
        out.append(("PASS", f"military.json: {len(doc.get('installations') or [])} garrison markers, "
                            f"{len(doc.get('ranges') or [])} training areas, 2026 budgets present"))
    size = path.stat().st_size
    out.append(("PASS" if size < 300_000 else "WARN", f"military.json {size / 1e3:.0f} kB (eager budget ~300 kB)"))
    return out

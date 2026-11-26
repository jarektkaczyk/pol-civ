"""Build Poland's selected heritage, nature, university and landmark sites."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..core.store import load_interim, load_interim_payload, write_web
from .military import Locator, _is_num

REQUIRES = ["_world", "pl_soc_heritage", "pl_soc_parks", "pl_soc_universities",
            "pl_transport_ports", "pl_transport_airports", "pl_energy_plants"]
PRODUCES = ["wonders.json"]

PARKS_N = 6
UNIVERSITIES_N = 6

# Serial properties use a recognisable Polish component instead of the mean of all components.
SERIAL_COMPONENT = {
    "whc_32": "whc_32bis-001",       # Wieliczka Salt Mine
    "whc_31": "whc_31-001",          # Auschwitz
    "whc_1054": "whc_1054-002",      # Swidnica Church of Peace
    "whc_1053": "whc_1053-003",      # Debno wooden church
    "whc_1133": "whc_1133quinquies-086",  # Polonina Wetlinska and Smerek
    "whc_1424": "whc_1424-009",      # Powroznik tserkva
    "whc_1599": "whc_1599-001",      # Krzemionki Opatowskie
}

RULES = [
    {"id": "unesco_property", "kind": "unesco", "text":
     "Every UNESCO World Heritage property with Poland among its states, one marker per property. Serial properties "
     "use the named, best-known Polish component in this file. Memorial properties are kept separate, never ranked, "
     "and never described as wonders."},
    {"id": "national_park", "kind": "natural", "year": 2024, "text":
     "The six Polish national parks with the most visitors in 2024, ranked by the GUS visitor count."},
    {"id": "research_university", "kind": "university", "year": 2025, "text":
     "The six institutions with the most students on 31 December 2025 among institutions with at least one A+ "
     "research category in the newest RAD-on evaluation available for each discipline."},
    {"id": "landmark", "kind": "landmark", "text":
     "Four stated national records: the tallest building, the busiest seaport by 2025 cargo tonnage, the largest "
     "operating power station by MW, and the busiest airport by 2025 passengers. These records are not ranked "
     "against each other."},
]


def _placed(loc: Locator, point: dict) -> dict | None:
    at = loc.place(point.get("lon"), point.get("lat"))
    if at is None:
        return None
    return {**at, "cbsa": None, "cells": None}


def select_unesco(points: list[dict]) -> list[tuple[dict, dict]]:
    """Return (property, marker) pairs, replacing serial-property means with selected components."""
    by_id = {point.get("id"): point for point in points}
    parents = [point for point in points if point.get("kind") in ("unesco_site", "memorial")]
    return [(parent, by_id.get(SERIAL_COMPONENT.get(parent.get("id"))) or parent) for parent in parents]


def _unesco(points: list[dict], loc: Locator) -> list[dict]:
    out = []
    for parent, marker in select_unesco(points):
        at = _placed(loc, marker)
        if at is None:
            continue
        props = parent.get("props") or {}
        memorial = parent.get("kind") == "memorial"
        out.append({
            "id": parent.get("id"), "name": parent.get("name"), "short": parent.get("name"),
            "kind": "memorial" if memorial else "unesco", "rule": "unesco_property", "rank": None,
            "curated": False, "metrics": {"inscribed": props.get("inscribed"), "category": props.get("category"),
                                             "area_ha": props.get("area_ha")},
            "ref": props.get("ref"), "component": marker.get("name") if marker is not parent else None,
            "component_id": marker.get("id") if marker is not parent else None,
            **at,
        })
    return out


def select_parks(points: list[dict]) -> list[dict]:
    return sorted((point for point in points if (point.get("props") or {}).get("visitors") is not None),
                  key=lambda point: (-(point["props"]["visitors"]), point.get("name") or ""))[:PARKS_N]


def _parks(points: list[dict], loc: Locator) -> list[dict]:
    out = []
    for rank, point in enumerate(select_parks(points), 1):
        at = _placed(loc, point)
        if at is None:
            continue
        props = point.get("props") or {}
        out.append({
            "id": point.get("id"), "name": point.get("name"), "short": point.get("name"),
            "kind": "natural", "rule": "national_park", "rank": rank, "curated": False,
            "metrics": {"visits": props.get("visitors"), "year": props.get("visitors_year"),
                        "area_km2": round(props["area_ha"] / 100, 2) if props.get("area_ha") is not None else None,
                        "unit_type": "National park"},
            "ref": props.get("ref"), **at,
        })
    return out


def select_universities(points: list[dict]) -> list[dict]:
    eligible = [point for point in points if point.get("lon") is not None and point.get("lat") is not None
                and ((point.get("props") or {}).get("count_a_plus") or 0) > 0
                and (point.get("props") or {}).get("students_total") is not None]
    return sorted(eligible, key=lambda point: (-(point["props"]["students_total"]), point.get("name") or ""))[
        :UNIVERSITIES_N]


def _universities(points: list[dict], loc: Locator) -> list[dict]:
    out = []
    for rank, point in enumerate(select_universities(points), 1):
        at = _placed(loc, point)
        if at is None:
            continue
        props = point.get("props") or {}
        out.append({
            "id": point.get("id"), "name": point.get("name"), "short": props.get("abbr") or point.get("name"),
            "kind": "university", "rule": "research_university", "rank": rank, "curated": False,
            "metrics": {"students": props.get("students_total"), "students_year": 2025,
                        "a_plus_categories": props.get("count_a_plus"), "a_categories": props.get("count_a"),
                        "evaluation_periods": props.get("evaluation_periods")},
            "ref": props.get("ref"), **at,
        })
    return out


def _largest(points: list[dict], field: str, *, predicate=lambda point: True) -> dict | None:
    candidates = [point for point in points if predicate(point) and _is_num((point.get("props") or {}).get(field))]
    return max(candidates, key=lambda point: point["props"][field], default=None)


def _landmark(point: dict, loc: Locator, *, item_id: str, name: str, record: str, value, unit: str,
              year: int | None, ref: str | None) -> dict | None:
    at = _placed(loc, point)
    if at is None:
        return None
    return {"id": item_id, "name": name, "short": name, "kind": "landmark", "rule": "landmark", "rank": None,
            "curated": False, "metrics": {"record": record, "value": value, "unit": unit, "year": year},
            "ref": ref, **at}


def _landmarks(ports: list[dict], airports: list[dict], plants: list[dict], loc: Locator) -> list[dict]:
    varso = {"lon": 20.9847, "lat": 52.2280}
    out = [_landmark(varso, loc, item_id="landmark-varso-tower", name="Varso Tower",
                     record="Tallest building in Poland", value=310, unit="m", year=2022,
                     ref="https://varso.com/en/varso-tower/")]
    port = _largest(ports, "cargo_kt", predicate=lambda point: (point.get("props") or {}).get("cargo_year") == 2025)
    airport = _largest(airports, "passengers",
                       predicate=lambda point: (point.get("props") or {}).get("passengers_year") == 2025)
    plant = _largest(plants, "mw", predicate=lambda point: (point.get("props") or {}).get("status") == "operating"
                     and not (point.get("props") or {}).get("storage"))
    if port:
        props = port["props"]
        out.append(_landmark(port, loc, item_id="landmark-busiest-seaport", name=port["name"],
                             record="Busiest seaport by cargo tonnage", value=props["cargo_kt"], unit="thousand tonnes",
                             year=props.get("cargo_year"), ref=props.get("ref")))
    if plant:
        props = plant["props"]
        out.append(_landmark(plant, loc, item_id="landmark-largest-power-station", name=plant["name"],
                             record="Largest operating power station", value=props["mw"], unit="MW",
                             year=props.get("mw_year"), ref=props.get("ref")))
    if airport:
        props = airport["props"]
        out.append(_landmark(airport, loc, item_id="landmark-busiest-airport", name=airport["name"],
                             record="Busiest airport by passengers", value=props["passengers"], unit="passengers",
                             year=props.get("passengers_year"), ref=props.get("ref")))
    return [item for item in out if item is not None]


def build() -> None:
    loc = Locator(load_interim("_world"))
    heritage = load_interim_payload("pl_soc_heritage")
    parks = load_interim_payload("pl_soc_parks")
    universities = load_interim_payload("pl_soc_universities")
    ports = load_interim_payload("pl_transport_ports")
    airports = load_interim_payload("pl_transport_airports")
    plants = load_interim_payload("pl_energy_plants")
    sites = [
        *_unesco(heritage["data"].get("points") or [], loc),
        *_parks(parks["data"].get("points") or [], loc),
        *_universities(universities["data"].get("points") or [], loc),
        *_landmarks(ports["data"].get("points") or [], airports["data"].get("points") or [],
                    plants["data"].get("points") or [], loc),
    ]
    park_total = ((parks["data"].get("tables") or {}).get("national_parks", {}).get("rows") or {}).get("PL", {})
    doc = {
        "version": 1,
        "vintage": {"heritage": heritage.get("vintage"), "parks": parks.get("vintage"),
                    "universities": universities.get("vintage"), "transport":
                    f"{ports.get('vintage')}; {airports.get('vintage')}", "energy": plants.get("vintage")},
        "sources": ["pl_soc_heritage", "pl_soc_parks", "pl_soc_universities", "pl_transport_ports",
                    "pl_transport_airports", "pl_energy_plants"],
        "rules": RULES,
        "national": {"park_visits": park_total.get("visitors"), "park_visits_year": 2024,
                     "national_parks": park_total.get("parks"), "unesco_properties": 18,
                     "memorials": sum(site["kind"] == "memorial" for site in sites)},
        "wonders": sites,
    }
    write_web("wonders.json", doc)
    counts = Counter(site["kind"] for site in sites)
    print(f"    {len(sites)} mapped cultural sites ({dict(counts)})")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "wonders.json"
    if not path.exists():
        return [("NOTE", "wonders.json not built (optional)")]
    doc = json.loads(path.read_text())
    problems = []
    sites = doc.get("wonders") or []
    ids = [site.get("id") for site in sites]
    if len(ids) != len(set(ids)):
        problems.append("site ids are not unique")
    if sum(site.get("rule") == "unesco_property" for site in sites) != 18:
        problems.append("UNESCO rule must yield 18 properties")
    memorials = [site for site in sites if site.get("kind") == "memorial"]
    if len(memorials) != 1 or memorials[0].get("rank") is not None:
        problems.append("Auschwitz-Birkenau must be one unranked memorial")
    if sum(site.get("rule") == "national_park" for site in sites) != PARKS_N:
        problems.append("national park rule must yield six sites")
    if sum(site.get("rule") == "research_university" for site in sites) != UNIVERSITIES_N:
        problems.append("research university rule must yield six sites")
    if sum(site.get("rule") == "landmark" for site in sites) != 4:
        problems.append("landmark rule must yield four national records")
    if any(not isinstance(site.get("cell"), int) or not _is_num(site.get("x")) or not _is_num(site.get("y"))
           for site in sites):
        problems.append("every site must have a cell and map position")
    out = [("FAIL", f"wonders.json: {problem}") for problem in problems]
    if not problems:
        out.append(("PASS", f"wonders.json: {len(sites)} sites, including 18 UNESCO properties, 6 parks, "
                            "6 universities, 4 record landmarks and 1 memorial"))
    size = path.stat().st_size
    out.append(("PASS" if size < 300_000 else "WARN", f"wonders.json {size / 1e3:.0f} kB (eager budget ~300 kB)"))
    return out

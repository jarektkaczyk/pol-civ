"""Made in Poland and Tech and games (economy.json): curated product and tech sites plus the game studios.

Sources: pl_econ_champions (plants, yards and makers with one fact each), pl_tech_sites (tech landmarks with one fact
each, and the Wikidata game studios with their best-known game). Every item gets map km, its Polish land hex, the
gmina it stands in (TERYT7, by point in polygon against the LAU 2024 outlines, not by reverse geocoding) and the
voivodeship. Loaded by ext/economy when one of its two Map switches is first turned on.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..core.geo import Shape
from ..core.store import load_interim, load_interim_payload, write_web
from .military import STATE_ABBR, Locator

REQUIRES = ["_world", "pl_geo_lau", "pl_econ_champions", "pl_tech_sites"]
PRODUCES = ["economy.json"]

LAYERS = [
    {"id": "made", "name": "Made in Poland", "source": "pl_econ_champions"},
    {"id": "tech", "name": "Tech and games", "source": "pl_tech_sites"},
]
# Kinds in drawing order; each has its own glyph (web/js/render/art/economy.js).
KINDS = [
    {"id": "cars", "layer": "made", "name": "Cars and batteries"},
    {"id": "transport", "layer": "made", "name": "Buses, trams, trains and aircraft"},
    {"id": "boats", "layer": "made", "name": "Boats"},
    {"id": "home", "layer": "made", "name": "Home: furniture, windows and appliances"},
    {"id": "food", "layer": "made", "name": "Food and farming"},
    {"id": "crafts", "layer": "made", "name": "Glass, pottery, porcelain and amber"},
    {"id": "cosmetics", "layer": "made", "name": "Cosmetics"},
    {"id": "energy", "layer": "made", "name": "Energy and industry"},
    {"id": "studio", "layer": "tech", "name": "Game studios"},
    {"id": "scaleup", "layer": "tech", "name": "Tech companies"},
    {"id": "hpc", "layer": "tech", "name": "Supercomputers and cloud"},
    {"id": "space", "layer": "tech", "name": "Space"},
    {"id": "research", "layer": "tech", "name": "Research and AI"},
]
KIND_LAYER = {k["id"]: k["layer"] for k in KINDS}
RULES = {
    "made": "Places behind products Poland is known for abroad, one fact each with the year of its figure. National "
            "figures are shown at one place that makes the product.",
    "tech": "Tech companies at their main Polish office, the Polish TOP500 supercomputers (November 2026), satellite "
            "makers, the 2025 patent leader and the first cloud regions, one fact each.",
    "studios": "Active video game studios on Wikidata with their headquarters in a Polish town and at least one "
               "released game; the best-known game is the one with the most Wikipedia articles, checked by hand for "
               "the largest studios. Studios in one town share one marker.",
}


def gmina_index(lau: dict, counties: list[str]) -> list[tuple[str, Shape]]:
    """[(TERYT7, outline)] for every LAU gmina whose 6-digit code matches a world.json gmina."""
    by6 = {c[:6]: c for c in counties}
    out = []
    for g in lau["gminy"]:
        code = by6.get(g["teryt6"])
        if code:
            out.append((code, Shape([[tuple(p) for p in r] for r in g["rings"]])))
    return out


def gmina_at(index: list[tuple[str, Shape]], lon: float, lat: float) -> str | None:
    hits = [code for code, shape in index if shape.contains(lon, lat)]
    return hits[0] if len(hits) == 1 else None


def place_item(point: dict, source: str, loc: Locator, index) -> dict | None:
    at = loc.place(point.get("lon"), point.get("lat"))
    if at is None:
        return None
    props = point.get("props") or {}
    county = gmina_at(index, point["lon"], point["lat"])
    pip = county is not None
    if county is None:
        county = at["county"]  # a coastal or offshore point: the gmina of its land hex
    item = {
        "id": point["id"], "layer": KIND_LAYER[point["kind"]], "kind": point["kind"], "name": point["name"],
        "place": props.get("place"),
    }
    for key in ("label", "fact", "game", "games", "sitelinks", "office", "seat_note", "scope"):
        if props.get(key) not in (None, ""):
            item[key] = props[key]
    item.update({
        "year": props.get("year"), "ref": props.get("ref"), "source": source,
        "x": at["x"], "y": at["y"], "cell": at["cell"], "county": county,
        "state": STATE_ABBR.get(county[:2]) if county else at["state"], "county_by": "polygon" if pip else "hex",
    })
    return item


def build() -> None:
    world = load_interim("_world")
    loc = Locator(world)
    index = gmina_index(load_interim("pl_geo_lau"), world["counties"])
    items, vintage, dropped = [], {}, []
    for layer in LAYERS:
        sid = layer["source"]
        payload = load_interim_payload(sid)
        vintage[sid] = payload.get("vintage")
        for point in payload["data"].get("points") or []:
            if point.get("kind") not in KIND_LAYER:
                raise ValueError(f"{sid}: {point.get('id')} has unknown kind {point.get('kind')!r}")
            item = place_item(point, sid, loc, index)
            if item is None:
                dropped.append(point.get("id"))
            else:
                items.append(item)
    order = {k["id"]: n for n, k in enumerate(KINDS)}
    items.sort(key=lambda it: (order[it["kind"]], -(it.get("sitelinks") or 0), it["name"]))
    counts = Counter(it["kind"] for it in items)
    doc = {
        "version": 1, "vintage": vintage, "sources": [layer["source"] for layer in LAYERS],
        "rules": RULES,
        "layers": [{"id": layer["id"], "name": layer["name"]} for layer in LAYERS],
        "kinds": [{**k, "count": counts.get(k["id"], 0)} for k in KINDS],
        "items": items,
    }
    write_web("economy.json", doc)
    by_hex = sum(1 for it in items if it["county_by"] == "hex")
    print(f"    {len(items)} items ({dict(counts)}); gmina by hex for {by_hex}; dropped {dropped or 'none'}")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "economy.json"
    if not path.exists():
        return [("NOTE", "economy.json not built (optional)")]
    doc = json.loads(path.read_text())
    world_path = Path(web_dir) / "world.json"
    world = json.loads(world_path.read_text()) if world_path.exists() else {}
    grid = world.get("grid") or {}
    size = (grid.get("cols") or 0) * (grid.get("rows") or 0)
    counties = {c.get("geoid") if isinstance(c, dict) else c for c in world.get("counties") or []}
    kinds = {k.get("id"): k.get("layer") for k in doc.get("kinds") or []}
    problems, ids = [], set()
    for it in doc.get("items") or []:
        iid = it.get("id")
        if not iid or iid in ids:
            problems.append(f"item id {iid!r} missing or duplicated")
        ids.add(iid)
        if kinds.get(it.get("kind")) != it.get("layer"):
            problems.append(f"{iid}: kind {it.get('kind')!r} does not belong to layer {it.get('layer')!r}")
        for key in ("x", "y"):
            if not isinstance(it.get(key), (int, float)):
                problems.append(f"{iid}: {key} is not a number")
        if not isinstance(it.get("cell"), int) or (size and not 0 <= it["cell"] < size):
            problems.append(f"{iid}: invalid cell")
        if counties and it.get("county") not in counties:
            problems.append(f"{iid}: county {it.get('county')!r} is not a world.json gmina")
        if not str(it.get("ref") or "").startswith("https://"):
            problems.append(f"{iid}: no ref URL")
        if it.get("kind") == "studio" and not it.get("fact"):
            if not it.get("game"):
                problems.append(f"{iid}: studio without a game")
        elif not it.get("fact") or not isinstance(it.get("year"), int):
            problems.append(f"{iid}: missing fact or year")
    out = [("FAIL", f"economy.json: {p}") for p in problems[:12]]
    if not problems:
        counts = Counter(it.get("layer") for it in doc.get("items") or [])
        towns = len({it.get("county") for it in doc.get("items") or [] if it.get("kind") == "studio"})
        out.append(("PASS", f"economy.json: {counts.get('made', 0)} Made in Poland items, {counts.get('tech', 0)} "
                            f"tech items (game studios in {towns} towns), every item with a ref, year and gmina"))
    kb = path.stat().st_size / 1e3
    out.append(("PASS" if kb < 300 else "WARN", f"economy.json {kb:.0f} kB (lazy)"))
    return out

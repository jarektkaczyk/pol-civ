"""Polish power plants, renewable capacity, mines, and mineral sites."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ..core.store import load_interim, load_interim_payload, write_web
from .infrastructure import Locator

REQUIRES = ["_world", "pl_energy_plants", "pl_energy_res", "pl_energy_oilgas", "pl_mines"]
PRODUCES = ["resources.json"]


def _type(id_, name, category, icon, emoji, color, unit, description, source):
    return {
        "id": id_, "name": name, "category": category, "icon": icon, "emoji": emoji,
        "color": color, "unit": unit, "description": description, "source": source,
    }


TYPES = [
    _type("nuclear", "Nuclear power plant", "energy", "r-nuclear", "N", "#c9b73d", "MW",
          "The planned Lubiatowo-Kopalino site. Its status and published planned capacity are shown.",
          "pl_energy_plants"),
    _type("hydro", "Hydroelectric plant", "energy", "r-hydro", "H", "#3f91bd", "MW",
          "Hydroelectric plants of at least 100 MW in the mapped plant list.", "pl_energy_plants"),
    _type("pumped_storage", "Pumped-storage plant", "energy", "r-pumped_storage", "P", "#315f8b", "MW",
          "Pumped-storage plants of at least 100 MW in the mapped plant list.", "pl_energy_plants"),
    _type("offshore_wind", "Offshore wind farm", "energy", "r-wind", "W", "#3f8f87", "MW",
          "The curated Baltic offshore wind projects, including projects under construction and planned.",
          "pl_energy_plants"),
    _type("onshore_wind", "Onshore wind farm", "energy", "r-wind", "W", "#70aa78", "MW",
          "Onshore wind plants of at least 100 MW in the mapped plant list.", "pl_energy_plants"),
    _type("solar", "Solar power plant", "energy", "r-solar", "S", "#d9a527", "MW",
          "Solar plants of at least 50 MW in the mapped plant list.", "pl_energy_plants"),
    _type("battery", "Battery storage", "energy", "r-battery", "B", "#67a65f", "MW",
          "Battery projects of at least 100 MW in the mapped plant list.", "pl_energy_plants"),
    _type("gas_plant", "Gas power plant", "energy", "r-gas_plant", "G", "#c9702d", "MW",
          "Gas plants of at least 100 MW in the mapped plant list.", "pl_energy_plants"),
    _type("hard_coal_plant", "Hard-coal power plant", "energy", "r-coal_plant", "C", "#434343", "MW",
          "Hard-coal plants of at least 100 MW in the mapped plant list.", "pl_energy_plants"),
    _type("lignite_plant", "Lignite power plant", "energy", "r-coal_plant", "L", "#665346", "MW",
          "Lignite plants of at least 100 MW in the mapped plant list.", "pl_energy_plants"),
    _type("coal_mine", "Hard-coal mine", "mineral", "r-coal_mine", "C", "#37322d", "sites",
          "The active hard-coal mines in the source list. The output field is 2025 raw-coal output where published.",
          "pl_mines"),
    _type("lignite_mine", "Lignite mine", "mineral", "r-coal_mine", "L", "#705a40", "sites",
          "The mapped lignite mines. The output field is 2025 output where published.", "pl_mines"),
    _type("copper", "Copper mine", "mineral", "r-copper", "Cu", "#b46b39", "sites",
          "KGHM's mapped copper mines. Mine-level output is not published and stays unknown.", "pl_mines"),
    _type("copper_smelter", "Copper smelter", "mineral", "r-copper", "Cu", "#8e5536", "sites",
          "KGHM's mapped copper smelters. Site-level output is not published and stays unknown.", "pl_mines"),
    _type("salt", "Salt mine", "mineral", "r-salt", "NaCl", "#7d8791", "sites",
          "The operating Klodawa mine and the historic Wieliczka and Bochnia mines.", "pl_mines"),
    _type("sulphur", "Sulphur mine", "mineral", "r-sulphur", "S", "#9b941f", "sites",
          "The operating native-sulphur mines. The output field is 2024 output where published.", "pl_mines"),
    _type("silver", "Historic silver mine", "mineral", "r-silver", "Ag", "#9aa4ad", "sites",
          "The historic Tarnowskie Gory silver, lead, and zinc mine.", "pl_mines"),
    _type("gas_pipeline_landfall", "Gas pipeline landfall", "energy", "r-gas", "G", "#2f5a7a", "bcm/year",
          "The Baltic Pipe receiving station at its Polish landfall.", "pl_energy_oilgas"),
    _type("gas_field", "Gas field", "energy", "r-gas", "G", "#477491", "sites",
          "The largest mapped domestic gas fields. Field output is not published and stays unknown.",
          "pl_energy_oilgas"),
    _type("oil_field", "Oil field", "energy", "r-oil", "O", "#594a3a", "sites",
          "The two largest mapped domestic oil fields. Field output is not published and stays unknown.",
          "pl_energy_oilgas"),
    _type("refinery", "Oil refinery", "energy", "r-oil", "R", "#806747", "Mt/year",
          "The two main Polish refineries, sized by crude processing capacity.", "pl_energy_oilgas"),
]

PLANT_TYPES = {
    "nuclear_plant": "nuclear", "hydro_plant": "hydro", "pumped_storage_plant": "pumped_storage",
    "offshore_wind_plant": "offshore_wind",
    "onshore_wind_plant": "onshore_wind", "solar_plant": "solar", "battery_plant": "battery",
    "gas_plant": "gas_plant", "hard_coal_plant": "hard_coal_plant", "lignite_plant": "lignite_plant",
}

MINE_TYPES = {
    "coal_mine": "coal_mine", "lignite_mine": "lignite_mine", "copper_mine": "copper",
    "copper_smelter": "copper_smelter", "salt_mine": "salt", "sulphur_mine": "sulphur",
}

OIL_GAS_TYPES = {
    "gas_pipeline_landfall": "gas_pipeline_landfall",
    "gas_field": "gas_field",
    "oil_field": "oil_field",
    "refinery": "refinery",
}


def _mine_type(point: dict) -> str | None:
    kind = point.get("kind")
    if kind in MINE_TYPES:
        return MINE_TYPES[kind]
    if kind == "historic_mine":
        commodity = (point.get("props") or {}).get("commodity")
        return "salt" if commodity == "salt" else "silver" if commodity == "silver_lead_zinc" else None
    return None


def _detail(props: dict) -> str | None:
    parts = []
    if props.get("status"):
        parts.append(str(props["status"]).replace("_", " ").capitalize())
    if props.get("operator"):
        parts.append(str(props["operator"]))
    if props.get("status_note"):
        parts.append(str(props["status_note"]))
    return " - ".join(parts) or None


def _status_parts(props: dict) -> dict:
    """The pieces of `detail`, so the browser can write it in the reader's language: status_label (English text of
    the status code) and status_note (English free text)."""
    return {"status_label": str(props["status"]).replace("_", " ").capitalize() if props.get("status") else None,
            "status_note": props.get("status_note")}


def plant_items(locator: Locator, points: list[dict]) -> list[dict]:
    out = []
    for point in points:
        type_id = PLANT_TYPES.get(point.get("kind"))
        if type_id is None:
            continue
        props = point.get("props") or {}
        offshore = type_id == "offshore_wind"
        at = locator.place(point.get("lon"), point.get("lat"), keep_water=offshore, rings=10 if offshore else 3)
        if at is None:
            continue
        out.append({
            "id": point["id"], "type": type_id, "name": point["name"], "value": props.get("mw"),
            "status": props.get("status"), "operator": props.get("operator"), "detail": _detail(props),
            **_status_parts(props), "year": props.get("mw_year"), "ref": props.get("ref"), **at,
        })
    return out


def mine_items(locator: Locator, points: list[dict]) -> list[dict]:
    out = []
    for point in points:
        type_id = _mine_type(point)
        if type_id is None:
            continue
        props = point.get("props") or {}
        at = locator.place(point.get("lon"), point.get("lat"))
        if at is None:
            continue
        out.append({
            "id": point["id"], "type": type_id, "name": point["name"], "value": 1,
            "output": props.get("output"), "output_unit": props.get("output_unit"),
            "status": props.get("status"), "operator": props.get("operator"), "detail": _detail(props),
            **_status_parts(props), "year": props.get("output_year"), "ref": props.get("ref"), **at,
        })
    return out


def oil_gas_items(locator: Locator, points: list[dict]) -> list[dict]:
    out = []
    for point in points:
        type_id = OIL_GAS_TYPES.get(point.get("kind"))
        if type_id is None:
            continue
        props = point.get("props") or {}
        at = locator.place(point.get("lon"), point.get("lat"))
        if at is None:
            continue
        if type_id == "gas_pipeline_landfall":
            value = props.get("capacity_bcm")
        elif type_id == "refinery":
            value = props.get("capacity_mt")
        else:
            value = 1
        detail = " - ".join(part for part in [
            str(props["status"]).replace("_", " ").capitalize() if props.get("status") else None,
            str(props["operator"]) if props.get("operator") else None,
        ] if part) or None
        out.append({
            "id": point["id"], "type": type_id, "name": point["name"], "value": value,
            "output": props.get("output"), "output_unit": props.get("output_unit"),
            "status": props.get("status"), "operator": props.get("operator"), "detail": detail,
            "status_label": _status_parts(props)["status_label"], "status_note": None, "year": props.get("year"), "ref": props.get("ref"), **at,
        })
    return out


def _summary(items: list[dict]) -> dict:
    type_by_id = {type_["id"]: type_ for type_ in TYPES}
    national = {}
    states = defaultdict(dict)
    for type_id, type_ in type_by_id.items():
        selected = [item for item in items if item["type"] == type_id]
        values = [item["value"] for item in selected if isinstance(item.get("value"), (int, float))]
        by_status = defaultdict(lambda: {"count": 0, "value": None})
        for item in selected:
            status = item.get("status") or "unknown"
            by_status[status]["count"] += 1
            if isinstance(item.get("value"), (int, float)):
                by_status[status]["value"] = round((by_status[status]["value"] or 0) + item["value"], 3)
        national[type_id] = {
            "count": len(selected), "value": round(sum(values), 3) if values else None,
            "unit": type_["unit"], "by_status": dict(sorted(by_status.items())),
        }
    for state in sorted({item.get("state") for item in items if item.get("state")}):
        for type_id, type_ in type_by_id.items():
            selected = [item for item in items if item.get("state") == state and item["type"] == type_id]
            if not selected:
                continue
            values = [item["value"] for item in selected if isinstance(item.get("value"), (int, float))]
            states[state][type_id] = {
                "count": len(selected), "value": round(sum(values), 3) if values else None, "unit": type_["unit"],
            }
    return {
        "note": (
            "Totals cover the mapped sites only. Power capacity includes operating, construction, and planned sites; "
            "use by_status to separate them. Mine values are added only where every item uses the type's stated unit."
        ),
        "national": national,
        "states": dict(states),
    }


def summarize(items: list[dict], types: list[dict]) -> dict:
    """Return the compact mapped-site summary used by shared city-view helpers."""
    def blank(type_: dict) -> dict:
        additive = "area" not in str(type_.get("unit") or "").lower()
        return {"count": 0, "value": 0 if additive else None, "unit": type_.get("unit")}

    type_by_id = {type_["id"]: type_ for type_ in types}
    national = {type_["id"]: blank(type_) for type_ in types}
    states: dict[str, dict] = {}
    for item in items:
        type_ = type_by_id[item["type"]]
        rows = [national[type_["id"]]]
        if item.get("state"):
            rows.append(states.setdefault(item["state"], {}).setdefault(type_["id"], blank(type_)))
        for row in rows:
            row["count"] += 1
            if row["value"] is not None and isinstance(item.get("value"), (int, float)):
                row["value"] += item["value"]
    for row in [*national.values(), *(row for state in states.values() for row in state.values())]:
        if row["value"] is not None:
            row["value"] = round(row["value"])
    return {"note": "Totals cover the mapped sites only.", "national": national, "states": dict(sorted(states.items()))}


def renewables(data: dict) -> dict:
    table = (data.get("tables") or {}).get("res_capacity_powiat") or {}
    fields = table.get("fields") or {}
    keys = list(fields)
    rows = table.get("rows") or {}
    return {
        "as_of": data.get("as_of"), "source": "pl_energy_res", "level": "powiat", "unit": "MW",
        "fields": [{"key": key, **fields[key]} for key in keys],
        "rows": [[code, *(values.get(key) for key in keys)] for code, values in sorted(rows.items())],
    }


def build() -> None:
    world = load_interim("_world")
    plant_payload = load_interim_payload("pl_energy_plants")
    res_payload = load_interim_payload("pl_energy_res")
    oil_gas_payload = load_interim_payload("pl_energy_oilgas")
    mine_payload = load_interim_payload("pl_mines")
    locator = Locator(world)
    items = plant_items(locator, plant_payload["data"].get("points") or [])
    items.extend(mine_items(locator, mine_payload["data"].get("points") or []))
    items.extend(oil_gas_items(locator, oil_gas_payload["data"].get("points") or []))
    rank = {type_["id"]: index for index, type_ in enumerate(TYPES)}
    items.sort(key=lambda item: (rank[item["type"]], -(item.get("value") or -1), item["name"]))

    write_web("resources.json", {
        "version": 1,
        "vintage": {
            "plants": plant_payload.get("vintage"), "renewables": res_payload.get("vintage"),
            "oil_gas": oil_gas_payload.get("vintage"), "mines": mine_payload.get("vintage"),
        },
        "sources": ["pl_energy_plants", "pl_energy_res", "pl_energy_oilgas", "pl_mines"],
        "types": TYPES,
        "items": items,
        "summary": _summary(items),
        "renewables": renewables(res_payload["data"]),
        "national_installed": plant_payload["data"].get("national_installed"),
        "rules": {
            "plants": next((note for note in plant_payload["data"].get("notes") or [] if note.startswith("Rule:")), None),
            "oil_gas": next((note for note in oil_gas_payload["data"].get("notes") or [] if note.startswith("Rule:")), None),
            "mines": next((note for note in mine_payload["data"].get("notes") or [] if note.startswith("Rule:")), None),
        },
    })
    energy = sum(1 for item in items if next(type_ for type_ in TYPES if type_["id"] == item["type"])["category"] == "energy")
    print(f"    {len(items)} resource sites ({energy} energy, {len(items) - energy} mine or mineral); "
          f"{len(res_payload['data']['tables']['res_capacity_powiat']['rows'])} renewable powiats")


def check(web_dir) -> list[tuple[str, str]]:
    web_dir = Path(web_dir)
    path = web_dir / "resources.json"
    if not path.exists():
        return [("NOTE", "resources.json not built")]
    out = []
    fail = lambda message: out.append(("FAIL", f"resources.json: {message}"))
    try:
        doc = json.loads(path.read_text())
        world = json.loads((web_dir / "world.json").read_text())
    except (OSError, ValueError) as exc:
        return [("FAIL", f"resources.json: cannot read output: {exc}")]
    size = int(world["grid"]["cols"]) * int(world["grid"]["rows"])
    type_ids = [type_.get("id") for type_ in doc.get("types") or []]
    if len(type_ids) != len(set(type_ids)) or not type_ids:
        fail("resource type ids are empty or duplicated")
    bad = [item.get("id") for item in doc.get("items") or []
           if item.get("type") not in type_ids or not isinstance(item.get("cell"), int) or not 0 <= item["cell"] < size]
    if bad:
        fail(f"{len(bad)} items have an unknown type or invalid cell")
    renewable = doc.get("renewables") or {}
    keys = [field.get("key") for field in renewable.get("fields") or []]
    rows = renewable.get("rows") or []
    if any(len(row) != len(keys) + 1 for row in rows) or len({row[0] for row in rows}) != len(rows):
        fail("renewable rows are malformed or have duplicate powiat codes")
    if not any(level == "FAIL" for level, _ in out):
        out.append(("PASS", f"resources: {len(doc.get('items') or [])} sites, {len(type_ids)} types, "
                            f"{len(rows)} renewable powiats"))
    return out

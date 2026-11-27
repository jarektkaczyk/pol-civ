"""Time-lapse lenses: tourist nights by month (GUS BDL P2882) and the smog week (GIOS hourly PM2.5).

The lens values in lenses.json are one still frame: the newest month, and the hour with the highest national mean
of the smog week. The browser (web/js/ext/timelapse) swaps the values as the motion clock runs, from
timelapse.json and smog.json.
"""

from __future__ import annotations

import json

from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload
from .timelapse import POPULATION_DATE, tourism_block

REQUIRES_D = ["pl_tourism_monthly", "smog.json"]


def tourism_lens(world: dict, ramps: dict, percentile_domain) -> dict | None:
    try:
        interim = load_interim_payload("pl_tourism_monthly")["data"]
    except FileNotFoundError:
        return None
    states = world["states"]
    pop_rows = load_interim("pl_stats_population")["tables"]["demographic_indicators"]["rows"]
    block = tourism_block(interim, states, {s: (pop_rows.get(s) or {}).get("population") for s in states})
    last = block["per_resident"][-1]
    values = [last[o] if o >= 0 else None for o in world["owner"]]
    flat = [v for row in block["per_resident"] for v in row]
    return {
        "id": "tourism_monthly", "group": "life", "name": "Tourist nights by month", "short_name": "Tourist nights",
        "icon": "l-tourism", "emoji": "\U0001f9f3", "unit": "nights per resident", "higher_is": "neutral",
        "source": "pl_tourism_monthly",
        "description": "Nights spent in tourist accommodation with 10 or more beds in one month, per resident of the "
                       "voivodeship.",
        "note": "Per voivodeship.",
        "format": "float", "scale": "log", "ramp": ramps["olive"], "domain": percentile_domain(flat, True),
        "scale_note": "Colours span the 2nd to 98th percentile of all voivodeship-months; values beyond are drawn at "
                      "the end colours.",
        "values": values,
        "time": {"axis": "month", "file": "timelapse", "first": block["months"][0], "last": block["months"][-1],
                 "shown": block["months"][-1], "population_date": POPULATION_DATE},
    }


def smog_lens(world: dict, ramps: dict, percentile_domain) -> dict | None:
    path = WEB_DATA / "smog.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    hourly = doc["national_hourly"]
    peak = max(range(len(hourly)), key=lambda h: hourly[h] if hourly[h] is not None else -1)
    values = [None] * len(world["owner"])
    for c, v in zip(doc["cells"], doc["values"][peak]):
        values[c] = v
    flat = [v for row in doc["values"] for v in row]
    return {
        "id": "smog_week", "group": "air", "name": "Smog week", "icon": "l-air", "emoji": "\U0001f32b️",
        "unit": "µg/m³ PM2.5", "higher_is": "bad", "source": "pl_air_hourly",
        "description": "Fine dust (PM2.5) hour by hour in the week with the worst smog of winter 2025/26.",
        "format": "float", "scale": "linear", "ramp": ramps["smog"], "domain": [0, percentile_domain(flat, False)[1]],
        "scale_note": "Colours run from 0 to the 98th percentile of all hex-hours; higher values are drawn at the "
                      "end colour.",
        "values": values,
        "time": {"axis": "hour", "file": "smog", "start": doc["start"], "hours": doc["hours"], "shown": peak},
    }


def lenses_d(world: dict, ramps: dict, percentile_domain) -> list[dict]:
    return [lens for lens in (tourism_lens(world, ramps, percentile_domain), smog_lens(world, ramps, percentile_domain))
            if lens]

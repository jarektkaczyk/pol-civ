"""Smog week (smog.json, lazy): hourly PM2.5 per hex for the worst smog week of winter 2025/26, for the motion clock.

The week, the stations and their hourly values come from `pl_air_hourly` (GIOS). Each Polish land hex takes the
inverse-distance-weighted mean (power 2) of the stations within RADIUS_KM of its centre that report that hour; a hex
with no such station is null for that hour. Hex values are whole ug/m3. `cells` lists the hexes that have a value
in at least one hour; `values[h][k]` is hex `cells[k]` in hour h (the hour starting at `start` + h hours).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..core.hexgrid import HexGrid
from ..core.store import load_interim_payload, write_web
from .counties import projection

REQUIRES = ["_world", "pl_air_hourly"]
PRODUCES = ["smog.json"]

RADIUS_KM = 40.0
POWER = 2
MIN_DIST_KM = 1.0  # a station inside a hex counts as 1 km away, so one station never takes all the weight


def neighbours(centres: dict[int, tuple[float, float]], stations: list[tuple[float, float]],
               radius: float = RADIUS_KM) -> dict[int, list[tuple[int, float]]]:
    """cell -> [(station index, IDW weight)] for the stations within `radius` km."""
    out = {}
    for cell, (cx, cy) in centres.items():
        near = []
        for j, (sx, sy) in enumerate(stations):
            d = math.hypot(cx - sx, cy - sy)
            if d <= radius:
                near.append((j, 1.0 / max(d, MIN_DIST_KM) ** POWER))
        if near:
            out[cell] = near
    return out


def idw(near: list[tuple[int, float]], hour_values: list[float | None]) -> float | None:
    """Weighted mean of the stations that report this hour, or None when none do."""
    num = den = 0.0
    for j, w in near:
        v = hour_values[j]
        if v is not None:
            num += w * v
            den += w
    return num / den if den else None


def build() -> None:
    world = load_interim_payload("_world")["data"]
    air = load_interim_payload("pl_air_hourly")
    data = air["data"]
    proj = projection(world)
    grid = HexGrid(**world["grid"])
    owner = world["owner"]
    centres = {i: grid.center(*grid.col_row(i)) for i in range(grid.size) if owner[i] >= 0}
    stations, xy = [], []
    for p in data["points"]:
        x, y = proj(p["lon"], p["lat"])
        cell = grid.cell_at(x, y)
        pr = p["props"]
        stations.append({"id": pr["station_code"], "name": p["name"], "city": pr.get("city"),
                         "x": round(x, 1), "y": round(y, 1), "cell": cell if cell >= 0 else None,
                         "pm25": pr["pm25"]})
        xy.append((x, y))
    week = data["week"]
    n = week["hours"]
    near = neighbours(centres, xy)
    cells = sorted(near)
    values = []
    for h in range(n):
        hour = [s["pm25"][h] for s in stations]
        row = []
        for c in cells:
            v = idw(near[c], hour)
            row.append(None if v is None else round(v))
        values.append(row)
    cells_used = [c for k, c in enumerate(cells) if any(values[h][k] is not None for h in range(n))]
    if len(cells_used) != len(cells):
        keep = [k for k, c in enumerate(cells) if c in set(cells_used)]
        values = [[row[k] for k in keep] for row in values]
    peak = max(((s["pm25"][h], s["name"], h) for s in stations for h in range(n) if s["pm25"][h] is not None),
               default=None)
    write_web("smog.json", {
        "version": 1,
        "vintage": air.get("vintage"),
        "sources": ["pl_air_hourly"],
        "axis": "hour",
        "start": week["start"],
        "hours": n,
        "unit": "ug/m3",
        "national_mean": week["national_mean"],
        "national_hourly": week["national_hourly"],
        "peak": None if peak is None else {"value": peak[0], "station": peak[1], "hour": peak[2]},
        "stations": stations,
        "cells": cells_used,
        "values": values,
        "rules": [
            "Smog week: of every 7-day window from December 2025 to February 2026, the one with the highest mean "
            "of the hourly national means of PM2.5 at the automatic GIOŚ stations.",
            f"Each hex shows the inverse-distance-weighted mean of the stations within {RADIUS_KM:g} km that "
            "measured that hour; hexes farther from every station stay empty.",
        ],
    })
    print(f"    {n} hours x {len(cells_used)} hexes, {len(stations)} stations")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "smog.json"
    if not path.exists():
        return [("NOTE", "smog.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    n, cells = doc.get("hours") or 0, doc.get("cells") or []
    vals = doc.get("values") or []
    if len(vals) != n or any(len(r) != len(cells) for r in vals):
        out.append(("FAIL", "smog.json: values must have one row per hour, one value per cell"))
    if any(len(s.get("pm25") or []) != n for s in doc.get("stations") or []):
        out.append(("FAIL", "smog.json: every station needs one value per hour"))
    if any(v is not None and v < 0 for r in vals for v in r):
        out.append(("FAIL", "smog.json: negative PM2.5"))
    world = Path(web_dir) / "world.json"
    if world.exists() and cells:
        owner = json.loads(world.read_text())["owner"]
        if any(c < 0 or c >= len(owner) or owner[c] < 0 for c in cells):
            out.append(("FAIL", "smog.json: every cell must be Polish land"))
    size = path.stat().st_size
    if size > 3_000_000:
        out.append(("WARN", f"smog.json is {size / 1e6:.1f} MB (budget 3 MB)"))
    if not out:
        filled = sum(v is not None for r in vals for v in r)
        out.append(("PASS", f"smog.json: {n} hours from {doc.get('start')}, {len(doc.get('stations') or [])} "
                            f"stations, {len(cells)} hexes, {filled} hex-hours with a value, {size / 1e6:.2f} MB"))
    return out

"""Population through time (timeline.json): per-hex density and change since 2015 for every year 2015 to 2025
(31 December) and 30 June 2026, for the time slider of the density and change lenses.

A hex's population in year Y is the sum over its gmina parts of (the part's people in the density lens) x
population(Y) / population(30 June 2026) of that gmina, so the newest year matches the density lens. Density is
people per km2 of the hex's land, as in lenses.py. Change is population(Y) / population(31 Dec 2015) - 1 per gmina,
spread over the hexes with the same population weights as the change lens, so 2025 matches it. Values are stored
only for Polish land cells (the `cells` list), as integers: density x 10 and change x 1000.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..core.hexgrid import HexGrid
from ..core.paths import WEB_DATA
from ..core.store import load_interim, load_interim_payload, write_web
from .growth import comparable, rate
from .plstats import cell_weights, optional, spread, unsampled_cells
from .counties import projection

REQUIRES = ["_world", "pl_hist_population", "pl_geo_lau", "lenses.json"]
PRODUCES = ["timeline.json"]

LENS_DATE = "2026-06-30"  # the density lens date (GUS 30 June 2026)
CHANGE_DATE = "2025-12-31"  # the change lens end date


def field_key(date: str) -> str:
    return f"pop_{date[:4]}" if date.endswith("12-31") else f"pop_{date[:4]}_{date[5:7]}"


def label(date: str) -> str:
    return date[:4] if date.endswith("12-31") else {"06-30": "June "}[date[5:]] + date[:4]


def build() -> None:
    world = load_interim("_world")
    payload = load_interim_payload("pl_hist_population")
    data = payload["data"]
    dates = data["dates"]
    rows = data["tables"]["population_years"]["rows"]
    gminas = world["counties"]
    by6 = {c[:6]: r for c, r in rows.items()}
    pop = {d: [(by6.get(g[:6]) or {}).get(field_key(d)) for g in gminas] for d in dates}
    base = pop[LENS_DATE]
    grid = HexGrid(**world["grid"])
    lau = (optional("pl_geo_lau") or {}).get("data")
    extra = unsampled_cells(world, lau, projection(world), grid)
    weights = cell_weights(world, base, extra)
    owner = world["owner"]
    cells = [i for i in range(grid.size) if owner[i] >= 0]
    hex_area = 1.5 * math.sqrt(3) * grid.radius ** 2
    land_area = {}
    for i in cells:
        smp = world["county_samples"][i]
        if smp:
            land_area[i] = hex_area * (sum(1 for x in smp if x >= 0) or 1) / len(smp)

    density, change = [], []
    for d in dates:
        dens = []
        for i in cells:
            parts = weights[i]
            if not parts or i not in land_area:
                dens.append(None)
                continue
            people, ok = 0.0, False
            for k, p in parts:
                if pop[d][k] is not None and base[k]:
                    people += p * pop[d][k] / base[k]
                    ok = True
            dens.append(round(people / land_area[i] * 10) if ok else None)
        density.append(dens)
        g = [rate(pop[d][k], pop[dates[0]][k]) if comparable([gminas[k]]) else None for k in range(len(gminas))]
        sp = spread(weights, g, 4)
        change.append([None if sp[i] is None else round(sp[i] * 1000) for i in cells])

    lenses = json.loads((WEB_DATA / "lenses.json").read_text())
    dom = {l["id"]: l.get("domain") for l in lenses["lenses"] if l["id"] in ("density", "growth")}
    write_web("timeline.json", {
        "version": 1,
        "vintage": payload.get("vintage") or data.get("vintage"),
        "sources": ["pl_hist_population"],
        "dates": dates,
        "labels": [label(d) for d in dates],
        "lens_dates": {"density": LENS_DATE, "growth": CHANGE_DATE},
        "scale": {"density": 10, "growth": 1000},
        "domains": dom,
        "cells": cells,
        "density": density,
        "growth": change,
        "notes": [
            "Density: residents per km2 of the hex's land on each date (GUS). Change: population on the date / "
            "population on 31 December 2015 - 1.",
            "From 31 December 2021 GUS counts are based on the 2021 census, earlier ones on the 2011 census: part "
            "of the change between 2020 and 2021 comes from that rebasing.",
            "Each year is on that year's gmina borders.",
        ],
    })
    print(f"    {len(dates)} dates x {len(cells)} cells")


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "timeline.json"
    if not path.exists():
        return [("NOTE", "timeline.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    n, cells = len(doc.get("dates") or []), doc.get("cells") or []
    for key in ("density", "growth"):
        arr = doc.get(key) or []
        if len(arr) != n or any(len(a) != len(cells) for a in arr):
            out.append(("FAIL", f"timeline.json: {key} must have one array per date, one value per cell"))
        else:
            filled = sum(v is not None for v in arr[-1])
            out.append(("PASS", f"timeline.json {key}: {n} dates x {len(cells)} cells, {filled} with data on the "
                                f"last date"))
    world = Path(web_dir) / "world.json"
    if world.exists() and cells:
        w = json.loads(world.read_text())
        if any(c < 0 or c >= len(w["owner"]) or w["owner"][c] < 0 for c in cells):
            out.append(("FAIL", "timeline.json: every cell must be Polish land"))
    if doc.get("lens_dates", {}).get("density") not in (doc.get("dates") or []):
        out.append(("FAIL", "timeline.json: the density lens date is not among the dates"))
    return out

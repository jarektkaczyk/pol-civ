"""Historic borders (history.json): the 1914 partition borders and the border of interwar Poland, in map km, with a
label for each 1914 state placed in its part of today's Poland.

Lines come from pl_hist_borders (CShapes 2.0) and are projected like every other map layer. A label sits at a point
picked by hand inside the state's 1914 zone, clear of the voivodeship names and the big city banners (LABEL_AT); the
builder checks that the point lies inside the zone and otherwise uses the Polish land hex nearest the mean centre of
the zone's Polish land hexes. Label points carry no data.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.geo import ring_contains
from ..core.hexgrid import HexGrid
from ..core.store import load_interim, load_interim_payload, write_web
from .counties import projection

REQUIRES = ["_world", "pl_hist_borders"]
PRODUCES = ["history.json"]

TIP = {
    "borders_1914": "Border of {a} and {b} on 1 July 1914",
    "borders_1930": "Border of Poland and {b}, 1921-1939",
}
NAMES = {"Germany (Prussia)": "the German Empire", "Russia (Soviet Union)": "the Russian Empire",
         "Austria-Hungary": "Austria-Hungary", "Poland": "Poland", "Danzig": "the Free City of Danzig",
         "Lithuania": "Lithuania", "Latvia": "Latvia", "Rumania": "Romania", "Czechoslovakia": "Czechoslovakia"}
# Hand-picked label points (lon, lat) inside each 1914 zone: around Pila/Walcz, Ostroleka/Lomza and Sanok.
LABEL_AT = {"German Empire": (15.85, 52.95), "Russian Empire": (21.45, 52.95), "Austria-Hungary": (22.3, 49.6)}
NAMES_1930 = {**NAMES, "Germany (Prussia)": "Germany", "Russia (Soviet Union)": "the Soviet Union"}


def zone_label(rings, cells, centres, proj, at=None) -> list[float] | None:
    """[x, y] (map km): the point `at` (lon, lat) when it lies inside the rings, else the Polish land hex nearest
    the mean of the Polish land hexes inside the rings."""
    rings_km = [[proj(lon, lat) for lon, lat in r] for r in rings if len(r) >= 3]
    if at is not None:
        x, y = proj(*at)
        if sum(1 for r in rings_km if ring_contains(r, x, y)) % 2 == 1:
            return [round(x, 1), round(y, 1)]
        print(f"    ! label point {at} is outside its zone: placed automatically")
    inside = []
    for c in cells:
        x, y = centres[c]
        n = sum(1 for r in rings_km if ring_contains(r, x, y))
        if n % 2 == 1:
            inside.append(c)
    if not inside:
        return None
    mx = sum(centres[c][0] for c in inside) / len(inside)
    my = sum(centres[c][1] for c in inside) / len(inside)
    best = min(inside, key=lambda c: (centres[c][0] - mx) ** 2 + (centres[c][1] - my) ** 2)
    return [round(centres[best][0], 1), round(centres[best][1], 1)]


def build() -> None:
    world = load_interim("_world")
    payload = load_interim_payload("pl_hist_borders")
    grid = HexGrid(**world["grid"])
    proj = projection(world)
    cells = [i for i in range(grid.size) if world["owner"][i] >= 0]
    centres = {c: grid.center(*grid.col_row(c)) for c in cells}
    layers = []
    for layer in payload["data"]["layers"]:
        names = NAMES_1930 if layer["id"] == "borders_1930" else NAMES
        lines = []
        for ln in layer["lines"]:
            pts = []
            for lon, lat in ln["pts"]:
                x, y = proj(lon, lat)
                pts += [round(x, 2), round(y, 2)]
            a, b = ln["between"]
            lines.append({"between": [names.get(a, a), names.get(b, b)],
                          "tip": TIP[layer["id"]].format(a=names.get(a, a), b=names.get(b, b)), "pts": pts})
        labels = []
        if layer["id"] == "borders_1914":
            for area in layer["areas"]:
                pos = zone_label(area["rings"], cells, centres, proj, LABEL_AT.get(area["name"]))
                if pos:
                    labels.append({"name": area["name"], "x": pos[0], "y": pos[1]})
        layers.append({"id": layer["id"], "date": layer["date"], "label": layer["label"], "lines": lines,
                       "labels": labels})
    write_web("history.json", {
        "version": 1,
        "vintage": payload.get("vintage"),
        "sources": ["pl_hist_borders"],
        "layers": layers,
        "rules": [
            "1914: the borders between the German Empire, the Russian Empire and Austria-Hungary on 1 July 1914.",
            "1921-1939: the border of Poland from the Treaty of Riga (18 March 1921) to 1939, as on 1 January 1930.",
            "A border is the stretch of a state's outline that runs within 2.5 km of its neighbour's outline "
            "(CShapes 2.0); coasts are left out.",
        ],
        "licence": "CShapes 2.0, ETH Zurich (Schvitz et al. 2022), CC BY-NC-SA 4.0",
    })
    print("    " + ", ".join(f"{l['id']}: {len(l['lines'])} lines, {len(l['labels'])} labels" for l in layers))


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "history.json"
    if not path.exists():
        return [("NOTE", "history.json missing (optional)")]
    doc = json.loads(path.read_text())
    out = []
    if doc.get("version") != 1 or not isinstance(doc.get("sources"), list):
        out.append(("FAIL", "history.json: version 1 and a sources list are required"))
    for layer in doc.get("layers") or []:
        bad = [ln for ln in layer.get("lines") or [] if len(ln.get("pts") or []) < 4 or len(ln["pts"]) % 2]
        if bad:
            out.append(("FAIL", f"history.json {layer.get('id')}: {len(bad)} lines with a bad point list"))
        km = sum(len(ln["pts"]) // 2 for ln in layer.get("lines") or [])
        out.append(("PASS", f"history.json {layer.get('id')}: {len(layer.get('lines') or [])} lines, {km} points, "
                            f"labels: {', '.join(l['name'] for l in layer.get('labels') or []) or 'none'}"))
    return out

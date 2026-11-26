"""The map itself: hex grid, land and water, relief, land cover, voivodeships, gminy, rivers and lakes of Poland.

Also saves interim "_world" (grid + projection + per-cell voivodeship/gmina/water/cover) so the other builders can
drop their data onto the same hexes.
"""

from __future__ import annotations

import math
from collections import Counter, deque

from ..core.geo import PL_ALBERS, PL_LAT, PL_LON, Albers, MapProjection, Shape, ShapeIndex
from ..core.hexgrid import SQRT3, HexGrid
from ..core.store import load_interim, save_interim, write_web

REQUIRES = ["pl_geo_lau", "pl_geo_teryt", "pl_geo_ne", "pl_geo_etopo", "pl_geo_worldcover", "pl_geo_forest_type",
            "pl_geo_hydrorivers"]
PRODUCES = ["_world", "world.json"]

HEX_RADIUS_KM = 5.0
MARGIN_KM = 0.0  # the map window (core.geo PL_LON / PL_LAT) already holds the neighbours and the Baltic

# Cell owner codes (besides voivodeship index >= 0)
WATER, FOREIGN = -1, -2

# --- tables (written to world.json so the frontend and the Almanac read one definition) --------------------------

LAND, OCEAN, COAST, LAKE = range(4)
TIDAL_SEA_SHARE = 0.5  # share of ETOPO samples below 0 m that keeps a sea-centred hex as water
COAST_DEPTH_M = -40  # the Baltic is shallow: deeper than this and away from land is "open sea"
LAKE_SHARE = 0.5  # WorldCover water share of a hex's land points that makes it a lake hex
WATER_TABLE = [
    {"id": LAND, "name": "Land", "rule": "At least 4 of the hex's 7 sample points (centre + 6) fall on a gmina "
     "(GISCO LAU) or a neighbouring country (Natural Earth), unless the centre is sea and the ETOPO 2022 mean is at or "
     "below sea level, or at least half its ETOPO samples are."},
    {"id": OCEAN, "name": "Open sea", "color": "#1d3f63", "rule": "Baltic deeper than 40 m and not next to land."},
    {"id": COAST, "name": "Coastal water", "color": "#2b6790", "rule": "Sea or lagoon next to a land hex, or "
     "shallower than 40 m (ETOPO 2022 mean). The Szczecin, Vistula and Curonian lagoons are coastal water."},
    {"id": LAKE, "name": "Lake", "color": "#3a80b0", "rule": "At least half of the hex's land-cover points are "
     "permanent water (ESA WorldCover 2021) and the water surface is above sea level (ETOPO 2022). A lake hex next "
     "to the sea stays a lake only where Natural Earth has a lake (Łebsko); otherwise it is a lagoon (coastal water)."},
]
WATER_NOTE = (
    "Gmina outlines (GISCO LAU 2024, 1:1 million) and Natural Earth 1:10m country outlines do not meet exactly. A sea "
    "hex whose ETOPO 2022 mean is above sea level (and under half of its samples below it) becomes land when at least "
    "4 of its 6 neighbours are land, or when it touches both Polish and foreign land; it takes the neighbours' "
    "majority owner. Lakes and the land of spits narrower than a hex (the Hel Peninsula, the Vistula Spit) are drawn "
    "as outlines over the hexes (world.json lakes and spits). A sea hex's elevation is the mean of its ETOPO samples "
    "below sea level (its water depth)."
)

FLAT, HILLS, MOUNTAINS, PEAKS = range(4)
LAND_MIN_ALT_M = -30  # ETOPO samples below this inside a land hex are treated as sea floor (Zulawy lies at -2 m)
HILLS_STD_M, MOUNTAINS_STD_M, MOUNTAINS_MEAN_M, PEAKS_MAX_M = 28.0, 110.0, 750.0, 1450.0
RELIEF_TABLE = [
    {"id": FLAT, "name": "Flat", "rule": f"Elevation standard deviation inside the hex under {HILLS_STD_M:g} m."},
    {"id": HILLS, "name": "Hills", "rule": f"Elevation standard deviation of {HILLS_STD_M:g} m or more (moraine "
     "hills, uplands)."},
    {"id": MOUNTAINS, "name": "Mountains", "rule": f"Elevation standard deviation of {MOUNTAINS_STD_M:g} m or more, "
     f"or mean elevation of {MOUNTAINS_MEAN_M:,.0f} m or more."},
    {"id": PEAKS, "name": "Peaks", "rule": f"Mountains whose highest sample reaches {PEAKS_MAX_M:,.0f} m, above the "
     "tree line (the Tatra, Babia Góra, Pilsko, the Karkonosze with Śnieżka)."},
]
RELIEF_NOTE = (
    "From ETOPO 2022 samples (15 arc-second, about 460 m by 290 m, roughly 300 per hex) at -30 m or higher, so "
    "lagoons and sea floor do not count; all samples are used if none qualify. Water hexes are always flat. "
    "A hex whose lower 60% of samples is flat lowland (spread under 15 m, under 300 m) is eased one class."
)

URBAN_MIN_PCT = 28
# id, key, name, colour, WorldCover codes, rule. Ids are fixed by docs/DATA_CONTRACTS.md.
COVER = [
    (1, "forest_deciduous", "Deciduous forest", "#4f7a35", [10], "Tree cover (WorldCover 10) is the largest group "
     "and broad-leaved forest the largest forest type (Copernicus forest type layer 2019)."),
    (2, "forest_evergreen", "Conifer forest", "#2f5a3a", [10], "Tree cover is the largest group and needle-leaved "
     "forest (pine, spruce, larch) the largest forest type."),
    (3, "forest_mixed", "Mixed forest", "#43703f", [10], "Tree cover is the largest group and mixed forest the "
     "largest forest type, or the type is unknown."),
    (4, "scrub", "Scrub", "#9fa069", [20], "Shrubland (WorldCover 20) is the largest group."),
    (5, "grassland", "Mountain meadows", "#9fb35a", [30, 100], "Grassland (30) or moss and lichen (100) is the "
     "largest group in a hex 900 m or higher: mountain meadows and alpine grass."),
    (6, "pasture", "Meadows and pastures", "#8fb04e", [30], "Grassland (WorldCover 30) is the largest group in a "
     "hex under 900 m. In lowland Poland this class is mostly hay meadows and pastures."),
    (7, "cropland", "Farmland", "#bdb45c", [40], "Cropland (WorldCover 40) is the largest group."),
    (8, "wetland", "Wetland", "#4f8a6e", [90], "Herbaceous wetland (WorldCover 90: fens, reed beds, river marshes) is "
     "the largest group."),
    (9, "urban", "Built-up", "#8a8378", [50], f"Built-up land (WorldCover 50) is {URBAN_MIN_PCT}% or more of the "
     "hex's land, whatever else is there."),
    (10, "barren", "Bare rock and sand", "#bfae95", [60], "Bare or sparse vegetation (60: rock, dunes, quarries) "
     "is the largest group."),
    (11, "ice", "Snow and ice", "#e8eef2", [70], "Permanent snow and ice (70) is the largest group."),
]
COVER_NOTE = (
    "From ESA WorldCover 2021 (read at 1/375 degree, about 300 m by 180 m), sampled on a 450 m lattice inside each "
    "hex (about 320 points). Water and no-data points are ignored; shares are of the remaining land points, rounded "
    "to whole percent, and the built-up threshold is applied to the rounded share. The forest type (conifer, "
    "deciduous, mixed) is the most common type of the Copernicus Global Land Cover 2019 forest layer at the hex's "
    "tree points. Neighbouring countries get a cover class for the map art; their shares (pct) stay 0."
)
WC_GROUPS = {"forest": (10,), "scrub": (20,), "grass": (30, 100), "crop": (40,), "wetland": (90, 95),
             "barren": (60,), "ice": (70,)}
GROUP_ID = {"scrub": 4, "crop": 7, "wetland": 8, "barren": 10, "ice": 11}
URBAN_ID = 9
MOUNTAIN_GRASS_M = 900
FOREST_TYPE = {"n": 2, "l": 2, "d": 1, "b": 1, "m": 3}  # forest type code -> cover id
PCT = {"forest": (10,), "crop": (40,), "pasture": (), "grass": (), "shrub": (20,), "wetland": (90, 95),
       "developed": (50,)}
LATTICE_KM = 0.45

# Rivers: HydroRIVERS chains (a river's main stem from its source to where it joins a bigger one).
RIVER_MIN_UPLAND_KM2 = 1500  # a chain is drawn when its catchment at the mouth is at least this
RIVER_NAME_KM = 3.0  # a Natural Earth river within this distance of most of a chain names it

# Lakes and spits drawn as outlines over the hexes.
LAKE_MIN_KM2 = 1.0  # in Poland; lakes in the neighbouring countries need FOREIGN_LAKE_MIN_KM2
FOREIGN_LAKE_MIN_KM2 = 4.0
SPIT_MIN_KM2 = 0.4
SPIT_RES_KM = 0.1
# Natural Earth draws these coastal lagoons as lakes; on the map they are coastal sea (water id 2).
LAGOONS = {"Zalew Wislany", "Kaliningradskiy Zaliv"}


def classify_relief(mean: float, std: float, emax: float) -> int:
    if std >= MOUNTAINS_STD_M or mean >= MOUNTAINS_MEAN_M:
        return PEAKS if emax >= PEAKS_MAX_M else MOUNTAINS
    if std >= HILLS_STD_M:
        return HILLS
    return FLAT


def is_valley_floor(samples: list) -> bool:
    """True when the lower 60% of a hex's land samples is flat lowland (within 15 m, under 300 m): the hex is mostly
    valley floor even if a scarp at its edge makes the whole hex's spread look hilly."""
    if len(samples) < 10:
        return False
    v = sorted(samples)
    lo = v[: max(3, int(len(v) * 0.6))]
    return lo[-1] < 300 and lo[-1] - lo[0] < 15


def dominant_cover(counts: Counter, land: int, elev: float, forest_types: Counter) -> int:
    """Cover id for a hex from its WorldCover class counts (land = points that are not water or no-data)."""
    if not land:
        return 0
    if round(100 * counts[50] / land) >= URBAN_MIN_PCT:  # same rounding as pct.developed
        return URBAN_ID
    best, best_n = None, 0
    for g, codes in WC_GROUPS.items():  # dict order breaks ties
        n = sum(counts[c] for c in codes)
        if n > best_n:
            best, best_n = g, n
    if best is None:
        return 0  # only built-up land below the urban threshold
    if best == "forest":
        by_id = Counter()
        for ch, n in forest_types.items():
            if ch in FOREST_TYPE:
                by_id[FOREST_TYPE[ch]] += n
        return by_id.most_common(1)[0][0] if by_id else 3
    if best == "grass":
        return 5 if elev >= MOUNTAIN_GRASS_M else 6
    return GROUP_ID[best]


def land_pct(counts: Counter, land: int, elev: float) -> dict[str, int]:
    """Shares (0..100) of a hex's land points. WorldCover grassland counts as pasture below MOUNTAIN_GRASS_M and as
    grass above it."""
    out = {k: round(100 * sum(counts[c] for c in codes) / land) for k, codes in PCT.items()}
    grass = round(100 * (counts[30] + counts[100]) / land)
    out["grass" if elev >= MOUNTAIN_GRASS_M else "pasture"] = grass
    return out


# --- geometry helpers -------------------------------------------------------------------------------------------


def inscribed_window(albers: Albers, lon=PL_LON, lat=PL_LAT, n: int = 200) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) in Albers km of the largest axis-aligned rectangle inside the lon/lat window
    (its edges sampled `n` times), so every map hex lies where the gridded sources have data."""
    west = [albers(lon[0], lat[0] + (lat[1] - lat[0]) * k / n)[0] for k in range(n + 1)]
    east = [albers(lon[1], lat[0] + (lat[1] - lat[0]) * k / n)[0] for k in range(n + 1)]
    south = [albers(lon[0] + (lon[1] - lon[0]) * k / n, lat[0])[1] for k in range(n + 1)]
    north = [albers(lon[0] + (lon[1] - lon[0]) * k / n, lat[1])[1] for k in range(n + 1)]
    return max(west), max(south), min(east), min(north)


def simplify(points: list[tuple[float, float]], min_km: float) -> list[tuple[float, float]]:
    out = [points[0]]
    for p in points[1:-1]:
        if math.dist(p, out[-1]) >= min_km:
            out.append(p)
    out.append(points[-1])
    return out


def douglas_peucker(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker simplification of an open polyline (iterative)."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        best, best_d = -1, tol
        for k in range(a + 1, b):
            px, py = pts[k]
            d = abs(dy * (px - ax) - dx * (py - ay)) / L if L else math.hypot(px - ax, py - ay)
            if d > best_d:
                best, best_d = k, d
        if best >= 0:
            keep[best] = True
            stack += [(a, best), (best, b)]
    return [p for p, k in zip(pts, keep) if k]


def chaikin_closed(ring: list[tuple[float, float]], rounds: int = 2) -> list[tuple[float, float]]:
    """Corner-cutting smoothing of a closed ring (no repeated end point)."""
    for _ in range(rounds):
        out = []
        n = len(ring)
        for k in range(n):
            (x0, y0), (x1, y1) = ring[k], ring[(k + 1) % n]
            out += [(0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1), (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1)]
        ring = out
    return ring


def ring_area(ring: list[tuple[float, float]]) -> float:
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))


def trace_rings(pixels: set[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """Outlines of a set of raster pixels (row, col) as closed rings of pixel-corner vertices (row, col), outer
    rings and holes alike, with the pixels on the left of each directed edge. Diagonal touches split rings."""
    nxt: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def edge(a, b):
        nxt.setdefault(a, []).append(b)

    for r, c in pixels:
        if (r - 1, c) not in pixels:
            edge((r, c + 1), (r, c))  # top edge, running west
        if (r + 1, c) not in pixels:
            edge((r + 1, c), (r + 1, c + 1))  # bottom edge, running east
        if (r, c - 1) not in pixels:
            edge((r, c), (r + 1, c))  # left edge, running south
        if (r, c + 1) not in pixels:
            edge((r + 1, c + 1), (r, c + 1))  # right edge, running north
    rings = []
    while nxt:
        start = next(iter(nxt))
        ring = [start]
        prev, cur = None, start
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            if len(outs) > 1 and prev is not None:
                # Saddle vertex: turn so that the pixel stays on the left (take the sharpest left turn).
                din = (cur[0] - prev[0], cur[1] - prev[1])
                outs.sort(key=lambda o: _turn(din, (o[0] - cur[0], o[1] - cur[1])))
            nb = outs.pop(0)
            if not outs:
                del nxt[cur]
            prev, cur = cur, nb
            if cur == start:
                break
            ring.append(cur)
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def _turn(din, dout) -> int:
    """0 for a left turn, 1 straight, 2 right (in row/col space with rows down, as seen on screen)."""
    cross = din[1] * dout[0] - din[0] * dout[1]
    return 0 if cross < 0 else 1 if cross == 0 else 2


def components(pixels: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    """4-connected components of a pixel set."""
    seen: set = set()
    out = []
    for p in pixels:
        if p in seen:
            continue
        comp = {p}
        seen.add(p)
        q = deque([p])
        while q:
            r, c = q.popleft()
            for nb in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if nb in pixels and nb not in seen:
                    seen.add(nb)
                    comp.add(nb)
                    q.append(nb)
        out.append(comp)
    return out


def rasterise_in_cells(shapes: list[Shape], cells: set[int], grid: HexGrid, res: float) -> set[tuple[int, int]]:
    """Pixels (row, col) of a `res`-km raster whose centre lies inside any of `shapes` (union; each shape even-odd)
    and inside one of `cells`. Scanline fill: only the rows and columns of those cells are visited."""
    if not cells:
        return set()
    R = grid.radius
    boxes = {}
    for i in cells:
        cx, cy = grid.center(*grid.col_row(i))
        boxes[i] = (int((cx - R) / res), int((cx + R) / res) + 1, int((cy - R) / res), int((cy + R) / res) + 1)
    rows_needed = {r for b in boxes.values() for r in range(b[2], b[3] + 1)}
    y_lo, y_hi = min(rows_needed) * res, (max(rows_needed) + 1) * res
    x_lo = min(b[0] for b in boxes.values()) * res
    x_hi = (max(b[1] for b in boxes.values()) + 1) * res
    # Crossings per row per shape (so overlapping shapes add up instead of cancelling).
    cross: dict[int, dict[int, list[float]]] = {}
    for k, sh in enumerate(shapes):
        x0, y0, x1, y1 = sh.bbox
        if x1 < x_lo or x0 > x_hi or y1 < y_lo or y0 > y_hi:
            continue
        for ring in sh.rings:
            for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
                if ay == by:
                    continue
                lo, hi = (ay, by) if ay < by else (by, ay)
                for r in range(max(int(lo / res - 0.5) + 1, 0), int(hi / res - 0.5) + 1):
                    if r not in rows_needed:
                        continue
                    y = (r + 0.5) * res
                    if lo <= y < hi:
                        cross.setdefault(r, {}).setdefault(k, []).append(ax + (y - ay) * (bx - ax) / (by - ay))
    spans: dict[int, list[tuple[float, float]]] = {}
    for r, per in cross.items():
        sp = []
        for xs in per.values():
            xs.sort()
            sp += [(xs[j], xs[j + 1]) for j in range(0, len(xs) - 1, 2)]
        spans[r] = sorted(sp)
    out = set()
    for i, (c0, c1, r0, r1) in boxes.items():
        for r in range(r0, r1 + 1):
            sp = spans.get(r)
            if not sp:
                continue
            y = (r + 0.5) * res
            for a, b in sp:
                if b < c0 * res or a > (c1 + 1) * res:
                    continue
                for c in range(max(c0, int(a / res - 0.5) + 1), min(c1, int(b / res - 0.5)) + 1):
                    if grid.cell_at((c + 0.5) * res, y) == i:
                        out.add((r, c))
    return out


def clip_segment(p, q, w, h):
    """Liang-Barsky: the part of segment p->q inside [0,w]x[0,h], or None."""
    (x0, y0), (x1, y1) = p, q
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0), (dx, w - x0), (-dy, y0), (dy, h - y0)):
        if pk == 0:
            if qk < 0:
                return None
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy)


def clip_polyline(pts, w, h) -> list[list[tuple[float, float]]]:
    """Split a polyline into the pieces that lie inside the map rectangle."""
    pieces, cur = [], []
    for p, q in zip(pts, pts[1:]):
        seg = clip_segment(p, q, w, h)
        if seg is None:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = []
            continue
        a, b = seg
        if cur and math.dist(cur[-1], a) < 1e-9:
            cur.append(b)
        else:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = [a, b]
        if b != q:  # left the map inside this segment
            pieces.append(cur)
            cur = []
    if len(cur) >= 2:
        pieces.append(cur)
    return pieces


def hex_lattice(radius: float, step: float) -> list[tuple[float, float]]:
    """Offsets of a square lattice (spacing `step`) that fall inside a pointy-top hex."""
    half_w = SQRT3 / 2 * radius
    n = int(radius // step) + 1
    out = []
    for iy in range(-n, n + 1):
        for ix in range(-n, n + 1):
            x, y = (ix + 0.5) * step, (iy + 0.5) * step
            if abs(x) <= half_w and abs(y) <= radius - abs(x) / SQRT3:
                out.append((x, y))
    return out


def majority(values: list, centre) -> object:
    """Most common value; ties go to `centre` if it is among the tied, else to the first seen."""
    counts = Counter(values)
    top = max(counts.values())
    tied = [v for v in counts if counts[v] == top]
    return centre if centre in tied else tied[0]


def river_chains(reaches: list[dict]) -> list[list[dict]]:
    """Group HydroRIVERS reaches into main-stem chains: at each confluence the upstream reach with the largest
    catchment continues the river, the others end there as tributaries. Each chain runs source -> mouth."""
    by_id = {r["id"]: r for r in reaches}
    ups: dict[int, list[dict]] = {}
    for r in reaches:
        if r["next"] in by_id:
            ups.setdefault(r["next"], []).append(r)
    main_up = {rid: max(lst, key=lambda u: (u["upland_km2"], -u["id"]))["id"] for rid, lst in ups.items()}
    chains = []
    for r in reaches:
        if main_up.get(r["next"]) == r["id"] and r["next"] in by_id:
            continue  # not a head: it continues into its downstream reach's chain from above
        # r is the lowest reach of a chain (an outlet, or a tributary's last reach): walk upstream along main_up.
        chain = [r]
        while chain[-1]["id"] in main_up:
            chain.append(by_id[main_up[chain[-1]["id"]]])
        chain.reverse()
        # A tributary ends where it meets its downstream reach (that reach's first point).
        nxt = by_id.get(r["next"])
        chains.append(chain + ([{"line": nxt["line"][:1], "join": True}] if nxt else []))
    return chains


def river_rank(dis_m3s: float | None) -> int:
    """1 (largest) .. 9 from long-term mean discharge at the mouth: Vistula ~1,000 m3/s is 1, a 5 m3/s river 7."""
    if not dis_m3s or dis_m3s <= 0:
        return 9
    return max(1, min(9, round(9 - 2.6 * math.log10(dis_m3s))))


# --- build --------------------------------------------------------------------------------------------------------


def build() -> None:
    lau = load_interim("pl_geo_lau")
    teryt = load_interim("pl_geo_teryt")
    ne = load_interim("pl_geo_ne")
    etopo = load_interim("pl_geo_etopo")
    wc = load_interim("pl_geo_worldcover")
    ft = load_interim("pl_geo_forest_type")
    hydro = load_interim("pl_geo_hydrorivers")

    # --- units: voivodeships, powiaty, gminy (TERYT codes in force now; outlines from LAU) --------------------------
    voivs = teryt["voivodeships"]
    voiv_idx = {v["code"]: k for k, v in enumerate(voivs)}
    powiaty = teryt["powiaty"]
    pow_idx = {p["code"]: k for k, p in enumerate(powiaty)}
    gminy = teryt["gminy"]  # sorted by code
    by6 = {g["code"][:6]: k for k, g in enumerate(gminy)}
    outlines = []  # (gmina index, rings)
    notes = []
    for g in lau["gminy"]:
        k = by6.get(g["teryt6"])
        if k is None:
            notes.append(f"LAU {lau['year']} gmina {g['teryt6']} {g['name']} is not in the {teryt['year']} register")
            continue
        outlines.append((k, g["rings"]))
    no_outline = [g for g in gminy if g["code"][:6] not in {x["teryt6"] for x in lau["gminy"]}]
    for g in no_outline:
        notes.append(f"{g['code']} {g['name']}: in the {teryt['year']} register but not in LAU {lau['year']} "
                     "(created since); its land is drawn as part of the gmina it was split from")
    renamed = [(g["teryt6"], g["name"], gminy[by6[g["teryt6"]]]["name"]) for g in lau["gminy"]
               if g["teryt6"] in by6 and g["name"] != gminy[by6[g["teryt6"]]]["name"]]
    for code6, old, new in renamed:
        notes.append(f"gmina {code6}: LAU {lau['year']} name {old!r}, {teryt['year']} register name {new!r}")
    for n in notes:
        print(f"    note: {n}")

    # --- projection and grid ----------------------------------------------------------------------------------------
    albers = Albers(**PL_ALBERS)
    x0, y0, x1, y1 = inscribed_window(albers)
    proj = MapProjection(x0, y1, MARGIN_KM)
    width, height = x1 - x0 + 2 * MARGIN_KM, y1 - y0 + 2 * MARGIN_KM
    grid = HexGrid.covering(width, height, HEX_RADIUS_KM)
    print(f"    grid {grid.cols}x{grid.rows} = {grid.size} hexes of {HEX_RADIUS_KM:g} km; map {width:.0f} x {height:.0f} km")

    def to_map(lon, lat):
        return proj(lon, lat)

    def shape(rings):
        return Shape([[to_map(lon, lat) for lon, lat in r] for r in rings])

    gmina_shapes = [shape(r) for _, r in outlines]
    gmina_of_shape = [k for k, _ in outlines]
    gmina_idx = ShapeIndex(gmina_shapes, cell_km=12)
    foreign = [c for c in ne["countries"] if c["iso"] != "POL"]
    foreign_shapes = [shape(c["rings"]) for c in foreign]
    foreign_idx = ShapeIndex(foreign_shapes, cell_km=40)
    lagoon_idx = ShapeIndex([shape(l["rings"]) for l in ne["lakes"] if l.get("name_en") in LAGOONS], cell_km=40)

    def locate_gmina(x, y) -> int:
        k = gmina_idx.locate(x, y)
        return gmina_of_shape[k] if k >= 0 else -1

    # --- elevation statistics per hex -----------------------------------------------------------------------------
    stats_all = [[0, 0.0, 0.0] for _ in range(grid.size)]
    stats_land = [[0, 0.0, 0.0] for _ in range(grid.size)]
    samples_land = [[] for _ in range(grid.size)]
    below_sea = [0] * grid.size
    below_sum = [0.0] * grid.size
    n_al, c_al = albers.n, albers.c
    lon_c = [math.radians(etopo["lon0"] + k * etopo["step"]) for k in range(etopo["cols"])]
    sin_t = [math.sin(n_al * (lo - albers.lon0)) for lo in lon_c]
    cos_t = [math.cos(n_al * (lo - albers.lon0)) for lo in lon_c]
    for r, row in enumerate(etopo["rows"]):
        lat = etopo["lat_top"] - r * etopo["step"]
        rho = 6371.0088 * math.sqrt(c_al - 2 * n_al * math.sin(math.radians(lat))) / n_al
        for c, alt in enumerate(row):
            if alt is None:
                continue
            i = grid.cell_at(rho * sin_t[c] - x0 + MARGIN_KM, y1 - (albers.rho0 - rho * cos_t[c]) + MARGIN_KM)
            if i < 0:
                continue
            if alt < 0:
                below_sea[i] += 1
                below_sum[i] += alt
            st = stats_all[i]
            st[0] += 1
            st[1] += alt
            st[2] += alt * alt
            if alt >= LAND_MIN_ALT_M:
                st = stats_land[i]
                st[0] += 1
                st[1] += alt
                st[2] += alt * alt
                samples_land[i].append(alt)

    def sea_share(i):
        return below_sea[i] / stats_all[i][0] if stats_all[i][0] else 0.0

    def mean_std(st):
        n, s1, s2 = st
        if not n:
            return None, None
        m = s1 / n
        return m, math.sqrt(max(0.0, s2 / n - m * m))

    # --- land-cover lattice per hex (WorldCover + forest type) ---------------------------------------------------
    wc_rows, wc_legend = wc["rows"], wc["legend"]
    wc_lon0, wc_top, wc_step, wc_cols, wc_n = wc["lon0"], wc["lat_top"], wc["step"], wc["cols"], len(wc["rows"])
    ft_rows = ft["rows"]
    ft_lon0, ft_top, ft_sx, ft_sy, ft_cols, ft_n = ft["lon0"], ft["lat_top"], ft["step_x"], ft["step_y"], ft["cols"], len(ft_rows)
    lattice = hex_lattice(HEX_RADIUS_KM, LATTICE_KM)
    wc_counts: list[Counter] = [Counter() for _ in range(grid.size)]
    ft_counts: list[Counter] = [Counter() for _ in range(grid.size)]
    for i in range(grid.size):
        cx, cy = grid.center(*grid.col_row(i))
        cnt, fcnt = wc_counts[i], ft_counts[i]
        for ox, oy in lattice:
            lon, lat = proj.inverse(cx + ox, cy + oy)
            r, c = int((wc_top - lat) / wc_step), int((lon - wc_lon0) / wc_step)
            if not (0 <= r < wc_n and 0 <= c < wc_cols):
                continue
            ch = wc_rows[r][c]
            cnt[ch] += 1
            if ch == "t":
                fr, fc = int((ft_top - lat) / ft_sy), int((lon - ft_lon0) / ft_sx)
                if 0 <= fr < ft_n and 0 <= fc < ft_cols:
                    fcnt[ft_rows[fr][fc]] += 1
    wc_counts = [Counter({wc_legend[ch]: n for ch, n in cnt.items()}) for cnt in wc_counts]

    def water_share(i):
        cnt = wc_counts[i]
        tot = sum(cnt.values())
        return cnt[80] / tot if tot else 0.0

    # --- ownership: majority of 7 sample points --------------------------------------------------------------------
    offsets = [(0.0, 0.0)] + [
        (0.6 * HEX_RADIUS_KM * math.cos(math.radians(60 * k - 30)), 0.6 * HEX_RADIUS_KM * math.sin(math.radians(60 * k - 30)))
        for k in range(6)
    ]
    gmina_voiv = [voiv_idx[g["code"][:2]] for g in gminy]
    owner = [WATER] * grid.size
    water = [OCEAN] * grid.size
    county_samples: list[list[int]] = [[] for _ in range(grid.size)]
    for i in range(grid.size):
        cx, cy = grid.center(*grid.col_row(i))
        kinds, gsmp = [], []
        for dx, dy in offsets:
            x, y = cx + dx, cy + dy
            g = locate_gmina(x, y)
            gsmp.append(g)
            if g < 0 and lagoon_idx.locate(x, y) >= 0:
                kinds.append("sea")
            elif g >= 0:
                kinds.append(gmina_voiv[g])
            elif foreign_idx.locate(x, y) >= 0:
                kinds.append(FOREIGN)
            else:
                kinds.append("sea")
        land = [k for k in kinds if k != "sea"]
        m_all, _ = mean_std(stats_all[i])
        tidal = kinds[0] == "sea" and m_all is not None and (m_all <= 0 or sea_share(i) >= TIDAL_SEA_SHARE)
        m_land, _ = mean_std(stats_land[i])
        if len(land) * 2 > len(kinds) and not tidal:
            if water_share(i) >= LAKE_SHARE and m_land is not None and m_land > 0.5:
                water[i] = LAKE
                continue
            pl = [k for k in land if k >= 0]
            n_foreign = len(land) - len(pl)
            if len(pl) > n_foreign or (len(pl) == n_foreign and kinds[0] != FOREIGN):
                owner[i] = majority(pl, kinds[0])
                county_samples[i] = gsmp
            else:
                owner[i] = FOREIGN
            water[i] = LAND
        else:
            water[i] = OCEAN

    # Lake hexes next to the sea are lagoons and bays (the Curonian Lagoon, the Szczecin Lagoon's arms, the German
    # Bodden) unless a Natural Earth lake lies under them (Łebsko, Gardno: coastal lakes behind a dune bar).
    ne_lake_idx = ShapeIndex([shape(l["rings"]) for l in ne["lakes"] if l.get("name_en") not in LAGOONS], cell_km=40)
    lagoon_cells = []
    for i in range(grid.size):
        if water[i] == LAKE and any(water[j] == OCEAN for j in grid.neighbours(i)):
            cx, cy = grid.center(*grid.col_row(i))
            if ne_lake_idx.locate(cx, cy) < 0:
                lagoon_cells.append(i)
    for i in lagoon_cells:
        water[i] = OCEAN
    print(f"    {len(lagoon_cells)} lake hexes next to the sea turned into coastal water (lagoons)")

    # Sliver fix: LAU and Natural Earth outlines do not meet exactly along the borders (the Oder, the Bug, the Neisse).
    slivers = []
    for i in range(grid.size):
        if water[i] != OCEAN:
            continue
        m, _ = mean_std(stats_all[i])
        land_nb = [owner[j] for j in grid.neighbours(i) if water[j] == LAND]
        border = FOREIGN in land_nb and any(o >= 0 for o in land_nb)
        if m is not None and m > 0 and sea_share(i) < TIDAL_SEA_SHARE and (len(land_nb) >= 4 or border):
            slivers.append((i, Counter(land_nb).most_common(1)[0][0]))
    for i, o in slivers:
        owner[i], water[i] = o, LAND
        if o >= 0:
            cx, cy = grid.center(*grid.col_row(i))
            county_samples[i] = [locate_gmina(cx + dx, cy + dy) for dx, dy in offsets]
    print(f"    {len(slivers)} sliver water hexes turned into land")

    # --- gmina of each Polish hex ----------------------------------------------------------------------------------
    county = [-1] * grid.size
    borrowed = 0
    for i in range(grid.size):
        smp = county_samples[i]
        if smp and max(smp) < 0:
            nb = [k for j in grid.neighbours(i) if owner[j] == owner[i] for k in county_samples[j] if k >= 0]
            if nb:
                smp[0] = Counter(nb).most_common(1)[0][0]
                borrowed += 1
    off_voiv = 0
    for i, smp in enumerate(county_samples):
        valid = [k for k in smp if k >= 0]
        if not valid:
            continue
        same = [k for k in valid if gmina_voiv[k] == owner[i]]
        pool = same or valid
        county[i] = smp[0] if smp[0] in pool else Counter(pool).most_common(1)[0][0]
        off_voiv += not same
    print(f"    {borrowed} hexes borrowed a neighbour's gmina; {off_voiv} have no gmina in their own voivodeship")

    # Gminy that no sample point hits, with the reason (lenses and statistics cannot place them on a hex).
    sampled = {k for smp in county_samples for k in smp if k >= 0}
    outline_of = {k: sh for k, sh in zip(gmina_of_shape, gmina_shapes)}
    area_of = {by6[g["teryt6"]]: g.get("area_km2") for g in lau["gminy"] if g["teryt6"] in by6}
    unsampled = []
    for k, g in enumerate(gminy):
        if k in sampled:
            continue
        sh = outline_of.get(k)
        if sh is None:
            reason = f"no outline in LAU {lau['year']} (created after 1 January {lau['year']})"
        else:
            x0b, y0b, x1b, y1b = sh.bbox
            c = grid.cell_at((x0b + x1b) / 2, (y0b + y1b) / 2)
            if c >= 0 and water[c] != LAND:
                reason = "its land lies in sea hexes (a spit or the shore), drawn as an outline"
            else:
                reason = f"smaller than the sample spacing ({area_of.get(k) or 0:.0f} km2)"
        unsampled.append({"code": g["code"], "name": g["name"], "reason": reason})
    print(f"    {len(unsampled)} of {len(gminy)} gminy own no sample point; "
          f"{len(gminy) - len({c for c in county if c >= 0})} are the gmina of no hex")

    # --- elevation, water depth classes and relief ---------------------------------------------------------------
    elev = [0] * grid.size
    relief = [FLAT] * grid.size
    elev_max = [0] * grid.size
    valley_floor = no_elev = 0
    for i in range(grid.size):
        if water[i] == LAND:
            m, sd = mean_std(stats_land[i])
            if m is None:
                m, sd = mean_std(stats_all[i])
                m = None if m is None else max(m, 0.0)
            if m is None:
                no_elev += 1
                continue
            elev[i] = round(m)
            emax = max(samples_land[i]) if samples_land[i] else m
            relief[i] = classify_relief(m, sd, emax)
            if relief[i] == HILLS and is_valley_floor(samples_land[i]):
                relief[i] = FLAT
                valley_floor += 1
            elev_max[i] = max(0, round(emax))
        else:
            m, _ = mean_std(stats_all[i])
            if m is None:
                no_elev += 1
                elev[i] = -50
            elif water[i] != LAKE and below_sea[i]:
                elev[i] = round(below_sum[i] / below_sea[i])
            else:
                elev[i] = min(round(m), 0)
            if water[i] == OCEAN:
                near_land = any(water[j] == LAND for j in grid.neighbours(i))
                water[i] = COAST if near_land or elev[i] > COAST_DEPTH_M else OCEAN
    print(f"    {no_elev} hexes without elevation samples; {valley_floor} valley-floor hexes eased to flat")

    # --- land cover ----------------------------------------------------------------------------------------------
    cover = [0] * grid.size
    pct = {k: [0] * grid.size for k in PCT}
    no_cover = 0
    for i in range(grid.size):
        if water[i] != LAND:
            continue
        counts = wc_counts[i]
        land_n = sum(n for code, n in counts.items() if code not in (0, 80))
        cover[i] = dominant_cover(counts, land_n, elev[i], ft_counts[i])
        if not land_n:
            no_cover += 1
            continue
        if owner[i] >= 0:
            for k, v in land_pct(counts, land_n, elev[i]).items():
                pct[k][i] = v
    print(f"    {len(lattice)} land-cover points per hex; {no_cover} land hexes without land-cover points")

    # --- rivers (HydroRIVERS chains, named from Natural Earth) ----------------------------------------------------
    ne_lines = []
    for rv in ne["rivers"]:
        if rv.get("name"):
            ne_lines.append((rv["name"], [to_map(lon, lat) for lon, lat in rv["line"]]))
    name_bucket: dict[tuple[int, int], list[tuple[str, tuple, tuple]]] = {}
    B = 10.0
    for name, pts in ne_lines:
        for p, q in zip(pts, pts[1:]):
            for bx in range(int(min(p[0], q[0]) // B) - 1, int(max(p[0], q[0]) // B) + 2):
                for by in range(int(min(p[1], q[1]) // B) - 1, int(max(p[1], q[1]) // B) + 2):
                    name_bucket.setdefault((bx, by), []).append((name, p, q))

    def seg_dist(pt, p, q):
        (px, py), (ax, ay), (bx, by) = pt, p, q
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if not L2 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        return math.hypot(px - ax - t * dx, py - ay - t * dy)

    def nearest_name(pt):
        best, best_d = None, RIVER_NAME_KM
        for name, p, q in name_bucket.get((int(pt[0] // B), int(pt[1] // B)), ()):
            d = seg_dist(pt, p, q)
            if d < best_d:
                best, best_d = name, d
        return best

    rivers = []
    for chain in river_chains(hydro["reaches"]):
        reaches = [r for r in chain if not r.get("join")]
        if reaches[-1]["upland_km2"] < RIVER_MIN_UPLAND_KM2:
            continue
        # Name each reach by the Natural Earth river nearest to most of its points, fill short gaps, then split the
        # main stem where the name changes (the lower Odra carries the Warta's water but is the Odra).
        names = []
        for r in reaches:
            votes = Counter(nearest_name(to_map(lon, lat)) for lon, lat in r["line"])
            votes.pop(None, None)
            top = votes.most_common(1)
            names.append(top[0][0] if top and top[0][1] * 2 >= len(r["line"]) else None)
        for k in range(1, len(names) - 1):
            if names[k] is None and names[k - 1] and names[k - 1] == next((n for n in names[k + 1:] if n), None):
                names[k] = names[k - 1]
        runs: list[list[int]] = []
        for k, nm in enumerate(names):
            if runs and (names[runs[-1][0]] == nm or nm is None or names[runs[-1][0]] is None and
                         sum(len(reaches[j]["line"]) for j in runs[-1]) < 4):
                if names[runs[-1][0]] is None and nm is not None:
                    names[runs[-1][0]] = nm
                runs[-1].append(k)
            else:
                runs.append([k])
        # A run shorter than a few km (a reach at a confluence that votes for the tributary) joins its upstream run.
        def run_km(run):
            pts = [to_map(lon, lat) for k in run for lon, lat in reaches[k]["line"]]
            return sum(math.dist(u, v) for u, v in zip(pts, pts[1:]))

        merged: list[list[int]] = []
        for run in runs:
            if merged and run_km(run) < 4.0:
                merged[-1] += run
            else:
                merged.append(run)
        if len(merged) > 1 and run_km(merged[0]) < 4.0:
            merged[1] = merged[0] + merged[1]
            names[merged[1][0]] = names[merged[1][len(merged[0])]]
            merged.pop(0)
        runs = merged
        tail = chain[len(reaches):]  # the junction point with the river it flows into
        for ri, run in enumerate(runs):
            pts_dis = []
            for k in run:
                for lon, lat in reaches[k]["line"]:
                    pts_dis.append((to_map(lon, lat), reaches[k]["dis_m3s"] or 0.0))
            if ri + 1 < len(runs):
                nxt = reaches[runs[ri + 1][0]]
                pts_dis.append((to_map(*nxt["line"][0]), nxt["dis_m3s"] or 0.0))
            else:
                pts_dis += [(to_map(lon, lat), pts_dis[-1][1]) for r in tail for lon, lat in r["line"]]
            line = [pts_dis[0]] + [q for p_, q in zip(pts_dis, pts_dis[1:]) if math.dist(p_[0], q[0]) > 1e-6]
            name = names[run[0]]
            for piece in clip_polyline([p_ for p_, _ in line], width, height):
                if sum(math.dist(u, v) for u, v in zip(piece, piece[1:])) < 2.0:
                    continue
                d0 = min(line, key=lambda q: math.dist(q[0], piece[0]))[1]
                d1 = min(line, key=lambda q: math.dist(q[0], piece[-1]))[1]
                pts = douglas_peucker(piece, 0.15)
                if len(pts) >= 2:
                    rivers.append({"name": name, "rank": river_rank(d1), "upland_km2": round(reaches[run[-1]]["upland_km2"]),
                                   "dis0_m3s": round(d0, 1), "dis_m3s": round(d1, 1),
                                   "pts": [round(v, 1) for p_ in pts for v in p_]})
    rivers.sort(key=lambda r: r["rank"])
    named = Counter(r["name"] for r in rivers if r["name"])
    print(f"    {len(rivers)} river lines ({len(named)} named): {', '.join(sorted(named))[:300]}")

    # --- lakes and spits (outlines from WorldCover pixels) ---------------------------------------------------------
    def px_to_map(r, c):
        return to_map(wc_lon0 + c * wc_step, wc_top - r * wc_step)

    px_km2 = (wc_step * 111.2) * (wc_step * 111.2 * math.cos(math.radians(52)))

    def outline(comp, min_km2):
        out = []
        for ring in trace_rings(comp):
            pts = [px_to_map(r, c) for r, c in ring]
            pts = chaikin_closed(douglas_peucker(pts + pts[:1], 0.05)[:-1], 2)
            pts = douglas_peucker(pts + pts[:1], 0.09)[:-1]
            if len(pts) >= 3 and abs(ring_area(pts)) >= min_km2 * 0.25:
                out.append([round(v, 1) for p in pts for v in p])
        return out

    # Lakes: inland water (not touching the sea's no-data pixels) of at least LAKE_MIN_KM2.
    water_px = {(r, c) for r, row in enumerate(wc_rows) for c, ch in enumerate(row) if ch == "w"}
    sea_ch = "."
    lakes = []
    lake_names = [(l["name"], shape(l["rings"])) for l in ne["lakes"] if l.get("name")]
    for comp in components(water_px):
        if len(comp) * px_km2 < LAKE_MIN_KM2:
            continue
        touches_sea = any(
            not (0 <= rr < wc_n and 0 <= cc < wc_cols) or wc_rows[rr][cc] == sea_ch
            for r, c in comp for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
        )
        if touches_sea:
            continue
        # Lagoons (the Vistula Lagoon, whose strait is narrower than a pixel) lie in sea hexes: not lakes.
        step = max(1, len(comp) // 200)
        probe = sorted(comp)[::step]
        in_sea = sum(1 for r, c in probe if water[grid.cell_at(*px_to_map(r + 0.5, c + 0.5))] in (OCEAN, COAST))
        if in_sea > 0.3 * len(probe):
            continue
        rs = [r for r, _ in comp]
        cs = [c for _, c in comp]
        # Rivers wide enough to show as water pixels form long thin components: keep compact water bodies only.
        span_km = math.dist(px_to_map(min(rs), min(cs)), px_to_map(max(rs) + 1, max(cs) + 1))
        area = len(comp) * px_km2
        if area / (span_km * span_km) < 0.012 and area < 25:
            continue
        r0, c0 = sorted(comp)[len(comp) // 2]
        cx, cy = px_to_map(r0 + 0.5, c0 + 0.5)
        if area < FOREIGN_LAKE_MIN_KM2 and locate_gmina(cx, cy) < 0 and not any(
                locate_gmina(*px_to_map(r + 0.5, c + 0.5)) >= 0 for r, c in probe[:: max(1, len(probe) // 12)]):
            continue
        rings = outline(comp, LAKE_MIN_KM2)
        if not rings:
            continue
        name = next((nm for nm, sh in lake_names if sh.contains(cx, cy)), None)
        lakes.append({"name": name, "area_km2": round(area, 1), "rings": rings})
    lakes.sort(key=lambda l: -l["area_km2"])
    print(f"    {len(lakes)} lakes of {LAKE_MIN_KM2:g} km2 or more; largest: "
          + ", ".join(f"{l['name'] or '?'} {l['area_km2']}" for l in lakes[:8]))

    # Spits: land narrower than a hex inside sea hexes (the Hel Peninsula, the Vistula Spit, the Curonian Spit),
    # from the gmina and country outlines rasterised at SPIT_RES_KM.
    near_sea = set()
    for i in range(grid.size):
        if water[i] in (OCEAN, COAST):
            ring1 = grid.neighbours(i)
            if any(water[j] == LAND for j in ring1) or any(water[k] == LAND for j in ring1 for k in grid.neighbours(j)):
                near_sea.add(i)
    land_shapes = gmina_shapes + foreign_shapes
    spit_px = rasterise_in_cells(land_shapes, near_sea, grid, SPIT_RES_KM)
    spits = []
    px_area = SPIT_RES_KM * SPIT_RES_KM
    for comp in components(spit_px):
        area = len(comp) * px_area
        if area < SPIT_MIN_KM2:
            continue
        rings = []
        for ring in trace_rings(comp):
            pts = [(c * SPIT_RES_KM, r * SPIT_RES_KM) for r, c in ring]
            pts = chaikin_closed(douglas_peucker(pts + pts[:1], 0.03)[:-1], 2)
            pts = douglas_peucker(pts + pts[:1], 0.04)[:-1]
            if len(pts) >= 3 and abs(ring_area(pts)) >= 0.05:
                rings.append([round(v, 2) for p in pts for v in p])
        if rings:
            inside = sum(locate_gmina((c + 0.5) * SPIT_RES_KM, (r + 0.5) * SPIT_RES_KM) >= 0
                         for r, c in list(comp)[:: max(1, len(comp) // 25)])
            spit = {"area_km2": round(area, 1), "rings": rings}
            if inside * 2 < min(25, len(comp)):
                spit["foreign"] = True
            spits.append(spit)
    spits.sort(key=lambda s: -s["area_km2"])
    print(f"    {len(spits)} spits and islands in sea hexes ({sum(s['area_km2'] for s in spits):.0f} km2)")

    # --- output ---------------------------------------------------------------------------------------------------
    cover_table = [{"id": 0, "key": "none", "name": "None", "rule": "Water, or no WorldCover land points."}] + [
        {"id": cid, "key": key, "name": name, "color": color, "worldcover": codes, "rule": rule}
        for cid, key, name, color, codes, rule in COVER
    ]
    tables = {
        "water": WATER_TABLE,
        "relief": RELIEF_TABLE,
        "cover": cover_table,
        "notes": {"water": WATER_NOTE, "relief": RELIEF_NOTE, "cover": COVER_NOTE},
    }
    states_out = [{"fips": v["code"], "abbr": ABBR[v["code"]], "name": v["name"]} for v in voivs]
    counties_out = [{"geoid": g["code"], "name": g["name"], "powiat": g["code"][:4], "type": g["type"]} for g in gminy]
    projection = {**proj.to_dict(), **PL_ALBERS}
    write_web(
        "world.json",
        {
            "version": 2,
            "grid": grid.to_dict(),
            "width": round(width, 1),
            "height": round(height, 1),
            "margin": MARGIN_KM,
            "projection": projection,
            "owner": owner,
            "county": county,
            "elev": elev,
            "elev_max": elev_max,
            "water": water,
            "relief": relief,
            "cover": cover,
            "pct": pct,
            "tables": tables,
            "states": states_out,
            "counties": counties_out,
            "rivers": rivers,
            "lakes": lakes,
            "spits": spits,
        },
    )
    powiat_of = [pow_idx.get(g["code"][:4], -1) for g in gminy]
    save_interim(
        "_world",
        {
            "grid": grid.to_dict(),
            "projection": projection,
            "owner": owner,
            "county": county,
            "county_samples": county_samples,
            "powiat": [powiat_of[c] if c >= 0 else -1 for c in county],
            "states": [v["code"] for v in voivs],
            "counties": [g["code"] for g in gminy],
            "powiaty": [p["code"] for p in powiaty],
            "water": water,
            "cover": cover,
            "pct": pct,
            "notes": notes,
            "gminy_without_samples": unsampled,
        },
    )


def check(web_dir) -> list[tuple[str, str]]:
    """Data-quality lines for world.json (pipeline check)."""
    import json

    path = web_dir / "world.json"
    if not path.exists():
        return [("NOTE", "world.json not built")]
    w = json.loads(path.read_text())
    out = []
    owner, county, water = w.get("owner") or [], w.get("county") or [], w.get("water") or []
    land = sum(1 for o in owner if o >= 0)
    out.append(("PASS" if land else "NOTE", f"{land} Polish land hexes of {len(owner)}"))
    gm = w.get("counties") or []
    with_hex = len({c for c in county if c >= 0})
    out.append(("NOTE", f"{with_hex} of {len(gm)} gminy are the gmina of at least one hex (small towns share a hex "
                        "with a larger neighbour; lenses use the 7 samples per hex)"))
    st = w.get("states") or []
    no_cells = [s.get("name") for k, s in enumerate(st) if not any(o == k for o in owner)]
    out.append(("NOTE" if no_cells else "PASS", f"{len(st)} voivodeships" + (f"; without hexes: {no_cells}" if no_cells else ", all own hexes")))
    for key in ("lakes", "spits"):
        items = w.get(key)
        if items is None:
            out.append(("NOTE", f"world.json has no {key}"))
            continue
        bad = [k for k, it in enumerate(items) if not isinstance(it, dict) or not isinstance(it.get("rings"), list)
               or not all(isinstance(r, list) and len(r) >= 6 and len(r) % 2 == 0 for r in it["rings"])]
        out.append(("FAIL" if bad else "PASS", f"{len(items)} {key}" + (f", {len(bad)} malformed" if bad else "")))
    named = sorted({r["name"] for r in w.get("rivers") or [] if r.get("name")})
    out.append(("NOTE", f"{len(w.get('rivers') or [])} river lines, {len(named)} named"))
    return out


# Two-letter voivodeship abbreviations: the ISO 3166-2:PL letter codes used until 2018 (the standard now uses the
# TERYT numbers, PL-02 ... PL-32). Source: https://en.wikipedia.org/wiki/ISO_3166-2:PL (change history).
ABBR = {
    "02": "DS", "04": "KP", "06": "LU", "08": "LB", "10": "LD", "12": "MA", "14": "MZ", "16": "OP",
    "18": "PK", "20": "PD", "22": "PM", "24": "SL", "26": "SK", "28": "WN", "30": "WP", "32": "ZP",
}

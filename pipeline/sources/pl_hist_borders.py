"""Historic borders over today's Poland: the 1914 partition borders and the interwar border of Poland (CShapes 2.0).

CShapes 2.0 (Schvitz, Rueegger, Girardin, Cederman, Weidmann and Gleditsch 2022, Journal of Conflict Resolution
66(1); ETH Zurich ICR) gives the
borders of every independent state from 1886 to 2019 with the dates each shape was valid. This source keeps:

* 1 July 1914: the borders between the German Empire, the Russian Empire and Austria-Hungary (the borders of
  the partitions);
* 1 January 1930: the border of interwar Poland (valid from 18 March 1921, the Treaty of Riga, to 1939) with
  Germany, the Free City of Danzig, Lithuania, Latvia, the Soviet Union, Romania and Czechoslovakia.

A border is the part of a state's outline that lies within TOL_KM of the neighbour's outline (so coasts are left
out). Lines are clipped to a box around the map and simplified; coordinates are lon/lat (WGS84).
"""

from __future__ import annotations

import json
import math

from ..core.source import Source, SourceInfo

URL = "https://icr.ethz.ch/data/cshapes/CShapes-2.0.geojson"
FILE = "CShapes-2.0.geojson"
HOMEPAGE = "https://icr.ethz.ch/data/cshapes/"
BOX = (12.0, 47.5, 27.0, 56.5)  # lon0, lat0, lon1, lat1 around the map
TOL_KM = 2.5
SIMPLIFY_KM = 0.4

# (layer id, date, label, [(state A, state B)], names for the labels {CShapes name: English label})
LAYERS = [
    ("borders_1914", (1914, 7, 1), "Borders of 1914",
     [("Germany (Prussia)", "Russia (Soviet Union)"), ("Germany (Prussia)", "Austria-Hungary"),
      ("Russia (Soviet Union)", "Austria-Hungary")],
     {"Germany (Prussia)": "German Empire", "Russia (Soviet Union)": "Russian Empire",
      "Austria-Hungary": "Austria-Hungary"}),
    ("borders_1930", (1930, 1, 1), "Interwar Poland (1921-1939)",
     [("Poland", "Germany (Prussia)"), ("Poland", "Danzig"), ("Poland", "Lithuania"), ("Poland", "Latvia"),
      ("Poland", "Russia (Soviet Union)"), ("Poland", "Rumania"), ("Poland", "Czechoslovakia")],
     {"Poland": "Poland"}),
]


def valid_on(props: dict, date: tuple[int, int, int]) -> bool:
    start = (props["gwsyear"], props["gwsmonth"], props["gwsday"])
    end = (props["gweyear"], props["gwemonth"], props["gweday"])
    return start <= date <= end


def rings(geom: dict) -> list[list[list[float]]]:
    if geom["type"] == "Polygon":
        return list(geom["coordinates"])
    if geom["type"] == "MultiPolygon":
        return [r for poly in geom["coordinates"] for r in poly]
    return []


def _km(lon0: float, lat0: float, lon1: float, lat1: float) -> float:
    k = math.cos(math.radians((lat0 + lat1) / 2))
    return math.hypot((lon1 - lon0) * 111.32 * k, (lat1 - lat0) * 110.57)


def _seg_dist_km(p, a, b) -> float:
    """Distance from point p to segment a-b (lon/lat pairs), in km on a local flat projection."""
    k = math.cos(math.radians(p[1]))
    ax, ay = (a[0] - p[0]) * 111.32 * k, (a[1] - p[1]) * 110.57
    bx, by = (b[0] - p[0]) * 111.32 * k, (b[1] - p[1]) * 110.57
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L))
    return math.hypot(ax + t * dx, ay + t * dy)


class SegmentIndex:
    """Segments of some rings in a 0.1 degree grid, for 'is there a segment within d km of this point?'."""

    STEP = 0.1

    def __init__(self, ring_list):
        self.grid: dict[tuple[int, int], list] = {}
        for ring in ring_list:
            for a, b in zip(ring, ring[1:]):
                for cell in self._cells(a, b):
                    self.grid.setdefault(cell, []).append((a, b))

    def _cells(self, a, b):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        s = self.STEP
        return {(i, j) for i in range(int(math.floor(x0 / s)), int(math.floor(x1 / s)) + 1)
                for j in range(int(math.floor(y0 / s)), int(math.floor(y1 / s)) + 1)}

    def near(self, p, d_km: float) -> bool:
        s = self.STEP
        ci, cj = int(math.floor(p[0] / s)), int(math.floor(p[1] / s))
        for i in range(ci - 1, ci + 2):
            for j in range(cj - 1, cj + 2):
                for a, b in self.grid.get((i, j), ()):
                    if _seg_dist_km(p, a, b) <= d_km:
                        return True
        return False


def in_box(p, box=BOX) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def shared_lines(rings_a, rings_b, tol_km: float = TOL_KM, box=BOX) -> list[list[list[float]]]:
    """Polylines of A's outline that run within tol_km of B's outline, inside the box."""
    index = SegmentIndex([r for r in rings_b if any(in_box(p, box) for p in r)])
    out: list[list[list[float]]] = []
    for ring in rings_a:
        if not any(in_box(p, box) for p in ring):
            continue
        cur: list[list[float]] = []
        for a, b in zip(ring, ring[1:]):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            keep = in_box(mid, box) and index.near(mid, tol_km)
            if keep:
                if not cur:
                    cur = [list(a)]
                cur.append(list(b))
            elif cur:
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
    # Join pieces that touch (a ring starts mid-border).
    joined: list[list[list[float]]] = []
    for line in out:
        if joined and joined[-1][-1] == line[0]:
            joined[-1].extend(line[1:])
        else:
            joined.append(line)
    return [simplify(l, SIMPLIFY_KM) for l in joined if len(l) >= 2 and length_km(l) >= 3]


def length_km(line) -> float:
    return sum(_km(*a, *b) for a, b in zip(line, line[1:]))


def simplify(line, tol_km: float) -> list[list[float]]:
    """Douglas-Peucker in km; coordinates rounded to 5 decimals (about 1 m)."""
    if len(line) <= 2:
        return [[round(x, 5), round(y, 5)] for x, y in line]
    keep = [False] * len(line)
    keep[0] = keep[-1] = True
    stack = [(0, len(line) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, None
        for k in range(i + 1, j):
            d = _seg_dist_km(line[k], line[i], line[j])
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol_km:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [[round(p[0], 5), round(p[1], 5)] for p, k in zip(line, keep) if k]


def build_layers(features: list[dict]) -> list[dict]:
    layers = []
    for lid, date, label, pairs, names in LAYERS:
        shapes: dict[str, list] = {}
        for f in features:
            p = f["properties"]
            if valid_on(p, date):
                shapes.setdefault(p["cntry_name"], []).extend(rings(f["geometry"]))
        lines = []
        for a, b in pairs:
            if a not in shapes or b not in shapes:
                raise RuntimeError(f"CShapes: no shape for {a if a not in shapes else b} on {date}")
            for pts in shared_lines(shapes[a], shapes[b]):
                lines.append({"between": [a, b], "pts": pts})
        areas = {names[n]: [r for r in shapes[n] if any(in_box(p) for p in r)] for n in names}
        layers.append({"id": lid, "date": "%04d-%02d-%02d" % date, "label": label, "lines": lines,
                       "areas": [{"name": k, "rings": [[[round(x, 4), round(y, 4)] for x, y in r] for r in v]}
                                 for k, v in areas.items()]})
    return layers


class HistoricBorders(Source):
    info = SourceInfo(
        id="pl_hist_borders",
        title="CShapes 2.0: historical state borders",
        publisher="ETH Zurich, International Conflict Research (Schvitz et al. 2022)",
        homepage=HOMEPAGE,
        license="CC BY-NC-SA 4.0: non-commercial use, which this free, ad-free site is; the derived borders are shared under the same licence",
        description="Borders of independent states 1886-2019 with their dates of validity. Used for the borders "
                    "of the partitions on 1 July 1914 and the border of interwar Poland (1921-1939).",
        used_for=["Borders of 1914 map layer", "Interwar border map layer"],
    )

    def fetch(self, force: bool = False) -> None:
        self.download(URL, FILE, force=force, expect_binary=True)

    def process(self) -> dict:
        doc = json.loads((self.raw_dir / FILE).read_text(encoding="utf-8"))
        layers = build_layers(doc["features"])
        return {
            "vintage": "CShapes 2.0 (2022); borders on 1914-07-01 and 1930-01-01",
            "layers": layers,
            "notes": [
                "Lines are the parts of one state's outline within 2.5 km of the neighbour's outline, clipped to "
                "lon 12-27, lat 47.5-56.5 and simplified to 0.4 km.",
                "1914: German Empire, Russian Empire and Austria-Hungary on 1 July 1914 (CShapes 'Germany "
                "(Prussia)', 'Russia (Soviet Union)', 'Austria-Hungary').",
                "Interwar: Poland on 1 January 1930 (CShapes shape valid 18 March 1921 to 1945); the 1938 and 1939 "
                "changes are not shown.",
                "Data licence CC BY-NC-SA 4.0: derived lines are shared under the same licence, with attribution.",
            ],
            "_files": [FILE],
        }

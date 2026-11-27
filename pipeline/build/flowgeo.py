"""Geometry helpers for the motion-flow builders (power, migration, money). No build(): not a builder.

Paths are flat arrays [x0, y0, x1, y1, ...] in map km, rounded to 0.1 km and simplified (Douglas-Peucker 0.3 km),
as docs/DATA_CONTRACTS.md asks for motion layers.
"""

from __future__ import annotations

import math

from ..core.geo import MapProjection
from ..core.hexgrid import HexGrid
from .world import douglas_peucker

DP_KM = 0.3


def projection(world_interim: dict) -> MapProjection:
    return MapProjection(**{k: world_interim["projection"][k] for k in ("min_x", "max_y", "margin")})


def flat(points, tol: float = DP_KM) -> list[float]:
    """[(x, y), ...] -> simplified flat array rounded to 0.1 km."""
    pts = douglas_peucker([(float(x), float(y)) for x, y in points], tol) if tol else list(points)
    out: list[float] = []
    for x, y in pts:
        out += [round(x, 1), round(y, 1)]
    return out


def clip_to_rect(points, width: float, height: float) -> tuple[list, bool]:
    """Keep the line from its first point until it leaves [0, width] x [0, height]; end it on the edge.

    Returns (points, clipped). The first point must be inside the map.
    """
    def inside(p):
        return 0 <= p[0] <= width and 0 <= p[1] <= height

    out = [points[0]]
    for a, b in zip(points, points[1:]):
        if inside(b):
            out.append(b)
            continue
        # the segment a-b leaves the rectangle: find the exit point
        t_exit = 1.0
        for axis, lim in ((0, 0.0), (0, width), (1, 0.0), (1, height)):
            d = b[axis] - a[axis]
            if d:
                t = (lim - a[axis]) / d
                if 0 <= t <= t_exit:
                    other = a[1 - axis] + t * (b[1 - axis] - a[1 - axis])
                    if -1e-9 <= other <= (height if axis == 0 else width) + 1e-9:
                        t_exit = t
        out.append((a[0] + t_exit * (b[0] - a[0]), a[1] + t_exit * (b[1] - a[1])))
        return out, True
    return out, False


def arc(a, b, bend: float = 0.15, n: int = 16) -> list[tuple[float, float]]:
    """A quadratic Bezier from a to b, bowed to the left of the direction a->b by `bend` x length.

    The flow a->b and the flow b->a bow to opposite sides, so they do not overlap.
    """
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    cx, cy = (ax + bx) / 2 + dy * bend, (ay + by) / 2 - dx * bend
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append((u * u * ax + 2 * u * t * cx + t * t * bx, u * u * ay + 2 * u * t * cy + t * t * by))
    return pts


def bearing_deg(a, b) -> float:
    """Compass bearing on the map (0 = up/north, 90 = right/east) from a to b; y points down."""
    return round(math.degrees(math.atan2(b[0] - a[0], a[1] - b[1])) % 360, 1)


def unit_centres(world: dict) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    """Centres (mean of hex centres) of every gmina (TERYT7) and powiat (TERYT4) in the _world interim."""
    grid = HexGrid(**world["grid"])
    g_acc: dict[int, list] = {}
    p_acc: dict[int, list] = {}
    for cell, smp in enumerate(world["county_samples"]):
        if not smp:
            continue
        x, y = grid.center(*grid.col_row(cell))
        for k in set(k for k in smp if k >= 0):
            a = g_acc.setdefault(k, [0.0, 0.0, 0])
            a[0] += x
            a[1] += y
            a[2] += 1
        p = world["powiat"][cell]
        if p >= 0:
            a = p_acc.setdefault(p, [0.0, 0.0, 0])
            a[0] += x
            a[1] += y
            a[2] += 1
    gminas = {world["counties"][k]: (a[0] / a[2], a[1] / a[2]) for k, a in g_acc.items()}
    powiaty = {world["powiaty"][k]: (a[0] / a[2], a[1] / a[2]) for k, a in p_acc.items()}
    return gminas, powiaty

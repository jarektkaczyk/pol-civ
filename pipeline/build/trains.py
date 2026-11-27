"""A day of Polish passenger trains for the Trains motion layer (lazy web/data/trains.json).

Shape of the file (see docs/DATA_CONTRACTS.md "trains.json"):

* `shapes`: route lines as flat arrays [x0, y0, x1, y1, ...] in map km (0.1 km, Douglas-Peucker 0.3 km),
  identical lines stored once;
* `patterns`: a shape plus the stations a train calls at and each station's distance along the line (km,
  measured on the stored polyline, so the browser can place a train by its own cumulative lengths);
* `trips`: operator, category, number, name, pattern and times. `t` is
  [departure from the first stop, then per next stop: running seconds, dwell seconds], counted in seconds
  from 00:00 of `day` (negative for a night train that left the evening before, above 86,400 for one that
  arrives the next morning).
"""

from __future__ import annotations

import datetime as dt
import json
import math
from bisect import bisect_left
from collections import Counter
from pathlib import Path

from ..core.fetch import read_manifest
from ..core.geo import MapProjection
from ..core.store import load_interim, load_interim_payload, write_web
from ..sources.pl_rail_gtfs import simplify_idx

REQUIRES = ["_world", "pl_rail_gtfs"]
PRODUCES = ["trains.json"]

SIMPLIFY_KM = 0.3
MAX_BYTES = 4_000_000

# Operator order: long distance first, then regional operators by size (the browser colours by index).
LONG_DISTANCE = {"IC", "LEO", "RJ"}

RULES = [
    "One ordinary Wednesday: the Wednesday in the published 30-day timetable with the most trains, outside "
    "public holidays and the Christmas and New Year period.",
    "Every passenger train of every operator on the PKP PLK network that runs that day is shown; replacement "
    "buses are left out.",
    "Night trains that leave the evening before are shown until they arrive that morning.",
    "Between two stops a train moves along its route line at a steady speed and waits at each station for its "
    "timetabled stop.",
]


def _proj(world: dict) -> MapProjection:
    cfg = world["projection"]
    return MapProjection(min_x=cfg["min_x"], max_y=cfg["max_y"], margin=cfg["margin"])


def r1(v: float) -> float:
    return round(v, 1) + 0.0  # + 0.0 turns -0.0 into 0.0


def project_shape(proj, pts: list[list]) -> tuple[list[float], list[float], list[float]]:
    """Interim shape [[lon, lat, gtfs_km], ...] -> (flat map-km polyline, gtfs km at each kept vertex,
    cumulative length at each kept vertex measured on the rounded polyline)."""
    xy = [proj(p[0], p[1]) for p in pts]
    gk = [p[2] for p in pts]
    if any(v is None for v in gk):  # no GTFS distances: use the length of the projected line
        gk, acc = [0.0], 0.0
        for a, b in zip(xy, xy[1:]):
            acc += math.dist(a, b)
            gk.append(acc)
    keep = simplify_idx(xy, SIMPLIFY_KM)
    flat, gkm, cum, acc, last = [], [], [], 0.0, None
    for k in keep:
        x, y = r1(xy[k][0]), r1(xy[k][1])
        if last is not None:
            if (x, y) == last:
                continue
            acc += math.dist(last, (x, y))
        flat += [x, y]
        gkm.append(gk[k])
        cum.append(acc)
        last = (x, y)
    if len(cum) == 1:  # a degenerate line: keep two points so the browser has a segment
        flat += flat[:2]
        gkm.append(gkm[0])
        cum.append(0.0)
    return flat, gkm, cum


def map_dist(d: float | None, gkm: list[float], cum: list[float]) -> float:
    """GTFS distance along the original line -> distance along the stored polyline (linear between vertices)."""
    if d is None or not gkm:
        return 0.0
    if d <= gkm[0]:
        return cum[0]
    if d >= gkm[-1]:
        return cum[-1]
    i = bisect_left(gkm, d)
    a, b = gkm[i - 1], gkm[i]
    f = 0.0 if b == a else (d - a) / (b - a)
    return cum[i - 1] + f * (cum[i] - cum[i - 1])


def nearest_dist(px: float, py: float, flat: list[float], cum: list[float], lo: float) -> float:
    """Distance along the polyline of the point nearest to (px, py), not before `lo` (stops without GTFS km)."""
    best, best_d = None, lo
    for i in range(len(cum) - 1):
        if cum[i + 1] < lo:
            continue
        ax, ay, bx, by = flat[2 * i], flat[2 * i + 1], flat[2 * i + 2], flat[2 * i + 3]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        f = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        e = math.hypot(ax + f * dx - px, ay + f * dy - py)
        if best is None or e < best:
            best, best_d = e, max(lo, cum[i] + f * (cum[i + 1] - cum[i]))
    return best_d


def encode_times(arr: list[int], dep: list[int]) -> list[int]:
    """[dep0, run1, dwell1, run2, dwell2, ...]; run_i = arr_i - dep_(i-1), dwell_i = dep_i - arr_i."""
    out = [dep[0]]
    for i in range(1, len(arr)):
        out += [arr[i] - dep[i - 1], dep[i] - arr[i]]
    return out


def decode_times(t: list[int]) -> tuple[list[int], list[int]]:
    """Inverse of encode_times (the first stop's arrival equals its departure)."""
    arr, dep = [t[0]], [t[0]]
    for i in range(1, len(t), 2):
        arr.append(dep[-1] + t[i])
        dep.append(arr[-1] + t[i + 1])
    return arr, dep


PROCESSED = ("Converted from the GTFS feed for this map: one day kept, stations and route lines projected and "
             "simplified, train positions between stops interpolated.")


def _utc(text: str | None) -> str | None:
    """ISO time with an offset -> 'YYYY-MM-DDTHH:MMZ' (UTC); None stays None."""
    if not text:
        return None
    stamp = dt.datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def original_feed() -> dict | None:
    """The exact file we processed (Koleje Mazowieckie's terms: the information stays available in its original form):
    its public URL, size, retrieval time and SHA-256, from the download manifest."""
    from pipeline.core.paths import RAW
    try:
        entry = json.loads((RAW / "pl_rail_gtfs" / "manifest.json").read_text(encoding="utf-8")).get("polish_trains.zip")
    except (OSError, ValueError):
        return None
    if not entry:
        return None
    return {"url": entry.get("url"), "bytes": entry.get("bytes"), "sha256": entry.get("sha256"),
            "retrieved": _utc(entry.get("retrieved"))}


def attribution(data: dict) -> dict:
    """What the PKP PLK and Koleje Mazowieckie re-use terms ask for: the source, when the data was made and
    obtained, and that it was processed. `credit` names are proper names (not translated)."""
    return {
        "credit": ["PKP Polskie Linie Kolejowe S.A.", "Koleje Mazowieckie - KM sp. z o.o.",
                   "Mikołaj Kuranowski (GTFS, mkuran.pl/gtfs)"],
        "created": _utc(data["feed"].get("version")),
        "retrieved": _utc(data.get("retrieved")),
        "processed": PROCESSED,
        "feed": data["feed"].get("attributions") or [],
        "original": original_feed(),
    }


def build_doc(data: dict, proj, vintage: str | None) -> dict:
    stations_pts = [p for p in data["points"] if p.get("lon") is not None and p.get("lat") is not None]
    st_index, stations = {}, []
    for p in sorted(stations_pts, key=lambda p: p["name"]):
        x, y = proj(p["lon"], p["lat"])
        st_index[p["props"]["stop_id"]] = len(stations)
        stations.append({"name": p["name"], "x": r1(x), "y": r1(y)})

    counts = Counter(t["agency"] for t in data["trips"])
    op_ids = sorted(counts, key=lambda a: (a not in LONG_DISTANCE, -counts[a], a))
    op_index = {a: i for i, a in enumerate(op_ids)}
    operators = [{"id": a, "name": data["agencies"].get(a, {}).get("name") or a,
                  "long_distance": a in LONG_DISTANCE, "trips": counts[a]} for a in op_ids]

    shapes, shape_key, shape_cache = [], {}, {}
    patterns, pattern_key = [], {}
    trips, dropped = [], Counter()
    for t in sorted(data["trips"], key=lambda t: (t["dep"][0], t["id"])):
        if any(s not in st_index for s in t["stops"]):
            dropped["station without coordinates"] += 1
            continue
        sid = t.get("shape")
        if sid and sid in data["shapes"]:
            if sid not in shape_cache:
                shape_cache[sid] = project_shape(proj, data["shapes"][sid])
            flat, gkm, cum = shape_cache[sid]
            dists, lo = [], 0.0
            for k, d in enumerate(t["dist"]):
                if d is None:
                    s = stations[st_index[t["stops"][k]]]
                    v = nearest_dist(s["x"], s["y"], flat, cum, lo)
                else:
                    v = max(lo, map_dist(d, gkm, cum))
                dists.append(v)
                lo = v
        else:  # no route line: straight segments between the stations
            dropped["no shape (straight lines between stations)"] += 1
            pts = [stations[st_index[s]] for s in t["stops"]]
            flat, cum, acc = [], [], 0.0
            for k, s in enumerate(pts):
                if k:
                    acc += math.dist((pts[k - 1]["x"], pts[k - 1]["y"]), (s["x"], s["y"]))
                flat += [s["x"], s["y"]]
                cum.append(acc)
            dists = list(cum)
        key = tuple(flat)
        if key not in shape_key:
            shape_key[key] = len(shapes)
            shapes.append(flat)
        sh = shape_key[key]
        stops = [st_index[s] for s in t["stops"]]
        dkm = [round(v, 1) for v in dists]
        tech = [k for k, v in enumerate(t.get("no_pax") or []) if v]
        pkey = (sh, tuple(stops), tuple(dkm), tuple(tech))
        if pkey not in pattern_key:
            pattern_key[pkey] = len(patterns)
            pat = {"shape": sh, "stops": stops, "d": dkm}
            if tech:
                pat["tech"] = tech
            patterns.append(pat)
        trips.append({
            "op": op_index[t["agency"]], "cat": t.get("category"), "no": t.get("number"), "name": t.get("name"),
            "p": pattern_key[pkey], "t": encode_times(t["arr"], t["dep"]),
        })

    starts = [tr["t"][0] for tr in trips]
    return {
        "version": 1,
        "vintage": vintage,
        "sources": ["pl_rail_gtfs"],
        "day": data["day"],
        "unit": "s",
        "period": data["day"],
        "rules": RULES,
        "attribution": attribution(data),
        "operators": operators,
        "stations": stations,
        "shapes": shapes,
        "patterns": patterns,
        "trips": trips,
        "range": [min(starts), max(decode_times(tr["t"])[0][-1] for tr in trips)] if trips else [0, 86400],
        "dropped": dict(dropped),
    }


def build() -> None:
    world = load_interim("_world")
    payload = load_interim_payload("pl_rail_gtfs")
    data = dict(payload["data"])
    data["retrieved"] = (read_manifest("pl_rail_gtfs").get("polish_trains.zip") or {}).get("retrieved")
    doc = build_doc(data, _proj(world), payload.get("vintage"))
    write_web("trains.json", doc)


def check(web_dir) -> list[tuple[str, str]]:
    path = Path(web_dir) / "trains.json"
    if not path.exists():
        return [("NOTE", "trains.json not built (optional)")]
    doc = json.loads(path.read_text())
    world_path = Path(web_dir) / "world.json"
    world = json.loads(world_path.read_text()) if world_path.exists() else {}
    w, h = world.get("width"), world.get("height")
    problems = []
    for key in ("version", "vintage", "sources", "rules", "day", "operators", "stations", "shapes", "patterns", "trips"):
        if key not in doc:
            problems.append(f"missing key {key}")
    ns, nsh, npat, nop = (len(doc.get(k) or []) for k in ("stations", "shapes", "patterns", "operators"))
    for i, sh in enumerate(doc.get("shapes") or []):
        if len(sh) < 4 or len(sh) % 2:
            problems.append(f"shape {i}: odd or too short")
    for i, p in enumerate(doc.get("patterns") or []):
        if not 0 <= p.get("shape", -1) < nsh:
            problems.append(f"pattern {i}: bad shape index")
        if len(p.get("stops") or []) != len(p.get("d") or []) or len(p.get("stops") or []) < 2:
            problems.append(f"pattern {i}: stops and distances differ in length")
        if any(not 0 <= s < ns for s in p.get("stops") or []):
            problems.append(f"pattern {i}: bad station index")
        d = p.get("d") or []
        if any(b < a for a, b in zip(d, d[1:])):
            problems.append(f"pattern {i}: distances go backwards")
    pats = doc.get("patterns") or []
    for i, tr in enumerate(doc.get("trips") or []):
        if not 0 <= tr.get("p", -1) < npat or not 0 <= tr.get("op", -1) < nop:
            problems.append(f"trip {i}: bad pattern or operator index")
            continue
        t = tr.get("t") or []
        if len(t) != 2 * len(pats[tr["p"]]["stops"]) - 1:
            problems.append(f"trip {i} ({tr.get('no')}): {len(t)} times for {len(pats[tr['p']]['stops'])} stops")
        if any(v < 0 for v in t[1:]):
            problems.append(f"trip {i} ({tr.get('no')}): time goes backwards")
    abroad = 0
    for s in doc.get("stations") or []:
        if not all(isinstance(s.get(k), (int, float)) for k in ("x", "y")):
            problems.append(f"station {s.get('name')!r}: x or y is not a number")
        elif w and h:
            if not (-600 <= s["x"] <= w + 600 and -600 <= s["y"] <= h + 600):
                problems.append(f"station {s.get('name')!r} lies more than 600 km beyond the map")
            elif not (0 <= s["x"] <= w and 0 <= s["y"] <= h):
                abroad += 1
    out = [("FAIL", f"trains.json: {p}") for p in problems[:12]]
    if abroad:
        out.append(("NOTE", f"trains.json: {abroad} stations of international trains lie beyond the map edge"))
    if not problems:
        out.append(("PASS", f"trains.json: {len(doc['trips'])} trips on {doc['day']}, {npat} stop patterns, "
                            f"{nsh} lines, {ns} stations, {nop} operators"))
    size = path.stat().st_size
    out.append(("PASS" if size < MAX_BYTES else "WARN", f"trains.json {size / 1e6:.2f} MB (lazy, target < 4 MB)"))
    return out

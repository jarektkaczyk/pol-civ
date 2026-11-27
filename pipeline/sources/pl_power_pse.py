"""Power grid of Poland: generation by fuel and cross-border flows per 15 minutes (PSE), plus the interconnectors.

PSE S.A. (the transmission system operator) publishes its reports through an open JSON API at
https://api.raporty.pse.pl/api/<report> (no key, CORS "*"). Three reports are used, one request each for a whole
day (`$first=2000` returns every row in one page):

* `his-gen-pal`: generation per 15 minutes by ENTSO-E production type (`alias_entsoe` B01...B20, value in MW as
  text with a decimal comma). The type names are the ENTSO-E code list (PsrType).
* `his-wlk-cal`: "Raporty dobowe z funkcjonowania KSE - Wielkosci podstawowe": `wi` (wind), `pv` (solar),
  `demand` ("Zapotrzebowanie na moc"), `swm_p`/`swm_np` (cross-border balance, parallel and non-parallel), in MW.
* `przeplywy-mocy`: "Wymiana miedzysystemowa - przeplywy mocy", value in MW per section code. PSE's report page:
  "eksport oznacza eksport mocy z Polski (znak "-")", "import oznacza import mocy do Polski (znak "+")", and the
  values are physical flows on the trading sections, without the local exchange on 110 kV lines.

`dtime` is the end of each 15-minute period in Warsaw time; `period` ("00:00 - 00:15") gives its start. The
snapshot is the newest complete day (all quarters present and not null), normally yesterday.

The interconnectors (the lines that cross the border) come from OpenStreetMap: overhead lines and cables of 220 kV
and more in 1-degree tiles along the border with Germany, Czechia, Slovakia, Ukraine and Lithuania and along the
coast, plus two sea tiles for the SwePol HVDC cable to Sweden. find_crossings() says how a crossing is found
(Natural Earth 1:10m countries, interim `pl_geo_ne`). The OSM tiles change rarely, so `--force` re-fetches the PSE
day only.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from ..core.source import Source, SourceInfo
from ..core.store import load_interim
from .pl_transport_util import ODBL_NOTE, OverpassError, haversine_m, osm_timestamp, overpass, simplify

API = "https://api.raporty.pse.pl/api/"
REPORTS = ("his-gen-pal", "his-wlk-cal", "przeplywy-mocy")
REPORTS_PAGE = "https://raporty.pse.pl/"
CODELIST = "https://eepublicdownloads.entsoe.eu/clean-documents/EDI/Library/Core/entso-e-code-list-v36r0.pdf"

# ENTSO-E code list v36 (PsrType), quoted names. The report uses these codes.
PSR = {
    "B01": "Biomass", "B02": "Fossil Brown coal/Lignite", "B03": "Fossil Coal-derived gas", "B04": "Fossil Gas",
    "B05": "Fossil Hard coal", "B06": "Fossil Oil", "B07": "Fossil Oil shale", "B08": "Fossil Peat",
    "B09": "Geothermal", "B10": "Hydro Pumped Storage", "B11": "Hydro Run-of-river and pondage",
    "B12": "Hydro Water Reservoir", "B13": "Marine", "B14": "Nuclear", "B15": "Other renewable", "B16": "Solar",
    "B17": "Waste", "B18": "Wind Offshore", "B19": "Wind Onshore", "B20": "Other",
}

# Neighbours with a PSE trading section. Sweden is reached only by the SwePol HVDC cable under the Baltic.
NEIGHBOURS = {"DE": "Germany", "CZ": "Czechia", "SK": "Slovakia", "LT": "Lithuania", "UA": "Ukraine", "SE": "Sweden"}
NO_SECTION = {"Belarus": "BY", "Russia": "RU"}  # lines to these countries carry no PSE section

# 1-degree tiles (south, west) along the border with the five land neighbours and along the coast.
TILES = [(48, 22), (49, 17), (49, 18), (49, 19), (49, 20), (49, 21), (49, 22), (49, 23), (50, 14), (50, 15),
         (50, 16), (50, 17), (50, 18), (50, 23), (50, 24), (51, 14), (51, 15), (51, 23), (52, 14), (53, 14),
         (53, 23), (54, 14), (54, 15), (54, 16), (54, 17), (54, 18), (54, 19), (54, 22), (54, 23),
         (55, 15), (55, 16)]  # the last two: the SwePol cable north to the map edge
TILE_PAD = 0.15
VOLTAGES = "(^|;)(220000|380000|400000|450000|750000)($|;)"
DEEP_KM = 1.5  # a point this far from the Polish border is surely on its side (Natural Earth is coarse)
GROUP_KM = 3.0  # crossings of one neighbour this close together are one interconnector
PATH_KM = 40.0  # line kept on each side of the crossing
PATH_SEA_KM = 150.0  # the undersea cable is followed to the map edge


def local_today() -> date:
    """Today's date in Warsaw (the PSE business day)."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Warsaw")).date()
    except Exception:  # no tz database: Warsaw is UTC+1 or UTC+2, so UTC+1 is right except near midnight
        return (datetime.now(timezone.utc) + timedelta(hours=1)).date()


def pse_url(report: str, day: str) -> str:
    """One request for a whole business day of a PSE report."""
    flt = quote("business_date eq '" + day + "'")
    return f"{API}{report}?$filter={flt}&$first=2000"


def num(value) -> float | None:
    """PSE values: numbers or text with a decimal comma ("4244,492"). None stays None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def iso_utc(ts: str) -> str:
    """PSE '2026-11-27 01:52:12.092' (UTC) -> '2026-11-27T01:52Z'."""
    return str(ts)[:10] + "T" + str(ts)[11:16] + "Z"


def section_pair(code: str) -> tuple[str, str] | None:
    """'DE-PL' -> ('DE', 'PL'); 'PL-UA_DOB' -> ('PL', 'UA'). None if not a two-country section."""
    m = re.fullmatch(r"([A-Z]{2})(?:_[A-Z0-9]+)?-([A-Z]{2})(?:_[A-Z0-9]+)?", str(code or ""))
    return (m.group(1), m.group(2)) if m else None


def quarter_start(period: str) -> str | None:
    """'00:00 - 00:15' -> '00:00'."""
    m = re.match(r"\s*(\d{2}:\d{2})", str(period or ""))
    return m.group(1) if m else None


def parse_day(gen_rows: list[dict], cal_rows: list[dict], flow_rows: list[dict]) -> dict:
    """The three reports of one day -> aligned series per quarter (ordered by UTC time).

    Returns {"utc": [...], "start": [...], "generation": {code: [MW]}, "wind": [...], "solar": [...],
    "demand": [...], "balance": [...], "sections": {code: [MW]}, "net": {country: [MW, + = import]}}.
    """
    keys = sorted({r["dtime_utc"] for r in cal_rows})
    index = {k: i for i, k in enumerate(keys)}
    n = len(keys)
    start = [None] * n
    out = {"utc": keys, "start": start, "generation": {}, "wind": [None] * n, "solar": [None] * n,
           "demand": [None] * n, "balance": [None] * n, "sections": {}, "net": {}}
    for r in cal_rows:
        i = index[r["dtime_utc"]]
        start[i] = quarter_start(r.get("period"))
        out["wind"][i] = num(r.get("wi"))
        out["solar"][i] = num(r.get("pv"))
        out["demand"][i] = num(r.get("demand"))
        p, np_ = num(r.get("swm_p")), num(r.get("swm_np"))
        out["balance"][i] = round(p + np_, 3) if p is not None and np_ is not None else None
    for r in gen_rows:
        i = index.get(r["dtime_utc"])
        code = r.get("alias_entsoe")
        if i is None or not code:
            continue
        out["generation"].setdefault(code, [None] * n)[i] = num(r.get("value"))
    for r in flow_rows:
        i = index.get(r["dtime_utc"])
        pair = section_pair(r.get("section_code"))
        if i is None or not pair or "PL" not in pair or pair[0] == pair[1]:
            continue
        code = r["section_code"]
        v = num(r.get("value"))
        sec = out["sections"].setdefault(code, [None] * n)
        sec[i] = v if sec[i] is None or v is None else sec[i] + v
        other = pair[1] if pair[0] == "PL" else pair[0]
        net = out["net"].setdefault(other, [None] * n)
        if v is not None:
            net[i] = round((net[i] or 0.0) + v, 3)
    return out


def day_complete(day: dict) -> str | None:
    """None if every quarter has demand, wind, solar, all generation types and all sections; else the reason."""
    n = len(day["utc"])
    if n < 92:  # 92 on the spring DST day, 100 on the autumn one, 96 otherwise
        return f"{n} quarters"
    for name in ("wind", "solar", "demand"):
        if any(v is None for v in day[name]):
            return f"{name} has gaps"
    if len(day["generation"]) < 10 or any(v is None for s in day["generation"].values() for v in s):
        return "generation has gaps"
    if len(day["net"]) < 6 or any(v is None for s in day["net"].values() for v in s):
        return "cross-border flows have gaps"
    return None


# --- interconnectors (OSM) ----------------------------------------------------------------------------------


def _km_xy(lon: float, lat: float) -> tuple[float, float]:
    return lon * 111.32 * math.cos(math.radians(52.0)), lat * 110.57


def point_in_rings(rings, lon: float, lat: float) -> bool:
    inside = False
    for ring in rings:
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


class _Border:
    """Segments of a set of rings in km, bucketed by 0.25 degree cells for fast nearby-distance queries."""

    CELL = 0.25
    FAR_KM = 30.0  # distances beyond the neighbouring cells are reported as this cap

    def __init__(self, rings):
        self.cells: dict[tuple[int, int], list] = {}
        for ring in rings:
            for a, b in zip(ring, ring[1:] + ring[:1]):
                seg = (*_km_xy(*a), *_km_xy(*b))
                for cx in range(int(math.floor(min(a[0], b[0]) / self.CELL)), int(math.floor(max(a[0], b[0]) / self.CELL)) + 1):
                    for cy in range(int(math.floor(min(a[1], b[1]) / self.CELL)), int(math.floor(max(a[1], b[1]) / self.CELL)) + 1):
                        self.cells.setdefault((cx, cy), []).append(seg)

    def dist(self, lon: float, lat: float) -> float:
        px, py = _km_xy(lon, lat)
        cx, cy = int(math.floor(lon / self.CELL)), int(math.floor(lat / self.CELL))
        best = self.FAR_KM
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for ax, ay, bx, by in self.cells.get((cx + i, cy + j), ()):
                    dx, dy = bx - ax, by - ay
                    den = dx * dx + dy * dy
                    t = 0.0 if den == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / den))
                    best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
        return best


_BORDERS: dict[int, _Border] = {}


def dist_to_rings_km(rings, lon: float, lat: float) -> float:
    """Distance from the point to the rings in km (capped at 30 km: only near-border distances matter here)."""
    border = _BORDERS.get(id(rings))
    if border is None:
        border = _BORDERS[id(rings)] = _Border(rings)
    return border.dist(lon, lat)


def _key(p) -> tuple[float, float]:
    return (round(p[0], 6), round(p[1], 6))


class Grid:
    """The OSM lines as a graph: nodes (rounded lon/lat) and edges, each edge with the ways that draw it."""

    def __init__(self, ways: list[dict]):
        self.ways = {w["id"]: w for w in ways}
        self.adj: dict[tuple, dict[tuple, set]] = {}
        for w in ways:
            pts = [_key(c) for c in w["coords"]]
            for a, b in zip(pts, pts[1:]):
                if a != b:
                    self.adj.setdefault(a, {}).setdefault(b, set()).add(w["id"])
                    self.adj.setdefault(b, {}).setdefault(a, set()).add(w["id"])

    def walk(self, start, first, km: float) -> list[tuple]:
        """Follow the line from `start` through `first` for about `km` past `first`, going straight on at junctions."""
        path, prev, cur, total = [start], start, first, 0.0
        seen = {start}
        while True:
            if prev != start:
                total += haversine_m(prev, cur) / 1000
            path.append(cur)
            seen.add(cur)
            if total >= km:
                break
            nxt = [n for n in self.adj.get(cur, {}) if n not in seen]
            if not nxt:
                break
            hx, hy = cur[0] - prev[0], cur[1] - prev[1]

            def straight(n):
                dx, dy = n[0] - cur[0], n[1] - cur[1]
                norm = math.hypot(dx, dy) * math.hypot(hx, hy) or 1.0
                return (dx * hx + dy * hy) / norm

            prev, cur = cur, max(nxt, key=straight)
        return path

    def reach(self, start, ok, limit: int = 400) -> list[tuple]:
        """Nodes reachable from `start` through nodes for which ok(node) is true (breadth first, capped)."""
        out, todo, seen = [], [start], {start}
        while todo and len(out) < limit:
            n = todo.pop(0)
            out.append(n)
            for m in self.adj.get(n, {}):
                if m not in seen and ok(m):
                    seen.add(m)
                    todo.append(m)
        return out


def _segment_cut(a, b, rings):
    """First intersection of segment a-b with the rings (lon/lat), or None."""
    best = None
    for ring in rings:
        for c, d in zip(ring, ring[1:] + ring[:1]):
            r = (b[0] - a[0], b[1] - a[1])
            s = (d[0] - c[0], d[1] - c[1])
            den = r[0] * s[1] - r[1] * s[0]
            if den == 0:
                continue
            t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
            u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
            if 0 <= t <= 1 and 0 <= u <= 1 and (best is None or t < best[0]):
                best = (t, (a[0] + t * r[0], a[1] + t * r[1]))
    return best[1] if best else None


def classify(lon: float, lat: float, countries: dict) -> tuple[str, float]:
    """(country name or 'sea', distance to the Polish border in km)."""
    d = dist_to_rings_km(countries["Poland"], lon, lat)
    if point_in_rings(countries["Poland"], lon, lat):
        return "Poland", d
    for name, rings in countries.items():
        if name != "Poland" and point_in_rings(rings, lon, lat):
            return name, d
    return "sea", d


def nearest_country(lon: float, lat: float, countries: dict) -> str:
    """The neighbour whose land is nearest to the point (for a point that Natural Earth puts in Poland)."""
    return min((n for n in countries if n != "Poland"), key=lambda n: dist_to_rings_km(countries[n], lon, lat))


def is_hvdc(tags: dict) -> bool:
    return str(tags.get("frequency", "")).strip() == "0" or "swepol" in str(tags.get("name", "")).lower()


def _kv(ways) -> list[int] | None:
    kv = sorted({int(v) // 1000 for w in ways for v in str(w["tags"].get("voltage", "")).split(";")
                 if v.strip().isdigit() and int(v) >= 220000}, reverse=True)
    return kv or None


def find_crossings(ways: list[dict], countries: dict) -> tuple[list[dict], list[str]]:
    """Interconnector crossings from OSM line ways. Returns (points, notes).

    1. An edge from a node in Poland to a node in a neighbour (or into the open sea, for an HVDC cable) is a
       crossing when the line reaches more than DEEP_KM inside Poland on one side and more than DEEP_KM inside
       the neighbour on the other (lines that wander across a border river and back are not crossings).
    2. On the far side, a line end (a border substation such as Hagenwerder) counts as well as DEEP_KM.
    Crossings of the same neighbour within GROUP_KM are one interconnector (double circuits drawn as two ways).
    """
    g = Grid(ways)
    cache: dict[tuple, tuple[str, float]] = {}

    def cls(n):
        if n not in cache:
            cache[n] = classify(n[0], n[1], countries)
        return cache[n]

    def far_side(start, side: str) -> bool:
        """Does the line from `start`, staying on `side`, reach DEEP_KM inside it or end there (a substation)?

        Polish side: deep only. Foreign side: deep, or a line end, since border substations (Hagenwerder) sit
        closer to the border than Natural Earth can tell. A line that only wanders across a border river and back
        has neither on the far side.
        """
        def ok(m):
            c = cls(m)[0]
            return c == side if side == "Poland" else c != "Poland"
        for m in g.reach(start, ok):
            c, d = cls(m)
            if d >= DEEP_KM and (c == side or side == "Sweden" and c == "sea"):
                return True
            if side != "Poland" and len(g.adj[m]) == 1 and c != "Poland":
                return True
        return False

    raw = []  # (country, polish node, foreign node, way ids)
    for a, nbrs in g.adj.items():
        if cls(a)[0] != "Poland":
            continue
        for b, wids in nbrs.items():
            cb = cls(b)
            if cb[0] == "Poland":
                continue
            country = cb[0]
            if country == "sea":
                if not any(is_hvdc(g.ways[w]["tags"]) for w in wids):
                    continue
                country = "Sweden"
            if far_side(a, "Poland") and far_side(b, country):
                raw.append((country, a, b, set(wids)))
    # group
    groups: list[dict] = []
    for country, a, b, wids in raw:
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        for gr in groups:
            if gr["country"] == country and haversine_m(gr["mid"], mid) / 1000 <= GROUP_KM:
                gr["edges"].append((a, b))
                gr["wids"] |= wids
                break
        else:
            groups.append({"country": country, "mid": mid, "edges": [(a, b)], "wids": set(wids)})
    by_iso = {v: k for k, v in NEIGHBOURS.items()}
    points, skipped = [], {}
    for gr in groups:
        iso = by_iso.get(gr["country"])
        if iso is None:
            skipped[gr["country"]] = skipped.get(gr["country"], 0) + 1
            continue
        a, b = gr["edges"][0]
        cross = _segment_cut(a, b, countries["Poland"]) or ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        inner = g.walk(b, a, PATH_KM)  # from the foreign node into Poland
        outer = g.walk(a, b, PATH_SEA_KM if gr["country"] == "Sweden" else PATH_KM)  # into the neighbour
        path = inner[::-1][:-1] + [cross] + outer[1:]
        path = simplify(path, 100.0)
        def ways_along(nodes, km=10.0):
            """Way ids in walking order along `nodes` for the first `km`."""
            out, total = [], 0.0
            for u, v in zip(nodes, nodes[1:]):
                for w in sorted(g.adj.get(u, {}).get(v, ())):
                    if w not in out:
                        out.append(w)
                total += haversine_m(u, v) / 1000
                if total > km:
                    break
            return out

        polish_ids = ways_along(inner[1:], 30.0)  # from the Polish node a inward
        foreign_ids = ways_along(outer[1:])  # from the foreign node b outward
        wl = [g.ways[w] for w in dict.fromkeys(sorted(gr["wids"]) + polish_ids + foreign_ids)]
        names = [g.ways[w]["tags"]["name"] for w in polish_ids + sorted(gr["wids"]) + foreign_ids
                 if g.ways[w]["tags"].get("name")]
        # the Polish side's name first; a Latin-script name before a Cyrillic one
        name = next((n for n in names if not re.search("[\u0400-\u04ff]", n)), names[0] if names else None)
        ids = [f"way/{w['id']}" for w in wl]
        points.append({
            "id": f"ic:{iso}:way/{sorted(gr['wids'])[0]}",
            "name": name,
            "kind": "interconnector",
            "lon": round(cross[0], 5),
            "lat": round(cross[1], 5),
            "props": {
                "neighbour": iso,
                "country": NEIGHBOURS[iso],
                "voltage_kv": _kv([g.ways[w] for w in sorted(gr["wids"]) + polish_ids]),
                "hvdc": any(is_hvdc(w["tags"]) for w in wl),
                "cable": any(w["tags"].get("power") == "cable" for w in wl),
                "operator": next((w["tags"].get("operator") for w in wl if w["tags"].get("operator")), None),
                "osm_ways": ids,
                "osm_ref": next((g.ways[w]["tags"].get("ref") for w in sorted(gr["wids"])
                                 if g.ways[w]["tags"].get("ref")), None),
                "path": [[round(x, 5), round(y, 5)] for x, y in path],  # Polish side first
            },
        })
    notes = [f"Lines to {k} left out (no PSE trading section): {v}" for k, v in sorted(skipped.items())]
    return sorted(points, key=lambda p: (p["props"]["neighbour"], p["lon"], p["lat"])), notes


def osm_ways(paths) -> list[dict]:
    seen, out = set(), []
    for p in paths:
        for el in json.loads(Path(p).read_text(encoding="utf-8")).get("elements", []):
            if el.get("type") != "way" or el["id"] in seen or len(el.get("geometry") or []) < 2:
                continue
            seen.add(el["id"])
            tags = el.get("tags") or {}
            out.append({"id": el["id"], "tags": {k: tags[k] for k in ("power", "voltage", "frequency", "name",
                                                                       "operator", "circuits", "cables", "ref")
                                                  if k in tags},
                        "coords": [(g["lon"], g["lat"]) for g in el["geometry"]]})
    return sorted(out, key=lambda w: w["id"])


class PolandPowerPse(Source):
    info = SourceInfo(
        id="pl_power_pse",
        title="Power system of Poland every 15 minutes: generation by fuel and cross-border flows",
        publisher="Polskie Sieci Elektroenergetyczne S.A. (PSE, transmission system operator); interconnector "
                  "lines from OpenStreetMap",
        homepage=REPORTS_PAGE,
        license="PSE: public sector information, no licence text published with the API; cite PSE S.A. "
                "OpenStreetMap: ODbL 1.0",
        description="Generation by production type (ENTSO-E codes), wind and solar output, demand and the "
                    "physical flows on each cross-border trading section, per 15 minutes, for the newest complete "
                    "day; the 220 kV and higher lines that cross the border.",
        used_for=["Power now map layer"],
    )

    def _day_paths(self, day: str) -> dict[str, str]:
        return {r: f"pse/{day}/{r}.json" for r in REPORTS}

    def _load_day(self, day: str) -> dict | None:
        rows = {}
        for report, rel in self._day_paths(day).items():
            path = self.raw_dir / rel
            if not path.exists():
                return None
            rows[report] = json.loads(path.read_text(encoding="utf-8")).get("value") or []
        return parse_day(rows["his-gen-pal"], rows["his-wlk-cal"], rows["przeplywy-mocy"])

    def fetch(self, force: bool = False) -> None:
        today = local_today()
        for back in range(1, 5):
            day = (today - timedelta(days=back)).isoformat()
            for report, rel in self._day_paths(day).items():
                self.download(pse_url(report, day), rel, force=force)
            parsed = self._load_day(day)
            reason = day_complete(parsed) if parsed else "missing"
            if reason is None:
                print(f"    PSE day {day}: {len(parsed['utc'])} quarters")
                break
            print(f"    PSE day {day} incomplete ({reason}); trying the day before")
            for rel in self._day_paths(day).values():
                self.discard(rel)
        else:
            raise RuntimeError("no complete PSE day in the last 4 days")
        failed = []
        for s, w in TILES:  # a busy Overpass fails one tile: go on with the others, report at the end
            q = (f'[out:json][timeout:90];way["power"~"^(line|cable)$"]["voltage"~"{VOLTAGES}"]'
                 f"({s - TILE_PAD},{w - TILE_PAD},{s + 1 + TILE_PAD},{w + 1 + TILE_PAD});out tags geom qt;")
            try:
                overpass(self, q, f"osm/tile_{s}_{w}.json")
            except OverpassError as exc:
                failed.append(f"{s}_{w}")
                print(f"      tile {s}_{w} failed: {exc}")
        if failed:
            raise RuntimeError(f"OSM tiles not fetched (run fetch again later): {failed}")

    def newest_day(self) -> str:
        days = sorted((p.name for p in (self.raw_dir / "pse").iterdir() if p.is_dir()), reverse=True)
        for day in days:
            parsed = self._load_day(day)
            if parsed and day_complete(parsed) is None:
                return day
        raise RuntimeError("no complete cached PSE day: run fetch pl_power_pse")

    def process(self) -> dict:
        day = self.newest_day()
        series = self._load_day(day)
        tile_paths = [self.raw_dir / f"osm/tile_{s}_{w}.json" for s, w in TILES]
        missing = [p.name for p in tile_paths if not p.exists()]
        if missing:
            raise RuntimeError(f"OSM tiles missing: {missing}")
        ne = load_interim("pl_geo_ne")
        countries = {c["name"]: c["rings"] for c in ne["countries"]}
        points, ic_notes = find_crossings(osm_ways(tile_paths), countries)
        got = {p["props"]["neighbour"] for p in points}
        if got != set(NEIGHBOURS):
            raise RuntimeError(f"interconnectors found for {sorted(got)}, expected {sorted(NEIGHBOURS)}")
        osm_date = osm_timestamp(tile_paths)
        published, retrieved = [], []
        manifest = json.loads((self.raw_dir / "manifest.json").read_text(encoding="utf-8"))
        for rel in self._day_paths(day).values():
            rows = json.loads((self.raw_dir / rel).read_text(encoding="utf-8")).get("value") or []
            published += [r["publication_ts_utc"] for r in rows if r.get("publication_ts_utc")]
            if rel in manifest:
                retrieved.append(manifest[rel]["retrieved"])
        gen_codes = sorted(series["generation"])
        mwh = {c: round(sum(series["generation"][c]) / 4) for c in gen_codes}
        return {
            "vintage": f"PSE {day} (15-minute data); OpenStreetMap {str(osm_date)[:10]}",
            "day": day,
            "timezone": "Europe/Warsaw",
            "published_utc": iso_utc(max(published)) if published else None,
            "retrieved_utc": max(retrieved) if retrieved else None,
            "fuels": {c: PSR.get(c) for c in gen_codes},
            "series": {
                "utc": series["utc"],
                "start": series["start"],
                "generation": series["generation"],
                "wind": series["wind"],
                "solar": series["solar"],
                "demand": series["demand"],
                "balance": series["balance"],
                "sections": series["sections"],
                "net": {k: series["net"][k] for k in sorted(series["net"])},
            },
            "tables": {
                "power_day": {
                    "level": "country",
                    "fields": {
                        **{f"gen_{c.lower()}_mwh": {"label": f"Generation, {PSR.get(c, c)}", "unit": "MWh",
                                                    "year": int(day[:4]), "note": f"{day}, PSE his-gen-pal {c}"}
                           for c in gen_codes},
                        "net_import_mwh": {"label": "Net cross-border import", "unit": "MWh", "year": int(day[:4]),
                                           "note": f"{day}, PSE przeplywy-mocy, all sections (+ import)"},
                    },
                    "rows": {"PL": {**{f"gen_{c.lower()}_mwh": mwh[c] for c in gen_codes},
                                    "net_import_mwh": round(sum(sum(s) for s in series["net"].values()) / 4)}},
                }
            },
            "points": points,
            "notes": [
                f"Business day {day} (Warsaw time), {len(series['utc'])} quarters of an hour; values are mean power "
                "in MW over each quarter; `start` is the start of the quarter.",
                "his-gen-pal: generation by ENTSO-E production type (code list v36, " + CODELIST + ").",
                "przeplywy-mocy: physical flows on the trading sections without the local 110 kV exchange; PSE: "
                "'+' is import into Poland, '-' is export from Poland. `net` adds both sections of a neighbour.",
                "his-wlk-cal: wi = wind, pv = solar, demand = 'Zapotrzebowanie na moc', balance = swm_p + swm_np "
                "(the national cross-border balance).",
                "Licence: the API and raporty.pse.pl publish no terms; www.pse.pl (reuse page "
                "https://www.pse.pl/bip/ponowne-wykorzystanie-informacji-publicznej) did not resolve from the "
                "build machine. The data is public sector information; credit PSE S.A.",
                "Interconnectors: OSM power=line/cable of 220 kV or more. A crossing is a line segment from Poland to "
                f"a neighbour (Natural Earth 1:10m) whose line reaches more than {DEEP_KM} km inside Poland and, on "
                f"the other side, more than {DEEP_KM} km inside the neighbour or a line end (a border substation); "
                "into the open sea only for the HVDC cable (frequency=0 or name SwePol). Crossings of one neighbour "
                f"within {GROUP_KM} km are one interconnector. Names are OSM names, Polish side first; null when "
                "no way near the crossing has one.",
                *ic_notes,
                ODBL_NOTE,
            ],
            "_files": [*self._day_paths(day).values(), *[f"osm/tile_{s}_{w}.json" for s, w in TILES]],
        }

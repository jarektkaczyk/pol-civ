"""Passenger train timetables of Poland for one weekday (GTFS, all operators on the PKP PLK network).

The feed is a daily GTFS conversion of the PKP PLK timetable API (plus Koleje Mazowieckie data) by
Mikolaj Kuranowski. It covers a rolling 30 days. We keep one representative Wednesday:

* the Wednesday in the feed window with the most train trips, skipping Polish public holidays and
  20 December to 6 January (holiday timetables);
* every rail trip (route_type 2) that runs that day, plus the trips of the day before that are still
  running after midnight (night trains), with their times shifted by -24 h;
* replacement buses (route_type 3, "ZKA") are left out: they are road services.

Times are seconds from 00:00 of the chosen Wednesday (negative for a night train that left on
Tuesday, above 86,400 for one that arrives on Thursday). Shapes keep the GTFS distance along the
line (km) at each kept vertex, so a builder can place every stop on the projected line.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
import re
import zipfile
from collections import Counter, defaultdict

from ..core.source import Source, SourceInfo

FEED_URL = "https://mkuran.pl/gtfs/polish_trains.zip"
WEEKDAY = 2  # Wednesday (date.weekday())
SHAPE_TOL_KM = 0.05  # Douglas-Peucker tolerance for the interim (the builder simplifies again in map km)

# Fixed-date public holidays in Poland (the movable ones fall on Sunday, Monday or Thursday).
HOLIDAYS_MMDD = {"01-01", "01-06", "05-01", "05-03", "08-15", "11-01", "11-11", "12-24", "12-25", "12-26"}
LINE_CODE = re.compile(r"^[A-Za-z]{1,2}\d{1,3}$")
SKIP_FROM, SKIP_TO = "12-20", "01-06"  # Christmas and New Year timetables


def gtfs_seconds(text: str) -> int:
    """'25:07:30' -> 90450 (GTFS times may pass 24:00)."""
    h, m, s = text.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def is_skipped_day(day: dt.date) -> bool:
    mmdd = day.strftime("%m-%d")
    return mmdd in HOLIDAYS_MMDD or mmdd >= SKIP_FROM or mmdd <= SKIP_TO


def pick_weekday(trips_per_day: dict[str, int]) -> str:
    """The Wednesday (YYYYMMDD) with the most train trips, outside holidays; ties go to the earlier day."""
    best = None
    for key in sorted(trips_per_day):
        day = dt.date(int(key[:4]), int(key[4:6]), int(key[6:]))
        if day.weekday() != WEEKDAY or is_skipped_day(day):
            continue
        if best is None or trips_per_day[key] > trips_per_day[best]:
            best = key
    if best is None:
        raise RuntimeError("no Wednesday outside the holiday window in the GTFS feed")
    return best


def simplify_idx(pts: list[tuple[float, float]], tol: float) -> list[int]:
    """Douglas-Peucker on planar points; returns the kept indices (ends always kept)."""
    n = len(pts)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for k in range(i + 1, j):
            x, y = pts[k]
            d = math.hypot(x - x1, y - y1) if norm == 0 else abs(dy * (x - x1) - dx * (y - y1)) / norm
            if d > best:
                best, idx = d, k
        if idx >= 0 and best > tol:
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return [k for k in range(n) if keep[k]]


def _plane(lon: float, lat: float) -> tuple[float, float]:
    """Local equirectangular km around 52 N (only used to simplify before the real projection)."""
    return lon * 111.195 * math.cos(math.radians(52.0)), lat * 111.195


def split_name(short_name: str, number: str) -> str | None:
    """'13120/1 Kolberg (P12)' with number '13120/1' -> 'Kolberg'; a bare number or line code -> None."""
    text = (short_name or "").strip()
    if number and text.startswith(number):
        text = text[len(number):].strip()
    if "(" in text:
        text = text[:text.index("(")].strip()
    if LINE_CODE.match(text) or text[:1].isdigit():
        return None  # an IC line code ("Ex03", "P12", "Px61") or another number, not a train name
    return text or None


class PlRailGtfs(Source):
    info = SourceInfo(
        id="pl_rail_gtfs",
        title="Passenger train timetables of Poland (GTFS)",
        publisher="PKP Polskie Linie Kolejowe; Koleje Mazowieckie; GTFS conversion by Mikołaj Kuranowski",
        homepage="https://mkuran.pl/gtfs/",
        license="Re-use under the public sector information terms of PKP PLK (bip.plk-sa.pl/ponowne-wykorzystywanie) "
        "and Koleje Mazowieckie: state the source, when the data was made and obtained, and that it was processed. "
        "GTFS conversion credited to Mikołaj Kuranowski.",
        description="Every passenger train that runs on one weekday, with its stops, times and route line.",
        used_for=["Trains layer"],
    )

    ZIP = "polish_trains.zip"

    def fetch(self, force=False):
        self.download(FEED_URL, self.ZIP, force=force, expect_binary=True)

    def _rows(self, z: zipfile.ZipFile, name: str):
        with z.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))

    def process(self):
        z = zipfile.ZipFile(self.raw_dir / self.ZIP)
        feed = next(self._rows(z, "feed_info.txt"))
        attributions = [r["organization_name"] for r in self._rows(z, "attributions.txt")]
        agencies = {r["agency_id"]: {"name": r["agency_name"], "url": r["agency_url"]} for r in self._rows(z, "agency.txt")}
        routes = {r["route_id"]: r for r in self._rows(z, "routes.txt")}
        services: dict[str, set[str]] = defaultdict(set)
        for r in self._rows(z, "calendar_dates.txt"):
            if r["exception_type"] == "1":
                services[r["date"]].add(r["service_id"])
        if "calendar.txt" in z.namelist():
            raise RuntimeError("pl_rail_gtfs: calendar.txt appeared in the feed; process() reads calendar_dates only")

        rail_trips = [t for t in self._rows(z, "trips.txt") if routes[t["route_id"]]["route_type"] == "2"]
        bus_trips = Counter()
        per_service = Counter(t["service_id"] for t in rail_trips)
        per_day = {d: sum(per_service[s] for s in sv) for d, sv in services.items()}
        day = pick_weekday(per_day)
        day_date = dt.date(int(day[:4]), int(day[4:6]), int(day[6:]))
        prev = (day_date - dt.timedelta(days=1)).strftime("%Y%m%d")
        today_ids = {t["trip_id"] for t in rail_trips if t["service_id"] in services[day]}
        prev_ids = {t["trip_id"] for t in rail_trips if t["service_id"] in services[prev]}
        for t in self._rows(z, "trips.txt"):
            if routes[t["route_id"]]["route_type"] == "3" and t["service_id"] in services[day]:
                bus_trips[t["route_id"].split("_")[0]] += 1

        times: dict[str, list[tuple[int, str, int, int, float | None, str, str]]] = defaultdict(list)
        wanted = today_ids | prev_ids
        for r in self._rows(z, "stop_times.txt"):
            if r["trip_id"] in wanted:
                dist = r["shape_dist_traveled"]
                times[r["trip_id"]].append((
                    int(r["stop_sequence"]), r["stop_id"], gtfs_seconds(r["arrival_time"]),
                    gtfs_seconds(r["departure_time"]), float(dist) if dist else None,
                    r["pickup_type"], r["drop_off_type"],
                ))

        stops_raw = {r["stop_id"]: r for r in self._rows(z, "stops.txt")}

        def station_of(stop_id: str) -> str:
            return stops_raw[stop_id].get("parent_station") or stop_id

        trips, used_shapes, used_stations, night = [], set(), Counter(), 0
        no_dist = 0
        runs = [(t, 0) for t in rail_trips if t["trip_id"] in today_ids]
        runs += [(t, -86400) for t in rail_trips if t["trip_id"] in prev_ids]
        for t, shift in runs:
            tid = t["trip_id"]
            st = sorted(times.get(tid, []))
            if len(st) < 2:
                continue
            if shift and st[-1][2] + shift <= 0:
                continue  # yesterday's trip that ended before midnight
            if shift:
                night += 1
            if any(s[4] is None for s in st):
                no_dist += 1
            stations = [station_of(s[1]) for s in st]
            used_stations.update(stations)
            if t["shape_id"]:
                used_shapes.add(t["shape_id"])
            route = routes[t["route_id"]]
            number = (t["plk_train_number"] or t["trip_short_name"] or "").strip() or None
            trips.append({
                "id": tid if not shift else tid + "@prev",
                "agency": route["agency_id"],
                "route": route["route_short_name"] or None,
                "route_name": route["route_long_name"] or None,
                "category": (t["plk_category_code"] or "").strip() or None,
                "number": number,
                # plk_train_name is the official name in capitals; the short name has it in normal case,
                # sometimes followed by an IC line code ("Kolberg (P12)") or with only a line code ("Ex03").
                "name": split_name(t["trip_short_name"], number or "") if (t["plk_train_name"] or "").strip() else None,
                "headsign": t["trip_headsign"] or None,
                "shape": t["shape_id"] or None,
                "stops": stations,
                "arr": [s[2] + shift for s in st],
                "dep": [s[3] + shift for s in st],
                "dist": [s[4] for s in st],
                # 1 = passengers may not board or alight here (a technical stop)
                "no_pax": [1 if (s[5] == "1" and s[6] == "1") else 0 for s in st],
            })

        shapes_raw: dict[str, list[tuple[int, float, float, float]]] = defaultdict(list)
        for r in self._rows(z, "shapes.txt"):
            if r["shape_id"] in used_shapes:
                shapes_raw[r["shape_id"]].append((
                    int(r["shape_pt_sequence"]), float(r["shape_pt_lon"]), float(r["shape_pt_lat"]),
                    float(r["shape_dist_traveled"]) if r["shape_dist_traveled"] else math.nan,
                ))
        shapes, raw_points, kept_points = {}, 0, 0
        for sid, pts in shapes_raw.items():
            pts.sort()
            keep = simplify_idx([_plane(p[1], p[2]) for p in pts], SHAPE_TOL_KM)
            raw_points += len(pts)
            kept_points += len(keep)
            shapes[sid] = [[round(pts[k][1], 5), round(pts[k][2], 5),
                            None if math.isnan(pts[k][3]) else round(pts[k][3], 3)] for k in keep]

        points = []
        for sid, n in sorted(used_stations.items()):
            s = stops_raw[sid]
            points.append({
                "id": f"station:{sid}", "name": s["stop_name"], "kind": "rail_station",
                "lon": round(float(s["stop_lon"]), 5) if s["stop_lon"] else None,
                "lat": round(float(s["stop_lat"]), 5) if s["stop_lat"] else None,
                "props": {"stop_id": sid, "country": s.get("country") or None, "trains": n},
            })

        day_iso = day_date.isoformat()
        feed_day = feed["feed_version"][:10]
        start, end = feed["feed_start_date"], feed["feed_end_date"]
        counts = Counter(t["agency"] for t in trips)
        return {
            "vintage": f"PKP PLK timetable via GTFS feed {feed_day}; weekday {day_iso}",
            "day": day_iso,
            "feed": {"version": feed["feed_version"], "start": f"{start[:4]}-{start[4:6]}-{start[6:]}",
                     "end": f"{end[:4]}-{end[4:6]}-{end[6:]}", "publisher": feed["feed_publisher_name"],
                     "attributions": attributions},
            "agencies": agencies,
            "trips": trips,
            "shapes": shapes,
            "points": points,
            "notes": [
                f"Day: {day_iso}, the Wednesday in the feed window ({start[:4]}-{start[4:6]}-{start[6:]} to "
                f"{end[:4]}-{end[4:6]}-{end[6:]}) with the most train trips, "
                "outside public holidays and 20 December to 6 January.",
                f"{len(trips)} rail trips: {len(trips) - night} that run that day and {night} that left the day before "
                "and run past midnight (times shifted by -24 h).",
                "Trips per operator: " + ", ".join(f"{a} {n}" for a, n in counts.most_common()) + ".",
                "Replacement buses left out (road services): " + (", ".join(f"{a} {n}" for a, n in bus_trips.most_common())
                                                                 or "none") + ".",
                f"Shapes: {len(shapes)} lines, {raw_points} GTFS points simplified to {kept_points} "
                f"(Douglas-Peucker {SHAPE_TOL_KM * 1000:.0f} m).",
                f"{no_dist} trips have a stop without shape_dist_traveled (the builder places those stops on the line).",
                "Attribution required by the feed: " + "; ".join(a.rstrip(".") for a in attributions) + ".",
            ],
            "_files": [self.ZIP],
        }

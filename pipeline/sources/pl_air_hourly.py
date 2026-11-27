"""GIOS hourly PM2.5 at every automatic station for the worst smog week of the last winter.

Source: the Chief Inspectorate of Environmental Protection (GIOS). Two parts of one data bank:

* the archive file "Wyniki pomiarow z <year> roku" (powietrze.gios.gov.pl/pjp/archives): hourly values of every
  station for a whole calendar year, one workbook per pollutant (here `<year>_PM25_1g.xlsx`);
* the API (api.gios.gov.pl/pjp-api/v1/rest) for the months of the current year that the archive does not hold yet:
  `station/findAll`, `station/sensors/{station}` and `archivalData/getDataBySensor/{sensor}` (500 rows per page,
  2 requests per minute; this module waits 31 s between those calls and backs off on HTTP 429).

The season is December to February of the newest winter inside the API's history window (about 12 months). Every
7-day window that starts at midnight is ranked by its mean of the hourly national means (mean over the stations
that report that hour); the window with the highest mean is the smog week. Times are GIOS time, UTC+1 all year,
and a value stamped hh:00 is the mean of the hour that ends then.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
import urllib.error
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from ..core.bdl import read_xlsx
from ..core.source import Source, SourceInfo
from .pl_soc_air import OLD_CODE, _records, archive_files
from .pl_soc_common import num, voivodeship_code

API = "https://api.gios.gov.pl/pjp-api/v1/rest"
ARCHIVE = "https://powietrze.gios.gov.pl/pjp/archives"
DOWNLOAD = "https://powietrze.gios.gov.pl/pjp/archives/downloadFile/{id}"

# The newest winter inside the API window on the run date (2026-11-27). December comes from the archive file of
# ARCHIVE_YEAR; January and February from the API. Hours are GIOS end-of-hour stamps in UTC+1.
ARCHIVE_YEAR = 2025
SEASON_FIRST = datetime(2025, 12, 1, 1)  # the hour 00:00-01:00 on 1 December 2025
SEASON_LAST = datetime(2026, 3, 1, 0)  # the hour 23:00-24:00 on 28 February 2026
API_FIRST = datetime(2026, 1, 1, 1)
WEEK_HOURS = 7 * 24
PAGE = 500  # documented maximum page size
ARCHIVAL_PAGE = 1500  # getDataBySensor accepts it (tested 2026-11-27): one request holds the 1,416 winter hours
SLOW_INTERVAL = 31.0  # seconds between rate-limited GIOS calls (limit: 2 per minute)
FAST_INTERVAL = 0.3  # station/sensors is in the 1,500-per-minute class
STAMP = "%Y-%m-%d %H:%M"


def excel_hour(serial: float) -> datetime:
    """Excel day serial (GIOS archive) -> datetime, rounded to the whole hour."""
    t = datetime(1899, 12, 30) + timedelta(days=float(serial))
    return (t + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def api_hour(text: str) -> datetime:
    """GIOS API stamp '2026-01-01 01:00:00' -> datetime."""
    return datetime.strptime(text[:16], STAMP)


def season_hours() -> list[datetime]:
    n = int((SEASON_LAST - SEASON_FIRST).total_seconds() // 3600) + 1
    return [SEASON_FIRST + timedelta(hours=i) for i in range(n)]


def archive_series(rows: list[list], first: datetime, last: datetime) -> dict[str, dict[datetime, float]]:
    """GIOS archive sheet rows -> {station code: {hour: value}} for hours first..last.

    The sheet has header rows (Nr, Kod stacji, Wskaznik, Czas usredniania, Jednostka, Kod stanowiska), then one row
    per hour: an Excel serial in column 0 and one value per station column. Only 1-hour PM2.5 columns are kept.
    """
    head = {str(r[0]).strip(): r for r in rows[:10] if r and isinstance(r[0], str)}
    codes, avg, ind = head.get("Kod stacji"), head.get("Czas uśredniania"), head.get("Wskaźnik")
    if not codes or not avg or not ind:
        raise RuntimeError("GIOS archive sheet: header rows not found")
    cols = [c for c in range(1, len(codes)) if codes[c] and avg[c] == "1g" and str(ind[c]).replace(",", ".") == "PM2.5"]
    out: dict[str, dict[datetime, float]] = {str(codes[c]): {} for c in cols}
    for r in rows:
        if not r or not isinstance(r[0], (int, float)):
            continue
        t = excel_hour(r[0])
        if t < first or t > last:
            continue
        for c in cols:
            v = num(r[c]) if c < len(r) else None
            if v is not None:
                out[str(codes[c])][t] = v
    return out


def api_rows(pages: list[dict]) -> tuple[str | None, dict[datetime, float]]:
    """Cached getDataBySensor pages -> (sensor position code, {hour: value})."""
    code, out = None, {}
    for p in pages:
        for r in p.get("Lista archiwalnych wyników pomiarów") or []:
            code = code or r.get("Kod stanowiska")
            v = num(r.get("Wartość"))
            if v is not None and r.get("Data"):
                out[api_hour(r["Data"])] = v
    return code, out


def national_means(series: dict[str, dict[datetime, float]], hours: list[datetime]) -> list[float | None]:
    """Mean over the stations that report each hour. An hour reported by fewer than half the median number of
    reporting stations is None, so a partial outage does not stand in for the country."""
    counts = [sum(1 for s in series.values() if h in s) for h in hours]
    ordered = sorted(c for c in counts if c)
    floor = 0.5 * ordered[len(ordered) // 2] if ordered else 1
    out = []
    for h, n in zip(hours, counts):
        vals = [s[h] for s in series.values() if h in s]
        out.append(sum(vals) / len(vals) if vals and n >= floor else None)
    return out


def rank_weeks(hours: list[datetime], means: list[float | None]) -> list[tuple[float, datetime, int]]:
    """Every 7-day window that starts at midnight -> (mean of hourly national means, start hour, hours with data),
    highest first. A window needs data in at least 90% of its hours."""
    out = []
    for i, h in enumerate(hours):
        if h.hour != 1 or i + WEEK_HOURS > len(hours):
            continue
        vals = [m for m in means[i:i + WEEK_HOURS] if m is not None]
        if len(vals) >= 0.9 * WEEK_HOURS:
            out.append((sum(vals) / len(vals), h, len(vals)))
    return sorted(out, key=lambda x: (-x[0], x[1]))


def station_code(sensor_code: str | None) -> str | None:
    """'MpKrakAlKras-PM2.5-1g' -> 'MpKrakAlKras'."""
    return sensor_code.split("-")[0] if sensor_code else None


class PlAirHourly(Source):
    info = SourceInfo(
        id="pl_air_hourly",
        title="Air quality: hourly PM2.5 at every automatic station, winter 2025/26",
        publisher="Główny Inspektorat Ochrony Środowiska (GIOŚ)",
        homepage="https://powietrze.gios.gov.pl/pjp/content/api",
        license="Public sector information; reuse must name GIOŚ as the source (API terms)",
        description="Hourly fine dust (PM2.5) at every automatic measuring station of the State Environmental "
        "Monitoring network, December 2025 to February 2026, with station coordinates. December comes from the "
        "archive file 'Wyniki pomiarów z 2025 roku', January and February from the GIOŚ API, one request per "
        "station: https://api.gios.gov.pl/pjp-api/v1/rest/archivalData/getDataBySensor/{sensor}"
        "?dateFrom=2026-01-01 01:00&dateTo=2026-03-01 00:00.",
        used_for=["Smog week lens"],
    )

    _last_slow = 0.0

    # ------------------------------------------------------------------ fetch

    def _get(self, url: str, rel: str, *, slow: bool, binary: bool = False) -> Path:
        """Cached download with GIOS pacing and a back-off on HTTP 429."""
        if (self.raw_dir / rel).exists():
            return self.raw_dir / rel
        for attempt in range(6):
            if slow:
                wait = SLOW_INTERVAL - (time.monotonic() - PlAirHourly._last_slow)
                if wait > 0:
                    time.sleep(wait)
            try:
                return self.download(url, rel, expect_binary=binary)
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 5:
                    raise
                print(f"      HTTP 429; waiting 65 s (attempt {attempt + 1})")
                exc.close()
                time.sleep(65)
            finally:
                if slow:
                    PlAirHourly._last_slow = time.monotonic()
        raise RuntimeError("unreachable")

    def _archive_ids(self) -> tuple[str, str]:
        page = self.download(ARCHIVE, "archive/archives.html")
        files = archive_files(Path(page).read_text(encoding="utf-8", errors="replace"))
        year_id = files.get(f"Wyniki pomiarów z {ARCHIVE_YEAR} roku")
        meta_id = next((fid for t, fid in files.items() if t.startswith("Metadane oraz kody stacji")), None)
        if not year_id or not meta_id:
            raise RuntimeError(f"GIOS archive page: {ARCHIVE_YEAR} measurements or station metadata not found")
        return year_id, meta_id

    def stations(self) -> list[dict]:
        return json.loads((self.raw_dir / "api/stations.json").read_text())["Lista stacji pomiarowych"]

    def pm25_sensors(self) -> list[tuple[int, int]]:
        """(station id, sensor id) of every PM2.5 sensor in the cached sensor lists."""
        out = []
        for st in self.stations():
            sid = st["Identyfikator stacji"]
            path = self.raw_dir / f"api/sensors/{sid}.json"
            for s in json.loads(path.read_text())["Lista stanowisk pomiarowych dla podanej stacji"]:
                if s.get("Wskaźnik - kod") == "PM2.5":
                    out.append((sid, s["Identyfikator stanowiska"]))
        return out

    @staticmethod
    def _api_rel(sensor: int, page: int, size: int = None) -> str:
        size = size or ARCHIVAL_PAGE
        tag = "" if size == PAGE else f"-s{size}"  # the first sensors were read in pages of 500
        return f"api/archival/{sensor}/{API_FIRST:%Y%m%d%H}-{SEASON_LAST:%Y%m%d%H}{tag}/page-{page:02d}.json"

    def _api_url(self, sensor: int, page: int) -> str:
        q = f"dateFrom={API_FIRST:%Y-%m-%d}%20{API_FIRST:%H:%M}&dateTo={SEASON_LAST:%Y-%m-%d}%20{SEASON_LAST:%H:%M}"
        return f"{API}/archivalData/getDataBySensor/{sensor}?{q}&page={page}&size={ARCHIVAL_PAGE}"

    def api_pages(self, sensor: int) -> tuple[list[dict], list[str]]:
        """Cached pages of one sensor (whole season in one page of ARCHIVAL_PAGE rows, else pages of 500)."""
        for size in (ARCHIVAL_PAGE, PAGE):
            rels, page = [], 0
            while (self.raw_dir / self._api_rel(sensor, page, size)).exists():
                rels.append(self._api_rel(sensor, page, size))
                page += 1
            if rels:
                return [json.loads((self.raw_dir / r).read_text()) for r in rels], rels
        return [], []

    def fetch(self, force: bool = False) -> None:
        year_id, meta_id = self._archive_ids()
        self._get(DOWNLOAD.format(id=year_id), f"archive/{ARCHIVE_YEAR}.zip", slow=False, binary=True)
        self._get(DOWNLOAD.format(id=meta_id), "archive/metadane.xlsx", slow=False, binary=True)
        self._get(f"{API}/station/findAll?page=0&size={PAGE}", "api/stations.json", slow=True)
        for st in self.stations():
            sid = st["Identyfikator stacji"]
            if not (self.raw_dir / f"api/sensors/{sid}.json").exists():
                self._get(f"{API}/station/sensors/{sid}?size={PAGE}", f"api/sensors/{sid}.json", slow=False)
                time.sleep(FAST_INTERVAL)
        auto = self.automatic_pm25_stations(fetch=True) | self.december_stations()
        codes = {st["Identyfikator stacji"]: st["Kod stacji"] for st in self.stations()}
        todo = []
        for sid, sensor in self.pm25_sensors():
            # The current-data endpoint (1,500 requests per minute) names the position, e.g. "X-PM2.5-1g".
            kind = self.sensor_kind(sensor, fetch=True)
            known = {codes[sid], codes[sid] + "MOB", codes[sid].removesuffix("MOB")} & auto
            if kind == "1g" or (kind is None and known):
                todo.append((codes[sid], sensor))
        print(f"    {len(todo)} PM2.5 sensors to read (1-hour now, or silent now but hourly in the metadata or in "
              f"December)", flush=True)
        for n, (code, sensor) in enumerate(todo, 1):
            old = [self.raw_dir / self._api_rel(sensor, i, PAGE) for i in range(3)]
            if all(p.exists() for p in old) or (old[0].exists() and not old[0].read_text().count('-1g"')):
                continue  # read before the switch to one large page
            first = json.loads(self._get(self._api_url(sensor, 0), self._api_rel(sensor, 0), slow=True).read_text())
            rows = first.get("Lista archiwalnych wyników pomiarów") or []
            pos = rows[0].get("Kod stanowiska") if rows else None
            total = int(first.get("totalPages") or 1)
            print(f"    [{n}/{len(todo)}] {code} sensor {sensor} {pos}: {total} page(s)", flush=True)
            if not pos or not pos.endswith("-1g"):
                continue
            for page in range(1, total):
                self._get(self._api_url(sensor, page), self._api_rel(sensor, page), slow=True)

    def sensor_kind(self, sensor: int, fetch: bool = False) -> str | None:
        """'1g' or '24g' from the sensor's current data (last 3 days); None when it has none."""
        rel = f"api/current/{sensor}.json"
        if fetch and not (self.raw_dir / rel).exists():
            try:
                self._get(f"{API}/data/getData/{sensor}?size={PAGE}", rel, slow=False)
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code == 400:  # API-ERR-100003: a manual (24-hour) position has no current data
                    return "24g"
                raise
            finally:
                time.sleep(FAST_INTERVAL)
        if not (self.raw_dir / rel).exists():
            return None
        rows = json.loads((self.raw_dir / rel).read_text()).get("Lista danych pomiarowych") or []
        pos = next((r.get("Kod stanowiska") for r in rows if r.get("Kod stanowiska")), None)
        return pos.rsplit("-", 1)[-1] if pos else None

    def december_stations(self) -> set[str]:
        """Station codes with 1-hour PM2.5 values in December of ARCHIVE_YEAR (archive file)."""
        with zipfile.ZipFile(self.raw_dir / f"archive/{ARCHIVE_YEAR}.zip") as z, tempfile.TemporaryDirectory() as d:
            sheet = z.extract(f"{ARCHIVE_YEAR}_PM25_1g.xlsx", d)
            series = archive_series(read_xlsx(sheet, 0), SEASON_FIRST, API_FIRST - timedelta(hours=1))
        return {k for k, v in series.items() if v}

    def automatic_pm25_stations(self, fetch: bool = False) -> set[str]:
        """Station codes with a 1-hour PM2.5 position open on API_FIRST (GIOS sensor metadata, automatic only)."""
        out, page, total = set(), 0, 1
        while page < total:
            rel = f"api/metadata-sensors-auto/page-{page:02d}.json"
            url = f"{API}/metadata/sensors?filter%5Btyp-pomiaru%5D=automatyczny&page={page}&size={PAGE}"
            path = self._get(url, rel, slow=True) if fetch else self.raw_dir / rel
            doc = json.loads(path.read_text())
            total = int(doc.get("totalPages") or 1)
            for r in doc.get("Lista metadanych stanowisk pomiarowych") or []:
                closed = r.get("Data zamknięcia")
                if closed:
                    m, d, y = (int(x) for x in closed.split("/"))
                    if datetime(y, m, d) < API_FIRST - timedelta(hours=1):
                        continue
                if str(r.get("Wskaźnik - kod")).replace(",", ".") == "PM2.5" and \
                        str(r.get("Czas uśredniania")).startswith("1-godz"):
                    out.add(r["Kod stacji"])
            page += 1
        return out

    # ---------------------------------------------------------------- process

    def station_meta(self) -> dict[str, dict]:
        """Station code -> {name, city, lon, lat, voivodeship}: the API list, then the archive metadata for
        stations that closed since (matched by the 'MOB' suffix or the old code as in pl_soc_air)."""
        out = {}
        for st in self.stations():
            out[st["Kod stacji"]] = {
                "name": st.get("Nazwa stacji"), "city": st.get("Nazwa miasta"),
                "lon": num(st.get("WGS84 λ E")), "lat": num(st.get("WGS84 φ N")),
                "voivodeship": voivodeship_code(st.get("Województwo")),
            }
        meta_path = self.raw_dir / "archive/metadane.xlsx"
        if meta_path.exists():
            for r in _records(meta_path, "STACJE"):
                code = r.get("kod_stacji")
                if code and code not in out:
                    out[code] = {"name": r.get("nazwa_stacji"), "city": r.get("miejscowosc"),
                                 "lon": num(r.get("wgs84_e")), "lat": num(r.get("wgs84_n")),
                                 "voivodeship": voivodeship_code(r.get("wojewodztwo")), "_old": r.get(OLD_CODE)}
        return out

    def season_series(self) -> tuple[dict[str, dict[datetime, float]], list[str]]:
        """Station code -> {hour: PM2.5} for the whole season, and the raw files used."""
        with zipfile.ZipFile(self.raw_dir / f"archive/{ARCHIVE_YEAR}.zip") as z, tempfile.TemporaryDirectory() as d:
            sheet = z.extract(f"{ARCHIVE_YEAR}_PM25_1g.xlsx", d)
            series = archive_series(read_xlsx(sheet, 0), SEASON_FIRST, API_FIRST - timedelta(hours=1))
        files = [f"archive/{ARCHIVE_YEAR}.zip", "api/stations.json"]
        for _, sensor in self.pm25_sensors():
            pages, rels = self.api_pages(sensor)
            code, rows = api_rows(pages)
            if not code or not code.endswith("-1g"):
                continue
            for i, page in enumerate(pages):  # (raw file, hours on it) so only pages of the chosen week are cited
                stamps = [api_hour(r["Data"]) for r in page.get("Lista archiwalnych wyników pomiarów") or []
                          if r.get("Data")]
                files.append((rels[i], set(stamps)))
            st = station_code(code)
            dest = series.setdefault(st, {})
            for h, v in rows.items():
                if API_FIRST <= h <= SEASON_LAST:
                    dest.setdefault(h, v)
        return {k: v for k, v in series.items() if v}, files

    def process(self) -> dict:
        series, files = self.season_series()
        archive_files_used = [f for f in files if isinstance(f, str)]
        hours = season_hours()
        means = national_means(series, hours)
        ranked = rank_weeks(hours, means)
        if not ranked:
            raise RuntimeError("no 7-day window with enough data")
        mean, first, _ = ranked[0]
        week = [first + timedelta(hours=i) for i in range(WEEK_HOURS)]
        meta = self.station_meta()
        points, missing = [], []
        for code in sorted(series):
            vals = [series[code].get(h) for h in week]
            if all(v is None for v in vals):
                continue
            st = meta.get(code) or meta.get(code[:-3] if code.endswith("MOB") else code + "MOB")
            if st is None:
                old = [m for m in meta.values() if code in re.split(r"[\s,;]+", m.get("_old") or "")]
                st = old[0] if len(old) == 1 else None
            if st is None or st.get("lon") is None or st.get("lat") is None:
                missing.append(code)
                continue
            got = [v for v in vals if v is not None]
            points.append({
                "id": f"gios_{code}", "name": st.get("name") or code, "kind": "air_station",
                "lon": round(st["lon"], 5), "lat": round(st["lat"], 5),
                "props": {"station_code": code, "city": st.get("city"), "voivodeship_code": st.get("voivodeship"),
                          "pm25": [None if v is None else round(v, 1) for v in vals],
                          "hours_with_data": len(got), "max": round(max(got), 1), "mean": round(sum(got) / len(got), 1)},
            })
        daily = []
        for d in range(len(hours) // 24):
            vals = [m for m in means[d * 24:(d + 1) * 24] if m is not None]
            daily.append(round(sum(vals) / len(vals), 1) if vals else None)
        start = first - timedelta(hours=1)
        end = week[-1]
        notes = [
            f"Season {SEASON_FIRST - timedelta(hours=1):%Y-%m-%d} to {SEASON_LAST - timedelta(hours=1):%Y-%m-%d}: "
            f"{len(series)} automatic PM2.5 stations. December {ARCHIVE_YEAR} from the GIOS archive file "
            f"'Wyniki pomiarów z {ARCHIVE_YEAR} roku'; January and February {API_FIRST.year} from the GIOS API "
            "(archivalData/getDataBySensor).",
            "Smog week: of every 7-day window starting at midnight, the one with the highest mean of the hourly "
            "national means (mean over the stations reporting each hour).",
            f"Chosen: {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} (UTC+1), national mean {mean:.1f} ug/m3.",
            "Runners-up: " + "; ".join(f"{h - timedelta(hours=1):%Y-%m-%d} {m:.1f}" for m, h, _ in ranked[1:5]) + ".",
            "GIOS times are UTC+1 all year; a value stamped hh:00 is the mean of the hour that ends then. "
            "Point props.pm25[i] is the hour starting at week_start + i hours.",
            "GIOS: data are not verified in real time and may change.",
        ]
        if missing:
            notes.append(f"Stations left out (no coordinates): {', '.join(missing)}")
        return {
            "vintage": f"GIOS hourly PM2.5, smog week {start:%Y-%m-%d} to {end - timedelta(hours=1):%Y-%m-%d}, "
                       f"{len(points)} stations",
            "week": {"start": f"{start:%Y-%m-%dT%H:%M}+01:00", "hours": WEEK_HOURS, "national_mean": round(mean, 1),
                     "national_hourly": [None if m is None else round(m, 1)
                                         for m in means[hours.index(first):hours.index(first) + WEEK_HOURS]],
                     "ranking": [{"start": f"{h - timedelta(hours=1):%Y-%m-%d}", "mean": round(m, 1)}
                                 for m, h, _ in ranked[:10]]},
            "season": {"first_day": f"{SEASON_FIRST - timedelta(hours=1):%Y-%m-%d}", "stations": len(series),
                       "daily_national_mean": daily},
            "points": points,
            "notes": notes,
            # The per-sensor API requests stay in data/raw/pl_air_hourly/manifest.json; the bibliography (loaded on
            # every page) cites the archive, the station list and the endpoint pattern in the description.
            "_files": ["archive/archives.html", *archive_files_used, "archive/metadane.xlsx"],
        }

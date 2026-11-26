"""GIOS air quality: annual mean PM2.5, PM10 and benzo(a)pyrene per measuring station.

Source: the Chief Inspectorate of Environmental Protection (GIOS) bank of measurement data
(powietrze.gios.gov.pl/pjp/archives): "Statystyki z lat 2000-<year>" (one sheet per pollutant,
one row per station, pollutant and averaging time) and "Metadane oraz kody stacji i stanowisk
pomiarowych" (station codes, names, type and WGS84 coordinates). File ids change when GIOS
updates the archive, so fetch() reads them from the archive page by their titles.

A station can report the same pollutant twice in a year (automatic 1-hour and gravimetric
24-hour samplers). The row with the higher data completeness is kept; on a tie the 24-hour
(reference) row. Completeness is kept in the point's props so a builder can grey out short
series. GIOS publishes modelled annual means only as a grid in an ArcGIS map service, not per
gmina or powiat, so no gmina table is made here.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.source import Source, SourceInfo
from ._resource_util import xlsx_rows
from .pl_soc_common import num, slug, voivodeship_code

ARCHIVE = "https://powietrze.gios.gov.pl/pjp/archives"
DOWNLOAD = "https://powietrze.gios.gov.pl/pjp/archives/downloadFile/{id}"
# field -> (sheet slug, unit)
POLLUTANTS = {"pm25": ("pm2_5", "ug/m3"), "pm10": ("pm10", "ug/m3"), "bap": ("bap_pm10", "ng/m3")}
OLD_CODE = "stary_kod_stacji_o_ile_inny_od_aktualnego"
LABELS = {"pm25": "PM2.5 annual mean", "pm10": "PM10 annual mean", "bap": "Benzo(a)pyrene in PM10, annual mean"}


def archive_files(html: str) -> dict[str, str]:
    """Archive page -> {file title: download id} (the title sits in the <p> after each link)."""
    out = {}
    for m in re.finditer(r'downloadFile/(\d+)"[^<]*>.*?archive_file_name">([^<]+)<', html, re.S):
        out[" ".join(m.group(2).split())] = m.group(1)
    return out


def pick_stats(html: str) -> tuple[int, str, str]:
    """(newest statistics year, its file id, station metadata file id)."""
    files = archive_files(html)
    stats = [(int(m.group(1)), fid) for t, fid in files.items() if (m := re.fullmatch(r"Statystyki z lat 2000-(\d{4})", t))]
    meta = [fid for t, fid in files.items() if t.startswith("Metadane oraz kody stacji")]
    if not stats or not meta:
        raise RuntimeError("GIOS archive page: statistics or metadata file not found")
    year, fid = max(stats)
    return year, fid, meta[0]


def _records(path: Path, sheet: str):
    """Rows of a sheet as {slug(header): text}; the header is the first row."""
    header = None
    for row in xlsx_rows(path, sheet):
        if header is None:
            header = {col: slug(text) for col, text in row.items()}
            continue
        yield {header[c]: v for c, v in row.items() if c in header}


def _sheet_names(path: Path) -> list[str]:
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    return [s.get("name") for s in wb.iter(ns + "sheet")]


def best_rows(rows: list[dict], year: int) -> dict[str, dict]:
    """Station code -> chosen row for `year` (higher completeness, then 24-hour)."""
    best: dict[str, dict] = {}
    for r in rows:
        if r.get("rok") != str(year) or num(r.get("srednia")) is None:
            continue
        code = r["kod_stacji"]
        key = (num(r.get("kompletnosc")) or 0.0, 1 if r.get("czas_usredniania") == "24g" else 0)
        if code not in best or key > best[code][0]:
            best[code] = (key, r)
    return {c: r for c, (k, r) in best.items()}


def find_station(code: str, stations: dict[str, dict]) -> dict | None:
    """Metadata row for a statistics station code: exact, then with/without the 'MOB' (mobile)
    suffix, then the old-code column. None when no single station matches."""
    if code in stations:
        return stations[code]
    alt = code[:-3] if code.endswith("MOB") else code + "MOB"
    if alt in stations:
        return stations[alt]
    old = [r for r in stations.values() if code in re.split(r"[\s,;]+", r.get(OLD_CODE, "") or "")]
    return old[0] if len(old) == 1 else None


class PlSocAir(Source):
    info = SourceInfo(
        id="pl_soc_air",
        title="Air quality: annual means of PM2.5, PM10 and benzo(a)pyrene by station",
        publisher="Główny Inspektorat Ochrony Środowiska (GIOŚ)",
        homepage="https://powietrze.gios.gov.pl/pjp/archives",
        license="Public information (State Environmental Monitoring); cite as GIOS",
        description="Annual mean concentrations of fine dust (PM2.5), PM10 and benzo(a)pyrene at every "
        "measuring station of the State Environmental Monitoring network, with station coordinates.",
        used_for=["Air quality lens", "Land advisor"],
    )

    def _ids(self, force=False):
        page = self.download(ARCHIVE, "archives.html", force=force)
        return pick_stats(Path(page).read_text(encoding="utf-8", errors="replace"))

    def fetch(self, force=False):
        year, fid, mid = self._ids(force=force)
        self.download(DOWNLOAD.format(id=fid), f"statystyki_2000_{year}.xlsx", force=force, expect_binary=True)
        self.download(DOWNLOAD.format(id=mid), "metadane_stacje.xlsx", force=force, expect_binary=True)

    def process(self):
        year, _, _ = self._ids()
        stats_path = self.raw_dir / f"statystyki_2000_{year}.xlsx"
        meta_path = self.raw_dir / "metadane_stacje.xlsx"
        sheets = {slug(s): s for s in _sheet_names(stats_path)}
        values: dict[str, dict] = {}
        for field, (sheet_slug, unit) in POLLUTANTS.items():
            rows = best_rows(list(_records(stats_path, sheets[sheet_slug])), year)
            for code, r in rows.items():
                v = values.setdefault(code, {})
                v[field] = round(num(r["srednia"]), 2)
                v[field + "_completeness"] = round(num(r.get("kompletnosc")) or 0, 1)
                v[field + "_averaging"] = r.get("czas_usredniania")
        stations = {r["kod_stacji"]: r for r in _records(meta_path, "STACJE") if r.get("kod_stacji")}
        points, missing, aliased = [], [], []
        for code in sorted(values):
            st = find_station(code, stations)
            if st is not None and st["kod_stacji"] != code:
                aliased.append(f"{code}={st['kod_stacji']}")
            lat = num(st.get("wgs84_n")) if st else None
            lon = num(st.get("wgs84_e")) if st else None
            if st is None or lat is None or lon is None:
                missing.append(code)
                continue
            props = {"station_code": code, "city": st.get("miejscowosc"), "address": st.get("adres"),
                     "station_type": st.get("typ_stacji"), "area_type": st.get("typ_obszaru"),
                     "voivodeship_code": voivodeship_code(st.get("wojewodztwo")), "year": year}
            for f in POLLUTANTS:
                props[f] = values[code].get(f)
                if f in values[code]:
                    props[f + "_completeness"] = values[code][f + "_completeness"]
                    props[f + "_averaging"] = values[code][f + "_averaging"]
            points.append({"id": f"gios_{code}", "name": st.get("nazwa_stacji") or code, "kind": "air_station",
                           "lon": round(lon, 5), "lat": round(lat, 5), "props": props})
        counts = {f: sum(1 for p in points if p["props"][f] is not None) for f in POLLUTANTS}
        notes = [
            f"GIOS statistics {year} (annual means): stations with PM2.5 {counts['pm25']}, PM10 {counts['pm10']}, "
            f"benzo(a)pyrene {counts['bap']}.",
            "Point props: " + "; ".join(f"{f} = {LABELS[f]} {year} ({POLLUTANTS[f][1]})" for f in POLLUTANTS)
            + ". A station without a pollutant -> null.",
            "Where a station has both 1-hour (automatic) and 24-hour (gravimetric) series, the one with higher "
            "completeness is kept (24-hour on a tie); <pollutant>_completeness is the % of the year covered.",
            "No gmina or powiat table: GIOS publishes modelled annual means only as a grid map service.",
        ]
        if aliased:
            notes.append("Statistics codes matched to metadata codes by the 'MOB' (mobile) suffix or the old code: "
                         + ", ".join(aliased))
        if missing:
            notes.append(f"Stations with {year} values but no coordinates in the metadata (left out): {', '.join(missing)}")
        return {
            "vintage": f"GIOS annual statistics {year}",
            "points": points,
            "notes": notes,
            "_files": ["archives.html", stats_path.name, meta_path.name],
        }

"""Air routes from Polish airports: monthly passengers per airport pair (Eurostat avia_par_pl).

Eurostat publishes the routes data Poland reports under Regulation (EC) 437/2003: passengers carried
(arrivals plus departures) between each main Polish airport and each partner airport, per month. We keep
the newest 12 months that have data. Positions and names of both ends come from OurAirports
(public domain, Unlicense).

ULC (the Polish Civil Aviation Authority) publishes newer quarterly figures only as PDF tables per foreign
city, not per airport pair, behind a bot-protection page, so they are not used.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import time
import urllib.error
import urllib.parse

from ..core.source import Source, SourceInfo
from .pl_transport_airports import AIRPORTS
from .pl_transport_util import eurostat_get, jsonstat_cells, jsonstat_labels

OA_AIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OA_COUNTRIES = "https://davidmegginson.github.io/ourairports-data/countries.csv"
MONTHS = 12
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
# Each airport by ICAO code (P239): its own English and Polish label, and the place it serves (P931).
AIRPORT_QUERY = """SELECT ?icao ?airport ?closed ?aen ?apl ?city ?en ?pl ?pop WHERE {
  VALUES ?icao { %s }
  ?airport wdt:P239 ?icao.
  OPTIONAL { ?airport wdt:P576 ?closed }
  OPTIONAL { ?airport rdfs:label ?aen FILTER(lang(?aen) = "en") }
  OPTIONAL { ?airport rdfs:label ?apl FILTER(lang(?apl) = "pl") }
  OPTIONAL {
    ?airport wdt:P931 ?city.
    OPTIONAL { ?city rdfs:label ?en FILTER(lang(?en) = "en") }
    OPTIONAL { ?city rdfs:label ?pl FILTER(lang(?pl) = "pl") }
    OPTIONAL { ?city wdt:P1082 ?pop }
  }
}"""
# Wikidata links ICAO EDDB to the closed Schoenefeld airport; Eurostat avia_par_pl names the EDDB partner
# "BERLIN-BRANDENBURG airport" (the code passed to the new airport in 2020).
LABEL_FIX = {"EDDB": {"label": "Berlin Brandenburg", "label_pl": "Berlin-Brandenburg"}}
EN_SUFFIXES = (" International Airport", " Airport", " Airfield")
PL_PREFIXES = ("Międzynarodowy port lotniczy ", "Port lotniczy ", "Lotnisko ")

# Eurostat country codes that differ from ISO 3166-1 alpha-2.
EUROSTAT_ISO = {"UK": "GB", "EL": "GR"}


def last_months(values_by_month: dict[str, float], n: int = MONTHS) -> list[str]:
    """The newest `n` consecutive months ending at the newest month with any value ('YYYY-MM')."""
    have = sorted(m for m, v in values_by_month.items() if v)
    if not have:
        return []
    y, m = map(int, have[-1].split("-"))
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def clean_city(text: str | None) -> str | None:
    """OurAirports municipality without the district part: 'Paris (Roissy-en-France, Val-d'Oise)' -> 'Paris',
    'Luton, Luton' -> 'Luton'."""
    text = (text or "").split("(")[0].split(",")[0].strip()
    return text or None


def short_label(text: str | None, lang: str) -> str | None:
    """'Milan Malpensa Airport' -> 'Milan Malpensa'; 'Port lotniczy Mediolan-Malpensa' -> 'Mediolan-Malpensa'."""
    text = (text or "").strip()
    if lang == "en":
        for suf in EN_SUFFIXES:
            if text.endswith(suf) and len(text) > len(suf):
                text = text[: -len(suf)].strip()
                break
    else:
        for pre in PL_PREFIXES:
            if text.lower().startswith(pre.lower()) and len(text) > len(pre):
                text = text[len(pre):].strip()
                break
    return text or None


def wikidata_airports(doc: dict) -> dict[str, dict]:
    """SPARQL rows -> {ICAO: {qid, label, label_pl, city, city_pl}}. Several entities for one code: one without
    a dissolution date (P576) wins, then the lowest QID number; several served places: the most populous one."""
    best: dict[str, tuple[tuple[int, int], float, dict]] = {}
    for b in doc.get("results", {}).get("bindings", []):
        icao = b["icao"]["value"]
        qid = b["airport"]["value"].rsplit("/", 1)[-1]
        qnum = (1 if "closed" in b else 0, int(qid[1:]) if qid[1:].isdigit() else 1 << 40)
        try:
            pop = float(b.get("pop", {}).get("value", "nan"))
        except ValueError:
            pop = float("nan")
        pop = -1.0 if pop != pop else pop
        row = {"qid": qid, "label": short_label(b.get("aen", {}).get("value"), "en"),
               "label_pl": short_label(b.get("apl", {}).get("value"), "pl"),
               "city": b.get("en", {}).get("value"), "city_pl": b.get("pl", {}).get("value")}
        cur = best.get(icao)
        if cur is None or qnum < cur[0] or (qnum == cur[0] and pop > cur[1]):
            best[icao] = (qnum, pop, row)
    return {k: v[2] for k, v in best.items()}


def parse_pair(code: str) -> tuple[str, str, str] | None:
    """'PL_EPWA_TR_LTAI' -> ('EPWA', 'TR', 'LTAI')."""
    parts = code.split("_")
    if len(parts) != 4 or parts[0] != "PL":
        return None
    return parts[1], EUROSTAT_ISO.get(parts[2], parts[2]), parts[3]


class PlAirRoutes(Source):
    info = SourceInfo(
        id="pl_air_routes",
        title="Air routes from Polish airports: passengers per month",
        publisher="Eurostat; OurAirports; Wikidata",
        homepage="https://ec.europa.eu/eurostat/databrowser/view/avia_par_pl/default/table",
        license="Eurostat: CC BY 4.0 (Commission Decision 2011/833/EU), credit Eurostat and state changes. "
        "OurAirports: public domain (Unlicense). Wikidata: CC0.",
        description="Passengers carried each month between each main Polish airport and each partner airport, "
        "with the position of both airports.",
        used_for=["Flights layer"],
    )

    ROUTES = "avia_par_pl_monthly.json"
    OA = "ourairports_airports.csv"
    OA_C = "ourairports_countries.csv"
    WD = "wikidata_airports.json"

    def _since(self) -> str:
        return f"{dt.date.today().year - 3}-01"

    def fetch(self, force=False):
        eurostat_get(self, "avia_par_pl", self.ROUTES, force=force, freq="M", unit="PAS", tra_meas="PAS_CRD",
                     sinceTimePeriod=self._since())
        self.download(OA_AIRPORTS, self.OA, force=force)
        self.download(OA_COUNTRIES, self.OA_C, force=force)
        for attempt in range(4):  # the query service answers 429 when busy; core.fetch does not retry 4xx
            try:
                self.download(self._wd_url(), self.WD, force=force,
                              headers={"Accept": "application/sparql-results+json"})
                break
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code != 429 or attempt == 3:
                    raise
                time.sleep(65 * (attempt + 1))

    def _codes(self) -> list[str]:
        doc = json.loads((self.raw_dir / self.ROUTES).read_text(encoding="utf-8"))
        codes = set()
        for pair in doc["dimension"]["airp_pr"]["category"]["index"]:
            parsed = parse_pair(pair)
            if parsed:
                codes.update((parsed[0], parsed[2]))
        return sorted(codes)

    def _wd_url(self) -> str:
        values = " ".join(f'"{c}"' for c in self._codes())
        return WIKIDATA_SPARQL + "?" + urllib.parse.urlencode({"query": AIRPORT_QUERY % values, "format": "json"})

    def process(self):
        doc = json.loads((self.raw_dir / self.ROUTES).read_text(encoding="utf-8"))
        ids, cells = jsonstat_cells(doc)
        pos = {d: ids.index(d) for d in ids}
        labels = jsonstat_labels(doc, "airp_pr")
        series: dict[str, dict[str, float]] = {}
        total_by_month: dict[str, float] = {}
        for key, v in cells.items():
            if v is None or key[pos["tra_meas"]] != "PAS_CRD" or key[pos["unit"]] != "PAS":
                continue
            pair, month = key[pos["airp_pr"]], key[pos["time"]]
            series.setdefault(pair, {})[month] = v
            total_by_month[month] = total_by_month.get(month, 0) + v
        months = last_months(total_by_month)
        if not months:
            raise RuntimeError("pl_air_routes: no monthly values in avia_par_pl")

        with open(self.raw_dir / self.OA, encoding="utf-8") as f:
            oa_rows = list(csv.DictReader(f))
        by_code: dict[str, dict] = {}
        for key in ("ident", "gps_code", "icao_code"):  # icao_code wins, then gps_code, then ident
            for r in oa_rows:
                if r.get(key):
                    by_code[r[key]] = r
        with open(self.raw_dir / self.OA_C, encoding="utf-8") as f:
            countries = {r["code"]: r["name"] for r in csv.DictReader(f)}
        wd = wikidata_airports(json.loads((self.raw_dir / self.WD).read_text(encoding="utf-8")))

        def airport(icao: str) -> dict:
            r = by_code.get(icao)
            w = {**(wd.get(icao) or {}), **LABEL_FIX.get(icao, {})}
            names = {"label": w.get("label"), "label_pl": w.get("label_pl"), "city": w.get("city"),
                     "city_pl": w.get("city_pl"), "wikidata": w.get("qid")}
            if not r:
                return {"icao": icao, "name": None, **names, "municipality": None, "country": None,
                        "country_name": None, "iata": None, "lon": None, "lat": None}
            return {
                "icao": icao, "name": r["name"] or None, **names, "municipality": clean_city(r["municipality"]),
                "country": r["iso_country"] or None, "country_name": countries.get(r["iso_country"]),
                "iata": r["iata_code"] or None,
                "lon": round(float(r["longitude_deg"]), 5), "lat": round(float(r["latitude_deg"]), 5),
            }

        routes, partners, missing = [], {}, []
        polish: dict[str, dict] = {}
        for pair in sorted(series):
            parsed = parse_pair(pair)
            if not parsed:
                continue
            pl, ctry, other = parsed
            values = [series[pair].get(m) for m in months]
            if not any(values):
                continue
            if pl not in polish:
                polish[pl] = airport(pl)
            if other not in partners:
                partners[other] = airport(other)
                if partners[other]["lon"] is None:
                    missing.append(other)
            routes.append({
                "from": pl, "to": other, "to_country": ctry, "domestic": ctry == "PL",
                "label": labels.get(pair), "passengers": values,
                "total": sum(v for v in values if v is not None),
            })

        points = []
        for icao, a in sorted(polish.items()):
            points.append({"id": f"airport:{icao}", "name": AIRPORTS.get(icao) or a["name"], "kind": "airport",
                           "lon": a["lon"], "lat": a["lat"], "props": {**a, "polish": True}})
        for icao, a in sorted(partners.items()):
            if icao in polish:
                continue
            points.append({"id": f"airport:{icao}", "name": a["name"], "kind": "partner_airport",
                           "lon": a["lon"], "lat": a["lat"], "props": {**a, "polish": False}})
        updated = (doc.get("updated") or "")[:10]
        total = sum(r["total"] for r in routes if not r["domestic"])
        return {
            "vintage": f"Eurostat avia_par_pl {months[0]} to {months[-1]} (data updated {updated})",
            "months": months,
            "unit": "passengers carried per month (arrivals plus departures)",
            "routes": routes,
            "points": points,
            "notes": [
                f"Months: {months[0]} to {months[-1]}, the newest 12 months in Eurostat avia_par_pl (passengers "
                f"carried, PAS_CRD, arrivals plus departures). Eurostat data update {updated}.",
                f"{len(routes)} airport pairs from {len(polish)} Polish airports to {len(partners)} partner airports. "
                f"International passengers in the period: {round(total):,}.",
                "Domestic pairs are reported by both Polish airports, so each domestic route appears twice "
                "(once from each end).",
                "A month without a value is null (Eurostat leaves out empty or confidential cells).",
                "Positions, names and countries of airports: OurAirports (public domain). Short English and Polish "
                "airport names and the place each airport serves (P931, the most populous when there are several): "
                "Wikidata (CC0), by ICAO code (P239).",
                "ULC publishes newer figures (2025) only as PDF tables per foreign city, without the Polish airport, "
                "so they are not used.",
            ] + [f"{icao}: not in OurAirports, no position" for icao in missing],
            "_files": [self.ROUTES, self.OA, self.OA_C, self.WD],
        }

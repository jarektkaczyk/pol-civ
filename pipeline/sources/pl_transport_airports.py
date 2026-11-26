"""Polish airports: passengers and freight (Eurostat), positions (OpenStreetMap), and the planned CPK hub.

The Civil Aviation Authority (ULC) publishes its airport statistics as PDFs behind a bot-protection
page that scripts cannot pass, so the figures come from Eurostat's airport tables, which Poland
reports under Regulation (EC) 437/2003:

* `avia_paoa` passengers carried (arrivals + departures), all flights;
* `avia_gooa` freight and mail loaded and unloaded, tonnes.

Positions are the centres of the OSM aerodromes with the airport's ICAO code.
"""

from __future__ import annotations

import json

from ..core.source import Source, SourceInfo
from .pl_transport_util import (
    ODBL_NOTE, POLAND_AREA, el_lonlat, eurostat_get, jsonstat_cells, osm_elements, osm_timestamp, overpass,
    wikidata_entities,
)

# ICAO -> display name. The selection rule: the brief's list of airports with scheduled traffic.
AIRPORTS = {
    "EPWA": "Warszawa-Chopin",
    "EPKK": "Kraków-Balice",
    "EPGD": "Gdańsk im. Lecha Wałęsy",
    "EPKT": "Katowice-Pyrzowice",
    "EPWR": "Wrocław-Strachowice",
    "EPPO": "Poznań-Ławica",
    "EPMO": "Warszawa-Modlin",
    "EPRZ": "Rzeszów-Jasionka",
    "EPSC": "Szczecin-Goleniów",
    "EPLL": "Łódź-Lublinek",
    "EPLB": "Lublin",
    "EPBY": "Bydgoszcz-Szwederowo",
    "EPSY": "Olsztyn-Mazury (Szczytno-Szymany)",
    "EPZG": "Zielona Góra-Babimost",
    "EPRA": "Warszawa-Radom",
}

# The planned hub. Status text is quoted from the official site; position from Wikidata (P625).
CPK = {
    "id": "cpk", "name": "Port Polska (CPK) hub airport", "qid": None, "status": "planned",
    "status_note": None, "opening_planned": None, "ref": None,
}

SINCE = 2023  # first year requested; the newest year in the answer is used

OSM_QUERY = (f'[out:json][timeout:120];{POLAND_AREA}'
             'nwr["aeroway"="aerodrome"]["icao"~"^EP"](area.pl);out center tags qt;')


def airport_values(doc: dict, measure: str, unit: str) -> tuple[dict[int, dict[str, float]], dict[str, str]]:
    """{year: {ICAO: value}} for Polish airports (rep_airp 'PL_EPxx'), total schedule and coverage."""
    ids, cells = jsonstat_cells(doc)
    pos = {d: ids.index(d) for d in ids}
    out: dict[int, dict[str, float]] = {}
    for key, v in cells.items():
        if v is None:
            continue
        if key[pos["tra_meas"]] != measure or key[pos["unit"]] != unit:
            continue
        if key[pos["schedule"]] != "TOTAL" or key[pos["tra_cov"]] != "TOTAL":
            continue
        airp = key[pos["rep_airp"]]
        if not airp.startswith("PL_"):
            continue
        out.setdefault(int(key[pos["time"]]), {})[airp[3:]] = v
    labels = doc["dimension"]["rep_airp"]["category"].get("label", {})
    return out, {k[3:]: v for k, v in labels.items() if k.startswith("PL_")}


class PlTransportAirports(Source):
    info = SourceInfo(
        id="pl_transport_airports",
        title="Airports of Poland: passengers and freight (Eurostat), positions (OpenStreetMap)",
        publisher="Eurostat (air transport statistics reported by Poland); OpenStreetMap contributors",
        homepage="https://ec.europa.eu/eurostat/web/transport/database",
        license="Eurostat: free re-use with attribution. OSM positions: ODbL 1.0. " + ODBL_NOTE,
        description="Passengers carried and freight and mail handled at Poland's airports in the newest full "
        "year, and the planned Port Polska (CPK) hub.",
        used_for=["Airports on the map (sized by passengers)", "Commerce advisor"],
    )

    PAX = "avia_paoa.json"
    FRT = "avia_gooa.json"
    OSM = "osm_aerodromes.json"
    WD = "wikidata.json"

    def fetch(self, force=False):
        eurostat_get(self, "avia_paoa", self.PAX, force=force, freq="A", unit="PAS", tra_meas="PAS_CRD",
                     schedule="TOTAL", tra_cov="TOTAL", sinceTimePeriod=SINCE)
        eurostat_get(self, "avia_gooa", self.FRT, force=force, freq="A", unit="T", tra_meas="FRM_LD_NLD",
                     schedule="TOTAL", tra_cov="TOTAL", sinceTimePeriod=SINCE)
        overpass(self, OSM_QUERY, self.OSM, force=force)
        if CPK["qid"]:
            wikidata_entities(self, [CPK["qid"]], self.WD, force=force)

    def process(self):
        pax, labels = airport_values(json.loads((self.raw_dir / self.PAX).read_text(encoding="utf-8")),
                                     "PAS_CRD", "PAS")
        frt, _ = airport_values(json.loads((self.raw_dir / self.FRT).read_text(encoding="utf-8")),
                                "FRM_LD_NLD", "T")
        year = max(y for y, v in pax.items() if v)
        fyear = max(y for y, v in frt.items() if v)
        osm = osm_elements([self.raw_dir / self.OSM])
        where = {}
        for el in osm:
            icao = (el.get("tags") or {}).get("icao")
            if icao in AIRPORTS and el_lonlat(el):
                where[icao] = (el_lonlat(el), el)
        points, notes = [], []
        for icao, name in AIRPORTS.items():
            ll, el = where.get(icao, (None, None))
            if ll is None:
                notes.append(f"{icao}: no OSM aerodrome with this ICAO code; no position")
            p = pax.get(year, {}).get(icao)
            if p is None:
                notes.append(f"{icao} {name}: not in Eurostat avia_paoa {year} (passengers null)")
            points.append({
                "id": f"airport:{icao}", "name": name, "kind": "airport",
                "lon": round(ll[0], 5) if ll else None, "lat": round(ll[1], 5) if ll else None,
                "props": {
                    "icao": icao, "iata": (el.get("tags") or {}).get("iata") if el else None,
                    "eurostat_name": labels.get(icao),
                    "passengers": p, "passengers_prev": pax.get(year - 1, {}).get(icao), "passengers_year": year,
                    "freight_t": frt.get(fyear, {}).get(icao), "freight_year": fyear,
                    "status": "operating", "osm_id": f"{el['type']}/{el['id']}" if el else None,
                },
            })
        points.sort(key=lambda pt: -(pt["props"]["passengers"] or 0))
        if CPK["qid"]:
            ent = wikidata_entities(self, [CPK["qid"]], self.WD).get(CPK["qid"], {})
            ll = ent.get("lonlat")
            points.append({
                "id": "airport:CPK", "name": CPK["name"], "kind": "airport_planned",
                "lon": round(ll[0], 5) if ll else None, "lat": round(ll[1], 5) if ll else None,
                "props": {"status": CPK["status"], "status_note": CPK["status_note"],
                          "opening_planned": CPK["opening_planned"], "passengers": None, "ref": CPK["ref"],
                          "wikidata": CPK["qid"]},
            })
        stamp = osm_timestamp([self.raw_dir / self.OSM])
        total = sum(v for v in pax.get(year, {}).values() if v)
        files = [self.PAX, self.FRT, self.OSM] + ([self.WD] if CPK["qid"] else [])
        return {
            "vintage": f"Eurostat airport traffic {year}",
            "tables": {"airports_country": {
                "level": "country",
                "fields": {"passengers": {"label": "Passengers carried at Polish airports in Eurostat", "unit": "persons",
                                          "year": year, "note": "sum of the reporting airports (avia_paoa)"}},
                "rows": {"PL": {"passengers": total or None}},
            }},
            "points": points,
            "notes": [
                "Rule: the airports with scheduled passenger traffic named in the brief, plus the planned CPK hub.",
                f"Passengers: Eurostat avia_paoa PAS_CRD (passengers carried, arrivals plus departures, all flights), "
                f"{year}; previous year in passengers_prev. Freight: avia_gooa FRM_LD_NLD (freight and mail loaded "
                f"and unloaded, tonnes), {fyear}.",
                "ULC statistics (ulc.gov.pl) could not be fetched by script (bot-protection page); Eurostat carries the "
                "airport data Poland reports under Regulation (EC) 437/2003. Small airports below Eurostat's reporting "
                "threshold have null traffic.",
                "Olsztyn-Mazury airport is at Szymany near Szczytno (ICAO EPSY); the brief's 'Szczytno' is this airport.",
                f"Positions: OSM aerodrome centres (extract {stamp}). {ODBL_NOTE}",
            ] + notes,
            "_files": files,
        }

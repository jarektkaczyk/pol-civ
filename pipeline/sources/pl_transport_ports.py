"""Polish seaports: cargo tonnage and containers, plus the LNG terminals.

* GUS, "Gospodarka morska w Polsce w 2025 r." (news release, tables xlsx): cargo traffic in the five
  main seaports (Gdańsk, Gdynia, Szczecin, Świnoujście, Police) and transit cargo, thousand tonnes,
  preliminary 2025 data.
* Eurostat `mar_go_am_pl` (annual gross weight of goods handled in main ports, Poland): the same five
  ports, final figures, as a cross-check.
* Eurostat `mar_go_qm_c2026` (containers handled in main ports, quarterly, 2025-2026): TEU per port,
  the four quarters of the newest full year summed.
* Small ports (Elbląg, Kołobrzeg, Darłowo, Ustka, Władysławowo) and the LNG terminals are curated
  (SMALL_PORTS, LNG) with the page each figure comes from.

Positions come from Wikidata (P625) by QID.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections import defaultdict

from ..core.source import Source, SourceInfo
from ._resource_util import download_checked, num, xlsx_rows
from .pl_transport_util import curated_points, eurostat_get, jsonstat_cells, wikidata_entities

GUS_PAGE = ("https://stat.gov.pl/obszary-tematyczne/transport-i-lacznosc/transport/"
            "gospodarka-morska-w-polsce-w-2025-r-,7,23.html")
GUS_XLSX = ("https://publikacje.new.stat.gov.pl/sites/default/files/2026-04/"
            "maritime_economy_in_Poland_in_2025_tables.xlsx")
GUS_YEAR = 2025
TEU_DATASET = "mar_go_qm_c2026"  # Eurostat splits the quarterly container data into two-year datasets

RSGM_ZIP = ("https://stat.gov.pl/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5515/11/18/1/"
            "rocznikstatystycznygospodarkimorskiej2025tabliceexcel.zip")
RSGM_PAGE = ("https://stat.gov.pl/obszary-tematyczne/roczniki-statystyczne/roczniki-statystyczne/"
             "rocznik-statystyczny-gospodarki-morskiej-2025,11,18.html")
RSGM_MEMBER = "Tablice przegladowe.xlsx"  # Tabl. I: cargo traffic by port, 1990-2024

MAIN_PORTS = {  # GUS name -> (id, Eurostat rep_mar, display name, Wikidata QID, expected label word)
    "Gdańsk": ("PLGDN", "PL_0PLGDN", "Port of Gdańsk", "Q1567868", "Gda"),
    "Gdynia": ("PLGDY", "PL_0PLGDY", "Port of Gdynia", "Q4352784", "Gdyn"),
    "Szczecin": ("PLSZZ", "PL_0PLSZZ", "Port of Szczecin", "Q4350543", "Szczecin"),
    "Świnoujście": ("PLSWI", "PL_0PLSWI", "Port of Świnoujście", "Q7231308", "winouj"),
    "Police": ("PLPLC", "PL_0PLPLC", "Port of Police", "Q960455", "Police"),
}

# Small ports. GUS splits cargo out only for Kołobrzeg among them (yearbook Tabl. I, read in process()).
SMALL_PORTS: list[dict] = [
    {"id": f"port:{pid}", "name": f"Port of {name}", "kind": "seaport", "qid": qid, "expect": expect,
     "port": name, "class": "small", "cargo_kt": None, "cargo_year": None, "teu": None, "ref": RSGM_PAGE}
    for pid, name, qid, expect in [
        ("PLKOL", "Kołobrzeg", "Q7231177", "Ko"), ("PLELB", "Elbląg", "Q11824135", "Elbl"),
        ("PLDAR", "Darłowo", "Q11824128", "Dar"), ("PLUST", "Ustka", "Q11824168", "Ustk"),
        ("PLWLA", "Władysławowo", "Q11824171", "adys"),
    ]
]

# LNG import terminals.
LNG: list[dict] = [
    {"id": "lng:swinoujscie", "name": "LNG terminal Świnoujście", "kind": "lng_terminal", "qid": "Q9357429",
     "expect": "LNG", "operator": "Gaz-System", "status": "operating", "capacity_bcm": 8.3,
     "status_note": "regasification capacity 8.3 bcm a year after the expansion, in effect since 1 January 2025",
     "ref": "https://www.lngindustry.com/regasification/24012025/gaz-system-completes-winoujcie-lng-terminal-"
            "expansion"},
    {"id": "lng:fsru_gdansk", "name": "FSRU terminal Gdańsk", "kind": "lng_terminal_planned", "qid": None,
     "lonlat": None, "operator": "Gaz-System", "status": "under_construction", "capacity_bcm": None,
     "status_note": "Floating terminal (vessel 'Solidarity', built by HD Hyundai); regasification to start in the "
                    "first quarter of 2028; capacity above 6 bcm a year. No published position: null.",
     "ref": "https://www.bairdmaritime.com/amp/story/offshore/vessels-rigs/fposfpsos/korean-builder-launches-"
            "gaz-systems-new-fsru"},
]


def gus_port_table(rows) -> dict[str, dict[str, float | None]]:
    """GUS Table 1 rows -> {port: {cargo_kt, cargo_index_prev, international_kt, unloading_kt, loading_kt}}."""
    out = {}
    for r in rows:
        name = (r.get("A") or "").strip()
        if name in MAIN_PORTS or name == "TOTAL":
            out[name] = {"cargo_kt": num(r.get("B")), "cargo_index_prev": num(r.get("D")),
                         "international_kt": num(r.get("E")), "unloading_kt": num(r.get("F")),
                         "loading_kt": num(r.get("G"))}
    return out


def yearbook_port(rows, port: str) -> tuple[int | None, float | None]:
    """(newest year, cargo kt) for `port` in the yearbook's Tabl. I (first row named after the port)."""
    years: dict[str, int] = {}
    for r in rows:
        if not years and sum(1 for v in r.values() if re.fullmatch(r"(19|20)\d\d", v or "")) >= 5:
            years = {c: int(v) for c, v in r.items() if re.fullmatch(r"(19|20)\d\d", v or "")}
            continue
        if years and (r.get("B") or "").strip() == port:
            col = max(years, key=years.get)
            return years[col], num(r.get(col))
    return None, None


def gus_transit_table(rows) -> dict[str, float | None]:
    return {(r.get("A") or "").strip(): num(r.get("B")) for r in rows if (r.get("A") or "").strip() in MAIN_PORTS}


def eurostat_by_port(doc: dict) -> tuple[int, dict[str, float]]:
    ids, cells = jsonstat_cells(doc)
    ri, ti = ids.index("rep_mar"), ids.index("time")
    by_year: dict[int, dict[str, float]] = defaultdict(dict)
    for k, v in cells.items():
        if v is not None:
            by_year[int(k[ti])][k[ri]] = v
    year = max(by_year)
    return year, by_year[year]


def teu_by_port(doc: dict) -> tuple[int | None, dict[str, float]]:
    """Sum the four quarters of the newest year that has all four, per port."""
    ids, cells = jsonstat_cells(doc)
    ri, ti = ids.index("rep_mar"), ids.index("time")
    q: dict[int, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for k, v in cells.items():
        if v is None:
            continue
        year, quarter = k[ti].split("-")
        q[int(year)][k[ri]][quarter] = v
    full = [y for y, ports in q.items() if any(len(qs) == 4 for qs in ports.values())]
    if not full:
        return None, {}
    year = max(full)
    return year, {p: sum(qs.values()) for p, qs in q[year].items() if len(qs) == 4}


class PlTransportPorts(Source):
    info = SourceInfo(
        id="pl_transport_ports",
        title="Seaports of Poland: cargo tonnage and containers, LNG terminals",
        publisher="Statistics Poland (GUS); Eurostat; port authorities and Gaz-System (curated items)",
        homepage=GUS_PAGE,
        license="GUS and Eurostat: free re-use with attribution. Curated figures: public pages (see ref).",
        description="Cargo handled in Polish seaports in 2025 (thousand tonnes), container throughput (TEU) and "
        "the LNG terminals at Świnoujście and Gdańsk.",
        used_for=["Ports on the map (sized by tonnage)", "Commerce advisor", "Energy advisor (LNG)"],
    )

    GUS = "gus_maritime_2025_tables.xlsx"
    RSGM = "rsgm_2025_tables.zip"
    RSGM_X = "rsgm_2025_tablice_przegladowe.xlsx"
    EST = "mar_go_am_pl.json"
    TEU = "mar_go_qm_c2026_teu.json"
    WD = "wikidata.json"

    def _qids(self):
        q = [v[3] for v in MAIN_PORTS.values() if v[3]]
        q += [it["qid"] for it in SMALL_PORTS + LNG if it.get("qid")]
        return q

    def fetch(self, force=False):
        if not download_checked(self, GUS_XLSX, self.GUS, force=force, magic=b"PK"):
            raise RuntimeError(f"GUS tables not available at {GUS_XLSX}")
        eurostat_get(self, "mar_go_am_pl", self.EST, force=force, direct="TOTAL", par_mar="TOTAL", cargo="TOTAL",
                     natvessr="TOTAL", unit="THS_T", rep_mar=[v[1] for v in MAIN_PORTS.values()], lastTimePeriod=2)
        eurostat_get(self, TEU_DATASET, self.TEU, force=force, par_mar="TOTAL", direct="TOTAL", cargo="TOTAL",
                     loadstat="TOTAL", unit="TEU", rep_mar=[v[1] for v in MAIN_PORTS.values()], lastTimePeriod=8)
        zpath = self.download(RSGM_ZIP, self.RSGM, force=force, expect_binary=True)
        out = self.raw_dir / self.RSGM_X
        if force or not out.exists():
            with zipfile.ZipFile(zpath) as z:
                member = next(n for n in z.namelist() if n.endswith(RSGM_MEMBER))
                out.write_bytes(z.read(member))
        if self._qids():
            wikidata_entities(self, self._qids(), self.WD, force=force)

    def process(self):
        gus_path = self.raw_dir / self.GUS
        t1 = gus_port_table(xlsx_rows(gus_path, "Table 1"))
        t4 = gus_transit_table(xlsx_rows(gus_path, "Table 4"))
        if set(t1) != set(MAIN_PORTS) | {"TOTAL"}:
            raise ValueError(f"GUS Table 1: ports found {sorted(t1)}")
        e_year, est = eurostat_by_port(json.loads((self.raw_dir / self.EST).read_text(encoding="utf-8")))
        teu_year, teu = teu_by_port(json.loads((self.raw_dir / self.TEU).read_text(encoding="utf-8")))
        wd = wikidata_entities(self, self._qids(), self.WD) if self._qids() else {}
        items = []
        for gname, (pid, rep, disp, qid, expect) in MAIN_PORTS.items():
            g = t1[gname]
            items.append({
                "id": f"port:{pid}", "name": disp, "kind": "seaport", "qid": qid, "expect": expect,
                "port": gname, "class": "main", "unlocode": pid,
                "cargo_kt": g["cargo_kt"], "cargo_year": GUS_YEAR, "cargo_index_prev": g["cargo_index_prev"],
                "international_kt": g["international_kt"], "unloading_kt": g["unloading_kt"],
                "loading_kt": g["loading_kt"], "transit_kt": t4.get(gname),
                "cargo_kt_eurostat": est.get(rep), "cargo_year_eurostat": e_year,
                "teu": teu.get(rep), "teu_year": teu_year,
                "ref": GUS_PAGE,
            })
        k_year, k_val = yearbook_port(xlsx_rows(self.raw_dir / self.RSGM_X, "Tabl. I"), "Kołobrzeg")
        small = [dict(it) for it in SMALL_PORTS]
        for it in small:
            if it["port"] == "Kołobrzeg":
                it.update(cargo_kt=k_val, cargo_year=k_year)
        items += small + [dict(it) for it in LNG]
        points, problems = curated_points(items, wd)
        points.sort(key=lambda p: -(p["props"].get("cargo_kt") or 0))
        files = [self.GUS, self.EST, self.TEU, self.RSGM] + ([self.WD] if self._qids() else [])
        total = t1["TOTAL"]
        return {
            "vintage": f"GUS maritime economy {GUS_YEAR} (preliminary); Eurostat ports {e_year}; TEU {teu_year}",
            "tables": {"ports_country": {
                "level": "country",
                "fields": {"cargo_kt": {"label": "Cargo traffic in Polish seaports", "unit": "kt", "year": GUS_YEAR,
                                        "note": "GUS, preliminary"},
                           "international_kt": {"label": "of which international maritime traffic", "unit": "kt",
                                                "year": GUS_YEAR}},
                "rows": {"PL": {"cargo_kt": total["cargo_kt"], "international_kt": total["international_kt"]}},
            }},
            "points": points,
            "notes": [
                "Rule: the five main seaports reported by GUS and Eurostat, the small commercial ports named in the "
                "brief, and the LNG import terminals.",
                f"cargo_kt: GUS news release 'Gospodarka morska w Polsce w {GUS_YEAR} r.' Table 1 (preliminary), "
                "thousand tonnes; transit_kt from its Table 4; cargo_index_prev = previous year = 100.",
                f"cargo_kt_eurostat: Eurostat mar_go_am_pl {e_year} (gross weight of goods handled, all cargo, "
                "final), a cross-check.",
                f"teu: Eurostat {TEU_DATASET}, four quarters of {teu_year} summed (all containers, loaded and "
                "empty). Port authorities count TEU their own way and may publish slightly different totals.",
                f"Small ports: GUS publishes cargo for Kołobrzeg only (Rocznik Statystyczny Gospodarki Morskiej 2025, "
                f"Tabl. I, {k_year}); Elbląg, Darłowo, Ustka and Władysławowo have no published tonnage (null). The "
                "2025 news release gives the five main ports only.",
                "Port authorities count cargo their own way: the Port of Gdańsk Authority reports 80.4 Mt for 2025 "
                "(https://www.portgdansk.pl/?p=81344) against GUS's 75.3 Mt. Do not mix the two series.",
                "LNG: Świnoujście regasification capacity as reported by LNG Industry (ref); the Gdańsk FSRU is "
                "under construction (start Q1 2028) and has no position yet.",
                "Positions: Wikidata P625 of each port item (CC0).",
            ] + problems,
            "_files": files,
        }

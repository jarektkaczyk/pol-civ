"""Freight between Polish regions (Eurostat).

* Road: national road freight loaded and unloaded per NUTS 3 region (`road_go_na_rl3g`,
  `road_go_na_ru3g`, thousand tonnes, all goods), newest year. Eurostat publishes no
  region-to-region (origin-destination) matrix for road freight, so road has tables only.
* Rail: national and international rail freight by NUTS 2 region of loading and of unloading
  (`tran_r_rago`, tonnes), the only official region-to-region freight matrix for Poland. Its
  newest year is older than the road tables; it is kept as flows between voivodeships.
"""

from __future__ import annotations

import json
import unicodedata

from ..core.source import Source, SourceInfo
from .pl_transport_util import eurostat_get, jsonstat_cells, jsonstat_labels

# NUTS 2 (2013 and 2016/2021/2024 codes) -> TERYT voivodeship code, with a name check against Eurostat's label.
NUTS2_VOIV = {
    "PL11": ("10", "lodzkie"), "PL71": ("10", "lodzkie"),
    "PL12": ("14", "mazowieckie"), "PL91": ("14", "warszawski"), "PL92": ("14", "mazowiecki"),
    "PL21": ("12", "malopolskie"), "PL22": ("24", "slaskie"),
    "PL31": ("06", "lubelskie"), "PL81": ("06", "lubelskie"),
    "PL32": ("18", "podkarpackie"), "PL82": ("18", "podkarpackie"),
    "PL33": ("26", "swietokrzyskie"), "PL72": ("26", "swietokrzyskie"),
    "PL34": ("20", "podlaskie"), "PL84": ("20", "podlaskie"),
    "PL41": ("30", "wielkopolskie"), "PL42": ("32", "zachodniopomorskie"), "PL43": ("08", "lubuskie"),
    "PL51": ("02", "dolnoslaskie"), "PL52": ("16", "opolskie"),
    "PL61": ("04", "kujawsko-pomorskie"), "PL62": ("28", "warminsko-mazurskie"), "PL63": ("22", "pomorskie"),
}
TOP_N = 25


def fold(text: str) -> str:
    """Lower case without diacritics (Eurostat labels mix 'Lódzkie' and 'Łódzkie')."""
    text = (text or "").replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def nuts2_to_voiv(code: str, label: str) -> str | None:
    """TERYT voivodeship code for a Polish NUTS 2 code, checked against Eurostat's label."""
    hit = NUTS2_VOIV.get(code)
    if not hit:
        return None
    teryt, word = hit
    if word not in fold(label):
        raise ValueError(f"NUTS2 {code} label {label!r} does not match {word!r}")
    return teryt


def newest_year_table(doc: dict, geo_dim: str = "geo") -> tuple[int, dict[str, float]]:
    """Newest year with Polish NUTS 3 values in a road_go_na_r?3g extract -> (year, {nuts3: kt})."""
    ids, cells = jsonstat_cells(doc)
    gi, ti = ids.index(geo_dim), ids.index("time")
    by_year: dict[int, dict[str, float]] = {}
    for key, v in cells.items():
        geo = key[gi]
        if v is None or not geo.startswith("PL") or len(geo) != 5:
            continue
        by_year.setdefault(int(key[ti]), {})[geo] = v
    year = max(by_year)
    return year, by_year[year]


def rail_flows(doc: dict) -> tuple[int, list[dict], dict[str, float]]:
    """(year, inter-voivodeship flows in kt, within-voivodeship kt) from a tran_r_rago extract for PL."""
    ids, cells = jsonstat_cells(doc)
    li, ui, ti = ids.index("c_load"), ids.index("c_unload"), ids.index("time")
    labels = jsonstat_labels(doc, "c_load")
    labels.update(jsonstat_labels(doc, "c_unload"))
    years = sorted({int(k[ti]) for k, v in cells.items() if v is not None})
    year = years[-1]
    pairs: dict[tuple[str, str], float] = {}
    within: dict[str, float] = {}
    for key, v in cells.items():
        if v is None or int(key[ti]) != year:
            continue
        a, b = key[li], key[ui]
        va, vb = nuts2_to_voiv(a, labels.get(a, "")), nuts2_to_voiv(b, labels.get(b, ""))
        if not va or not vb:
            continue  # foreign regions and 'not regionalised'
        if va == vb:
            within[va] = within.get(va, 0.0) + v / 1000.0
        else:
            pairs[(va, vb)] = pairs.get((va, vb), 0.0) + v / 1000.0
    flows = [{"from": a, "to": b, "level": "voivodeship", "value": round(v, 1), "unit": "kt", "year": year,
              "mode": "rail"} for (a, b), v in sorted(pairs.items(), key=lambda kv: -kv[1])]
    return year, flows, {k: round(v, 1) for k, v in within.items()}


class PlTransportFreight(Source):
    info = SourceInfo(
        id="pl_transport_freight",
        title="Road freight by NUTS 3 region and rail freight between regions (Eurostat)",
        publisher="Eurostat (data from Statistics Poland, GUS)",
        homepage="https://ec.europa.eu/eurostat/web/transport/database",
        license="Eurostat copyright notice: free re-use with attribution (CC BY 4.0 equivalent)",
        description="Tonnes of goods loaded and unloaded by road in each NUTS 3 subregion of Poland (national "
        "transport by Polish hauliers), and tonnes of rail freight between voivodeships. Road freight has no "
        "published region-to-region matrix.",
        used_for=["Trade routes between regions", "Commerce advisor"],
    )

    RL = "road_go_na_rl3g.json"
    RU = "road_go_na_ru3g.json"
    RAIL = "tran_r_rago_pl.json"

    def fetch(self, force=False):
        eurostat_get(self, "road_go_na_rl3g", self.RL, force=force, nst07="TOTAL", unit="THS_T", lastTimePeriod=2)
        eurostat_get(self, "road_go_na_ru3g", self.RU, force=force, nst07="TOTAL", unit="THS_T", lastTimePeriod=2)
        eurostat_get(self, "tran_r_rago", self.RAIL, force=force, geo="PL", unit="T", lastTimePeriod=1)

    def process(self):
        load = json.loads((self.raw_dir / self.RL).read_text(encoding="utf-8"))
        unload = json.loads((self.raw_dir / self.RU).read_text(encoding="utf-8"))
        y_l, loaded = newest_year_table(load)
        y_u, unloaded = newest_year_table(unload, geo_dim="geo")
        names = jsonstat_labels(load, "geo")
        rows = {}
        for code in sorted(set(loaded) | set(unloaded)):
            rows[code] = {"loaded_kt": loaded.get(code), "unloaded_kt": unloaded.get(code)}
        rail = json.loads((self.raw_dir / self.RAIL).read_text(encoding="utf-8"))
        y_r, flows, within = rail_flows(rail)
        top = [f"{f['from']}->{f['to']} {f['value']:g} kt" for f in flows[:10]]
        return {
            "vintage": f"Eurostat road freight {max(y_l, y_u)}, rail regional freight {y_r}",
            "tables": {
                "road_freight_nuts3": {
                    "level": "nuts3",
                    "fields": {
                        "loaded_kt": {"label": "Road freight loaded (national transport)", "unit": "kt", "year": y_l,
                                      "note": "road_go_na_rl3g, all goods (NST 2007 TOTAL)"},
                        "unloaded_kt": {"label": "Road freight unloaded (national transport)", "unit": "kt",
                                        "year": y_u, "note": "road_go_na_ru3g, all goods"},
                    },
                    "rows": rows,
                },
                "rail_freight_within_voivodeship": {
                    "level": "voivodeship",
                    "fields": {"within_kt": {"label": "Rail freight loaded and unloaded in the same voivodeship",
                                             "unit": "kt", "year": y_r, "note": "tran_r_rago"}},
                    "rows": {k: {"within_kt": v} for k, v in sorted(within.items())},
                },
            },
            "flows": flows,
            "nuts3_names": {code: names.get(code) for code in rows},
            "notes": [
                "Road: Eurostat publishes national road freight by NUTS 3 region of loading and of unloading only; "
                "there is no published origin-destination matrix, so road has no flows.",
                "Road NUTS 3 codes are Eurostat's current codes for Poland; rows with older NUTS versions (labelled "
                "'NUTS 2013' or 'NUTS 2010' by Eurostat) carry no values for the newest year.",
                f"Rail flows: tran_r_rago {y_r} (newest year published), national and international rail freight by "
                "NUTS 2 region of loading and unloading, Polish pairs only. PL91 and PL92 are summed into Mazowieckie "
                "(14). Flows between different voivodeships only; same-voivodeship tonnage is a table (Eurostat leaves "
                "some cells empty; those voivodeships are absent).",
                f"Rule (flows): every inter-voivodeship pair with a value, largest first. Top 10: {'; '.join(top)}.",
            ],
            "_files": [self.RL, self.RU, self.RAIL],
        }

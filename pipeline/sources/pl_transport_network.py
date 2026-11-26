"""Official lengths of Poland's motorways and railway lines (Eurostat `tran_r_net`).

A cross-check for the OpenStreetMap lengths in `pl_transport_osm`, by NUTS 2 region and for the
country. Each measure takes its own newest year with a value (Eurostat fills them at different times).
"""

from __future__ import annotations

import json

from ..core.source import Source, SourceInfo
from .pl_transport_freight import nuts2_to_voiv
from .pl_transport_util import eurostat_get, jsonstat_cells, jsonstat_labels

MEASURES = {  # tra_infr -> field
    "MWAY": ("motorway_km", "Motorways"),
    "RL": ("rail_line_km", "Railway lines"),
    "RL_ELC": ("rail_electrified_km", "Electrified railway lines"),
    "RL_TGE2": ("rail_double_track_km", "Railway lines with two or more tracks"),
    "RIV": ("navigable_river_km", "Navigable rivers"),
    "CNL": ("navigable_canal_km", "Navigable canals"),
}
GEOS = ["PL", "PL21", "PL22", "PL41", "PL42", "PL43", "PL51", "PL52", "PL61", "PL62", "PL63", "PL71", "PL72",
        "PL81", "PL82", "PL84", "PL91", "PL92"]


def newest_by_measure(doc: dict) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    """({geo: {field: km}}, {field: year}): per measure the newest year with a value for the country."""
    ids, cells = jsonstat_cells(doc)
    ii, ui, gi, ti = ids.index("tra_infr"), ids.index("unit"), ids.index("geo"), ids.index("time")
    years: dict[str, int] = {}
    for key, v in cells.items():
        if v is None or key[ui] != "KM" or key[ii] not in MEASURES or key[gi] != "PL":
            continue
        f = MEASURES[key[ii]][0]
        years[f] = max(years.get(f, 0), int(key[ti]))
    rows: dict[str, dict[str, float]] = {}
    for key, v in cells.items():
        if v is None or key[ui] != "KM" or key[ii] not in MEASURES:
            continue
        f = MEASURES[key[ii]][0]
        if int(key[ti]) == years.get(f):
            rows.setdefault(key[gi], {})[f] = v
    return rows, years


class PlTransportNetwork(Source):
    info = SourceInfo(
        id="pl_transport_network",
        title="Road, rail and inland waterway network lengths by NUTS 2 region (tran_r_net)",
        publisher="Eurostat (data from Statistics Poland, GUS)",
        homepage="https://ec.europa.eu/eurostat/databrowser/view/tran_r_net/default/table",
        license="Eurostat copyright notice: free re-use with attribution (CC BY 4.0 equivalent)",
        description="Kilometres of motorways, railway lines (electrified, double track) and navigable waterways "
        "per region, as reported to Eurostat.",
        used_for=["Commerce advisor network lengths"],
    )

    FILE = "tran_r_net_pl.json"

    def fetch(self, force=False):
        eurostat_get(self, "tran_r_net", self.FILE, force=force, geo=GEOS, unit="KM", lastTimePeriod=4)

    def process(self):
        doc = json.loads((self.raw_dir / self.FILE).read_text(encoding="utf-8"))
        rows, years = newest_by_measure(doc)
        labels = jsonstat_labels(doc, "geo")
        nuts2 = {g: r for g, r in rows.items() if g != "PL"}
        for g in nuts2:
            nuts2_to_voiv(g, labels.get(g, ""))  # raises when a code is not the region we expect
        fields = {f: {"label": label, "unit": "km", "year": years.get(f)} for f, label in MEASURES.values()
                  if f in years}
        return {
            "vintage": "Eurostat tran_r_net " + ", ".join(f"{f} {y}" for f, y in sorted(years.items())),
            "tables": {
                "network_country": {"level": "country", "fields": fields, "rows": {"PL": rows.get("PL", {})}},
                "network_nuts2": {"level": "nuts2", "fields": fields, "rows": nuts2},
            },
            "notes": [
                "Each measure uses its newest year with a value for Poland; regions use the same year.",
                "Eurostat 'MWAY' for Poland is the motorway (autostrada, A-road) length; compare it with "
                "pl_transport_osm motorway_km. Expressways (S-roads) are not a separate Eurostat measure.",
                "NUTS 2: PL91 (Warszawski stołeczny) and PL92 (Mazowiecki regionalny) together form voivodeship 14.",
            ],
            "_files": [self.FILE],
        }

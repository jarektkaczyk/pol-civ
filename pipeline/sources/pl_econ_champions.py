"""Made in Poland: a curated list of the places behind Poland's best-known products and exports.

The list lives in pl_econ_champions.json next to this module. Each item is one plant, yard, orchard region or maker,
with a one-line fact, the year the figure refers to and the `ref` page the fact was read from (re-read for every item
in November 2026). National figures (Poland's share of EU apples, of world yacht exports ...) are written as national
figures and placed at one named place that makes the product; a "largest" claim made only by the company is written
as the company's claim. fetch() caches every ref page so the Almanac lists them with their retrieval date.

Left out on purpose: projects that were cancelled or closed (Intel Miekinia, Volvo Buses Wroclaw), tobacco, and sites
that already have a marker in another layer (KGHM Glogow, Orlen Plock, Belchatow, Baltic Hub).
"""

from __future__ import annotations

from ..core.source import Source, SourceInfo
from ._econ_sites import cache_refs, cached_refs, check_item, load_json, to_point

CURATED = "pl_econ_champions.json"


class PlEconChampions(Source):
    info = SourceInfo(
        id="pl_econ_champions",
        title="Made in Poland: plants, yards and makers behind Polish products",
        publisher="Eurostat, GUS, the Polish Investment and Trade Agency (PAIH), company reports and press pages",
        homepage="https://www.paih.gov.pl/",
        license="Short quotations of published figures with the page named; Eurostat and GUS: reuse with attribution",
        description="A curated list of places that make what Poland is known for abroad: car and battery plants, "
        "bus, tram and train makers, yachts, home appliances, windows and furniture, food, crafts and cosmetics. "
        "Each place has one fact, the year of the figure and the page it comes from.",
        used_for=["Made in Poland map layer", "City View"],
    )

    def fetch(self, force=False):
        cur = load_json(__file__, CURATED)
        for note in cache_refs(self, cur["items"], force=force):
            print(f"      ! {note}")

    def process(self):
        cur = load_json(__file__, CURATED)
        kinds = {k["id"] for k in cur["kinds"]}
        problems = [p for it in cur["items"] for p in check_item(it, kinds)]
        if problems:
            raise ValueError("pl_econ_champions.json: " + "; ".join(problems))
        files, ref_notes = cached_refs(self, cur["items"])
        return {
            "vintage": "Curated November 2026; figures 2017-2026 (each item has its year)",
            "points": [to_point(it) for it in cur["items"]],
            "notes": ["rule: " + cur["rule"]] + ref_notes,
            "_files": files,
        }

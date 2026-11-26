"""Military layer of Poland from public sources: garrisons, bases, allied sites, training areas,
troop strength and the 2026 defence budget.

The site list is curated (pl_soc_military.json, next to this module). Each item has a `ref` URL
that states its garrison: MON (gov.pl/web/obrona-narodowa), NATO, US Army press, or cited
Wikipedia unit pages where the official unit sites (wojsko-polskie.pl) refuse automated reads.
Positions are the centre of the garrison town only (coordinates of the town from Wikipedia /
Wikidata, 3 decimals), never a barracks, airfield or range position.

fetch() caches the official documents behind the headline numbers (MON budget booklet, NATO
defence expenditure report) so the Almanac can cite them; the numbers themselves were read from
those documents and are written below with their page references.
"""

from __future__ import annotations

from collections import defaultdict

from ..core.source import Source, SourceInfo
from .pl_soc_common import load_curated, voivodeship_code

MON_BUDGET_2026 = "https://www.gov.pl/attachment/177eff55-1be1-4553-8bb8-a67fbfb820e9"
NATO_2026 = "https://www.nato.int/content/dam/nato/webready/documents/finance/def-exp-2026-en.pdf"
KPRM_BUDGET_2026 = ("https://www.gov.pl/web/premier/"
                    "bezpieczenstwo-wsparcie-rodzin-i-ambitne-inwestycje--rzad-przyjal-budzet-2026")
DEFENCE24_STRENGTH = "https://defence24.pl/sily-zbrojne/mamy-najnowsze-dane-tylu-zolnierzy-ma-polska-news-defence24"
WOT_PAGE = "https://www.gov.pl/web/obrona-narodowa/wojska-obrony-terytorialnej-"

RULE = (
    "Units: every division and brigade of the Land Forces (active or forming in 2026), the Air Force wings and "
    "brigades, Navy flotillas and naval aviation, Special Forces units and the Territorial Defence brigades, at "
    "the seat of their command. Bases: tactical, transport, training and UAV air bases, army and naval aviation "
    "bases, naval ports. Allied: US and NATO commands and sites in Poland named by MON, NATO or the US Army. "
    "Training areas: the main land and air force ranges. Brigades that exist only in plans are left out. "
    "Every position is the garrison town centre."
)

# Headline figures, read from the cited documents (value, unit, year, note, ref).
HEADLINE = {
    "strength_total": (216271, "persons", 2025,
                       "Polish Armed Forces strength in 2025 (MON budget booklet, March 2026, chart "
                       "'Liczebnosc Sil Zbrojnych RP w latach 2024-2026'; 2024: 205,387)", MON_BUDGET_2026),
    "strength_total_mid_2026": (220000, "persons", 2026,
                                "about 220,000 at the end of June 2026: MON answers published by Defence24 on "
                                "24 Jul 2026 (secondary source, rounded)", DEFENCE24_STRENGTH),
    "professional_soldiers": (156000, "persons", 2026,
                              "about 156,000 professional soldiers, end of June 2026 (MON via Defence24)",
                              DEFENCE24_STRENGTH),
    "territorial_defence": (40000, "persons", 2026,
                            "Territorial Defence Force (WOT) soldiers, MON WOT page (undated)", WOT_PAGE),
    "voluntary_service": (14600, "persons", 2026,
                          "voluntary basic military service (DZSW), end of June 2026 (MON via Defence24); "
                          "3,300 more in first-year training", DEFENCE24_STRENGTH),
    "defence_budget_2026": (124.8e9, "PLN", 2026,
                            "defence spending in the 2026 budget act (MON booklet, March 2026, p. 2): "
                            "PLN 124.8 bn = 3.0% of GDP; MON part 29 alone PLN 118.64 bn", MON_BUDGET_2026),
    "defence_budget_2026_pct_gdp": (3.0, "% of GDP", 2026, "budget act share (MON booklet, p. 2-3)",
                                    MON_BUDGET_2026),
    "defence_total_2026_with_fwsz": (200e9, "PLN", 2026,
                                     "government total for security in 2026 including the Armed Forces Support "
                                     "Fund (FWSZ), announced with the draft budget on 28 Aug 2025", KPRM_BUDGET_2026),
    "defence_total_2026_with_fwsz_pct_gdp": (4.81, "% of GDP", 2026, "same announcement", KPRM_BUDGET_2026),
    "nato_core_defence_2026_pct_gdp": (4.68, "% of GDP", 2026,
                                       "NATO 'Defence Investment of NATO Countries (2014-2026)', cut-off 3 Jul "
                                       "2026, core defence expenditure, 2026 estimate (Table 3)", NATO_2026),
    "nato_core_defence_2026": (193789e6, "PLN", 2026,
                               "same NATO report, Table 1 (read by OCR from the image PDF)", NATO_2026),
    "nato_core_defence_2025_pct_gdp": (4.25, "% of GDP", 2025, "same NATO report, 2025 estimate (Table 3)",
                                       NATO_2026),
}

COUNTED_KINDS = {"unit_land", "unit_air", "unit_navy", "unit_special", "unit_territorial", "air_base", "naval_base"}


def garrison_counts(items: list[dict]) -> dict[str, dict]:
    """Voivodeship code -> {"garrison_towns", "units", "bases"} over Polish units and bases.

    Allied sites and training areas are not counted. A town with several units counts once.
    """
    towns: dict[str, set] = defaultdict(set)
    units: dict[str, int] = defaultdict(int)
    bases: dict[str, int] = defaultdict(int)
    for it in items:
        if it["kind"] not in COUNTED_KINDS:
            continue
        code = voivodeship_code(it.get("voivodeship"))
        if code is None:
            raise ValueError(f"{it['id']}: unknown voivodeship {it.get('voivodeship')!r}")
        towns[code].add(it["garrison"])
        if it["kind"].startswith("unit_"):
            units[code] += 1
        else:
            bases[code] += 1
    return {c: {"garrison_towns": len(towns[c]), "units": units[c], "bases": bases[c]} for c in sorted(towns)}


class PlSocMilitary(Source):
    info = SourceInfo(
        id="pl_soc_military",
        title="Military garrisons, bases, allied sites, strength and budget",
        publisher="Ministerstwo Obrony Narodowej (MON), NATO, US Army; cited Wikipedia unit pages",
        homepage="https://www.gov.pl/web/obrona-narodowa",
        license="Public information (MON, NATO); Wikipedia text CC BY-SA 4.0",
        description="Seats of the divisions, brigades, air wings, flotillas, special and territorial units, "
        "the air and naval bases, US and NATO sites and the main training areas, at town level. Troop strength "
        "and the 2026 defence budget from MON and NATO.",
        used_for=["Military layer", "Military advisor"],
    )

    def fetch(self, force=False):
        self.download(MON_BUDGET_2026, "mon_budzet_2026.pdf", force=force, expect_binary=True)
        self.download(NATO_2026, "nato_def_exp_2026.pdf", force=force, expect_binary=True)

    def process(self):
        items = load_curated(__file__, "pl_soc_military.json")["items"]
        points = []
        for it in items:
            props = {k: it[k] for k in ("short", "branch", "status", "garrison", "voivodeship", "parent",
                                        "operator", "area_km2", "wing", "unit", "note") if it.get(k) is not None}
            props["voivodeship_code"] = voivodeship_code(it.get("voivodeship"))
            props["ref"] = it["ref"]
            points.append({"id": it["id"], "name": it["name"], "kind": it["kind"],
                           "lon": it["lon"], "lat": it["lat"], "props": props})
        headline_fields = {k: {"label": k.replace("_", " "), "unit": u, "year": y, "note": n, "ref": r}
                           for k, (v, u, y, n, r) in HEADLINE.items()}
        tables = {
            "headline": {"level": "country", "fields": headline_fields,
                         "rows": {"PL": {k: v[0] for k, v in HEADLINE.items()}}},
            "garrisons": {
                "level": "voivodeship",
                "fields": {
                    "garrison_towns": {"label": "Garrison towns", "unit": "towns", "year": 2026,
                                       "note": "distinct towns with a Polish unit or base in this list"},
                    "units": {"label": "Units (divisions, brigades, wings, flotillas)", "unit": "units",
                              "year": 2026},
                    "bases": {"label": "Air and naval bases", "unit": "bases", "year": 2026},
                },
                "rows": garrison_counts(items),
            },
        }
        return {
            "vintage": "Curated November 2026; MON budget booklet March 2026; NATO defence report July 2026",
            "tables": tables,
            "points": points,
            "notes": [
                "rule: " + RULE,
                "Garrison counts by voivodeship are counted from this list; no official count by voivodeship "
                "was found (the garrison list is in the MON regulation Dz.U. 2022 poz. 1868, amended by "
                "Dz.U. 2025 poz. 934).",
                "Brigades of 8 DP AK planned in 2023 (Mielec, Laziska, Raducz, Leszno) are left out: no source "
                "shows them active in 2026.",
                "wojsko-polskie.pl and several nato.int sites refuse automated reads; their units cite pl.wikipedia "
                "unit pages, which cite MON.",
                "NATO 2026 report uses 'core defence expenditure'; it is not comparable with the 2025 edition "
                "(Poland 2025e 4.48% there).",
            ],
            "_files": ["mon_budzet_2026.pdf", "nato_def_exp_2026.pdf"],
        }

"""Lenses for Poland: per-hex values of the gmina metrics (counties.py METRICS), grouped for the lens dock.

A hex takes the population-weighted mean of the gminas its 7 samples fall in (each gmina's population shared over
its sample hits), so a lens and the gmina tables show the same numbers. Metrics published per powiat, voivodeship
or diocese reach the gminas first (counties.py) and say so in the lens `note`. Categorical lenses take the
category with the most people among the hex's gminas. Density is people per km² of the hex's land. Land lenses
read the hex's own land-cover shares.
"""

from __future__ import annotations

import math
from collections import Counter

from ..core.hexgrid import HexGrid
from ..core.store import load_interim, write_web
from .counties import FLOOD_CATS, LEVEL_TEXT, METRIC, SEJM, SEJM_COLORS, Metrics, description, projection
from .plstats import Stats, Units, cell_weights, optional, spread, unsampled_cells
from .lenses_more_a import LENSES_A, lens_values
from .yields import Economy
from .lenses_more_b import REQUIRES_B, lenses_b  # identity, commuting and EU funds lenses (lenses_more_b.py)
from .lenses_more_c import GROUPS_C, LENSES_C, REQUIRES_C  # enterprise lenses (lenses_more_c.py)

REQUIRES = ["_world", "pl_geo_teryt", "pl_geo_lau", "pl_geo_fua", "pl_stats_population", "pl_stats_labour", "pl_stats_prosperity",
            "pl_gdp", "pl_foreigners", "pl_census_2021", "pl_soc_elections", "pl_soc_faith", "pl_soc_air",
            "pl_soc_health", "pl_soc_universities", "pl_soc_disasters", "pl_more_gus", "pl_more_exams",
            "pl_more_finance"] + REQUIRES_B + REQUIRES_C
PRODUCES = ["lenses.json"]

GROUPS = [
    {"id": "people", "name": "People"},
    {"id": "prosperity", "name": "Prosperity"},
    {"id": "knowledge", "name": "Knowledge"},
    {"id": "life", "name": "Daily life"},
    {"id": "faith", "name": "Faith"},
    {"id": "vote", "name": "Vote"},
    {"id": "air", "name": "Air"},
    {"id": "hazards", "name": "Hazards"},
    {"id": "land", "name": "Land"},
]
GROUPS[2:2] = GROUPS_C  # after Prosperity

R = {  # ramps, dark to light
    "plum": ["#1b1035", "#4b2377", "#9a3b8a", "#e0645e", "#f9b24a", "#fff3a8"],
    "gold": ["#3a1c0b", "#7a4413", "#b8781f", "#e3b23c", "#f6e27f", "#fffbe0"],
    "teal": ["#0b2a2e", "#165a5c", "#2f8f83", "#7cc29a", "#d4ecb0", "#ffffe0"],
    "fire": ["#03051a", "#4c1d4b", "#a11a5b", "#e83f3f", "#f69c73", "#faebdd"],
    "cividis": ["#00224e", "#35456c", "#666970", "#948e77", "#c8b866", "#fee838"],
    "mako": ["#0b0405", "#382a54", "#395d9c", "#3497a9", "#60ceac", "#def5e5"],
    "blue": ["#08203e", "#0f4c81", "#2a7fc1", "#5fa8e0", "#a6d1f2", "#eaf5ff"],
    "violet": ["#1a0a2e", "#3f1d6b", "#6a3fa0", "#9a72c9", "#c9a9e6", "#f3e8ff"],
    "rose": ["#2b0b1e", "#5e1742", "#93275f", "#c84f7c", "#ea8fa8", "#fbd9e1"],
    "olive": ["#1c1a05", "#45410f", "#76701d", "#a8a033", "#d4ce62", "#f8f6c4"],
    "rust": ["#1a0505", "#4a0f0f", "#80201a", "#b8452b", "#e07b54", "#f9c9a8"],
    "dusk": ["#1a1033", "#3d2466", "#6b3d8f", "#a5649c", "#d99a8f", "#f7dca0"],
    "smog": ["#0d1a12", "#2d3a2a", "#5f5a3a", "#8f6f3d", "#c0763a", "#f0a15a"],
    "forest": ["#0b1f0f", "#14401c", "#1f6b2b", "#3a9443", "#7fc07a", "#d5efcd"],
    "farm": ["#141d05", "#2f4510", "#557019", "#84a02a", "#b8cf55", "#eef7b8"],
    "built": ["#121218", "#2c2c3c", "#4b4b66", "#727294", "#a3a3c2", "#e2e2f0"],
    # Diverging, neutral hues (not party colours): teal below 50%, parchment at 50%, amber above.
    "vote": ["#0f5257", "#3c8c8a", "#9cc9bf", "#efe4c6", "#e8b86a", "#c9822a", "#8a4f12"],
}

# lens id -> (metric key, icon, emoji, ramp, scale, extra)
LENSES = [
    ("density", "density", "l-people", "👥", "plum", "log", {}),
    ("age", "median_age", "l-age", "🎂", "mako", "linear", {}),
    ("growth", "growth", "l-growth", "📈", "teal", "linear", {}),
    ("migration", "net_migration", "l-migration", "🧳", "teal", "linear", {}),
    ("elderly", "elderly", "l-elderly", "👵", "dusk", "linear", {}),
    ("births", "births", "l-births", "👶", "rose", "linear", {}),
    ("ukrainians", "ukrainians", "l-foreign", "🌻", "blue", "log", {}),
    ("income", "pit", "l-income", "💰", "gold", "linear", {}),
    ("wage", "wage", "l-wage", "💵", "gold", "linear", {}),
    ("unemployment", "unemployment", "l-unemployment", "📉", "rust", "linear", {}),
    ("dwellings", "dwellings", "l-home", "🏗️", "cividis", "linear", {}),
    ("higher_ed", "higher_ed", "l-bachelors", "🎓", "violet", "linear", {}),
    ("students", "students", "l-students", "🏛️", "violet", "log", {}),
    ("tourism", "tourism", "l-tourism", "🧳", "olive", "linear", {}),
    ("doctors", "doctors", "l-doctors", "🩺", "teal", "log", {}),
    ("life_f", "life_f", "l-life", "❤️", "mako", "linear", {}),
    ("life_m", "life_m", "l-life", "❤️", "mako", "linear", {}),
    ("catholic", "catholic", "l-faith", "⛪", "dusk", "linear", {}),
    ("no_religion", "no_religion", "l-faith", "🕊️", "blue", "linear", {}),
    ("mass", "mass", "l-faith-tradition", "🔔", "dusk", "linear", {}),
    ("vote", "president_2025", "l-vote", "🗳️", "vote", "linear", {"domain": [0.2, 0.8]}),
    ("turnout", "turnout_2025", "l-turnout", "✉️", "cividis", "linear", {}),
    ("sejm", "sejm_2023", "l-sejm", "🏛️", None, "linear", {}),
    ("pm25", "pm25", "l-air", "🌫️", "smog", "linear", {}),
    ("flood", "flood_2024", "l-disasters", "🌊", None, "linear", {}),
]
LENSES = [lens for lens in LENSES if lens[0] not in {more[0] for more in LENSES_A}] + LENSES_A + LENSES_C
NOTES = {
    "ukrainians": "Counts where the PESEL UKR number was issued, not where people live now.",
    "income": "Follows the taxable income of residents.",
    "students": "Only gminas with a university have a value.",
    "doctors": "Counted at the hospital or clinic, so city powiats rank high.",
    "catholic": "The census question was voluntary: about a fifth of residents did not answer.",
    "no_religion": "The census question was voluntary: about a fifth of residents did not answer.",
    "vote": "Per gmina, 2025. Colours split at 50%: teal leans to Trzaskowski, amber to Nawrocki.",
    "pm25": "The nearest station within 25 km. Blank: no station that close.",
    "flood": "A declaration is a legal act that unlocks aid, not a measure of damage.",
    "sejm": "Shows only the committee with the most votes.",
    "growth": "Gminas whose borders changed since 2015 (Opole and its neighbours, Kamienica, Supraśl) show no change.",
}
LAND = {
    "forest": (["forest"], "Forest", "l-forest", "🌲", "forest",
               "Share of the hex's land with tree cover (ESA WorldCover 2021)."),
    "farmland": (["crop", "pasture"], "Farmland", "l-farmland", "🚜", "farm",
                 "Share of the hex's land in cropland or in meadow and pasture below 900 m (ESA WorldCover 2021)."),
    "developed": (["developed"], "Built-up", "l-developed", "🏙️", "built",
                  "Share of the hex's land that is built up (ESA WorldCover 2021)."),
}
DIGITS = {"pct": 4, "float": 2, "years": 1, "pln": 0, "int": 0}
DOMAIN_NOTE = " Colours span the 2nd to 98th percentile of hexes; values beyond are drawn at the end colours."

# The dock has little horizontal room. The legend keeps the full statistical name; only dock buttons use these.
SHORT_NAMES = {
    "income": "PIT per person",
    "wage": "Gross monthly wage",
    "tourism_city": "City tourist nights",
    "exam_8_maths": "Grade 8 maths",
    "farm_area": "Farm area",
    "farm_land_share": "Farmland share",
    "vote": "2025 presidential vote",
    "turnout": "2025 turnout",
    "vote_2015": "2015 presidential vote",
    "vote_2020": "2020 presidential vote",
    "vote_shift_2020_2025": "Vote shift 2020-2025",
    "kashubian": "Kashubian share",
    "german": "German share",
    "belarusian": "Belarusian share",
}


def nice(v: float, up: bool) -> float:
    """v rounded outward (up or down) to 2 significant digits."""
    if v == 0:
        return 0
    mag = 10 ** (math.floor(math.log10(abs(v))) - 1)
    return round((math.ceil if up else math.floor)(v / mag) * mag, 10)


def percentile_domain(values: list, log: bool) -> list[float] | None:
    """[2nd, 98th] percentile of the non-null hex values, rounded outward; positive values only on a log scale."""
    vals = sorted(v for v in values if v is not None and (v > 0 or not log))
    if not vals:
        return None
    lo, hi = vals[int(0.02 * (len(vals) - 1))], vals[int(0.98 * (len(vals) - 1))]
    lo, hi = nice(lo, False), nice(hi, True)
    return [lo, hi] if hi > lo else [lo, nice(vals[-1], True)]


def dominant(weights, cats: list) -> list:
    """Per cell: the category index with the most people among the cell's gminas (None where none has one)."""
    out = [None] * len(weights)
    for i, parts in enumerate(weights):
        acc: dict[int, float] = {}
        for k, p in parts:
            if cats[k] is not None:
                acc[cats[k]] = acc.get(cats[k], 0) + p + 1e-9
        if acc:
            out[i] = max(acc.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return out


def level_note(metric: dict) -> str | None:
    lvl = metric["level"]
    return {"powiat": "Per powiat.", "voivodeship": "Per voivodeship.", "diocese": "Per diocese."}.get(lvl)


def build() -> None:
    world = load_interim("_world")
    teryt = load_interim("pl_geo_teryt")
    units = Units(world, teryt)
    stats = Stats()
    econ = Economy(units, stats)
    grid = HexGrid(**world["grid"])
    owner = world["owner"]
    m = Metrics(world, units, stats, econ, projection(world), grid)
    pops = m.values["population"]
    lau = (optional("pl_geo_lau") or {}).get("data")
    extra = unsampled_cells(world, lau, projection(world), grid)
    weights = cell_weights(world, pops, extra)
    print(f"    {len(extra)} gminas without hex samples placed by their LAU centre")
    hex_area = 1.5 * math.sqrt(3) * grid.radius ** 2

    lenses = []
    for lid, key, icon, emoji, ramp, scale, extra in LENSES:
        extra = dict(extra)
        data = extra.pop("_data", None)
        metric, gv = lens_values(data, stats, units.gminas) if data else (METRIC[key], m.values[key])
        if not any(v is not None for v in gv):
            print(f"    lens {lid}: no data yet ({metric['source']})")
            continue
        base = {"id": lid, "group": metric["group"], "name": metric["label"], "icon": icon, "emoji": emoji,
                "unit": metric["unit"], "higher_is": metric["higher_is"], "source": metric["source"],
                "description": description(metric)}
        note = " ".join(x for x in (level_note(metric), NOTES.get(lid)) if x)
        if note:
            base["note"] = note
        if key in ("sejm_2023", "flood_2024"):
            cats = ([{"id": cid, "name": name, "color": SEJM_COLORS[j]} for j, (_, cid, name) in enumerate(SEJM)]
                    if key == "sejm_2023" else [{"id": cid, "name": name, "color": col} for cid, name, col in FLOOD_CATS])
            pos = {c["id"]: j for j, c in enumerate(cats)}
            vals = dominant(weights, [pos.get(v) if v is not None else None for v in gv])
            lenses.append({**base, "format": "category", "categories": cats, "ramp": [c["color"] for c in cats],
                           "scale": "linear", "domain": [0, len(cats) - 1], "unit": None, "values": vals})
            continue
        if key == "density":
            vals = [None] * grid.size
            for i, parts in enumerate(weights):
                smp = world["county_samples"][i]
                if parts and smp:
                    land = sum(1 for x in smp if x >= 0) or 1
                    vals[i] = round(sum(p for _, p in parts) / (hex_area * land / len(smp)), 1)
        else:
            vals = spread(weights, gv, DIGITS.get(metric["format"], 2))
        lenses.append({**base, "format": metric["format"], "scale": scale, "ramp": R[ramp], "values": vals, **extra})
    lenses += lenses_b(world, units, weights, R, GROUPS)

    pct = world.get("pct")
    if pct:
        cover = world.get("cover") or [1] * grid.size
        for lid, (keys, name, icon, emoji, ramp, desc) in LAND.items():
            vals = [round(sum(pct[k][i] for k in keys) / 100, 2) if owner[i] >= 0 and cover[i] else None
                    for i in range(grid.size)]
            lenses.append({"id": lid, "group": "land", "name": name, "icon": icon, "emoji": emoji,
                           "unit": "share of land", "format": "pct", "scale": "linear", "ramp": R[ramp],
                           "higher_is": "neutral", "source": "pl_geo_worldcover", "description": desc,
                           "values": vals})

    for lens in lenses:
        if lens["id"] in SHORT_NAMES:
            lens["short_name"] = SHORT_NAMES[lens["id"]]
        if "domain" in lens:
            continue
        lens["domain"] = percentile_domain(lens["values"], lens["scale"] == "log")
        lens["description"] += DOMAIN_NOTE
    groups = [g for g in GROUPS if any(l["group"] == g["id"] for l in lenses)]
    vint = "; ".join(v for v in (stats.vintage(s) for s in ("pl_stats_population", "pl_soc_elections")) if v)
    write_web("lenses.json", {"vintage": vint, "groups": groups, "lenses": lenses})
    print(f"    {len(lenses)} lenses: " + ", ".join(l["id"] for l in lenses))


REQUIRED_NOTES = {"ukrainians", "vote", "pm25", "flood", "catholic"} | {lens[0] for lens in LENSES_A + LENSES_C}


def check(web_dir) -> list[tuple[str, str]]:
    """Polish lenses: caveat notes, category shape, the neutral vote ramp and a short coverage summary
    (pipeline.check validates the general shape)."""
    import json
    from pathlib import Path

    from ..core.i18n import t

    path = Path(web_dir) / "lenses.json"
    if not path.exists():
        return [("NOTE", "lenses.json missing (pipeline.check reports it)")]
    doc = json.loads(path.read_text())
    out = []
    by_id = {l.get("id"): l for l in doc.get("lenses", []) if isinstance(l, dict)}
    for lid, lens in by_id.items():
        full = t(lens.get("name", ""), "pl")
        if len(full) > 22:
            short = t(lens.get("short_name", ""), "pl")
            if not short or len(short) > 22:
                out.append(("FAIL", f"lens {lid}: Polish dock name is {len(full)} characters; short_name must be at most 22"))
    for lid in sorted(REQUIRED_NOTES & set(by_id)):
        if not by_id[lid].get("note"):
            out.append(("FAIL", f"lens {lid}: the legend caveat (note) is required"))
    for lid in ("vote", "vote_2015", "vote_2020", "vote_shift_2020_2025"):
        vote = by_id.get(lid)
        if vote and vote.get("ramp") != R["vote"]:
            out.append(("FAIL", f"lens {lid}: must use the neutral teal-amber ramp, not party colours"))
    for lid, lens in by_id.items():
        vals = [v for v in lens.get("values") or [] if v is not None]
        if lens.get("format") == "category":
            cats = lens.get("categories") or []
            mix = Counter(vals).most_common(3)
            out.append(("PASS", f"lens {lid}: {len(vals)} hexes; " + ", ".join(
                f"{cats[i]['id'] if i < len(cats) else i} {c}" for i, c in mix)))
        elif vals:
            vals.sort()
            out.append(("PASS", f"lens {lid}: {len(vals)} hexes, median {vals[len(vals) // 2]}"))
    missing = [l for l, *_ in LENSES if l not in by_id]
    if missing:
        out.append(("NOTE", f"lenses without data yet: {', '.join(missing)}"))
    return out

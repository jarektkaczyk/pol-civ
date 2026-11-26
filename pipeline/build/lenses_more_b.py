"""More lenses (a helper of lenses.py): national and ethnic identity (NSP 2021), commuting (NSP 2021) and EU
co-financing per resident.

lenses.py calls lenses_b(world, units, weights, ramps) after its own lenses and adds what it returns. Every lens here
is per gmina and is spread onto the hexes exactly like the lenses of lenses.py (population-weighted mean of the
gminas of the hex's samples; categorical lenses take the category with the most people). A source that is missing
leaves its lenses out. Source gmina codes are matched to today's codes on their first six TERYT digits.
"""

from __future__ import annotations

import math

from ..core.store import load_interim_payload
from .plstats import spread

REQUIRES_B = ["pl_identity", "pl_flows_commuting", "pl_eu_funds", "pl_hist_population"]
GROUPS_B = [{"id": "identity", "name": "Identity"}]

IDENTITY_NOTE = "Per gmina, NSP 2021 census (31 March 2021, GUS). Blank: fewer than 10 people declared it."
FEW = " GUS lists an identity in a gmina only when at least 10 people declared it."

# Largest identity other than Polish: category id, name, colour (neutral, distinct hues; no flag colours).
MINORITY_CATS = [
    ("silesian", "Silesian", "#c9a14a"),
    ("kashubian", "Kashubian", "#4f8fa8"),
    ("german", "German", "#8a7fb5"),
    ("ukrainian", "Ukrainian", "#6fa86a"),
    ("belarusian", "Belarusian", "#b8734f"),
    ("lemko", "Lemko", "#a35d7a"),
    ("lithuanian", "Lithuanian", "#5c9c95"),
    ("roma", "Roma", "#c48a8a"),
    ("other", "Another identity", "#7d7f86"),
]

# Lens specs. `value(rec, ctx)` turns the gmina's source record into the lens value (None = no data).
LENSES_B = [
    {"id": "silesian", "group": "identity", "name": "Silesian identity", "icon": "l-people", "emoji": "⛏️",
     "unit": "share of residents", "format": "pct", "scale": "log", "ramp": "gold", "higher_is": "neutral",
     "source": "pl_identity", "table": "identity_gmina", "field": "silesian_share",
     "description": "Residents who declared a Silesian national or ethnic identity, as the first or the second of "
                    "two possible answers, as a share of all residents (NSP 2021 census, 31 March 2021)." + FEW,
     "note": IDENTITY_NOTE},
    {"id": "kashubian", "group": "identity", "name": "Kashubian identity", "icon": "l-people", "emoji": "⚓",
     "unit": "share of residents", "format": "pct", "scale": "log", "ramp": "teal", "higher_is": "neutral",
     "source": "pl_identity", "table": "identity_gmina", "field": "kashubian_share",
     "description": "Residents who declared a Kashubian national or ethnic identity, as the first or the second "
                    "of two possible answers, as a share of all residents (NSP 2021 census, 31 March 2021)." + FEW,
     "note": IDENTITY_NOTE},
    {"id": "german", "group": "identity", "name": "German identity", "icon": "l-people", "emoji": "🏘️",
     "unit": "share of residents", "format": "pct", "scale": "log", "ramp": "violet", "higher_is": "neutral",
     "source": "pl_identity", "table": "identity_gmina", "field": "german_share",
     "description": "Residents who declared a German national or ethnic identity, as the first or the second of "
                    "two possible answers, as a share of all residents (NSP 2021 census, 31 March 2021)." + FEW,
     "note": IDENTITY_NOTE},
    {"id": "belarusian", "group": "identity", "name": "Belarusian identity", "icon": "l-people", "emoji": "🌾",
     "unit": "share of residents", "format": "pct", "scale": "log", "ramp": "rust", "higher_is": "neutral",
     "source": "pl_identity", "table": "identity_gmina", "field": "belarusian_share",
     "description": "Residents who declared a Belarusian national or ethnic identity, as the first or the second "
                    "of two possible answers, as a share of all residents (NSP 2021 census, 31 March 2021)." + FEW,
     "note": IDENTITY_NOTE},
    {"id": "minority", "group": "identity", "name": "Largest minority identity", "icon": "l-people", "emoji": "🧭",
     "unit": None, "format": "category", "higher_is": "neutral",
     "source": "pl_identity", "table": "identity_gmina", "field": "largest_minority",
     "description": "The national or ethnic identity other than Polish that the most residents of the gmina "
                    "declared (first or second answer), NSP 2021 census, 31 March 2021. Identities are named as "
                    "in the census list; 'Another identity' covers all others (for example English or American)."
                    + FEW,
     "note": "Per gmina, NSP 2021 census (31 March 2021, GUS). Blank: no identity other than Polish reached 10 "
             "people. Shows only the largest one, however small."},
    {"id": "commuters", "group": "life", "name": "Commuters in", "icon": "l-commute", "emoji": "🚆",
     "unit": "per 1,000 residents", "format": "float", "scale": "log", "ramp": "mako", "higher_is": "neutral",
     "source": "pl_flows_commuting", "table": "commuting_gmina", "field": "commuters_in",
     "per": ("pl_identity", "identity_gmina", "total"), "scale_by": 1000,
     "description": "Wage employees who live in another gmina and work in this one, per 1,000 residents of the "
                    "gmina (NSP 2021 census, 31 March 2021; residents from the same census). Job centres rank "
                    "high, dormitory suburbs low.",
     "note": "Per gmina, NSP 2021 census (31 March 2021, GUS). Wage employees only: the self-employed and "
             "farmers are not counted."},
    {"id": "eu_funds", "group": "prosperity", "name": "EU co-financing", "icon": "l-income", "emoji": "🇪🇺",
     "unit": "zł per resident", "format": "pln", "scale": "log", "ramp": "teal", "higher_is": "neutral",
     "source": "pl_eu_funds", "table": "eu_funds_gmina", "field": "eu_cofinancing",
     "per": ("pl_hist_population", "population_years", "pop_2026_06"),
     "description": None,  # from the source (programmes and snapshot date)
     "note": None},
]


def _payload(name: str) -> dict | None:
    try:
        return load_interim_payload(name)
    except FileNotFoundError:
        print(f"    ! interim {name} missing: its lenses are left out")
        return None


def _rows_by6(payload: dict | None, table: str) -> dict[str, dict]:
    rows = (((payload or {}).get("data") or {}).get("tables") or {}).get(table, {}).get("rows") or {}
    return {code[:6]: rec for code, rec in rows.items()}


def gmina_values(spec: dict, gminas: list[str], cache: dict) -> list:
    """The spec's value for each of today's gminas (None where the source has none)."""
    def rows(src, table):
        key = (src, table)
        if key not in cache:
            if ("payload", src) not in cache:
                cache[("payload", src)] = _payload(src)
            cache[key] = _rows_by6(cache[("payload", src)], table)
        return cache[key]

    main = rows(spec["source"], spec["table"])
    per = rows(*spec["per"][:2]) if spec.get("per") else None
    out = []
    for g in gminas:
        v = (main.get(g[:6]) or {}).get(spec["field"])
        if per is not None:
            d = (per.get(g[:6]) or {}).get(spec["per"][2])
            v = round(v / d * spec.get("scale_by", 1), 2) if isinstance(v, (int, float)) and d else None
        elif spec["format"] == "pct" and isinstance(v, (int, float)):
            v = round(v / 100, 5)  # interim percent -> lens fraction
        out.append(v)
    return out


def sig(v: float, n: int) -> float:
    """v rounded to n significant digits (keeps small shares such as 0.00018 readable on a log scale)."""
    if v == 0:
        return 0
    return round(v, n - 1 - int(math.floor(math.log10(abs(v)))))


def _dominant(weights, cats: list) -> list:
    out = [None] * len(weights)
    for i, parts in enumerate(weights):
        acc: dict[int, float] = {}
        for k, p in parts:
            if cats[k] is not None:
                acc[cats[k]] = acc.get(cats[k], 0) + p + 1e-9
        if acc:
            out[i] = max(acc.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return out


def lenses_b(world: dict, units, weights, ramps: dict, groups: list | None = None) -> list[dict]:
    """The lenses of LENSES_B that have data, in the lenses.json shape (no domain: lenses.py sets it).
    Adds GROUPS_B to `groups` (lenses.py GROUPS) when a lens uses them."""
    cache: dict = {}
    out = []
    for spec in LENSES_B:
        gv = gmina_values(spec, units.gminas, cache)
        if not any(v is not None for v in gv):
            print(f"    lens {spec['id']}: no data yet ({spec['source']})")
            continue
        payload = cache.get(("payload", spec["source"])) or {}
        meta = (payload.get("data") or {}).get("lens_text", {}).get(spec["id"], {})
        lens = {"id": spec["id"], "group": spec["group"], "name": spec["name"], "icon": spec["icon"],
                "emoji": spec["emoji"], "unit": spec["unit"], "higher_is": spec["higher_is"],
                "source": spec["source"], "description": spec["description"] or meta.get("description", ""),
                "note": spec["note"] or meta.get("note")}
        if not lens["note"]:
            lens.pop("note")
        if spec["format"] == "category":
            pos = {cid: j for j, (cid, _n, _c) in enumerate(MINORITY_CATS)}
            vals = _dominant(weights, [pos.get(v) if v is not None else None for v in gv])
            lens.update({"format": "category", "scale": "linear", "unit": None, "values": vals,
                         "categories": [{"id": c, "name": n, "color": col} for c, n, col in MINORITY_CATS],
                         "ramp": [col for _c, _n, col in MINORITY_CATS], "domain": [0, len(MINORITY_CATS) - 1]})
        else:
            vals = spread(weights, gv)
            vals = [None if v is None else round(v) if spec["format"] == "pln" else sig(v, 3) for v in vals]
            lens.update({"format": spec["format"], "scale": spec["scale"], "ramp": ramps[spec["ramp"]],
                         "values": vals})
        out.append(lens)
    if groups is not None:
        for g in GROUPS_B:
            if any(l["group"] == g["id"] for l in out) and all(x["id"] != g["id"] for x in groups):
                groups.insert(next((i + 1 for i, x in enumerate(groups) if x["id"] == "people"), len(groups)), g)
    return out

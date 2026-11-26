"""Districts and city badges of the City View towns (districts.json), from location quotients of PKD sections.

GUS publishes workers by PKD 2007 section (A-S) per powiat, not per gmina, so a town's districts describe its
powiat: exact for the 66 cities with powiat rights, the whole powiat for other towns (each row's `scope` says
which). LQ = (powiat workers in the district's sections / powiat workers) / (the same ratio for Poland).
Badges come from published rules (BADGE_RULES), checked in order; the first that holds wins.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..core.i18n import t
from ..core.paths import WEB_DATA
from ..core.store import load_interim, write_web
from .plstats import Stats, Units, num, total
from .yields import SECTIONS

REQUIRES = ["_world", "pl_geo_teryt", "pl_stats_labour", "pl_stats_population", "pl_transport_ports", "pl_mines",
            "pl_soc_military", "cities.json"]
PRODUCES = ["districts.json"]

MIN_LQ = 1.25
MIN_JOBS = 1000
MIN_SHARE = 0.01
SPECIALTY_LQ = 3.0
MAX_PER_CITY = 5
TOP = 8
PORT_KM, MINE_KM, GARRISON_KM = 10.0, 15.0, 5.0
TECH_LQ, TECH_SHARE = 2.0, 0.04
UNIVERSITY_SHARE = 0.10
TOURIST_LQ = 2.0
INDUSTRIAL_LQ = 1.5


def _d(id, name, color, sections, sub, badge, labels, description, caveat=None):
    return {"id": id, "name": name, "icon": f"d-{id.replace('_', '-')}", "color": color, "sections": sections,
            "sub": sub, "badge": {"id": badge, "label": labels.pop("_", name), "labels": labels},
            "description": description, "caveat": caveat}


CATALOG = [
    _d("campus", "Campus", "#4a7bd0", ["J", "M", "P"],
       {"J": "IT & telecoms", "M": "Science & engineering", "P": "Schools & universities"},
       "scientific", {"_": "Knowledge city", "J": "Tech city", "P": "University town"},
       "Information and communication, professional and scientific work, and education (PKD J, M, P)."),
    _d("commercial_hub", "Commercial hub", "#c9a23a", ["G", "K", "L", "N"],
       {"G": "Trade", "K": "Finance", "L": "Real estate", "N": "Business services"},
       "commercial", {"_": "Trade city", "K": "Finance city"},
       "Trade, finance, real estate and business services (PKD G, K, L, N)."),
    _d("industrial_zone", "Industrial zone", "#8a5a3a", ["B", "C"], {"B": "Mining", "C": "Manufacturing"},
       "industrial", {"_": "Industrial town", "B": "Mining town"},
       "Mining and manufacturing (PKD B, C)."),
    _d("harbor", "Harbor", "#2f7fa8", ["H"], {"H": "Transport & storage"}, "maritime", {"_": "Port city"},
       "Transport and storage (PKD H), shown as a harbor only in towns with a seaport within 10 km.",
       "Inland towns with many transport jobs (logistics parks) do not get a harbor."),
    _d("theater_square", "Theater square", "#b07ce0", ["R"], {"R": "Arts, sport & recreation"}, "cultural",
       {"_": "Arts city"}, "Arts, entertainment and recreation (PKD R)."),
    _d("entertainment_complex", "Entertainment complex", "#d07a3a", ["I"], {"I": "Hotels & restaurants"},
       "entertainment", {"_": "Tourist town"}, "Accommodation and food service (PKD I)."),
    _d("government_plaza", "Government plaza", "#7a6a9a", ["O"], {"O": "Public administration & defence"},
       "governmental", {"_": "Government town"}, "Public administration and defence (PKD O)."),
    _d("aqueduct", "Aqueduct & power", "#3a9ab0", ["D", "E"], {"D": "Power & heat", "E": "Water & waste"},
       "utility", {"_": "Utility town"}, "Electricity, gas and heat supply, water and waste (PKD D, E)."),
    _d("encampment", "Encampment", "#6a7a4a", [], {}, "militaristic", {"_": "Garrison town"},
       "A military unit or base in the town (pl_soc_military).", "Not from PKD jobs: GUS counts soldiers in "
       "section O with civil servants."),
]
BY_ID = {d["id"]: d for d in CATALOG}

BADGE_RULES = [
    ("capital", "Capital city", "government_plaza", "Warszawa, the capital of Poland."),
    ("port", "Port city", "harbor", f"A seaport (pl_transport_ports) within {PORT_KM:.0f} km of the town."),
    ("copper", "Copper town", "industrial_zone", f"A copper mine or smelter (pl_mines) within {MINE_KM:.0f} km."),
    ("coal", "Coal town", "industrial_zone", f"A hard coal or lignite mine (pl_mines) within {MINE_KM:.0f} km."),
    ("refinery", "Refinery town", "industrial_zone",
     "A crude oil refinery in the town. Not awarded yet: no refinery dataset is in the pipeline."),
    ("auto", "Auto city", "industrial_zone",
     "Car making (PKD division 29) far above the national share. Not awarded: GUS publishes sections, not divisions, "
     "per powiat."),
    ("tech", "Tech city", "campus", f"Information and communication (PKD J) at least {TECH_LQ:g} times the national "
     f"share of workers and at least {TECH_SHARE:.0%} of them."),
    ("university", "University town", "campus",
     f"University students equal to at least {UNIVERSITY_SHARE:.0%} of residents (GUS, 31 December 2025)."),
    ("spa", "Spa town", "entertainment_complex", "The town's official name carries 'Zdrój' (spa)."),
    ("tourist", "Tourist town", "entertainment_complex",
     f"Accommodation and food service (PKD I) at least {TOURIST_LQ:g} times the national share of workers."),
    ("industrial", "Industrial town", "industrial_zone",
     f"Mining and manufacturing (PKD B, C) at least {INDUSTRIAL_LQ:g} times the national share of workers."),
    ("garrison", "Garrison town", "encampment",
     f"A military unit HQ or base (pl_soc_military) within {GARRISON_KM:.0f} km of the town."),
]
RULE_TEXT = (
    f"A district appears when its PKD sections employ at least {MIN_LQ:g} times the national share of workers "
    f"(location quotient) and at least {MIN_JOBS:,} people or {MIN_SHARE:.0%} of the town's workers, or when one of "
    f"its sections alone is at least {SPECIALTY_LQ:g} times the national share with {MIN_JOBS:,} workers. Districts "
    f"are ranked by workers above the national norm (workers - workers / LQ), up to {MAX_PER_CITY}. Workers are "
    "counted where the employer is (GUS, 31 December 2025), per powiat."
)
SCOPE_NOTE = ("GUS publishes workers by PKD section per powiat: a town without powiat rights shows its whole powiat.")


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def lq(emp, tot, nat_emp, nat_tot):
    if emp is None or not tot or not nat_emp or not nat_tot:
        return None
    return (emp / tot) / (nat_emp / nat_tot)


def evaluate(rec: dict, nat: dict, wet: bool) -> list[dict]:
    """The districts that pass the rule for one powiat's PKD record, strongest first."""
    tot = num(rec.get("workers_total"))
    out = []
    for d in CATALOG:
        if not d["sections"] or (d["id"] == "harbor" and not wet):
            continue
        emp = total(rec.get(f"workers_{s}") for s in d["sections"])
        nat_emp = total(nat.get(f"workers_{s}") for s in d["sections"])
        q = lq(emp, tot, nat_emp, nat["workers_total"])
        if q is None:
            continue
        best_sub = None
        for s in d["sections"]:
            se = num(rec.get(f"workers_{s}"))
            sq = lq(se, tot, nat.get(f"workers_{s}"), nat["workers_total"])
            if se is not None and sq is not None and sq > 1 and se >= MIN_JOBS and (best_sub is None or sq > best_sub[1]):
                best_sub = (s, sq, se)
        broad = q >= MIN_LQ and (emp >= MIN_JOBS or emp >= MIN_SHARE * tot)
        spec = best_sub is not None and best_sub[1] >= SPECIALTY_LQ
        if not (broad or spec):
            continue
        strength = emp - emp / q if q else 0
        if spec:
            strength = max(strength, best_sub[2] - best_sub[2] / best_sub[1])
        withheld = sum(1 for s in d["sections"] if rec.get(f"workers_{s}") is None)
        out.append({
            "id": d["id"], "lq": round(q, 2), "emp": round(emp), "share": round(emp / tot, 3),
            "sub": best_sub[0] if best_sub else None, "sub_lq": round(best_sub[1], 2) if best_sub else None,
            "sub_emp": round(best_sub[2]) if best_sub else None, "via": "broad" if broad else "specialty",
            "strength": round(strength), "suppressed": withheld, "lower_bound": withheld > 0,
        })
    out.sort(key=lambda x: -x["strength"])
    return out[:MAX_PER_CITY]


def near(town: dict, points: list[dict], kinds: set, km: float) -> dict | None:
    if town.get("lon") is None:
        return None
    best = None
    for p in points:
        if p.get("kind") in kinds and p.get("lon") is not None:
            d = haversine_km(town["lon"], town["lat"], p["lon"], p["lat"])
            if d <= km and (best is None or d < best[0]):
                best = (d, p)
    return best[1] if best else None


def badge_for(town: dict, rec: dict, nat: dict, ctx: dict) -> dict | None:
    """The first badge rule that holds, as {id, label, district, basis, text}."""
    tot = num(rec.get("workers_total"))
    jl = lq(num(rec.get("workers_J")), tot, nat.get("workers_J"), nat["workers_total"])
    il = lq(num(rec.get("workers_I")), tot, nat.get("workers_I"), nat["workers_total"])
    bc = total(rec.get(f"workers_{s}") for s in "BC")
    bcl = lq(bc, tot, total(nat.get(f"workers_{s}") for s in "BC"), nat["workers_total"])
    students = ctx["students"].get(town["gmina"])
    for rid, label, district, _ in BADGE_RULES:
        text, tpl, tvars = None, None, None
        if rid == "capital" and town.get("capital"):
            text = tpl = "Capital of Poland"
        elif rid == "port" and (p := near(town, ctx["ports"], {"seaport"}, PORT_KM)):
            text = tpl = p["name"]
        elif rid == "copper" and (p := near(town, ctx["mines"], {"copper_mine", "copper_smelter"}, MINE_KM)):
            text = p["name"]
        elif rid == "coal" and (p := near(town, ctx["mines"], {"coal_mine", "lignite_mine"}, MINE_KM)):
            text = p["name"]
        elif rid == "tech" and jl is not None and jl >= TECH_LQ and num(rec.get("workers_J")) / tot >= TECH_SHARE:
            tpl, tvars = "IT and telecoms: {lq} times the national share of workers", {"lq": round(jl, 1)}
        elif rid == "university" and students and town.get("gmina_population") and \
                students / town["gmina_population"] >= UNIVERSITY_SHARE:
            tpl = "{students} university students, {share}% of residents"
            tvars = {"students": students, "share": round(100 * students / town["gmina_population"])}
        elif rid == "spa" and "Zdrój" in town["name"]:
            text = tpl = "Spa town by name"
        elif rid == "tourist" and il is not None and il >= TOURIST_LQ:
            tpl, tvars = "Hotels and restaurants: {lq} times the national share of workers", {"lq": round(il, 1)}
        elif rid == "industrial" and bcl is not None and bcl >= INDUSTRIAL_LQ:
            tpl, tvars = "Mines and factories: {lq} times the national share of workers", {"lq": round(bcl, 1)}
        elif rid == "garrison" and (p := near(town, ctx["military"], ctx["mil_kinds"], GARRISON_KM)):
            text = p["props"].get("short") or p["name"]
        if tvars is not None:
            text = t(tpl, "en", **tvars)
        if text:
            # text is the English line; tpl and vars let the browser write it in the reader's language (t()).
            out = {"id": BY_ID[district]["badge"]["id"], "rule": rid, "label": label, "district": district,
                   "basis": "rule", "text": text}
            out["tpl"] = tpl or text  # a place name (a mine, a garrison) is its own template
            if tvars:
                out["vars"] = tvars
            return out
    return None


def _points(name: str) -> list[dict]:
    try:
        return load_interim(name).get("points") or []
    except FileNotFoundError:
        print(f"    ! interim {name} missing: its badges are not awarded")
        return []


def build() -> None:
    world = load_interim("_world")
    teryt = load_interim("pl_geo_teryt")
    units = Units(world, teryt)
    stats = Stats(["pl_stats_labour", "pl_stats_population"]).rekey(units)
    pkd = stats.rows("pl_stats_labour", "employment_pkd_powiat")
    cities = json.loads((WEB_DATA / "cities.json").read_text())
    places = {p["id"]: p for p in _points("pl_geo_places")}
    nat = {"workers_total": total(r.get("workers_total") for r in pkd.values())}
    for s in SECTIONS:
        nat[f"workers_{s}"] = total(r.get(f"workers_{s}") for r in pkd.values())
    ctx = {
        "ports": _points("pl_transport_ports"), "mines": _points("pl_mines"), "military": _points("pl_soc_military"),
        "mil_kinds": {"unit_land", "unit_air", "unit_navy", "unit_special", "unit_territorial", "air_base",
                      "naval_base"},
        "students": {g: r.get("students") for g, r in stats.rows("pl_stats_population", "university_students_city").items()},
    }
    out = {}
    badges: dict[str, int] = {}
    for c in cities:
        if not c.get("city_view"):
            continue
        rec = pkd.get(c["powiat"])
        if not rec or not num(rec.get("workers_total")):
            out[c["id"]] = None
            continue
        p = places.get(c["id"]) or {}
        town = {**c, "lon": p.get("lon"), "lat": p.get("lat")}
        wet = near(town, ctx["ports"], {"seaport"}, PORT_KM) is not None
        tot = rec["workers_total"]
        tops = []
        for s, (key, label) in SECTIONS.items():
            q = lq(num(rec.get(f"workers_{s}")), tot, nat[f"workers_{s}"], nat["workers_total"])
            if q is not None and num(rec.get(f"workers_{s}")) >= MIN_JOBS:
                tops.append({"pkd": s, "emp": rec[f"workers_{s}"], "lq": round(q, 2)})
        tops.sort(key=lambda t: -t["lq"])
        b = badge_for(town, rec, nat, ctx)
        if b:
            badges[b["label"]] = badges.get(b["label"], 0) + 1
        out[c["id"]] = {
            "emp": tot, "wage": c.get("wage"), "scope": c["name"] if c.get("kind") == "city" else units.powiat_label(c["powiat"]),
            "top": tops[:TOP], "districts": evaluate(rec, nat, wet), "badge": b,
        }
    write_web("districts.json", {
        "version": 1,
        "vintage": stats.vintage("pl_stats_labour") or "GUS",
        "year": stats.field_year("pl_stats_labour", "employment_pkd_powiat", "workers_total"),
        "sources": ["pl_stats_labour", "pl_stats_population", "pl_transport_ports", "pl_mines", "pl_soc_military"],
        "rule": {"min_lq": MIN_LQ, "min_jobs": MIN_JOBS, "min_share": MIN_SHARE, "specialty_lq": SPECIALTY_LQ,
                 "max_per_city": MAX_PER_CITY, "text": RULE_TEXT, "scope_note": SCOPE_NOTE},
        "badges": [{"id": rid, "label": label, "district": d, "rule": text} for rid, label, d, text in BADGE_RULES],
        "catalog": CATALOG,
        "industries": {s: {"title": label, "pl_emp": nat[f"workers_{s}"]} for s, (_, label) in SECTIONS.items()},
        "national": {"emp": nat["workers_total"]},
        "cities": out,
    })
    print(f"    {len(out)} City View towns; badges: " + ", ".join(f"{k} {v}" for k, v in sorted(badges.items())))


def check(web_dir: Path) -> list[tuple[str, str]]:
    p = Path(web_dir) / "districts.json"
    if not p.exists():
        return [("NOTE", "districts.json: missing (optional, skipped)")]
    out: list[tuple[str, str]] = []
    try:
        doc = json.loads(p.read_text())
    except ValueError as exc:
        return [("FAIL", f"districts.json: invalid JSON ({exc})")]
    for k in ("version", "vintage", "rule", "badges", "catalog", "cities"):
        if k not in doc:
            out.append(("FAIL", f"districts.json: missing key {k!r}"))
    if out:
        return out
    ids = [d.get("id") for d in doc["catalog"]]
    if ids != [d["id"] for d in CATALOG]:
        out.append(("FAIL", "districts.json: catalog ids differ from the contract"))
    for b in doc["badges"]:
        if not b.get("rule"):
            out.append(("FAIL", f"districts.json: badge {b.get('id')} has no published rule"))
    n = 0
    for cid, row in doc["cities"].items():
        if row is None:
            continue
        n += 1
        if len(row.get("districts", [])) > MAX_PER_CITY:
            out.append(("FAIL", f"districts.json: {cid} has more than {MAX_PER_CITY} districts"))
        for d in row.get("districts", []):
            if d.get("id") not in ids:
                out.append(("FAIL", f"districts.json: {cid} has an unknown district {d.get('id')}"))
        b = row.get("badge")
        if b and b.get("district") not in ids:
            out.append(("FAIL", f"districts.json: {cid} badge district {b.get('district')} not in the catalog"))
    out.append(("PASS", f"districts.json: {n} towns with districts"))
    return out

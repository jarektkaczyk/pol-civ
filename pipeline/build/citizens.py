"""Citizens of each City View town (citizens.json): rows of small figures by work, age, sex, education and origin.

Rows and their units (`scope` in each row says which one a town's row describes):

* workforce: workers by PKD section group, the town's powiat (a city with powiat rights is its own powiat),
  GUS 31 December 2025, by employer seat. A section GUS withholds counts as absent.
* age, sex: residents of the town's gmina (GUS 30 June 2026): the whole urban-rural gmina for a town inside one.
* education: per 1,000 residents aged 13+, with or without a higher-education diploma, the town's powiat (NSP 2021
  census share; the row's total is 1,000, not a head count).
* nativity: Ukrainian citizens with a PESEL UKR number registered in the powiat, per powiat residents.

Figures are rounded with the largest-remainder method so each row's figures add up exactly.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..core.paths import WEB_DATA
from ..core.store import load_interim, write_web
from .plstats import Stats, Units, num, total
from .yields import Economy

REQUIRES = ["_world", "pl_geo_teryt", "pl_stats_population", "pl_stats_labour", "pl_census_2021", "pl_foreigners",
            "cities.json"]
PRODUCES = ["citizens.json"]

FIGURES = {"workforce": 20, "age": 10, "sex": 10, "education": 10, "nativity": 10}
SPECIALIST_HIGH = 1.5
SPECIALIST_LOW = 0.67
MIN_SHARE = 0.01
MAX_HIGH, MAX_LOW = 4, 2


def _g(key, label, lines):
    return {"key": key, "label": label, "lines": lines}


GROUPS = {
    "workforce": [
        _g("farmer", "Farming, forestry & fishing", "PKD A"),
        _g("maker", "Factories, energy & transport", "PKD B, C, D, E, H"),
        _g("builder", "Construction", "PKD F"),
        _g("clerk", "Trade, finance & offices", "PKD G, K, L, N"),
        _g("engineer", "IT, science & engineering", "PKD J, M"),
        _g("scholar", "Education & the arts", "PKD P, R"),
        _g("healer", "Health & care", "PKD Q"),
        _g("service", "Hospitality, public service & other", "PKD I, O, S"),
    ],
    "age": [
        _g("child", "Children (0-14)", "age 0-14"),
        _g("young", "Young adults (15-29)", "age 15-29"),
        _g("midlife", "Adults (30-64)", "age 30-64"),
        _g("elder", "65 and older", "age 65+"),
    ],
    "sex": [_g("female", "Women", "female"), _g("male", "Men", "male")],
    "education": [
        _g("bachelors", "Higher education", "NSP 2021 higher_share"),
        _g("high_school", "No higher education", "100% - higher_share"),
    ],
    "nativity": [
        _g("foreign_born", "Ukrainians with PESEL UKR", "pesel_ukr"),
        _g("born_in_state", "Other residents", "population - pesel_ukr"),
    ],
}
WORK_SECTIONS = {"farmer": "A", "maker": "BCDEH", "builder": "F", "clerk": "GKLN", "engineer": "JM",
                 "scholar": "PR", "healer": "Q", "service": "IOS"}
AGES = {"child": range(0, 15), "young": range(15, 30), "midlife": range(30, 65), "elder": range(65, 200)}
ROW_LABELS = {
    "workforce": "Workers by sector",
    "age": "Residents by age",
    "sex": "Residents by sex",
    "education": "Per 1,000 residents aged 13+ by education (census 2021)",
    "nativity": "Residents by origin",
}
RULE_TEXT = ("A category is marked when its share is at least 1.5 times or at most 0.67 times the share in Poland; "
             "categories under 1% both here and nationally are skipped.")


def largest_remainder(values: dict[str, float], n: int) -> dict[str, int]:
    """Integer counts summing exactly to n, proportional to `values` (Hamilton's method). Ties go to the larger
    value, then the earlier key. All-zero input gives all zeros."""
    keys = list(values)
    vals = [max(0.0, float(values[k] or 0)) for k in keys]
    tot = sum(vals)
    if tot <= 0 or n <= 0:
        return {k: 0 for k in keys}
    quotas = [v * n / tot for v in vals]
    base = [math.floor(q) for q in quotas]
    order = sorted(range(len(keys)), key=lambda i: (-(quotas[i] - base[i]), -vals[i], i))
    for i in order[: n - sum(base)]:
        base[i] += 1
    return dict(zip(keys, base))


def make_row(name: str, counts: dict | None, scope: str, **extra) -> dict | None:
    """{total, counts, shares, figures, scope, ...} or None when a count is missing or the total is 0."""
    if not counts or any(v is None for v in counts.values()):
        return None
    counts = {k: round(v) for k, v in counts.items()}
    tot = sum(counts.values())
    if tot <= 0:
        return None
    return {"total": tot, "counts": counts, "shares": {k: round(v / tot, 3) for k, v in counts.items()},
            "figures": largest_remainder(counts, FIGURES[name]), "scope": scope, **extra}


def age_counts(rec: dict) -> dict | None:
    out = {k: 0 for k in AGES}
    for lo in range(0, 85, 5):
        v = num(rec.get(f"age_{lo}_{lo + 4}"))
        if v is None:
            return None
        out[next(k for k, r in AGES.items() if lo in r)] += v
    v = num(rec.get("age_85_plus"))
    if v is None:
        return None
    out["elder"] += v
    return out


def work_counts(pkd_recs: list[dict]) -> dict | None:
    if not pkd_recs:
        return None
    out = {}
    for k, letters in WORK_SECTIONS.items():
        out[k] = total(r.get(f"workers_{s}") for r in pkd_recs for s in letters)
        if out[k] is None:  # every section of the group withheld: the count is unknown, not 0
            return None
    return out if sum(out.values()) else None


def specialists(r: dict, nat: dict) -> list[dict]:
    hi, lo = [], []
    for name in GROUPS:
        a, b = r.get(name), nat.get(name)
        if not a or not b:
            continue
        for k, n in a["counts"].items():
            s, ns = n / a["total"], b["counts"][k] / b["total"]
            if not ns or (s < MIN_SHARE and ns < MIN_SHARE):
                continue
            ratio = s / ns
            item = {"row": name, "key": k, "share": round(s, 3), "national": round(ns, 3), "ratio": round(ratio, 2)}
            if ratio >= SPECIALIST_HIGH:
                hi.append(item)
            elif ratio <= SPECIALIST_LOW:
                lo.append(item)
    hi.sort(key=lambda x: -x["ratio"])
    lo.sort(key=lambda x: x["ratio"])
    return hi[:MAX_HIGH] + lo[:MAX_LOW]


class Rows:
    def __init__(self, units: Units, stats: Stats, econ: Economy):
        self.u, self.e = units, econ
        self.pop = stats.rows("pl_stats_population", "population")
        self.pkd = stats.rows("pl_stats_labour", "employment_pkd_powiat")
        self.edu = stats.rows("pl_census_2021", "education_powiat")
        self.ukr = stats.rows("pl_foreigners", "pesel_ukr_powiat")

    def powiat_pop(self, powiaty: list[str]) -> float | None:
        return total(self.e.pop.get(g) for p in powiaty for g in self.u.gminas_of_powiat.get(p, []))

    def for_units(self, gminas: list[str], powiaty: list[str], scope_g: str, scope_p: str) -> dict:
        recs = [self.pop.get(g) or {} for g in gminas]
        ages = [age_counts(r) for r in recs]
        age = None if any(a is None for a in ages) else {k: sum(a[k] for a in ages) for k in AGES}
        sex = {"female": total(r.get("female") for r in recs), "male": total(r.get("male") for r in recs)}
        ppop = self.powiat_pop(powiaty)
        edu = None
        shares = [(num((self.edu.get(p) or {}).get("higher_share")), self.powiat_pop([p])) for p in powiaty]
        if shares and all(s is not None and w for s, w in shares):
            # Per 1,000 residents aged 13+: NSP 2021 publishes the share for most powiaty but counts for few.
            hi = sum(s / 100 * w for s, w in shares) / sum(w for _, w in shares)
            edu = {"bachelors": 1000 * hi, "high_school": 1000 * (1 - hi)}
        ukr = total((self.ukr.get(p) or {}).get("pesel_ukr") for p in powiaty)
        nat = {"foreign_born": ukr, "born_in_state": ppop - ukr} if ukr is not None and ppop else None
        median = None
        if age:
            from .plstats import median_age
            pooled = {}
            for r in recs:
                for k, v in r.items():
                    if k.startswith("age_") and num(v) is not None:
                        pooled[k] = pooled.get(k, 0) + v
            median = median_age(pooled)
        out = {
            "workforce": make_row("workforce", work_counts([self.pkd[p] for p in powiaty if p in self.pkd]), scope_p),
            "age": make_row("age", age, scope_g, median=median),
            "sex": make_row("sex", sex if all(v is not None for v in sex.values()) else None, scope_g),
            "education": make_row("education", edu, scope_p),
            "nativity": make_row("nativity", nat, scope_p),
        }
        if out["education"]:
            out["education"]["bachelors_plus"] = out["education"]["shares"]["bachelors"]
        if out["nativity"]:
            out["nativity"]["foreign_born"] = round(out["nativity"]["counts"]["foreign_born"] / out["nativity"]["total"], 4)
        return out


def build() -> None:
    world = load_interim("_world")
    teryt = load_interim("pl_geo_teryt")
    units = Units(world, teryt)
    stats = Stats(["pl_stats_population", "pl_stats_labour", "pl_census_2021", "pl_foreigners", "pl_geo_fua",
                   "pl_stats_prosperity", "pl_gdp"])
    econ = Economy(units, stats)
    rows = Rows(units, stats, econ)
    cities = json.loads((WEB_DATA / "cities.json").read_text())
    national = rows.for_units(units.gminas, units.powiaty, "Poland", "Poland")
    out = {}
    for c in cities:
        if not c.get("city_view"):
            continue
        g, p = c["gmina"], c["gmina"][:4]
        gscope = c["name"] if c.get("scope") in ("city", "gmina") else f"gmina {units.gmina_name.get(g, c['name'])}"
        pscope = c["name"] if c.get("kind") == "city" else units.powiat_label(p)
        r = rows.for_units([g], [p], gscope, pscope)
        if all(v is None for v in r.values()):
            out[c["id"]] = None
            continue
        r["specialists"] = specialists(r, national)
        r["reliable"] = True
        out[c["id"]] = r
    national["specialists"] = []
    sources = [s for s in ("pl_stats_population", "pl_stats_labour", "pl_census_2021", "pl_foreigners") if stats.has(s)]
    write_web("citizens.json", {
        "version": 1,
        "vintage": "; ".join(v for v in (stats.vintage(s) for s in sources) if v),
        "year": econ.years["population"] or 2025,
        "sources": sources,
        "figures": FIGURES,
        "rows": ROW_LABELS,
        "groups": GROUPS,
        "rule": {"specialist_high": SPECIALIST_HIGH, "specialist_low": SPECIALIST_LOW, "min_share": MIN_SHARE,
                 "max_high": MAX_HIGH, "max_low": MAX_LOW, "text": RULE_TEXT},
        "national": national,
        "cities": out,
    })
    nulls = {k: sum(1 for r in out.values() if not r or r.get(k) is None) for k in GROUPS}
    print(f"    {len(out)} City View towns; rows without data: " + ", ".join(f"{k} {v}" for k, v in nulls.items()))


def _check_row(cid: str, r: dict, bad) -> None:
    for name in GROUPS:
        v = r.get(name)
        if v is None:
            continue
        keys = [g["key"] for g in GROUPS[name]]
        if list(v.get("counts", {})) != keys or list(v.get("shares", {})) != keys:
            bad(f"{cid}: {name} categories differ from groups")
            continue
        if any(x is None or x < 0 for x in v["counts"].values()):
            bad(f"{cid}: {name} has negative or null counts")
        if sum(v["counts"].values()) != v["total"]:
            bad(f"{cid}: {name} counts do not sum to the total")
        f = v.get("figures") or {}
        if list(f) != keys or sum(f.values()) != FIGURES[name]:
            bad(f"{cid}: {name} figures must cover every category and sum to {FIGURES[name]}")


def check(web_dir: Path) -> list[tuple[str, str]]:
    p = Path(web_dir) / "citizens.json"
    if not p.exists():
        return [("NOTE", "citizens.json: missing (optional, skipped)")]
    out: list[tuple[str, str]] = []
    bad = lambda m: out.append(("FAIL", f"citizens.json: {m}"))  # noqa: E731
    try:
        doc = json.loads(p.read_text())
    except ValueError as exc:
        return [("FAIL", f"citizens.json: invalid JSON ({exc})")]
    for k in ("version", "vintage", "year", "sources", "figures", "groups", "national", "cities"):
        if k not in doc:
            bad(f"missing key {k!r}")
    if out:
        return out
    if doc["figures"] != FIGURES:
        bad(f"figures {doc['figures']} != {FIGURES}")
    for name, gs in GROUPS.items():
        if [g.get("key") for g in doc["groups"].get(name, [])] != [g["key"] for g in gs]:
            bad(f"groups.{name} keys differ from the contract")
    _check_row("national", doc["national"], bad)
    cities = doc["cities"] if isinstance(doc["cities"], dict) else {}
    cp = Path(web_dir) / "cities.json"
    if cp.exists():
        try:
            view = {c.get("id") for c in json.loads(cp.read_text()) if isinstance(c, dict) and c.get("city_view")}
        except (ValueError, TypeError, AttributeError):
            view = None
        if view is not None and view != set(cities):
            bad(f"cities differ from the City View towns of cities.json ({len(view ^ set(cities))} ids)")
    for cid, r in cities.items():
        if r is not None:
            _check_row(cid, r, bad)
    if any(lv == "FAIL" for lv, _ in out):
        return out[:50]
    nulls = {k: sum(1 for r in cities.values() if not r or r.get(k) is None) for k in GROUPS}
    out.append(("PASS", f"citizens.json: {len(cities)} City View towns"))
    out.append(("NOTE", "citizens.json: towns without a row: " + ", ".join(f"{k} {v}" for k, v in nulls.items())))
    return out

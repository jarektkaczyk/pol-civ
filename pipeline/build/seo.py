"""Text pages and machine-readable indexes for search engines, generative engines and agents.

Runs after every other builder and reads only web/data/*.json. It writes, under web/:

    atlas/index.html, atlas/index.md            "Poland in numbers": national figures, the 16 voivodeships, every page
    atlas/<slug>/index.html, index.md           one page per voivodeship and per City View town (cities.json city_view)
    llms.txt, llms-full.txt                     llmstxt.org index, and every page as compact markdown
    sitemap.xml                                 every page with lastmod
    data/index.json                             the data catalogue: each public data file, its rows, vintage, publishers

Every number on a page comes from a web/data file; each page lists the publishers and years of its figures. A value
that is null in the data is left out of the page, never filled. The headline sentence of a page is the place's best
rank among its peers (16 voivodeships, or the towns of 20,000+ people), computed here.

Share images (web/og/<slug>.jpg) are rendered from the live app by scripts/og-shots.mjs, which reads the plan this
builder saves in the `_seo` interim. A page points to its own image when it exists, else to the main share image.
Set POLCIV_BUILD_DATE=YYYY-MM-DD to pin the "Last updated" date (default: today, UTC).
"""

from __future__ import annotations

import html
import json
import math
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from ..core.paths import WEB

REQUIRES = ["world.json", "cities.json", "states.json", "nation.json", "counties.json", "metros.json", "wonders.json",
            "districts.json", "resources.json", "sources.json"]
PRODUCES = ["index.json"]
RUN_LAST = True

SITE_URL = "https://softonsofa.com/pol-civ/"
SITE_NAME = "Polska"
APP_TITLE = "Polska: Poland as a strategy map built from real data"
AUTHOR = {"@type": "Person", "name": "Jarek Tkaczyk", "url": "https://softonsofa.com/"}
REPO_URL = "https://github.com/jarektkaczyk/pol-civ"
# Content Security Policy of the text pages (no inline script or style). web/index.html carries APP_CSP; check()
# compares it, so change both together. PostHog EU (analytics, cookieless) and Cloudflare Web Analytics are allowed.
_CSP_COMMON = ("default-src 'self'; script-src 'self' https://eu-assets.i.posthog.com https://static.cloudflareinsights.com; "
               "connect-src 'self' https://eu.i.posthog.com https://eu-assets.i.posthog.com https://cloudflareinsights.com; "
               "img-src 'self' data: blob:; font-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'")
ATLAS_CSP = _CSP_COMMON + "; style-src 'self'"
APP_CSP = _CSP_COMMON + "; style-src 'self' 'unsafe-inline'"  # the app sets inline styles from JS
MAIN_OG = "og-image.jpg"
# Cloudflare Web Analytics is injected by js/app/analytics.js (token in js/app/config.js) under the PostHog guard.
# No page may load the beacon directly: check() fails a page that does.
CF_BEACON_HOST = "static.cloudflareinsights.com/beacon"
NEARBY_KM = 30  # heritage sites listed on a town page: within this distance of the town
# Local paths and private names must never reach a public page (the pieces are joined so this file passes the
# release leak gate itself).
LEAK = re.compile("|".join(["beyond" + "indie", "/Us" + "ers/", "/private" + "/tmp", "~/pro" + "jects", "scratch" + "pad",
                            "claude" + "-501"]), re.I)

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


# --- small helpers ---------------------------------------------------------------------------------------------------

def slug(name: str) -> str:
    """ASCII slug: Polish letters folded (ł to l first, since NFD does not decompose it), marks stripped."""
    s = str(name).replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def fmt_int(v) -> str:
    return f"{round(v):,}"


def fmt_big(v, unit: str = "") -> str:
    """37.3 million, 3.92 trillion zł."""
    tail = f" {unit}" if unit else ""
    for size, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(v) >= size:
            x = v / size
            return f"{x:.3g} {word}{tail}" if x < 100 else f"{x:.0f} {word}{tail}"
    return f"{fmt_int(v)}{tail}"


def fmt_pct(frac, digits: int = 1, signed: bool = False) -> str:
    s = f"{frac * 100:.{digits}f}%"
    return ("+" + s) if signed and frac > 0 else s


def fmt_pln(v) -> str:
    return f"{fmt_int(v)} zł"


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def the_nth(rank: int, word: str) -> str:
    """the highest / the 3rd highest."""
    return f"the {word}" if rank == 1 else f"the {ordinal(rank)} {word}"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def md_esc(s) -> str:
    return str(s).replace("|", "\\|")


def build_date() -> str:
    pinned = os.environ.get("POLCIV_BUILD_DATE", "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", pinned):
        return pinned
    return datetime.now(timezone.utc).date().isoformat()


def human_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d} {MONTHS[m - 1]} {y}"


def _when(text: str | None, fallback) -> str:
    """The first '31 December 2025' or 'May 2026' phrase in a description, else the fallback year."""
    text = text or ""
    m = re.search(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})", text)
    if m:
        return m.group(0)
    m = re.search(r"\b(" + "|".join(MONTHS) + r") (\d{4})", text)
    if m:
        return m.group(0)
    return str(fallback) if fallback is not None else ""


def _iso(day_month_year: str) -> str | None:
    m = re.fullmatch(r"(\d{1,2}) (\w+) (\d{4})", day_month_year or "")
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"


def rank_of(value, values, high: bool) -> int:
    """Competition rank of value among values (1 = highest when high, else lowest)."""
    return 1 + sum(1 for v in values if (v > value if high else v < value))


# --- data model ------------------------------------------------------------------------------------------------------

def _load(web_data: Path, name: str):
    p = web_data / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except ValueError:
        return None


class Data:
    """The web/data files this builder reads, plus lookups."""

    def __init__(self, web_data: Path):
        self.dir = Path(web_data)
        self.world = _load(self.dir, "world.json") or {}
        self.cities = _load(self.dir, "cities.json") or []
        self.states = _load(self.dir, "states.json") or []
        self.nation_doc = _load(self.dir, "nation.json") or {}
        self.nation = self.nation_doc.get("nation") or {}
        self.counties = _load(self.dir, "counties.json")
        self.metros_doc = _load(self.dir, "metros.json") or {}
        self.wonders_doc = _load(self.dir, "wonders.json") or {}
        self.districts = _load(self.dir, "districts.json") or {}
        self.resources = _load(self.dir, "resources.json") or {}
        self.sources = _load(self.dir, "sources.json") or []
        self.lenses = _load(self.dir, "lenses.json") or {}
        self.source_by_id = {s.get("id"): s for s in self.sources if isinstance(s, dict)}
        self.city_by_id = {c["id"]: c for c in self.cities if isinstance(c, dict) and c.get("id")}
        self.metro_by_id = {m["id"]: m for m in self.metros_doc.get("metros", []) if m.get("id")}
        self.state_by_abbr = {s.get("abbr"): s for s in self.states}
        self.state_by_fips = {s.get("fips"): s for s in self.states}
        self.gmina = {}
        self.field = {}
        if isinstance(self.counties, dict):
            cols = self.counties.get("columns") or []
            self.gmina = {r[0]: dict(zip(cols, r)) for r in self.counties.get("rows", [])}
            self.field = {f.get("key"): f for f in self.counties.get("fields", [])}
        self.view_towns = [c for c in self.cities if c.get("city_view")]
        proj = self.world.get("projection") or {}
        self._proj = None
        if {"min_x", "max_y"} <= set(proj):
            from ..core.geo import MapProjection

            self._proj = MapProjection(proj["min_x"], proj["max_y"], proj.get("margin", 0))
        cat = {}
        for lens in self.lenses.get("lenses", []):
            for c in lens.get("categories") or []:
                cat[(lens.get("id"), c.get("id"))] = c.get("name")
        self.category = cat

    # dates of the figures, read from the data's own descriptions
    def when(self, key: str) -> str:
        years = self.nation_doc.get("years") or {}
        if key == "population":
            v = (self.source_by_id.get("pl_stats_population") or {}).get("vintage") or self.nation_doc.get("vintage")
            return _when(v, years.get("population"))
        if key == "workers":
            return f"31 December {years['workers']}" if years.get("workers") else ""
        if key in ("wage", "unemployment"):
            return _when((self.field.get(key) or {}).get("description"), years.get(key))
        if key == "pit":
            return f"{years.get('pit')} plan" if years.get("pit") else "plan"
        if key in self.field:
            return _when(self.field[key].get("description"), None)
        return ""

    def lonlat(self, x, y):
        if self._proj is None or num(x) is None or num(y) is None:
            return None
        lon, lat = self._proj.inverse(x, y)
        return round(lon, 4), round(lat, 4)

    def state_centre(self, index: int):
        """Mean position of the voivodeship's hexes (map km)."""
        grid = self.world.get("grid") or {}
        owner = self.world.get("owner") or []
        cols, r = grid.get("cols"), grid.get("radius")
        if not cols or not r:
            return None
        xs = ys = n = 0
        for i, o in enumerate(owner):
            if o == index:
                col, row = i % cols, i // cols
                xs += math.sqrt(3) * r * (col + 0.5 * (row & 1))
                ys += 1.5 * r * row
                n += 1
        return (xs / n, ys / n) if n else None

    def publisher(self, sid: str) -> str:
        return (self.source_by_id.get(sid) or {}).get("publisher") or sid


# --- page model ------------------------------------------------------------------------------------------------------
# A page is a dict: slug, path ("atlas/krakow/"), kind ("index" | "voivodeship" | "town"), title, description, h1,
# lede, paras [str], open (deep link), sections [{h2, rows | items | paras}], sources [(source id | None, text)],
# crumbs [(name, path)], place (JSON-LD node or None), og ("og/krakow.jpg"), og_number (text for the share image),
# focus (for the share image: {"city": id} | {"state": abbr}).
# Table rows are (label, value text, when text, source id). List items are (text, link path or None, note).


class Sources:
    """Collects the sources a page cites, in order of first use."""

    def __init__(self, d: Data):
        self.d = d
        self.ids: list[str] = []
        self.extra: list[tuple[str, str]] = []

    def use(self, sid: str | None):
        if sid and sid not in self.ids:
            self.ids.append(sid)
        return sid

    def page(self, text: str, url: str):
        if (text, url) not in self.extra:
            self.extra.append((text, url))

    def lines(self) -> list[tuple[str, str | None]]:
        out = []
        for sid in self.ids:
            s = self.d.source_by_id.get(sid)
            if not s:  # not in sources.json: nothing to cite by name
                continue
            pub = s.get("publisher") or sid
            title = s.get("title") or ""
            vint = s.get("vintage") or ""
            out.append((f"{pub}: {title}" + (f" ({vint})" if vint else ""), s.get("homepage")))
        out.extend((t, u) for t, u in self.extra)
        return out


def _row(src: Sources, label, value, when, sid):
    return (label, value, when, src.use(sid))


def heritage_items(d: Data, src: Sources, wonders) -> list[tuple[str, str | None, str]]:
    """List items for heritage sites, parks, universities and landmarks. Memorials are named as memorials."""
    kind_src = {"unesco": "pl_soc_heritage", "memorial": "pl_soc_heritage", "natural": "pl_soc_parks",
                "university": "pl_soc_universities"}
    out = []
    for wd in wonders:
        kind = wd.get("kind")
        m = wd.get("metrics") or {}
        name = wd.get("name") or wd.get("short")
        if kind == "memorial":
            note = f"Memorial and museum, UNESCO World Heritage since {m['inscribed']}" if m.get("inscribed") else "Memorial and museum"
        elif kind == "unesco":
            note = f"UNESCO World Heritage site since {m['inscribed']}" if m.get("inscribed") else "UNESCO World Heritage site"
        elif kind == "natural":
            vis = num(m.get("visits"))
            note = "National park" + (f", {fmt_int(vis)} visits in {m.get('year')}" if vis and m.get("year") else "")
            latest = num(m.get("visits_latest"))
            if latest and m.get("latest_year"):
                note = (f"National park, {fmt_int(latest)} visits in {m['latest_year']}"
                        + (f" ({fmt_int(vis)} in {m.get('year')})" if vis and m.get("year") else ""))
        elif kind == "university":
            st = num(m.get("students"))
            note = "University" + (f", {fmt_int(st)} students on 31 December {m.get('students_year')}" if st and m.get("students_year") else f", {fmt_int(st)} students" if st else "")
        else:
            rec, val = m.get("record"), num(m.get("value"))
            note = rec or "Landmark"
            if val is not None:
                note += f": {fmt_int(val) if val >= 1000 or float(val).is_integer() else val} {m.get('unit') or ''}".rstrip()
                if m.get("year"):
                    note += f" ({m['year']})"
        sid = kind_src.get(kind)
        if kind == "landmark":
            wid = wd.get("id") or ""
            sid = ("pl_transport_ports" if "seaport" in wid else "pl_transport_airports" if "airport" in wid
                   else "pl_energy_plants" if "power" in wid else None)
            if sid is None and wd.get("ref"):
                src.page(f"{name}: {wd['ref'].split('/')[2]}", wd["ref"])
        src.use(sid)
        out.append((name, None, note))
    return out


def _town_scope(c: dict, g: dict | None) -> str:
    """Words for the unit of a gmina-level figure: the town itself, or its whole urban-rural gmina."""
    if c.get("scope") == "urban-rural gmina":
        return f" (whole gmina of {c['name']})"
    return ""


def _powiat_words(c: dict, g: dict | None) -> str:
    if c.get("kind") == "city":
        return c["name"]
    lab = (g or {}).get("powiat") or "its powiat"
    return lab


# headline metrics for towns: (key, value getter, allow high, allow low, sentence, source id, sentence needs the count)
STRIKING_RANK = 10  # a headline other than size needs a top-10 place at either end


def _town_metrics(d: Data):
    def g(c, k):
        return num((d.gmina.get(c.get("gmina")) or {}).get(k))

    n_all = len(d.view_towns)
    peer = f"of the {n_all} Polish towns with 20,000 or more people"
    peer_any = f"for any of the {n_all} Polish towns with 20,000 or more people"

    def who(c):
        """Gmina-level figures of a town inside an urban-rural gmina describe the whole gmina."""
        return f"the gmina of {c['name']}" if c.get("scope") == "urban-rural gmina" else c["name"]

    def around(c):
        return c["name"] if c.get("kind") == "city" else f"{c['name']} ({_powiat_words(c, d.gmina.get(c.get('gmina')))})"

    def cap(t):
        return t[:1].upper() + t[1:]

    def s_growth(c, v, r, high):
        if high:
            return f"{c['name']} grew by {fmt_pct(v)} between 2015 and 2025, {the_nth(r, 'fastest growth')} {peer}."
        return f"{c['name']} lost {fmt_pct(-v)} of its residents between 2015 and 2025, {the_nth(r, 'steepest fall')} {peer}."

    def s_wage(c, v, r, high):
        word = "highest" if high else "lowest"
        lead = f"The average gross wage in {c['name']}" if c.get("kind") == "city" else f"The average gross wage around {around(c)}"
        return f"{lead} was {fmt_pln(v)} a month in {d.when('wage')}, {the_nth(r, word)} {peer_any}."

    def s_unemp(c, v, r, high):
        word = "highest" if high else "lowest"
        lead = f"Registered unemployment in {c['name']}" if c.get("kind") == "city" else f"Registered unemployment around {around(c)}"
        return f"{lead} was {fmt_pct(v)} in {d.when('unemployment')}, {the_nth(r, word)} {peer_any}."

    def s_pit(c, v, r, high):
        word = "highest" if high else "lowest"
        year = (d.nation_doc.get("years") or {}).get("pit")
        return (f"{cap(who(c))} expects {fmt_pln(v)} per resident from its share of personal income tax"
                + (f" in {year}" if year else "") + f", {the_nth(r, word)} {peer}.")

    def s_age(c, v, r, high):
        word = "oldest" if high else "youngest"
        return f"{cap(who(c))} has {the_nth(r, word)} population {peer}: a median age of {v:.1f} years."

    def s_pm(c, v, r, high, n):
        word = "most polluted" if high else "cleanest"
        return (f"{c['name']} has {the_nth(r, word)} air of the {n} towns of 20,000+ with a measuring station within 25 km: "
                f"PM2.5 averaged {v:.1f} µg/m³ in 2025 at the nearest station.")

    def s_turnout(c, v, r, high):
        word = "highest" if high else "lowest"
        return f"Turnout in {who(c)} was {fmt_pct(v)} in the presidential runoff of 1 June 2025, {the_nth(r, word)} {peer}."

    def s_students(c, v, r, high, n):
        return (f"{c['name']} has {fmt_int(v)} university students per 1,000 residents, {the_nth(r, 'highest share')} "
                f"of the {n} towns of 20,000+ with a university.")

    return [
        ("growth", lambda c: num(c.get("growth")), True, True, s_growth, "pl_stats_population", False),
        ("wage", lambda c: num(c.get("wage")), True, True, s_wage, "pl_stats_labour", False),
        ("unemployment", lambda c: num(c.get("unemployment")), True, True, s_unemp, "pl_stats_labour", False),
        ("pit", lambda c: num(c.get("pit_per_person")), True, True, s_pit, "pl_stats_prosperity", False),
        ("pm25", lambda c: g(c, "pm25"), True, True, s_pm, "pl_soc_air", True),
        ("students", lambda c: g(c, "students"), True, False, s_students, "pl_stats_population", True),
        ("median_age", lambda c: g(c, "median_age"), True, True, s_age, "pl_stats_population", False),
        ("turnout", lambda c: g(c, "turnout_2025"), True, True, s_turnout, "pl_soc_elections", False),
    ]


def town_word(c: dict) -> str:
    """'city' for a city with powiat rights or a town of 100,000 or more residents, else 'town'."""
    return "city" if c.get("kind") == "city" or (num(c.get("population")) or 0) >= 100_000 else "town"


def town_headline(d: Data, c: dict) -> tuple[str, str | None]:
    """(sentence, source id): the town's most striking true fact.

    Its size rank among all towns, or a top-10 place at either end of a metric among the towns of 20,000+ (the
    City View towns), whichever rank is better; size wins a tie. A town with no top-10 place leads with its size.
    """
    pr = (c.get("ranks") or {}).get("population")
    pop = num(c.get("population"))
    when = d.when("population")
    best = None
    if pr and pop:
        if c.get("capital"):
            text = f"{c['name']} is the capital and the largest city of Poland, with {fmt_int(pop)} residents on {when}."
        else:
            text = f"{c['name']} is {the_nth(pr, 'largest ' + town_word(c))} in Poland, with {fmt_int(pop)} residents on {when}."
        best = (pr, 0, text, "pl_geo_places")
    for order, (key, get, hi, lo, sentence, sid, needs_n) in enumerate(_town_metrics(d), start=1):
        v = get(c)
        if v is None:
            continue
        vals = [x for x in (get(t) for t in d.view_towns) if x is not None]
        for high in (True, False):
            if (high and not hi) or (not high and not lo):
                continue
            if key == "growth" and ((high and v <= 0) or (not high and v >= 0)):
                continue
            r = rank_of(v, vals, high)
            if r > STRIKING_RANK:
                continue
            if best is None or (r, order) < best[:2]:
                text = sentence(c, v, r, high, len(vals)) if needs_n else sentence(c, v, r, high)
                best = (r, order, text, sid)
    if best and best[1] == 0 and best[0] > 20 and pop:
        g = num(c.get("growth"))
        tail = (f" Between 2015 and 2025 it grew by {fmt_pct(g)}." if g and g > 0
                else f" Between 2015 and 2025 it lost {fmt_pct(-g)} of its residents." if g and g < 0 else "")
        return f"{c['name']} had {fmt_int(pop)} residents on {when}.{tail}", "pl_geo_places"
    return (best[2], best[3]) if best else (f"{c['name']} is a {town_word(c)} in Poland.", None)


def _state_metrics(d: Data):
    gdps = [num(s.get("gdp")) for s in d.states]
    total = sum(x for x in gdps if x) if all(gdps) else None

    def cap(s, k):
        caps = s.get("capitals") or []
        g = d.gmina.get(caps[0]["gmina"]) if caps else None
        return num((g or {}).get(k))

    def gdp_share(s):
        g = num(s.get("gdp"))
        return g / total if g and total else None

    def s_pop(s, v, r, high):
        word = "most populous" if high else "least populous"
        return f"{s['name']} is {the_nth(r, word)} voivodeship, with {fmt_int(v)} residents on {d.when('population')}."

    def s_growth(s, v, r, high):
        if v > 0:
            return f"{s['name']} grew by {fmt_pct(v)} between 2015 and 2025, {the_nth(r, 'fastest growth')} of the 16 voivodeships."
        if high:
            return f"{s['name']} lost {fmt_pct(-v)} of its residents between 2015 and 2025, {the_nth(r, 'smallest fall')} of the 16 voivodeships."
        return f"{s['name']} lost {fmt_pct(-v)} of its residents between 2015 and 2025, {the_nth(r, 'steepest fall')} of the 16 voivodeships."

    def s_gdp(s, v, r, high):
        word = "largest economy" if high else "smallest economy"
        return (f"{s['name']} is {the_nth(r, word)} of the 16 voivodeships: {fmt_pct(v)} of Poland's GDP in "
                f"{s.get('gdp_year')}, {fmt_big(s['gdp'], 'zł')}.")

    def s_wage(s, v, r, high):
        word = "highest" if high else "lowest"
        return f"{s['name']} has {the_nth(r, word)} average gross wage of the 16 voivodeships: {fmt_pln(v)} a month in {d.when('wage')}."

    def s_unemp(s, v, r, high):
        word = "highest" if high else "lowest"
        return f"{s['name']} has {the_nth(r, word)} registered unemployment of the 16 voivodeships: {fmt_pct(v)} in {d.when('unemployment')}."

    def s_pit(s, v, r, high):
        word = "highest" if high else "lowest"
        return f"{s['name']} has {the_nth(r, word)} personal income tax revenue per resident of the 16 voivodeships: {fmt_pln(v)} planned for {d.nation_doc.get('years', {}).get('pit', '')}."

    def s_forest(s, v, r, high):
        word = "most" if high else "least"
        return f"{s['name']} has {the_nth(r, word)} tree cover of the 16 voivodeships: {fmt_pct(v, 0)} of its land."

    def s_life(s, v, r, high):
        word = "longest" if high else "shortest"
        return f"Women in {s['name']} have {the_nth(r, word)} life expectancy of the 16 voivodeships: {v:.1f} years at birth in 2025."

    def s_tour(s, v, r, high):
        return f"{s['name']} has {the_nth(r, 'most')} tourist nights per resident of the 16 voivodeships: {v:.1f} in 2025."

    return [
        ("population", lambda s: num(s.get("population")), True, True, s_pop, "pl_stats_population"),
        ("gdp", gdp_share, True, False, s_gdp, "pl_gdp"),
        ("growth", lambda s: num(s.get("growth")), True, True, s_growth, "pl_stats_population"),
        ("wage", lambda s: num(s.get("wage")), True, True, s_wage, "pl_stats_labour"),
        ("unemployment", lambda s: num(s.get("unemployment")), True, True, s_unemp, "pl_stats_labour"),
        ("pit", lambda s: num(s.get("pit_per_person")), True, True, s_pit, "pl_stats_prosperity"),
        ("forest", lambda s: num((s.get("land") or {}).get("forest")), True, True, s_forest, "pl_geo_worldcover"),
        ("life_f", lambda s: cap(s, "life_f"), True, True, s_life, "pl_stats_population"),
        ("tourism", lambda s: cap(s, "tourism"), True, False, s_tour, "pl_stats_prosperity"),
    ], gdp_share, cap


def state_headline(d: Data, s: dict) -> tuple[str, str | None]:
    metrics, _, _ = _state_metrics(d)
    best = None
    for order, (key, get, hi, lo, sentence, sid) in enumerate(metrics):
        v = get(s)
        if v is None:
            continue
        vals = [x for x in (get(t) for t in d.states) if x is not None]
        for high in (True, False):
            if (high and not hi) or (not high and not lo):
                continue
            r = rank_of(v, vals, high)
            if best is None or (r, order) < best[:2]:
                best = (r, order, sentence(s, v, r, high), sid)
    return (best[2], best[3]) if best else (f"{s['name']} is a voivodeship of Poland.", None)


# --- pages -----------------------------------------------------------------------------------------------------------

def page_paths(d: Data) -> tuple[dict, dict]:
    """Slugs for voivodeships (by abbr) and towns (by id); a clash gets the voivodeship slug appended."""
    taken: set[str] = set()
    st, tw = {}, {}
    for s in d.states:
        sl = slug(s["name"])
        st[s["abbr"]] = sl
        taken.add(sl)
    for c in sorted(d.view_towns, key=lambda c: -(num(c.get("population")) or 0)):
        sl = slug(c["name"])
        if sl in taken:
            sv = d.state_by_fips.get(c.get("voivodeship")) or {}
            sl = f"{sl}-{slug(sv.get('name', c.get('voivodeship', '')))}"
        k = 2
        base = sl
        while sl in taken:
            sl = f"{base}-{k}"
            k += 1
        tw[c["id"]] = sl
        taken.add(sl)
    return st, tw


def _place_node(url: str, name: str, typ: str, lonlat, parent: dict | None, pop, pop_date: str | None, teryt: str | None,
                extra_names=None) -> list[dict]:
    """The place node, plus an Observation (a QuantitativeValue with a date) for its population."""
    node = {"@type": typ, "@id": url + "#place", "name": name, "url": url}
    if extra_names:
        node["alternateName"] = extra_names
    if parent:
        node["containedInPlace"] = parent
    if lonlat:
        node["geo"] = {"@type": "GeoCoordinates", "longitude": lonlat[0], "latitude": lonlat[1]}
    if teryt:
        node["identifier"] = {"@type": "PropertyValue", "propertyID": "TERYT", "value": teryt}
    out = [node]
    if pop is not None:
        node["additionalProperty"] = {"@type": "PropertyValue", "propertyID": "population", "name": "Population",
                                      "value": pop, "unitText": "residents"}
        obs = {"@type": "Observation", "@id": url + "#population", "name": f"Population of {name}",
               "observationAbout": {"@id": url + "#place"}, "variableMeasured": "population", "value": pop,
               "unitText": "residents"}
        if pop_date:
            obs["observationDate"] = pop_date
        out.append(obs)
    return out


def _jsonld(page: dict, date: str) -> dict:
    url = SITE_URL + page["path"]
    crumbs = [{"@type": "ListItem", "position": i + 1, "name": n, "item": SITE_URL + p} for i, (n, p) in enumerate(page["crumbs"])]
    web = {"@type": "WebPage", "@id": url, "url": url, "name": page["title"], "description": page["description"],
           "inLanguage": "en", "dateModified": date, "author": AUTHOR,
           "isPartOf": {"@type": "WebSite", "@id": SITE_URL + "#website", "name": SITE_NAME, "url": SITE_URL},
           "breadcrumb": {"@id": url + "#breadcrumb"},
           "primaryImageOfPage": {"@type": "ImageObject", "url": SITE_URL + page["og"]}}
    graph = [web, {"@type": "BreadcrumbList", "@id": url + "#breadcrumb", "itemListElement": crumbs}]
    if page.get("place"):
        web["about"] = {"@id": page["place"][0]["@id"]}
        graph.extend(page["place"])
    return {"@context": "https://schema.org", "@graph": graph}


def _og_for(web: Path, sl: str) -> str:
    rel = f"og/{sl}.jpg"
    if (web / rel).exists():
        return rel
    return MAIN_OG if (web / MAIN_OG).exists() else "og-image.png"


def build_pages(d: Data, web: Path) -> list[dict]:
    st_slug, tw_slug = page_paths(d)
    pages = [index_page(d, web, st_slug, tw_slug)]
    for i, s in enumerate(d.states):
        pages.append(state_page(d, web, i, s, st_slug, tw_slug))
    for c in sorted(d.view_towns, key=lambda c: -(num(c.get("population")) or 0)):
        pages.append(town_page(d, web, c, st_slug, tw_slug))
    return pages


def index_page(d: Data, web: Path, st_slug: dict, tw_slug: dict) -> dict:
    src = Sources(d)
    n = d.nation
    pop, growth = num(n.get("population")), num(n.get("growth"))
    when_pop = d.when("population")
    rows = []
    if pop:
        rows.append(_row(src, "Population", fmt_int(pop), when_pop, "pl_stats_population"))
    if growth is not None:
        series = n.get("pop_series") or {}
        rows.append(_row(src, "Change since 2015", fmt_pct(growth, 1, True) + (f" (from {fmt_int(series['2015'])})" if series.get("2015") else ""),
                         "2015 to 2025", "pl_stats_population"))
    if num(n.get("gdp")):
        rows.append(_row(src, "GDP", fmt_big(n["gdp"], "zł"), str(n.get("gdp_year", "")), "pl_gdp"))
        if pop:
            rows.append(_row(src, "GDP per resident", fmt_pln(n["gdp"] / pop), f"{n.get('gdp_year')} GDP, {when_pop[-4:]} residents", "pl_gdp"))
    if num(n.get("wage")):
        rows.append(_row(src, "Average gross wage", f"{fmt_pln(n['wage'])} a month", d.when("wage"), "pl_stats_labour"))
    if num(n.get("unemployment")) is not None:
        rows.append(_row(src, "Registered unemployment", fmt_pct(n["unemployment"]), d.when("unemployment"), "pl_stats_labour"))
    if num(n.get("employed")):
        rows.append(_row(src, "People working", fmt_int(n["employed"]), d.when("workers"), "pl_stats_labour"))
    if num(n.get("pit_per_person")):
        rows.append(_row(src, "Personal income tax revenue of the gminas per resident", fmt_pln(n["pit_per_person"]), d.when("pit"), "pl_stats_prosperity"))
    wn = d.wonders_doc.get("national") or {}
    if wn.get("unesco_properties"):
        rows.append(_row(src, "UNESCO World Heritage properties", fmt_int(wn["unesco_properties"]), "2026", "pl_soc_heritage"))
    if wn.get("national_parks"):
        rows.append(_row(src, "National parks", fmt_int(wn["national_parks"]), str(wn.get("park_visits_year", "")), "pl_soc_parks"))
    if wn.get("park_visits"):
        rows.append(_row(src, "Visits to national parks", fmt_int(wn["park_visits"]), str(wn.get("park_visits_year", "")), "pl_soc_parks"))
    counts = []
    if d.gmina:
        counts.append(f"{len(d.gmina):,} gminas")
    powiaty = _load(d.dir, "powiaty.json")
    if isinstance(powiaty, dict) and powiaty.get("rows"):
        counts.append(f"{len(powiaty['rows'])} powiats")
    if d.cities:
        counts.append(f"{len(d.cities):,} towns")
    src.use("pl_geo_teryt")

    # voivodeship table (static, by population)
    metrics, gdp_share, cap = _state_metrics(d)
    vrows = []
    for s in sorted(d.states, key=lambda s: -(num(s.get("population")) or 0)):
        caps = ", ".join(c["name"] for c in s.get("capitals") or [])
        vrows.append([(s["name"], f"{st_slug[s['abbr']]}/"), caps,
                      fmt_int(s["population"]) if num(s.get("population")) else "",
                      fmt_pct(s["growth"], 1, True) if num(s.get("growth")) is not None else "",
                      fmt_pct(gdp_share(s)) if gdp_share(s) else "",
                      fmt_pln(s["wage"]) if num(s.get("wage")) else "",
                      fmt_pct(s["unemployment"]) if num(s.get("unemployment")) is not None else ""])
    gdp_year = next((s.get("gdp_year") for s in d.states if s.get("gdp_year")), "")
    vtable = {"head": ["Voivodeship", "Capital", f"Population, {when_pop}", "Change 2015-2025", f"Share of GDP, {gdp_year}",
                       f"Average wage, {d.when('wage')}", f"Unemployment, {d.when('unemployment')}"], "rows": vrows}
    for sid in ("pl_gdp", "pl_stats_labour"):
        src.use(sid)

    towns_by_state = []
    for s in sorted(d.states, key=lambda s: s["name"]):
        items = [(t["name"], f"{tw_slug[t['id']]}/", fmt_int(t["population"]) if num(t.get("population")) else "")
                 for t in sorted((t for t in d.view_towns if t.get("voivodeship") == s.get("fips")), key=lambda t: t["name"])]
        towns_by_state.append({"h3": s["name"], "items": items})

    largest = max(d.states, key=lambda s: num(s.get("population")) or 0) if d.states else None
    lede = (f"Poland had {fmt_int(pop)} residents on {when_pop}." + (f" Between 2015 and 2025 the population fell by {fmt_pct(-growth)}." if growth and growth < 0
            else f" Between 2015 and 2025 the population grew by {fmt_pct(growth)}." if growth else "")) if pop else "Poland in numbers."
    paras = []
    if counts:
        paras.append(f"The country has 16 voivodeships, {', '.join(counts[:-1])} and {counts[-1]}." if len(counts) > 1 else f"The country has 16 voivodeships and {counts[0]}.")
    if largest and num(n.get("gdp")):
        paras.append(f"Its GDP was {fmt_big(n['gdp'], 'zł')} in {n.get('gdp_year')}. {largest['name']}, around Warszawa, is the largest "
                     f"voivodeship by population and produced {fmt_pct(gdp_share(largest))} of the national GDP in {largest.get('gdp_year')}."
                     if gdp_share(largest) else f"Its GDP was {fmt_big(n['gdp'], 'zł')} in {n.get('gdp_year')}.")
    paras.append("Each voivodeship and each town of 20,000 or more people has its own page below, with its figures and their sources.")

    title = "Poland in numbers: population, economy and the 16 voivodeships"
    desc = (f"Poland had {fmt_int(pop)} residents on {when_pop}" + (f" and a GDP of {fmt_big(n['gdp'], 'zł')} in {n.get('gdp_year')}" if num(n.get("gdp")) else "")
            + f". Figures for the 16 voivodeships and {len(d.view_towns)} towns, with sources.") if pop else "Poland in numbers."
    pop_iso = _iso(when_pop)
    place = _place_node(SITE_URL + "atlas/", "Poland", "Country", None, None, pop, pop_iso, None, ["Polska"])
    return {
        "slug": "atlas", "path": "atlas/", "kind": "index", "title": title, "description": desc, "h1": "Poland in numbers",
        "lede": lede, "paras": paras, "open": ("Open the map", ""), "crumbs": [(SITE_NAME, ""), ("Atlas", "atlas/")],
        "sections": [
            {"h2": "National figures", "rows": rows},
            {"h2": "The 16 voivodeships", "table": vtable},
            {"h2": "Towns of 20,000 or more people", "groups": towns_by_state},
        ],
        "sources": src.lines(), "place": place, "og": MAIN_OG if (web / MAIN_OG).exists() else "og-image.png",
        "og_number": f"{fmt_big(pop)} people" if pop else "", "focus": {},
    }


def state_page(d: Data, web: Path, idx: int, s: dict, st_slug: dict, tw_slug: dict) -> dict:
    src = Sources(d)
    sl = st_slug[s["abbr"]]
    name = s["name"]
    lede, lede_sid = state_headline(d, s)
    src.use(lede_sid)
    metrics, gdp_share, cap = _state_metrics(d)
    when_pop = d.when("population")
    rows = []
    if num(s.get("population")):
        rows.append(_row(src, "Population", fmt_int(s["population"]), when_pop, "pl_stats_population"))
    if num(s.get("growth")) is not None:
        rows.append(_row(src, "Change since 2015", fmt_pct(s["growth"], 1, True), "2015 to 2025", "pl_stats_population"))
    if num(s.get("gdp")):
        share = gdp_share(s)
        rows.append(_row(src, "GDP", fmt_big(s["gdp"], "zł") + (f" ({fmt_pct(share)} of Poland)" if share else ""), str(s.get("gdp_year", "")), "pl_gdp"))
    if num(s.get("wage")):
        rows.append(_row(src, "Average gross wage", f"{fmt_pln(s['wage'])} a month", d.when("wage"), "pl_stats_labour"))
    if num(s.get("unemployment")) is not None:
        rows.append(_row(src, "Registered unemployment", fmt_pct(s["unemployment"]), d.when("unemployment"), "pl_stats_labour"))
    if num(s.get("employed")):
        rows.append(_row(src, "People working", fmt_int(s["employed"]), d.when("workers"), "pl_stats_labour"))
    if num(s.get("pit_per_person")):
        rows.append(_row(src, "Personal income tax revenue of the gminas per resident", fmt_pln(s["pit_per_person"]), d.when("pit"), "pl_stats_prosperity"))
    for key, label, fmt in (("life_f", "Life expectancy at birth, women", lambda v: f"{v:.1f} years"),
                            ("life_m", "Life expectancy at birth, men", lambda v: f"{v:.1f} years"),
                            ("tourism", "Tourist nights per resident", lambda v: f"{v:.1f}"),
                            ("dwellings", "New dwellings per 1,000 residents", lambda v: f"{v:.1f}")):
        v = cap(s, key)
        if v is not None:
            f = d.field.get(key) or {}
            rows.append(_row(src, label, fmt(v), _when(f.get("description"), None) or "2025", f.get("source")))
    forest = num((s.get("land") or {}).get("forest"))
    if forest is not None:
        rows.append(_row(src, "Tree cover", f"{fmt_pct(forest, 0)} of the land", "2021", "pl_geo_worldcover"))

    caps = s.get("capitals") or []
    cap_text = ""
    if len(caps) == 1:
        cap_text = f"Its capital is {caps[0]['name']}."
    elif caps:
        vo = [c["name"] for c in caps if c.get("role") in ("voivode", "both")]
        sj = [c["name"] for c in caps if c.get("role") in ("sejmik", "both")]
        cap_text = f"The voivode sits in {', '.join(vo)} and the regional assembly (sejmik) in {', '.join(sj)}."
    towns = sorted((c for c in d.cities if c.get("voivodeship") == s.get("fips")), key=lambda c: -(num(c.get("population")) or 0))
    paras = [p for p in [cap_text, f"It has {len(towns)} towns; {sum(1 for t in towns if t.get('city_view'))} of them have 20,000 or more residents." if towns else ""] if p]
    src.use("pl_geo_places")
    top = [(t["name"], f"../{tw_slug[t['id']]}/" if t["id"] in tw_slug else None, f"{fmt_int(t['population'])} residents")
           for t in towns[:10] if num(t.get("population"))]

    wonders = [wd for wd in d.wonders_doc.get("wonders", []) if wd.get("state") == s["abbr"]]
    heritage = heritage_items(d, src, wonders)

    res_items = []
    rtypes = {t["id"]: t for t in d.resources.get("types", [])}
    items = [i for i in d.resources.get("items", []) if i.get("state") == s["abbr"]]
    mw = sorted((i for i in items if (rtypes.get(i.get("type")) or {}).get("unit") == "MW" and num(i.get("value"))),
                key=lambda i: -i["value"])[:6]
    other = [i for i in items if (rtypes.get(i.get("type")) or {}).get("unit") != "MW"][:6]
    for i in mw + other:
        t = rtypes.get(i.get("type")) or {}
        note = t.get("name", "")
        if t.get("unit") == "MW":
            note += f", {fmt_int(i['value'])} MW"
        elif num(i.get("output")) is not None and i.get("output_unit"):
            note += f", {i['output']:,.1f} {i['output_unit']}" + (f" ({i['year']})" if i.get("year") else "")
        if i.get("status") and i["status"] != "operating":
            note += f" ({i['status']})"
        src.use(t.get("source"))
        res_items.append((i.get("name") or t.get("name"), None, note))

    page_towns = sorted((t for t in towns if t["id"] in tw_slug), key=lambda t: t["name"])
    sections = [{"h2": "Figures", "rows": rows}]
    if top:
        sections.append({"h2": "Largest towns", "items": top})
    if heritage:
        sections.append({"h2": "Heritage, parks and landmarks", "items": heritage})
    if res_items:
        sections.append({"h2": "Energy and resources", "items": res_items})
    if page_towns:
        sections.append({"h2": f"Town pages in {name}", "items": [(t["name"], f"../{tw_slug[t['id']]}/", "") for t in page_towns]})

    pop = num(s.get("population"))
    title = f"{name} voivodeship in numbers: population, economy and towns"
    bits = [f"{fmt_int(pop)} residents" if pop else None,
            f"GDP {fmt_big(s['gdp'], 'zł')} in {s.get('gdp_year')}" if num(s.get("gdp")) else None,
            f"average wage {fmt_pln(s['wage'])}" if num(s.get("wage")) else None,
            f"unemployment {fmt_pct(s['unemployment'])}" if num(s.get("unemployment")) is not None else None]
    desc = f"{name}, Poland: " + ", ".join(b for b in bits if b) + ". Largest towns, heritage and energy, with sources."
    centre = d.state_centre(idx)
    ll = d.lonlat(*centre) if centre else None
    poland = {"@type": "Country", "name": "Poland", "url": SITE_URL + "atlas/"}
    url = SITE_URL + f"atlas/{sl}/"
    place = _place_node(url, f"{name} Voivodeship", "AdministrativeArea", ll, poland, pop, _iso(when_pop), s.get("fips"), [name])
    return {
        "slug": sl, "path": f"atlas/{sl}/", "kind": "voivodeship", "title": title, "description": desc, "h1": name,
        "sub": "Voivodeship of Poland", "lede": lede, "paras": paras, "open": ("Open on the map", f"#state={s['abbr']}"),
        "crumbs": [(SITE_NAME, ""), ("Atlas", "atlas/"), (name, f"atlas/{sl}/")], "sections": sections,
        "sources": src.lines(), "place": place, "og": _og_for(web, sl),
        "og_number": f"{fmt_int(pop)} people" if pop else "", "focus": {"state": s["abbr"]},
    }


def town_page(d: Data, web: Path, c: dict, st_slug: dict, tw_slug: dict) -> dict:
    src = Sources(d)
    sl = tw_slug[c["id"]]
    name = c["name"]
    g = d.gmina.get(c.get("gmina")) or {}
    sv = d.state_by_fips.get(c.get("voivodeship")) or {}
    vname = sv.get("name", "")
    lede, lede_sid = town_headline(d, c)
    src.use(lede_sid)
    when_pop = d.when("population")
    scope = _town_scope(c, g)
    pw = _powiat_words(c, g)
    pw_suffix = "" if c.get("kind") == "city" else f" ({pw})"

    rows = []
    pop = num(c.get("population"))
    if pop:
        rows.append(_row(src, "Population", fmt_int(pop), when_pop, "pl_geo_places"))
    if num(c.get("growth")) is not None:
        ser = c.get("pop_series") or {}
        extra = f" (from {fmt_int(ser['2015'])})" if num(ser.get("2015")) else ""
        rows.append(_row(src, "Change since 2015", fmt_pct(c["growth"], 1, True) + extra, "2015 to 2025", "pl_stats_population"))
    if num(g.get("median_age")) is not None:
        rows.append(_row(src, "Median age" + scope, f"{g['median_age']:.1f} years", when_pop, "pl_stats_population"))
    if num(g.get("elderly")) is not None:
        rows.append(_row(src, "Residents aged 65 or more" + scope, fmt_pct(g["elderly"]), when_pop, "pl_stats_population"))
    if num(c.get("wage")):
        rows.append(_row(src, "Average gross wage" + pw_suffix, f"{fmt_pln(c['wage'])} a month", d.when("wage"), "pl_stats_labour"))
    if num(c.get("unemployment")) is not None:
        rows.append(_row(src, "Registered unemployment" + pw_suffix, fmt_pct(c["unemployment"]), d.when("unemployment"), "pl_stats_labour"))
    if num(c.get("pit_per_person")):
        rows.append(_row(src, "Personal income tax revenue per resident" + scope, fmt_pln(c["pit_per_person"]), d.when("pit"), "pl_stats_prosperity"))
    if num(g.get("students")) is not None:
        rows.append(_row(src, "University students per 1,000 residents", fmt_int(g["students"]), _when((d.field.get("students") or {}).get("description"), None), "pl_stats_population"))
    if c.get("kind") == "city" and num(c.get("employed")):
        rows.append(_row(src, "People working in the city", fmt_int(c["employed"]), d.when("workers"), "pl_stats_labour"))

    # city type and districts
    dist = (d.districts.get("cities") or {}).get(c["id"]) or None
    dist_paras, dist_items = [], []
    if dist:
        catalog = {x["id"]: x for x in d.districts.get("catalog", [])}
        badge = dist.get("badge")
        sc = dist.get("scope") or name
        where = name if sc == name else f"powiat {sc}" if not str(sc).startswith("powiat") else sc
        if badge:
            dist_paras.append(f"City type: {badge['label']}." + (f" {badge['text']}." if badge.get("text") else ""))
        elif not dist.get("districts"):
            dist_paras.append("No kind of work stands out against the national mix.")
        for x in dist.get("districts") or []:
            cat = catalog.get(x.get("id")) or {}
            subs = cat.get("sub") or {}
            sub = subs.get(x.get("sub"))
            if x.get("via") == "specialty" and sub:
                label = f"{sub} ({cat.get('name', x.get('id'))} district)"
                lq, emp, more = num(x.get("sub_lq")), num(x.get("sub_emp")), ""
            else:
                label = f"{cat.get('name', x.get('id'))} district" + (f" ({', '.join(subs.values())})" if subs else "")
                lq, emp = num(x.get("lq")), num(x.get("emp"))
                more = (f"; {sub} alone {x['sub_lq']:.1f} times" if sub and len(subs) > 1 and num(x.get("sub_lq")) and abs(x["sub_lq"] - (lq or 0)) >= 0.1 else "")
            note = []
            if emp:
                note.append(f"{fmt_int(emp)} workers" + (" or more" if x.get("lower_bound") else ""))
            if lq:
                note.append(f"{lq:.1f} times the national share" + more)
            dist_items.append((label, None, ", ".join(note)))
        if where != name:
            dist_paras.append(f"These figures describe the jobs in {where}, by employer seat, on 31 December 2025.")
        else:
            dist_paras.append("Jobs by employer seat on 31 December 2025, against the share of each kind of work in Poland.")
        src.use("pl_stats_labour")

    # vote
    vote_paras = []
    nv, turnout = num(g.get("president_2025")), num(g.get("turnout_2025"))
    if nv is not None:
        unit = name if c.get("scope") != "urban-rural gmina" else f"the gmina of {name}"
        vote_paras.append(f"In the presidential runoff of 1 June 2025, Rafał Trzaskowski won {fmt_pct(1 - nv)} of valid votes in {unit} "
                          f"and Karol Nawrocki {fmt_pct(nv)}." + (f" Turnout was {fmt_pct(turnout)}." if turnout is not None else ""))
        sejm = g.get("sejm_2023")
        if sejm and d.category.get(("sejm", sejm)):
            vote_paras.append(f"In the Sejm election of 15 October 2023 the largest committee there was {d.category[('sejm', sejm)]}.")
        src.use("pl_soc_elections")

    # air
    air_paras = []
    pm = num(g.get("pm25"))
    if pm is not None:
        station = g.get("air_station")
        air_paras.append(f"PM2.5 averaged {pm:.1f} µg/m³ in 2025" + (f" at the GIOŚ station {station}." if station else "."))
        vals = sorted(x for x in (num((d.gmina.get(t.get("gmina")) or {}).get("pm25")) for t in d.view_towns) if x is not None)
        if len(vals) >= 5:
            med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
            air_paras.append(f"The median of the {len(vals)} towns of 20,000+ with a station within 25 km was {med:.1f} µg/m³.")
        src.use("pl_soc_air")
    else:
        air_paras.append("No GIOŚ station measured PM2.5 within 25 km of the town centre in 2025.")

    # nearby heritage and metro
    near = []
    for wd in d.wonders_doc.get("wonders", []):
        if num(wd.get("x")) is None or num(c.get("x")) is None:
            continue
        km = math.hypot(wd["x"] - c["x"], wd["y"] - c["y"])
        if km <= NEARBY_KM:
            near.append((km, wd))
    near.sort(key=lambda t: t[0])
    near_items = []
    for (km, wd), item in zip(near, heritage_items(d, src, [wd for _, wd in near])):
        near_items.append((item[0], None, item[2] + (f", {km:.0f} km away" if km >= 2 else ", in the town")))
    metro = d.metro_by_id.get(c.get("fua"))
    metro_paras = []
    if metro:
        mp = num(metro.get("population"))
        core = d.city_by_id.get(metro.get("core")) or {}
        metro_paras.append(f"{name} belongs to the {metro.get('full') or metro.get('name')}" + (f", {fmt_int(mp)} residents" if mp else "")
                           + (f" in {len(metro.get('gminas') or [])} gminas" if metro.get("gminas") else "") + "."
                           + (f" Its core town is {core['name']}." if core.get("name") and core.get("id") != c["id"] else ""))
        src.use("pl_geo_fua")

    sections = [{"h2": "Figures", "rows": rows}]
    if dist_paras:
        sections.append({"h2": "City type and districts", "paras": dist_paras, "items": dist_items})
    if vote_paras:
        sections.append({"h2": "2025 presidential election", "paras": [p for p in vote_paras if p]})
    sections.append({"h2": "Air quality", "paras": air_paras})
    if metro_paras or near_items:
        sections.append({"h2": "Metro area and places nearby", "paras": metro_paras, "items": near_items})
    peers = [d.city_by_id[p] for p in c.get("peers") or [] if p in d.city_by_id and p in tw_slug]
    if peers:
        sections.append({"h2": "Towns of a similar size", "items": [(p["name"], f"../{tw_slug[p['id']]}/", f"{fmt_int(p['population'])} residents") for p in peers]})

    caps = [x for x in sv.get("capitals") or [] if x.get("gmina") == c.get("gmina")]
    kind = "the capital of Poland and a city with powiat rights" if c.get("capital") else "a city with powiat rights" if c.get("kind") == "city" else "a town"
    where = f"in {vname} voivodeship" if c.get("kind") == "city" else f"in {pw}, {vname} voivodeship"
    intro = f"{name} is {kind} {where}."
    if caps:
        role = caps[0].get("role")
        intro += {"both": f" It is the capital of {vname}.", "voivode": f" It is the seat of the voivode of {vname}.",
                  "sejmik": f" It is the seat of the regional assembly (sejmik) of {vname}."}.get(role, "")
    paras = [intro]

    title = f"{name}, Poland: population, wages, vote and air quality"
    bits = [f"{fmt_int(pop)} residents ({when_pop})" if pop else None,
            f"{fmt_pct(c['growth'], 1, True)} from 2015 to 2025" if num(c.get("growth")) is not None else None,
            f"average wage {fmt_pln(c['wage'])}" if num(c.get("wage")) else None,
            f"unemployment {fmt_pct(c['unemployment'])}" if num(c.get("unemployment")) is not None else None,
            f"PM2.5 {pm:.1f} µg/m³" if pm is not None else None]
    desc = f"{name}, {vname}: " + ", ".join(b for b in bits if b) + "."
    url = SITE_URL + f"atlas/{sl}/"
    parent = {"@type": "AdministrativeArea", "@id": SITE_URL + f"atlas/{st_slug.get(sv.get('abbr'), '')}/#place",
              "name": f"{vname} Voivodeship", "url": SITE_URL + f"atlas/{st_slug.get(sv.get('abbr'), '')}/"}
    place = _place_node(url, name, "City", d.lonlat(c.get("x"), c.get("y")), parent, pop, _iso(when_pop), c.get("id"))
    crumbs = [(SITE_NAME, ""), ("Atlas", "atlas/")]
    if sv:
        crumbs.append((vname, f"atlas/{st_slug[sv['abbr']]}/"))
    crumbs.append((name, f"atlas/{sl}/"))
    return {
        "slug": sl, "path": f"atlas/{sl}/", "kind": "town", "title": title, "description": desc, "h1": name,
        "sub": c.get("full") or name, "lede": lede, "paras": paras, "open": ("Open on the map", f"#city={c['id']}&view=city"),
        "crumbs": crumbs, "sections": sections, "sources": src.lines(), "place": place, "og": _og_for(web, sl),
        "og_number": f"{fmt_int(pop)} people" if pop else "", "focus": {"city": c["id"]},
    }


# --- rendering -------------------------------------------------------------------------------------------------------

EMBLEM = ('<svg class="emblem" aria-hidden="true" viewBox="0 0 64 64" width="24" height="24"><path d="M8 6h48v24c0 15-10 24-24 30C18 54 8 45 8 30z" fill="#120d06"/>'
          '<path d="M11 9h42v21c0 13-9 21-21 26.5C20 51 11 43 11 30z" fill="#c9a45c"/><path d="M14.5 12.5h35V30c0 11-7.5 18-17.5 22.8C22 48 14.5 41 14.5 30z" fill="#B3262E"/>'
          '<path d="M14.5 12.5h35V28c-6 3-11.5-3-17.5 0s-11.5 3-17.5 0z" fill="#f4ecd8"/><path d="M14.5 28c6 3 11.5 3 17.5 0s11.5-3 17.5 0" fill="none" stroke="#e2bf6e" stroke-width="2.6"/></svg>')
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cpath d='M8 6h48v24c0 15-10 24-24 30C18 54 8 45 8 30z' fill='%23120d06'/%3E"
           "%3Cpath d='M11 9h42v21c0 13-9 21-21 26.5C20 51 11 43 11 30z' fill='%23c9a45c'/%3E%3Cpath d='M14.5 12.5h35V30c0 11-7.5 18-17.5 22.8C22 48 14.5 41 14.5 30z' fill='%23B3262E'/%3E"
           "%3Cpath d='M14.5 12.5h35V28c-6 3-11.5-3-17.5 0s-11.5 3-17.5 0z' fill='%23f4ecd8'/%3E%3Cpath d='M14.5 28c6 3 11.5 3 17.5 0s11.5-3 17.5 0' fill='none' stroke='%23c9a45c' stroke-width='3'/%3E%3C/svg%3E")


def _rel_root(page: dict) -> str:
    return "../" * page["path"].count("/")


def _link(page: dict, target_path: str) -> str:
    """Relative link from the page to a site path ("" = the app, "atlas/krakow/")."""
    return _rel_root(page) + target_path


def render_html(page: dict, date: str) -> str:
    root = _rel_root(page)
    url = SITE_URL + page["path"]
    og = SITE_URL + page["og"]
    ld = json.dumps(_jsonld(page, date), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    h = []
    a = h.append
    a("<!doctype html>")
    a('<html lang="en">')
    a("<head>")
    a('<meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width, initial-scale=1">')
    a(f'<meta http-equiv="Content-Security-Policy" content="{esc(ATLAS_CSP)}">')
    a(f"<title>{esc(page['title'])}</title>")
    a(f'<meta name="description" content="{esc(page["description"])}">')
    a(f'<link rel="canonical" href="{esc(url)}">')
    a(f'<link rel="alternate" type="text/markdown" href="index.md">')
    a(f'<link rel="icon" type="image/svg+xml" href="{FAVICON}">')
    a('<meta name="theme-color" content="#0f2233">')
    a(f'<meta name="author" content="{esc(AUTHOR["name"])}">')
    a('<meta property="og:type" content="article">')
    a(f'<meta property="og:site_name" content="{SITE_NAME}">')
    a(f'<meta property="og:title" content="{esc(page["title"])}">')
    a(f'<meta property="og:description" content="{esc(page["description"])}">')
    a(f'<meta property="og:url" content="{esc(url)}">')
    a(f'<meta property="og:image" content="{esc(og)}">')
    a('<meta property="og:image:width" content="1200">')
    a('<meta property="og:image:height" content="630">')
    a(f'<meta property="og:image:alt" content="{esc(page["h1"])} on the hex map of Poland">')
    a(f'<meta property="article:modified_time" content="{date}">')
    a('<meta name="twitter:card" content="summary_large_image">')
    a(f'<meta name="twitter:title" content="{esc(page["title"])}">')
    a(f'<meta name="twitter:description" content="{esc(page["description"])}">')
    a(f'<meta name="twitter:image" content="{esc(og)}">')
    a(f'<meta name="pc-atlas" content="{esc(page["kind"])}:{esc(page["slug"])}">')
    a(f'<link rel="stylesheet" href="{root}css/atlas.css">')
    a(f'<script type="application/ld+json">{ld}</script>')
    a(f'<script type="module" src="{root}js/app/analytics.js"></script>')
    a("</head>")
    a("<body>")
    a(f'<header class="bar"><a class="brand" href="{root}">{EMBLEM}<span>Polska</span></a>'
      f'<a class="bar-open" href="{root}{esc(page["open"][1])}">{esc(page["open"][0])}</a></header>')
    a('<main>')
    crumbs = page["crumbs"]
    cur = ' aria-current="page"'
    a('<nav class="crumbs" aria-label="Breadcrumb"><ol>' + "".join(
        f'<li><a href="{_link(page, p)}"{cur if i == len(crumbs) - 1 else ""}>{esc(n)}</a></li>'
        for i, (n, p) in enumerate(crumbs)) + "</ol></nav>")
    a(f"<h1>{esc(page['h1'])}</h1>")
    if page.get("sub"):
        a(f'<p class="sub">{esc(page["sub"])}</p>')
    a(f'<p class="lede">{esc(page["lede"])}</p>')
    for p in page["paras"]:
        a(f"<p>{esc(p)}</p>")
    a(f'<p><a class="open" href="{root}{esc(page["open"][1])}">{esc(page["open"][0])}</a></p>')
    for sec in page["sections"]:
        a("<section>")
        a(f"<h2>{esc(sec['h2'])}</h2>")
        for p in sec.get("paras") or []:
            a(f"<p>{esc(p)}</p>")
        if sec.get("rows"):
            a('<table class="figures"><tbody>')
            for label, value, when, _sid in sec["rows"]:
                a(f'<tr><th scope="row">{esc(label)}</th><td class="v">{esc(value)}</td><td class="w">{esc(when)}</td></tr>')
            a("</tbody></table>")
        if sec.get("table"):
            t = sec["table"]
            a('<div class="scroll"><table class="grid"><thead><tr>' + "".join(f'<th scope="col">{esc(x)}</th>' for x in t["head"]) + "</tr></thead><tbody>")
            for row in t["rows"]:
                (n, href), rest = row[0], row[1:]
                a(f'<tr><th scope="row"><a href="{esc(href)}">{esc(n)}</a></th>' + "".join(f"<td>{esc(x)}</td>" for x in rest) + "</tr>")
            a("</tbody></table></div>")
        if sec.get("items"):
            a('<ul class="items">')
            for text, href, note in sec["items"]:
                name = f'<a href="{esc(href)}">{esc(text)}</a>' if href else f"<b>{esc(text)}</b>"
                a(f"<li>{name}" + (f'<span class="note">{esc(note)}</span>' if note else "") + "</li>")
            a("</ul>")
        for grp in sec.get("groups") or []:
            if not grp["items"]:
                continue
            a(f"<h3>{esc(grp['h3'])}</h3>")
            a('<ul class="towns">' + "".join(f'<li><a href="{esc(href)}">{esc(t)}</a> <span class="note">{esc(n)}</span></li>' for t, href, n in grp["items"]) + "</ul>")
        a("</section>")
    a('<section class="sources">')
    a("<h2>Sources</h2>")
    a("<ul>" + "".join(f'<li><a href="{esc(u)}" rel="noopener">{esc(t)}</a></li>' if u else f"<li>{esc(t)}</li>" for t, u in page["sources"]) + "</ul>")
    a("</section>")
    a("</main>")
    a(f'<footer><p>Last updated {human_date(date)}. Part of <a href="{root}">Polska</a>, a map of Poland built from public data. '
      f'<a href="index.md">Markdown version</a>. <a href="{root}llms.txt">llms.txt</a>. '
      f'Code: <a href="{REPO_URL}" rel="noopener">MIT licence</a>; data: the publishers above, under their own terms.</p></footer>')
    a("</body>")
    a("</html>")
    return "\n".join(h) + "\n"


def render_md(page: dict, date: str, full: bool = True) -> str:
    """Markdown copy of a page. full=False gives the compact form used in llms-full.txt."""
    url = SITE_URL + page["path"]
    out = []
    a = out.append
    hd = "#" if full else "##"
    a(f"{hd} {page['h1']}")
    a("")
    if full:
        a(f"Source page: {url}")
        a(f"Last updated: {date}")
        a("")
    elif page.get("sub"):
        a(f"{page['sub']}. Page: {url}")
        a("")
    a(page["lede"])
    a("")
    for p in page["paras"]:
        a(p)
        a("")
    if full:
        a(f"[{page['open'][0]}]({SITE_URL}{page['open'][1]})")
        a("")
    h2 = "##" if full else "###"
    for sec in page["sections"]:
        if not full and sec.get("groups"):
            continue
        a(f"{h2} {sec['h2']}")
        a("")
        for p in sec.get("paras") or []:
            a(p)
            a("")
        if sec.get("rows"):
            if full:
                a("| Figure | Value | Date | Publisher |")
                a("|---|---|---|---|")
                for label, value, when, sid in sec["rows"]:
                    a(f"| {md_esc(label)} | {md_esc(value)} | {md_esc(when)} | {md_esc(page['_pub'](sid))} |")
            else:
                for label, value, when, sid in sec["rows"]:
                    a(f"- {label}: {value} ({when}; {page['_pub'](sid)})" if when else f"- {label}: {value} ({page['_pub'](sid)})")
            a("")
        if sec.get("table"):
            t = sec["table"]
            a("| " + " | ".join(t["head"]) + " |")
            a("|" + "---|" * len(t["head"]))
            for row in t["rows"]:
                (n, href), rest = row[0], row[1:]
                a(f"| [{n}]({SITE_URL}atlas/{href}) | " + " | ".join(md_esc(x) for x in rest) + " |")
            a("")
        if sec.get("items"):
            for text, href, note in sec["items"]:
                link = f"[{text}]({SITE_URL}{_abs_from(page, href)})" if href else text
                a(f"- {link}" + (f": {note}" if note else ""))
            a("")
        for grp in sec.get("groups") or []:
            if not grp["items"]:
                continue
            a(f"{'###' if full else '####'} {grp['h3']}")
            a("")
            for t, href, n in grp["items"]:
                a(f"- [{t}]({SITE_URL}{_abs_from(page, href)})" + (f": {n} residents" if n else ""))
            a("")
    if full:
        a(f"{h2} Sources")
        a("")
        for t, u in page["sources"]:
            a(f"- [{t}]({u})" if u else f"- {t}")
        a("")
    return "\n".join(out).rstrip() + "\n"


def _abs_from(page: dict, href: str) -> str:
    """Site path of a link written relative to the page (atlas/ or atlas/<slug>/)."""
    base = page["path"]
    parts = [p for p in base.split("/") if p]
    for seg in href.split("/"):
        if seg == "..":
            parts = parts[:-1]
        elif seg and seg != ".":
            parts.append(seg)
    return "/".join(parts) + ("/" if href.endswith("/") else "")


# --- indexes ---------------------------------------------------------------------------------------------------------

FILE_INFO = {
    "world.json": ("The hex grid of Poland: owner voivodeship and gmina per hex, elevation, water, relief, land cover, rivers, lakes.",
                   ["grid", "owner", "county", "elev", "water", "relief", "cover", "pct", "states", "counties", "rivers", "lakes"],
                   ["pl_geo_lau", "pl_geo_teryt", "pl_geo_ne", "pl_geo_etopo", "pl_geo_worldcover", "pl_geo_forest_type", "pl_geo_hydrorivers"]),
    "cities.json": ("Every town with town rights (1 January 2026), with population, growth, wage, unemployment, GDP share, yields and ranks.",
                    ["id (TERYT7)", "name", "population", "growth", "wage", "unemployment", "pit_per_person", "gdp", "city_view", "fua"],
                    ["pl_geo_places", "pl_stats_population", "pl_stats_labour", "pl_stats_prosperity", "pl_gdp", "pl_geo_fua"]),
    "metros.json": ("Metro areas: Eurostat functional urban areas of Poland, with their member gminas and economic figures.",
                    ["id (FUA code)", "name", "population", "gminas", "cities", "wage", "unemployment"],
                    ["pl_geo_fua", "pl_stats_population", "pl_stats_labour", "pl_gdp"]),
    "states.json": ("The 16 voivodeships: population, growth, GDP, wage, unemployment, jobs by PKD section, capitals, land cover.",
                    ["fips (TERYT2)", "abbr", "name", "population", "gdp", "wage", "unemployment", "capitals", "land"],
                    ["pl_stats_population", "pl_stats_labour", "pl_stats_prosperity", "pl_gdp", "pl_geo_worldcover"]),
    "nation.json": ("National figures of Poland and the yield definitions.",
                    ["nation.population", "nation.gdp", "nation.wage", "nation.unemployment", "years", "yields"],
                    ["pl_stats_population", "pl_stats_labour", "pl_stats_prosperity", "pl_gdp"]),
    "counties.json": ("Every gmina (TERYT7) with about 30 metrics: density, age, migration, PIT, wage, unemployment, education, faith, vote, air, flood, land cover.",
                      None, None),
    "powiaty.json": ("Every powiat (TERYT4) with the same metrics, summed or weighted from its gminas.", None, None),
    "lenses.json": ("The map lenses: one value per hex for each metric, with legend domains and notes.", None, None),
    "resources.json": ("Power plants, mines, oil and gas sites, offshore wind and renewables by powiat.",
                       ["types", "items (name, type, value, status, operator)", "summary", "renewables"], None),
    "infrastructure.json": ("Motorways, expressways and main railway lines on hex links, plus seaports and airports.", ["roads", "rail", "ports", "airports", "totals"], None),
    "military.json": ("Garrisons, bases, allied sites and training areas, with strength and budget.", ["installations", "ranges", "states", "national"], None),
    "wonders.json": ("Heritage and landmark sites chosen by published rules: UNESCO properties, national parks, research universities, record landmarks.",
                     ["wonders (name, kind, metrics, ref, x, y)", "rules", "national"], None),
    "trade.json": ("Road and rail freight routes between regions.", ["zones", "routes", "national_kt"], None),
    "citizens.json": ("Citizen mix of each town of 20,000+: workers by sector, age, sex, education, origin.", ["cities", "national", "groups"], None),
    "districts.json": ("Districts and city types of each town of 20,000+, from location quotients of jobs by PKD section.", ["cities", "catalog", "badges", "rule"], None),
    "disasters.json": ("The gminas declared a natural disaster area after the September 2024 flood.", ["flood_2024"], None),
    "sources.json": ("The bibliography: every source with publisher, licence, vintage and the exact files used.", ["id", "publisher", "license", "vintage", "files"], []),
}


def _rows(name: str, doc) -> int | None:
    if doc is None:
        return None
    if isinstance(doc, list):
        return len(doc)
    for k in ("rows", "metros", "lenses", "items", "wonders", "installations", "routes", "cities"):
        v = doc.get(k)
        if isinstance(v, (list, dict)) and v:
            return len(v)
    if name == "world.json":
        g = doc.get("grid") or {}
        return (g.get("cols") or 0) * (g.get("rows") or 0) or None
    if name == "nation.json":
        return 1
    if name == "disasters.json":
        return len(((doc.get("flood_2024") or {}).get("gminas") or {}).get("rows") or []) or None
    return None


def data_catalog(d: Data, web: Path, date: str) -> dict:
    files = []
    for name, (desc, fields, sids) in FILE_INFO.items():
        p = d.dir / name
        if not p.exists():
            continue
        doc = _load(d.dir, name)
        if sids is None:
            if isinstance(doc, dict) and isinstance(doc.get("sources"), list):
                sids = doc["sources"]
            elif isinstance(doc, dict) and isinstance(doc.get("fields"), list):
                sids = sorted({f.get("source") for f in doc["fields"] if f.get("source")})
            elif isinstance(doc, dict) and isinstance(doc.get("lenses"), list):
                sids = sorted({x.get("source") for x in doc["lenses"] if x.get("source")})
            else:
                sids = []
        if fields is None and isinstance(doc, dict) and isinstance(doc.get("fields"), list):
            fields = [f"{f.get('key')} ({f.get('label')})" for f in doc["fields"]]
        if fields is None and isinstance(doc, dict) and isinstance(doc.get("lenses"), list):
            fields = [f"{x.get('id')} ({x.get('name')})" for x in doc["lenses"]]
        vint = doc.get("vintage") if isinstance(doc, dict) else None
        if vint is None and sids:
            vint = {sid: (d.source_by_id.get(sid) or {}).get("vintage") for sid in sids}
        pubs = []
        for sid in sids:
            pub = (d.source_by_id.get(sid) or {}).get("publisher")
            if pub and pub not in pubs:
                pubs.append(pub)
        files.append({"path": f"data/{name}", "url": f"{SITE_URL}data/{name}", "bytes": p.stat().st_size,
                      "description": desc, "fields": fields or [], "rows": _rows(name, doc), "vintage": vint,
                      "sources": sids, "publishers": pubs})
    return {
        "version": 1, "name": "Polska data catalogue", "site": SITE_URL, "generated": date,
        "description": "Public data behind the Polska map of Poland. Each file is JSON; shapes are documented in docs/DATA_CONTRACTS.md of the source repository.",
        "contracts": f"{REPO_URL}/blob/main/docs/DATA_CONTRACTS.md",
        "license": {"code": "MIT (see LICENSE in the source repository)",
                    "data": "Each figure belongs to its publisher and is reused under the publisher's terms (see sources.json): "
                            "Polish public statistics with attribution (GUS: CC BY 4.0), Eurostat and Copernicus reuse policies, "
                            "ESA WorldCover and HydroSHEDS CC BY 4.0, OpenStreetMap data ODbL (road, rail and position data stay ODbL)."},
        "creator": AUTHOR, "text_pages": f"{SITE_URL}atlas/", "llms": f"{SITE_URL}llms.txt", "files": files,
    }


def llms_txt(d: Data, pages: list[dict], catalog: dict) -> str:
    n = d.nation
    out = [f"# {APP_TITLE}", ""]
    pop = num(n.get("population"))
    out.append("> Polska draws real Poland as a hex strategy map: terrain, towns, yields, lenses and resources, every figure from a "
               "public source (GUS, Eurostat, PKW, GIOŚ, UNESCO and others). The atlas has a text page with dated, sourced figures "
               f"for Poland, each of the 16 voivodeships and each of the {len(d.view_towns)} towns of 20,000 or more people.")
    out.append("")
    if pop:
        out.append(f"Poland had {fmt_int(pop)} residents on {d.when('population')}. Pages are in English; place names keep their Polish spelling.")
        out.append("")
    out += ["## App", "", f"- [Polska, the map]({SITE_URL}): interactive hex map with lenses, town views and advisors (needs JavaScript)", ""]
    out += ["## Atlas", "", f"- [Poland in numbers]({SITE_URL}atlas/): national figures, the 16 voivodeships and links to every page",
            f"- [Full text]({SITE_URL}llms-full.txt): every atlas page as compact markdown in one file"]
    for p in pages:
        if p["kind"] == "voivodeship":
            out.append(f"- [{p['h1']}]({SITE_URL}{p['path']}index.md): {p['lede']}")
    out.append("")
    out += ["## Data", "", f"- [Data catalogue]({SITE_URL}data/index.json): every data file with its fields, rows, vintage and publishers"]
    for f in catalog["files"]:
        out.append(f"- [{f['path']}]({f['url']}): {f['description']}")
    out.append("")
    out += ["## Sources", ""]
    seen = set()
    for s in d.sources:
        pub = s.get("publisher")
        if not pub or pub in seen:
            continue
        seen.add(pub)
        out.append(f"- [{pub}]({s.get('homepage') or SITE_URL + 'data/sources.json'}): {s.get('title', '')}")
    out.append("")
    out += ["## How to cite", "",
            f"- [Cite this site]({SITE_URL}atlas/): \"Polska: Poland as a strategy map built from real data\", Jarek Tkaczyk, {SITE_URL}, with the page URL and the date you read it",
            f"- [Cite the figures]({SITE_URL}data/sources.json): name the original publisher and year given next to each figure; the atlas pages list them under Sources",
            f"- [Source code]({REPO_URL}): MIT licence; the data stay under their publishers' terms", ""]
    out += ["## Optional", ""]
    for p in pages:
        if p["kind"] == "town":
            out.append(f"- [{p['h1']}]({SITE_URL}{p['path']}index.md): {p['sub']}")
    return "\n".join(out).rstrip() + "\n"


def llms_full(pages: list[dict], date: str) -> str:
    out = [f"# {APP_TITLE}: full text", "",
           f"Every atlas page of {SITE_URL} as compact markdown. Generated {date}. Each figure gives its date and publisher.", ""]
    for p in pages:
        out.append(render_md(p, date, full=False))
    return "\n".join(out).rstrip() + "\n"


def app_jsonld(d: Data, catalog: dict, date: str) -> dict:
    """WebSite, WebApplication and Dataset nodes for web/index.html."""
    n = d.nation_doc
    years = [y for y in (n.get("years") or {}).values() if isinstance(y, int)]
    gy = (d.nation.get("growth_years") or [None])[0]
    span = f"{min([gy] + years if gy else years)}/{max(years)}" if years else None
    image = SITE_URL + MAIN_OG
    site = {"@type": "WebSite", "@id": SITE_URL + "#website", "name": SITE_NAME, "alternateName": "pol-civ", "url": SITE_URL,
            "inLanguage": "en", "author": AUTHOR}
    appn = {"@type": "WebApplication", "@id": SITE_URL + "#app", "name": SITE_NAME, "alternateName": "pol-civ", "url": SITE_URL,
            "description": "Real Poland drawn as a turn-based strategy map: hex terrain, towns with yields, lenses for every gmina "
                           "and advisors, every figure from a public source.",
            "applicationCategory": "EducationalApplication", "operatingSystem": "Any (web browser)",
            "browserRequirements": "Requires JavaScript and HTML canvas", "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "PLN"}, "inLanguage": "en", "image": image,
            "author": AUTHOR, "dateModified": date, "isBasedOn": "https://karpathy.ai/usaciv/",
            "license": f"{REPO_URL}/blob/main/LICENSE"}
    dist = [{"@type": "DataDownload", "name": f["path"].split("/")[-1], "contentUrl": f["url"], "encodingFormat": "application/json",
             "description": f["description"]} for f in catalog["files"]]
    dist.insert(0, {"@type": "DataDownload", "name": "index.json", "contentUrl": SITE_URL + "data/index.json",
                    "encodingFormat": "application/json", "description": "Catalogue of the data files: fields, rows, vintage, publishers."})
    pubs = []
    for s in d.sources:
        p = s.get("publisher")
        if p and p not in pubs:
            pubs.append(p)
    data = {"@type": "Dataset", "@id": SITE_URL + "#dataset", "name": "Polska: public data on Poland by gmina, powiat, voivodeship and town",
            "description": "Population, growth, age, wages, unemployment, income tax revenue, GDP, education, health, faith, elections, "
                           "air quality, land cover, energy, transport, heritage and defence figures for Poland's 16 voivodeships, "
                           "380 powiats, 2,479 gminas and 1,026 towns, gathered from official publishers and drawn on a hex map.",
            "url": SITE_URL + "atlas/", "sameAs": SITE_URL + "data/index.json", "isAccessibleForFree": True, "inLanguage": "en",
            "keywords": ["Poland", "Polska", "GUS", "voivodeship", "gmina", "powiat", "population", "regional statistics"],
            "creator": AUTHOR, "dateModified": date,
            "license": {"@type": "CreativeWork", "name": "Code under the MIT licence; each figure under its publisher's own terms (see sources.json)",
                        "url": SITE_URL + "data/sources.json"},
            "spatialCoverage": {"@type": "Place", "name": "Poland"},
            "isBasedOn": [s.get("homepage") for s in d.sources if s.get("homepage")][:40],
            "citation": pubs,
            "distribution": dist}
    if span:
        data["temporalCoverage"] = span
    return {"@context": "https://schema.org", "@graph": [site, appn, data]}


def fill_index_html(web: Path, ld: dict) -> bool:
    """Put the JSON-LD between the seo markers of web/index.html. False if the markers are missing."""
    p = web / "index.html"
    if not p.exists():
        return False
    text = p.read_text()
    m = re.search(r"(<!-- seo:jsonld[^>]*-->)(.*?)(<!-- /seo:jsonld -->)", text, re.S)
    if not m:
        return False
    body = json.dumps(ld, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    new = text[:m.start(2)] + f'<script type="application/ld+json">{body}</script>' + text[m.end(2):]
    if new != text:
        _write(p, new)
    return True


def sitemap(pages: list[dict], date: str) -> str:
    urls = [SITE_URL] + [SITE_URL + p["path"] for p in pages]
    body = "".join(f"  <url><loc>{esc(u)}</loc><lastmod>{date}</lastmod></url>\n" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + body + "</urlset>\n")


# --- build -----------------------------------------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    from ..core.store import atomic_write_text

    atomic_write_text(path, text)


def build_site(web: Path, date: str | None = None, save_plan=None) -> dict:
    """Write every output under `web` (reading web/data). Returns a summary {pages, bytes}."""
    web = Path(web)
    date = date or build_date()
    d = Data(web / "data")
    if not d.cities or not d.states:
        raise FileNotFoundError("seo: cities.json and states.json are required")
    pages = build_pages(d, web)
    for p in pages:
        p["_pub"] = lambda sid, d=d: d.publisher(sid) if sid else "see Sources"
    atlas = web / "atlas"
    keep = {p["path"] for p in pages}
    if atlas.exists():  # drop pages of towns that left the list
        for sub in atlas.iterdir():
            if sub.is_dir() and f"atlas/{sub.name}/" not in keep:
                for f in sub.iterdir():
                    f.unlink()
                sub.rmdir()
    for p in pages:
        folder = web / p["path"]
        _write(folder / "index.html", render_html(p, date))
        _write(folder / "index.md", render_md(p, date))
    catalog = data_catalog(d, web, date)
    _write(web / "data" / "index.json", json.dumps(catalog, ensure_ascii=False, indent=1) + "\n")
    _write(web / "llms.txt", llms_txt(d, pages, catalog))
    _write(web / "llms-full.txt", llms_full(pages, date))
    _write(web / "sitemap.xml", sitemap(pages, date))
    fill_index_html(web, app_jsonld(d, catalog, date))
    plan = [{"slug": p["slug"], "kind": p["kind"], "name": p["h1"], "sub": p.get("sub") or "", "number": p["og_number"],
             "focus": p["focus"], "out": f"og/{p['slug']}.jpg"} for p in pages if p["kind"] != "index"]
    if save_plan:
        save_plan(plan)
    total = sum(f.stat().st_size for f in atlas.rglob("*") if f.is_file())
    return {"pages": len(pages), "atlas_bytes": total, "plan": plan}


def build() -> None:
    from ..core.store import save_interim

    res = build_site(WEB, save_plan=lambda plan: save_interim("_seo", {"og_plan": plan}))
    print(f"    atlas: {res['pages']} pages, {res['atlas_bytes'] / 1e3:.0f} kB; llms.txt, llms-full.txt, sitemap.xml, data/index.json")


# --- check -----------------------------------------------------------------------------------------------------------

_TAG = re.compile(r'<(meta|link)\s+([^>]*)>', re.I)
_ATTR = re.compile(r'([a-zA-Z:-]+)="([^"]*)"')


def _head(text: str) -> dict:
    out = {}
    for _, attrs in _TAG.findall(text):
        a = dict(_ATTR.findall(attrs))
        key = a.get("property") or a.get("name") or a.get("http-equiv") or (("link:" + a.get("rel", "")) if "rel" in a else None)
        if key and key not in out:
            out[key] = html.unescape(a.get("content", a.get("href", "")))
    return out


def jsonld_of(text: str) -> list:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)]


def check(web_dir: Path) -> list[tuple[str, str]]:
    web_dir = Path(web_dir)
    web = web_dir.parent
    atlas = web / "atlas"
    out: list[tuple[str, str]] = []
    if not (atlas / "index.html").exists():
        return [("NOTE", "web/atlas missing (optional; run: uv run python -m pipeline build seo)")]
    pages = sorted(atlas.rglob("index.html"))
    bad = []
    for p in pages:
        text = p.read_text()
        rel = p.parent.relative_to(web).as_posix() + "/"
        head = _head(text)
        if head.get("link:canonical") != SITE_URL + rel:
            bad.append(f"{rel}: canonical {head.get('link:canonical')!r}")
        for k in ("description", "og:title", "og:image", "twitter:card", "Content-Security-Policy"):
            if not head.get(k):
                bad.append(f"{rel}: no {k}")
        img = head.get("og:image", "")
        if img.startswith(SITE_URL) and not (web / img[len(SITE_URL):]).exists():
            bad.append(f"{rel}: share image {img[len(SITE_URL):]} missing")
        try:
            lds = jsonld_of(text)
            types = {n.get("@type") for ld in lds for n in ld.get("@graph", [])}
            if "WebPage" not in types or "BreadcrumbList" not in types:
                bad.append(f"{rel}: JSON-LD lacks WebPage or BreadcrumbList")
        except ValueError as exc:
            bad.append(f"{rel}: JSON-LD does not parse ({exc})")
        if CF_BEACON_HOST in text:
            bad.append(f"{rel}: loads the Cloudflare beacon directly (analytics.js injects it)")
        if "js/app/analytics.js" not in text:
            bad.append(f"{rel}: no analytics.js")
        if not (p.parent / "index.md").exists():
            bad.append(f"{rel}: no index.md")
        if LEAK.search(text):
            bad.append(f"{rel}: contains a local path or private name")
    for b in bad[:10]:
        out.append(("FAIL", b))
    if len(bad) > 10:
        out.append(("FAIL", f"... {len(bad) - 10} more page problems"))
    if not bad:
        out.append(("PASS", f"atlas: {len(pages)} pages with canonical, description, share card, CSP, JSON-LD and a markdown copy"))
    shared = sum(1 for p in pages if f'content="{SITE_URL}og/' in p.read_text())
    out.append(("NOTE" if shared < len(pages) - 1 else "PASS", f"atlas: {shared} of {len(pages) - 1} place pages have their own share image (scripts/og-shots.mjs)"))

    cities = _load(web_dir, "cities.json")
    if isinstance(cities, list):
        want = sum(1 for c in cities if isinstance(c, dict) and c.get("city_view"))
        states = _load(web_dir, "states.json") or []
        have = len(pages) - 1
        if have != want + len(states):
            out.append(("WARN", f"atlas: {have} place pages, data has {len(states)} voivodeships + {want} towns (rebuild: pipeline build seo)"))

    sm = web / "sitemap.xml"
    if sm.exists():
        locs = re.findall(r"<loc>(.*?)</loc>", sm.read_text())
        missing = [u for u in locs if not (web / (u[len(SITE_URL):] + "index.html" if u.startswith(SITE_URL) else "x")).exists()]
        listed = {u[len(SITE_URL):] for u in locs}
        unlisted = [p.parent.relative_to(web).as_posix() + "/" for p in pages if p.parent.relative_to(web).as_posix() + "/" not in listed]
        if missing or unlisted:
            out.append(("FAIL", f"sitemap.xml: {len(missing)} URLs without a page, {len(unlisted)} pages not listed"))
        else:
            out.append(("PASS", f"sitemap.xml: {len(locs)} URLs, each with a page"))
    else:
        out.append(("FAIL", "sitemap.xml missing"))

    lt = web / "llms.txt"
    if lt.exists():
        problems = llms_problems(lt.read_text(), web)
        out.append(("FAIL", "llms.txt: " + "; ".join(problems[:5])) if problems else ("PASS", "llms.txt: H1, summary, sections, every local link resolves"))
    else:
        out.append(("FAIL", "llms.txt missing"))
    if not (web / "llms-full.txt").exists():
        out.append(("FAIL", "llms-full.txt missing"))

    cat = _load(web_dir, "index.json")
    if isinstance(cat, dict):
        gone = [f["path"] for f in cat.get("files", []) if not (web / f["path"]).exists()]
        out.append(("FAIL", f"data/index.json lists missing files: {gone}") if gone else ("PASS", f"data/index.json: {len(cat.get('files', []))} files catalogued"))
    else:
        out.append(("FAIL", "data/index.json missing or invalid"))

    idx = web / "index.html"
    if idx.exists():
        csp = _head(idx.read_text()).get("Content-Security-Policy")
        if csp != APP_CSP:
            out.append(("WARN", "web/index.html CSP differs from seo.APP_CSP (keep them equal)"))
        if CF_BEACON_HOST in idx.read_text():
            out.append(("FAIL", "web/index.html loads the Cloudflare beacon directly (analytics.js injects it)"))
    for name in ("llms.txt", "llms-full.txt", "sitemap.xml"):
        f = web / name
        if f.exists() and LEAK.search(f.read_text()):
            out.append(("FAIL", f"{name}: contains a local path or private name"))
    return out


def llms_problems(text: str, web: Path | None = None) -> list[str]:
    """llmstxt.org structure: an H1 first, then a blockquote summary, then H2 sections of '- [name](url): note' links."""
    lines = text.splitlines()
    problems = []
    if not lines or not lines[0].startswith("# "):
        problems.append("first line is not an H1")
    if not any(l.startswith("> ") for l in lines[:6]):
        problems.append("no blockquote summary after the H1")
    if sum(1 for l in lines if l.startswith("## ")) < 3:
        problems.append("fewer than three H2 sections")
    if sum(1 for l in lines if l.startswith("# ")) != 1:
        problems.append("more than one H1")
    in_sec = False
    for l in lines:
        if l.startswith("## "):
            in_sec = True
            continue
        if in_sec and l.strip() and not re.match(r"^- \[[^\]]+\]\([^)]+\)(: .+)?$", l):
            problems.append(f"not a link line: {l[:60]}")
            break
    if web is not None:
        for u in re.findall(r"\]\((https?://[^)]+)\)", text):
            if u.startswith(SITE_URL):
                rel = u[len(SITE_URL):]
                target = web / (rel + "index.html" if rel.endswith("/") or rel == "" else rel)
                if not target.exists():
                    problems.append(f"link to a missing file: {rel}")
                    break
    return problems

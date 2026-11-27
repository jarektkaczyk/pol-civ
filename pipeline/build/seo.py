"""Text pages and machine-readable indexes for search engines, generative engines and agents, in English and Polish.

Runs after every other builder and reads only web/data/*.json. It writes, under web/ (English) and web/pl/ (Polish):

    atlas/index.html, atlas/index.md            "Poland in numbers": national figures, the 16 voivodeships, every page
    atlas/<slug>/index.html, index.md           one page per voivodeship and per City View town (cities.json city_view)
    llms.txt, llms-full.txt                     llmstxt.org index, and every page as compact markdown
    pl/index.html                               the Polish app page, made from web/index.html (texts from the catalogue)
    sitemap.xml                                 every page of both languages with lastmod and hreflang alternates
    data/index.json                             the data catalogue (English): each data file, its rows, vintage, publishers

The two languages share slugs: /pol-civ/atlas/krakow/ and /pol-civ/pl/atlas/krakow/. Each page names both as hreflang
alternates (x-default is English) and links within its own language. The atlas sentences are written per language
(EN and PL templates below), never translated whole; data prose (lens labels, publishers, heritage names) goes
through the catalogue (pipeline.core.i18n.t).

Every number on a page comes from a web/data file; each page lists the publishers and years of its figures. A value
that is null in the data is left out of the page, never filled. The headline sentence of a page is the place's best
rank among its peers (16 voivodeships, or the towns of 20,000+ people), computed here.

Share images (web/og/<slug>.jpg, Polish web/og/pl/<slug>.jpg) are rendered from the live app by scripts/og-shots.mjs,
which reads the plan this builder saves in the `_seo` interim. A page points to its own image when it exists, else to
the English one, else to the main share image. Set POLCIV_BUILD_DATE=YYYY-MM-DD to pin the "Last updated" date
(default: today, UTC).
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

from ..core import i18n as I
from ..core.paths import WEB

REQUIRES = ["world.json", "cities.json", "states.json", "nation.json", "counties.json", "metros.json", "wonders.json",
            "districts.json", "resources.json", "sources.json"]
PRODUCES = ["index.json"]
RUN_LAST = True

SITE_URL = "https://softonsofa.com/pol-civ/"
SITE_NAME = "Polska"
APP_TITLE = "Polska: Poland, the Civ way"
AUTHOR = {"@type": "Person", "name": "Jarek Tkaczyk", "url": "https://softonsofa.com/"}
REPO_URL = "https://github.com/jarektkaczyk/pol-civ"
LANGS = ("en", "pl")
PREFIX = {"en": "", "pl": "pl/"}  # site path of each language
OG_LOCALE = {"en": "en_GB", "pl": "pl_PL"}
# Content Security Policy of the text pages (no inline script or style). web/index.html carries APP_CSP; check()
# compares it, so change both together. PostHog EU (analytics, cookieless) and Cloudflare Web Analytics are allowed.
_CSP_COMMON = ("default-src 'self'; script-src 'self' https://eu-assets.i.posthog.com https://static.cloudflareinsights.com; "
               "connect-src 'self' https://eu.i.posthog.com https://eu-assets.i.posthog.com https://cloudflareinsights.com; "
               "img-src 'self' data: blob:; font-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'")
ATLAS_CSP = _CSP_COMMON + "; style-src 'self'"
# The app also reads today's power figures from the PSE open API (ext/power).
APP_CSP = (_CSP_COMMON.replace("https://cloudflareinsights.com;", "https://cloudflareinsights.com https://api.raporty.pse.pl;")
           + "; style-src 'self' 'unsafe-inline'")  # the app sets inline styles from JS
MAIN_OG = "og-image.jpg"
MAIN_OG_PL = "og/pl/main.jpg"
# Cloudflare Web Analytics is injected by js/app/analytics.js (token in js/app/config.js) under the PostHog guard.
# No page may load the beacon directly: check() fails a page that does.
CF_BEACON_HOST = "static.cloudflareinsights.com/beacon"
NEARBY_KM = 30  # heritage sites listed on a town page: within this distance of the town
# Local paths and private names must never reach a public page (the pieces are joined so this file passes the
# release leak gate itself).
LEAK = re.compile("|".join(["beyond" + "indie", "/Us" + "ers/", "/private" + "/tmp", "~/pro" + "jects", "scratch" + "pad",
                            "claude" + "-501"]), re.I)


# --- small helpers ---------------------------------------------------------------------------------------------------

def slug(name: str) -> str:
    """ASCII slug: Polish letters folded (ł to l first, since NFD does not decompose it), marks stripped."""
    s = str(name).replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


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


_ISO_DAY = re.compile(r"(?<![\d-])\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?![\d-])")
_ISO_MONTH = re.compile(r"(?<![\d-])\d{4}-(0[1-9]|1[0-2])(?![\d-])")


def _when(text: str | None, fallback) -> str:
    """The first ISO day ("2025-12-31") or month ("2026-05") in a description, else the fallback year. English
    dates ("31 December 2025") are read as ISO too."""
    text = I.iso_dates(text or "")
    m = _ISO_DAY.search(text) or _ISO_MONTH.search(text)
    if m:
        return m.group(0)
    return str(fallback) if fallback is not None else ""


def rank_of(value, values, high: bool) -> int:
    """Competition rank of value among values (1 = highest when high, else lowest)."""
    return 1 + sum(1 for v in values if (v > value if high else v < value))


# --- Polish grammar --------------------------------------------------------------------------------------------------

PL_MONTH_LOC = ["styczniu", "lutym", "marcu", "kwietniu", "maju", "czerwcu", "lipcu", "sierpniu", "wrześniu",
                "październiku", "listopadzie", "grudniu"]
# Town names that are grammatically plural, beyond what pl_is_plural() reads from the ending.
PL_PLURAL_NAMES = {"Łaziska Górne"}


PL_PLACES = ("pierwsze", "drugie", "trzecie", "czwarte", "piąte", "szóste", "siódme", "ósme", "dziewiąte",
             "dziesiąte", "jedenaste", "dwunaste", "trzynaste", "czternaste", "piętnaste", "szesnaste",
             "siedemnaste", "osiemnaste", "dziewiętnaste", "dwudzieste")


def pl_place(rank: int) -> str:
    return PL_PLACES[rank - 1] if 1 <= rank <= len(PL_PLACES) else f"{rank}."


def pl_result(rank: int, high: bool, group: str) -> str:
    if rank == 1:
        return f"To {'najwyższy' if high else 'najniższy'} wynik {group}."
    return f"To {pl_place(rank)} miejsce{' od końca' if not high else ''} {group}."


def pl_form(n, one: str, few: str, many: str) -> str:
    """The noun form for a count: 1 miasto, 2 miasta, 5 miast (fractions take the "few" form)."""
    cat = I.plural_category(n, "pl")
    return one if cat == "one" else many if cat == "many" else few


def pl_count(n, one: str, few: str, many: str) -> str:
    return f"{I.fmt_num(n, 0, 'pl')} {pl_form(n, one, few, many)}"


def pl_adj(words: str, case: str) -> str:
    """Decline the adjectives of a unit name: "małopolskie" or "lubiński wschodni" to the genitive ("gen") or the
    locative ("loc"). Voivodeship names are neuter (-ie), powiat names masculine (-i, -y)."""
    words = words.lower()
    if case == "nom":
        return words
    # Only the final part of a hyphenated compound changes. Separate adjectives
    # in names such as "warszawski zachodni" both take the requested case.
    soft, hard = {"gen": ("iego", "ego"), "loc": ("im", "ym")}[case]
    return " ".join(re.sub(r"(ie|i|y)$", lambda m: hard if m[0] == "y" else soft, word)
                    for word in words.split())


def pl_voiv(name: str, case: str = "nom") -> str:
    """"Małopolskie" -> "województwo małopolskie" / "województwa małopolskiego" / "województwie małopolskim"."""
    head = {"nom": "województwo", "gen": "województwa", "loc": "województwie"}[case]
    return f"{head} {pl_adj(name, case)}"


def pl_powiat(label: str, case: str = "nom") -> str:
    """"powiat lubiński" -> "powiat lubiński" / "powiatu lubińskiego" / "powiecie lubińskim"."""
    adj = re.sub(r"^powiat\s+", "", label.strip())
    head = {"nom": "powiat", "gen": "powiatu", "loc": "powiecie"}[case]
    return f"{head} {pl_adj(adj, case)}"


def pl_is_plural(name: str) -> bool:
    """Town names that take a plural verb: Katowice, Kielce, Suwałki, Tychy, Tarnowskie Góry, Piekary Śląskie."""
    if name in PL_PLURAL_NAMES:
        return True
    words = [w for w in re.split(r"[ -]", name) if w]
    while len(words) > 1 and words[0] in ("Nowy", "Nowa", "Nowe", "Stary", "Stara", "Stare"):
        words = words[1:]
    return bool(words) and bool(re.search(r"(ce|y|ki|kie)$", words[0]))


def pl_verb(name: str, singular: str, plural: str) -> str:
    return plural if pl_is_plural(name) else singular


class Fmt:
    """Numbers, dates and short words of one language."""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.pl = lang == "pl"
        self.prefix = PREFIX[lang]

    def tr(self, text) -> str:
        """Data prose through the catalogue (ISO dates inside are formatted)."""
        return I.t(text, self.lang) if text else ""

    def int(self, v) -> str:
        return I.fmt_num(round(v), 0, self.lang)

    def num(self, v, digits: int = 1) -> str:
        return I.fmt_num(v, digits, self.lang)

    def pct(self, frac, digits: int = 1, signed: bool = False) -> str:
        s = I.fmt_num(frac * 100, digits, self.lang) + "%"
        return ("+" + s) if signed and frac > 0 else s

    def pln(self, v) -> str:
        return f"{self.int(v)} zł"

    def big(self, v, unit: str = "") -> str:
        """37.3 million, 3.92 trillion zł / 37,3 mln, 3,92 bln zł."""
        tail = f" {unit}" if unit else ""
        for size, en, pl in ((1e12, "trillion", "bln"), (1e9, "billion", "mld"), (1e6, "million", "mln")):
            if abs(v) >= size:
                x = v / size
                s = f"{x:.3g}" if x < 100 else f"{x:.0f}"
                return f"{s.replace('.', ',') if self.pl else s} {pl if self.pl else en}{tail}"
        return f"{self.int(v)}{tail}"

    def years(self, v) -> str:
        return f"{self.num(v, 1)} roku" if self.pl else f"{v:.1f} years"

    def date(self, token) -> str:
        """An ISO day, month or year as a table date: "30 June 2026" / "30 czerwca 2026"."""
        return I.fmt_date(token, self.lang)

    def when_pl(self, token) -> str:
        """A date inside a Polish sentence: "30 czerwca 2026 r.", "w maju 2026 r.", "w 2026 r."."""
        s = str(token or "")
        m = re.fullmatch(r"(\d{4})-(\d{2})", s)
        if m:
            return f"w {PL_MONTH_LOC[int(m.group(2)) - 1]} {m.group(1)} r."
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return f"{I.fmt_date(s, 'pl')} r."
        if re.fullmatch(r"\d{4}", s):
            return f"w {s} r."
        return s

    def residents(self, n) -> str:
        """"803,282 residents" / "803 282 mieszkańców"."""
        return pl_count(n, "mieszkańca", "mieszkańców", "mieszkańców") if self.pl else f"{self.int(n)} residents"


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

    def when(self, key: str) -> str:
        """The date of a figure as an ISO token ("2026-06-30", "2026-05", "2026"), read from the data's own
        descriptions. "pit" gives the plan year."""
        years = self.nation_doc.get("years") or {}
        if key == "population":
            v = (self.source_by_id.get("pl_stats_population") or {}).get("vintage") or self.nation_doc.get("vintage")
            return self.nation_doc.get("population_date") or _when(v, years.get("population"))
        if key == "workers":
            return f"{years['workers']}-12-31" if years.get("workers") else ""
        if key in ("wage", "unemployment"):
            return _when((self.field.get(key) or {}).get("description"), years.get(key))
        if key == "pit":
            return str(years.get("pit") or "")
        if key in self.field:
            return _when(self.field[key].get("description"), None)
        return ""

    def when_text(self, f: Fmt, key: str) -> str:
        """The date column of a figure: "30 June 2026", "2026 plan" / "30 czerwca 2026", "plan na 2026"."""
        tok = self.when(key)
        if key == "pit":
            return (f"plan na {tok}" if tok else "plan") if f.pl else (f"{tok} plan" if tok else "plan")
        return f.date(tok)

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

    def publisher(self, sid: str, lang: str = "en") -> str:
        pub = (self.source_by_id.get(sid) or {}).get("publisher")
        return I.t(pub, lang) if pub else sid


# --- page model ------------------------------------------------------------------------------------------------------
# A page is a dict: lang, slug, path ("atlas/krakow/" or "pl/atlas/krakow/"), kind ("index" | "voivodeship" | "town"),
# name (the place), title, description, h1, sub, lede, paras [str], open (label, deep link), sections
# [{h2, rows | items | paras | table | groups}], sources [(text, url | None)], crumbs [(name, path)], place (JSON-LD
# nodes or None), og ("og/krakow.jpg"), og_number (text for the share image), focus (for the share image:
# {"city": id} | {"state": abbr}), alts {lang: path} (set by build_site).
# Table rows are (label, value text, when text, source id). List items are (text, link path or None, note).


class Sources:
    """Collects the sources a page cites, in order of first use."""

    def __init__(self, d: Data, f: Fmt | None = None):
        self.d = d
        self.f = f or Fmt("en")
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
        tr = self.f.tr
        out = []
        for sid in self.ids:
            s = self.d.source_by_id.get(sid)
            if not s:  # not in sources.json: nothing to cite by name
                continue
            pub = tr(s.get("publisher")) or sid
            title = tr(s.get("title"))
            vint = tr(s.get("vintage"))
            out.append((f"{pub}: {title}" + (f" ({vint})" if vint else ""), s.get("homepage")))
        out.extend((t, u) for t, u in self.extra)
        return out


def _row(src: Sources, label, value, when, sid):
    return (label, value, when, src.use(sid))


def heritage_items(d: Data, src: Sources, wonders) -> list[tuple[str, str | None, str]]:
    """List items for heritage sites, parks, universities and landmarks. Memorials are named as memorials."""
    f = src.f
    kind_src = {"unesco": "pl_soc_heritage", "memorial": "pl_soc_heritage", "natural": "pl_soc_parks",
                "university": "pl_soc_universities"}
    out = []
    for wd in wonders:
        kind = wd.get("kind")
        m = wd.get("metrics") or {}
        name = f.tr(wd.get("name") or wd.get("short"))
        if kind == "memorial":
            if f.pl:
                note = (f"Miejsce pamięci i muzeum, na Liście światowego dziedzictwa UNESCO od {m['inscribed']} r."
                        if m.get("inscribed") else "Miejsce pamięci i muzeum")
            else:
                note = f"Memorial and museum, UNESCO World Heritage since {m['inscribed']}" if m.get("inscribed") else "Memorial and museum"
        elif kind == "unesco":
            if f.pl:
                note = (f"Obiekt na Liście światowego dziedzictwa UNESCO od {m['inscribed']} r." if m.get("inscribed")
                        else "Obiekt na Liście światowego dziedzictwa UNESCO")
            else:
                note = f"UNESCO World Heritage site since {m['inscribed']}" if m.get("inscribed") else "UNESCO World Heritage site"
        elif kind == "natural":
            vis = num(m.get("visits"))
            latest = num(m.get("visits_latest"))
            if f.pl:
                def visits(n, y):
                    return f"{pl_count(n, 'wizyta', 'wizyty', 'wizyt')} w {y} r."
                note = "Park narodowy" + (f", {visits(vis, m.get('year'))}" if vis and m.get("year") else "")
                if latest and m.get("latest_year"):
                    note = (f"Park narodowy, {visits(latest, m['latest_year'])}"
                            + (f" ({f.int(vis)} w {m.get('year')} r.)" if vis and m.get("year") else ""))
            else:
                note = "National park" + (f", {f.int(vis)} visits in {m.get('year')}" if vis and m.get("year") else "")
                if latest and m.get("latest_year"):
                    note = (f"National park, {f.int(latest)} visits in {m['latest_year']}"
                            + (f" ({f.int(vis)} in {m.get('year')})" if vis and m.get("year") else ""))
        elif kind == "university":
            st = num(m.get("students"))
            if f.pl:
                note = "Uczelnia"
                if st:
                    note += f", {pl_count(st, 'student', 'studentów', 'studentów')}"
                    if m.get("students_year"):
                        note += f" (stan na 31 grudnia {m['students_year']} r.)"
            else:
                note = "University" + (f", {f.int(st)} students on 31 December {m.get('students_year')}" if st and m.get("students_year") else f", {f.int(st)} students" if st else "")
        else:
            rec, val = m.get("record"), num(m.get("value"))
            note = f.tr(rec) or ("Obiekt wyjątkowy" if f.pl else "Landmark")
            if val is not None:
                shown = f.int(val) if val >= 1000 or float(val).is_integer() else (f.num(val, 1) if f.pl else val)
                note += f": {shown} {f.tr(m.get('unit'))}".rstrip()
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


def _town_scope(f: Fmt, c: dict) -> str:
    """Words for the unit of a gmina-level figure: the town itself, or its whole urban-rural gmina."""
    if c.get("scope") == "urban-rural gmina":
        return f" (cała gmina {c['name']})" if f.pl else f" (whole gmina of {c['name']})"
    return ""


def _powiat_words(c: dict, g: dict | None) -> str:
    if c.get("kind") == "city":
        return c["name"]
    lab = (g or {}).get("powiat") or "its powiat"
    return lab


# headline metrics for towns: (key, value getter, allow high, allow low, sentence, source id, sentence needs the count)
STRIKING_RANK = 10  # a headline other than size needs a top-10 place at either end


def _town_metrics(d: Data, f: Fmt):
    def g(c, k):
        return num((d.gmina.get(c.get("gmina")) or {}).get(k))

    n_all = len(d.view_towns)
    peer = f"of the {n_all} Polish towns with 20,000 or more people"
    peer_any = f"for any of the {n_all} Polish towns with 20,000 or more people"
    peer_pl = f"wśród {f.int(n_all)} miast liczących co najmniej 20 tys. mieszkańców"

    def who(c):
        """Gmina-level figures of a town inside an urban-rural gmina describe the whole gmina."""
        return f"the gmina of {c['name']}" if c.get("scope") == "urban-rural gmina" else c["name"]

    def gmina_pl(c):
        return f"w gminie {c['name']}" if c.get("scope") == "urban-rural gmina" else "w mieście"

    def around(c):
        return c["name"] if c.get("kind") == "city" else f"{c['name']} ({_powiat_words(c, d.gmina.get(c.get('gmina')))})"

    def powiat_pl(c):
        """Location of a powiat-level figure on a town page."""
        lab = (d.gmina.get(c.get("gmina")) or {}).get("powiat")
        if c.get("kind") == "city" or not lab or not str(lab).startswith("powiat"):
            return "w mieście" if c.get("kind") == "city" else "w powiecie"
        return f"w {pl_powiat(lab, 'loc')}"

    def cap(t):
        return t[:1].upper() + t[1:]

    def s_growth(c, v, r, high):
        if f.pl:
            change, trend = ("wzrosła", "wzrostu") if high else ("spadła", "spadku")
            return (f"W latach 2015-2025 liczba mieszkańców miasta {change} o {f.pct(abs(v))}. "
                    f"Pod względem tempa {trend} {c['name']} {pl_verb(c['name'], 'zajmuje', 'zajmują')} "
                    f"{pl_place(r)} miejsce {peer_pl}.")
        if high:
            return f"{c['name']} grew by {f.pct(v)} between 2015 and 2025, {the_nth(r, 'fastest growth')} {peer}."
        return f"{c['name']} lost {f.pct(-v)} of its residents between 2015 and 2025, {the_nth(r, 'steepest fall')} {peer}."

    def s_wage(c, v, r, high):
        if f.pl:
            return (f"{cap(f.when_pl(d.when('wage')))} przeciętne miesięczne wynagrodzenie brutto {powiat_pl(c)} "
                    f"wyniosło {f.pln(v)}. {pl_result(r, high, peer_pl)}")
        word = "highest" if high else "lowest"
        lead = f"The average gross wage in {c['name']}" if c.get("kind") == "city" else f"The average gross wage around {around(c)}"
        return f"{lead} was {f.pln(v)} a month in {f.date(d.when('wage'))}, {the_nth(r, word)} {peer_any}."

    def s_unemp(c, v, r, high):
        if f.pl:
            return (f"{cap(f.when_pl(d.when('unemployment')))} stopa bezrobocia rejestrowanego {powiat_pl(c)} "
                    f"wyniosła {f.pct(v)}. {pl_result(r, high, peer_pl)}")
        word = "highest" if high else "lowest"
        lead = f"Registered unemployment in {c['name']}" if c.get("kind") == "city" else f"Registered unemployment around {around(c)}"
        return f"{lead} was {f.pct(v)} in {f.date(d.when('unemployment'))}, {the_nth(r, word)} {peer_any}."

    def s_pit(c, v, r, high):
        year = (d.nation_doc.get("years") or {}).get("pit")
        if f.pl:
            plan = f"Plan na {year} r." if year else "Plan budżetowy"
            return (f"{plan} przewiduje {gmina_pl(c)} dochody z PIT w wysokości {f.pln(v)} na mieszkańca. "
                    f"{pl_result(r, high, peer_pl)}")
        word = "highest" if high else "lowest"
        return (f"{cap(who(c))} expects {f.pln(v)} per resident from its share of personal income tax"
                + (f" in {year}" if year else "") + f", {the_nth(r, word)} {peer}.")

    def s_age(c, v, r, high):
        if f.pl:
            return f"Mediana wieku {gmina_pl(c)} wynosi {f.years(v)}. {pl_result(r, high, peer_pl)}"
        word = "oldest" if high else "youngest"
        return f"{cap(who(c))} has {the_nth(r, word)} population {peer}: a median age of {v:.1f} years."

    def s_pm(c, v, r, high, n):
        if f.pl:
            group = f"wśród {f.int(n)} miast liczących co najmniej 20 tys. mieszkańców ze stacją pomiarową w promieniu 25 km"
            return (f"W 2025 r. średnie roczne stężenie pyłu PM2,5 na najbliższej stacji wyniosło {f.num(v)} µg/m³. "
                    f"{pl_result(r, high, group)}")
        word = "most polluted" if high else "cleanest"
        return (f"{c['name']} has {the_nth(r, word)} air of the {n} towns of 20,000+ with a measuring station within 25 km: "
                f"PM2.5 averaged {v:.1f} µg/m³ in 2025 at the nearest station.")

    def s_turnout(c, v, r, high):
        if f.pl:
            return (f"W drugiej turze wyborów prezydenckich 1 czerwca 2025 r. frekwencja {gmina_pl(c)} wyniosła "
                    f"{f.pct(v)}. {pl_result(r, high, peer_pl)}")
        word = "highest" if high else "lowest"
        return f"Turnout in {who(c)} was {f.pct(v)} in the presidential runoff of 1 June 2025, {the_nth(r, word)} {peer}."

    def s_students(c, v, r, high, n):
        if f.pl:
            group = f"wśród {f.int(n)} miast liczących co najmniej 20 tys. mieszkańców, w których działa uczelnia"
            return (f"Na 1000 mieszkańców przypada tu {pl_count(round(v), 'student', 'studentów', 'studentów')}. "
                    f"{pl_result(r, high, group)}")
        return (f"{c['name']} has {f.int(v)} university students per 1,000 residents, {the_nth(r, 'highest share')} "
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


def town_headline(d: Data, c: dict, f: Fmt | None = None) -> tuple[str, str | None]:
    """(sentence, source id): the town's most striking true fact.

    Its size rank among all towns, or a top-10 place at either end of a metric among the towns of 20,000+ (the
    City View towns), whichever rank is better; size wins a tie. A town with no top-10 place leads with its size.
    """
    f = f or Fmt("en")
    name = c["name"]
    pr = (c.get("ranks") or {}).get("population")
    pop = num(c.get("population"))
    when = d.when("population")
    counts = f"{pl_verb(name, 'Liczy', 'Liczą')} {f.residents(pop)} (stan na {f.when_pl(when)})." if f.pl and pop else ""
    best = None
    if pr and pop:
        if c.get("capital"):
            text = (f"{name} to stolica i największe miasto Polski. {counts}" if f.pl else
                    f"{name} is the capital and the largest city of Poland, with {f.int(pop)} residents on {f.date(when)}.")
        else:
            text = (f"{name} {pl_verb(name, 'zajmuje', 'zajmują')} {pl_place(pr)} miejsce w Polsce pod względem liczby "
                    f"mieszkańców. {counts}" if f.pl else
                    f"{name} is {the_nth(pr, 'largest ' + town_word(c))} in Poland, with {f.int(pop)} residents on {f.date(when)}.")
        best = (pr, 0, text, "pl_geo_places")
    for order, (key, get, hi, lo, sentence, sid, needs_n) in enumerate(_town_metrics(d, f), start=1):
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
        if f.pl:
            tail = (f" W latach 2015-2025 liczba ludności wzrosła o {f.pct(g)}." if g and g > 0
                    else f" W latach 2015-2025 liczba ludności spadła o {f.pct(-g)}." if g and g < 0 else "")
            return f"{name} {pl_verb(name, 'liczy', 'liczą')} {f.residents(pop)} (stan na {f.when_pl(when)}).{tail}", "pl_geo_places"
        tail = (f" Between 2015 and 2025 it grew by {f.pct(g)}." if g and g > 0
                else f" Between 2015 and 2025 it lost {f.pct(-g)} of its residents." if g and g < 0 else "")
        return f"{name} had {f.int(pop)} residents on {f.date(when)}.{tail}", "pl_geo_places"
    if best:
        return best[2], best[3]
    return (f"{name} to miasto w Polsce." if f.pl else f"{name} is a {town_word(c)} in Poland."), None


def _state_metrics(d: Data, f: Fmt | None = None):
    f = f or Fmt("en")
    gdps = [num(s.get("gdp")) for s in d.states]
    total = sum(x for x in gdps if x) if all(gdps) else None

    def cap(s, k):
        caps = s.get("capitals") or []
        g = d.gmina.get(caps[0]["gmina"]) if caps else None
        return num((g or {}).get(k))

    def gdp_share(s):
        g = num(s.get("gdp"))
        return g / total if g and total else None

    def region(s):
        return "w " + pl_voiv(s["name"], "loc")

    def s_pop(s, v, r, high):
        if f.pl:
            return (f"{f.when_pl(d.when('population')).capitalize()} {pl_voiv(s['name'])} liczyło {f.residents(v)}. "
                    f"{pl_result(r, high, 'wśród województw')}")
        word = "most populous" if high else "least populous"
        return f"{s['name']} is {the_nth(r, word)} voivodeship, with {f.int(v)} residents on {f.date(d.when('population'))}."

    def s_growth(s, v, r, high):
        if f.pl:
            lead = f"W latach 2015-2025 liczba ludności {pl_voiv(s['name'], 'gen')}"
            change = (f"wzrosła o {f.pct(v)}" if v > 0 else f"spadła o {f.pct(-v)}" if v < 0
                      else "nie zmieniła się")
            return f"{lead} {change}. {pl_result(r, high, 'w rankingu zmiany liczby ludności województw')}"
        if v > 0:
            return f"{s['name']} grew by {f.pct(v)} between 2015 and 2025, {the_nth(r, 'fastest growth')} of the 16 voivodeships."
        if high:
            return f"{s['name']} lost {f.pct(-v)} of its residents between 2015 and 2025, {the_nth(r, 'smallest fall')} of the 16 voivodeships."
        return f"{s['name']} lost {f.pct(-v)} of its residents between 2015 and 2025, {the_nth(r, 'steepest fall')} of the 16 voivodeships."

    def s_gdp(s, v, r, high):
        if f.pl:
            return (f"W {s.get('gdp_year')} r. PKB {pl_voiv(s['name'], 'gen')} wyniósł {f.big(s['gdp'], 'zł')}, "
                    f"czyli {f.pct(v)} krajowego PKB. {pl_result(r, high, 'wśród województw')}")
        word = "largest economy" if high else "smallest economy"
        return (f"{s['name']} is {the_nth(r, word)} of the 16 voivodeships: {f.pct(v)} of Poland's GDP in "
                f"{s.get('gdp_year')}, {f.big(s['gdp'], 'zł')}.")

    def s_wage(s, v, r, high):
        if f.pl:
            return (f"{f.when_pl(d.when('wage')).capitalize()} przeciętne miesięczne wynagrodzenie brutto {region(s)} "
                    f"wyniosło {f.pln(v)}. {pl_result(r, high, 'wśród województw')}")
        word = "highest" if high else "lowest"
        return f"{s['name']} has {the_nth(r, word)} average gross wage of the 16 voivodeships: {f.pln(v)} a month in {f.date(d.when('wage'))}."

    def s_unemp(s, v, r, high):
        if f.pl:
            return (f"{f.when_pl(d.when('unemployment')).capitalize()} stopa bezrobocia rejestrowanego {region(s)} "
                    f"wyniosła {f.pct(v)}. {pl_result(r, high, 'wśród województw')}")
        word = "highest" if high else "lowest"
        return f"{s['name']} has {the_nth(r, word)} registered unemployment of the 16 voivodeships: {f.pct(v)} in {f.date(d.when('unemployment'))}."

    def s_pit(s, v, r, high):
        year = d.nation_doc.get("years", {}).get("pit", "")
        if f.pl:
            return (f"Planowane na {year} r. dochody gmin z PIT {region(s)} wynoszą {f.pln(v)} na mieszkańca. "
                    f"{pl_result(r, high, 'wśród województw')}")
        word = "highest" if high else "lowest"
        return f"{s['name']} has {the_nth(r, word)} personal income tax revenue per resident of the 16 voivodeships: {f.pln(v)} planned for {year}."

    def s_forest(s, v, r, high):
        if f.pl:
            return (f"Drzewa pokrywają {f.pct(v, 0)} powierzchni {pl_voiv(s['name'], 'gen')}. "
                    f"{pl_result(r, high, 'wśród województw')}")
        word = "most" if high else "least"
        return f"{s['name']} has {the_nth(r, word)} tree cover of the 16 voivodeships: {f.pct(v, 0)} of its land."

    def s_life(s, v, r, high):
        if f.pl:
            return (f"W 2025 r. {region(s)} przeciętne dalsze trwanie życia nowo narodzonych dziewczynek wynosiło "
                    f"{f.years(v)}. {pl_result(r, high, 'wśród województw')}")
        word = "longest" if high else "shortest"
        return f"Women in {s['name']} have {the_nth(r, word)} life expectancy of the 16 voivodeships: {v:.1f} years at birth in 2025."

    def s_tour(s, v, r, high):
        if f.pl:
            return (f"W 2025 r. {region(s)} na mieszkańca przypadało średnio {f.num(v)} noclegu udzielonego turystom. "
                    f"{pl_result(r, high, 'wśród województw')}")
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


def state_headline(d: Data, s: dict, f: Fmt | None = None) -> tuple[str, str | None]:
    f = f or Fmt("en")
    metrics, _, _ = _state_metrics(d, f)
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
    if best:
        return best[2], best[3]
    return (f"{pl_voiv(s['name']).capitalize()} to województwo w Polsce." if f.pl
            else f"{s['name']} is a voivodeship of Poland."), None


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
                extra_names=None, lang: str = "en") -> list[dict]:
    """The place node, plus an Observation (a QuantitativeValue with a date) for its population."""
    pl = lang == "pl"
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
        unit = "mieszkańcy" if pl else "residents"
        node["additionalProperty"] = {"@type": "PropertyValue", "propertyID": "population",
                                      "name": "Ludność" if pl else "Population", "value": pop, "unitText": unit}
        obs = {"@type": "Observation", "@id": url + "#population",
               "name": f"Ludność: {name}" if pl else f"Population of {name}",
               "observationAbout": {"@id": url + "#place"}, "variableMeasured": "population", "value": pop,
               "unitText": unit}
        if pop_date:
            obs["observationDate"] = pop_date
        out.append(obs)
    return out


def _iso_day(token: str) -> str | None:
    return token if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token or "") else None


def _jsonld(page: dict, date: str) -> dict:
    lang = page.get("lang", "en")
    home = SITE_URL + PREFIX[lang]
    url = SITE_URL + page["path"]
    crumbs = [{"@type": "ListItem", "position": i + 1, "name": n, "item": SITE_URL + p} for i, (n, p) in enumerate(page["crumbs"])]
    web = {"@type": "WebPage", "@id": url, "url": url, "name": page["title"], "description": page["description"],
           "inLanguage": lang, "dateModified": date, "author": AUTHOR,
           "isPartOf": {"@type": "WebSite", "@id": home + "#website", "name": SITE_NAME, "url": home},
           "breadcrumb": {"@id": url + "#breadcrumb"},
           "primaryImageOfPage": {"@type": "ImageObject", "url": SITE_URL + page["og"]}}
    graph = [web, {"@type": "BreadcrumbList", "@id": url + "#breadcrumb", "itemListElement": crumbs}]
    if page.get("place"):
        web["about"] = {"@id": page["place"][0]["@id"]}
        graph.extend(page["place"])
    return {"@context": "https://schema.org", "@graph": graph}


def _main_og(web: Path, lang: str = "en") -> str:
    if lang == "pl" and (web / MAIN_OG_PL).exists():
        return MAIN_OG_PL
    return MAIN_OG if (web / MAIN_OG).exists() else "og-image.png"


def _og_for(web: Path, sl: str, lang: str = "en") -> str:
    """The page's share image: og/pl/<slug>.jpg (Polish), else og/<slug>.jpg, else the main image."""
    if lang == "pl" and (web / f"og/pl/{sl}.jpg").exists():
        return f"og/pl/{sl}.jpg"
    rel = f"og/{sl}.jpg"
    if (web / rel).exists():
        return rel
    return _main_og(web, lang)


def build_pages(d: Data, web: Path, lang: str = "en") -> list[dict]:
    f = Fmt(lang)
    st_slug, tw_slug = page_paths(d)
    pages = [index_page(d, web, st_slug, tw_slug, f)]
    for i, s in enumerate(d.states):
        pages.append(state_page(d, web, i, s, st_slug, tw_slug, f))
    for c in sorted(d.view_towns, key=lambda c: -(num(c.get("population")) or 0)):
        pages.append(town_page(d, web, c, st_slug, tw_slug, f))
    for p in pages:
        p["lang"] = lang
    return pages


def index_page(d: Data, web: Path, st_slug: dict, tw_slug: dict, f: Fmt | None = None) -> dict:
    f = f or Fmt("en")
    L = (lambda en, pl: pl) if f.pl else (lambda en, pl: en)
    pre = f.prefix
    src = Sources(d, f)
    n = d.nation
    pop, growth = num(n.get("population")), num(n.get("growth"))
    when_pop = d.when("population")
    pop_date = f.date(when_pop)
    rows = []
    if pop:
        rows.append(_row(src, L("Population", "Ludność"), f.int(pop), pop_date, "pl_stats_population"))
    if growth is not None:
        series = n.get("pop_series") or {}
        rows.append(_row(src, L("Change since 2015", "Zmiana od 2015 r."),
                         f.pct(growth, 1, True) + (f" ({L('from', 'z')} {f.int(series['2015'])})" if series.get("2015") else ""),
                         L("2015 to 2025", "2015-2025"), "pl_stats_population"))
    if num(n.get("gdp")):
        rows.append(_row(src, L("GDP", "PKB"), f.big(n["gdp"], "zł"), str(n.get("gdp_year", "")), "pl_gdp"))
        if pop:
            rows.append(_row(src, L("GDP per resident", "PKB na mieszkańca"), f.pln(n["gdp"] / pop),
                             L(f"{n.get('gdp_year')} GDP, {when_pop[:4]} residents", f"PKB {n.get('gdp_year')}, ludność {when_pop[:4]}"),
                             "pl_gdp"))
    if num(n.get("wage")):
        rows.append(_row(src, L("Average gross wage", "Przeciętne miesięczne wynagrodzenie brutto"),
                         L(f"{f.pln(n['wage'])} a month", f.pln(n["wage"])), d.when_text(f, "wage"), "pl_stats_labour"))
    if num(n.get("unemployment")) is not None:
        rows.append(_row(src, L("Registered unemployment", "Stopa bezrobocia rejestrowanego"), f.pct(n["unemployment"]),
                         d.when_text(f, "unemployment"), "pl_stats_labour"))
    if num(n.get("employed")):
        rows.append(_row(src, L("People working", "Pracujący"), f.int(n["employed"]), d.when_text(f, "workers"), "pl_stats_labour"))
    if num(n.get("pit_per_person")):
        rows.append(_row(src, L("Personal income tax revenue of the gminas per resident", "Dochody gmin z PIT na mieszkańca"),
                         f.pln(n["pit_per_person"]), d.when_text(f, "pit"), "pl_stats_prosperity"))
    wn = d.wonders_doc.get("national") or {}
    if wn.get("unesco_properties"):
        rows.append(_row(src, L("UNESCO World Heritage properties", "Obiekty na Liście światowego dziedzictwa UNESCO"),
                         f.int(wn["unesco_properties"]), "2026", "pl_soc_heritage"))
    if wn.get("national_parks"):
        rows.append(_row(src, L("National parks", "Parki narodowe"), f.int(wn["national_parks"]),
                         str(wn.get("park_visits_year", "")), "pl_soc_parks"))
    if wn.get("park_visits"):
        rows.append(_row(src, L("Visits to national parks", "Liczba wizyt w parkach narodowych"), f.int(wn["park_visits"]),
                         str(wn.get("park_visits_year", "")), "pl_soc_parks"))
    counts = []
    if d.gmina:
        counts.append(pl_count(len(d.gmina), "gminę", "gminy", "gmin") if f.pl else f"{len(d.gmina):,} gminas")
    powiaty = _load(d.dir, "powiaty.json")
    if isinstance(powiaty, dict) and powiaty.get("rows"):
        k = len(powiaty["rows"])
        counts.append(pl_count(k, "powiat", "powiaty", "powiatów") if f.pl else f"{k} powiats")
    if d.cities:
        counts.append(pl_count(len(d.cities), "miasto", "miasta", "miast") if f.pl else f"{len(d.cities):,} towns")
    src.use("pl_geo_teryt")

    # voivodeship table (static, by population)
    metrics, gdp_share, cap = _state_metrics(d, f)
    vrows = []
    for s in sorted(d.states, key=lambda s: -(num(s.get("population")) or 0)):
        caps = ", ".join(c["name"] for c in s.get("capitals") or [])
        vrows.append([(s["name"], f"{st_slug[s['abbr']]}/"), caps,
                      f.int(s["population"]) if num(s.get("population")) else "",
                      f.pct(s["growth"], 1, True) if num(s.get("growth")) is not None else "",
                      f.pct(gdp_share(s)) if gdp_share(s) else "",
                      f.pln(s["wage"]) if num(s.get("wage")) else "",
                      f.pct(s["unemployment"]) if num(s.get("unemployment")) is not None else ""])
    gdp_year = next((s.get("gdp_year") for s in d.states if s.get("gdp_year")), "")
    wage_d, unemp_d = f.date(d.when("wage")), f.date(d.when("unemployment"))
    head = (["Województwo", "Stolica", f"Ludność, {pop_date}", "Zmiana 2015-2025", f"Udział w PKB, {gdp_year}",
             f"Przeciętne wynagrodzenie, {wage_d}", f"Stopa bezrobocia, {unemp_d}"] if f.pl else
            ["Voivodeship", "Capital", f"Population, {pop_date}", "Change 2015-2025", f"Share of GDP, {gdp_year}",
             f"Average wage, {wage_d}", f"Unemployment, {unemp_d}"])
    vtable = {"head": head, "rows": vrows}
    for sid in ("pl_gdp", "pl_stats_labour"):
        src.use(sid)

    towns_by_state = []
    for s in sorted(d.states, key=lambda s: s["name"]):
        items = [(t["name"], f"{tw_slug[t['id']]}/", f.int(t["population"]) if num(t.get("population")) else "")
                 for t in sorted((t for t in d.view_towns if t.get("voivodeship") == s.get("fips")), key=lambda t: t["name"])]
        towns_by_state.append({"h3": s["name"], "items": items})

    largest = max(d.states, key=lambda s: num(s.get("population")) or 0) if d.states else None
    paras = []
    if f.pl:
        lede = (f"{f.when_pl(when_pop)} Polska liczyła {f.residents(pop)}."
                + (f" W latach 2015-2025 liczba ludności spadła o {f.pct(-growth)}." if growth and growth < 0
                   else f" W latach 2015-2025 liczba ludności wzrosła o {f.pct(growth)}." if growth else "")) if pop else "Polska w liczbach."
        lede = lede[:1].upper() + lede[1:]
        if counts:
            units = [f"{len(d.states)} województw", *counts]
            if len(counts) == 3:
                units[1], units[2] = units[2], units[1]
            paras.append(f"Polska ma {', '.join(units[:-1])} i {units[-1]}.")
        if largest and num(n.get("gdp")):
            gdp_text = f"PKB Polski wyniósł w {n.get('gdp_year')} r. {f.big(n['gdp'], 'zł')}."
            paras.append(gdp_text + (f" Na {pl_voiv(largest['name'])} przypadło {f.pct(gdp_share(largest))} "
                                     f"krajowego PKB w {largest.get('gdp_year')} r."
                                     if gdp_share(largest) else ""))
        title = "Polska w liczbach: ludność, gospodarka i 16 województw"
        n_towns = pl_count(len(d.view_towns), "miasta", "miast", "miast")
        desc = (f"{f.when_pl(when_pop)} Polska liczyła {f.residents(pop)}"
                + (f", a jej PKB wyniósł w {n.get('gdp_year')} r. {f.big(n['gdp'], 'zł')}" if num(n.get("gdp")) else "")
                + f". Dane dla 16 województw i {n_towns}, ze źródłami.") if pop else "Polska w liczbach."
        desc = desc[:1].upper() + desc[1:]
    else:
        lede = (f"Poland had {f.int(pop)} residents on {pop_date}." + (f" Between 2015 and 2025 the population fell by {f.pct(-growth)}." if growth and growth < 0
                else f" Between 2015 and 2025 the population grew by {f.pct(growth)}." if growth else "")) if pop else "Poland in numbers."
        if counts:
            paras.append(f"The country has 16 voivodeships, {', '.join(counts[:-1])} and {counts[-1]}." if len(counts) > 1 else f"The country has 16 voivodeships and {counts[0]}.")
        if largest and num(n.get("gdp")):
            paras.append(f"Its GDP was {f.big(n['gdp'], 'zł')} in {n.get('gdp_year')}. {largest['name']}, around Warszawa, is the largest "
                         f"voivodeship by population and produced {f.pct(gdp_share(largest))} of the national GDP in {largest.get('gdp_year')}."
                         if gdp_share(largest) else f"Its GDP was {f.big(n['gdp'], 'zł')} in {n.get('gdp_year')}.")
        paras.append("Each voivodeship and each town of 20,000 or more people has its own page below, with its figures and their sources.")
        title = "Poland in numbers: population, economy and the 16 voivodeships"
        desc = (f"Poland had {f.int(pop)} residents on {pop_date}" + (f" and a GDP of {f.big(n['gdp'], 'zł')} in {n.get('gdp_year')}" if num(n.get("gdp")) else "")
                + f". Figures for the 16 voivodeships and {len(d.view_towns)} towns, with sources.") if pop else "Poland in numbers."
    place = _place_node(SITE_URL + pre + "atlas/", L("Poland", "Polska"), "Country", None, None, pop, _iso_day(when_pop), None,
                        [L("Polska", "Poland")], f.lang)
    h1 = L("Poland in numbers", "Polska w liczbach")
    return {
        "slug": "atlas", "path": pre + "atlas/", "kind": "index", "name": h1, "title": title, "description": desc, "h1": h1,
        "lede": lede, "paras": paras, "open": (L("Open the map", "Otwórz mapę"), pre),
        "crumbs": [(SITE_NAME, pre), ("Atlas", pre + "atlas/")],
        "sections": [
            {"h2": L("National figures", "Dane krajowe"), "rows": rows},
            {"h2": L("The 16 voivodeships", "16 województw"), "table": vtable},
            {"h2": L("Towns of 20,000 or more people", "Miasta liczące co najmniej 20 tys. mieszkańców"), "groups": towns_by_state},
        ],
        "sources": src.lines(), "place": place, "og": _main_og(web, f.lang),
        "og_number": (f"{f.big(pop)} " + L("people", "mieszkańców")) if pop else "", "focus": {},
    }


def state_page(d: Data, web: Path, idx: int, s: dict, st_slug: dict, tw_slug: dict, f: Fmt | None = None) -> dict:
    f = f or Fmt("en")
    L = (lambda en, pl: pl) if f.pl else (lambda en, pl: en)
    pre = f.prefix
    src = Sources(d, f)
    sl = st_slug[s["abbr"]]
    name = s["name"]
    lede, lede_sid = state_headline(d, s, f)
    src.use(lede_sid)
    metrics, gdp_share, cap = _state_metrics(d, f)
    when_pop = d.when("population")
    rows = []
    if num(s.get("population")):
        rows.append(_row(src, L("Population", "Ludność"), f.int(s["population"]), f.date(when_pop), "pl_stats_population"))
    if num(s.get("growth")) is not None:
        rows.append(_row(src, L("Change since 2015", "Zmiana od 2015 r."), f.pct(s["growth"], 1, True),
                         L("2015 to 2025", "2015-2025"), "pl_stats_population"))
    if num(s.get("gdp")):
        share = gdp_share(s)
        rows.append(_row(src, L("GDP", "PKB"), f.big(s["gdp"], "zł") + (L(f" ({f.pct(share)} of Poland)", f" ({f.pct(share)} PKB Polski)") if share else ""),
                         str(s.get("gdp_year", "")), "pl_gdp"))
    if num(s.get("wage")):
        rows.append(_row(src, L("Average gross wage", "Przeciętne miesięczne wynagrodzenie brutto"),
                         L(f"{f.pln(s['wage'])} a month", f.pln(s["wage"])), d.when_text(f, "wage"), "pl_stats_labour"))
    if num(s.get("unemployment")) is not None:
        rows.append(_row(src, L("Registered unemployment", "Stopa bezrobocia rejestrowanego"), f.pct(s["unemployment"]),
                         d.when_text(f, "unemployment"), "pl_stats_labour"))
    if num(s.get("employed")):
        rows.append(_row(src, L("People working", "Pracujący"), f.int(s["employed"]), d.when_text(f, "workers"), "pl_stats_labour"))
    if num(s.get("pit_per_person")):
        rows.append(_row(src, L("Personal income tax revenue of the gminas per resident", "Dochody gmin z PIT na mieszkańca"),
                         f.pln(s["pit_per_person"]), d.when_text(f, "pit"), "pl_stats_prosperity"))
    for key, label, fmt in (("life_f", L("Life expectancy at birth, women", "Przeciętne dalsze trwanie życia nowo narodzonych dziewczynek"), f.years),
                            ("life_m", L("Life expectancy at birth, men", "Przeciętne dalsze trwanie życia nowo narodzonych chłopców"), f.years),
                            ("tourism", L("Tourist nights per resident", "Udzielone noclegi na 1 mieszkańca"), lambda v: f.num(v, 1)),
                            ("dwellings", L("New dwellings per 1,000 residents", "Mieszkania oddane do użytkowania na 1000 ludności"), lambda v: f.num(v, 1))):
        v = cap(s, key)
        if v is not None:
            fd = d.field.get(key) or {}
            rows.append(_row(src, label, fmt(v), f.date(_when(fd.get("description"), None) or "2025"), fd.get("source")))
    forest = num((s.get("land") or {}).get("forest"))
    if forest is not None:
        rows.append(_row(src, L("Tree cover", "Pokrycie terenu drzewami"),
                         L(f"{f.pct(forest, 0)} of the land", f"{f.pct(forest, 0)} powierzchni"), "2021", "pl_geo_worldcover"))

    caps = s.get("capitals") or []
    cap_text = ""
    if len(caps) == 1:
        cap_text = L(f"Its capital is {caps[0]['name']}.",
                     f"Stolicą województwa {pl_verb(caps[0]['name'], 'jest', 'są')} {caps[0]['name']}.")
    elif caps:
        vo = [c["name"] for c in caps if c.get("role") in ("voivode", "both")]
        sj = [c["name"] for c in caps if c.get("role") in ("sejmik", "both")]
        cap_text = L(f"The voivode sits in {', '.join(vo)} and the regional assembly (sejmik) in {', '.join(sj)}.",
                     f"Siedzibą wojewody {pl_verb(vo[0], 'jest', 'są') if len(vo) == 1 else 'są'} {', '.join(vo)}, "
                     f"a sejmiku województwa {', '.join(sj)}.")
    towns = sorted((c for c in d.cities if c.get("voivodeship") == s.get("fips")), key=lambda c: -(num(c.get("population")) or 0))
    big_n = sum(1 for t in towns if t.get("city_view"))
    if f.pl:
        verb = "liczą" if I.plural_category(big_n, "pl") == "few" else "liczy"
        towns_text = (f"W województwie {pl_form(len(towns), 'jest', 'są', 'jest')} "
                      f"{pl_count(len(towns), 'miasto', 'miasta', 'miast')}. {f.int(big_n)} z nich {verb} "
                      f"co najmniej 20 tys. mieszkańców.") if towns else ""
    else:
        towns_text = f"It has {len(towns)} towns; {big_n} of them have 20,000 or more residents." if towns else ""
    paras = [p for p in [cap_text, towns_text] if p]
    src.use("pl_geo_places")
    top = [(t["name"], f"../{tw_slug[t['id']]}/" if t["id"] in tw_slug else None, f.residents(t["population"]))
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
        note = f.tr(t.get("name", ""))
        if t.get("unit") == "MW":
            note += f", {f.int(i['value'])} MW"
        elif num(i.get("output")) is not None and i.get("output_unit"):
            out_v = f.num(i["output"], 1) if f.pl else f"{i['output']:,.1f}"
            note += f", {out_v} {f.tr(i['output_unit'])}" + (f" ({i['year']})" if i.get("year") else "")
        if i.get("status") and i["status"] != "operating":
            if f.pl:
                note += f" ({f.tr(i.get('status_label') or i['status']).lower()})"
            else:
                note += f" ({i['status']})"
        src.use(t.get("source"))
        res_items.append((f.tr(i.get("name") or t.get("name")), None, note))

    page_towns = sorted((t for t in towns if t["id"] in tw_slug), key=lambda t: t["name"])
    sections = [{"h2": L("Figures", "Dane"), "rows": rows}]
    if top:
        sections.append({"h2": L("Largest towns", "Największe miasta"), "items": top})
    if heritage:
        sections.append({"h2": L("Heritage, parks and landmarks", "Dziedzictwo, parki i obiekty wyjątkowe"), "items": heritage})
    if res_items:
        sections.append({"h2": L("Energy and resources", "Energia i surowce"), "items": res_items})
    if page_towns:
        sections.append({"h2": L(f"Town pages in {name}", f"Miasta w {pl_voiv(name, 'loc')}"),
                         "items": [(t["name"], f"../{tw_slug[t['id']]}/", "") for t in page_towns]})

    pop = num(s.get("population"))
    if f.pl:
        title = f"{pl_voiv(name).capitalize()} w liczbach: ludność, gospodarka i miasta"
        bits = [f.residents(pop) if pop else None,
                f"PKB {f.big(s['gdp'], 'zł')} w {s.get('gdp_year')} r." if num(s.get("gdp")) else None,
                f"przeciętne wynagrodzenie {f.pln(s['wage'])}" if num(s.get("wage")) else None,
                f"stopa bezrobocia {f.pct(s['unemployment'])}" if num(s.get("unemployment")) is not None else None]
        desc = (f"{pl_voiv(name).capitalize()}: " + ", ".join(b for b in bits if b)
                + ". Największe miasta, dziedzictwo i energetyka, ze źródłami.").replace("r.. ", "r. ")
    else:
        title = f"{name} voivodeship in numbers: population, economy and towns"
        bits = [f"{f.int(pop)} residents" if pop else None,
                f"GDP {f.big(s['gdp'], 'zł')} in {s.get('gdp_year')}" if num(s.get("gdp")) else None,
                f"average wage {f.pln(s['wage'])}" if num(s.get("wage")) else None,
                f"unemployment {f.pct(s['unemployment'])}" if num(s.get("unemployment")) is not None else None]
        desc = f"{name}, Poland: " + ", ".join(b for b in bits if b) + ". Largest towns, heritage and energy, with sources."
    centre = d.state_centre(idx)
    ll = d.lonlat(*centre) if centre else None
    poland = {"@type": "Country", "name": L("Poland", "Polska"), "url": SITE_URL + pre + "atlas/"}
    url = SITE_URL + f"{pre}atlas/{sl}/"
    place = _place_node(url, L(f"{name} Voivodeship", pl_voiv(name).capitalize()), "AdministrativeArea", ll, poland, pop,
                        _iso_day(when_pop), s.get("fips"), [name], f.lang)
    return {
        "slug": sl, "path": f"{pre}atlas/{sl}/", "kind": "voivodeship", "name": name, "title": title, "description": desc,
        "h1": name, "sub": L("Voivodeship of Poland", "Województwo"), "lede": lede, "paras": paras,
        "open": (L("Open on the map", "Pokaż na mapie"), f"{pre}#state={s['abbr']}"),
        "crumbs": [(SITE_NAME, pre), ("Atlas", pre + "atlas/"), (name, f"{pre}atlas/{sl}/")], "sections": sections,
        "sources": src.lines(), "place": place, "og": _og_for(web, sl, f.lang),
        "og_number": (L(f"{f.int(pop)} people", f.residents(pop))) if pop else "", "focus": {"state": s["abbr"]},
    }


def town_page(d: Data, web: Path, c: dict, st_slug: dict, tw_slug: dict, f: Fmt | None = None) -> dict:
    f = f or Fmt("en")
    L = (lambda en, pl: pl) if f.pl else (lambda en, pl: en)
    pre = f.prefix
    src = Sources(d, f)
    sl = tw_slug[c["id"]]
    name = c["name"]
    g = d.gmina.get(c.get("gmina")) or {}
    sv = d.state_by_fips.get(c.get("voivodeship")) or {}
    vname = sv.get("name", "")
    lede, lede_sid = town_headline(d, c, f)
    src.use(lede_sid)
    when_pop = d.when("population")
    pop_date = f.date(when_pop)
    scope = _town_scope(f, c)
    pw = _powiat_words(c, g)
    pw_suffix = "" if c.get("kind") == "city" else f" ({pw})"

    rows = []
    pop = num(c.get("population"))
    if pop:
        rows.append(_row(src, L("Population", "Ludność"), f.int(pop), pop_date, "pl_geo_places"))
    if num(c.get("growth")) is not None:
        ser = c.get("pop_series") or {}
        extra = f" ({L('from', 'z')} {f.int(ser['2015'])})" if num(ser.get("2015")) else ""
        rows.append(_row(src, L("Change since 2015", "Zmiana od 2015 r."), f.pct(c["growth"], 1, True) + extra,
                         L("2015 to 2025", "2015-2025"), "pl_stats_population"))
    if num(g.get("median_age")) is not None:
        rows.append(_row(src, L("Median age", "Mediana wieku") + scope, f.years(g["median_age"]), pop_date, "pl_stats_population"))
    if num(g.get("elderly")) is not None:
        rows.append(_row(src, L("Residents aged 65 or more", "Mieszkańcy w wieku 65 lat i więcej") + scope, f.pct(g["elderly"]),
                         pop_date, "pl_stats_population"))
    if num(c.get("wage")):
        rows.append(_row(src, L("Average gross wage", "Przeciętne miesięczne wynagrodzenie brutto") + pw_suffix,
                         L(f"{f.pln(c['wage'])} a month", f.pln(c["wage"])), d.when_text(f, "wage"), "pl_stats_labour"))
    if num(c.get("unemployment")) is not None:
        rows.append(_row(src, L("Registered unemployment", "Stopa bezrobocia rejestrowanego") + pw_suffix, f.pct(c["unemployment"]),
                         d.when_text(f, "unemployment"), "pl_stats_labour"))
    if num(c.get("pit_per_person")):
        rows.append(_row(src, L("Personal income tax revenue per resident", "Dochody z PIT na mieszkańca") + scope,
                         f.pln(c["pit_per_person"]), d.when_text(f, "pit"), "pl_stats_prosperity"))
    if num(g.get("students")) is not None:
        rows.append(_row(src, L("University students per 1,000 residents", "Studenci na 1000 mieszkańców"), f.int(g["students"]),
                         f.date(_when((d.field.get("students") or {}).get("description"), None)), "pl_stats_population"))
    if c.get("kind") == "city" and num(c.get("employed")):
        rows.append(_row(src, L("People working in the city", "Pracujący w mieście"), f.int(c["employed"]),
                         d.when_text(f, "workers"), "pl_stats_labour"))

    # city type and districts
    dist = (d.districts.get("cities") or {}).get(c["id"]) or None
    dist_paras, dist_items = [], []
    if dist:
        catalog = {x["id"]: x for x in d.districts.get("catalog", [])}
        badge = dist.get("badge")
        sc = dist.get("scope") or name
        where = name if sc == name else f"powiat {sc}" if not str(sc).startswith("powiat") else sc
        if badge:
            if f.pl:
                btext = (I.t(badge["tpl"], "pl", **(badge.get("vars") or {})) if badge.get("tpl")
                         else f.tr(badge.get("text")))
                label = f.tr(badge["label"])
                if len(label) > 1 and label[1].islower():  # "Ośrodek IT" -> "ośrodek IT" after the colon
                    label = label[0].lower() + label[1:]
                if c.get("capital") and badge.get("rule") == "capital":
                    dist_paras.append(btext.rstrip(".") + "." if btext else f"{label.capitalize()}.")
                else:
                    dist_paras.append(f"Typ miasta: {label}." + (f" {btext.rstrip('.')}." if btext else ""))
            else:
                dist_paras.append(f"City type: {badge['label']}." + (f" {badge['text']}." if badge.get("text") else ""))
        elif not dist.get("districts"):
            dist_paras.append(L("No kind of work stands out against the national mix.",
                                "Struktura zatrudnienia nie odbiega wyraźnie od krajowej."))
        for x in dist.get("districts") or []:
            cat = catalog.get(x.get("id")) or {}
            subs = cat.get("sub") or {}
            sub = subs.get(x.get("sub"))
            cat_name = cat.get("name", x.get("id"))
            if x.get("via") == "specialty" and sub:
                label = L(f"{sub} ({cat_name} district)", f"{f.tr(sub)} ({f.tr(cat_name)})")
                lq, emp, more = num(x.get("sub_lq")), num(x.get("sub_emp")), ""
            else:
                sub_list = ", ".join(f.tr(v) for v in subs.values())
                label = L(f"{cat_name} district" + (f" ({', '.join(subs.values())})" if subs else ""),
                          f.tr(cat_name) + (f" ({sub_list})" if subs else ""))
                lq, emp = num(x.get("lq")), num(x.get("emp"))
                show_more = sub and len(subs) > 1 and num(x.get("sub_lq")) and abs(x["sub_lq"] - (lq or 0)) >= 0.1
                more = (L(f"; {sub} alone {x['sub_lq']:.1f} times", f" ({f.tr(sub)}: {f.num(x['sub_lq'], 1)})")
                        if show_more else "")
            note = []
            if emp:
                if f.pl:
                    workers = pl_count(emp, "pracujący", "pracujących", "pracujących")
                    note.append(("co najmniej " if x.get("lower_bound") else "") + workers)
                else:
                    note.append(f"{f.int(emp)} workers" + (" or more" if x.get("lower_bound") else ""))
            if lq:
                note.append(L(f"{lq:.1f} times the national share", f"wskaźnik lokalizacji {f.num(lq)}") + more)
            dist_items.append((label, None, ", ".join(note)))
        if where != name:
            dist_paras.append(L(f"These figures describe the jobs in {where}, by employer seat, on 31 December 2025.",
                                f"Liczba pracujących w {pl_powiat(where, 'loc')} według siedziby pracodawcy "
                                f"(31 grudnia 2025 r.)."))
        else:
            dist_paras.append(L("Jobs by employer seat on 31 December 2025, against the share of each kind of work in Poland.",
                                "Liczba pracujących w mieście według siedziby pracodawcy (31 grudnia 2025 r.)."))
        if f.pl and dist_items:
            dist_paras[-1] += " Wskaźnik lokalizacji porównuje udział branży w zatrudnieniu lokalnym z jej udziałem w zatrudnieniu w kraju."
        src.use("pl_stats_labour")

    # vote
    vote_paras = []
    nv, turnout = num(g.get("president_2025")), num(g.get("turnout_2025"))
    if nv is not None:
        if f.pl:
            unit = "w mieście" if c.get("scope") != "urban-rural gmina" else f"w gminie {name}"
            vote_paras.append(f"W drugiej turze wyborów prezydenckich 1 czerwca 2025 r. Rafał Trzaskowski zdobył "
                              f"{unit} {f.pct(1 - nv)} ważnych głosów, a Karol Nawrocki {f.pct(nv)}."
                              + (f" Frekwencja wyniosła {f.pct(turnout)}." if turnout is not None else ""))
        else:
            unit = name if c.get("scope") != "urban-rural gmina" else f"the gmina of {name}"
            vote_paras.append(f"In the presidential runoff of 1 June 2025, Rafał Trzaskowski won {f.pct(1 - nv)} of valid votes in {unit} "
                              f"and Karol Nawrocki {f.pct(nv)}." + (f" Turnout was {f.pct(turnout)}." if turnout is not None else ""))
        sejm = g.get("sejm_2023")
        if sejm and d.category.get(("sejm", sejm)):
            party = f.tr(d.category[("sejm", sejm)])
            vote_paras.append(L(f"In the Sejm election of 15 October 2023 the largest committee there was {party}.",
                                f"W wyborach do Sejmu 15 października 2023 r. najwięcej głosów otrzymał tu komitet {party}."))
        src.use("pl_soc_elections")

    # air
    air_paras = []
    pm = num(g.get("pm25"))
    if pm is not None:
        station = g.get("air_station")
        if f.pl:
            air_paras.append("W 2025 r. średnie roczne stężenie pyłu PM2,5" + (f" na stacji GIOŚ {station}" if station else "")
                             + f" wyniosło {f.num(pm, 1)} µg/m³.")
        else:
            air_paras.append(f"PM2.5 averaged {pm:.1f} µg/m³ in 2025" + (f" at the GIOŚ station {station}." if station else "."))
        vals = sorted(x for x in (num((d.gmina.get(t.get("gmina")) or {}).get("pm25")) for t in d.view_towns) if x is not None)
        if len(vals) >= 5:
            med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
            air_paras.append(L(f"The median of the {len(vals)} towns of 20,000+ with a station within 25 km was {med:.1f} µg/m³.",
                               f"Wśród {f.int(len(vals))} miast liczących co najmniej 20 tys. mieszkańców ze stacją "
                               f"w promieniu 25 km mediana wyniosła {f.num(med, 1)} µg/m³."))
        src.use("pl_soc_air")
    else:
        air_paras.append(L("No GIOŚ station measured PM2.5 within 25 km of the town centre in 2025.",
                           "W 2025 r. żadna stacja GIOŚ nie mierzyła PM2,5 w promieniu 25 km od centrum miasta."))

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
        near_items.append((item[0], None, item[2] + (L(f", {km:.0f} km away", f", {km:.0f} km od miasta") if km >= 2
                                                     else L(", in the town", ", w mieście"))))
    metro = d.metro_by_id.get(c.get("fua"))
    metro_paras = []
    if metro:
        mp = num(metro.get("population"))
        core = d.city_by_id.get(metro.get("core")) or {}
        ng = len(metro.get("gminas") or [])
        if f.pl:
            if core.get("id") == c["id"]:
                metro_paras.append(f"{name} {pl_verb(name, 'jest', 'są')} głównym miastem miejskiego obszaru funkcjonalnego.")
            else:
                area = f"{name} {pl_verb(name, 'należy', 'należą')} do miejskiego obszaru funkcjonalnego"
                if core.get("name"):
                    area += f", którego głównym miastem {pl_verb(core['name'], 'jest', 'są')} {core['name']}"
                metro_paras.append(area + ".")
            if ng:
                metro_paras[-1] += f" Obszar obejmuje {pl_count(ng, 'gminę', 'gminy', 'gmin')}"
                metro_paras[-1] += (f" i liczy {f.residents(mp)}." if mp else ".")
            elif mp:
                metro_paras[-1] += f" Obszar liczy {f.residents(mp)}."
        else:
            metro_paras.append(f"{name} belongs to the {metro.get('full') or metro.get('name')}" + (f", {f.int(mp)} residents" if mp else "")
                               + (f" in {ng} gminas" if metro.get("gminas") else "") + "."
                               + (f" Its core town is {core['name']}." if core.get("name") and core.get("id") != c["id"] else ""))
        src.use("pl_geo_fua")

    sections = [{"h2": L("Figures", "Dane"), "rows": rows}]
    if dist_paras:
        sections.append({"h2": L("City type and districts", "Typ miasta i dzielnice"), "paras": dist_paras, "items": dist_items})
    if vote_paras:
        sections.append({"h2": L("2025 presidential election", "Wyniki wyborów"), "paras": [p for p in vote_paras if p]})
    sections.append({"h2": L("Air quality", "Jakość powietrza"), "paras": air_paras})
    if metro_paras or near_items:
        sections.append({"h2": L("Metro area and places nearby", "Obszar funkcjonalny i okolica"), "paras": metro_paras, "items": near_items})
    peers = [d.city_by_id[p] for p in c.get("peers") or [] if p in d.city_by_id and p in tw_slug]
    if peers:
        sections.append({"h2": L("Towns of a similar size", "Miasta podobnej wielkości"),
                         "items": [(p["name"], f"../{tw_slug[p['id']]}/", f.residents(p["population"])) for p in peers]})

    caps = [x for x in sv.get("capitals") or [] if x.get("gmina") == c.get("gmina")]
    if f.pl:
        in_voiv = f"w {pl_voiv(vname, 'loc')}" if vname else "w Polsce"
        if c.get("capital"):
            intro = f"{name} to stolica Polski i miasto na prawach powiatu {in_voiv}."
        elif c.get("kind") == "city":
            intro = f"{name} to miasto na prawach powiatu {in_voiv}."
        elif str(g.get("powiat") or "").startswith("powiat"):
            intro = f"{name} to miasto {in_voiv}, w {pl_powiat(g['powiat'], 'loc')}."
        else:
            intro = f"{name} to miasto {in_voiv}."
        if caps:
            role = caps[0].get("role")
            is_ = pl_verb(name, "Jest", "Są")
            intro += {"both": f" {is_} stolicą województwa.", "voivode": f" {is_} siedzibą wojewody.",
                      "sejmik": f" {is_} siedzibą sejmiku województwa."}.get(role, "")
    else:
        kind = "the capital of Poland and a city with powiat rights" if c.get("capital") else "a city with powiat rights" if c.get("kind") == "city" else "a town"
        where = f"in {vname} voivodeship" if c.get("kind") == "city" else f"in {pw}, {vname} voivodeship"
        intro = f"{name} is {kind} {where}."
        if caps:
            role = caps[0].get("role")
            intro += {"both": f" It is the capital of {vname}.", "voivode": f" It is the seat of the voivode of {vname}.",
                      "sejmik": f" It is the seat of the regional assembly (sejmik) of {vname}."}.get(role, "")
    paras = [intro]

    if f.pl:
        title = f"{name}: ludność, wynagrodzenia, wybory i jakość powietrza"
        bits = [f"{f.residents(pop)} ({pop_date})" if pop else None,
                f"{f.pct(c['growth'], 1, True)} w latach 2015-2025" if num(c.get("growth")) is not None else None,
                f"przeciętne wynagrodzenie {f.pln(c['wage'])}" if num(c.get("wage")) else None,
                f"stopa bezrobocia {f.pct(c['unemployment'])}" if num(c.get("unemployment")) is not None else None,
                f"PM2,5 {f.num(pm, 1)} µg/m³" if pm is not None else None]
        desc = f"{name}, {pl_voiv(vname)}: " + ", ".join(b for b in bits if b) + "."
    else:
        title = f"{name}, Poland: population, wages, vote and air quality"
        bits = [f"{f.int(pop)} residents ({pop_date})" if pop else None,
                f"{f.pct(c['growth'], 1, True)} from 2015 to 2025" if num(c.get("growth")) is not None else None,
                f"average wage {f.pln(c['wage'])}" if num(c.get("wage")) else None,
                f"unemployment {f.pct(c['unemployment'])}" if num(c.get("unemployment")) is not None else None,
                f"PM2.5 {pm:.1f} µg/m³" if pm is not None else None]
        desc = f"{name}, {vname}: " + ", ".join(b for b in bits if b) + "."
    url = SITE_URL + f"{pre}atlas/{sl}/"
    sv_slug = st_slug.get(sv.get("abbr"), "")
    parent = {"@type": "AdministrativeArea", "@id": SITE_URL + f"{pre}atlas/{sv_slug}/#place",
              "name": L(f"{vname} Voivodeship", pl_voiv(vname).capitalize()), "url": SITE_URL + f"{pre}atlas/{sv_slug}/"}
    place = _place_node(url, name, "City", d.lonlat(c.get("x"), c.get("y")), parent, pop, _iso_day(when_pop), c.get("id"),
                        lang=f.lang)
    crumbs = [(SITE_NAME, pre), ("Atlas", pre + "atlas/")]
    if sv:
        crumbs.append((vname, f"{pre}atlas/{st_slug[sv['abbr']]}/"))
    crumbs.append((name, f"{pre}atlas/{sl}/"))
    return {
        "slug": sl, "path": f"{pre}atlas/{sl}/", "kind": "town", "name": name, "title": title, "description": desc, "h1": name,
        "sub": c.get("full") or name, "lede": lede, "paras": paras,
        "open": (L("Open on the map", "Pokaż na mapie"), f"{pre}#city={c['id']}&view=city"),
        "crumbs": crumbs, "sections": sections, "sources": src.lines(), "place": place, "og": _og_for(web, sl, f.lang),
        "og_number": L(f"{f.int(pop)} people", f.residents(pop)) if pop else "", "focus": {"city": c["id"]},
    }


# --- rendering -------------------------------------------------------------------------------------------------------

EMBLEM = ('<svg class="emblem" aria-hidden="true" viewBox="0 0 64 64" width="24" height="24"><path d="M8 6h48v24c0 15-10 24-24 30C18 54 8 45 8 30z" fill="#120d06"/>'
          '<path d="M11 9h42v21c0 13-9 21-21 26.5C20 51 11 43 11 30z" fill="#c9a45c"/><path d="M14.5 12.5h35V30c0 11-7.5 18-17.5 22.8C22 48 14.5 41 14.5 30z" fill="#B3262E"/>'
          '<path d="M14.5 12.5h35V28c-6 3-11.5-3-17.5 0s-11.5 3-17.5 0z" fill="#f4ecd8"/><path d="M14.5 28c6 3 11.5 3 17.5 0s11.5-3 17.5 0" fill="none" stroke="#e2bf6e" stroke-width="2.6"/></svg>')
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cpath d='M8 6h48v24c0 15-10 24-24 30C18 54 8 45 8 30z' fill='%23120d06'/%3E"
           "%3Cpath d='M11 9h42v21c0 13-9 21-21 26.5C20 51 11 43 11 30z' fill='%23c9a45c'/%3E%3Cpath d='M14.5 12.5h35V30c0 11-7.5 18-17.5 22.8C22 48 14.5 41 14.5 30z' fill='%23B3262E'/%3E"
           "%3Cpath d='M14.5 12.5h35V28c-6 3-11.5-3-17.5 0s-11.5 3-17.5 0z' fill='%23f4ecd8'/%3E%3Cpath d='M14.5 28c6 3 11.5 3 17.5 0s11.5-3 17.5 0' fill='none' stroke='%23c9a45c' stroke-width='3'/%3E%3C/svg%3E")

# Atlas chrome per language (headings and sentences live in the page builders above).
CHROME = {
    "en": {"og_alt": "{h1} on the hex map of Poland", "crumbs": "Breadcrumb", "sources": "Sources", "lang": "Language",
           "updated": "Last updated {date}.", "part": 'Part of <a href="{home}">Polska</a>, a map of Poland built from public data.',
           "md": "Markdown version", "code": "Code: <a href=\"{repo}\" rel=\"noopener\">MIT licence</a>; data: the publishers above, under their own terms.",
           "md_cols": "| Figure | Value | Date | Publisher |", "md_page": "Source page", "md_updated": "Last updated",
           "md_other": "Polish version", "page": "Page", "residents": "residents", "see": "see Sources"},
    "pl": {"og_alt": "{h1} na mapie Polski podzielonej na heksy", "crumbs": "Ścieżka nawigacji", "sources": "Źródła", "lang": "Język",
           "updated": "Ostatnia aktualizacja: {date}.", "part": '<a href="{home}">Mapa Polski</a> na podstawie danych publicznych.',
           "md": "Wersja Markdown", "code": 'Kod udostępniono na <a href="{repo}" rel="noopener">licencji MIT</a>. Warunki wykorzystania danych określają ich wydawcy.',
           "md_cols": "| Wskaźnik | Wartość | Data | Źródło |", "md_page": "Adres strony", "md_updated": "Ostatnia aktualizacja",
           "md_other": "Wersja angielska", "page": "Strona", "residents": "mieszkańców", "see": "zob. Źródła"},
}


def _rel_root(page: dict) -> str:
    return "../" * page["path"].count("/")


def _link(page: dict, target_path: str) -> str:
    """Relative link from the page to a site path ("" = the app, "atlas/krakow/", "pl/atlas/krakow/")."""
    return _rel_root(page) + target_path


def _alternates(page: dict) -> list[tuple[str, str]]:
    """(hreflang, absolute URL) of the page in each language, plus x-default (English)."""
    alts = page.get("alts") or {page.get("lang", "en"): page["path"]}
    out = [(lang, SITE_URL + alts[lang]) for lang in LANGS if lang in alts]
    if "en" in alts:
        out.append(("x-default", SITE_URL + alts["en"]))
    return out


def render_html(page: dict, date: str) -> str:
    lang = page.get("lang", "en")
    ch = CHROME[lang]
    root = _rel_root(page)
    home = root + PREFIX[lang]
    url = SITE_URL + page["path"]
    og = SITE_URL + page["og"]
    ld = json.dumps(_jsonld(page, date), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    h = []
    a = h.append
    a("<!doctype html>")
    a(f'<html lang="{lang}">')
    a("<head>")
    a('<meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width, initial-scale=1">')
    a(f'<meta http-equiv="Content-Security-Policy" content="{esc(ATLAS_CSP)}">')
    a(f"<title>{esc(page['title'])}</title>")
    a(f'<meta name="description" content="{esc(page["description"])}">')
    a(f'<link rel="canonical" href="{esc(url)}">')
    for hl, href in _alternates(page):
        a(f'<link rel="alternate" hreflang="{hl}" href="{esc(href)}">')
    a(f'<link rel="alternate" type="text/markdown" href="index.md">')
    a(f'<link rel="icon" type="image/svg+xml" href="{FAVICON}">')
    a('<meta name="theme-color" content="#0f2233">')
    a(f'<meta name="author" content="{esc(AUTHOR["name"])}">')
    a('<meta property="og:type" content="article">')
    a(f'<meta property="og:site_name" content="{SITE_NAME}">')
    a(f'<meta property="og:title" content="{esc(page["title"])}">')
    a(f'<meta property="og:description" content="{esc(page["description"])}">')
    a(f'<meta property="og:url" content="{esc(url)}">')
    a(f'<meta property="og:locale" content="{OG_LOCALE[lang]}">')
    for other in LANGS:
        if other != lang and other in (page.get("alts") or {}):
            a(f'<meta property="og:locale:alternate" content="{OG_LOCALE[other]}">')
    a(f'<meta property="og:image" content="{esc(og)}">')
    a('<meta property="og:image:width" content="1200">')
    a('<meta property="og:image:height" content="630">')
    a(f'<meta property="og:image:alt" content="{esc(ch["og_alt"].format(h1=page["h1"]))}">')
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
    alts = page.get("alts") or {}
    switch = "".join(
        f'<a href="{esc(_link(page, alts[l]))}" hreflang="{l}" lang="{l}"' + (' aria-current="page"' if l == lang else "")
        + f">{l.upper()}</a>" for l in LANGS if l in alts)
    a(f'<header class="bar"><a class="brand" href="{home}">{EMBLEM}<span>Polska</span></a>'
      f'<a class="bar-open" href="{root}{esc(page["open"][1])}">{esc(page["open"][0])}</a>'
      + (f'<nav class="lang" aria-label="{ch["lang"]}">{switch}</nav>' if len(alts) > 1 else "") + "</header>")
    a('<main>')
    crumbs = page["crumbs"]
    cur = ' aria-current="page"'
    a(f'<nav class="crumbs" aria-label="{ch["crumbs"]}"><ol>' + "".join(
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
    a(f"<h2>{ch['sources']}</h2>")
    a("<ul>" + "".join(f'<li><a href="{esc(u)}" rel="noopener">{esc(t)}</a></li>' if u else f"<li>{esc(t)}</li>" for t, u in page["sources"]) + "</ul>")
    a("</section>")
    a("</main>")
    if lang == "en":
        updated = f"Last updated {I.fmt_date(date, 'en')}."
    else:
        updated = ch["updated"].format(date=I.fmt_date(date, lang))
    a(f'<footer><p>{updated} {ch["part"].format(home=home)} '
      f'<a href="index.md">{ch["md"]}</a>. <a href="{home}llms.txt">llms.txt</a>. '
      f'{ch["code"].format(repo=REPO_URL)}</p></footer>')
    a("</body>")
    a("</html>")
    return "\n".join(h) + "\n"


def render_md(page: dict, date: str, full: bool = True) -> str:
    """Markdown copy of a page. full=False gives the compact form used in llms-full.txt."""
    lang = page.get("lang", "en")
    ch = CHROME[lang]
    url = SITE_URL + page["path"]
    pub = page.get("_pub") or (lambda sid: sid or ch["see"])
    out = []
    a = out.append
    hd = "#" if full else "##"
    a(f"{hd} {page['h1']}")
    a("")
    if full:
        a(f"{ch['md_page']}: {url}")
        for other, href in _alternates(page):
            if other not in (lang, "x-default"):
                a(f"{CHROME[lang]['md_other']}: {href}")
        a(f"{ch['md_updated']}: {date}")
        a("")
    elif page.get("sub"):
        a(f"{page['sub']}. {ch['page']}: {url}")
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
    atlas_url = SITE_URL + PREFIX[lang] + "atlas/"
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
                a(ch["md_cols"])
                a("|---|---|---|---|")
                for label, value, when, sid in sec["rows"]:
                    a(f"| {md_esc(label)} | {md_esc(value)} | {md_esc(when)} | {md_esc(pub(sid))} |")
            else:
                for label, value, when, sid in sec["rows"]:
                    a(f"- {label}: {value} ({when}; {pub(sid)})" if when else f"- {label}: {value} ({pub(sid)})")
            a("")
        if sec.get("table"):
            t = sec["table"]
            a("| " + " | ".join(t["head"]) + " |")
            a("|" + "---|" * len(t["head"]))
            for row in t["rows"]:
                (n, href), rest = row[0], row[1:]
                a(f"| [{n}]({atlas_url}{href}) | " + " | ".join(md_esc(x) for x in rest) + " |")
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
                a(f"- [{t}]({SITE_URL}{_abs_from(page, href)})" + (f": {n} {ch['residents']}" if n else ""))
            a("")
    if full:
        a(f"{h2} {ch['sources']}")
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
    "history.json": ("The 1914 partition borders and the borders of interwar Poland, simplified from CShapes 2.0.",
                     ["layers (date, label, lines, labels)", "rules", "licence"], ["pl_hist_borders"]),
    "commuting.json": ("Commuting flows into the 12 most populous cities, from the NSP 2021 gmina matrix.",
                       ["cities (name, commuters_in, commuters_out, arcs)", "rule"], ["pl_flows_commuting"]),
    "timeline.json": ("Annual population density and change for Polish land hexes, 2015 to 2026.",
                      ["dates", "cells", "density", "growth", "domains", "notes"], ["pl_hist_population"]),
    "economy.json": ("Made in Poland and Tech and games: product and tech sites with one fact each, and the game studios of each town.",
                     ["items (layer, kind, name, place, fact, year, ref, x, y, cell, county, state)", "kinds", "rules"],
                     ["pl_econ_champions", "pl_tech_sites"]),
    "permits_monthly.json": ("Building permits for new factories and warehouses per gmina and month, from the GUNB permit register.",
                             ["months", "gminas (code, name, x, y)", "counts (month, gmina, permits)", "national", "rules"],
                             ["pl_econ_permits"]),
    "trains.json": ("Every passenger train of one ordinary weekday: operator, number, name, stops with times and the line it runs on.",
                    ["trips (op, cat, no, name, p, t)", "patterns (shape, stops, d)", "shapes", "stations (name, x, y)",
                     "operators", "rules", "attribution"], ["pl_rail_gtfs"]),
    "flights.json": ("Air routes from the main Polish airports with passengers per month over the newest 12 months.",
                     ["routes (from, to, value, total, end, bearing, km)", "airports (icao, name, label, city, country, x, y)",
                      "months", "rules"], ["pl_air_routes"]),
    "power.json": ("One day of the power system every 15 minutes: generation by fuel, wind, solar, demand and the flows "
                   "on each border, with the border lines, the largest wind and solar sites and capacity by powiat.",
                   ["t", "mix (by fuel group)", "wind", "solar", "demand", "neighbours (code, net, lines)",
                    "wind_farms", "solar_farms", "res_powiat", "live", "rules", "attribution"],
                   ["pl_power_pse", "pl_energy_plants", "pl_energy_res"]),
    "migration.json": ("Moves of permanent residence between the 16 voivodeships, origin by destination, every year.",
                       ["years", "regions (code, name, capital, x, y, in, out, net)", "flows (from, to, values, path)",
                        "rules"], ["pl_migration_od"]),
    "money.json": ("State money for each gmina, powiat and voivodeship in one year: PIT and CIT shares, general subsidy "
                   "and the wealth correction.",
                   ["units (code, level, kind, name, x, y, pit, cit, subsidy, total, correction, needs)", "fields",
                    "rules"], ["pl_local_finance_flows"]),
    "timelapse.json": ("Tourist nights per voivodeship for each of the newest 36 months, and the presidential runoffs "
                       "and population years that play over time.",
                       ["states", "tourism (months, nights, per_resident, national, population)",
                        "elections (frames: year, lens, candidate, share, turnout)", "population", "rules"],
                       ["pl_tourism_monthly", "pl_stats_population", "pl_soc_elections", "pl_hist_population"]),
    "smog.json": ("Hourly PM2.5 at every automatic GIOŚ station in the week with the worst smog of winter 2025/26, "
                  "and the same hours on hexes within 40 km of a station.",
                  ["start", "hours", "stations (id, name, city, x, y, pm25)", "cells", "values", "national_hourly",
                   "peak", "rules"], ["pl_air_hourly"]),
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
    if name == "history.json":
        return len(doc.get("layers") or []) or None
    if name == "timeline.json":
        return len(doc.get("cells") or []) or None
    if name == "trains.json":
        return len(doc.get("trips") or []) or None
    if name == "permits_monthly.json":
        return len(doc.get("gminas") or []) or None
    if name == "power.json":
        return len(doc.get("t") or []) or None
    if name == "migration.json":
        return len(doc.get("flows") or []) or None
    if name == "money.json":
        return len(doc.get("units") or []) or None
    if name == "timelapse.json":
        return len((doc.get("tourism") or {}).get("months") or []) or None
    if name == "smog.json":
        return len(doc.get("stations") or []) or None
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
        licences = []
        for sid in sids:
            source = d.source_by_id.get(sid) or {}
            pub = source.get("publisher")
            if pub and pub not in pubs:
                pubs.append(pub)
            terms = source.get("license")
            if terms:
                licences.append({"source": sid, "terms": terms})
        files.append({"path": f"data/{name}", "url": f"{SITE_URL}data/{name}", "bytes": p.stat().st_size,
                      "description": desc, "fields": fields or [], "rows": _rows(name, doc), "vintage": vint,
                      "sources": sids, "publishers": pubs, "licenses": licences})
    return {
        "version": 1, "name": "Polska data catalogue", "site": SITE_URL, "generated": date,
        "description": "Public data behind the Polska map of Poland. Each file is JSON; shapes are documented in docs/DATA_CONTRACTS.md of the source repository.",
        "contracts": f"{REPO_URL}/blob/main/docs/DATA_CONTRACTS.md",
        "license": {"code": "MIT (see LICENSE in the source repository)",
                    "data": "Each figure belongs to its publisher and is reused under the publisher's terms (see sources.json): "
                            "Polish public statistics with attribution (GUS: CC BY 4.0), Eurostat and Copernicus reuse policies, "
                            "ESA WorldCover and HydroSHEDS CC BY 4.0, CShapes 2.0 CC BY-NC-SA 4.0, and OpenStreetMap "
                            "data ODbL (road, rail and position data stay ODbL)."},
        "creator": AUTHOR, "text_pages": f"{SITE_URL}atlas/", "llms": f"{SITE_URL}llms.txt", "files": files,
    }


# Polish descriptions of the data files (pl/llms.txt and the JSON-LD of pl/index.html; data/index.json stays English).
FILE_INFO_PL = {
    "index.json": "Katalog plików danych: pola, liczba wierszy, stan danych, wydawcy.",
    "world.json": "Siatka heksagonalna Polski: województwo i gmina każdego heksu, wysokość, wody, rzeźba terenu, pokrycie terenu, rzeki, jeziora.",
    "cities.json": "Wszystkie miasta (stan na 1 stycznia 2026 r.): ludność, zmiana liczby ludności, wynagrodzenie, bezrobocie, udział w PKB, zasoby i pozycje w rankingach.",
    "metros.json": "Miejskie obszary funkcjonalne Polski według Eurostatu: gminy wchodzące w ich skład i dane gospodarcze.",
    "states.json": "16 województw: ludność, zmiana liczby ludności, PKB, wynagrodzenie, bezrobocie, pracujący według sekcji PKD, stolice, pokrycie terenu.",
    "nation.json": "Dane krajowe Polski i definicje zasobów miast.",
    "counties.json": "Każda gmina (TERYT7) z około 30 wskaźnikami: gęstość zaludnienia, wiek, migracje, PIT, wynagrodzenie, bezrobocie, wykształcenie, wyznanie, wybory, powietrze, powódź, pokrycie terenu.",
    "powiaty.json": "Każdy powiat (TERYT4) z tymi samymi wskaźnikami, zsumowanymi lub ważonymi z danych gmin.",
    "lenses.json": "Warstwy mapy: jedna wartość na heks dla każdego wskaźnika, z zakresami legendy i uwagami.",
    "resources.json": "Elektrownie, kopalnie, złoża ropy i gazu, morskie farmy wiatrowe oraz odnawialne źródła energii według powiatów.",
    "infrastructure.json": "Autostrady, drogi ekspresowe i główne linie kolejowe na połączeniach heksów oraz porty morskie i lotniska.",
    "military.json": "Garnizony, bazy, obiekty sojusznicze i poligony, z liczebnością i budżetem.",
    "wonders.json": "Obiekty dziedzictwa i obiekty wyjątkowe wybrane według opublikowanych reguł: obiekty UNESCO, parki narodowe, uczelnie badawcze, obiekty rekordowe.",
    "trade.json": "Drogowe i kolejowe przewozy ładunków między regionami.",
    "citizens.json": "Struktura mieszkańców każdego miasta liczącego co najmniej 20 tys. mieszkańców: pracujący według sektorów, wiek, płeć, wykształcenie, pochodzenie.",
    "districts.json": "Dzielnice i typy miast liczących co najmniej 20 tys. mieszkańców, wyznaczone ze wskaźników lokalizacji pracujących według sekcji PKD.",
    "disasters.json": "Gminy objęte stanem klęski żywiołowej po powodzi we wrześniu 2024 r.",
    "history.json": "Granice zaborów w 1914 r. i granice II Rzeczypospolitej, uproszczone na podstawie CShapes 2.0.",
    "commuting.json": "Dojazdy do pracy do 12 największych miast według macierzy gmin z NSP 2021.",
    "timeline.json": "Roczna gęstość zaludnienia i zmiana liczby ludności na polskich heksach w latach 2015-2026.",
    "economy.json": "Z Polski na świat oraz Technologie i gry: zakłady, firmy i ośrodki z jednym faktem każdy oraz studia gier w każdym mieście.",
    "permits_monthly.json": "Pozwolenia na budowę nowych hal i magazynów według gmin i miesięcy, z rejestru GUNB.",
    "trains.json": "Wszystkie pociągi pasażerskie jednego zwykłego dnia roboczego: przewoźnik, numer, nazwa, stacje z godzinami i linia, po której jadą.",
    "flights.json": "Trasy lotnicze z głównych polskich lotnisk z liczbą pasażerów w każdym z ostatnich 12 miesięcy.",
    "timelapse.json": "Noclegi turystów według województw w każdym z 36 ostatnich miesięcy oraz drugie tury wyborów prezydenckich i liczba ludności w kolejnych latach, do odtwarzania w czasie.",
    "smog.json": "Godzinowe stężenia PM2,5 na wszystkich automatycznych stacjach GIOŚ w tygodniu z najgorszym smogiem zimy 2025/26 oraz te same godziny na heksach w promieniu 40 km od stacji.",
    "power.json": "Jedna doba systemu elektroenergetycznego co 15 minut: produkcja według paliw, wiatr, słońce, zapotrzebowanie i przepływy na każdej granicy, z liniami transgranicznymi, największymi farmami wiatrowymi i fotowoltaicznymi oraz mocą według powiatów.",
    "migration.json": "Zmiany miejsca pobytu stałego między 16 województwami (skąd i dokąd) w każdym roku.",
    "money.json": "Pieniądze od państwa dla każdej gminy, powiatu i województwa w jednym roku: udziały w PIT i CIT, subwencja ogólna i korekta z tytułu zamożności.",
    "sources.json": "Bibliografia: każde źródło z wydawcą, licencją, stanem danych i dokładnie wykorzystanymi plikami.",
}


def _file_desc(name: str, lang: str, en: str) -> str:
    return FILE_INFO_PL.get(name, en) if lang == "pl" else en


def llms_txt(d: Data, pages: list[dict], catalog: dict, lang: str = "en") -> str:
    f = Fmt(lang)
    n = d.nation
    pre = SITE_URL + PREFIX[lang]
    pop = num(n.get("population"))
    if f.pl:
        out = [f"# {I.t(APP_TITLE, 'pl')}", ""]
        out.append("> Na mapie Polski w stylu Civ można porównać miasta i ich zasoby, obejrzeć rzeźbę terenu "
                   "i sprawdzić rozmieszczenie surowców. Atlas zawiera dane dla Polski, 16 województw i "
                   f"{pl_count(len(d.view_towns), 'miasta', 'miast', 'miast')} liczących co najmniej 20 tys. mieszkańców. "
                   "Przy danych podano datę i źródło, m.in. GUS, Eurostat, PKW, GIOŚ i UNESCO.")
        out.append("")
        if pop:
            out.append(f"{f.when_pl(d.when('population'))} Polska liczyła {f.residents(pop)}. "
                       f"Wersja angielska: {SITE_URL}llms.txt")
            out[-1] = out[-1][:1].upper() + out[-1][1:]
            out.append("")
        out += ["## Aplikacja", "", f"- [Polska, mapa]({pre}): interaktywna mapa heksagonalna z warstwami, widokami miast i doradcami (wymaga JavaScriptu)", ""]
        out += ["## Atlas", "", f"- [Polska w liczbach]({pre}atlas/): dane krajowe, 16 województw i linki do wszystkich stron",
                f"- [Pełny tekst]({pre}llms-full.txt): wszystkie strony atlasu w jednym pliku Markdown"]
    else:
        out = [f"# {APP_TITLE}", ""]
        out.append("> Polska draws real Poland, the Civ way: terrain, towns, yields, lenses and resources, every figure from a "
                   "public source (GUS, Eurostat, PKW, GIOŚ, UNESCO and others). The atlas has a text page with dated, sourced figures "
                   f"for Poland, each of the 16 voivodeships and each of the {len(d.view_towns)} towns of 20,000 or more people.")
        out.append("")
        if pop:
            out.append(f"Poland had {f.int(pop)} residents on {f.date(d.when('population'))}. Pages are in English; place names keep "
                       f"their Polish spelling. Polish version: {SITE_URL}pl/llms.txt")
            out.append("")
        out += ["## App", "", f"- [Polska, the map]({SITE_URL}): interactive hex map with lenses, town views and advisors (needs JavaScript)", ""]
        out += ["## Atlas", "", f"- [Poland in numbers]({SITE_URL}atlas/): national figures, the 16 voivodeships and links to every page",
                f"- [Full text]({SITE_URL}llms-full.txt): every atlas page as compact markdown in one file"]
    for p in pages:
        if p["kind"] == "voivodeship":
            out.append(f"- [{p['h1']}]({SITE_URL}{p['path']}index.md): {p['lede']}")
    out.append("")
    if f.pl:
        out += ["## Dane", "", f"- [Katalog danych]({SITE_URL}data/index.json): pola, liczba wierszy, okres i wydawcy danych "
                               "dla każdego pliku (po angielsku)"]
    else:
        out += ["## Data", "", f"- [Data catalogue]({SITE_URL}data/index.json): every data file with its fields, rows, vintage and publishers"]
    for fi in catalog["files"]:
        out.append(f"- [{fi['path']}]({fi['url']}): {_file_desc(fi['path'].split('/')[-1], lang, fi['description'])}")
    out.append("")
    out += ["## Źródła" if f.pl else "## Sources", ""]
    seen = set()
    for s in d.sources:
        pub = s.get("publisher")
        if not pub or pub in seen:
            continue
        seen.add(pub)
        out.append(f"- [{f.tr(pub)}]({s.get('homepage') or SITE_URL + 'data/sources.json'}): {f.tr(s.get('title', ''))}")
    out.append("")
    if f.pl:
        out += ["## Jak cytować", "",
                f"- [Cytowanie serwisu]({pre}atlas/): \"{I.t(APP_TITLE, 'pl')}\", Jarek Tkaczyk, {pre}, z adresem strony i datą odczytu",
                f"- [Cytowanie danych]({SITE_URL}data/sources.json): podaj wydawcę i rok danych. Spis źródeł znajduje się na końcu każdej strony atlasu.",
                f"- [Kod źródłowy]({REPO_URL}): kod jest dostępny na licencji MIT. Warunki wykorzystania danych określają ich wydawcy.", ""]
        out += ["## Miasta (opcjonalnie)", ""]
    else:
        out += ["## How to cite", "",
                f"- [Cite this site]({SITE_URL}atlas/): \"Polska: Poland, the Civ way\", Jarek Tkaczyk, {SITE_URL}, with the page URL and the date you read it",
                f"- [Cite the figures]({SITE_URL}data/sources.json): name the original publisher and year given next to each figure; the atlas pages list them under Sources",
                f"- [Source code]({REPO_URL}): MIT licence; the data stay under their publishers' terms", ""]
        out += ["## Optional", ""]
    for p in pages:
        if p["kind"] == "town":
            out.append(f"- [{p['h1']}]({SITE_URL}{p['path']}index.md): {p['sub']}")
    return "\n".join(out).rstrip() + "\n"


def llms_full(pages: list[dict], date: str, lang: str = "en") -> str:
    if lang == "pl":
        out = [f"# {I.t(APP_TITLE, 'pl')}: pełny tekst", "",
               f"Tekst atlasu {SITE_URL}pl/atlas/ w formacie Markdown. Stan na {date}. Przy danych podano daty i wydawców.", ""]
    else:
        out = [f"# {APP_TITLE}: full text", "",
               f"Every atlas page of {SITE_URL} as compact markdown. Generated {date}. Each figure gives its date and publisher.", ""]
    for p in pages:
        out.append(render_md(p, date, full=False))
    return "\n".join(out).rstrip() + "\n"


def app_jsonld(d: Data, catalog: dict, date: str, lang: str = "en", image: str = MAIN_OG) -> dict:
    """WebSite, WebApplication and Dataset nodes for web/index.html (English) or web/pl/index.html (Polish)."""
    pl = lang == "pl"
    home = SITE_URL + PREFIX[lang]
    n = d.nation_doc
    years = [y for y in (n.get("years") or {}).values() if isinstance(y, int)]
    gy = (d.nation.get("growth_years") or [None])[0]
    span = f"{min([gy] + years if gy else years)}/{max(years)}" if years else None
    site = {"@type": "WebSite", "@id": home + "#website", "name": SITE_NAME, "alternateName": "pol-civ", "url": home,
            "inLanguage": lang, "author": AUTHOR}
    appn = {"@type": "WebApplication", "@id": home + "#app", "name": SITE_NAME, "alternateName": "pol-civ", "url": home,
            "description": ("Prawdziwa Polska w stylu Civ: heksagonalny teren, miasta i ich zasoby, "
                            "warstwy dla każdej gminy oraz doradcy, a każda liczba z publicznego źródła." if pl else
                            "Real Poland, the Civ way: hex terrain, towns with yields, lenses for every gmina "
                            "and advisors, every figure from a public source."),
            "applicationCategory": "EducationalApplication",
            "operatingSystem": "Dowolny (przeglądarka internetowa)" if pl else "Any (web browser)",
            "browserRequirements": "Wymaga JavaScriptu i elementu canvas HTML" if pl else "Requires JavaScript and HTML canvas",
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "PLN"}, "inLanguage": lang, "image": SITE_URL + image,
            "author": AUTHOR, "dateModified": date, "isBasedOn": "https://karpathy.ai/usaciv/",
            "license": f"{REPO_URL}/blob/main/LICENSE"}
    dist = [{"@type": "DataDownload", "name": fi["path"].split("/")[-1], "contentUrl": fi["url"], "encodingFormat": "application/json",
             "description": _file_desc(fi["path"].split("/")[-1], lang, fi["description"])} for fi in catalog["files"]]
    dist.insert(0, {"@type": "DataDownload", "name": "index.json", "contentUrl": SITE_URL + "data/index.json",
                    "encodingFormat": "application/json",
                    "description": _file_desc("index.json", lang, "Catalogue of the data files: fields, rows, vintage, publishers.")})
    pubs = []
    for s in d.sources:
        p = s.get("publisher")
        if p and I.t(p, lang) not in pubs:
            pubs.append(I.t(p, lang))
    data = {"@type": "Dataset", "@id": home + "#dataset",
            "name": ("Polska: dane publiczne o Polsce według gmin, powiatów, województw i miast" if pl else
                     "Polska: public data on Poland by gmina, powiat, voivodeship and town"),
            "description": ("Ludność, zmiana liczby ludności, wiek, wynagrodzenia, bezrobocie, dochody z PIT, PKB, wykształcenie, "
                            "zdrowie, wyznanie, wybory, jakość powietrza, pokrycie terenu, energetyka, transport, dziedzictwo "
                            "i obronność: dane dla 16 województw, 380 powiatów, 2479 gmin i 1026 miast Polski, zebrane od "
                            "oficjalnych wydawców i przedstawione na mapie heksagonalnej." if pl else
                            "Population, growth, age, wages, unemployment, income tax revenue, GDP, education, health, faith, elections, "
                            "air quality, land cover, energy, transport, heritage and defence figures for Poland's 16 voivodeships, "
                            "380 powiats, 2,479 gminas and 1,026 towns, gathered from official publishers and drawn on a hex map."),
            "url": home + "atlas/", "sameAs": SITE_URL + "data/index.json", "isAccessibleForFree": True, "inLanguage": lang,
            "keywords": (["Polska", "GUS", "województwo", "gmina", "powiat", "ludność", "statystyka regionalna"] if pl else
                         ["Poland", "Polska", "GUS", "voivodeship", "gmina", "powiat", "population", "regional statistics"]),
            "creator": AUTHOR, "dateModified": date,
            "license": {"@type": "CreativeWork",
                        "name": ("Kod na licencji MIT; każda liczba na warunkach jej wydawcy (zob. sources.json)" if pl else
                                 "Code under the MIT licence; each figure under its publisher's own terms (see sources.json)"),
                        "url": SITE_URL + "data/sources.json"},
            "spatialCoverage": {"@type": "Place", "name": "Polska" if pl else "Poland"},
            "isBasedOn": [s.get("homepage") for s in d.sources if s.get("homepage")][:40],
            "citation": pubs,
            "distribution": dist}
    if span:
        data["temporalCoverage"] = span
    return {"@context": "https://schema.org", "@graph": [site, appn, data]}


_JSONLD_SLOT = re.compile(r"(<!-- seo:jsonld[^>]*-->)(.*?)(<!-- /seo:jsonld -->)", re.S)


def _put_jsonld(text: str, ld: dict) -> str | None:
    m = _JSONLD_SLOT.search(text)
    if not m:
        return None
    body = json.dumps(ld, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return text[:m.start(2)] + f'<script type="application/ld+json">{body}</script>' + text[m.end(2):]


def fill_index_html(web: Path, ld: dict) -> bool:
    """Put the JSON-LD between the seo markers of web/index.html and make sure its head names both languages
    (canonical, hreflang alternates, og:locale:alternate). False if the markers are missing."""
    p = web / "index.html"
    if not p.exists():
        return False
    text = p.read_text()
    new = _put_jsonld(text, ld)
    if new is None:
        return False
    new = _app_head(new, "en")
    if new != text:
        _write(p, new)
    return True


def _head_insert(text: str, tags: str) -> str:
    """Insert tags into the head: before the JSON-LD slot when there is one, else before </head>."""
    i = text.find("<!-- seo:jsonld")
    if i < 0:
        i = text.find("</head>")
    if i < 0:
        return text
    return text[:i] + tags + "\n  " + text[i:]


def _set_meta(text: str, prop: str, value: str) -> str:
    return re.sub(r'(<meta\s+(?:property|name)="%s"\s+content=")[^"]*(")' % re.escape(prop),
                  lambda m: m.group(1) + esc(value) + m.group(2), text)


def _app_head(text: str, lang: str, og_image: str | None = None) -> str:
    """The language parts of an app page head: canonical, hreflang alternates, og:url, og:locale (+ alternate),
    og:image. Missing canonical and hreflang links are inserted."""
    home = SITE_URL + PREFIX[lang]
    if re.search(r'<link rel="canonical"', text):
        text = re.sub(r'(<link rel="canonical" href=")[^"]*(")', lambda m: m.group(1) + home + m.group(2), text)
    else:
        text = _head_insert(text, f'<link rel="canonical" href="{home}">')
    if 'hreflang="x-default"' not in text:
        links = "\n  ".join(f'<link rel="alternate" hreflang="{hl}" href="{href}">'
                            for hl, href in (("en", SITE_URL), ("pl", SITE_URL + "pl/"), ("x-default", SITE_URL)))
        text = re.sub(r'(<link rel="canonical" href="[^"]*">)', lambda m: m.group(1) + "\n  " + links, text, count=1)
    text = _set_meta(text, "og:url", home)
    other = "pl" if lang == "en" else "en"
    if 'property="og:locale"' in text:
        text = _set_meta(text, "og:locale", OG_LOCALE[lang])
        if 'property="og:locale:alternate"' in text:
            text = _set_meta(text, "og:locale:alternate", OG_LOCALE[other])
        else:
            text = re.sub(r'(<meta property="og:locale" content="[^"]*">)',
                          lambda m: m.group(1) + f'\n  <meta property="og:locale:alternate" content="{OG_LOCALE[other]}">', text, count=1)
    if og_image:
        text = _set_meta(text, "og:image", SITE_URL + og_image)
        text = _set_meta(text, "twitter:image", SITE_URL + og_image)
    return text


_PROTECTED = re.compile(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", re.S | re.I)
_PIECE = re.compile(r"(<[^>]*>)|([^<]+)")
_READABLE = re.compile(r'(\s(?:title|aria-label|placeholder|alt)=")([^"]*)(")')
_URL_ATTR = re.compile(r'(\s(?:href|src)=")([^"]*)(")')
_META_TEXT = re.compile(r'(<meta\s+(?:name|property)="([^"]+)"\s+content=")([^"]*)(")')


def _tr_html(raw: str, lang: str) -> str | None:
    """Translation of an HTML text or attribute value (the catalogue key is the whitespace-collapsed text)."""
    key = " ".join(html.unescape(raw).split())
    if not I.is_text(key):
        return None
    return I.t(key, lang)


def _pl_url(u: str) -> str:
    """A relative link of web/index.html, seen from web/pl/: assets go up a level; atlas/ and llms.txt have Polish
    twins under pl/; the language switch swaps."""
    if not u or re.match(r"^(?:[a-z][a-z0-9+.-]*:|#|/|\.\./)", u):
        return u
    if u == "./":
        return "../"
    if u == "pl/":
        return "./"
    if u.startswith("atlas/") or u in ("llms.txt", "llms-full.txt"):
        return u
    return "../" + u


def _pl_tag(tag: str, lang: str) -> str:
    if re.match(r"<html\b", tag, re.I):
        return re.sub(r'\slang="[^"]*"', f' lang="{lang}"', tag) if " lang=" in tag else tag[:5] + f' lang="{lang}"' + tag[5:]
    if tag.startswith("<meta"):
        m = _META_TEXT.search(tag)
        if m and m.group(2) in I._HtmlText.META:
            tr = _tr_html(m.group(3), lang)
            if tr is not None:
                tag = tag[:m.start(3)] + esc(tr) + tag[m.end(3):]
        return tag
    tag = _READABLE.sub(lambda m: m.group(1) + (esc(_tr_html(m.group(2), lang)) if _tr_html(m.group(2), lang) is not None
                                                else m.group(2)) + m.group(3), tag)
    tag = _URL_ATTR.sub(lambda m: m.group(1) + _pl_url(m.group(2)) + m.group(3), tag)
    if 'data-lang="en"' in tag:
        tag = tag.replace(' aria-current="page"', "")
    if 'data-lang="pl"' in tag and "aria-current" not in tag:
        tag = tag[:-1] + ' aria-current="page">'
    return tag


def polish_index(en_html: str, ld: dict, og_image: str | None = None) -> str:
    """web/pl/index.html from web/index.html: lang="pl", every visible text and readable attribute through the
    catalogue, links that work from /pol-civ/pl/, the Polish head (canonical, og, hreflang) and JSON-LD."""
    out = []
    pos = 0
    for m in _PROTECTED.finditer(en_html):
        out.append(_pl_markup(en_html[pos:m.start()]))
        block = m.group(0)
        if block.lower().startswith("<script"):
            block = re.sub(r'(\ssrc=")([^"]*)(")', lambda x: x.group(1) + _pl_url(x.group(2)) + x.group(3), block, count=1)
        out.append(block)
        pos = m.end()
    out.append(_pl_markup(en_html[pos:]))
    text = "".join(out)
    text = _put_jsonld(text, ld) or text
    return _app_head(text, "pl", og_image)


def _pl_markup(part: str) -> str:
    out = []
    for m in _PIECE.finditer(part):
        if m.group(1):
            out.append(_pl_tag(m.group(1), "pl"))
            continue
        raw = m.group(2)
        tr = _tr_html(raw, "pl") if raw.strip() else None
        if tr is None:
            out.append(raw)
        else:
            lead = raw[:len(raw) - len(raw.lstrip())]
            tail = raw[len(raw.rstrip()):]
            out.append(lead + html.escape(tr, quote=False) + tail)
    return "".join(out)


def sitemap(pages_by_lang: dict, date: str) -> str:
    """Every page of both languages, each with its hreflang alternates (x-default: English)."""
    if isinstance(pages_by_lang, list):  # one language
        pages_by_lang = {"en": pages_by_lang}
    groups = [{lang: PREFIX[lang] for lang in pages_by_lang}]
    for p in pages_by_lang.get("en") or next(iter(pages_by_lang.values())):
        groups.append(p.get("alts") or {p.get("lang", "en"): p["path"]})
    body = []
    for alts in groups:
        links = "".join(f'<xhtml:link rel="alternate" hreflang="{l}" href="{esc(SITE_URL + alts[l])}"/>' for l in LANGS if l in alts)
        if "en" in alts:
            links += f'<xhtml:link rel="alternate" hreflang="x-default" href="{esc(SITE_URL + alts["en"])}"/>'
        for l in LANGS:
            if l in alts:
                body.append(f"  <url><loc>{esc(SITE_URL + alts[l])}</loc><lastmod>{date}</lastmod>{links if len(alts) > 1 else ''}</url>\n")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "".join(body) + "</urlset>\n")


# --- build -----------------------------------------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    from ..core.store import atomic_write_text

    atomic_write_text(path, text)


def build_site(web: Path, date: str | None = None, save_plan=None) -> dict:
    """Write every output under `web` (reading web/data). Returns a summary {pages, pages_pl, bytes, plan}."""
    web = Path(web)
    date = date or build_date()
    d = Data(web / "data")
    if not d.cities or not d.states:
        raise FileNotFoundError("seo: cities.json and states.json are required")
    by_lang = {lang: build_pages(d, web, lang) for lang in LANGS}
    paths = {lang: {p["slug"]: p["path"] for p in pages} for lang, pages in by_lang.items()}
    for lang, pages in by_lang.items():
        for p in pages:
            p["alts"] = {l: paths[l][p["slug"]] for l in LANGS if p["slug"] in paths[l]}
            p["_pub"] = lambda sid, d=d, lang=lang: d.publisher(sid, lang) if sid else CHROME[lang]["see"]
    total = 0
    for lang, pages in by_lang.items():
        atlas = web / PREFIX[lang] / "atlas"
        keep = {p["path"] for p in pages}
        if atlas.exists():  # drop pages of towns that left the list
            for sub in atlas.iterdir():
                if sub.is_dir() and f"{PREFIX[lang]}atlas/{sub.name}/" not in keep:
                    for fl in sub.iterdir():
                        fl.unlink()
                    sub.rmdir()
        for p in pages:
            folder = web / p["path"]
            _write(folder / "index.html", render_html(p, date))
            _write(folder / "index.md", render_md(p, date))
        total += sum(fl.stat().st_size for fl in atlas.rglob("*") if fl.is_file())
    catalog = data_catalog(d, web, date)
    _write(web / "data" / "index.json", json.dumps(catalog, ensure_ascii=False, indent=1) + "\n")
    for lang in LANGS:
        _write(web / PREFIX[lang] / "llms.txt", llms_txt(d, by_lang[lang], catalog, lang))
        _write(web / PREFIX[lang] / "llms-full.txt", llms_full(by_lang[lang], date, lang))
    _write(web / "sitemap.xml", sitemap(by_lang, date))
    fill_index_html(web, app_jsonld(d, catalog, date, "en", _main_og(web, "en")))
    if (web / "index.html").exists():
        og_pl = _main_og(web, "pl")
        _write(web / "pl" / "index.html",
               polish_index((web / "index.html").read_text(), app_jsonld(d, catalog, date, "pl", og_pl), og_pl))
    plan = []
    for lang in LANGS:
        for p in by_lang[lang]:
            if p["kind"] == "index":
                continue
            item = {"slug": p["slug"], "kind": p["kind"], "name": p["name"], "sub": p.get("sub") or "", "number": p["og_number"],
                    "focus": p["focus"], "out": f"og/{PREFIX[lang]}{p['slug']}.jpg"}
            if lang != "en":
                item["lang"] = lang
            plan.append(item)
    if save_plan:
        save_plan(plan)
    return {"pages": len(by_lang["en"]), "pages_pl": len(by_lang["pl"]), "atlas_bytes": total, "plan": plan}


def build() -> None:
    from ..core.store import save_interim

    res = build_site(WEB, save_plan=lambda plan: save_interim("_seo", {"og_plan": plan}))
    print(f"    atlas: {res['pages']} English and {res['pages_pl']} Polish pages, {res['atlas_bytes'] / 1e3:.0f} kB; "
          "pl/index.html, llms.txt and llms-full.txt (both languages), sitemap.xml, data/index.json")


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


def hreflangs(text: str) -> dict:
    """{hreflang: href} of the <link rel="alternate" hreflang> tags of a page."""
    out = {}
    for _, attrs in _TAG.findall(text):
        a = dict(_ATTR.findall(attrs))
        if a.get("rel") == "alternate" and a.get("hreflang"):
            out[a["hreflang"]] = html.unescape(a.get("href", ""))
    return out


def page_lang(text: str) -> str | None:
    m = re.search(r'<html\b[^>]*\blang="([^"]+)"', text)
    return m.group(1) if m else None


def jsonld_of(text: str) -> list:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)]


def _lang_problems(web: Path, rel: str, text: str, lang: str) -> list[str]:
    """hreflang pairs present, self-referencing and reciprocal; <html lang> right."""
    bad = []
    if page_lang(text) != lang:
        bad.append(f"{rel}: html lang {page_lang(text)!r}, want {lang!r}")
    alts = hreflangs(text)
    if set(alts) != set(LANGS) | {"x-default"}:
        bad.append(f"{rel}: hreflang alternates {sorted(alts)}")
        return bad
    if alts[lang] != SITE_URL + rel:
        bad.append(f"{rel}: hreflang {lang} is not the page itself")
    if alts["x-default"] != alts["en"]:
        bad.append(f"{rel}: x-default is not the English page")
    for other in LANGS:
        if other == lang:
            continue
        target = alts[other][len(SITE_URL):] if alts[other].startswith(SITE_URL) else None
        tf = web / ((target or "") + "index.html")
        if target is None or not tf.exists():
            bad.append(f"{rel}: {other} alternate {alts[other]} has no page")
        elif hreflangs(tf.read_text()).get(lang) != SITE_URL + rel:
            bad.append(f"{rel}: {other} alternate does not point back")
    return bad


def check(web_dir: Path) -> list[tuple[str, str]]:
    web_dir = Path(web_dir)
    web = web_dir.parent
    out: list[tuple[str, str]] = []
    if not (web / "atlas" / "index.html").exists():
        return [("NOTE", "web/atlas missing (optional; run: uv run python -m pipeline build seo)")]
    all_pages = {}
    for lang in LANGS:
        atlas = web / PREFIX[lang] / "atlas"
        pages = sorted(atlas.rglob("index.html")) if atlas.exists() else []
        all_pages[lang] = pages
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
            if head.get("og:locale") != OG_LOCALE[lang]:
                bad.append(f"{rel}: og:locale {head.get('og:locale')!r}")
            bad += _lang_problems(web, rel, text, lang)
            img = head.get("og:image", "")
            if img.startswith(SITE_URL) and not (web / img[len(SITE_URL):]).exists():
                bad.append(f"{rel}: share image {img[len(SITE_URL):]} missing")
            try:
                lds = jsonld_of(text)
                nodes = [n for ld in lds for n in ld.get("@graph", [])]
                types = {n.get("@type") for n in nodes}
                if "WebPage" not in types or "BreadcrumbList" not in types:
                    bad.append(f"{rel}: JSON-LD lacks WebPage or BreadcrumbList")
                elif any(n.get("@type") == "WebPage" and n.get("inLanguage") != lang for n in nodes):
                    bad.append(f"{rel}: JSON-LD inLanguage is not {lang}")
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
            out.append(("FAIL", f"... {len(bad) - 10} more page problems ({lang})"))
        if not pages:
            out.append(("FAIL", f"atlas ({lang}): no pages under {PREFIX[lang]}atlas/"))
        elif not bad:
            out.append(("PASS", f"atlas ({lang}): {len(pages)} pages with canonical, hreflang pairs, description, share card, "
                                "CSP, JSON-LD and a markdown copy"))
        own = f'content="{SITE_URL}og/{PREFIX[lang]}'
        shared = sum(1 for p in pages if own in (tx := p.read_text()) and (lang != "en" or 'og/pl/' not in tx)
                     and f'og/{PREFIX[lang]}main.jpg' not in tx)  # the atlas index shows the main image
        out.append(("NOTE" if shared < len(pages) - 1 else "PASS",
                    f"atlas ({lang}): {shared} of {max(len(pages) - 1, 0)} place pages have their own share image (scripts/og-shots.mjs"
                    + (" --lang pl)" if lang != "en" else ")")))

    cities = _load(web_dir, "cities.json")
    if isinstance(cities, list):
        want = sum(1 for c in cities if isinstance(c, dict) and c.get("city_view"))
        states = _load(web_dir, "states.json") or []
        for lang in LANGS:
            have = len(all_pages[lang]) - 1
            if have != want + len(states):
                out.append(("WARN", f"atlas ({lang}): {have} place pages, data has {len(states)} voivodeships + {want} towns "
                                    "(rebuild: pipeline build seo)"))

    sm = web / "sitemap.xml"
    if sm.exists():
        smt = sm.read_text()
        blocks = re.findall(r"<url>(.*?)</url>", smt, re.S)
        locs = [re.search(r"<loc>(.*?)</loc>", b).group(1) for b in blocks if "<loc>" in b]
        missing = [u for u in locs if not (web / (u[len(SITE_URL):] + "index.html" if u.startswith(SITE_URL) else "x")).exists()]
        listed = {u[len(SITE_URL):] for u in locs}
        unlisted = [p.parent.relative_to(web).as_posix() + "/" for lang in LANGS for p in all_pages[lang]
                    if p.parent.relative_to(web).as_posix() + "/" not in listed]
        no_alt = [b for b in blocks if len(set(re.findall(r'hreflang="([^"]+)"', b))) < len(LANGS) + 1]
        if 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' not in smt:
            out.append(("FAIL", "sitemap.xml: no xhtml namespace for the hreflang alternates"))
        if missing or unlisted or no_alt:
            out.append(("FAIL", f"sitemap.xml: {len(missing)} URLs without a page, {len(unlisted)} pages not listed, "
                                f"{len(no_alt)} URLs without en/pl/x-default alternates"))
        else:
            out.append(("PASS", f"sitemap.xml: {len(locs)} URLs, each with a page and its en/pl/x-default alternates"))
    else:
        out.append(("FAIL", "sitemap.xml missing"))

    for lang in LANGS:
        name = PREFIX[lang] + "llms.txt"
        lt = web / name
        if lt.exists():
            problems = llms_problems(lt.read_text(), web)
            out.append(("FAIL", f"{name}: " + "; ".join(problems[:5])) if problems
                       else ("PASS", f"{name}: H1, summary, sections, every local link resolves"))
        else:
            out.append(("FAIL", f"{name} missing"))
        if not (web / PREFIX[lang] / "llms-full.txt").exists():
            out.append(("FAIL", f"{PREFIX[lang]}llms-full.txt missing"))

    cat = _load(web_dir, "index.json")
    if isinstance(cat, dict):
        gone = [fi["path"] for fi in cat.get("files", []) if not (web / fi["path"]).exists()]
        out.append(("FAIL", f"data/index.json lists missing files: {gone}") if gone else ("PASS", f"data/index.json: {len(cat.get('files', []))} files catalogued"))
    else:
        out.append(("FAIL", "data/index.json missing or invalid"))

    for lang in LANGS:
        rel = PREFIX[lang]
        idx = web / rel / "index.html"
        label = f"web/{rel}index.html"
        if not idx.exists():
            out.append(("FAIL" if lang != "en" else "WARN", f"{label} missing (pipeline build seo writes pl/index.html)"))
            continue
        text = idx.read_text()
        csp = _head(text).get("Content-Security-Policy")
        if csp != APP_CSP:
            out.append(("WARN" if lang == "en" else "FAIL", f"{label} CSP differs from seo.APP_CSP (keep them equal)"))
        if CF_BEACON_HOST in text:
            out.append(("FAIL", f"{label} loads the Cloudflare beacon directly (analytics.js injects it)"))
        bad = []
        if _head(text).get("link:canonical") != SITE_URL + rel:
            bad.append(f"canonical {_head(text).get('link:canonical')!r}")
        bad += [b.split(": ", 1)[1] for b in _lang_problems(web, rel, text, lang)]
        if 'property="og:locale"' in text and _head(text).get("og:locale") != OG_LOCALE[lang]:
            bad.append(f"og:locale {_head(text).get('og:locale')!r}")
        try:
            nodes = [n for ld in jsonld_of(text) for n in ld.get("@graph", [])]
            if nodes and any(n.get("inLanguage") not in (None, lang) for n in nodes):
                bad.append(f"JSON-LD inLanguage is not {lang}")
        except ValueError as exc:
            bad.append(f"JSON-LD does not parse ({exc})")
        if lang != "en":
            if re.search(r'(?:href|src)="(?:css|js|data)/', text):
                bad.append("asset links not made relative to pl/")
        if LEAK.search(text):
            bad.append("contains a local path or private name")
        if lang != "en" and (web / "index.html").exists() and not bad:
            # pl/index.html is made from index.html and the catalogue: a change to either needs a rebuild.
            try:
                lds = jsonld_of(text)
                og = _head(text).get("og:image", "")
                want = polish_index((web / "index.html").read_text(), lds[0] if lds else {},
                                    og[len(SITE_URL):] if og.startswith(SITE_URL) else None)
                if want != text:
                    out.append(("WARN", f"{label} is older than web/index.html or the catalogue (rebuild: pipeline build seo)"))
            except ValueError:
                pass
        if bad:
            out.append(("FAIL", f"{label}: " + "; ".join(bad[:5])))
        else:
            out.append(("PASS", f"{label}: lang, canonical, hreflang pair, CSP and JSON-LD"))

    for name in ("llms.txt", "llms-full.txt", "pl/llms.txt", "pl/llms-full.txt", "sitemap.xml"):
        fl = web / name
        if fl.exists() and LEAK.search(fl.read_text()):
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

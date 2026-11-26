"""The two languages of the site: English (the source language) and Polish.

One catalogue, gettext style: web/i18n/pl.json maps each English source string (exact) to its Polish text. The
browser (web/js/i18n.js) and the atlas builder (pipeline/build/seo.py) read the same file. English needs no
catalogue: a key is its own English text.

    t("Median age", "pl")                          -> "Mediana wieku"
    t("{n} towns", "pl", n=12)                     -> placeholders are {name}; numbers are formatted per language
    plural(5, {"one": "{n} town", "other": "{n} towns"}, "pl")   -> catalogue entry {"one", "few", "many", "other"}

Dates. Data files carry dates as ISO text: "2026-06-30", "2026-10", "2025". Builders write free text with ISO dates
inside ("GUS, 2025-12-31"); write_web() turns any English date a source still writes ("30 June 2026", "Oct 2026")
into ISO, and localize_dates() formats every ISO date of a text for the reader at render time.

Extraction. keys_in_js() finds every t("...") and t.plural(n, {...}) call in web/js; data_keys() reads the text
fields listed in DATA_TEXT from web/data; html_keys() reads the visible text of web/index.html. missing() is the
list of English keys with no Polish entry: scripts/i18n-extract.py prints it and pipeline/build/i18n.py check()
fails the build on it.
"""

from __future__ import annotations

import datetime
import html.parser
import json
import math
import re
from pathlib import Path

from .paths import WEB

LANGS = ("en", "pl")
CATALOGUE = WEB / "i18n" / "pl.json"
JS_DIR = WEB / "js"
INDEX_HTML = WEB / "index.html"
NBSP = "\u00a0"

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
# Polish month names: genitive after a day ("30 czerwca 2026"), nominative alone ("październik 2026").
MONTHS_PL_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
                 "października", "listopada", "grudnia"]
MONTHS_PL_NOM = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień",
                 "październik", "listopad", "grudzień"]
_MONTH_NO = {m: i + 1 for i, m in enumerate(MONTHS_EN)}
_MONTH_NO.update({m[:3]: i + 1 for i, m in enumerate(MONTHS_EN)})
_MONTH_NO["Sept"] = 9
_MONTH_ALT = "|".join(sorted(_MONTH_NO, key=len, reverse=True))


# --- dates -------------------------------------------------------------------------------------------------------

_EN_DAY = re.compile(r"\b(\d{1,2}) (%s)\.? (\d{4})\b" % _MONTH_ALT)
_EN_MONTH = re.compile(r"\b(%s) (\d{4})\b" % "|".join(MONTHS_EN))
_EN_MONTH_DAY = re.compile(r"\b(%s) (\d{1,2}), (\d{4})\b" % "|".join(MONTHS_EN))  # "June 30, 2026"
# Keys whose values are identifiers or links, never prose: iso_dates_deep() leaves them alone.
NOT_PROSE = {"ref", "url", "href", "wikidata", "file", "path", "id", "source", "sources", "icon", "color"}


def iso_dates(text: str) -> str:
    """English dates in a text to ISO: "30 June 2026" -> "2026-06-30", "31 Dec 2025" -> "2025-12-31",
    "October 2026" -> "2026-10". Anything else is left as it is."""
    if not isinstance(text, str) or not re.search(r"\d{4}", text):
        return text

    def day(m):
        d, mon, y = int(m.group(1)), _MONTH_NO[m.group(2)], m.group(3)
        try:
            datetime.date(int(y), mon, d)  # "31 Sept 2025" is not a date: leave it as written
        except ValueError:
            return m.group(0)
        return f"{y}-{mon:02d}-{d:02d}"

    text = _EN_MONTH_DAY.sub(lambda m: f"{m.group(3)}-{_MONTH_NO[m.group(1)]:02d}-{int(m.group(2)):02d}", text)
    text = _EN_DAY.sub(day, text)
    return _EN_MONTH.sub(lambda m: f"{m.group(2)}-{_MONTH_NO[m.group(1)]:02d}", text)


def iso_dates_deep(obj, key: str | None = None):
    """iso_dates() on every string of a JSON value, except under the NOT_PROSE keys."""
    if key in NOT_PROSE:
        return obj
    if isinstance(obj, str):
        return iso_dates(obj)
    if isinstance(obj, list):
        return [iso_dates_deep(v) for v in obj]
    if isinstance(obj, dict):
        return {k: iso_dates_deep(v, k) for k, v in obj.items()}
    return obj


_ISO_DAY = re.compile(r"(?<![\w/.:=-])(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?![\w/-])")
_ISO_MONTH = re.compile(r"(?<![\w/.:=-])(\d{4})-(0[1-9]|1[0-2])(?![\w/-])")


def fmt_date(iso, lang: str = "en") -> str:
    """"2026-06-30" -> "30 June 2026" / "30 czerwca 2026"; "2026-10" -> "October 2026" / "październik 2026";
    "2025" -> "2025". Anything that is not an ISO date comes back unchanged."""
    if iso is None:
        return ""
    s = str(iso)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if lang == "pl":
            return f"{d} {MONTHS_PL_GEN[mo - 1]} {y}"
        return f"{d} {MONTHS_EN[mo - 1]} {y}"
    m = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return f"{MONTHS_PL_NOM[mo - 1]} {y}" if lang == "pl" else f"{MONTHS_EN[mo - 1]} {y}"
    return s


def localize_dates(text: str, lang: str = "en") -> str:
    """Every ISO date inside a text, formatted for the reader (links and file names are left alone)."""
    if not isinstance(text, str) or "-" not in text:
        return text
    text = _ISO_DAY.sub(lambda m: fmt_date(m.group(0), lang), text)
    return _ISO_MONTH.sub(lambda m: fmt_date(m.group(0), lang), text)


# --- numbers -----------------------------------------------------------------------------------------------------

def _group(int_text: str, sep: str, min_digits: int) -> str:
    neg = int_text.startswith("-")
    digits = int_text[1:] if neg else int_text
    if len(digits) >= min_digits:
        parts = []
        while len(digits) > 3:
            parts.insert(0, digits[-3:])
            digits = digits[:-3]
        parts.insert(0, digits)
        digits = sep.join(parts)
    return ("-" if neg else "") + digits


def fmt_num(v, digits: int = 0, lang: str = "en", trim: bool = False) -> str:
    """A number with grouping: en "1,866,929" / "12.5"; pl "1 866 929" (no-break space, from 5 digits, as Intl
    pl-PL) / "12,5". trim drops trailing zeros of the fraction."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return ""
    s = f"{v:.{digits}f}" if digits else str(int(round(v)))
    whole, _, frac = s.partition(".")
    if trim and frac:
        frac = frac.rstrip("0")
    if lang == "pl":
        out = _group(whole, NBSP, 5)
        return out + ("," + frac if frac else "")
    out = _group(whole, ",", 4)
    return out + ("." + frac if frac else "")


def fmt_pct(frac, digits: int = 1, lang: str = "en") -> str:
    """A 0..1 share as a percentage: "16.3%" / "16,3%"."""
    if frac is None:
        return ""
    return fmt_num(frac * 100, digits, lang) + "%"


# --- catalogue ---------------------------------------------------------------------------------------------------

_CACHE: dict[str, dict] = {}


def load_catalogue(path: Path | None = None) -> dict:
    """The Polish catalogue {English: Polish | {one, few, many, other}} (empty if the file does not exist)."""
    p = Path(path or CATALOGUE)
    key = str(p)
    if key not in _CACHE:
        _CACHE[key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _CACHE[key]


def _fill(text: str, lang: str, vars_: dict) -> str:
    def rep(m):
        name = m.group(1)
        if name not in vars_:
            return m.group(0)
        v = vars_[name]
        if isinstance(v, bool) or v is None:
            return str(v if v is not None else "")
        if isinstance(v, int):
            return str(v) if abs(v) < 10000 else fmt_num(v, 0, lang)  # a year must not read "2,024"
        if isinstance(v, float):
            return fmt_num(v, 0 if v.is_integer() else 1, lang, trim=True)
        return str(v)

    return re.sub(r"\{(\w+)\}", rep, text)


def t(key: str, lang: str = "en", catalogue: dict | None = None, **vars_) -> str:
    """The text of `key` in `lang`, with {name} placeholders filled and ISO dates formatted. A key with no Polish
    entry falls back to English (pipeline check fails the build before that can ship)."""
    if key is None:
        return ""
    text = key
    if lang == "pl":
        cat = load_catalogue() if catalogue is None else catalogue
        hit = cat.get(key)
        if isinstance(hit, str):
            text = hit
    return localize_dates(_fill(text, lang, vars_), lang)


def plural_category(n, lang: str = "en") -> str:
    """CLDR plural category: en one/other; pl one (1), few (2-4, not 12-14), many (0, 5+, 12-14), other (fractions)."""
    if lang != "pl":
        return "one" if n == 1 else "other"
    if not isinstance(n, int) and not (isinstance(n, float) and n.is_integer()):
        return "other"
    n = abs(int(n))
    if n == 1:
        return "one"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "many"


def plural(n, forms: dict, lang: str = "en", catalogue: dict | None = None, **vars_) -> str:
    """forms are the English {one, other}; the Polish forms come from the catalogue entry keyed by forms["other"]."""
    chosen = forms.get("one") if plural_category(n, "en") == "one" else forms.get("other")
    if lang == "pl":
        cat = load_catalogue() if catalogue is None else catalogue
        hit = cat.get(forms.get("other"))
        if isinstance(hit, dict):
            cat_name = plural_category(n, "pl")
            chosen = hit.get(cat_name) or hit.get("few") or hit.get("many") or chosen  # fractions: like "few"
    return localize_dates(_fill(chosen or "", lang, {"n": n, **vars_}), lang)


# --- extraction --------------------------------------------------------------------------------------------------

# A string literal: "..." or '...' (escapes allowed) or `...` with no ${...} inside.
_STR = r"""("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\$]|\\.|\$(?!\{))*`)"""
_T_CALL = re.compile(r"(?<![\w.$])t\(\s*" + _STR + r"\s*[,)]", re.S)
_PLURAL_CALL = re.compile(r"(?<![\w.$])t\.plural\(\s*[^,]+,\s*\{(.*?)\}\s*[,)]", re.S)
_FORM = re.compile(r"(one|other)\s*:\s*" + _STR, re.S)
_JS_ESC = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'", "`": "`", "$": "$"}


def _unquote(lit: str) -> str:
    body = lit[1:-1]

    def rep(m):
        c = m.group(1)
        if c.startswith("u"):
            return chr(int(c[2:-1] if c[1] == "{" else c[1:], 16))
        if c.startswith("x"):
            return chr(int(c[1:], 16))
        return _JS_ESC.get(c, c)

    return re.sub(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", rep, body, flags=re.S)


def keys_in_js(js_dir: Path | None = None) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(plain keys, plural keys) found in web/js, each {key: ["file:line", ...]}. Plural keys are the English
    "other" forms. Files under js/dev are skipped (not shipped)."""
    base = Path(js_dir or JS_DIR)
    plain: dict[str, list[str]] = {}
    plurals: dict[str, list[str]] = {}
    for f in sorted(base.rglob("*.js")):
        rel = f.relative_to(base.parent).as_posix()
        text = f.read_text(encoding="utf-8")
        # Line comments can hold examples such as t("...") in docs; strip them (keeping line numbers).
        code = re.sub(r"(?m)^\s*//.*$|^\s*\*.*$", lambda m: "", text)
        for m in _T_CALL.finditer(code):
            line = code.count("\n", 0, m.start()) + 1
            plain.setdefault(_unquote(m.group(1)), []).append(f"{rel}:{line}")
        for m in _PLURAL_CALL.finditer(code):
            line = code.count("\n", 0, m.start()) + 1
            forms = {k: _unquote(v) for k, v in _FORM.findall(m.group(1))}
            if "other" in forms:
                plurals.setdefault(forms["other"], []).append(f"{rel}:{line}")
    return plain, plurals


# Data text fields shown to readers, by file: a path of keys, "[]" for every list item, "*" for every dict value.
# The browser passes each of these values through t(); proper names (places, units, operators) are not listed.
DATA_TEXT: dict[str, list[str]] = {
    "lenses.json": ["groups[].name", "lenses[].name", "lenses[].short_name", "lenses[].description", "lenses[].note", "lenses[].unit",
                    "lenses[].categories[].name", "lenses[].categories[].description", "lenses[].legend[].label"],
    "world.json": ["tables.water[].name", "tables.relief[].name", "tables.cover[].name", "tables.water[].rule",
                   "tables.relief[].rule", "tables.cover[].rule", "tables.notes[]"],
    "nation.json": ["yields[].label", "yields[].description", "industries.*"],
    "counties.json": ["fields[].label", "fields[].description", "fields[].unit"],
    "powiaty.json": ["fields[].label", "fields[].description", "fields[].unit"],
    "citizens.json": ["groups.*[].label", "rows.*", "rule.text"],
    "districts.json": ["rule.text", "rule.scope_note", "badges[].label", "badges[].rule", "catalog[].name",
                       "catalog[].description", "catalog[].caveat", "catalog[].sub.*", "catalog[].badge.label",
                       "catalog[].badge.labels.*", "industries.*.title", "cities.*.badge.tpl"],
    "disasters.json": ["*.rule", "*.name", "*.label", "*.note"],
    "trade.json": ["rule", "path_note", "modes[].name", "road_freight.fields[].label", "units.*"],
    "metros.json": ["rule"],
    "military.json": ["caveats", "caveats[]", "components[].name", "components[].description", "rule", "rules.*",
                      "national.spending.*.name", "national.spending.*.note", "ranges[].kind"],
    "infrastructure.json": ["rules.*", "road_classes[].name", "rail_tiers[].name", "ports[].name",
                            "airports[].status_note"],
    "resources.json": ["types[].name", "types[].description", "types[].unit", "items[].name", "items[].status_label", "items[].status_note",
                       "items[].output_unit",
                       "rules.*", "summary.note", "renewables.fields[].label", "renewables.fields[].note"],
    "wonders.json": ["rules[].text", "wonders[].name", "wonders[].short", "wonders[].component",
                     "wonders[].metrics.category", "wonders[].metrics.record", "wonders[].metrics.unit",
                     "wonders[].metrics.unit_type", "wonders[].note"],
    "commuting.json": ["rule", "notes[]"],
    "history.json": ["layers[].label", "layers[].labels[].name", "layers[].lines[].tip", "rules[]", "licence", "notes[]"],
    "timeline.json": ["notes[]", "rule"],
    "sources.json": ["[].title", "[].description", "[].publisher", "[].license", "[].vintage", "[].used_for[]",
                     "[].notes[]", "[].caveats[]"],
}
# Vintage lines are shown in the Almanac and in lens notes.
for _name in ("lenses.json", "nation.json", "counties.json", "powiaty.json", "citizens.json", "districts.json",
              "disasters.json", "trade.json", "metros.json", "military.json", "infrastructure.json", "resources.json",
              "wonders.json", "commuting.json", "history.json", "timeline.json"):
    DATA_TEXT[_name] += ["vintage", "vintage.*", "gdp_vintage"]


def _walk(obj, parts: list[str]):
    if not parts:
        if isinstance(obj, str):
            yield obj
        return
    head, rest = parts[0], parts[1:]
    if head == "[]":
        if isinstance(obj, list):
            for v in obj:
                yield from _walk(v, rest)
    elif head == "*":
        if isinstance(obj, dict):
            for v in obj.values():
                yield from _walk(v, rest)
    elif isinstance(obj, dict) and head in obj:
        yield from _walk(obj[head], rest)


def split_path(path: str) -> list[str]:
    """"lenses[].categories[].name" -> ["lenses", "[]", "categories", "[]", "name"]; "[].title" -> ["[]", "title"]."""
    out = []
    for part in path.split("."):
        while part.endswith("[]"):
            if part[:-2]:
                out.append(part[:-2])
            part = ""
            out.append("[]")
        if part:
            out.append(part)
    return out


def is_text(s: str) -> bool:
    """A value worth translating: it has a word of two or more letters and is not a code, number or link."""
    s = s.strip()
    # Links, colours, snake_case ids and short upper-case codes ("PKD", "MW") are not prose.
    if not s or re.fullmatch(r"https?://\S+|#[0-9a-fA-F]{3,8}|[a-z0-9]+(_[a-z0-9]+)+|[A-Z0-9_\-]{1,8}", s):
        return False
    return bool(re.search(r"[A-Za-zÀ-ž]{2,}", s))


def data_keys(web_data: Path | None = None, spec: dict | None = None) -> dict[str, list[str]]:
    """{text: ["file:path", ...]} for every DATA_TEXT field present in web/data."""
    base = Path(web_data or WEB / "data")
    out: dict[str, list[str]] = {}
    for name, paths in (spec or DATA_TEXT).items():
        f = base / name
        if not f.exists():
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        for path in paths:
            for s in _walk(doc, split_path(path)):
                if is_text(s):
                    where = f"{name}:{path}"
                    lst = out.setdefault(s, [])
                    if where not in lst:
                        lst.append(where)
    return out


class _HtmlText(html.parser.HTMLParser):
    """Visible text and the readable attributes of web/index.html (title, aria-label, placeholder, alt, meta
    descriptions). Script and style contents are skipped."""

    ATTRS = {"title", "aria-label", "placeholder", "alt"}
    META = {"description", "og:title", "og:description", "og:image:alt", "twitter:title", "twitter:description",
            "twitter:image:alt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, int]] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "meta" and (a.get("name") in self.META or a.get("property") in self.META) and a.get("content"):
            self.found.append((a["content"], self.getpos()[0]))
        for k in self.ATTRS:
            if a.get(k):
                self.found.append((a[k], self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.found.append((" ".join(data.split()), self.getpos()[0]))


def html_keys(path: Path | None = None) -> dict[str, list[str]]:
    p = Path(path or INDEX_HTML)
    if not p.exists():
        return {}
    parser = _HtmlText()
    parser.feed(p.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for text, line in parser.found:
        if is_text(text):
            out.setdefault(text, []).append(f"{p.name}:{line}")
    return out


def all_keys(web: Path | None = None) -> dict[str, dict]:
    """{key: {"where": [...], "plural": bool}} from the JS, the data files and index.html."""
    base = Path(web or WEB)
    plain, plurals = keys_in_js(base / "js")
    out: dict[str, dict] = {}
    for src in (plain, data_keys(base / "data"), html_keys(base / "index.html")):
        for k, where in src.items():
            out.setdefault(k, {"where": [], "plural": False})["where"] += where
    for k, where in plurals.items():
        e = out.setdefault(k, {"where": [], "plural": True})
        e["where"] += where
        e["plural"] = True
    return out


def missing(web: Path | None = None, catalogue: dict | None = None) -> dict[str, dict]:
    """The keys with no usable Polish entry: absent, empty, or a plural key without one/few/many forms."""
    cat = load_catalogue() if catalogue is None else catalogue
    out = {}
    for k, info in all_keys(web).items():
        v = cat.get(k)
        if info["plural"]:
            ok = isinstance(v, dict) and all(isinstance(v.get(f), str) and v.get(f) for f in ("one", "few", "many"))
        else:
            ok = isinstance(v, str) and v.strip() != ""
        if not ok:
            out[k] = info
    return out


def placeholder_problems(catalogue: dict | None = None) -> list[str]:
    """Entries whose Polish text drops or invents a {placeholder}, or adds HTML the English key does not have."""
    cat = load_catalogue() if catalogue is None else catalogue
    probs = []
    for k, v in cat.items():
        if k.startswith("_"):
            continue
        texts = list(v.values()) if isinstance(v, dict) else [v]
        want = set(re.findall(r"\{(\w+)\}", k))
        for text in texts:
            if not isinstance(text, str):
                probs.append(f"{k!r}: value is not text")
                continue
            got = set(re.findall(r"\{(\w+)\}", text))
            extra = got - want - ({"n"} if isinstance(v, dict) else set())
            lost = want - got - ({"n"} if isinstance(v, dict) else set())
            if extra or lost:
                probs.append(f"{k!r}: placeholders {sorted(lost)} lost, {sorted(extra)} added")
            if re.search(r"[<>]", text) and not re.search(r"[<>]", k):
                probs.append(f"{k!r}: the Polish text adds HTML")
    return probs

// Languages: English (the source language) and Polish. web/i18n/pl.json maps each English string (exact) to Polish;
// pipeline/core/i18n.py reads the same catalogue for the atlas and lists the keys that have no Polish entry.
//
//   t("Median age")                               -> "Mediana wieku" on the Polish page, the key itself in English
//   t("{name} in {year}", {name, year})          -> {placeholders}; numbers are formatted for the language
//   t.plural(n, {one: "{n} town", other: "{n} towns"})  -> Polish forms from the catalogue entry of the "other" form:
//                                                     {"one": "{n} miasto", "few": "{n} miasta", "many": "{n} miast"}
//
// t() returns plain text: escape it before putting it into HTML (vars that are already HTML stay as they are).
// ISO dates inside any text ("2026-06-30", "2026-10") come out in the reader's form ("30 czerwca 2026").
// The language is the <html lang> of the page: web/index.html is English, web/pl/index.html is Polish. The catalogue
// loads with a top-level await, so every module that imports this one can call t() at import time.

const doc = typeof document !== "undefined" ? document : null;
export let LANG = doc?.documentElement?.lang?.toLowerCase().startsWith("pl") ? "pl" : "en";
/** Path from the page to the site root (web/): "" for /pol-civ/, "../" for /pol-civ/pl/. */
export const ROOT = LANG === "pl" ? "../" : "";
let LOCALE = LANG === "pl" ? "pl-PL" : "en-GB";
let catalogue = {};

if (LANG === "pl") {
  try {
    const r = await fetch(`${ROOT}i18n/pl.json`);
    if (r.ok) catalogue = await r.json();
  } catch (err) {
    console.warn("i18n: the Polish catalogue did not load", err);
  }
}

/** Switch language and catalogue (tests, tools). The page itself never switches: each language has its own URL. */
export function setLocale(lang, cat = {}) {
  LANG = lang === "pl" ? "pl" : "en";
  LOCALE = LANG === "pl" ? "pl-PL" : "en-GB";
  catalogue = cat || {};
  NF.clear();
}

const NF = new Map();
function nf(opts) {
  const key = JSON.stringify(opts);
  let f = NF.get(key);
  if (!f) NF.set(key, (f = new Intl.NumberFormat(LOCALE, opts)));
  return f;
}
const fin = (v) => typeof v === "number" && Number.isFinite(v);

function fill(text, vars) {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (m, name) => {
    if (!(name in vars)) return m;
    const v = vars[name];
    if (v == null) return "";
    // Integers of up to four digits stay ungrouped (a year passed as a number must not read "2,024").
    if (typeof v === "number") return Number.isInteger(v) ? (Math.abs(v) < 1e4 ? String(v) : num(v)) : num(v, 1, { trim: true });
    return String(v);
  });
}

/** The text of `key` in the page language, with {placeholders} filled and ISO dates formatted. */
export function t(key, vars) {
  if (key == null) return "";
  const k = String(key);
  const hit = LANG === "pl" ? catalogue[k] : null;
  return localizeDates(fill(typeof hit === "string" && hit ? hit : k, vars));
}

/** CLDR plural category: English one/other; Polish one (1), few (2-4 but not 12-14), many (0, 5+), other (fractions). */
export function pluralCategory(n, lang = LANG) {
  if (lang !== "pl") return n === 1 ? "one" : "other";
  if (!Number.isInteger(n)) return "other";
  const a = Math.abs(n);
  if (a === 1) return "one";
  if (a % 10 >= 2 && a % 10 <= 4 && !(a % 100 >= 12 && a % 100 <= 14)) return "few";
  return "many";
}

/** forms: the English {one, other}. {n} is the formatted count; other vars as in t(). */
t.plural = function plural(n, forms, vars) {
  let text = n === 1 ? forms.one : forms.other;
  if (LANG === "pl") {
    const hit = catalogue[forms.other];
    // Fractions take the "other" form; Polish uses the genitive singular there, the same word as "few" (1,5 miasta).
    if (hit && typeof hit === "object") text = hit[pluralCategory(n)] || hit.few || hit.many || text;
  }
  return localizeDates(fill(text || "", { n, ...vars }));
};

/** Whether the catalogue has `key` (always true in English). */
t.has = (key) => LANG !== "pl" || typeof catalogue[key] === "string" || typeof catalogue[key] === "object";

// ---------------------------------------------------------------- numbers

const DASH = "–";

/** A number with the language's grouping and decimal sign: 1,866,929 / 1 866 929; 12.5 / 12,5. */
export function num(v, digits = 0, { trim = false, signed = false } = {}) {
  if (!fin(v)) return DASH;
  return nf({ minimumFractionDigits: trim ? 0 : digits, maximumFractionDigits: digits, signDisplay: signed ? "exceptZero" : "auto" }).format(v);
}
/** A number to `n` significant digits (0.000456, 0.34, 12.3), with the language's decimal sign. */
export const sig = (v, n = 3) => (fin(v) ? nf({ maximumSignificantDigits: n }).format(v) : DASH);
export const int = (v) => (fin(v) ? num(Math.round(v)) : DASH);
/** A 0..1 share as a percentage: 16.3% / 16,3%. */
export const pct = (frac, digits = 1, opts = {}) => (fin(frac) ? num(frac * 100, digits, opts) + "%" : DASH);
/** A value already in percent (0..100). */
export const pct100 = (v, digits = 1, opts = {}) => (fin(v) ? num(v, digits, opts) + "%" : DASH);

// Short scales: English K, M, B, T; Polish tys., mln, mld, bln (with a space, as Polish writes them).
const SCALES = {
  en: [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]],
  pl: [[1e12, " bln"], [1e9, " mld"], [1e6, " mln"], [1e3, " tys."]],
};

/** 3.92T / 3,92 bln; 18.6M / 18,6 mln; 12K / 12 tys. Below 1,000 a plain integer. */
export function compact(n) {
  if (!fin(n)) return DASH;
  const a = Math.abs(n);
  for (const [base, suffix] of SCALES[LANG]) {
    if (a < base) continue;
    const v = n / base;
    const digits = base === 1e3 ? (a >= 1e5 ? 0 : 1) : base === 1e12 ? (a >= 1e13 ? 1 : 2) : a >= base * 100 ? 0 : 1;
    return num(v, digits, { trim: base === 1e3 }) + suffix;
  }
  return num(Math.round(n));
}

/** Money in złoty, short: 3.92T zł / 3,92 bln zł. */
export const money = (n) => (fin(n) ? compact(n) + " zł" : DASH);
/** Money in złoty, in full: 9,178 zł / 9178 zł. */
export const zloty = (n) => (fin(n) ? int(n) + " zł" : DASH);

/** Population, short: 1.9M / 1,9 mln; 28K / 28 tys. */
export function popShort(n) {
  if (!fin(n)) return DASH;
  if (n >= 1e7) return num(Math.round(n / 1e6)) + (LANG === "pl" ? " mln" : "M");
  if (n >= 1e6) return num(n / 1e6, 1) + (LANG === "pl" ? " mln" : "M");
  return num(Math.round(n / 1e3)) + (LANG === "pl" ? " tys." : "K");
}

// ---------------------------------------------------------------- dates

const DF = {};
function df(kind) {
  const k = LOCALE + kind;
  if (!DF[k]) {
    const opts = kind === "day" ? { day: "numeric", month: "long", year: "numeric" } : { month: "long", year: "numeric" };
    DF[k] = new Intl.DateTimeFormat(LOCALE, { ...opts, timeZone: "UTC" });
  }
  return DF[k];
}

/** "2026-06-30" -> 30 June 2026 / 30 czerwca 2026; "2026-10" -> October 2026 / październik 2026; "2025" -> 2025. */
export function date(iso) {
  if (iso == null) return "";
  const s = String(iso);
  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (m) return df("day").format(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])));
  m = /^(\d{4})-(\d{2})$/.exec(s);
  if (m) return df("month").format(new Date(Date.UTC(+m[1], +m[2] - 1, 1)));
  return s;
}

const ISO_DAY = /(?<![\w/.:=-])(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?![\w/-])/g;
const ISO_MONTH = /(?<![\w/.:=-])(\d{4})-(0[1-9]|1[0-2])(?![\w/-])/g;

/** Every ISO date inside a text, formatted for the reader. Links and file names are left alone. */
export function localizeDates(text) {
  if (typeof text !== "string" || text.indexOf("-") < 0) return text;
  return text.replace(ISO_DAY, (m) => date(m)).replace(ISO_MONTH, (m) => date(m));
}

// ---------------------------------------------------------------- the other language

/** The URL of the current view in `lang`: same page, same hash. */
export function langHref(lang, loc = typeof location !== "undefined" ? location : null) {
  if (!loc) return lang === "pl" ? "pl/" : "./";
  const path = loc.pathname;
  const isPl = /\/pl(\/|$)/.test(path);
  let target = path;
  if (lang === "pl" && !isPl) target = path.replace(/\/?(index\.html)?$/, "/") + "pl/";
  if (lang === "en" && isPl) target = path.replace(/\/pl(\/(index\.html)?)?$/, "/");
  return target + (loc.search || "") + (loc.hash || "");
}

export { LOCALE };

// Number formatting for the City View: format.js's compact helpers with a roll-over fix, so a value that rounds up
// to the next unit reads "1.0M" rather than "1000K" (e.g. a town of 999,600 people). format.js is shared with the
// rest of the app; this wrapper keeps the same output for every other value. Money is Polish zloty, as in format.js.
import { compact as baseCompact, popShort as basePopShort, money as baseMoney } from "../../format.js";
import { LANG } from "../../i18n.js";

const UNITS = LANG === "pl"
  ? [[1e12, "\u00a0bln"], [1e9, "\u00a0mld"], [1e6, "\u00a0mln"], [1e3, "\u00a0tys."]]
  : [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];

/** Rounds n up to the next unit when its compact form would print 1000 of the current one. */
function rollover(n, fmt) {
  if (n == null || Number.isNaN(n)) return fmt(n);
  const s = fmt(n);
  const m = /^-?1(?:\u00a0| |,)?000(?:[.,]0+)?(K|M|B|\u00a0tys\.|\u00a0mln|\u00a0mld)$/.exec(s);
  if (!m) return s;
  const i = UNITS.findIndex(([, u]) => u === m[1]);
  return fmt(Math.sign(n) * UNITS[i - 1][0]);
}

export const compact = (n) => rollover(n, baseCompact);
// format.js money() is compact(n) + the currency; the rolled-over compact keeps its unit and currency text.
export const money = (n) => (n == null || Number.isNaN(n) ? baseMoney(null) : compact(n) + "\u00a0zł");
export const yieldValue = (y, v) => (y.unit === "pln" || y.unit === "usd" ? money(v) : compact(v));
export const popShort = (n) => rollover(n, basePopShort);

/**
 * A translated text with HTML pieces: the text is escaped, then each {key} still in it takes vars[key] as HTML.
 * Call t() with {key: "{key}"} for those placeholders so they survive translation, e.g.
 * fillHtml(t("{mark} compares a share with Poland's.", { mark: "{mark}" }), { mark: "<span>...</span>" }).
 */
export function fillHtml(text, vars) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c])
    .replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? vars[k] : m));
}

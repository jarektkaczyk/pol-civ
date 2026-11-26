// Number formats for the page language (web/js/i18n.js holds the language and the Intl formatters).
import { compact, money, zloty, int, pct, popShort } from "./i18n.js";

export { compact, money, zloty, int, pct, popShort };
// Money is Polish złoty (PLN), written after the number: "3.92T zł" / "3,92 bln zł", "9,178 zł" / "9178 zł".
export const dollars = zloty;

export function yieldValue(y, v) {
  return y.unit === "pln" || y.unit === "usd" ? money(v) : compact(v);
}

export const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Text for the economy markers: the hover tooltip / tap card, the name plate, and the City View "Made here" block.
// Facts and labels are data text (economy.json); t() gives the Polish text in the Polish UI. No source text here: the
// Almanac lists the sources.
import { esc } from "../../format.js";
import { t } from "../../i18n.js";

const muted = (s) => `<span class="muted">${s}</span>`;
const CARD_STUDIOS = 10;
const CARD_NAMES = 8;

/** The name a site shows: its label (a product, translated) or its proper name. */
export const siteName = (it) => (it.label ? t(it.label) : it.name);

const studiosHeading = (n) => t.plural(n, { one: "{n} game studio", other: "{n} game studios" }, { n });
const more = (n) => t.plural(n, { one: "and {n} more", other: "and {n} more" }, { n });
const yearOf = (it) => (it.year ? ` (${esc(String(it.year))})` : "");
const studioLine = (it) => `<b>${esc(it.name)}</b>: ${esc(it.game)}${yearOf(it)}`;

function where(it) {
  return [it.office ? t("{place} office", { place: it.place }) : it.place, it.state].filter(Boolean).join(" \u00b7 ");
}

function siteCard(it) {
  return `<b>${esc(siteName(it))}</b> ${muted(esc(where(it)))}<br>${esc(t(it.fact))}${
    it.year ? `<br>${muted(esc(String(it.year)))}` : ""}`;
}

/** Tooltip / card HTML for one marker. */
export function markerCard(m) {
  const first = m.items[0];
  let body;
  if (m.studios && m.count === 1) {
    body = `<b>${esc(first.name)}</b> ${muted(esc(where(first)))}<br>${esc(t("Best-known game: {game}", { game: first.game }))}${yearOf(first)}`;
  } else if (m.studios) {
    const list = m.items.slice(0, CARD_STUDIOS).map(studioLine);
    if (m.count > CARD_STUDIOS) list.push(muted(esc(more(m.count - CARD_STUDIOS))));
    body = `<b>${esc(studiosHeading(m.count))}</b> ${muted(esc(first.place || ""))}<br>${list.join("<br>")}`;
  } else if (m.cluster) {
    // a town with several sites: the first one in full, then the others by name
    const names = m.items.slice(1, 1 + CARD_NAMES).map((it) => esc(siteName(it)));
    if (m.count - 1 > CARD_NAMES) names.push(esc(more(m.count - 1 - CARD_NAMES)));
    body = `${siteCard(first)}<br><br>${muted(esc(t("Also here:")))} ${names.join(", ")}`;
  } else {
    body = siteCard(first);
  }
  return `<div class="econ-card">${body}</div>`;
}

/** The plate under a marker (close in), or "" for a town cluster (its count badge says enough). */
export function plateText(m) {
  if (m.studios) return m.count === 1 ? m.items[0].name : studiosHeading(m.count);
  return m.cluster ? "" : siteName(m.items[0]);
}

/** The City View block: the sites and studios in the town's gmina, or "" when there are none. */
export function madeHereHtml(doc, cityId) {
  const items = (doc?.items || []).filter((it) => it.county === cityId);
  if (!items.length) return "";
  const studios = items.filter((it) => it.kind === "studio" && !it.fact);
  const sites = items.filter((it) => !studios.includes(it));
  // the year in brackets only when the fact does not already say it
  const rows = sites.map((it) => {
    const fact = t(it.fact);
    const year = it.year && !fact.includes(String(it.year)) ? ` ${muted(`(${esc(String(it.year))})`)}` : "";
    return `<li><b>${esc(siteName(it))}</b><br>${esc(fact)}${year}</li>`;
  });
  if (studios.length) {
    const names = studios.slice(0, 6).map((it) => `${esc(it.name)} (${esc(it.game)})`);
    if (studios.length > 6) names.push(esc(more(studios.length - 6)));
    rows.push(`<li><b>${esc(studiosHeading(studios.length))}</b><br>${names.join(", ")}</li>`);
  }
  return `<h4 class="cv-h4">${esc(t("Made here"))}</h4><ul class="econ-made">${rows.join("")}</ul>`;
}

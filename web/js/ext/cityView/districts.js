// City View "Districts": the town's real industry specialisation (districts.json, location quotients of PKD
// sections per powiat) as strategy-game districts, plus the Encampment tier from military.json when it has one.
//
//   cityDistricts(ddata, mil, id) -> [district]  the town's districts, strongest first, each with what the dock and
//                                                the map plaques need ({id, name, short, color, icon, lq, emp, ...})
//   badgeOf(ddata, id) -> {label, text, color, icon, district} | null | undefined   the city-type badge
//   districtsHtml(m, ddata, mil) -> HTML         the section body
//   badgeHtml(m, ddata) -> HTML                  the header badge
import { dollars, esc, int, pct } from "../../format.js";
import { t, num } from "../../i18n.js";
import { compact, fillHtml } from "./fmt.js";
import { icon } from "../../ui/icon.js";
import { hasIcon } from "../../icons.js";

// Icons the district catalog names (d-*) are not drawn yet; until they are, a near icon from the set stands in,
// and canvas plaques without any icon get the letter in `mark`.
const FALLBACK = {
  campus: ["y-science", "\u{1f393}"], commercial_hub: ["i-finance", "\u{1f4b0}"], industrial_zone: ["i-manufacturing", "\u{1f3ed}"],
  harbor: ["i-transportation", "\u2693"], theater_square: ["i-arts", "\u{1f3ad}"], entertainment_complex: ["i-accommodation", "\u{1f3a1}"],
  aerodrome: ["i-transportation", "\u2708\ufe0f"], government_plaza: ["i-public_admin", "\u{1f3db}"], encampment: [null, "\u26fa"],
  aqueduct: ["i-utilities", "\u{1f4a7}"],
};
const SHORT = {
  campus: t("Campus"), commercial_hub: t("Commerce"), industrial_zone: t("Industry"), harbor: t("Harbor"), theater_square: t("Theater"),
  entertainment_complex: t("Leisure"), aerodrome: t("Aerodrome"), government_plaza: t("Gov. plaza"), encampment: t("Encampment"),
  aqueduct: t("Aqueduct"),
};
const TIER = { garrison: t("Garrison"), fortress: t("Fortress") };
const tr = (s) => (s ? t(s) : s);

const catCache = new WeakMap();
function catalog(ddata) {
  let m = catCache.get(ddata);
  if (!m) catCache.set(ddata, (m = new Map((ddata?.catalog || []).map((c) => [c.id, c]))));
  return m;
}

export function iconFor(id, cat) {
  if (cat?.icon && hasIcon(cat.icon)) return cat.icon;
  const f = FALLBACK[id]?.[0];
  return f && hasIcon(f) ? f : null;
}

const instCache = new WeakMap();
function installationsById(mil) {
  let m = instCache.get(mil);
  if (!m) instCache.set(mil, (m = new Map((mil?.installations || []).map((i) => [i.id, i]))));
  return m;
}

/**
 * The town's districts: districts.json entries (strongest first), with military.json's Encampment merged in (its
 * tier label; added at the end when only military.json has one).
 */
export function cityDistricts(ddata, mil, id) {
  const cat = catalog(ddata);
  const row = ddata?.cities?.[id] || null;
  const mc = mil?.cities?.[id] || null;
  const out = [];
  for (const d of row?.districts || []) {
    const c = cat.get(d.id) || {};
    const spec = d.via === "specialty" && d.sub;
    out.push({
      ...d, name: tr(c.name) || d.id, color: c.color || "#5a6a7a", icon: iconFor(d.id, c), emoji: FALLBACK[d.id]?.[1] || "\u25c6",
      cat: c, subName: d.sub ? tr(c.sub?.[d.sub]) || tr(ddata.industries?.[d.sub]?.title) || d.sub : null,
      // The map plaque: a speciality-qualified district is labelled by that speciality (its own LQ is the reason).
      short: spec ? tr(c.sub?.[d.sub]) || SHORT[d.id] : SHORT[d.id] || tr(c.name) || d.id,
      mapLq: spec ? d.sub_lq : d.lq,
      military: d.id === "encampment" ? mc : null,
    });
  }
  if (mc && !out.some((d) => d.id === "encampment")) {
    const c = cat.get("encampment") || {};
    out.push({
      id: "encampment", name: tr(c.name) || t("Encampment"), color: c.color || "#8a4a3a", icon: iconFor("encampment", c), emoji: "\u26fa",
      cat: c, lq: null, emp: null, short: TIER[mc.tier] || t("Encampment"), mapLq: null, military: mc, militaryOnly: true,
    });
  }
  for (const d of out) {
    if (d.military) d.tierLabel = TIER[d.military.tier] || d.military.tier;
  }
  return out;
}

/** The city-type badge; undefined while districts.json is loading, null when there is none. */
export function badgeOf(ddata, id) {
  if (!ddata) return ddata; // undefined (loading) or null (missing)
  const row = ddata.cities?.[id];
  if (!row) return null;
  if (!row.badge) return { label: t("Diversified"), text: t("No industry group stands out."), color: "#6a7484", icon: null, district: null };
  const b = row.badge;
  const c = catalog(ddata).get(b.district) || {};
  // label and text in the page language (text from its template when the file has one)
  return { ...b, label: tr(b.label), text: b.tpl ? t(b.tpl, b.vars) : b.text,
    color: c.color || "#6a7484", icon: iconFor(b.district, c), emoji: FALLBACK[b.district]?.[1] };
}

export function badgeHtml(m, ddata) {
  const b = badgeOf(ddata, m.city.id);
  if (!b) return "";
  return `<span class="cv-type${b.district ? "" : " plain"}" style="--tc:${esc(b.color)}" title="${esc(b.text || b.label)}">
    <span class="cv-type-ic">${icon(b.icon, b.emoji || "\u25c6", { size: 13 })}</span>${esc(b.label)}</span>`;
}

const ge = (lb) => (lb ? "\u2265" : "");

function lqTag(lq, lb, tip) {
  if (lq == null) return "";
  const cls = lq >= 1.25 ? "hi" : lq <= 0.75 ? "lo" : "mid";
  return `<span class="cv-lq ${cls}" title="${esc(tip || t("{lq} times Poland's share of workers", { lq: num(lq, 2) }))}">\u00d7${ge(lb)}${num(lq, 1)}</span>`;
}

// Three columns (industry, workers, times Poland), over the stylesheet's five.
const TOP_COLS = "grid-template-columns:minmax(0,1fr) 56px 48px";

const sectionTitle = (ddata, pkd) => tr(ddata?.industries?.[pkd]?.title) || `PKD ${pkd}`;

function districtCard(d, row, ddata, mil) {
  const c = d.cat || {};
  const lb = !!d.lower_bound;
  const supTip = lb ? ` ${t("GUS withholds part of this, so it is a lower bound.")}` : "";
  // A shortened count ("1.2K") takes the plural form of a large number.
  const workers = (n, text) => t.plural(Math.abs(n) >= 1000 ? 1e6 : Math.round(n), { one: "{n} worker", other: "{n} workers" }, { n: text });
  const facts = [];
  if (d.emp != null) {
    facts.push(`<div><span>${esc(t("Workers"))}</span><b>${ge(lb)}${compact(d.emp)}</b><small>${d.share != null ? esc(t("{share} of all", { share: pct(d.share, 1) })) : ""}</small></div>`);
  }
  if (d.strength != null) {
    facts.push(`<div title="${esc(t("Workers above Poland's norm: workers - workers / LQ"))}"><span>${esc(t("Above norm"))}</span><b>${ge(lb)}${compact(Math.max(0, d.strength))}</b><small>${esc(t("workers"))}</small></div>`);
  }
  let spec = "";
  if (d.sub && d.subName) {
    const slb = d.sub_lower_bound ?? !!(row?.top || []).find((x) => x.pkd === d.sub)?.lower_bound;
    const subTip = d.sub_lq == null ? undefined : slb
      ? t("{lq} times Poland's share of workers (a lower bound)", { lq: num(d.sub_lq, 2) })
      : t("{lq} times Poland's share of workers", { lq: num(d.sub_lq, 2) });
    spec = `<p class="cv-dc-sub">${esc(d.via === "specialty" ? t("Qualifies through") : t("Strongest section"))}: <b>${esc(d.subName)}</b> ${lqTag(d.sub_lq, slb, subTip)}${
      d.sub_emp != null ? ` <small>${esc(workers(d.sub_emp, ge(slb) + compact(d.sub_emp)))}</small>` : ""}${
      d.via === "specialty" && d.lq != null ? `<br><small>${esc(t("The district's sections together are {lq} times Poland's share; this section alone passes the rule.", { lq: num(d.lq, 2) }))}</small>` : ""}</p>`;
  }
  let milHtml = "";
  if (d.military) {
    const mc = d.military;
    const inst = installationsById(mil);
    const names = (mc.installations || []).map((i) => inst.get(i)?.name).filter(Boolean);
    const facts2 = [];
    if (mc.armed_forces != null) {
      facts2.push(mc.share != null
        ? t.plural(mc.armed_forces, { one: "{n} soldier, {share} of adults", other: "{n} soldiers, {share} of adults" }, { share: pct(mc.share, mc.share < 0.01 ? 2 : 1) })
        : t.plural(mc.armed_forces, { one: "{n} soldier", other: "{n} soldiers" }));
    }
    milHtml = `<div class="cv-dc-mil">
      <p><b>${esc(d.tierLabel || "")}</b>${mc.naval ? ` ${esc(t("(naval)"))}` : ""}${facts2.length ? `: ${esc(facts2.join(""))}` : ""}.</p>
      ${names.length ? `<p class="cv-dc-inst">${names.slice(0, 5).map((n) => `<span>${esc(n)}</span>`).join("")}${
        mc.installation_count > Math.min(5, names.length) ? `<small>${esc(t("+{n} more", { n: mc.installation_count - Math.min(5, names.length) }))}</small>` : ""}</p>` : ""}
    </div>`;
  }
  const caveat = c.caveat ? `<p class="cv-dc-cav">${esc(t(c.caveat))}</p>` : "";
  const desc = c.description ? t(c.description) : "";
  const title = d.military && d.tierLabel ? `${esc(d.name)} \u00b7 ${esc(d.tierLabel)}` : esc(d.name);
  return `<div class="cv-dc" style="--dc:${esc(d.color)}" title="${esc(desc)}${esc(supTip)}">
    <div class="cv-dc-h"><span class="cv-dc-hex">${icon(d.icon, d.emoji, { size: 18 })}</span>
      <div class="cv-dc-t"><b>${title}</b><small>${esc(desc)}</small></div>
      ${d.lq != null ? lqTag(d.lq, lb, `${t("{lq} times Poland's share of workers in these sections.", { lq: num(d.lq, 2) })}${supTip}`) : ""}</div>
    ${facts.length ? `<div class="cv-dc-f">${facts.join("")}</div>` : ""}
    ${spec}${milHtml}${caveat}
  </div>`;
}

function topTable(row, ddata) {
  const top = row?.top || [];
  if (!top.length) return "";
  const max = Math.max(...top.map((x) => x.lq || 0), 1);
  const heading = t("Most specialised industries");
  return `<h4 class="cv-h4">${esc(heading)}</h4>
  <div class="cv-top" role="table" aria-label="${esc(heading)}">
    <div class="cv-top-r cv-top-hd" role="row" style="${TOP_COLS}"><span role="columnheader">${esc(t("Sector"))}</span><span role="columnheader">${esc(t("Workers"))}</span><span role="columnheader" title="${esc(t("Times Poland's share"))}">\u00d7PL</span></div>
    ${top.map((x) => {
      const title = sectionTitle(ddata, x.pkd);
      const lb = !!x.lower_bound;
      return `<div class="cv-top-r" role="row" style="${TOP_COLS}" title="${esc(title)} (PKD ${esc(x.pkd)})${lb ? `. ${esc(t("A lower bound: GUS withholds part of it."))}` : ""}">
        <span role="cell" class="cv-top-n">${esc(title)}<i style="width:${((Math.log(1 + (x.lq || 0)) / Math.log(1 + max)) * 100).toFixed(1)}%"></i></span>
        <span role="cell">${ge(lb)}${compact(x.emp)}</span>
        <span role="cell"><b>${x.lq != null ? `${ge(lb)}${num(x.lq, 1)}` : "\u2013"}</b></span></div>`;
    }).join("")}
  </div>`;
}

/** The Districts section body. ddata: districts.json (undefined while loading, null when missing). */
export function districtsHtml(m, ddata, mil) {
  if (ddata === undefined) return `<p class="muted cv-note">${esc(t("Loading districts..."))}</p>`;
  if (!ddata) return `<p class="muted cv-note">${esc(t("District data is not available."))}</p>`;
  const c = m.city;
  const row = ddata.cities?.[c.id] || null;
  const list = cityDistricts(ddata, mil, c.id);
  const b = badgeOf(ddata, c.id);
  const plWage = m.nation?.nation?.wage;
  let lead;
  if (!row) {
    lead = `<p class="cv-lead">${esc(t("No district figures for {name}.", { name: c.name }))}</p>`;
  } else {
    const n = int(row.emp);
    const jobs = row.wage == null ? t.plural(row.emp, { one: "{n} worker.", other: "{n} workers." }, { n })
      : plWage == null ? t("{n} workers, average gross wage {wage} a month.", { n, wage: dollars(row.wage) })
        : t("{n} workers, average gross wage {wage} a month (Poland {pl}).", { n, wage: dollars(row.wage), pl: dollars(plWage) });
    lead = `<p class="cv-lead">${b?.district ? `<b class="cv-type-l" style="--tc:${esc(b.color)}">${esc(b.label)}</b> \u00b7 ${esc(b.text || "")}. ` : ""}${esc(jobs)}</p>`;
  }
  // A town without powiat rights: GUS counts workers by section per powiat, so the figures are its powiat's.
  const scope = row?.scope && row.scope !== c.name
    ? `<p class="cv-note cv-scope">${esc(t("{name} has no powiat rights: these figures are for the whole {scope}.", { name: c.name, scope: row.scope }))}</p>` : "";
  const cards = list.length
    ? `<div class="cv-dcs">${list.map((d) => districtCard(d, row, ddata, mil)).join("")}</div>`
    : row ? `<p class="muted cv-note">${esc(t("No district stands out: jobs here are spread much like Poland's."))}</p>` : "";
  return `${lead}
    ${scope}
    ${cards}
    ${topTable(row, ddata)}
    <div class="cv-schematic">
      <p>${fillHtml(t("{onmap} each district stands as a plaque on a hex near the town centre. The positions are schematic: they show what the town specialises in, not where the jobs are.", { onmap: "{onmap}" }), { onmap: `<b>${esc(t("On the map"))}</b>` })}</p>
    </div>`;
}

// City View "Districts": the town's real industry specialisation (districts.json, location quotients of PKD
// sections per powiat) as strategy-game districts, plus the Encampment tier from military.json when it has one.
//
//   cityDistricts(ddata, mil, id) -> [district]  the town's districts, strongest first, each with what the dock and
//                                                the map plaques need ({id, name, short, color, icon, lq, emp, ...})
//   badgeOf(ddata, id) -> {label, text, color, icon, district} | null | undefined   the city-type badge
//   districtsHtml(m, ddata, mil) -> HTML         the section body
//   badgeHtml(m, ddata) -> HTML                  the header badge
import { dollars, esc, int, pct } from "../../format.js";
import { compact } from "./fmt.js";
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
  campus: "Campus", commercial_hub: "Commerce", industrial_zone: "Industry", harbor: "Harbor", theater_square: "Theater",
  entertainment_complex: "Leisure", aerodrome: "Aerodrome", government_plaza: "Gov. plaza", encampment: "Encampment",
  aqueduct: "Aqueduct",
};
const TIER = { garrison: "Garrison", fortress: "Fortress" };

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
      ...d, name: c.name || d.id, color: c.color || "#5a6a7a", icon: iconFor(d.id, c), emoji: FALLBACK[d.id]?.[1] || "\u25c6",
      cat: c, subName: d.sub ? c.sub?.[d.sub] || ddata.industries?.[d.sub]?.title || d.sub : null,
      // The map plaque: a speciality-qualified district is labelled by that speciality (its own LQ is the reason).
      short: spec ? c.sub?.[d.sub] || SHORT[d.id] : SHORT[d.id] || c.name || d.id,
      mapLq: spec ? d.sub_lq : d.lq,
      military: d.id === "encampment" ? mc : null,
    });
  }
  if (mc && !out.some((d) => d.id === "encampment")) {
    const c = cat.get("encampment") || {};
    out.push({
      id: "encampment", name: c.name || "Encampment", color: c.color || "#8a4a3a", icon: iconFor("encampment", c), emoji: "\u26fa",
      cat: c, lq: null, emp: null, short: TIER[mc.tier] || "Encampment", mapLq: null, military: mc, militaryOnly: true,
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
  if (!row.badge) return { label: "Diversified", text: "No industry group stands out.", color: "#6a7484", icon: null, district: null };
  const c = catalog(ddata).get(row.badge.district) || {};
  return { ...row.badge, color: c.color || "#6a7484", icon: iconFor(row.badge.district, c), emoji: FALLBACK[row.badge.district]?.[1] };
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
  return `<span class="cv-lq ${cls}" title="${esc(tip || `${lq.toFixed(2)} times Poland's share of workers`)}">\u00d7${ge(lb)}${lq.toFixed(1)}</span>`;
}

// Three columns (industry, workers, times Poland), over the stylesheet's five.
const TOP_COLS = "grid-template-columns:minmax(0,1fr) 56px 48px";

const sectionTitle = (ddata, pkd) => ddata?.industries?.[pkd]?.title || `PKD ${pkd}`;

function districtCard(d, row, ddata, mil) {
  const c = d.cat || {};
  const lb = !!d.lower_bound;
  const supTip = lb ? " GUS withholds part of this, so it is a lower bound." : "";
  const facts = [];
  if (d.emp != null) {
    facts.push(`<div><span>Workers</span><b>${ge(lb)}${compact(d.emp)}</b><small>${d.share != null ? `${pct(d.share, 1)} of all` : ""}</small></div>`);
  }
  if (d.strength != null) {
    facts.push(`<div title="Workers above Poland's norm: workers - workers / LQ"><span>Above norm</span><b>${ge(lb)}${compact(Math.max(0, d.strength))}</b><small>workers</small></div>`);
  }
  let spec = "";
  if (d.sub && d.subName) {
    const slb = d.sub_lower_bound ?? !!(row?.top || []).find((t) => t.pkd === d.sub)?.lower_bound;
    spec = `<p class="cv-dc-sub">${d.via === "specialty" ? "Qualifies through" : "Strongest section"}: <b>${esc(d.subName)}</b> ${lqTag(d.sub_lq, slb, d.sub_lq != null ? `${d.sub_lq.toFixed(2)} times Poland's share of workers${slb ? " (a lower bound)" : ""}` : undefined)}${
      d.sub_emp != null ? ` <small>${ge(slb)}${compact(d.sub_emp)} workers</small>` : ""}${
      d.via === "specialty" && d.lq != null ? `<br><small>The district's sections together are ${d.lq.toFixed(2)} times Poland's share; this section alone passes the rule.</small>` : ""}</p>`;
  }
  let milHtml = "";
  if (d.military) {
    const mc = d.military;
    const inst = installationsById(mil);
    const names = (mc.installations || []).map((i) => inst.get(i)?.name).filter(Boolean);
    const facts2 = [];
    if (mc.armed_forces != null) facts2.push(`${int(mc.armed_forces)} soldiers${mc.share != null ? `, ${pct(mc.share, mc.share < 0.01 ? 2 : 1)} of adults` : ""}`);
    milHtml = `<div class="cv-dc-mil">
      <p><b>${esc(d.tierLabel || "")}</b>${mc.naval ? " (naval)" : ""}${facts2.length ? `: ${facts2.join("")}` : ""}.</p>
      ${names.length ? `<p class="cv-dc-inst">${names.slice(0, 5).map((n) => `<span>${esc(n)}</span>`).join("")}${
        mc.installation_count > Math.min(5, names.length) ? `<small>+${mc.installation_count - Math.min(5, names.length)} more</small>` : ""}</p>` : ""}
    </div>`;
  }
  const caveat = c.caveat ? `<p class="cv-dc-cav">${esc(c.caveat)}</p>` : "";
  const title = d.military && d.tierLabel ? `${esc(d.name)} \u00b7 ${esc(d.tierLabel)}` : esc(d.name);
  return `<div class="cv-dc" style="--dc:${esc(d.color)}" title="${esc(c.description || "")}${esc(supTip)}">
    <div class="cv-dc-h"><span class="cv-dc-hex">${icon(d.icon, d.emoji, { size: 18 })}</span>
      <div class="cv-dc-t"><b>${title}</b><small>${esc(c.description || "")}</small></div>
      ${d.lq != null ? lqTag(d.lq, lb, `${d.lq.toFixed(2)} times Poland's share of workers in these sections.${supTip}`) : ""}</div>
    ${facts.length ? `<div class="cv-dc-f">${facts.join("")}</div>` : ""}
    ${spec}${milHtml}${caveat}
  </div>`;
}

function topTable(row, ddata) {
  const top = row?.top || [];
  if (!top.length) return "";
  const max = Math.max(...top.map((t) => t.lq || 0), 1);
  return `<h4 class="cv-h4">Most specialised industries</h4>
  <div class="cv-top" role="table" aria-label="Most specialised industries">
    <div class="cv-top-r cv-top-hd" role="row" style="${TOP_COLS}"><span role="columnheader">Industry</span><span role="columnheader">Workers</span><span role="columnheader" title="Times Poland's share">\u00d7PL</span></div>
    ${top.map((t) => {
      const title = sectionTitle(ddata, t.pkd);
      const lb = !!t.lower_bound;
      return `<div class="cv-top-r" role="row" style="${TOP_COLS}" title="${esc(title)} (PKD ${esc(t.pkd)})${lb ? ". A lower bound: GUS withholds part of it." : ""}">
        <span role="cell" class="cv-top-n">${esc(title)}<i style="width:${((Math.log(1 + (t.lq || 0)) / Math.log(1 + max)) * 100).toFixed(1)}%"></i></span>
        <span role="cell">${ge(lb)}${compact(t.emp)}</span>
        <span role="cell"><b>${t.lq != null ? `${ge(lb)}${t.lq.toFixed(1)}` : "\u2013"}</b></span></div>`;
    }).join("")}
  </div>`;
}

/** The Districts section body. ddata: districts.json (undefined while loading, null when missing). */
export function districtsHtml(m, ddata, mil) {
  if (ddata === undefined) return `<p class="muted cv-note">Loading districts...</p>`;
  if (!ddata) return `<p class="muted cv-note">District data is not available.</p>`;
  const c = m.city;
  const row = ddata.cities?.[c.id] || null;
  const list = cityDistricts(ddata, mil, c.id);
  const b = badgeOf(ddata, c.id);
  const plWage = m.nation?.nation?.wage;
  let lead;
  if (!row) {
    lead = `<p class="cv-lead">No district figures for ${esc(c.name)}.</p>`;
  } else {
    lead = `<p class="cv-lead">${b?.district ? `<b class="cv-type-l" style="--tc:${esc(b.color)}">${esc(b.label)}</b> \u00b7 ${esc(b.text || "")}. ` : ""}${
      int(row.emp)} workers${row.wage != null ? `, average gross wage ${dollars(row.wage)} a month${plWage != null ? ` (Poland ${dollars(plWage)})` : ""}` : ""}.</p>`;
  }
  // A town without powiat rights: GUS counts workers by section per powiat, so the figures are its powiat's.
  const scope = row?.scope && row.scope !== c.name
    ? `<p class="cv-note cv-scope">${esc(c.name)} has no powiat rights: these figures are for the whole ${esc(row.scope)}.</p>` : "";
  const cards = list.length
    ? `<div class="cv-dcs">${list.map((d) => districtCard(d, row, ddata, mil)).join("")}</div>`
    : row ? `<p class="muted cv-note">No district stands out: jobs here are spread much like Poland's.</p>` : "";
  return `${lead}
    ${scope}
    ${cards}
    ${topTable(row, ddata)}
    <div class="cv-schematic">
      <p><b>On the map</b> each district stands as a plaque on a hex near the town centre. The positions are schematic: they show what the town specialises in, not where the jobs are.</p>
    </div>`;
}

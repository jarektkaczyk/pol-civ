// City View "Citizens" rows: the town's people as rows of small figures (citizens.json).
//
//   citizensHtml(m, data) -> HTML      the rows (placeholders for the figure canvases)
//   mountCitizens(host, m, data)       paints the figures and wires the hover / focus read-out
//
// Each row: N figures (from the file's `figures`, or rounded here with the same largest-remainder method), a
// caption ("each figure ~ 27K workers"), a read-out line that a hovered or focused figure fills ("1 in 4 workers
// in Krakow works in IT, science or engineering (Poland: 1 in 11)"), and a thin bar with Poland's mix. A row with
// no data says so, never drawn as zeros. Each row describes its own unit (`scope`: the town, its gmina or its
// powiat); the read-out names it.
import { esc, int, pct } from "../../format.js";
import { compact } from "./fmt.js";
import { CATEGORY_COLOR, figureCanvas, loadPainter } from "./figures.js";

// shares: the row's counts are per 1,000 residents (education), so no "about N people" read-out.
const ROWS = [
  { id: "workforce", title: "Workforce", sub: "by sector", noun: ["worker", "workers"], n: null },
  { id: "age", title: "Generations", sub: "by age", noun: ["resident", "residents"], n: null },
  { id: "sex", title: "Women and men", sub: "", noun: ["resident", "residents"], n: null },
  { id: "education", title: "Education", sub: "residents aged 13+", noun: ["resident aged 13+", "residents aged 13+"], n: 10, shares: true },
  { id: "nativity", title: "Origins", sub: "Ukrainians with PESEL UKR status", noun: ["resident", "residents"], n: 10 },
];

// [singular verb phrase, plural verb phrase] per category, for "1 in 4 workers in X works ..." / "7 in 10 ... are ...".
const PHRASE = {
  workforce: {
    farmer: ["works in farming, forestry or fishing", "work in farming, forestry or fishing"],
    maker: ["works in a factory, energy, water or transport", "work in factories, energy, water or transport"],
    builder: ["works in construction", "work in construction"],
    clerk: ["works in trade, finance or an office", "work in trade, finance or offices"],
    engineer: ["works in IT, science or engineering", "work in IT, science or engineering"],
    scholar: ["works in education or the arts", "work in education or the arts"],
    healer: ["works in health or social care", "work in health or social care"],
    service: ["works in hospitality, public service or other services", "work in hospitality, public service or other services"],
  },
  age: {
    child: ["is a child (0-14)", "are children (0-14)"],
    young: ["is a young adult (15-29)", "are young adults (15-29)"],
    midlife: ["is 30 to 64", "are 30 to 64"],
    elder: ["is 65 or older", "are 65 or older"],
  },
  sex: {
    female: ["is a woman", "are women"],
    male: ["is a man", "are men"],
  },
  education: {
    bachelors: ["has higher education", "have higher education"],
    high_school: ["has no higher education", "have no higher education"],
  },
  nativity: {
    foreign_born: ["is a Ukrainian with PESEL UKR status", "are Ukrainians with PESEL UKR status"],
    born_in_state: ["is another resident", "are other residents"],
  },
};

// Short legend labels (the file's labels are long).
const SHORT = {
  workforce: { farmer: "Farming", maker: "Industry & transport", builder: "Construction", clerk: "Trade & offices",
    engineer: "IT & science", scholar: "Education & arts", healer: "Health", service: "Hospitality & public" },
  age: { child: "0-14", young: "15-29", midlife: "30-64", elder: "65+" },
  sex: { female: "Women", male: "Men" },
  education: { bachelors: "Higher education", high_school: "No higher education" },
  nativity: { foreign_born: "Ukrainians", born_in_state: "Other residents" },
};

const DASH = "\u2013";
const TIMES = "\u00d7";

/** Largest-remainder rounding of counts into n figures (the pipeline's method, for rows without figures). */
export function largestRemainder(counts, keys, n) {
  const tot = keys.reduce((a, k) => a + (counts[k] || 0), 0);
  if (!(tot > 0)) return null;
  const raw = keys.map((k) => ((counts[k] || 0) / tot) * n);
  const out = raw.map(Math.floor);
  let left = n - out.reduce((a, v) => a + v, 0);
  const order = raw.map((v, j) => [v - Math.floor(v), j]).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  for (let k = 0; k < left; k++) out[order[k][1]]++;
  return Object.fromEntries(keys.map((k, j) => [k, out[j]]));
}

/** "1 in 7", "3 in 10", "fewer than 1 in 1,000". */
export function oneIn(share) {
  if (share == null || !Number.isFinite(share)) return null;
  if (share <= 0) return { text: "none", plural: true };
  if (share < 0.001) return { text: "fewer than 1 in 1,000", plural: false };
  if (share >= 0.3) {
    const k = Math.round(share * 10);
    return k >= 10 ? { text: "nearly all", plural: true } : { text: `${k} in 10`, plural: k !== 1 };
  }
  const n = Math.round(1 / share);
  return { text: `1 in ${int(n)}`, plural: false };
}

function sentence(rowId, key, share, natShare, place, noun) {
  const a = oneIn(share);
  if (!a) return "";
  const ph = PHRASE[rowId]?.[key] || ["is in this group", "are in this group"];
  const pl = oneIn(natShare);
  const lead = a.text.charAt(0).toUpperCase() + a.text.slice(1);
  return `${lead} ${noun[1]} in ${place} ${a.plural ? ph[1] : ph[0]}${pl ? ` (Poland: ${pl.text})` : ""}`;
}

function rowModel(rowDef, row, nat, groups, figuresN) {
  const keys = (groups[rowDef.id] || []).map((g) => g.key);
  const n = figuresN[rowDef.id] ?? rowDef.n ?? 10;
  const figs = row.figures || largestRemainder(row.counts || {}, keys, n);
  const natFigs = nat?.figures || (nat ? largestRemainder(nat.counts || {}, keys, n) : null);
  return { keys, n, figs, natFigs };
}

// Specialists by row/key from the file (ratios from unrounded shares).
function specMap(city) {
  const m = new Map();
  for (const s of city?.specialists || []) m.set(`${s.row}|${s.key}`, s);
  return m;
}

// The unit a row describes, when it is not the town itself ("powiat bochenski").
function scopeOf(row, city) {
  const s = row?.scope;
  return s && s !== city.name ? s : null;
}

/** The Citizens rows. data = citizens.json (or null / undefined while loading). */
export function citizensHtml(m, data) {
  const c = m.city;
  if (data === undefined) return `<p class="muted cv-note">Loading the citizen mix...</p>`;
  if (!data || !data.cities) return `<p class="muted cv-note">The citizen mix is not available.</p>`;
  const row0 = data.cities[c.id];
  if (!row0) return `<p class="muted cv-note">No citizen figures for ${esc(c.name)}.</p>`;
  const nat = data.national || {};
  const groups = data.groups || {};
  const specs = specMap(row0);
  const label = Object.fromEntries(Object.entries(groups).map(([r, gs]) => [r, Object.fromEntries(gs.map((g) => [g.key, g.label]))]));
  const hi = data.rule?.specialist_high ?? 1.5, lo = data.rule?.specialist_low ?? 0.67;

  // Headline: median age, higher education, Ukrainians, and the "great person" call-out (the strongest specialist).
  const med = row0.age?.median, plMed = nat.age?.median;
  const ba = row0.education?.bachelors_plus, plBa = nat.education?.bachelors_plus;
  const fb = row0.nativity?.foreign_born ?? row0.nativity?.shares?.foreign_born;
  const plFb = nat.nativity?.foreign_born ?? nat.nativity?.shares?.foreign_born;
  const chip = (v, pl, fmt, lbl, tip) => (v == null ? "" : `<div class="cv-cz-chip" title="${esc(tip)}"><b>${fmt(v)}</b><span>${esc(lbl)}</span>${pl != null ? `<small>Poland ${fmt(pl)}</small>` : ""}</div>`);
  const top = (row0.specialists || []).find((s) => s.ratio >= hi);
  const topRow = ROWS.find((r) => r.id === top?.row);
  const topPlace = top ? scopeOf(row0[top.row], c) : null;
  const great = top && topRow ? `<div class="cv-great" style="--fc:${esc(CATEGORY_COLOR[top.row]?.[top.key] || "#c9a45c")}">
      <span class="cv-great-fig" data-great="${esc(top.row)}|${esc(top.key)}" aria-hidden="true"></span>
      <div><small>Standout citizens</small><b>${esc(label[top.row]?.[top.key] || top.key)}</b>
      <span>${pct(top.share, 1)} of ${esc(topRow.noun[1])}${topPlace ? ` in ${esc(topPlace)}` : " here"}, ${pct(top.national, 1)} in Poland: ${top.ratio.toFixed(1)} times Poland's share.</span></div></div>` : "";

  const rows = ROWS.map((rd) => {
    const row = row0[rd.id];
    const scope = scopeOf(row, c);
    const sub = [rd.sub, scope].filter(Boolean).join(" \u00b7 ");
    const head = `<div class="cv-cz-h"><b>${esc(rd.title)}</b>${sub ? `<span>${esc(sub)}</span>` : ""}</div>`;
    if (!row) {
      return `<div class="cv-cz-row missing" data-row="${rd.id}">${head}
        <p class="muted cv-note">No ${esc(rd.title.toLowerCase())} figures for ${esc(c.name)}.</p></div>`;
    }
    const { keys, n, figs } = rowModel(rd, row, nat[rd.id], groups, data.figures || {});
    if (!figs) return `<div class="cv-cz-row missing" data-row="${rd.id}">${head}<p class="muted cv-note">No ${esc(rd.title.toLowerCase())} figures for ${esc(c.name)}.</p></div>`;
    const per = row.total / n;
    const cells = [];
    for (const k of keys) {
      for (let j = 0; j < (figs[k] || 0); j++) {
        const sp = specs.get(`${rd.id}|${k}`);
        const mark = sp ? (sp.ratio >= 1 ? "up" : "down") : "";
        // One tab stop per category (its first figure), not one per figure.
        cells.push(`<span class="cv-fig${mark ? ` ${mark}` : ""}" tabindex="${j ? -1 : 0}" role="img" data-k="${esc(k)}" aria-label="${esc(label[rd.id]?.[k] || k)}"></span>`);
      }
    }
    // Legend: every category, with its share, Poland's share and a chevron for specialists. Categories that round
    // to no figure are still listed (greyed), so nothing silently disappears.
    const plShares = nat[rd.id]?.shares || null;
    const legend = keys.map((k) => {
      const sh = row.shares?.[k], pl = plShares?.[k];
      const sp = specs.get(`${rd.id}|${k}`);
      const chev = sp ? `<em class="${sp.ratio >= 1 ? "up" : "down"}" title="${sp.ratio.toFixed(1)} times Poland's share">${sp.ratio >= 1 ? "\u25b2" : "\u25bc"}</em>` : "";
      return `<span class="cv-cz-k${figs[k] ? "" : " zero"}" data-k="${esc(k)}" title="${esc(label[rd.id]?.[k] || k)}: ${sh != null ? pct(sh, 1) : DASH}${pl != null ? ` (Poland ${pct(pl, 1)})` : ""}${figs[k] ? "" : ". Rounds to no figure."}"><i style="background:${esc(CATEGORY_COLOR[rd.id]?.[k] || "#888")}"></i>${esc(SHORT[rd.id]?.[k] || label[rd.id]?.[k] || k)} <small>${sh != null ? pct(sh, 0) : DASH}</small>${chev}</span>`;
    }).join("");
    // Poland's mix (shares), aligned with the figures' order; none when the file has no national row.
    const plBar = plShares ? `<div class="cv-cz-us" title="Poland, same order"><span>PL</span><div>${keys.map((k) => {
      const v = plShares[k] || 0;
      return v > 0 ? `<i style="flex:${v};background:${esc(CATEGORY_COLOR[rd.id]?.[k] || "#888")}" title="${esc(SHORT[rd.id]?.[k] || k)}: ${pct(v, 1)} in Poland"></i>` : "";
    }).join("")}</div></div>` : "";
    const cap = rd.shares
      ? `Each figure = ${Math.round(100 / n)}% of ${rd.noun[1]}`
      : `Each figure \u2248 ${compact(per)} ${rd.noun[1]} \u00b7 ${compact(row.total)} in all`;
    const extra = rd.id === "age" && med != null ? ` \u00b7 median age ${med.toFixed(1)}${plMed != null ? ` (Poland ${plMed.toFixed(1)})` : ""}` : "";
    return `<div class="cv-cz-row" data-row="${rd.id}" style="--n:${n}">${head}
      <div class="cv-figs" role="group" aria-label="${esc(rd.title)}: ${keys.filter((k) => figs[k]).map((k) => `${figs[k]} of ${n} ${SHORT[rd.id]?.[k] || k}`).join(", ")}">${cells.join("")}</div>
      ${plBar}
      <div class="cv-cz-out" aria-live="polite" data-default="${esc(cap + extra)}">${esc(cap + extra)}</div>
      <div class="cv-cz-legend">${legend}</div>
    </div>`;
  }).join("");

  const unreliable = row0.reliable === false
    ? `<p class="cv-warn">Small numbers here: read these figures as rough.</p>` : "";
  return `
    <div class="cv-cz-top">
      ${chip(med, plMed, (v) => v.toFixed(1), "median age", "Median age of residents")}
      ${chip(ba, plBa, (v) => pct(v, 0), "higher education", "Residents aged 13+ with higher education")}
      ${chip(fb, plFb, (v) => pct(v, 1), "Ukrainians", "Ukrainians with PESEL UKR status, share of residents")}
    </div>
    ${great}
    ${unreliable}
    <div class="cv-cz${row0.reliable === false ? " unreliable" : ""}">${rows}</div>
    <p class="cv-note">\u25b2\u25bc = at least ${hi} times or at most ${lo} times Poland's share.</p>`;
}

/** Paint the figure canvases and wire the read-outs. */
export function mountCitizens(host, m, data) {
  if (!host || !data?.cities?.[m.city.id]) return;
  const row0 = data.cities[m.city.id];
  const nat = data.national || {};
  const dpr = Math.min(3, Math.max(1, Math.round((devicePixelRatio || 1) * 2) / 2));
  const paintAll = () => {
    host.querySelectorAll(".cv-cz-row[data-row]").forEach((rowEl) => {
      const rid = rowEl.dataset.row;
      rowEl.querySelectorAll(".cv-fig").forEach((el) => {
        const src = figureCanvas(rid, el.dataset.k, 36, dpr);
        const cv = document.createElement("canvas");
        cv.width = src.width;
        cv.height = src.height;
        cv.getContext("2d").drawImage(src, 0, 0);
        el.replaceChildren(cv);
      });
    });
    const g = host.querySelector("[data-great]");
    if (g) {
      const [rid, k] = g.dataset.great.split("|");
      const src = figureCanvas(rid, k, 36, dpr);
      const cv = document.createElement("canvas");
      cv.width = src.width;
      cv.height = src.height;
      cv.getContext("2d").drawImage(src, 0, 0);
      g.replaceChildren(cv);
    }
  };
  paintAll();
  // Once the citizen painter (render/art/people.js) loads, repaint the figures.
  loadPainter().then(() => { if (host.isConnected) paintAll(); });

  host.querySelectorAll(".cv-cz-row[data-row]").forEach((rowEl) => {
    const rid = rowEl.dataset.row;
    const rd = ROWS.find((r) => r.id === rid);
    const row = row0[rid];
    const out = rowEl.querySelector(".cv-cz-out");
    if (!row || !out) return;
    const show = (k) => {
      rowEl.querySelectorAll("[data-k]").forEach((el) => el.classList.toggle("lit", el.dataset.k === k));
      rowEl.classList.toggle("focus", !!k);
      if (!k) {
        out.textContent = out.dataset.default;
        out.classList.remove("on");
        return;
      }
      const sh = row.shares?.[k], pl = nat[rid]?.shares?.[k];
      const people = !rd.shares && row.counts?.[k] != null ? ` \u00b7 \u2248${compact(row.counts[k])} ${rd.noun[1]}` : "";
      out.innerHTML = `${esc(sentence(rid, k, sh, pl, row.scope || m.city.name, rd.noun))}<small>${sh != null ? pct(sh, 1) : DASH} here${pl != null ? ` \u00b7 ${pct(pl, 1)} in Poland` : ""}${people}</small>`;
      out.classList.add("on");
    };
    let pinned = null;
    rowEl.addEventListener("pointerover", (e) => {
      const el = e.target.closest("[data-k]");
      if (el && rowEl.contains(el)) show(el.dataset.k);
    });
    rowEl.addEventListener("pointerleave", () => show(pinned));
    rowEl.addEventListener("focusin", (e) => {
      const el = e.target.closest("[data-k]");
      if (el) show(el.dataset.k);
    });
    rowEl.addEventListener("focusout", () => show(pinned));
    // A tap pins the category (phones have no hover); another tap on it lets go.
    rowEl.addEventListener("click", (e) => {
      const el = e.target.closest("[data-k]");
      if (!el) return;
      pinned = pinned === el.dataset.k ? null : el.dataset.k;
      show(pinned);
    });
  });
}

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
import { esc, pct } from "../../format.js";
import { t, num } from "../../i18n.js";
import { compact } from "./fmt.js";
import { CATEGORY_COLOR, figureCanvas, loadPainter } from "./figures.js";

// shares: the row's counts are per 1,000 residents (education), so no "about N people" read-out.
// Each row's own sentences (its noun differs by language): cap / capShare = the caption, people = the read-out's
// count, great = the standout line, none = the no-data note.
const ROWS = [
  { id: "workforce", title: t("Workforce"), sub: t("by sector"), n: null,
    cap: (v) => t("Each figure \u2248 {per} workers \u00b7 {total} in all", v),
    people: (n) => t("\u2248{n} workers", { n }),
    great: (v) => (v.place ? t("{share} of workers in {place}, {pl} in Poland: {ratio} times Poland's share.", v)
      : t("{share} of workers here, {pl} in Poland: {ratio} times Poland's share.", v)),
    none: (name) => t("No workforce figures for {name}.", { name }) },
  { id: "age", title: t("Generations"), sub: t("by age"), n: null,
    cap: (v) => t("Each figure \u2248 {per} residents \u00b7 {total} in all", v),
    people: (n) => t("\u2248{n} residents", { n }),
    great: (v) => (v.place ? t("{share} of residents in {place}, {pl} in Poland: {ratio} times Poland's share.", v)
      : t("{share} of residents here, {pl} in Poland: {ratio} times Poland's share.", v)),
    none: (name) => t("No generations figures for {name}.", { name }) },
  { id: "sex", title: t("Women and men"), sub: "", n: null,
    cap: (v) => t("Each figure \u2248 {per} residents \u00b7 {total} in all", v),
    people: (n) => t("\u2248{n} residents", { n }),
    great: (v) => (v.place ? t("{share} of residents in {place}, {pl} in Poland: {ratio} times Poland's share.", v)
      : t("{share} of residents here, {pl} in Poland: {ratio} times Poland's share.", v)),
    none: (name) => t("No women and men figures for {name}.", { name }) },
  { id: "education", title: t("Education"), sub: t("residents aged 13+"), n: 10, shares: true,
    capShare: (v) => t("Each figure = {pct}% of residents aged 13+", v),
    great: (v) => (v.place ? t("{share} of residents aged 13+ in {place}, {pl} in Poland: {ratio} times Poland's share.", v)
      : t("{share} of residents aged 13+ here, {pl} in Poland: {ratio} times Poland's share.", v)),
    none: (name) => t("No education figures for {name}.", { name }) },
  { id: "nativity", title: t("Origins"), sub: t("Ukrainians with PESEL UKR status"), n: 10,
    cap: (v) => t("Each figure \u2248 {per} residents \u00b7 {total} in all", v),
    people: (n) => t("\u2248{n} residents", { n }),
    great: (v) => (v.place ? t("{share} of residents in {place}, {pl} in Poland: {ratio} times Poland's share.", v)
      : t("{share} of residents here, {pl} in Poland: {ratio} times Poland's share.", v)),
    none: (name) => t("No origins figures for {name}.", { name }) },
];

// The read-out sentence per category, [singular verb, plural verb] ("1 in 4 workers in X works ..." / "3 in 10 ...
// work ..."), with {share} ("1 in 4") and {place}. One key per sentence, so each language words it its own way.
const PHRASE = {
  workforce: {
    farmer: [(v) => t("{share} workers in {place} works in farming, forestry or fishing", v), (v) => t("{share} workers in {place} work in farming, forestry or fishing", v)],
    maker: [(v) => t("{share} workers in {place} works in a factory, energy, water or transport", v), (v) => t("{share} workers in {place} work in factories, energy, water or transport", v)],
    builder: [(v) => t("{share} workers in {place} works in construction", v), (v) => t("{share} workers in {place} work in construction", v)],
    clerk: [(v) => t("{share} workers in {place} works in trade, finance or an office", v), (v) => t("{share} workers in {place} work in trade, finance or offices", v)],
    engineer: [(v) => t("{share} workers in {place} works in IT, science or engineering", v), (v) => t("{share} workers in {place} work in IT, science or engineering", v)],
    scholar: [(v) => t("{share} workers in {place} works in education or the arts", v), (v) => t("{share} workers in {place} work in education or the arts", v)],
    healer: [(v) => t("{share} workers in {place} works in health or social care", v), (v) => t("{share} workers in {place} work in health or social care", v)],
    service: [(v) => t("{share} workers in {place} works in hospitality, public service or other services", v), (v) => t("{share} workers in {place} work in hospitality, public service or other services", v)],
  },
  age: {
    child: [(v) => t("{share} residents in {place} is a child (0-14)", v), (v) => t("{share} residents in {place} are children (0-14)", v)],
    young: [(v) => t("{share} residents in {place} is a young adult (15-29)", v), (v) => t("{share} residents in {place} are young adults (15-29)", v)],
    midlife: [(v) => t("{share} residents in {place} is 30 to 64", v), (v) => t("{share} residents in {place} are 30 to 64", v)],
    elder: [(v) => t("{share} residents in {place} is 65 or older", v), (v) => t("{share} residents in {place} are 65 or older", v)],
  },
  sex: {
    female: [(v) => t("{share} residents in {place} is a woman", v), (v) => t("{share} residents in {place} are women", v)],
    male: [(v) => t("{share} residents in {place} is a man", v), (v) => t("{share} residents in {place} are men", v)],
  },
  education: {
    bachelors: [(v) => t("{share} residents aged 13+ in {place} has higher education", v), (v) => t("{share} residents aged 13+ in {place} have higher education", v)],
    high_school: [(v) => t("{share} residents aged 13+ in {place} has no higher education", v), (v) => t("{share} residents aged 13+ in {place} have no higher education", v)],
  },
  nativity: {
    foreign_born: [(v) => t("{share} residents in {place} is a Ukrainian with PESEL UKR status", v), (v) => t("{share} residents in {place} are Ukrainians with PESEL UKR status", v)],
    born_in_state: [(v) => t("{share} residents in {place} is another resident", v), (v) => t("{share} residents in {place} are other residents", v)],
  },
};

// Short legend labels (the file's labels are long).
const SHORT = {
  workforce: { farmer: t("Farming"), maker: t("Industry & transport"), builder: t("Construction"), clerk: t("Trade & offices"),
    engineer: t("IT & science"), scholar: t("Education & arts"), healer: t("Health"), service: t("Hospitality & public") },
  age: { child: "0-14", young: "15-29", midlife: "30-64", elder: "65+" },
  sex: { female: t("Women"), male: t("Men") },
  education: { bachelors: t("Higher education"), high_school: t("No higher education") },
  nativity: { foreign_born: t("Ukrainians"), born_in_state: t("Other residents") },
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
  if (share <= 0) return { text: t("none"), plural: true };
  if (share < 0.001) return { text: t("fewer than 1 in 1,000"), plural: false };
  if (share >= 0.3) {
    const k = Math.round(share * 10);
    return k >= 10 ? { text: t("nearly all"), plural: true } : { text: t("{k} in 10", { k }), plural: k !== 1 };
  }
  const n = Math.round(1 / share);
  return { text: t("1 in {n}", { n }), plural: false };
}

function sentence(rowId, key, share, natShare, place) {
  const a = oneIn(share);
  if (!a) return "";
  const ph = PHRASE[rowId]?.[key];
  if (!ph) return "";
  const pl = oneIn(natShare);
  let text = ph[a.plural ? 1 : 0]({ share: a.text, place });
  text = text.charAt(0).toUpperCase() + text.slice(1);
  return pl ? t("{text} (Poland: {share})", { text, share: pl.text }) : text;
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
  if (data === undefined) return `<p class="muted cv-note">${esc(t("Loading the citizen mix..."))}</p>`;
  if (!data || !data.cities) return `<p class="muted cv-note">${esc(t("The citizen mix is not available."))}</p>`;
  const row0 = data.cities[c.id];
  if (!row0) return `<p class="muted cv-note">${esc(t("No citizen figures for {name}.", { name: c.name }))}</p>`;
  const nat = data.national || {};
  const groups = data.groups || {};
  const specs = specMap(row0);
  const label = Object.fromEntries(Object.entries(groups).map(([r, gs]) => [r, Object.fromEntries(gs.map((g) => [g.key, t(g.label)]))]));
  const hi = data.rule?.specialist_high ?? 1.5, lo = data.rule?.specialist_low ?? 0.67;

  // Headline: median age, higher education, Ukrainians, and the "great person" call-out (the strongest specialist).
  const med = row0.age?.median, plMed = nat.age?.median;
  const ba = row0.education?.bachelors_plus, plBa = nat.education?.bachelors_plus;
  const fb = row0.nativity?.foreign_born ?? row0.nativity?.shares?.foreign_born;
  const plFb = nat.nativity?.foreign_born ?? nat.nativity?.shares?.foreign_born;
  const chip = (v, pl, fmt, lbl, tip) => (v == null ? "" : `<div class="cv-cz-chip" title="${esc(tip)}"><b>${fmt(v)}</b><span>${esc(lbl)}</span>${pl != null ? `<small>${esc(t("Poland {value}", { value: fmt(pl) }))}</small>` : ""}</div>`);
  const top = (row0.specialists || []).find((s) => s.ratio >= hi);
  const topRow = ROWS.find((r) => r.id === top?.row);
  const topPlace = top ? scopeOf(row0[top.row], c) : null;
  const great = top && topRow ? `<div class="cv-great" style="--fc:${esc(CATEGORY_COLOR[top.row]?.[top.key] || "#c9a45c")}">
      <span class="cv-great-fig" data-great="${esc(top.row)}|${esc(top.key)}" aria-hidden="true"></span>
      <div><small>${esc(t("Standout citizens"))}</small><b>${esc(label[top.row]?.[top.key] || top.key)}</b>
      <span>${esc(topRow.great({ share: pct(top.share, 1), place: topPlace, pl: pct(top.national, 1), ratio: num(top.ratio, 1) }))}</span></div></div>` : "";

  const rows = ROWS.map((rd) => {
    const row = row0[rd.id];
    const scope = scopeOf(row, c);
    const sub = [rd.sub, scope].filter(Boolean).join(" \u00b7 ");
    const head = `<div class="cv-cz-h"><b>${esc(rd.title)}</b>${sub ? `<span>${esc(sub)}</span>` : ""}</div>`;
    if (!row) {
      return `<div class="cv-cz-row missing" data-row="${rd.id}">${head}
        <p class="muted cv-note">${esc(rd.none(c.name))}</p></div>`;
    }
    const { keys, n, figs } = rowModel(rd, row, nat[rd.id], groups, data.figures || {});
    if (!figs) return `<div class="cv-cz-row missing" data-row="${rd.id}">${head}<p class="muted cv-note">${esc(rd.none(c.name))}</p></div>`;
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
      const chev = sp ? `<em class="${sp.ratio >= 1 ? "up" : "down"}" title="${esc(t("{ratio} times Poland's share", { ratio: num(sp.ratio, 1) }))}">${sp.ratio >= 1 ? "\u25b2" : "\u25bc"}</em>` : "";
      let tip = `${label[rd.id]?.[k] || k}: ${sh != null ? pct(sh, 1) : DASH}`;
      if (pl != null) tip = t("{text} (Poland {share})", { text: tip, share: pct(pl, 1) });
      if (!figs[k]) tip = t("{text}. Rounds to no figure.", { text: tip });
      return `<span class="cv-cz-k${figs[k] ? "" : " zero"}" data-k="${esc(k)}" title="${esc(tip)}"><i style="background:${esc(CATEGORY_COLOR[rd.id]?.[k] || "#888")}"></i>${esc(SHORT[rd.id]?.[k] || label[rd.id]?.[k] || k)} <small>${sh != null ? pct(sh, 0) : DASH}</small>${chev}</span>`;
    }).join("");
    // Poland's mix (shares), aligned with the figures' order; none when the file has no national row.
    const plBar = plShares ? `<div class="cv-cz-us" title="${esc(t("Poland, same order"))}"><span>PL</span><div>${keys.map((k) => {
      const v = plShares[k] || 0;
      return v > 0 ? `<i style="flex:${v};background:${esc(CATEGORY_COLOR[rd.id]?.[k] || "#888")}" title="${esc(t("{label}: {share} in Poland", { label: SHORT[rd.id]?.[k] || k, share: pct(v, 1) }))}"></i>` : "";
    }).join("")}</div></div>` : "";
    const cap = rd.shares
      ? rd.capShare({ pct: Math.round(100 / n) })
      : rd.cap({ per: compact(per), total: compact(row.total) });
    const extra = rd.id === "age" && med != null ? ` \u00b7 ${plMed != null
      ? t("median age {age} (Poland {pl})", { age: num(med, 1), pl: num(plMed, 1) })
      : t("median age {age}", { age: num(med, 1) })}` : "";
    return `<div class="cv-cz-row" data-row="${rd.id}" style="--n:${n}">${head}
      <div class="cv-figs" role="group" aria-label="${esc(rd.title)}: ${esc(keys.filter((k) => figs[k]).map((k) => t("{n} of {total} {label}", { n: figs[k], total: n, label: SHORT[rd.id]?.[k] || k })).join(", "))}">${cells.join("")}</div>
      ${plBar}
      <div class="cv-cz-out" aria-live="polite" data-default="${esc(cap + extra)}">${esc(cap + extra)}</div>
      <div class="cv-cz-legend">${legend}</div>
    </div>`;
  }).join("");

  const unreliable = row0.reliable === false
    ? `<p class="cv-warn">${esc(t("Small numbers here: read these figures as rough."))}</p>` : "";
  return `
    <div class="cv-cz-top">
      ${chip(med, plMed, (v) => num(v, 1), t("median age"), t("Median age of residents"))}
      ${chip(ba, plBa, (v) => pct(v, 0), t("higher education"), t("Residents aged 13+ with higher education"))}
      ${chip(fb, plFb, (v) => pct(v, 1), t("Ukrainians"), t("Ukrainians with PESEL UKR status, share of residents"))}
    </div>
    ${great}
    ${unreliable}
    <div class="cv-cz${row0.reliable === false ? " unreliable" : ""}">${rows}</div>
    <p class="cv-note">${esc(t("\u25b2\u25bc = at least {hi} times or at most {lo} times Poland's share.", { hi: num(hi, 2, { trim: true }), lo: num(lo, 2, { trim: true }) }))}</p>`;
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
      const parts = [t("{share} here", { share: sh != null ? pct(sh, 1) : DASH })];
      if (pl != null) parts.push(t("{share} in Poland", { share: pct(pl, 1) }));
      if (!rd.shares && row.counts?.[k] != null) parts.push(rd.people(compact(row.counts[k])));
      out.innerHTML = `${esc(sentence(rid, k, sh, pl, row.scope || m.city.name))}<small>${esc(parts.join(" \u00b7 "))}</small>`;
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

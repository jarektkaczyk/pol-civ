// The city screen: a docked dashboard (a bottom sheet on phones) with the header (and its city-type badge),
// Citizens (figure rows from citizens.json), Districts (districts.json), Economy, Workforce, Resources and Compare.
// Plain HTML strings + inline SVG charts; render(el, model, handlers) fills `el`. The citizens and districts files
// load on demand (h.loadData) and fill their sections when they arrive.
import { dollars, esc, int, pct } from "../../format.js";
import { compact, money, popShort, yieldValue } from "./fmt.js";
import { icon, glyph } from "../../ui/icon.js";
import { css } from "../../color.js";
import { isCapital } from "../../world.js";
import { sparkline, meter, bar } from "./charts.js";
import { popSeries, rankCount, resourceValue, LAND } from "./model.js";
import { citizensHtml, mountCitizens } from "./citizens.js";
import { badgeHtml, cityDistricts, districtsHtml } from "./districts.js";

const TABS = [
  ["citizens", "Citizens", "pop"],
  ["districts", "Districts", "l-developed"],
  ["economy", "Economy", "y-gold"],
  ["workforce", "Workforce", "y-production"],
  ["resources", "Resources", "resources"],
  ["compare", "Compare", "layers"],
];

const MINUS = "\u2212";
const DASH = "\u2013";
const signed = (g, d = 1) => (g == null ? DASH : `${g >= 0 ? "+" : MINUS}${Math.abs(g * 100).toFixed(d)}%`);
const rankCache = new WeakMap();
function countOf(cities, key) {
  let m = rankCache.get(cities);
  if (!m) rankCache.set(cities, (m = new Map()));
  if (!m.has(key)) m.set(key, rankCount(cities, key));
  return m.get(key);
}

/** The powiat label of a town without powiat rights ("powiat bochenski"), from cities.json `full`; else null. */
export function powiatOf(c) {
  if (c.kind === "city") return null;
  const part = String(c.full || "").split(", ")[1] || "";
  return /^powiat /.test(part) ? part : null;
}

function rankBadge(rank, of, label, tip) {
  if (rank == null) return "";
  const tier = rank <= 10 ? "gold" : rank <= 50 ? "silver" : "bronze";
  return `<div class="cv-rank ${tier}" title="${esc(tip || `${label}: #${rank} of ${of} towns (1 = highest)`)}">
    <span class="cv-medal">#${rank}</span><span class="cv-rank-l">${esc(label)}</span></div>`;
}

function lqBadge(lq) {
  if (lq == null) return "";
  const tip = `This share is ${lq.toFixed(2)} times Poland's share`;
  const cls = lq >= 1.25 ? "hi" : lq <= 0.75 ? "lo" : "mid";
  return `<span class="cv-lq ${cls}" title="${esc(tip)}">\u00d7${lq.toFixed(1)}</span>`;
}

function medallion(id, fallback, bg, size = 18) {
  return `<span class="cv-med" style="--bg:${esc(bg)}">${icon(id, fallback, { size })}</span>`;
}

// --- header --------------------------------------------------------------------------------------------------------
function header(m) {
  const c = m.city, n = m.nation.nation;
  const cities = m.cityList;
  const col = css(m.stateRGB);
  const chips = m.states.map((s) => (s.index >= 0
    ? `<button class="chip" data-state="${s.index}" title="Open ${esc(s.name)}">${esc(s.abbr)}</button>`
    : `<span class="chip">${esc(s.abbr)}</span>`)).join("");
  const g = Number.isFinite(c.growth) ? c.growth : null;
  const yrs = Array.isArray(c.growth_years) ? c.growth_years : null;
  const growth = g == null ? "" : `<span class="cv-growth ${g >= 0 ? "good" : "bad"}" title="Population change${yrs ? ` ${yrs[0]}${DASH}${yrs[1]}` : ""}. Poland: ${signed(n.growth)}">${g >= 0 ? "\u25b2" : "\u25bc"} ${Math.abs(g * 100).toFixed(1)}%${yrs ? ` <small>since ${yrs[0]}</small>` : ""}</span>`;
  const perCap = c.gdp != null && c.population ? c.gdp / c.population : null;
  const r = c.ranks || {};
  const N = (k) => countOf(cities, k);
  return `
  <div class="sheet-grip cv-grip" aria-hidden="true"></div>
  <header class="cv-head" style="--sc:${col}">
    <div class="cv-ribbon" aria-hidden="true"></div>
    <button class="icon-btn cv-close" data-close aria-label="Close the City View (Esc)" title="Back to the map (Esc)">${icon("close", "x", { size: 13 })}</button>
    <div class="cv-kind">City View \u00b7 ${c.kind === "city" ? "City with powiat rights" : "Town"}</div>
    <div class="cv-title">
      <div class="cv-crest" aria-hidden="true"><span>${esc(popShort(c.population))}</span></div>
      <div class="cv-tt">
        <h2 class="cv-name" tabindex="-1">${isCapital(c) ? `<span class="cv-cap" title="Capital of Poland">\u2605</span> ` : ""}${esc(c.name)}</h2>
        <div class="cv-full">${esc(c.full || "")}</div>
        <div class="cv-typeslot" data-ctype></div>
        ${chips ? `<div class="chips">${chips}</div>` : ""}
      </div>
    </div>
    <div class="cv-headline">
      <div class="cv-big"><span class="lbl">${icon("pop", "", { size: 13 })} Population</span><b>${int(c.population)}</b>${growth}</div>
      <div class="cv-big"><span class="lbl">${icon("y-gold", "", { size: 13 })} GDP${c.gdp_year ? ` ${c.gdp_year}` : ""}</span><b>${money(c.gdp)}</b>${
        perCap != null ? `<span class="cv-sub">${money(perCap)} per person</span>` : ""}</div>
    </div>
    <div class="cv-ranks" aria-label="Ranks among ${cities.length} towns">
      ${rankBadge(r.population, N("population"), "Population")}
      ${rankBadge(r.gdp, N("gdp"), "GDP")}
      ${rankBadge(r.gdp_per_capita, N("gdp_per_capita"), "GDP / person")}
      ${rankBadge(r.growth, N("growth"), "Growth", r.growth != null ? `Growth: #${r.growth} of ${N("growth")} towns (1 = fastest growing)` : "")}
    </div>
  </header>
  <nav class="cv-tabs" aria-label="City View sections">
    ${TABS.map(([id, label, ic]) => `<button type="button" data-tab="${id}">${icon(ic, "", { size: 14 })}<span>${label}</span></button>`).join("")}
  </nav>`;
}

// --- citizens ------------------------------------------------------------------------------------------------------
function citizens(m) {
  const c = m.city, n = m.nation.nation;
  const series = popSeries(c);
  const ch = series.length >= 2 ? series.at(-1).value / series[0].value - 1 : null;
  const pw = powiatOf(c);
  // sub: the small line beside the value; by default Poland's value, left out when there is none.
  const row = (ic, label, v, pl, fmt, better, max, sub = pl != null ? `Poland ${fmt(pl)}` : "", tick = pl, tip = "") => `
    <div class="cv-stat"${tip ? ` title="${esc(tip)}"` : ""}>
      <div class="cv-stat-top"><span class="sl">${icon(ic, "", { size: 14 })}${esc(label)}</span>
        <span class="sv"><b>${v == null ? DASH : fmt(v)}</b>${sub ? `<small>${sub}</small>` : ""}</span></div>
      ${meter(v, tick, max ?? Math.max(v || 0, pl || 0) * 1.35, better)}
    </div>`;
  // Workers by employer seat: set beside the residents as "per 100 residents" (and Poland's figure).
  const per100 = c.employed != null && c.population > 0 ? (c.employed / c.population) * 100 : null;
  const plPer100 = n.employed != null && n.population > 0 ? (n.employed / n.population) * 100 : null;
  const empSub = per100 == null ? ""
    : `${Math.round(per100)} per 100 residents${plPer100 != null ? ` \u00b7 Poland ${Math.round(plPer100)}` : ""}`;
  const powiatSub = (pl, fmt) => [pl != null ? `Poland ${fmt(pl)}` : "", pw ? esc(pw) : ""].filter(Boolean).join(" \u00b7 ");
  const multi = m.tiles.length > 1;
  const tilesNote = multi
    ? `On the map each hex of ${esc(c.name)} shows <b>about how many people live there</b> and its <b>main land use</b>.`
    : `${esc(c.name)} fits inside one map hex (about ${compact(m.hexArea)} km\u00b2).`;
  return `
  <section class="cv-sec" id="cv-citizens" data-sec="citizens" aria-labelledby="cv-h-citizens">
    <h3 id="cv-h-citizens">${icon("pop", "", { size: 15 })}Citizens</h3>
    <div class="cv-citizens" data-citizens>${citizensHtml(m, undefined)}</div>
    <h4 class="cv-h4">Population</h4>
    <div class="cv-card">
      <div class="cv-card-h"><span>Population ${series.length ? `${series[0].year}${DASH}${series.at(-1).year}` : ""}</span>${
        ch != null ? `<span class="${ch >= 0 ? "good" : "bad"}">${signed(ch)}</span>` : ""}</div>
      ${sparkline(series, { fmt: (v) => popShort(v), title: `Population of ${c.name} by year` })}
    </div>
    <div class="cv-stats">
      ${row("pop", "Workers", c.employed, null, int, null, c.population, empSub, plPer100 != null ? (plPer100 / 100) * c.population : null)}
      ${row("unemployment", "Registered unemployment", c.unemployment, n.unemployment, (x) => pct(x), "low", undefined, powiatSub(n.unemployment, (x) => pct(x)))}
      ${row("l-income", "Average gross wage / month", c.wage, n.wage, dollars, "high", undefined, powiatSub(n.wage, dollars))}
      ${row("y-gold", "PIT revenue per resident", c.pit_per_person, n.pit_per_person, dollars, "high")}
    </div>
    <div class="cv-legend-tiles">${tileLegend(m)}<p>${tilesNote}</p></div>
  </section>`;
}

function tileLegend(m) {
  const counts = new Map();
  for (const t of m.tiles) if (t.land) counts.set(t.land.key, (counts.get(t.land.key) || 0) + 1);
  return `<div class="cv-tl">${LAND.filter((g) => counts.has(g.key)).map((g) =>
    `<span class="cv-tl-i"><i style="background:${esc(m.landColor(g.key))}"></i>${esc(g.label)} <small>${counts.get(g.key)}</small></span>`).join("")}</div>`;
}

// --- districts -----------------------------------------------------------------------------------------------------
function districts(m) {
  return `
  <section class="cv-sec" id="cv-districts" data-sec="districts" aria-labelledby="cv-h-districts">
    <h3 id="cv-h-districts">${icon("l-developed", "", { size: 15 })}Districts</h3>
    <div data-districts>${districtsHtml(m, undefined, null)}</div>
  </section>`;
}

// --- economy -------------------------------------------------------------------------------------------------------
function economy(m) {
  const c = m.city, nat = m.nation, n = nat.nation;
  const r = c.ranks || {};
  const cities = m.cityList;
  const perCap = c.gdp != null && c.population ? c.gdp / c.population : null;
  const plPerCap = n.gdp && n.population ? n.gdp / n.population : null;
  const yields = nat.yields.map((y) => {
    const v = c.yields?.[y.key];
    const rk = r[y.key];
    return `<div class="cv-yield" style="--yc:${esc(y.color)}" title="${esc(y.label)}">
      <div class="ico">${glyph(y, 20)}</div><div class="val">${v == null ? DASH : yieldValue(y, v)}</div>
      <div class="lbl">${esc(y.key === "gold" ? "GDP" : y.label)}</div>
      ${rk != null ? `<div class="rk">#${rk} <small>of ${countOf(cities, y.key)}</small></div>` : ""}</div>`;
  }).join("");
  const share = c.gdp != null && n.gdp ? c.gdp / n.gdp : null;
  return `
  <section class="cv-sec" id="cv-economy" data-sec="economy" aria-labelledby="cv-h-economy">
    <h3 id="cv-h-economy">${icon("y-gold", "", { size: 15 })}Economy</h3>
    <div class="cv-gdp">
      <div><span class="lbl">GDP${c.gdp_year ? ` (${c.gdp_year})` : ""}</span><b>${money(c.gdp)}</b>${r.gdp != null ? `<small>#${r.gdp} of ${countOf(cities, "gdp")}</small>` : ""}</div>
      <div><span class="lbl">GDP per person</span><b>${money(perCap)}</b>${
        plPerCap && perCap != null ? `<small class="${perCap >= plPerCap ? "good" : "bad"}">Poland ${money(plPerCap)}</small>` : ""}</div>
      <div><span class="lbl">Share of Poland's GDP</span><b>${share != null ? pct(share, 2) : DASH}</b>${
        c.population && n.population ? `<small>${pct(c.population / n.population, 2)} of people</small>` : ""}</div>
    </div>
    <h4 class="cv-h4">Yields <span class="muted">rank among towns</span></h4>
    <div class="cv-yields">${yields}</div>
  </section>`;
}

// --- workforce -----------------------------------------------------------------------------------------------------
function workforce(m) {
  const c = m.city;
  const cards = m.inds.map((d) => {
    const spec = d.lq != null && d.lq >= 1.25;
    return `<div class="cv-bld${spec ? " spec" : ""}" title="${esc(d.label)}: ${int(d.jobs)} workers (${pct(d.share)}; Poland ${pct(d.natShare)})">
      ${medallion(d.icon, "", d.color, 17)}
      <div class="cv-bld-t"><span class="cv-bld-n">${esc(d.short)}</span>
        <span class="cv-bld-v">${compact(d.jobs)} <small>${pct(d.share, 1)}</small></span></div>
      ${lqBadge(d.lq)}
    </div>`;
  }).join("");
  const lead = m.indsBySection
    ? `${esc(c.name)}'s ${int(c.employed)} workers by industry. <span class="cv-lq hi">\u00d7N</span> compares an industry's share with Poland's.`
    : `${esc(c.name)}'s ${int(c.employed)} workers by yield. <span class="cv-lq hi">\u00d7N</span> compares a share with Poland's.`;
  return `
  <section class="cv-sec" id="cv-workforce" data-sec="workforce" aria-labelledby="cv-h-workforce">
    <h3 id="cv-h-workforce">${icon("y-production", "", { size: 15 })}Workforce</h3>
    ${m.inds.length ? `<p class="cv-lead">${lead}</p>` : ""}
    <div class="cv-blds">${cards || `<p class="muted cv-note">No workforce figures for ${esc(c.name)}.</p>`}</div>
  </section>`;
}

// --- resources -----------------------------------------------------------------------------------------------------
function resources(m) {
  const list = m.sites.map((s, k) => {
    const t = s.type;
    const val = resourceValue(s.item, t, compact);
    return `<button type="button" class="cv-site" data-site="${k}" title="Fly to ${esc(s.item.name)}">
      <span class="cv-med" style="--bg:${esc(t?.color || "#3a4a5e")}">${glyph(t, 16)}</span>
      <span class="cv-site-t"><b>${esc(s.item.name)}</b><small>${esc(t?.name || s.item.type)}${s.item.state ? ` \u00b7 ${esc(s.item.state)}` : ""}</small>
        ${s.item.detail ? `<small class="cv-site-d">${esc(s.item.detail)}</small>` : ""}</span>
      <span class="cv-site-v">${esc(val)}</span>
    </button>`;
  }).join("");
  const mw = m.sites.filter((s) => s.type?.unit === "MW").reduce((a, s) => a + (s.item.value || 0), 0);
  const summary = m.sites.length
    ? `<p class="cv-lead">${m.sites.length} mapped site${m.sites.length === 1 ? "" : "s"}${
      mw ? ` \u00b7 ${mw >= 1000 ? `${(mw / 1000).toFixed(1)} GW` : `${Math.round(mw)} MW`} of generating capacity` : ""}. Click one to fly there.</p>`
    : `<p class="muted cv-note">No mapped resource sites in ${esc(m.city.name)}.</p>`;
  return `
  <section class="cv-sec" id="cv-resources" data-sec="resources" aria-labelledby="cv-h-resources">
    <h3 id="cv-h-resources">${icon("resources", "", { size: 15 })}Resources</h3>
    ${summary}
    <div class="cv-sites">${list}</div>
  </section>`;
}

// --- compare -------------------------------------------------------------------------------------------------------
const COMPARE = {
  size: [
    ["Population", (c) => c.population, (v) => popShort(v)],
    ["GDP / person", (c) => (c.gdp != null && c.population ? c.gdp / c.population : null), money],
    ["Wage", (c) => c.wage, money],
    ["Growth", (c) => (Number.isFinite(c.growth) ? c.growth : null), (v) => signed(v)],
  ],
  work: [
    ["Workers", (c) => c.employed, compact],
    ["Jobless", (c) => c.unemployment, (v) => pct(v)],
    ["PIT / person", (c) => c.pit_per_person, money],
    ["Wage", (c) => c.wage, money],
  ],
};

export function compareTable(m, set = "size") {
  const rows = [m.city, ...m.peers];
  const cols = COMPARE[set] || COMPARE.size;
  const max = cols.map(([, f]) => Math.max(...rows.map((c) => Math.abs(f(c) ?? 0))) || 1);
  return `<div class="cv-cmp" role="table" aria-label="${esc(m.city.name)} and its peers">
    <div class="cv-cmp-r cv-cmp-h" role="row"><span role="columnheader">Town</span>${cols.map(([l]) => `<span role="columnheader">${esc(l)}</span>`).join("")}</div>
    ${rows.map((c, k) => `<div class="cv-cmp-r${k === 0 ? " me" : ""}" role="row">
      <span role="cell">${k === 0 ? `<b class="cv-cmp-n">${esc(c.name)}</b>` : `<button type="button" class="cv-cmp-n" data-peer="${esc(c.id)}" title="Open ${esc(c.full || c.name)} in the City View">${esc(c.name)}</button>`}<small>${esc((c.states || []).join(" "))}</small></span>
      ${cols.map(([, f, fmt], j) => {
        const v = f(c);
        const col = v != null && v < 0 ? "#f08a6a" : k === 0 ? "#ecd08e" : "#8fa6bd";
        return `<span role="cell"><em>${v == null ? DASH : esc(fmt(v))}</em>${bar(v == null ? 0 : Math.abs(v) / max[j], col)}</span>`;
      }).join("")}
    </div>`).join("")}
  </div>`;
}

function compare(m) {
  const n = m.peers.length;
  return `
  <section class="cv-sec" id="cv-compare" data-sec="compare" aria-labelledby="cv-h-compare">
    <h3 id="cv-h-compare">${icon("layers", "", { size: 15 })}Compare</h3>
    ${n ? `<p class="cv-lead">The ${n} town${n === 1 ? "" : "s"} closest in population. Click one to open it.</p>
    <div class="cv-seg" role="group" aria-label="Metrics">
      <button type="button" data-set="size" aria-pressed="true">Size &amp; wealth</button>
      <button type="button" data-set="work" aria-pressed="false">Work &amp; income</button>
    </div>` : ""}
    <div data-compare>${compareTable(m, "size")}</div>
  </section>`;
}

function footer(m) {
  return `<div class="cv-foot">Ranks are among all ${int(m.cityList.length)} towns on the map.
    <a href="#" data-pedia>Almanac</a></div>`;
}

/**
 * Fill the dock. handlers: {onClose, onState(idx), onPeer(id), onSite(site), onSiteHover(site|null), onPedia,
 * loadData(name) -> Promise<data|null>, onDistricts(list)} (the town's districts once districts.json is in, for the
 * map plaques).
 */
/**
 * Scrolls the dock to a section (its tab id, e.g. "districts"). Citizens and districts arrive later and change the
 * heights above, so the section is re-aligned as they do, for up to 4 s or until the user scrolls themselves.
 */
export function goToSection(el, id) {
  const sec = el?.querySelector(`[data-sec="${id}"]`);
  if (!sec) return false;
  const align = () => {
    const nav = el.querySelector(".cv-tabs");
    el.scrollTop = Math.max(0, sec.offsetTop - (nav?.offsetHeight || 0) - 4);
    el.onscroll?.(); // the tab spy (a scroll event is not always sent for a programmatic jump)
  };
  align();
  let ro = null;
  const stop = () => {
    ro?.disconnect();
    ro = null;
    for (const t of ["wheel", "touchstart", "keydown", "pointerdown"]) el.removeEventListener(t, stop);
  };
  for (const t of ["wheel", "touchstart", "keydown", "pointerdown"]) el.addEventListener(t, stop, { passive: true });
  if (typeof ResizeObserver === "function") {
    ro = new ResizeObserver(() => { if (sec.isConnected) align(); else stop(); });
    for (const c of el.children) ro.observe(c);
  }
  setTimeout(stop, 4000);
  return true;
}

export function render(el, m, h) {
  el.classList.add("cv-dock");
  el.style.setProperty("--sc", css(m.stateRGB));
  el.innerHTML = header(m) + citizens(m) + districts(m) + economy(m) + workforce(m) + resources(m) + compare(m) + footer(m);
  el.scrollTop = 0;

  el.querySelector("[data-close]").onclick = () => h.onClose();
  el.querySelectorAll("[data-state]").forEach((b) => (b.onclick = () => h.onState(+b.dataset.state)));
  el.querySelector("[data-pedia]").onclick = (e) => { e.preventDefault(); h.onPedia(); };

  // Sites: hover lights the hex on the map, click flies there.
  el.querySelectorAll("[data-site]").forEach((b) => {
    const s = m.sites[+b.dataset.site];
    b.onclick = () => h.onSite(s);
    b.onmouseenter = b.onfocus = () => h.onSiteHover(s);
    b.onmouseleave = b.onblur = () => h.onSiteHover(null);
  });

  // Compare: metric sets and peer links (delegated, the table is re-rendered).
  const cmp = el.querySelector("[data-compare]");
  el.querySelectorAll("[data-set]").forEach((b) => (b.onclick = () => {
    el.querySelectorAll("[data-set]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    cmp.innerHTML = compareTable(m, b.dataset.set);
  }));
  cmp.addEventListener("click", (e) => {
    const b = e.target.closest("[data-peer]");
    if (b) h.onPeer(b.dataset.peer);
  });

  // Tabs scroll to their section; the active tab follows the scroll position.
  const nav = el.querySelector(".cv-tabs");
  const tabs = [...el.querySelectorAll("[data-tab]")];
  const secs = tabs.map((t) => el.querySelector(`[data-sec="${t.dataset.tab}"]`));
  tabs.forEach((t, k) => (t.onclick = () => {
    const top = secs[k].offsetTop - nav.offsetHeight - 4;
    el.scrollTo({ top, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }));
  const spy = () => {
    const y = el.scrollTop + nav.offsetHeight + 24;
    let k = 0;
    secs.forEach((s, j) => { if (s.offsetTop <= y) k = j; });
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 4) k = secs.length - 1;
    tabs.forEach((t, j) => t.classList.toggle("on", j === k));
  };
  el.onscroll = spy;
  spy();

  // Citizens and districts arrive with their files (each loaded once, on demand).
  const czHost = el.querySelector("[data-citizens]");
  Promise.resolve(h.loadData?.("citizens")).then((data) => {
    if (!czHost.isConnected) return;
    czHost.innerHTML = citizensHtml(m, data ?? null);
    mountCitizens(czHost, m, data);
  }, () => { if (czHost.isConnected) czHost.innerHTML = citizensHtml(m, null); });
  const dHost = el.querySelector("[data-districts]");
  const typeSlot = el.querySelector("[data-ctype]");
  Promise.all([h.loadData?.("districts"), Promise.resolve(h.loadData?.("military")).catch(() => null)]).then(([dd, mil]) => {
    if (!dHost.isConnected) return;
    dHost.innerHTML = districtsHtml(m, dd ?? null, mil ?? null);
    typeSlot.innerHTML = badgeHtml(m, dd ?? null);
    h.onDistricts?.(dd ? cityDistricts(dd, mil, m.city.id) : []);
  }, () => { if (dHost.isConnected) dHost.innerHTML = districtsHtml(m, null, null); });
}

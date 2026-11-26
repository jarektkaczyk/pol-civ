// Economy advisor: workers by industry, metro GDP on the map, leaders, specialisation and growth vs output.
import { esc, fin, ratio, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { money, dollars, pct, signedPct, count3, fmtShort } from "../core/fmt.js";
import { barList, rampLegend, sizeLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, selectBox, sourcesHtml, frameBtn } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { icon } from "../../../ui/icon.js";
import { hasIcon } from "../../../icons.js";

export const METRO_MIN = 250000;
const TIMES = "\u00d7";
const short = (s) => String(s || "").replace(/\s*\(.*\)\s*$/, "");
// PKD section keys -> the closest icon in the shared set.
const ICON_OF = { trade: "retail", transport: "transportation", energy: "utilities", water: "utilities" };
const indIcon = (k) => { const id = `i-${ICON_OF[k] || k}`; return hasIcon(id) ? icon(id, "\u2022", { size: 14 }) : ""; };

export function mount(ctx) {
  const { app, data, el, link, params } = ctx;
  const nation = app.data.nation;
  const n = nation.nation || {};
  const yrs = nation.years || {};
  const metros = data.levels.metros;
  const towns = data.levels.towns;
  const states = data.levels.states;
  const rows = metros.rows;
  const jobInd = Object.keys(nation.industries || {}).filter((k) => fin(n.jobs?.[k]));
  const indName = (k) => short(nation.industries?.[k] || k);

  // --- headline -------------------------------------------------------------------------------------------------
  el.insertAdjacentHTML("beforeend", tiles([
    { label: `GDP ${n.gdp_year || ""}`, value: money(n.gdp), sub: "current złoty" },
    { label: "Per person", value: money(ratio(n.gdp, n.population)), sub: "GDP per resident" },
    { label: "Average wage", value: dollars(n.wage), sub: `gross per month, ${yrs.wage || ""}` },
  ]));

  // --- workers by industry --------------------------------------------------------------------------------------
  const indBody = section(el, { title: "Workers by industry", kicker: "Poland", note: "People working in each PKD section, counted where the employer is. Hover an industry to light up the voivodeships where it has the largest share of workers; click it to rank the cities that specialise in it." });
  const indRows = jobInd.map((k) => ({ key: k, label: indName(k), full: nation.industries[k], value: n.jobs[k], text: count3(n.jobs[k]), sub: pct(ratio(n.jobs[k], n.workers ?? n.employed)), icon: indIcon(k) }))
    .sort((a, b) => b.value - a.value);
  const indBars = barList(indBody, {
    rows: indRows, ariaLabel: "Workers by industry",
    onHover: (r) => {
      if (!r) return link.hover(null);
      const top = states.rows.map((s) => ({ s, v: ratio(app.data.states[s.ref]?.jobs?.[r.key], s.v.workers) })).filter((x) => fin(x.v)).sort((a, b) => b.v - a.v).slice(0, 4);
      link.hover(rowsHighlight(states, top.map((x) => x.s), { dim: true, label: `${indName(r.key)}: ${top.map((x) => x.s.name).join(", ")}` }));
    },
    onClick: (r) => { setIndustry(r.key); specBody.scrollIntoView({ behavior: "smooth", block: "start" }); },
  });

  // --- map: metro GDP circles -----------------------------------------------------------------------------------
  const mapBody = section(el, { title: "Metro economies on the map", note: "Each circle is a metro area: its area is the metro's GDP, its colour GDP per person. Hover a circle for numbers; click to frame the metro." });
  const ppDomain = robustDomain(rows.map((r) => r.v.gdp_pc), 0.03, true) || [40000, 150000];
  const ppColor = colorScale({ type: "seq", domain: ppDomain, ramp: RAMPS.gold });
  const gMax = Math.max(1, ...rows.map((r) => r.v.gdp || 0));
  const bubbles = ctx.bubbles("gdp", {
    rMax: 30, minR: 1.5, alpha: 0.6,
    tip: (b) => `<b>${esc(b.row.name)}</b> <span class="sub">${esc(b.row.sub)}</span><br>GDP <b>${money(b.row.v.gdp)}</b> &middot; per person <b>${money(b.row.v.gdp_pc)}</b><br>${count3(b.row.v.population)} people`,
    onHover: (b) => { table.setHot(b ? b.key : null); scatter.setHot(b ? b.key : null); link.hover(b ? rowsHighlight(metros, [b.row]) : null); },
    onClick: (b) => metros.focus(b.row),
  });
  const bubbleItems = rows.filter((r) => fin(r.v.gdp) && r.ref.cell != null).map((r) => ({ key: r.key, x: app.w.grid.cx(r.ref.cell), y: app.w.grid.cy(r.ref.cell), value: r.v.gdp, color: ppColor(r.v.gdp_pc), row: r }));
  bubbles.set(bubbleItems, { vMax: gMax });
  const showBubbles = document.createElement("label");
  showBubbles.className = "adv-check";
  showBubbles.innerHTML = `<input type="checkbox" checked> Show GDP circles`;
  showBubbles.querySelector("input").addEventListener("change", (e) => bubbles.set(e.target.checked ? bubbleItems : [], { vMax: gMax }));
  mapBody.appendChild(showBubbles);
  mapBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.gold, domain: ppDomain, fmt: money, label: "GDP per person" })
    + sizeLegend([1e10, 1e11, 5e11].filter((v) => v <= gMax), (v) => 30 * Math.sqrt(v / gMax), money, "Circle area = GDP (at the home zoom)"));

  // --- leaders --------------------------------------------------------------------------------------------------
  const lBody = section(el, { title: "Leading metros", note: `All ${rows.length} metro areas: a city and the gminas that commute to it.` });
  segmented(lBody, {
    label: "Rank by", value: "gdp",
    options: [{ value: "gdp", label: "Largest GDP" }, { value: "gdp_pc", label: "GDP per person" }, { value: "wage", label: "Wage" }, { value: "growth", label: "Fastest growing" }],
    onChange: (v) => table.setColumns(cols, { key: v, dir: "desc" }),
  });
  const cols = [
    { key: "name", label: "Metro", align: "l", value: (r) => r.name, html: (r) => `${esc(r.name)} <span class="sub">${esc(r.sub)}</span>` },
    { key: "gdp", label: "GDP", value: (r) => r.v.gdp, text: (r) => money(r.v.gdp), bar: { max: gMax, color: "rgba(224,181,76,.35)" } },
    { key: "gdp_pc", label: "Per person", value: (r) => r.v.gdp_pc, text: (r) => money(r.v.gdp_pc) },
    { key: "wage", label: "Wage", value: (r) => r.v.wage, text: (r) => money(r.v.wage), hideBelow: 420 },
    { key: "growth", label: "Growth", value: (r) => r.v.growth, text: (r) => signedPct(r.v.growth) },
  ];
  const table = createTable(lBody, {
    caption: "Metros by GDP", columns: cols, rows, sort: { key: "gdp", dir: "desc" }, rank: true, maxHeight: 280,
    search: "Search metros",
    onHover: (r) => { link.hover(r ? rowsHighlight(metros, [r]) : null); bubbles.setHot(r ? r.key : null); scatter.setHot(r ? r.key : null); },
    onClick: (r) => metros.focus(r),
  });

  // --- specialisation -------------------------------------------------------------------------------------------
  // GUS publishes workers by PKD section per powiat, so specialisation is measured for cities with powiat rights
  // (their own powiat) and for voivodeships.
  const jobsOf = (r) => (r.level === "states" ? app.data.states[r.ref]?.jobs : r.ref.jobs) || {};
  const cityRows = towns.rows.filter((r) => r.ref.kind === "city" && Object.keys(r.ref.jobs || {}).length);
  const specBody = section(el, { title: "Who specialises in what", note: `Location quotient: an industry's share of the area's workers divided by its share in Poland. ${TIMES}2 means twice as concentrated as the country. The 15 most specialised are outlined on the map.` });
  let industry = params.industry && jobInd.includes(params.industry) ? params.industry : "manufacturing";
  let specLevel = "towns";
  const specCtl = document.createElement("div");
  specCtl.className = "adv-row";
  specBody.appendChild(specCtl);
  const indSel = selectBox(specCtl, {
    label: "Industry", value: industry,
    options: jobInd.map((k) => ({ value: k, label: indName(k) })),
    onChange: (v) => setIndustry(v),
  });
  segmented(specCtl, { label: "Areas", value: specLevel, options: [{ value: "towns", label: `Cities (${cityRows.length})` }, { value: "states", label: "Voivodeships" }], onChange: (v) => { specLevel = v; setIndustry(industry); } });
  const specInfo = document.createElement("p");
  specInfo.className = "adv-note";
  specBody.appendChild(specInfo);
  const plShare = (k = industry) => ratio(n.jobs?.[k], n.workers ?? n.employed);
  const shareOf = (r, k = industry) => ratio(jobsOf(r)[k], r.v.workers);
  const lq = (r, k = industry) => { const p = plShare(k); return p ? ratio(shareOf(r, k), p) : null; };
  const specLv = () => (specLevel === "states" ? states : towns);
  const specCols = (maxLq) => [
    { key: "name", label: specLevel === "states" ? "Voivodeship" : "City", align: "l", value: (r) => r.name, html: (r) => `${esc(r.name)}${specLevel === "states" ? "" : ` <span class="sub">${esc(r.sub)}</span>`}` },
    { key: "share", label: "Share of workers", value: (r) => shareOf(r), text: (r) => pct(shareOf(r)) },
    { key: "lq", label: "LQ", value: (r) => lq(r), text: (r) => (fin(lq(r)) ? `${TIMES}${lq(r).toFixed(2)}` : "\u2013"), bar: { max: maxLq, color: "rgba(74,134,214,.45)" } },
    { key: "workers", label: "Workers", value: (r) => jobsOf(r)[industry], text: (r) => count3(jobsOf(r)[industry]) },
  ];
  const specTable = createTable(specBody, {
    caption: "Most specialised places", rank: true, maxHeight: 260, rows: [], columns: specCols(1),
    sort: { key: "lq", dir: "desc" },
    onHover: (r) => link.hover(r ? rowsHighlight(specLv(), [r]) : null),
    onClick: (r) => specLv().focus(r),
  });

  // --- scatter --------------------------------------------------------------------------------------------------
  const scBody = section(el, { title: "Growth vs output", note: "Each dot is a metro area: GDP per person across, population change up, size = population. Drag a rectangle to select metros and outline them on the map." });
  const scCtl = document.createElement("div");
  scCtl.className = "adv-row";
  scBody.appendChild(scCtl);
  let colorBy = "wage";
  const COLORS = {
    wage: { label: "Average wage", fmt: money, cell: dollars, ramp: RAMPS.gold },
    pit: { label: "PIT per person", fmt: money, cell: dollars, ramp: RAMPS.gold },
    unemployment: { label: "Unemployment", fmt: (v) => pct(v), cell: pct, ramp: RAMPS.heat },
  };
  selectBox(scCtl, {
    label: "Colour", value: colorBy,
    options: [...Object.entries(COLORS).map(([k, c]) => ({ value: k, label: c.label })), { value: "none", label: "None" }],
    onChange: (v) => { colorBy = v; drawScatter(); },
  });
  const legendEl = document.createElement("div");
  const scatter = createScatter(scBody, {
    points: [], height: 300,
    x: { label: "GDP per person", fmt: (v) => money(v), log: true },
    y: { label: "Population change", fmt: (v) => fmtShort("signed", v) },
    size: { label: "Population", fmt: count3, max: 15, min: 2 },
    refY: [{ v: n.growth ?? 0, label: `Poland ${signedPct(n.growth)}` }],
    onHover: (p) => { link.hover(p ? rowsHighlight(metros, [p.row]) : null); bubbles.setHot(p ? p.key : null); table.setHot(p ? p.key : null, false); },
    onClick: (p) => metros.focus(p.row),
    onBrush: (set) => {
      const sel = set ? rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(metros, sel, { dim: true }) : specHighlight(), { frame: sel.length > 1 });
      bubbles.setSelected(set);
      brushInfo.innerHTML = sel.length ? brushSummary(sel) : "";
    },
  });
  scBody.appendChild(legendEl);
  const brushInfo = document.createElement("div");
  brushInfo.className = "adv-brushinfo";
  scBody.appendChild(brushInfo);
  function brushSummary(sel) {
    const pop = sel.reduce((a, r) => a + (r.v.population || 0), 0);
    const gdp = sel.reduce((a, r) => a + (r.v.gdp || 0), 0);
    return `<b>${sel.length}</b> metros selected &middot; ${count3(pop)} people &middot; ${money(gdp)} GDP (${pct(gdp / n.gdp)} of Poland) ${frameBtn()}<button type="button" class="adv-mini" data-clear>Clear</button>`;
  }
  brushInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { scatter.setSelected(null); link.base(specHighlight()); bubbles.setSelected(null); brushInfo.innerHTML = ""; } });

  function drawScatter() {
    const c = COLORS[colorBy];
    let color = null, legend = "";
    if (c) {
      const dom = robustDomain(rows.map((r) => r.v[colorBy]), 0.03) || [0, 1];
      const cs = colorScale({ type: "seq", domain: dom, ramp: c.ramp });
      color = (v) => cs(v);
      legend = rampLegend({ ramp: c.ramp, domain: dom, fmt: c.fmt, label: c.label });
    }
    const labels = [...rows].sort((a, b) => (b.v.population || 0) - (a.v.population || 0)).slice(0, 8).map((r) => r.key);
    scatter.update({
      points: rows.filter((r) => fin(r.v.gdp_pc) && fin(r.v.growth)).map((r) => ({ key: r.key, x: r.v.gdp_pc, y: r.v.growth, s: r.v.population, c: c ? r.v[colorBy] : null, label: r.name, sub: r.sub, row: r })),
      color, labels, colorLabel: c ? c.label : null, colorFmt: c ? c.cell : String,
    });
    legendEl.innerHTML = legend;
  }

  let specTop = [];
  const specHighlight = () => (specTop.length ? rowsHighlight(specLv(), specTop, { ringMax: 15 }) : null);
  function setIndustry(k) {
    industry = k;
    indSel.set(k);
    const base = specLevel === "states" ? states.rows : cityRows;
    const list = base.filter((r) => fin(lq(r))).sort((a, b) => lq(b) - lq(a));
    specTop = list.slice(0, specLevel === "states" ? 4 : 15);
    const maxLq = Math.max(1, ...list.slice(0, 40).map((r) => lq(r)));
    specTable.setColumns(specCols(maxLq), { key: "lq", dir: "desc" });
    specTable.setRows(list);
    specInfo.innerHTML = `Poland: <b>${pct(plShare(k))}</b> of workers (${count3(n.jobs?.[k])} people) work in ${esc(indName(k).toLowerCase())}.`;
    if (!scatter.selected) link.base(specHighlight());
    indBars.setSelected(k);
  }
  drawScatter();
  setIndustry(industry);

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["pl_gdp", "pl_stats_labour", "pl_stats_population", "pl_geo_fua"], [
    `Below the voivodeship, GDP is an estimate: Eurostat publishes it per NUTS 3 subregion (${yrs.gdp_nuts3 || 2023}), shared out here by wage bill and workers.`,
    "Workers are counted where the employer is: a firm's staff in other towns can count at its head office.",
    `GDP per person divides GDP of ${esc(String(yrs.gdp_nuts3 || 2023))} (metros) by residents of ${esc(String(yrs.population || 2025))}.`,
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? metros.rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      table.setHot(r ? r.key : null);
      const s = h.cell >= 0 ? specLv().rowAtCell(h.cell) : null;
      specTable.setHot(s ? s.key : null);
    },
    onEscape() {
      if (scatter.selected) { scatter.setSelected(null); link.base(specHighlight()); bubbles.setSelected(null); brushInfo.innerHTML = ""; return true; }
      return false;
    },
  };
}

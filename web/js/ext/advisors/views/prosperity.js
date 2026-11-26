// Prosperity advisor: wages against tax revenue, unemployment, and the best and worst paid places.
import { esc, fin, colorScale, robustDomain, RAMPS, fillHtml } from "../core/util.js";
import { money, dollars, pct, int, count3, fmtShort } from "../core/fmt.js";
import { barList, histogram, rampLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, lensButton, sourcesHtml, topBy, frameBtn } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { t } from "../../../i18n.js";

const METRO_MIN = 250000;
const people = (n) => t.plural(Math.abs(n) >= 1e4 ? 1e6 : Math.round(n),
  { one: "{n} person", other: "{n} people" }, { n: count3(n) });
// "<b>3</b> powiaty selected", per level.
const selectedHtml = (level, count) => {
  const keep = { n: "{n}" };
  const tpl = level === "powiaty" ? t.plural(count, { one: "{n} powiat selected", other: "{n} powiaty selected" }, keep)
    : level === "metros" ? t.plural(count, { one: "{n} metro selected", other: "{n} metros selected" }, keep)
    : t.plural(count, { one: "{n} voivodeship selected", other: "{n} voivodeships selected" }, keep);
  return fillHtml(tpl, { n: `<b>${int(count)}</b>` });
};

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const yrs = app.data.nation?.years || {};
  const { states, metros, powiaty, counties } = data.levels;

  el.insertAdjacentHTML("beforeend", tiles([
    { label: t("Average wage"), value: dollars(n.wage), sub: t("gross per month, {year}", { year: String(yrs.wage || "") }) },
    { label: t("PIT per person"), value: dollars(n.pit), sub: t("gmina revenue, {year}", { year: String(yrs.pit || "") }) },
    { label: t("Unemployment"), value: pct(n.unemployment), sub: t("registered, {year}", { year: String(yrs.unemployment || "") }) },
  ]));

  // --- wage vs PIT ----------------------------------------------------------------------------------------------
  const aBody = section(el, { title: t("Pay and tax revenue"), note: esc(t("Average wage (where the employer is) against personal income tax per resident (where people live). Colour = unemployment. Drag a rectangle to select places.")) });
  const aCtl = document.createElement("div");
  aCtl.className = "adv-row";
  aBody.appendChild(aCtl);
  const lvOpts = [...(powiaty ? [{ value: "powiaty", label: t("Powiaty") }] : []), { value: "metros", label: t("Metros") }, { value: "states", label: t("Voivodeships") }];
  let level = lvOpts[0].value;
  segmented(aCtl, { label: t("Places"), value: level, options: lvOpts, onChange: (v) => { level = v; drawPay(); } });
  for (const [id, label] of [["wage", t("Wage lens")], ["income", t("PIT lens")]]) {
    const b = lensButton(app, id, label);
    if (b) aCtl.appendChild(b);
  }
  const lv = () => data.levels[level];
  const uDom = robustDomain((powiaty || metros).rows.map((r) => r.v.unemployment), 0.03) || [0.02, 0.15];
  const uColor = colorScale({ type: "seq", domain: uDom, ramp: RAMPS.heat });
  const scatter = createScatter(aBody, {
    height: 310, points: [],
    x: { label: t("Average wage"), fmt: money },
    y: { label: t("PIT per person"), fmt: money },
    size: { label: t("Population"), fmt: count3, max: 14, min: 1.6 },
    color: (c) => uColor(c), colorLabel: t("Unemployment"), colorFmt: (v) => pct(v),
    onHover: (p) => { link.hover(p ? rowsHighlight(lv(), [p.row]) : null); payTable.setHot(p ? p.key : null, false); },
    onClick: (p) => lv().focus(p.row),
    onBrush: (set) => {
      const sel = set ? lv().rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(lv(), sel, { dim: true }) : null, { frame: sel.length > 1 });
      payTable.setSelected(set);
      selInfo.innerHTML = sel.length ? `${selectedHtml(level, sel.length)} &middot; ${esc(people(sel.reduce((a, r) => a + (r.v.population || 0), 0)))} ${frameBtn()}<button type="button" class="adv-mini" data-clear>${esc(t("Clear"))}</button>` : "";
    },
  });
  aBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.heat, domain: uDom, fmt: (v) => fmtShort("pct", v), label: t("Unemployment") }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  aBody.appendChild(selInfo);
  const clearSel = () => { scatter.setSelected(null); payTable.setSelected(null); link.base(null); selInfo.innerHTML = ""; };
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) clearSel(); });
  aBody.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${esc(t("Pay table"))}</h4>`);
  const payTable = createTable(aBody, {
    caption: t("Wage and PIT per person"), rank: true, maxHeight: 260, rows: [], search: t("Search places"),
    columns: [
      { key: "name", label: t("Place"), align: "l", value: (r) => r.name, html: (r) => `${esc(r.name)}${r.level === "states" ? "" : ` <span class="sub">${esc(r.sub)}</span>`}` },
      { key: "wage", label: t("Wage"), value: (r) => r.v.wage, text: (r) => dollars(r.v.wage) },
      { key: "pit", label: t("PIT"), value: (r) => r.v.pit, text: (r) => dollars(r.v.pit) },
      { key: "unemployment", label: t("Unemp."), value: (r) => r.v.unemployment, html: (r) => (fin(r.v.unemployment) ? `<span class="dot" style="background:${uColor(r.v.unemployment)}"></span>${pct(r.v.unemployment)}` : "\u2013") },
    ],
    sort: { key: "pit", dir: "desc" },
    onHover: (r) => { link.hover(r ? rowsHighlight(lv(), [r]) : null); scatter.setHot(r ? r.key : null); },
    onClick: (r) => lv().focus(r),
  });
  function drawPay() {
    clearSel();
    const rows = lv().rows.filter((r) => fin(r.v.wage) && fin(r.v.pit));
    scatter.update({
      points: rows.map((r) => ({ key: r.key, x: r.v.wage, y: r.v.pit, s: r.v.population, c: r.v.unemployment, label: r.name, sub: r.sub, row: r })),
      labels: topBy(rows, (r) => r.v.population, { n: level === "states" ? 8 : 6 }).map((x) => x.r.key),
      refX: fin(n.wage) ? [{ v: n.wage, label: t("Poland") }] : [],
      refY: fin(n.pit) ? [{ v: n.pit, label: t("Poland") }] : [],
    });
    payTable.setRows(rows);
  }
  drawPay();

  // --- unemployment ---------------------------------------------------------------------------------------------
  let uHist = null;
  const uBody = section(el, { title: t("Unemployment"), note: esc([t("Registered unemployment rate (GUS)."), powiaty ? t("The chart counts powiaty; hover a bar to outline them.") : ""].filter(Boolean).join(" ")) });
  const uCtl = document.createElement("div");
  uCtl.className = "adv-row";
  uBody.appendChild(uCtl);
  const ub = lensButton(app, "unemployment", t("Unemployment lens"));
  if (ub) uCtl.appendChild(ub);
  if (powiaty) {
    const hHost = document.createElement("div");
    uBody.appendChild(hHost);
    uHist = histogram(hHost, {
      values: powiaty.rows.map((r) => ({ key: r.key, v: r.v.unemployment, w: r.v.population })), bins: 28, domain: [0, 0.22], height: 120,
      fmt: (v) => fmtShort("pct", v), label: t("Histogram of powiat unemployment rates"),
      countText: (c) => t.plural(c, { one: "{n} powiat", other: "{n} powiaty" }),
      colorOf: (_, f) => colorScale({ type: "seq", domain: [0, 1], ramp: RAMPS.heat })(f),
      markers: fin(n.unemployment) ? [{ v: n.unemployment, label: t("Poland {v}", { v: pct(n.unemployment) }) }] : [],
      onHover: (bin) => link.hover(bin ? rowsHighlight(powiaty, bin.keys.map((k) => powiaty.byKey.get(k)), { dim: true }) : null),
    });
  }
  const uHost = document.createElement("div");
  let uLevel = "states";
  segmented(uBody, { label: t("Areas"), value: uLevel, options: [{ value: "states", label: t("Voivodeships") }, { value: "metros", label: t("Large metros") }], onChange: (v) => { uLevel = v; drawU(); } });
  uBody.appendChild(uHost);
  function drawU() {
    uHost.innerHTML = "";
    const lvU = uLevel === "states" ? states : metros;
    const min = uLevel === "states" ? 0 : METRO_MIN;
    const k = uLevel === "states" ? 5 : 8;
    const high = topBy(lvU.rows, (r) => r.v.unemployment, { n: k, min });
    const low = topBy(lvU.rows, (r) => r.v.unemployment, { n: k, min, asc: true });
    const max = Math.max(...high.map((x) => x.v));
    const mk = (list) => list.map((x) => ({ key: x.r.key, label: x.r.name, sub: uLevel === "metros" ? x.r.sub : "", value: x.v, text: pct(x.v), tone: x.v > n.unemployment * 1.03 ? "bad" : x.v < n.unemployment * 0.97 ? "good" : null, row: x.r }));
    const o = { max, onHover: (r) => link.hover(r ? rowsHighlight(lvU, [r.row]) : null), onClick: (r) => lvU.focus(r.row) };
    uHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${esc(t("Highest"))}</h4>`);
    barList(uHost, { ...o, rows: mk(high) });
    uHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${esc(t("Lowest"))}</h4>`);
    barList(uHost, { ...o, rows: mk(low) });
    if (uLevel === "metros") uHost.insertAdjacentHTML("beforeend", `<p class="adv-note">${esc(t("Metros of {n}+ people.", { n: count3(METRO_MIN) }))}</p>`);
  }
  drawU();

  // --- wages ----------------------------------------------------------------------------------------------------
  const wBody = section(el, { title: t("Where work pays most"), note: esc(t("Average gross monthly wage, by employer seat.")) });
  const wHost = document.createElement("div");
  let wLevel = powiaty ? "powiaty" : "states";
  segmented(wBody, { label: t("Areas"), value: wLevel, options: [...(powiaty ? [{ value: "powiaty", label: t("Powiaty") }] : []), { value: "states", label: t("Voivodeships") }], onChange: (v) => { wLevel = v; drawW(); } });
  wBody.appendChild(wHost);
  function drawW() {
    wHost.innerHTML = "";
    const lvW = data.levels[wLevel];
    const k = wLevel === "states" ? 5 : 8;
    const high = topBy(lvW.rows, (r) => r.v.wage, { n: k });
    const low = topBy(lvW.rows, (r) => r.v.wage, { n: k, asc: true });
    const max = Math.max(...high.map((x) => x.v));
    const mk = (list) => list.map((x) => ({ key: x.r.key, label: x.r.name, sub: wLevel === "states" ? "" : x.r.sub, value: x.v, text: dollars(x.v), row: x.r }));
    const o = { max, onHover: (r) => link.hover(r ? rowsHighlight(lvW, [r.row]) : null), onClick: (r) => lvW.focus(r.row) };
    wHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${esc(t("Highest"))}</h4>`);
    barList(wHost, { ...o, rows: mk(high), ariaLabel: t("Highest wages") });
    wHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${esc(t("Lowest"))}</h4>`);
    barList(wHost, { ...o, rows: mk(low), ariaLabel: t("Lowest wages") });
  }
  drawW();

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["pl_stats_labour", "pl_stats_prosperity"], [
    esc(t("Wages are published per powiat and counted where the employer is; a gmina shows its powiat's wage.")),
    esc(t("PIT per person is the gminas' planned share of personal income tax divided by residents: it follows where taxpayers live, and is no measure of household income.")),
    esc(t("Registered unemployment counts people signed on at a labour office; it runs above the survey rate in some regions and below it in others.")),
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? lv().rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      payTable.setHot(r ? r.key : null);
      if (uHist && powiaty) {
        const p = h.cell >= 0 ? powiaty.rowAtCell(h.cell) : null;
        uHist.setHot(p ? uHist.binOf(p.v.unemployment)?.i ?? null : null);
      }
    },
    onEscape() {
      if (scatter.selected) { clearSel(); return true; }
      return false;
    },
  };
}

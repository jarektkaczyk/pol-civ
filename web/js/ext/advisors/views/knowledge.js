// Knowledge advisor: higher education, universities and the Science yield.
import { esc, fin, ratio, colorScale, RAMPS } from "../core/util.js";
import { money, pct, int, count3, fmtShort, fmtValue, signedPct } from "../core/fmt.js";
import { barList, histogram, rampLegend } from "../core/charts.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, mapPicker, frameBtn, sourcesHtml, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { scienceLens } from "../core/lenses.js";
import { t, num } from "../../../i18n.js";

const TIMES = "\u00d7";
// Bold the count in an escaped plural text ("<b>12</b> powiaty").
const boldN = (text, n) => esc(text).replace(esc(int(n)), `<b>${esc(int(n))}</b>`);
// A count in short form; a scale word (K, M; tys., mln) takes the plural of a large number.
const big = (v) => (Math.abs(v) >= 1e4 ? 1e6 : Math.round(v));
const people = (v) => t.plural(big(v), { one: "{v} person", other: "{v} people" }, { v: count3(v) });
const LEVEL_COUNT = {
  powiaty: (n) => t.plural(n, { one: "{n} powiat", other: "{n} powiaty" }),
  metros: (n) => t.plural(n, { one: "{n} metro", other: "{n} metros" }),
  states: (n) => t.plural(n, { one: "{n} voivodeship", other: "{n} voivodeships" }),
};

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const nation = app.data.nation;
  const { metros, powiaty, counties } = data.levels;
  const sci = nation.yields?.find((y) => y.key === "science");
  const plSci = n.yields?.science;
  const plWorkers = n.workers ?? n.employed;
  const plShare = ratio(plSci, plWorkers);
  const wavg = (k) => {
    if (!counties) return null;
    let a = 0, w = 0;
    for (const r of counties.rows) if (fin(r.v[k]) && fin(r.v.population)) { a += r.v[k] * r.v.population; w += r.v.population; }
    return w ? a / w : null;
  };
  const students = counties ? counties.rows.reduce((a, r) => a + (fin(r.v.students) && fin(r.v.population) ? (r.v.students * r.v.population) / 1000 : 0), 0) : null;
  const hasLens = (id) => !!app.lensById?.get(id);

  el.insertAdjacentHTML("beforeend", tiles([
    { label: t("Science workers"), value: count3(plSci), sub: t("{share} of workers", { share: pct(plShare) }), color: sci?.color },
    { label: t("Higher education"), value: pct(wavg("higher_ed")), sub: t("residents 13+, NSP 2021") },
    { label: t("University students"), value: count3(students), sub: t("in Polish gminas") },
  ]));

  // --- the map: higher education by default (the scatter's x axis), students, or science jobs by metro ---------
  const mapRow = document.createElement("div");
  mapRow.className = "adv-sec adv-mapsec";
  el.appendChild(mapRow);
  const picker = mapPicker(ctx, mapRow, {
    value: hasLens("higher_ed") ? "higher_ed" : "science",
    options: [
      ...(hasLens("higher_ed") ? [{ value: "higher_ed", label: t("Degrees"), lens: () => "higher_ed" }] : []),
      ...(hasLens("students") ? [{ value: "students", label: t("Students"), lens: () => "students" }] : []),
      { value: "science", label: t("Science jobs"), lens: () => scienceLens(data) },
      { value: "terrain", label: t("Terrain"), lens: () => null },
    ],
  });

  // --- science yield --------------------------------------------------------------------------------------------
  const sBody = section(el, { title: t("The Science yield"), note: esc(sci?.description ? t(sci.description) : t("Workers in information & communication and in professional, scientific & technical services.")) });
  const sHost = document.createElement("div");
  let mode = "share";
  segmented(sBody, { label: t("Rank by"), value: mode, options: [{ value: "share", label: t("Share of workers") }, { value: "abs", label: t("Most workers") }], onChange: (v) => { mode = v; drawSci(); } });
  const sMap = document.createElement("button");
  sMap.type = "button";
  sMap.className = "adv-mini";
  sMap.textContent = t("Colour the map by science jobs");
  sMap.addEventListener("click", () => picker.set("science"));
  sBody.querySelector(".adv-seg")?.after(sMap);
  sBody.appendChild(sHost);
  const share = (r) => ratio(r.v.y_science, r.v.workers);
  function drawSci() {
    sHost.innerHTML = "";
    const list = mode === "abs" ? topBy(metros.rows, (r) => r.v.y_science, { n: 12 }) : topBy(metros.rows, share, { n: 12 });
    barList(sHost, {
      rank: true, ariaLabel: t("Science leaders"),
      rows: list.map((x) => ({ key: x.r.key, label: x.r.name, sub: mode === "abs" ? pct(share(x.r)) : t("{ratio} Poland", { ratio: `${TIMES}${num(share(x.r) / plShare, 2)}` }), value: x.v, text: mode === "abs" ? count3(x.v) : pct(x.v), color: sci?.color, row: x.r })),
      onHover: (r) => link.hover(r ? rowsHighlight(metros, [r.row]) : null),
      onClick: (r) => metros.focus(r.row),
    });
  }
  drawSci();

  if (!counties) {
    el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["pl_stats_labour"], []));
    return {};
  }

  // --- degrees vs PIT -------------------------------------------------------------------------------------------
  const dBody = section(el, { title: t("Degrees and income"), note: esc(t("Share of residents 13+ with a higher-education diploma against PIT revenue per resident; colour = population change. Drag to select; hover the map to find a place.")) });
  const dCtl = document.createElement("div");
  dCtl.className = "adv-row";
  dBody.appendChild(dCtl);
  const lvOpts = [...(powiaty ? [{ value: "powiaty", label: t("Powiaty") }] : []), { value: "metros", label: t("Metros") }, { value: "states", label: t("Voivodeships") }];
  let level = lvOpts[0].value;
  segmented(dCtl, { label: t("Places"), value: level, options: lvOpts, onChange: (v) => { level = v; drawDeg(); } });
  const lv = () => data.levels[level];
  const gDom = [-0.12, 0.12];
  const gColor = colorScale({ type: "div", domain: gDom, mid: 0 });
  const scatter = createScatter(dBody, {
    height: 300, points: [],
    x: { label: t("Higher education"), fmt: (v) => fmtShort("pct", v) },
    y: { label: t("PIT per person"), fmt: money },
    size: { label: t("Population"), fmt: count3, max: 14, min: 1.6 },
    color: (c) => gColor(c), colorLabel: t("Population change"), colorFmt: (v) => signedPct(v),
    onHover: (p) => link.hover(p ? rowsHighlight(lv(), [p.row]) : null),
    onClick: (p) => lv().focus(p.row),
    onBrush: (set) => {
      const sel = set ? lv().rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(lv(), sel, { dim: true }) : null, { frame: sel.length > 1 });
      selInfo.innerHTML = sel.length ? `${boldN((LEVEL_COUNT[level] || LEVEL_COUNT.states)(sel.length), sel.length)} &middot; ${esc(people(sel.reduce((a, r) => a + (r.v.population || 0), 0)))} ${frameBtn()}<button type="button" class="adv-mini" data-clear>${esc(t("Clear"))}</button>` : "";
    },
  });
  dBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.div, domain: gDom, fmt: (v) => fmtShort("signed", v), label: t("Population change"), mid: 0 }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  dBody.appendChild(selInfo);
  const clearSel = () => { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; };
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) clearSel(); });
  function drawDeg() {
    clearSel();
    const rows = lv().rows.filter((r) => fin(r.v.higher_ed) && fin(r.v.pit));
    scatter.update({
      points: rows.map((r) => ({ key: r.key, x: r.v.higher_ed, y: r.v.pit, s: r.v.population, c: r.v.growth, label: r.name, sub: r.sub, row: r })),
      labels: topBy(rows, (r) => r.v.population, { n: 6 }).map((x) => x.r.key),
    });
  }
  drawDeg();

  // --- university towns -----------------------------------------------------------------------------------------
  const uBody = section(el, { title: t("University towns"), note: esc(t("Gminas with a university, by students per 1,000 residents. Hover a bar to outline the gmina.")) });
  const uni = counties.rows.filter((r) => fin(r.v.students) && r.v.students > 0);
  if (hasLens("students")) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "adv-mini";
    b.textContent = t("Colour the map by students");
    b.addEventListener("click", () => picker.set("students"));
    uBody.appendChild(b);
  }
  let uMode = "rate";
  const uHost = document.createElement("div");
  segmented(uBody, { label: t("Rank by"), value: uMode, options: [{ value: "rate", label: t("Per 1,000 residents") }, { value: "abs", label: t("Most students") }], onChange: (v) => { uMode = v; drawUni(); } });
  uBody.appendChild(uHost);
  const count = (r) => (fin(r.v.students) && fin(r.v.population) ? (r.v.students * r.v.population) / 1000 : null);
  function drawUni() {
    uHost.innerHTML = "";
    const list = uMode === "abs" ? topBy(uni, count, { n: 12 }) : topBy(uni, (r) => r.v.students, { n: 12, min: 20000 });
    barList(uHost, {
      rank: true, ariaLabel: t("University towns"),
      rows: list.map((x) => ({ key: x.r.key, label: x.r.name, sub: uMode === "abs" ? t("{v} per 1,000", { v: fmtValue("float", x.r.v.students) }) : t.plural(big(count(x.r)), { one: "{v} student", other: "{v} students" }, { v: count3(count(x.r)) }), value: x.v, text: uMode === "abs" ? count3(x.v) : fmtValue("float", x.v), row: x.r })),
      onHover: (r) => link.hover(r ? rowsHighlight(counties, [r.row]) : null),
      onClick: (r) => counties.focus(r.row),
    });
    if (uMode === "rate") uHost.insertAdjacentHTML("beforeend", `<p class="adv-note">${esc(t("Gminas of 20K+ people."))}</p>`);
  }
  drawUni();

  // --- higher education across gminas ---------------------------------------------------------------------------
  let heHist = null;
  if (powiaty) {
    const hBody = section(el, { title: t("Who holds a degree"), note: esc(t("Powiaty by the share of residents 13+ with a higher-education diploma (NSP 2021). Hover a bar to outline those powiaty.")) });
    const hHost = document.createElement("div");
    hBody.appendChild(hHost);
    const plHe = wavg("higher_ed");
    heHist = histogram(hHost, {
      values: powiaty.rows.map((r) => ({ key: r.key, v: r.v.higher_ed })), bins: 28, domain: [0.05, 0.45], height: 120,
      fmt: (v) => fmtShort("pct", v), countText: (c) => t.plural(c, { one: "{n} powiat", other: "{n} powiats" }), label: t("Histogram of powiat higher-education shares"),
      colorOf: (_, t) => colorScale({ type: "seq", domain: [0, 1], ramp: RAMPS.seq })(t),
      markers: fin(plHe) ? [{ v: plHe, label: t("Poland {share}", { share: pct(plHe) }) }] : [],
      onHover: (bin) => link.hover(bin ? rowsHighlight(powiaty, bin.keys.map((k) => powiaty.byKey.get(k)), { dim: true }) : null),
    });
  }

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["pl_stats_labour", "pl_census_2021", "pl_stats_population", "pl_soc_universities"], [
    esc(t("Science workers are counted where the employer is and cover whole PKD sections: an IT firm's receptionist counts, a hospital's researcher does not.")),
    esc(t("Higher education comes from the 2021 census and is published per powiat; every gmina shows its powiat's share.")),
    esc(t("Students are counted where their university is, not where they live.")),
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? lv().rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      if (heHist && powiaty) {
        const p = h.cell >= 0 ? powiaty.rowAtCell(h.cell) : null;
        heHist.setHot(p ? heHist.binOf(p.v.higher_ed)?.i ?? null : null);
      }
    },
    onEscape() {
      if (scatter.selected) { clearSel(); return true; }
      return false;
    },
  };
}

// People advisor: population, growth, density, age, migration and the Ukrainians who came after 2022.
import { esc, fin, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { pct, int, signedPct, count3, fmtShort, fmtValue } from "../core/fmt.js";
import { barList, histogram, rampLegend } from "../core/charts.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, mapPicker, frameBtn, sourcesHtml, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { growthLens } from "../core/lenses.js";
import { t, date } from "../../../i18n.js";

// Escape a translated template and fill its {placeholders} with HTML.
const tHtml = (text, vars) => esc(text).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
// Bold the count in an escaped plural text ("<b>12</b> gminas").
const boldN = (text, n) => esc(text).replace(esc(int(n)), `<b>${esc(int(n))}</b>`);
// A count of people in short form; a scale word (K, M; tys., mln) takes the plural of a large number.
const people = (v) => t.plural(Math.abs(v) >= 1e4 ? 1e6 : Math.round(v), { one: "{v} person", other: "{v} people" }, { v: count3(v) });

const POWIAT_MIN = 50000;

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const { states, metros, powiaty, counties } = data.levels;
  const yrs = (n.growth_years || []).join("-");

  el.insertAdjacentHTML("beforeend", tiles([
    { label: t("Residents"), value: count3(n.population), sub: app.data.nation?.population_date ? date(app.data.nation.population_date) : String(app.data.nation?.years?.population || "") },
    { label: t("Change {years}", { years: yrs }), value: signedPct(n.growth, 2), sub: t("on today's borders") },
    { label: t("Metro areas"), value: int(metros.rows.length), sub: counties ? t.plural(counties.rows.length, { one: "{n} gmina", other: "{n} gminas" }) : "" },
  ]));

  // --- the map: growth by default, so the map tells the same story as the first chart ---------------------------
  const mapRow = document.createElement("div");
  mapRow.className = "adv-sec adv-mapsec";
  el.appendChild(mapRow);
  const lensOpt = (value, label, id) => ({ value, label, lens: () => id });
  const hasLens = (id) => !!app.lensById?.get(id);
  const picker = mapPicker(ctx, mapRow, {
    value: "growth",
    options: [
      hasLens("growth") ? lensOpt("growth", t("Growth"), "growth") : { value: "growth", label: t("Growth"), lens: () => growthLens(data, "metros") },
      ...[["density", t("Density")], ["age", t("Age")], ["migration", t("Migration")], ["ukrainians", t("Ukrainians")]].filter(([id]) => hasLens(id)).map(([id, label]) => lensOpt(id, label, id)),
      { value: "terrain", label: t("Terrain"), lens: () => null },
    ],
  });

  // --- growth ---------------------------------------------------------------------------------------------------
  let gLevel = "metros";
  const gBody = section(el, { title: t("Who is growing, who is shrinking"), note: esc(t("Population change {years}, both years on today's borders (GUS). Powiaty of {min}+ people.", { years: yrs, min: int(POWIAT_MIN) })) });
  const gHost = document.createElement("div");
  segmented(gBody, {
    label: t("Areas"), value: gLevel,
    options: [{ value: "metros", label: t("Metros") }, ...(powiaty ? [{ value: "powiaty", label: t("Powiaty") }] : []), { value: "states", label: t("Voivodeships") }],
    onChange: (v) => { gLevel = v; drawGrowth(); },
  });
  gBody.appendChild(gHost);
  function drawGrowth() {
    gHost.innerHTML = "";
    const lv = data.levels[gLevel];
    const min = gLevel === "powiaty" ? POWIAT_MIN : 0;
    const k = gLevel === "states" ? 5 : 8;
    const fast = topBy(lv.rows, (r) => r.v.growth, { n: k, min });
    const slow = topBy(lv.rows, (r) => r.v.growth, { n: k, min, asc: true });
    const max = Math.max(...[...fast, ...slow].map((x) => Math.abs(x.v)));
    const mk = (list) => list.map((x) => ({ key: x.r.key, label: x.r.name, sub: gLevel === "states" ? "" : x.r.sub, value: x.v, text: signedPct(x.v), tone: x.v >= 0 ? "good" : "bad", row: x.r }));
    const opts = {
      diverging: true, max,
      onHover: (r) => link.hover(r ? rowsHighlight(lv, [r.row]) : null),
      onClick: (r) => lv.focus(r.row),
    };
    gHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${esc(fast.every((x) => x.v > 0) ? t("Fastest growing") : t("Least shrinking"))}</h4>`);
    barList(gHost, { ...opts, rows: mk(fast), ariaLabel: t("Fastest growing") });
    gHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${esc(slow.every((x) => x.v < 0) ? t("Fastest shrinking") : t("Slowest growing"))}</h4>`);
    barList(gHost, { ...opts, rows: mk(slow), ariaLabel: t("Fastest shrinking") });
  }
  drawGrowth();

  if (!counties) {
    el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["pl_stats_population"], []));
    return {};
  }

  // --- density --------------------------------------------------------------------------------------------------
  const halfDense = (() => {
    const s = counties.rows.filter((r) => fin(r.v.density) && fin(r.v.population)).sort((a, b) => a.v.density - b.v.density);
    const tot = s.reduce((a, r) => a + r.v.population, 0);
    let acc = 0;
    for (const r of s) { acc += r.v.population; if (acc >= tot / 2) return r.v.density; }
    return null;
  })();
  const dBody = section(el, {
    title: t("How crowded"),
    note: fin(halfDense)
      ? tHtml(t("Gminas by residents per km\u00b2 (log scale). Switch to {people} to weight each gmina by its population: half of Poland lives in gminas of more than {density} people per km\u00b2. Hover a bar to see those gminas; click to keep them outlined."), { people: `<i>${esc(t("People").toLowerCase())}</i>`, density: esc(int(halfDense)) })
      : tHtml(t("Gminas by residents per km\u00b2 (log scale). Switch to {people} to weight each gmina by its population. Hover a bar to see those gminas; click to keep them outlined."), { people: `<i>${esc(t("People").toLowerCase())}</i>` }),
  });
  const dCtl = document.createElement("div");
  dCtl.className = "adv-row";
  dBody.appendChild(dCtl);
  let weighted = false, pinnedBin = null;
  segmented(dCtl, { label: t("Count"), value: "gminas", options: [{ value: "gminas", label: t("Gminas") }, { value: "people", label: t("People") }], onChange: (v) => { weighted = v === "people"; drawHist(); } });
  const dLens = document.createElement("button");
  dLens.type = "button";
  dLens.className = "adv-mini";
  dLens.textContent = t("Colour the map by density");
  dLens.addEventListener("click", () => picker.set("density"));
  dCtl.appendChild(dLens);
  const histHost = document.createElement("div");
  dBody.appendChild(histHost);
  const binInfo = document.createElement("div");
  binInfo.className = "adv-brushinfo";
  dBody.appendChild(binInfo);
  let hist = null;
  const plDensity = counties.rows.reduce((a, r) => a + (r.v.population || 0), 0) / counties.rows.reduce((a, r) => a + (r.v.area_km2 || 0), 0);
  const cByKey = counties.byKey;
  const densRamp = RAMPS.heat;
  function drawHist() {
    histHost.innerHTML = "";
    const vals = counties.rows.map((r) => ({ key: r.key, v: r.v.density, w: r.v.population }));
    const dom = [5, 5000];
    hist = histogram(histHost, {
      values: vals, log: true, bins: 30, domain: dom, weighted, height: 130,
      fmt: (v) => fmtShort("float", v), countText: (c) => t.plural(c, { one: "{n} gmina", other: "{n} gminas" }), weightFmt: (w) => people(w),
      label: t("Histogram of gmina population density"),
      colorOf: (_, t) => colorScale({ type: "seq", domain: [0, 1], ramp: densRamp })(t),
      markers: fin(plDensity) ? [{ v: plDensity, label: t("Poland") }] : [],
      onHover: (bin) => link.hover(bin ? rowsHighlight(counties, bin.keys.map((k) => cByKey.get(k)), { dim: true }) : null),
      onClick: (bin) => {
        pinnedBin = pinnedBin === bin.i ? null : bin.i;
        const rows = pinnedBin != null ? bin.keys.map((k) => cByKey.get(k)) : [];
        link.base(rows.length ? rowsHighlight(counties, rows, { dim: true }) : null, { frame: rows.length > 1 });
        binInfo.innerHTML = rows.length ? `${boldN(t.plural(rows.length, { one: "{n} gmina of {lo}-{hi} people/km\u00b2", other: "{n} gminas of {lo}-{hi} people/km\u00b2" }, { lo: fmtShort("float", bin.x0), hi: fmtShort("float", bin.x1) }), rows.length)} &middot; ${esc(people(rows.reduce((a, r) => a + (r.v.population || 0), 0)))} ${frameBtn()}<button type="button" class="adv-mini" data-clear>${esc(t("Clear"))}</button>` : "";
      },
    });
  }
  binInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { pinnedBin = null; link.base(null); binInfo.innerHTML = ""; } });
  drawHist();

  // --- age and migration ----------------------------------------------------------------------------------------
  const aBody = section(el, { title: t("Age and migration"), note: esc(t("Each dot is a gmina: median age across, net migration up, size = population, colour = density. Young, growing suburbs sit top left; ageing, emptying villages bottom right. Drag a rectangle to select gminas; they light up on the map.")) });
  const aCtl = document.createElement("div");
  aCtl.className = "adv-row";
  aBody.appendChild(aCtl);
  aCtl.innerHTML = `<span class="adv-note">${esc(t("Colour the map by"))}</span>${hasLens("age") ? `<button type="button" class="adv-mini" data-map="age">${esc(t("median age"))}</button>` : ""}${hasLens("migration") ? `<button type="button" class="adv-mini" data-map="migration">${esc(t("migration"))}</button>` : ""}`;
  aCtl.addEventListener("click", (e) => { const v = e.target.closest("[data-map]")?.dataset.map; if (v) picker.set(v); });
  const dDom = robustDomain(counties.rows.map((r) => r.v.density), 0.02, true) || [10, 2000];
  const dColor = colorScale({ type: "seq", domain: dDom, log: true, ramp: RAMPS.heat });
  const big = topBy(counties.rows, (r) => r.v.population, { n: 6 }).map((x) => x.r.key);
  const medAge = medianOf(counties.rows, "median_age");
  const scatter = createScatter(aBody, {
    height: 310,
    points: counties.rows.filter((r) => fin(r.v.median_age) && fin(r.v.net_migration)).map((r) => ({ key: r.key, x: r.v.median_age, y: r.v.net_migration, s: r.v.population, c: r.v.density, label: r.name, sub: r.sub, row: r })),
    x: { label: t("Median age"), fmt: (v) => int(v) },
    y: { label: t("Net migration per 1,000"), fmt: (v) => fmtShort("float", v) },
    size: { label: t("Population"), fmt: count3, max: 14, min: 1.4 },
    color: (c) => dColor(c), colorLabel: t("Density"), colorFmt: (v) => `${fmtValue("float", v)} /km\u00b2`,
    labels: big,
    refX: fin(medAge) ? [{ v: medAge, label: t("median gmina") }] : [],
    refY: [{ v: 0, label: "" }],
    onHover: (p) => link.hover(p ? rowsHighlight(counties, [p.row]) : null),
    onClick: (p) => counties.focus(p.row),
    onBrush: (set) => {
      const sel = set ? counties.rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(counties, sel, { dim: true }) : null, { frame: sel.length > 1 });
      selInfo.innerHTML = sel.length ? selSummary(sel) : "";
    },
  });
  aBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.heat, domain: dDom, log: true, fmt: (v) => fmtShort("float", v), label: t("People per km\u00b2") }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  aBody.appendChild(selInfo);
  function selSummary(sel) {
    const pop = sel.reduce((a, r) => a + (r.v.population || 0), 0);
    const top = [...sel].sort((a, b) => (b.v.population || 0) - (a.v.population || 0)).slice(0, 5);
    return `${boldN(t.plural(sel.length, { one: "{n} gmina", other: "{n} gminas" }), sel.length)} &middot; ${esc(t("{people} ({share} of Poland)", { people: people(pop), share: pct(pop / n.population) }))}<br><span class="sub">${tHtml(t("Largest: {places}"), { places: top.map((r) => `${esc(r.name)}, ${esc(r.sub)}`).join(" &middot; ") })}</span> ${frameBtn()}<button type="button" class="adv-mini" data-clear>${esc(t("Clear"))}</button>`;
  }
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; } });

  // --- Ukrainians -----------------------------------------------------------------------------------------------
  if (powiaty && powiaty.field("ukrainians")) {
    const uBody = section(el, { title: t("Where Ukrainians live"), note: esc(t("Ukrainian citizens with a PESEL UKR number (temporary protection) per 1,000 residents, by powiat. Hover a bar to outline the powiat.")) });
    if (hasLens("ukrainians")) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "adv-mini";
      b.textContent = t("Colour the map by Ukrainians");
      b.addEventListener("click", () => picker.set("ukrainians"));
      uBody.appendChild(b);
    }
    const list = topBy(powiaty.rows, (r) => r.v.ukrainians, { n: 10 });
    const total = powiaty.rows.reduce((a, r) => a + (fin(r.v.ukrainians) && fin(r.v.population) ? (r.v.ukrainians * r.v.population) / 1000 : 0), 0);
    uBody.insertAdjacentHTML("beforeend", `<p class="adv-note">${tHtml(t("About {people} in Poland ({share} of residents)."), { people: esc(people(total)).replace(esc(count3(total)), `<b>${esc(count3(total))}</b>`), share: esc(pct(total / n.population)) })}</p>`);
    barList(uBody, {
      rank: true, ariaLabel: t("Powiaty with the most Ukrainians per 1,000 residents"),
      rows: list.map((x) => ({ key: x.r.key, label: x.r.name, sub: x.r.sub, value: x.v, text: fmtValue("float", x.v), row: x.r })),
      onHover: (r) => link.hover(r ? rowsHighlight(powiaty, [r.row]) : null),
      onClick: (r) => powiaty.focus(r.row),
    });
  }

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["pl_stats_population", "pl_foreigners", "pl_geo_teryt"], [
    esc(t("A gmina's dot shows its median age, worked out from five-year age groups; the median of a group of gminas is not the average of their medians.")),
    esc(t("Net migration counts registered moves only: people who rent without registering their address are missed.")),
    ...(data.countiesOffMap ? [esc(t.plural(data.countiesOffMap, { one: "{n} of the smallest gminas is smaller than one hex, so selecting it outlines nothing on the map.", other: "{n} of the smallest gminas are smaller than one hex, so selecting them outlines nothing on the map." }))] : []),
  ]));

  return {
    onMapHover(h) {
      const r = h.cell >= 0 ? counties.rowAtCell(h.cell) : null;
      scatter.setHot(r ? r.key : null);
      hist?.setHot(r ? hist.binOf(r.v.density)?.i ?? null : null);
    },
    onEscape() {
      if (scatter.selected || pinnedBin != null) {
        scatter.setSelected(null); pinnedBin = null; link.base(null); selInfo.innerHTML = ""; binInfo.innerHTML = "";
        return true;
      }
      return false;
    },
  };
}

function medianOf(rows, k) {
  const s = rows.map((r) => r.v[k]).filter(fin).sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : null;
}

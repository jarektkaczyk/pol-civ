// People advisor: population, growth, density, age, migration and the Ukrainians who came after 2022.
import { esc, fin, colorScale, robustDomain, RAMPS } from "../core/util.js";
import { pct, int, signedPct, count3, fmtShort, fmtValue } from "../core/fmt.js";
import { barList, histogram, rampLegend } from "../core/charts.js";
import { createScatter } from "../core/scatter.js";
import { section, tiles, segmented, mapPicker, frameBtn, sourcesHtml, topBy } from "../core/view.js";
import { rowsHighlight } from "../core/data.js";
import { growthLens } from "../core/lenses.js";

const POWIAT_MIN = 50000;

export function mount(ctx) {
  const { app, data, el, link } = ctx;
  const n = data.nat;
  const { states, metros, powiaty, counties } = data.levels;
  const yrs = (n.growth_years || []).join("-");

  el.insertAdjacentHTML("beforeend", tiles([
    { label: "Residents", value: count3(n.population), sub: `31 December ${app.data.nation?.years?.population || ""}` },
    { label: `Change ${yrs}`, value: signedPct(n.growth, 2), sub: "on today's borders" },
    { label: "Metro areas", value: int(metros.rows.length), sub: counties ? `${int(counties.rows.length)} gminas` : "" },
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
      hasLens("growth") ? lensOpt("growth", "Growth", "growth") : { value: "growth", label: "Growth", lens: () => growthLens(data, "metros") },
      ...[["density", "Density"], ["age", "Age"], ["migration", "Migration"], ["ukrainians", "Ukrainians"]].filter(([id]) => hasLens(id)).map(([id, label]) => lensOpt(id, label, id)),
      { value: "terrain", label: "Terrain", lens: () => null },
    ],
  });

  // --- growth ---------------------------------------------------------------------------------------------------
  let gLevel = "metros";
  const gBody = section(el, { title: "Who is growing, who is shrinking", note: `Population change ${yrs}, both years on today's borders (GUS). Powiaty of ${int(POWIAT_MIN)}+ people.` });
  const gHost = document.createElement("div");
  segmented(gBody, {
    label: "Areas", value: gLevel,
    options: [{ value: "metros", label: "Metros" }, ...(powiaty ? [{ value: "powiaty", label: "Powiaty" }] : []), { value: "states", label: "Voivodeships" }],
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
    gHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${fast.every((x) => x.v > 0) ? "Fastest growing" : "Least shrinking"}</h4>`);
    barList(gHost, { ...opts, rows: mk(fast), ariaLabel: "Fastest growing" });
    gHost.insertAdjacentHTML("beforeend", `<h4 class="adv-h4">${slow.every((x) => x.v < 0) ? "Fastest shrinking" : "Slowest growing"}</h4>`);
    barList(gHost, { ...opts, rows: mk(slow), ariaLabel: "Fastest shrinking" });
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
  const dBody = section(el, { title: "How crowded", note: `Gminas by residents per km\u00b2 (log scale). Switch to <i>people</i> to weight each gmina by its population${fin(halfDense) ? `: half of Poland lives in gminas of more than ${int(halfDense)} people per km\u00b2` : ""}. Hover a bar to see those gminas; click to keep them outlined.` });
  const dCtl = document.createElement("div");
  dCtl.className = "adv-row";
  dBody.appendChild(dCtl);
  let weighted = false, pinnedBin = null;
  segmented(dCtl, { label: "Count", value: "gminas", options: [{ value: "gminas", label: "Gminas" }, { value: "people", label: "People" }], onChange: (v) => { weighted = v === "people"; drawHist(); } });
  const dLens = document.createElement("button");
  dLens.type = "button";
  dLens.className = "adv-mini";
  dLens.textContent = "Colour the map by density";
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
      fmt: (v) => fmtShort("float", v), unitLabel: "gminas", weightFmt: (w) => `${count3(w)} people`,
      label: "Histogram of gmina population density",
      colorOf: (_, t) => colorScale({ type: "seq", domain: [0, 1], ramp: densRamp })(t),
      markers: fin(plDensity) ? [{ v: plDensity, label: "Poland" }] : [],
      onHover: (bin) => link.hover(bin ? rowsHighlight(counties, bin.keys.map((k) => cByKey.get(k)), { dim: true }) : null),
      onClick: (bin) => {
        pinnedBin = pinnedBin === bin.i ? null : bin.i;
        const rows = pinnedBin != null ? bin.keys.map((k) => cByKey.get(k)) : [];
        link.base(rows.length ? rowsHighlight(counties, rows, { dim: true }) : null, { frame: rows.length > 1 });
        binInfo.innerHTML = rows.length ? `<b>${int(rows.length)}</b> gminas of ${fmtShort("float", bin.x0)}-${fmtShort("float", bin.x1)} people/km\u00b2 &middot; ${count3(rows.reduce((a, r) => a + (r.v.population || 0), 0))} people ${frameBtn()}<button type="button" class="adv-mini" data-clear>Clear</button>` : "";
      },
    });
  }
  binInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { pinnedBin = null; link.base(null); binInfo.innerHTML = ""; } });
  drawHist();

  // --- age and migration ----------------------------------------------------------------------------------------
  const aBody = section(el, { title: "Age and migration", note: "Each dot is a gmina: median age across, net migration up, size = population, colour = density. Young, growing suburbs sit top left; ageing, emptying villages bottom right. Drag a rectangle to select gminas; they light up on the map." });
  const aCtl = document.createElement("div");
  aCtl.className = "adv-row";
  aBody.appendChild(aCtl);
  aCtl.innerHTML = `<span class="adv-note">Colour the map by</span>${hasLens("age") ? `<button type="button" class="adv-mini" data-map="age">median age</button>` : ""}${hasLens("migration") ? `<button type="button" class="adv-mini" data-map="migration">migration</button>` : ""}`;
  aCtl.addEventListener("click", (e) => { const v = e.target.closest("[data-map]")?.dataset.map; if (v) picker.set(v); });
  const dDom = robustDomain(counties.rows.map((r) => r.v.density), 0.02, true) || [10, 2000];
  const dColor = colorScale({ type: "seq", domain: dDom, log: true, ramp: RAMPS.heat });
  const big = topBy(counties.rows, (r) => r.v.population, { n: 6 }).map((x) => x.r.key);
  const medAge = medianOf(counties.rows, "median_age");
  const scatter = createScatter(aBody, {
    height: 310,
    points: counties.rows.filter((r) => fin(r.v.median_age) && fin(r.v.net_migration)).map((r) => ({ key: r.key, x: r.v.median_age, y: r.v.net_migration, s: r.v.population, c: r.v.density, label: r.name, sub: r.sub, row: r })),
    x: { label: "Median age", fmt: (v) => String(+v.toFixed(0)) },
    y: { label: "Net migration per 1,000", fmt: (v) => fmtShort("float", v) },
    size: { label: "Population", fmt: count3, max: 14, min: 1.4 },
    color: (c) => dColor(c), colorLabel: "Density", colorFmt: (v) => `${fmtValue("float", v)} /km\u00b2`,
    labels: big,
    refX: fin(medAge) ? [{ v: medAge, label: "median gmina" }] : [],
    refY: [{ v: 0, label: "" }],
    onHover: (p) => link.hover(p ? rowsHighlight(counties, [p.row]) : null),
    onClick: (p) => counties.focus(p.row),
    onBrush: (set) => {
      const sel = set ? counties.rows.filter((r) => set.has(r.key)) : [];
      link.base(sel.length ? rowsHighlight(counties, sel, { dim: true }) : null, { frame: sel.length > 1 });
      selInfo.innerHTML = sel.length ? selSummary(sel) : "";
    },
  });
  aBody.insertAdjacentHTML("beforeend", rampLegend({ ramp: RAMPS.heat, domain: dDom, log: true, fmt: (v) => fmtShort("float", v), label: "People per km\u00b2" }));
  const selInfo = document.createElement("div");
  selInfo.className = "adv-brushinfo";
  aBody.appendChild(selInfo);
  function selSummary(sel) {
    const pop = sel.reduce((a, r) => a + (r.v.population || 0), 0);
    const top = [...sel].sort((a, b) => (b.v.population || 0) - (a.v.population || 0)).slice(0, 5);
    return `<b>${int(sel.length)}</b> gminas &middot; ${count3(pop)} people (${pct(pop / n.population)} of Poland)<br><span class="sub">Largest: ${top.map((r) => `${esc(r.name)}, ${esc(r.sub)}`).join(" &middot; ")}</span> ${frameBtn()}<button type="button" class="adv-mini" data-clear>Clear</button>`;
  }
  selInfo.addEventListener("click", (e) => { if (e.target.closest("[data-clear]")) { scatter.setSelected(null); link.base(null); selInfo.innerHTML = ""; } });

  // --- Ukrainians -----------------------------------------------------------------------------------------------
  if (powiaty && powiaty.field("ukrainians")) {
    const uBody = section(el, { title: "Where Ukrainians live", note: "Ukrainian citizens with a PESEL UKR number (temporary protection) per 1,000 residents, by powiat. Hover a bar to outline the powiat." });
    if (hasLens("ukrainians")) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "adv-mini";
      b.textContent = "Colour the map by Ukrainians";
      b.addEventListener("click", () => picker.set("ukrainians"));
      uBody.appendChild(b);
    }
    const list = topBy(powiaty.rows, (r) => r.v.ukrainians, { n: 10 });
    const total = powiaty.rows.reduce((a, r) => a + (fin(r.v.ukrainians) && fin(r.v.population) ? (r.v.ukrainians * r.v.population) / 1000 : 0), 0);
    uBody.insertAdjacentHTML("beforeend", `<p class="adv-note">About <b>${count3(total)}</b> people in Poland (${pct(total / n.population)} of residents).</p>`);
    barList(uBody, {
      rank: true, ariaLabel: "Powiaty with the most Ukrainians per 1,000 residents",
      rows: list.map((x) => ({ key: x.r.key, label: x.r.name, sub: x.r.sub, value: x.v, text: fmtValue("float", x.v), row: x.r })),
      onHover: (r) => link.hover(r ? rowsHighlight(powiaty, [r.row]) : null),
      onClick: (r) => powiaty.focus(r.row),
    });
  }

  el.insertAdjacentHTML("beforeend", sourcesHtml(data, ["pl_stats_population", "pl_foreigners", "pl_geo_teryt"], [
    "A gmina's dot shows its median age, worked out from five-year age groups; the median of a group of gminas is not the average of their medians.",
    "Net migration counts registered moves only: people who rent without registering their address are missed.",
    ...(data.countiesOffMap ? [`${int(data.countiesOffMap)} of the smallest gminas are smaller than one hex, so selecting them outlines nothing on the map.`] : []),
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

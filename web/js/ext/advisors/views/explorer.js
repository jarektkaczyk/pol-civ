// Explorer: the generic slice-and-dice. Pick a level, any columns, filter, sort, plot any X / Y / size / colour,
// brush points onto the map, and show a column as a map lens where one exists.
import { esc, fin, colorScale, robustDomain, extent, RAMPS, fillHtml } from "../core/util.js";
import { fmtValue, fmtShort, fmtCell, parseNum, count3, int } from "../core/fmt.js";
import { rampLegend, swatchLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { createScatter } from "../core/scatter.js";
import { section, segmented, selectBox, sourcesHtml, frameBtn } from "../core/view.js";
import { rowsHighlight, extendData } from "../core/data.js";
import { track } from "../../../app/analytics.js";
import { t } from "../../../i18n.js";

const DEFAULT_COLS = {
  states: ["population", "growth", "gdp_pc", "wage", "unemployment"],
  metros: ["states", "population", "growth", "gdp_pc", "wage"],
  powiaty: ["state", "population", "wage", "unemployment", "president_2025"],
  counties: ["state", "population", "density", "pit", "president_2025"],
  towns: ["state", "population", "growth", "wage", "pit"],
};
const DEFAULT_XY = {
  states: { x: "gdp_pc", y: "growth", s: "population", c: "wage" },
  metros: { x: "gdp_pc", y: "growth", s: "population", c: "wage" },
  powiaty: { x: "pit", y: "president_2025", s: "population", c: "higher_ed" },
  counties: { x: "pit", y: "president_2025", s: "population", c: "density" },
  towns: { x: "pit", y: "growth", s: "population", c: "unemployment" },
};
// Table headers: short enough for a ~60 px column (they wrap to two lines; a soft hyphen \u00ad marks where a long
// word may break). Plain text: escaped where they go into the header.
const SHORT = {
  population: t("People"), gdp_pc: t("GDP per person"), pit: t("PIT per person"), unemployment: t("Unemploy\u00adment"), area_km2: t("Area"),
  energy_mw: t("Mapped power"), median_age: t("Median age"), net_migration: t("Net migr\u00adation"), elderly: t("Aged 65+"),
  ukrainians: t("Ukrain\u00adians"), dwellings: t("New dwell\u00adings"), higher_ed: t("Higher educ\u00adation"), students: t("Stud\u00adents"),
  tourism: t("Tourist nights"), life_f: t("Life exp. women"), life_m: t("Life exp. men"), catholic: t("Catholic"), no_religion: t("No relig\u00adion"),
  mass: t("Mass attend\u00adance"), president_2025: t("Nawrocki 2025"), turnout_2025: t("Turnout 2025"), sejm_2023: t("Sejm 2023"),
  flood_2024: t("Flood 2024"), air_station: t("Air station"), n_towns: t("Towns"), n_gminas: t("Gminas"), core: t("Core town"),
  // towns: industry districts, citizens
  city_type: t("City type"), n_districts: t("Districts (n)"), dist_workers: t("Workers (district basis)"), dist_scope: t("Counted over"),
  top_industry: t("Top industry"), top_lq: t("Top LQ"), cz_median_age: t("Median age (gmina)"), cz_degree: t("Higher educ\u00adation"),
  cz_specialist: t("Top citizen"), cz_foreign_born: t("Ukrain\u00adians"), encampment: t("Garrison"),
};
// Operators are logic keys; OP_TEXT is what the reader sees.
const OPS = { num: [">", "\u2265", "<", "\u2264", "="], text: ["=", "contains", "\u2260"] };
const OP_TEXT = { contains: t("contains") };
const opText = (o) => OP_TEXT[o] || o;
const TABLE_CAPTION = {
  states: t("Voivodeships table"), metros: t("Metros table"), powiaty: t("Powiaty table"), counties: t("Gminas table"), towns: t("Towns table"),
};
const TABLE_SEARCH = {
  states: t("Search voivodeships"), metros: t("Search metros"), powiaty: t("Search powiaty"), counties: t("Search gminas"), towns: t("Search towns"),
};
// "<b>12</b> of 380 powiaty", per level (the total sets the plural form).
const OF_TOTAL = {
  states: (total) => t.plural(total, { one: "{shown} of {n} voivodeship", other: "{shown} of {n} voivodeships" }, { shown: "{shown}", n: "{n}" }),
  metros: (total) => t.plural(total, { one: "{shown} of {n} metro", other: "{shown} of {n} metros" }, { shown: "{shown}", n: "{n}" }),
  powiaty: (total) => t.plural(total, { one: "{shown} of {n} powiat", other: "{shown} of {n} powiaty" }, { shown: "{shown}", n: "{n}" }),
  counties: (total) => t.plural(total, { one: "{shown} of {n} gmina", other: "{shown} of {n} gminas" }, { shown: "{shown}", n: "{n}" }),
  towns: (total) => t.plural(total, { one: "{shown} of {n} town", other: "{shown} of {n} towns" }, { shown: "{shown}", n: "{n}" }),
};
const people = (n) => t.plural(Math.abs(n) >= 1e4 ? 1e6 : Math.round(n),
  { one: "{n} person", other: "{n} people" }, { n: count3(n) });

// Remember the explorer's setup per viewer (a convenience; the page works without it).
const STORE = "advisors.explorer.pl1";
const load = () => { try { return JSON.parse(localStorage.getItem(STORE) || "null"); } catch { return null; } };
const save = (s) => { try { localStorage.setItem(STORE, JSON.stringify(s)); } catch { /* private mode */ } };

export async function mount(ctx) {
  const { app, data, el, link } = ctx;
  // Columns from the optional files (garrisons, industry districts, citizen mixes): loaded on demand, only when the
  // Explorer opens, and added to the towns level once.
  await extendData(data, ["military", "districts", "citizens"]);
  const avail = ["states", "metros", "powiaty", "counties", "towns"].filter((k) => data.levels[k]);
  const saved = load() || {};
  const st = {
    level: avail.includes(ctx.params.level) ? ctx.params.level : avail.includes(saved.level) ? saved.level : "metros",
    cols: { ...DEFAULT_COLS, ...(saved.cols || {}) },
    xy: { ...DEFAULT_XY, ...(saved.xy || {}) },
    filters: [],
    onlySel: false,
    sel: null,
  };
  const persist = () => {
    save({ level: st.level, cols: st.cols, xy: st.xy });
    track("explorer_used", { level: st.level, columns: (st.cols[st.level] || []).length });
  };
  const L = () => data.levels[st.level];
  const yieldLabels = new Map((app.data.nation?.yields || []).map((y) => [y.key, y.label]));

  // --- controls -------------------------------------------------------------------------------------------------
  const top = section(el, { title: t("Explore the data"), note: esc(t("Choose what to compare, filter it, sort the table, and plot any two columns. Hover a row or a point to see it on the map; drag across the chart to select a group.")) });
  const lvRow = document.createElement("div");
  lvRow.className = "adv-row";
  top.appendChild(lvRow);
  segmented(lvRow, {
    label: t("Level"), value: st.level,
    options: avail.map((k) => ({ value: k, label: data.levels[k].label })),
    onChange: (v) => { st.level = v; st.filters = st.filters.filter((f) => L().field(f.key)); st.sel = null; persist(); rebuild(); },
  });
  const colsBox = document.createElement("details");
  colsBox.className = "adv-cols";
  lvRow.appendChild(colsBox);

  const fRow = document.createElement("div");
  fRow.className = "adv-fbuild";
  top.appendChild(fRow);
  const chipsRow = document.createElement("div");
  chipsRow.className = "adv-row adv-filterbar";
  top.appendChild(chipsRow);
  const summary = document.createElement("p");
  summary.className = "adv-note adv-summary";
  top.appendChild(summary);

  // --- table ----------------------------------------------------------------------------------------------------
  const tBody = section(el, { title: t("Table") });
  const selRow = document.createElement("div");
  selRow.className = "adv-row";
  tBody.appendChild(selRow);
  const tableHost = document.createElement("div");
  tBody.appendChild(tableHost);
  let table = null;

  // --- chart ----------------------------------------------------------------------------------------------------
  const cBody = section(el, { title: t("Chart") });
  const axes = document.createElement("div");
  axes.className = "adv-axes";
  cBody.appendChild(axes);
  const scatterHost = document.createElement("div");
  cBody.appendChild(scatterHost);
  const legendEl = document.createElement("div");
  cBody.appendChild(legendEl);
  const lensRow = document.createElement("div");
  lensRow.className = "adv-row";
  cBody.appendChild(lensRow);
  const fieldInfo = document.createElement("div");
  fieldInfo.className = "adv-fieldinfo";
  cBody.appendChild(fieldInfo);
  const scatter = createScatter(scatterHost, {
    height: 320, points: [],
    onHover: (p) => { link.hover(p ? rowsHighlight(L(), [p.row]) : null); table?.setHot(p ? p.key : null, false); },
    onClick: (p) => L().focus(p.row),
    onBrush: (set) => { st.sel = set; applySelection(); },
  });
  const srcEl = document.createElement("div");
  el.appendChild(srcEl);

  // --- logic ----------------------------------------------------------------------------------------------------
  const fieldOpts = (withNone = false, numeric = true) => {
    const fs = L().fields.filter((f) => (numeric ? f.format !== "text" : f.key !== "name"));
    return [...(withNone ? [{ value: "", label: t("None") }] : []), ...fs.map((f) => ({ value: f.key, label: f.label, group: f.group }))];
  };
  const numeric = (f) => f && f.format !== "text";
  const val = (r, k) => r.v[k] ?? null;
  const fmtF = (f, v) => fmtValue(f.format, v, f.unit);

  function passes(r) {
    for (const f of st.filters) {
      const fd = L().field(f.key);
      if (!fd) continue;
      const v = val(r, f.key);
      if (numeric(fd)) {
        if (!fin(v)) return false;
        const w = f.value;
        if (f.op === ">" && !(v > w)) return false;
        if (f.op === "\u2265" && !(v >= w)) return false;
        if (f.op === "<" && !(v < w)) return false;
        if (f.op === "\u2264" && !(v <= w)) return false;
        if (f.op === "=" && !(Math.abs(v - w) <= Math.abs(w) * 0.005 + 1e-9)) return false;
      } else {
        const s = String(v ?? "").toLowerCase(), w = String(f.value).toLowerCase();
        if (f.op === "=" && s !== w) return false;
        if (f.op === "\u2260" && s === w) return false;
        if (f.op === "contains" && !s.includes(w)) return false;
      }
    }
    return true;
  }
  const filtered = () => L().rows.filter(passes);

  function renderCols() {
    const on = new Set(st.cols[st.level]);
    const groups = new Map();
    for (const f of L().fields) {
      if (f.key === "name") continue;
      if (!groups.has(f.group)) groups.set(f.group, []);
      groups.get(f.group).push(f);
    }
    colsBox.innerHTML = `<summary class="adv-mini">${esc(t("Columns ({n})", { n: on.size }))}</summary><div class="adv-cols-pop">${[...groups].map(([g, list]) => `<fieldset><legend>${esc(g)}</legend>${list.map((f) => `<label title="${esc(f.description)}"><input type="checkbox" value="${esc(f.key)}"${on.has(f.key) ? " checked" : ""}> ${esc(f.label)}</label>`).join("")}</fieldset>`).join("")}</div>`;
  }
  colsBox.addEventListener("change", (e) => {
    const k = e.target.value;
    const list = st.cols[st.level].filter((x) => x !== k);
    if (e.target.checked) list.push(k);
    st.cols = { ...st.cols, [st.level]: list };
    colsBox.querySelector("summary").textContent = t("Columns ({n})", { n: list.length });
    persist();
    buildTable();
  });

  function renderFilterBuilder() {
    fRow.innerHTML = "";
    const fs = L().fields;
    const fsel = selectBox(fRow, { label: t("Filter"), value: fs.find((f) => f.key === "population")?.key || fs[0].key, options: fs.map((f) => ({ value: f.key, label: f.label, group: f.group })) });
    const ops = document.createElement("select");
    ops.setAttribute("aria-label", t("Comparison"));
    const valIn = document.createElement("input");
    valIn.type = "text";
    valIn.placeholder = t("e.g. 1M, 25%, MA");
    valIn.setAttribute("aria-label", t("Value"));
    const add = document.createElement("button");
    add.type = "button";
    add.className = "adv-mini";
    add.textContent = t("Add");
    const syncOps = () => {
      const f = L().field(fsel.value);
      ops.innerHTML = (numeric(f) ? OPS.num : OPS.text).map((o) => `<option value="${esc(o)}">${esc(opText(o))}</option>`).join("");
      valIn.placeholder = numeric(f) ? (f.format === "pct" || f.format === "signed" ? t("e.g. 25%") : f.format === "pln" || f.format === "usd" || f.format === "money" ? t("e.g. 8K") : t("e.g. 1M")) : ["counties", "powiaty", "towns"].includes(st.level) ? t("e.g. MA") : t("text");
    };
    fsel.select.addEventListener("change", syncOps);
    syncOps();
    const submit = () => {
      const f = L().field(fsel.value);
      if (!f || !valIn.value.trim()) return;
      const v = numeric(f) ? parseNum(valIn.value, f.format) : valIn.value.trim();
      if (v == null) { valIn.setCustomValidity(t("Not a number")); valIn.reportValidity(); return; }
      valIn.setCustomValidity("");
      st.filters.push({ key: f.key, op: ops.value, value: v });
      valIn.value = "";
      refresh();
    };
    add.addEventListener("click", submit);
    valIn.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
    fRow.append(ops, valIn, add);
    // quick presets
    const presets = document.createElement("span");
    presets.className = "adv-presets";
    const GE = OPS.num[1];
    const P = {
      counties: [["population", GE, 2e4, t("20K+ people")], ["population", GE, 1e5, t("100K+")]],
      powiaty: [["population", GE, 1e5, t("100K+ people")], ["population", GE, 2.5e5, t("250K+")]],
      towns: [["population", GE, 2e4, t("20K+ people")], ["population", GE, 1e5, t("100K+")]],
    }[st.level] || [["population", GE, 1e6, t("1M+ people")], ["population", GE, 2.5e5, t("250K+")]];
    presets.innerHTML = P.map((p, i) => `<button type="button" class="adv-mini" data-preset="${i}">${esc(p[3])}</button>`).join("");
    presets.addEventListener("click", (e) => {
      const i = e.target.closest("[data-preset]")?.dataset.preset;
      if (i == null) return;
      const [key, op, value] = P[+i];
      st.filters = st.filters.filter((f) => f.key !== key);
      st.filters.push({ key, op, value });
      refresh();
    });
    fRow.appendChild(presets);
  }

  function renderChips() {
    chipsRow.innerHTML = st.filters.map((f, i) => {
      const fd = L().field(f.key);
      const txt = `${fd?.label || f.key} ${opText(f.op)} ${numeric(fd) ? fmtShort(fd.format, f.value) : f.value}`;
      return `<span class="adv-fchip">${esc(txt)}<button type="button" data-rm="${i}" aria-label="${esc(t("Remove filter {filter}", { filter: txt }))}">\u2715</button></span>`;
    }).join("") + (st.filters.length > 1 ? `<button type="button" class="adv-mini" data-rm="all">${esc(t("Clear all"))}</button>` : "") + (st.filters.length && filterHighlight() ? frameBtn() : "");
  }
  chipsRow.addEventListener("click", (e) => {
    const i = e.target.closest("[data-rm]")?.dataset.rm;
    if (i == null) return;
    if (i === "all") st.filters = [];
    else st.filters.splice(+i, 1);
    refresh();
  });

  function buildTable() {
    const lv = L();
    const keys = st.cols[st.level].filter((k) => lv.field(k));
    const sortKey = keys.includes("population") ? "population" : keys[0] || "name";
    const maxOf = (k) => { const e = extent(lv.rows.map((r) => val(r, k))); return e ? Math.max(Math.abs(e[0]), Math.abs(e[1])) : 1; };
    const cols = [
      { key: "name", label: lv.field("name")?.label || t("Name"), align: "l", width: "minmax(92px,1.7fr)", value: (r) => r.name, html: (r) => `${esc(r.name)}${st.level !== "states" && r.sub ? ` <span class="sub">${esc(r.sub)}</span>` : ""}` },
      ...keys.map((k) => {
        const f = lv.field(k);
        const title = f.unit ? t("{label} ({unit}). Click to sort.", { label: f.label, unit: f.unit }) : t("{label}. Click to sort.", { label: f.label });
        // A yield column is headed by the yield's own name (Food, Science).
        const yieldLabel = k.startsWith("y_") ? yieldLabels.get(k.slice(2)) : null;
        const short = SHORT[k] ? esc(SHORT[k]) : yieldLabel ? esc(t(yieldLabel)) : null;
        // The name column already carries the voivodeship as a suffix, so a voivodeship column goes first when space is short.
        const isState = k === "state" || k === "states";
        return numeric(f)
          ? { key: k, label: f.label, short, title, value: (r) => val(r, k), text: (r) => fmtCell(f.format, val(r, k), f.unit), tip: (r) => fmtF(f, val(r, k)), bar: k === sortKey ? { max: maxOf(k), color: "rgba(154,123,201,.32)" } : null }
          : { key: k, label: f.label, short, title, align: "l", width: isState ? "minmax(0,.55fr)" : "minmax(0,.8fr)", hideBelow: isState ? 480 : 0, value: (r) => val(r, k), text: (r) => val(r, k) ?? "\u2013" };
      }),
    ];
    if (!table) {
      table = createTable(tableHost, {
        caption: TABLE_CAPTION[st.level] || lv.label, columns: cols, rows: [], sort: { key: sortKey, dir: "desc" }, rank: true, maxHeight: 360,
        search: TABLE_SEARCH[st.level] || t("Search"),
        onHover: (r) => { link.hover(r ? rowsHighlight(L(), [r]) : null); scatter.setHot(r ? r.key : null); },
        onClick: (r) => L().focus(r),
      });
    } else table.setColumns(cols, { key: sortKey, dir: "desc" });
    refreshRows();
  }

  function axisSelects() {
    axes.innerHTML = "";
    const xy = st.xy[st.level];
    const fix = (k, fallback) => (L().field(k) && numeric(L().field(k)) ? k : fallback);
    xy.x = fix(xy.x, "population");
    xy.y = fix(xy.y, "population");
    xy.s = xy.s && L().field(xy.s) ? xy.s : "";
    xy.c = xy.c && L().field(xy.c) ? xy.c : "";
    const mk = (key, label, none) => selectBox(axes, {
      label, value: xy[key], options: fieldOpts(none, key !== "c"),
      onChange: (v) => { xy[key] = v; if (key === "x" || key === "y") delete xy[`log${key}`]; persist(); drawScatter(); },
    });
    mk("x", t("X"), false);
    mk("y", t("Y"), false);
    mk("s", t("Size"), true);
    mk("c", t("Colour"), true);
    const logs = document.createElement("span");
    logs.className = "adv-logs";
    logs.innerHTML = `<label class="adv-check"><input type="checkbox" data-log="x"> ${esc(t("log X"))}</label><label class="adv-check"><input type="checkbox" data-log="y"> ${esc(t("log Y"))}</label>`;
    axes.appendChild(logs);
    logs.addEventListener("change", (e) => {
      const a = e.target.dataset.log;
      xy[`log${a}`] = e.target.checked;
      persist();
      drawScatter();
    });
  }
  // A skewed, positive column reads better on a log axis.
  const autoLog = (k, rows) => {
    const e = extent(rows.map((r) => val(r, k)), true);
    const all = rows.map((r) => val(r, k)).filter(fin);
    return !!e && all.every((v) => v > 0) && e[1] / e[0] > 60;
  };

  function drawScatter() {
    const lv = L();
    const xy = st.xy[st.level];
    const rows = filtered();
    const fx = lv.field(xy.x), fy = lv.field(xy.y), fs = xy.s ? lv.field(xy.s) : null, fc = xy.c ? lv.field(xy.c) : null;
    const lx = xy.logx ?? autoLog(xy.x, rows), ly = xy.logy ?? autoLog(xy.y, rows);
    axes.querySelector('[data-log="x"]').checked = lx;
    axes.querySelector('[data-log="y"]').checked = ly;
    let color = null;
    legendEl.innerHTML = "";
    if (fc) {
      if (numeric(fc)) {
        const signed = fc.format === "signed";
        const cl = autoLog(fc.key, rows);
        const dom = robustDomain(rows.map((r) => val(r, fc.key)), 0.03, cl) || [0, 1];
        const spec = signed ? { type: "div", domain: dom, mid: 0 } : { type: "seq", domain: dom, log: cl, ramp: fc.higher_is === "bad" ? RAMPS.heat : RAMPS.seq };
        const cs = colorScale(spec);
        color = (c) => cs(c);
        legendEl.innerHTML = rampLegend({ ramp: spec.ramp || RAMPS.div, domain: signed ? [-Math.max(...dom.map(Math.abs)), Math.max(...dom.map(Math.abs))] : dom, log: cl, fmt: (v) => fmtShort(fc.format, v), label: fc.label, mid: signed ? 0 : null });
      } else {
        const cats = [...new Set(rows.map((r) => val(r, fc.key)))].slice(0, 12);
        const pal = ["#e0b54c", "#4a86d6", "#3f9c82", "#c46a4f", "#9a7bc9", "#6e9a3c", "#d98a2b", "#5fbfbf", "#c9a0c0", "#a3a3c2", "#e8774a", "#b9b06a"];
        const m = new Map(cats.map((c, i) => [c, pal[i]]));
        color = (c) => m.get(c) || "#8b8070";
        const more = new Set(rows.map((r) => val(r, fc.key))).size > cats.length;
        legendEl.innerHTML = swatchLegend([...cats.map((c) => ({ label: c ?? "\u2013", color: m.get(c) })), ...(more ? [{ label: t("others"), color: "#8b8070" }] : [])], fc.label);
      }
    }
    const big = [...rows].sort((a, b) => (val(b, "population") || 0) - (val(a, "population") || 0)).slice(0, st.level === "states" ? 10 : 6).map((r) => r.key);
    scatter.update({
      points: rows.map((r) => ({ key: r.key, x: val(r, xy.x), y: val(r, xy.y), s: fs ? val(r, xy.s) : null, c: fc ? val(r, xy.c) : null, label: r.name, sub: r.sub, row: r })),
      x: { label: fx.label, fmt: (v) => fmtShort(fx.format, v), log: lx },
      y: { label: fy.label, fmt: (v) => fmtShort(fy.format, v), log: ly },
      size: fs && numeric(fs) ? { label: fs.label, fmt: (v) => fmtF(fs, v), max: st.level === "counties" ? 13 : 15, min: 1.6 } : null,
      radius: st.level === "counties" ? 2.2 : st.level === "powiaty" || st.level === "towns" ? 2.8 : 3.5,
      color, colorLabel: fc?.label, colorFmt: (v) => (fc && numeric(fc) ? fmtF(fc, v) : String(v)),
      labels: big,
      refLines: [], refX: [], refY: [],
    });
    if (st.sel) scatter.setSelected(st.sel);
    // Lens buttons for the plotted columns that have a matching map lens.
    lensRow.innerHTML = "";
    const lensFields = [fc, fy, fx].filter((f, i, a) => f && f.lens && a.findIndex((g) => g && g.lens === f.lens) === i);
    for (const f of lensFields) {
      const lens = app.lensById.get(f.lens);
      if (!lens) continue;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "adv-lensbtn";
      const on = app.state.lens?.id === lens.id;
      b.setAttribute("aria-pressed", String(on));
      b.textContent = on ? t("Showing the {lens} lens", { lens: t(lens.name) }) : t("Show {label} on the map as a lens", { label: f.label });
      b.addEventListener("click", () => { app.setLens(app.state.lens?.id === lens.id ? null : lens.id); drawScatter(); });
      lensRow.appendChild(b);
    }
    if (!lensFields.length) lensRow.innerHTML = `<span class="adv-note">${esc(t("No map lens for these columns: hover and brush to see places on the map."))}</span>`;
    fieldInfo.innerHTML = [fx, fy, fs, fc].filter((f, i, a) => f && a.indexOf(f) === i).map((f) => `<p><b>${esc(f.label)}</b>${f.unit ? ` <span class="sub">${esc(f.unit)}</span>` : ""}: ${esc(f.description || "")}</p>`).join("");
    const srcIds = [fx, fy, fs, fc].filter(Boolean).map((f) => f.source).filter(Boolean);
    srcEl.innerHTML = sourcesHtml(data, [...srcIds, "pl_stats_population"], [
      esc(t("Columns marked \u2248 are population-weighted means of gmina values: a fair guide, not the area's own figure.")),
      esc(t("Below the voivodeship, GDP is an estimate: a share of the GDP Eurostat publishes per NUTS 3 subregion.")),
      esc(t("Workers and wages are counted where the employer is; PIT per person follows where taxpayers live.")),
      ...(st.level === "counties" && data.countiesOffMap ? [esc(t.plural(data.countiesOffMap, { one: "{n} small gmina is smaller than one hex: it is in the table and chart but cannot be outlined on the map.", other: "{n} small gminas are smaller than one hex: they are in the table and chart but cannot be outlined on the map." }))] : []),
    ]);
  }

  function applySelection() {
    const lv = L();
    const sel = st.sel ? lv.rows.filter((r) => st.sel.has(r.key)) : [];
    link.base(sel.length ? rowsHighlight(lv, sel, { dim: true }) : filterHighlight(), { frame: sel.length > 1 || (!sel.length && st.filters.length > 0) });
    table?.setSelected(st.sel);
    selRow.innerHTML = st.sel ? `<span class="adv-fchip">${esc(t("{n} selected on the chart", { n: st.sel.size }))}<button type="button" data-clear-sel aria-label="${esc(t("Clear the selection"))}">\u2715</button></span>${frameBtn()}
      <label class="adv-check"><input type="checkbox" data-only${st.onlySel ? " checked" : ""}> ${esc(t("Only show the selection"))}</label>` : `<span class="adv-note">${esc(t("Tip: drag across the chart below to select a group."))}</span>`;
    refreshRows();
    updateSummary();
  }
  selRow.addEventListener("click", (e) => { if (e.target.closest("[data-clear-sel]")) { st.sel = null; st.onlySel = false; scatter.setSelected(null); applySelection(); } });
  selRow.addEventListener("change", (e) => { if (e.target.matches("[data-only]")) { st.onlySel = e.target.checked; refreshRows(); } });

  // With filters on, outline the rows that pass (when there are not too many to read).
  function filterHighlight() {
    if (!st.filters.length) return null;
    const rows = filtered();
    if (!rows.length || rows.length > (st.level === "counties" ? 1500 : 400)) return null;
    return rowsHighlight(L(), rows, { dim: true, ringMax: 12 });
  }

  function refreshRows() {
    if (!table) return;
    let rows = filtered();
    if (st.onlySel && st.sel) rows = rows.filter((r) => st.sel.has(r.key));
    table.setRows(rows);
  }
  function updateSummary() {
    const rows = filtered();
    const pop = rows.reduce((a, r) => a + (val(r, "population") || 0), 0);
    const total = L().rows.length;
    const ofTotal = fillHtml(OF_TOTAL[st.level](total), { shown: `<b>${int(rows.length)}</b>`, n: esc(int(total)) });
    summary.innerHTML = `${ofTotal} \u00b7 ${esc(people(pop))}${st.sel ? ` \u00b7 ${fillHtml(t("{n} selected"), { n: `<b>${int(st.sel.size)}</b>` })}` : ""}`;
  }
  function refresh() {
    renderChips();
    st.sel = null;
    scatter.setSelected(null);
    refreshRows();
    drawScatter();
    applySelection();
  }
  function rebuild() {
    if (table) { table.destroy(); table = null; }
    renderCols();
    renderFilterBuilder();
    axisSelects();
    buildTable();
    refresh();
  }
  rebuild();

  const hostRowAt = (cell) => (cell >= 0 ? L().rowAtCell(cell) : null);
  return {
    onMapHover(h) {
      const r = hostRowAt(h.cell);
      scatter.setHot(r ? r.key : null);
      table?.setHot(r ? r.key : null);
    },
    onEscape() {
      if (st.sel) { st.sel = null; st.onlySel = false; scatter.setSelected(null); applySelection(); return true; }
      return false;
    },
  };
}

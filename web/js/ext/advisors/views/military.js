// Military advisor: Polish garrisons, training areas, personnel and the two 2026 budget definitions.
import { esc, fin } from "../core/util.js";
import { int } from "../core/fmt.js";
import { barList } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, chips } from "../core/view.js";
import { frameBox, focusPoint } from "../core/frame.js";
import { FORT_KINDS, fortKind } from "../../../render/art/sites.js";
import { t, num, zloty, LANG } from "../../../i18n.js";

const TIER = { major: t("Major garrison"), base: t("Garrison"), site: t("Military site") };
// Money in the style of the shared money() helper (124.8B zl / 124,8 mld zl), with one decimal for billions.
const pln = (value) => {
  if (!fin(value)) return "-";
  if (value >= 1e9) return `${num(value / 1e9, 1, { trim: true })}${LANG === "pl" ? " mld" : "B"} z\u0142`;
  if (value >= 1e6) return `${num(value / 1e6, 0)}${LANG === "pl" ? " mln" : "M"} z\u0142`;
  return zloty(value);
};
const compName = (c) => (c?.name ? t(c.name) : "");
// Escape a translated template and fill its {placeholders} with HTML.
const tHtml = (text, vars) => esc(text).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));

export function groupGarrisons(installations, compById, activeComponents, voivodeship = null) {
  const order = new Map([...compById.keys()].map((id, index) => [id, index]));
  const tierRank = { site: 0, base: 1, major: 2 };
  const grouped = new Map();
  for (const item of installations) {
    if (!activeComponents.has(item.component) || (voivodeship && item.state !== voivodeship)) continue;
    const key = `garrison:${item.name}`;
    let row = grouped.get(key);
    if (!row) {
      row = { ...item, key, count: 0, units: [], branchCounts: new Map() };
      grouped.set(key, row);
    }
    row.count += item.count || 0;
    row.units.push(...(item.units || []));
    row.branchCounts.set(item.component, (row.branchCounts.get(item.component) || 0) + (item.count || 0));
    if ((tierRank[item.tier] || 0) > (tierRank[row.tier] || 0)) row.tier = item.tier;
  }
  for (const row of grouped.values()) {
    row.branches = [...row.branchCounts]
      .sort((a, b) => b[1] - a[1] || (order.get(a[0]) || 0) - (order.get(b[0]) || 0));
    row.branchText = row.branches.map(([id]) => compName(compById.get(id)) || id).join(", ");
  }
  return [...grouped.values()];
}

export async function mount(ctx) {
  const { app, data, el, link } = ctx;
  const mil = await app.loadData("military");
  if (!mil) {
    el.innerHTML = `<p class="adv-empty pad">${esc(t("No military data is available."))}</p>`;
    return {};
  }
  const components = mil.components || [];
  const compById = new Map(components.map((c) => [c.id, c]));
  const installations = (mil.installations || []).map((it, index) => ({ ...it, key: it.id || String(index) }));
  const ranges = mil.ranges || [];
  const voivodeships = data.levels.states;
  const voivodeshipIndex = (abbr) => voivodeships.byKey.get(abbr)?.ref ?? null;
  const voivodeshipName = (abbr) => voivodeships.byKey.get(abbr)?.name || abbr;
  const national = mil.national || {};
  const personnel = national.personnel || {};
  const spending = national.spending || {};
  const filter = { components: new Set(components.map((c) => c.id)), voivodeship: null };

  el.insertAdjacentHTML("beforeend", tiles([
    { label: t("Armed Forces"), value: int(personnel.total_mid_2026), sub: t("at the end of June 2026") },
    { label: t("Professional soldiers"), value: int(personnel.professional), sub: t("June 2026") },
    { label: t("Territorial Defence"), value: int(personnel.territorial_defence), sub: t("soldiers") },
  ]));

  const budgetBody = section(el, { title: t("Defence spending in 2026") });
  const budgetRows = [spending.budget_act, spending.with_support_fund].filter(Boolean);
  budgetBody.insertAdjacentHTML("beforeend", budgetRows.length ? budgetRows.map((row) => `
    <p class="adv-note"><b>${esc(t(row.name))}</b><br>
      ${esc(pln(row.total_pln))}${fin(row.pct_gdp) ? `, ${esc(t("{v}% of GDP", { v: num(row.pct_gdp, row.pct_gdp % 1 ? 2 : 1) }))}` : ""}
    </p>`).join("") : `<p class="adv-empty">${esc(t("No 2026 budget figures are available."))}</p>`);

  const componentBody = section(el, { title: t("Show garrisons") });
  const componentChips = chips(componentBody, {
    label: t("Branches"),
    items: components.map((c) => ({ key: c.id, label: compName(c), color: FORT_KINDS[fortKind(c.id)]?.accent })),
    onChange: (on) => { filter.components = on; apply(); },
  });
  const activePlace = document.createElement("div");
  activePlace.className = "adv-row adv-filterbar";
  componentBody.appendChild(activePlace);
  activePlace.addEventListener("click", (event) => { if (event.target.closest("[data-clear-place]")) setVoivodeship(null); });

  const siteBody = section(el, { title: t("Garrisons and allied sites") });
  const siteTable = createTable(siteBody, {
    caption: t("Garrison towns"), search: t("Search garrisons and branches"), rank: true, maxHeight: 348, rowH: 58, rows: [],
    searchText: (r) => `${r.name} ${r.branchText} ${(r.units || []).join(" ")}`,
    columns: [
      { key: "name", label: t("Garrison"), align: "l", width: "minmax(0,.9fr)", value: (r) => r.name, text: (r) => r.name },
      { key: "branch", label: t("Branches"), align: "l", width: "minmax(0,2fr)", value: (r) => r.branchText, text: (r) => r.branchText },
      { key: "units", label: t("Entries"), width: "48px", value: (r) => r.count, text: (r) => int(r.count) },
      { key: "tier", label: t("Scale"), align: "l", value: (r) => r.tier, text: (r) => TIER[r.tier] || r.tier, hideBelow: 600 },
    ],
    sort: { key: "units", dir: "desc" },
    onHover: (r) => link.hover(r ? { cells: new Set([r.cell]), dimOthers: true, label: r.name } : null),
    onClick: (r) => focusPoint(app, r.x, r.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
  });
  siteTable.el.classList.add("mil-garrisons");

  const rangeBody = section(el, { title: t("Main training areas") });
  createTable(rangeBody, {
    caption: t("Training areas"), rows: ranges, maxHeight: 220,
    columns: [
      { key: "name", label: t("Training area"), align: "l", width: "minmax(0,1.7fr)", value: (r) => r.name, text: (r) => r.name },
      { key: "garrison", label: t("Near"), align: "l", value: (r) => r.garrison, text: (r) => r.garrison || "-" },
      { key: "area", label: t("Area"), short: "km&sup2;", width: "54px", value: (r) => r.area_km2, text: (r) => fin(r.area_km2) ? `${int(r.area_km2)} km\u00b2` : "-" },
    ],
    sort: { key: "area", dir: "desc" },
    onHover: (r) => link.hover(r ? { cells: new Set(r.cells || [r.cell]), dimOthers: true, label: r.name } : null),
    onClick: (r) => focusPoint(app, r.x, r.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
  });

  const placeBody = section(el, { title: t("Garrisons by voivodeship") });
  const placeRows = Object.entries(mil.states || {}).map(([abbr, row]) => ({
    key: abbr, label: voivodeshipName(abbr), value: row.garrison_towns, sub: `${t.plural(row.units, { one: "{n} formation", other: "{n} formations" })}, ${t.plural(row.bases, { one: "{n} base", other: "{n} bases" })}`, row,
  })).filter((r) => fin(r.value)).sort((a, b) => b.value - a.value);
  const placeBars = barList(placeBody, {
    rows: placeRows, rank: true, ariaLabel: t("Garrison towns by voivodeship"),
    onHover: (r) => {
      const idx = r ? voivodeshipIndex(r.key) : null;
      link.hover(idx != null ? { states: new Set([idx]), dimOthers: true, label: r.label } : null);
    },
    onClick: (r) => setVoivodeship(filter.voivodeship === r.key ? null : r.key, true),
  });

  const forceBody = section(el, { title: t("Personnel") });
  const forceRows = [
    { key: "professional", label: t("Professional soldiers"), value: personnel.professional },
    { key: "territorial", label: t("Territorial Defence"), value: personnel.territorial_defence },
    { key: "voluntary", label: t("Voluntary basic service"), value: personnel.voluntary_service },
  ].filter((r) => fin(r.value));
  barList(forceBody, { rows: forceRows, ariaLabel: t("Polish Armed Forces personnel"), rank: false, max: Math.max(1, ...forceRows.map((r) => r.value)) });

  function shown() {
    return groupGarrisons(installations, compById, filter.components, filter.voivodeship);
  }

  function setVoivodeship(abbr, fly = false) {
    filter.voivodeship = abbr;
    placeBars.setSelected(abbr);
    apply();
    const idx = abbr ? voivodeshipIndex(abbr) : null;
    if (fly && idx != null) {
      const bounds = app.highlightBounds({ states: new Set([idx]) });
      if (bounds) frameBox(app, bounds, { pad: 30, maxScale: 2.6 });
    }
  }

  function apply() {
    const rows = shown();
    siteTable.setRows(rows);
    const idx = filter.voivodeship ? voivodeshipIndex(filter.voivodeship) : null;
    link.base(idx != null ? { states: new Set([idx]), dimOthers: true } : null);
    activePlace.innerHTML = idx != null ? `<span class="adv-fchip">${tHtml(t("Voivodeship: {name}"), { name: `<b>${esc(voivodeshipName(filter.voivodeship))}</b>` })} &middot; ${esc(t.plural(rows.length, { one: "{n} town", other: "{n} towns" }))}<button type="button" data-clear-place aria-label="${esc(t("Clear the voivodeship filter"))}">x</button></span>` : "";
  }
  apply();

  return {
    onMapHover(event) {
      const item = event.item;
      if (event.layer === "forts" && item?.data?.name) siteTable.setHot(`garrison:${item.data.name}`);
    },
    onEscape() {
      if (filter.voivodeship) { setVoivodeship(null); return true; }
      if (filter.components.size !== components.length) {
        filter.components = new Set(components.map((c) => c.id));
        componentChips.set(filter.components);
        apply();
        return true;
      }
      return false;
    },
  };
}

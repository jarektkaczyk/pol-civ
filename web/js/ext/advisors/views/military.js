// Military advisor: Polish garrisons, training areas, personnel and the two 2026 budget definitions.
import { esc, fin } from "../core/util.js";
import { int } from "../core/fmt.js";
import { barList } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, chips } from "../core/view.js";
import { frameBox, focusPoint } from "../core/frame.js";
import { FORT_KINDS, fortKind } from "../../../render/art/sites.js";

const STATUS = { act: "Active", active: "Active", forming: "Forming" };
const TIER = { major: "Major garrison", base: "Garrison", site: "Military site" };
const pln = (value) => {
  if (!fin(value)) return "-";
  if (value >= 1e9) return `PLN ${(value / 1e9).toFixed(value % 1e9 ? 1 : 0)} bn`;
  if (value >= 1e6) return `PLN ${(value / 1e6).toFixed(0)} mn`;
  return `PLN ${int(value)}`;
};

export async function mount(ctx) {
  const { app, data, el, link } = ctx;
  const mil = await app.loadData("military");
  if (!mil) {
    el.innerHTML = `<p class="adv-empty pad">No military data is available.</p>`;
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
    { label: "Armed Forces", value: int(personnel.total_mid_2026), sub: "at the end of June 2026" },
    { label: "Professional soldiers", value: int(personnel.professional), sub: "June 2026" },
    { label: "Territorial Defence", value: int(personnel.territorial_defence), sub: "soldiers" },
  ]));

  const budgetBody = section(el, { title: "Defence spending in 2026" });
  const budgetRows = [spending.budget_act, spending.with_support_fund].filter(Boolean);
  budgetBody.insertAdjacentHTML("beforeend", budgetRows.length ? budgetRows.map((row) => `
    <p class="adv-note"><b>${esc(row.name)}</b><br>
      ${esc(pln(row.total_pln))}${fin(row.pct_gdp) ? `, ${row.pct_gdp.toFixed(row.pct_gdp % 1 ? 2 : 1)}% of GDP` : ""}
    </p>`).join("") : `<p class="adv-empty">No 2026 budget figures are available.</p>`);

  const componentBody = section(el, { title: "Show garrisons" });
  const componentChips = chips(componentBody, {
    label: "Branches",
    items: components.map((c) => ({ key: c.id, label: c.name, color: FORT_KINDS[fortKind(c.id)]?.accent })),
    onChange: (on) => { filter.components = on; apply(); },
  });
  const activePlace = document.createElement("div");
  activePlace.className = "adv-row adv-filterbar";
  componentBody.appendChild(activePlace);
  activePlace.addEventListener("click", (event) => { if (event.target.closest("[data-clear-place]")) setVoivodeship(null); });

  const siteBody = section(el, { title: "Garrisons and allied sites" });
  const siteTable = createTable(siteBody, {
    caption: "Garrison markers", search: "Search garrisons and branches", rank: true, maxHeight: 320, rows: [],
    searchText: (r) => `${r.name} ${compById.get(r.component)?.name || ""} ${(r.units || []).join(" ")}`,
    columns: [
      { key: "name", label: "Garrison", align: "l", width: "minmax(0,1.5fr)", value: (r) => r.name, text: (r) => r.name },
      { key: "branch", label: "Branch", align: "l", width: "minmax(0,1fr)", value: (r) => compById.get(r.component)?.name, text: (r) => compById.get(r.component)?.name || r.component },
      { key: "units", label: "Entries", value: (r) => r.count, text: (r) => int(r.count) },
      { key: "tier", label: "Scale", align: "l", value: (r) => r.tier, text: (r) => TIER[r.tier] || r.tier, hideBelow: 420 },
    ],
    sort: { key: "units", dir: "desc" },
    onHover: (r) => link.hover(r ? { cells: new Set([r.cell]), dimOthers: true, label: r.name } : null),
    onClick: (r) => focusPoint(app, r.x, r.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
  });

  const rangeBody = section(el, { title: "Main training areas" });
  createTable(rangeBody, {
    caption: "Training areas", rows: ranges, maxHeight: 220,
    columns: [
      { key: "name", label: "Training area", align: "l", width: "minmax(0,1.7fr)", value: (r) => r.name, text: (r) => r.name },
      { key: "garrison", label: "Near", align: "l", value: (r) => r.garrison, text: (r) => r.garrison || "-" },
      { key: "area", label: "Area", value: (r) => r.area_km2, text: (r) => fin(r.area_km2) ? `${int(r.area_km2)} km2` : "-" },
    ],
    sort: { key: "area", dir: "desc" },
    onHover: (r) => link.hover(r ? { cells: new Set(r.cells || [r.cell]), dimOthers: true, label: r.name } : null),
    onClick: (r) => focusPoint(app, r.x, r.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
  });

  const placeBody = section(el, { title: "Garrisons by voivodeship" });
  const placeRows = Object.entries(mil.states || {}).map(([abbr, row]) => ({
    key: abbr, label: voivodeshipName(abbr), value: row.garrison_towns, sub: `${int(row.units)} formations, ${int(row.bases)} bases`, row,
  })).filter((r) => fin(r.value)).sort((a, b) => b.value - a.value);
  const placeBars = barList(placeBody, {
    rows: placeRows, rank: true, ariaLabel: "Garrison towns by voivodeship",
    onHover: (r) => {
      const idx = r ? voivodeshipIndex(r.key) : null;
      link.hover(idx != null ? { states: new Set([idx]), dimOthers: true, label: r.label } : null);
    },
    onClick: (r) => setVoivodeship(filter.voivodeship === r.key ? null : r.key, true),
  });

  const forceBody = section(el, { title: "Personnel" });
  const forceRows = [
    { key: "professional", label: "Professional soldiers", value: personnel.professional },
    { key: "territorial", label: "Territorial Defence", value: personnel.territorial_defence },
    { key: "voluntary", label: "Voluntary basic service", value: personnel.voluntary_service },
  ].filter((r) => fin(r.value));
  barList(forceBody, { rows: forceRows, ariaLabel: "Polish Armed Forces personnel", rank: false, max: Math.max(1, ...forceRows.map((r) => r.value)) });

  function shown() {
    return installations.filter((it) => filter.components.has(it.component) && (!filter.voivodeship || it.state === filter.voivodeship));
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
    activePlace.innerHTML = idx != null ? `<span class="adv-fchip">Voivodeship: <b>${esc(voivodeshipName(filter.voivodeship))}</b> &middot; ${int(rows.length)} markers<button type="button" data-clear-place aria-label="Clear the voivodeship filter">x</button></span>` : "";
  }
  apply();

  return {
    onMapHover(event) {
      const item = event.item;
      if (event.layer === "forts" && item?.data?.id) siteTable.setHot(item.data.id);
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

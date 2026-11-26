// Energy and Resources advisor: mapped Polish plants, mines and renewable capacity by powiat.
import { esc, fin } from "../core/util.js";
import { fmtValue, mw, int, count3 } from "../core/fmt.js";
import { barList, shareBar, stackedBars, sizeLegend } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, chips } from "../core/view.js";
import { frameBox, focusPoint } from "../core/frame.js";
import { glyph } from "../../../ui/icon.js";

const GROUPS = [
  { id: "power", label: "Power plants", types: ["nuclear", "hard_coal_plant", "lignite_plant", "gas_plant", "hydro"] },
  { id: "renewable", label: "Wind, solar and storage", types: ["onshore_wind", "offshore_wind", "solar", "battery"] },
  { id: "mines", label: "Mines and smelters", types: ["coal_mine", "lignite_mine", "copper", "copper_smelter", "salt", "sulphur", "silver"] },
  { id: "oilgas", label: "Oil and gas", types: ["gas_pipeline_landfall", "gas_field", "oil_field", "refinery"] },
];

export function mount(ctx) {
  const { app, el, link } = ctx;
  const res = app.data.resources;
  if (!res) {
    el.innerHTML = `<p class="adv-empty pad">No energy and resource data is available.</p>`;
    return {};
  }
  const types = res.types || [];
  const typeById = new Map(types.map((t) => [t.id, t]));
  const items = (res.items || []).map((it, idx) => ({ ...it, idx, key: String(idx) }));
  const national = res.summary?.national || {};
  const voivodeships = app.data.states || [];
  const voivodeshipIdx = new Map(voivodeships.map((s, i) => [s.abbr, i]));
  const isMW = (id) => typeById.get(id)?.unit === "MW";
  const mwTypes = types.filter((t) => t.unit === "MW");
  const listed = new Set(GROUPS.flatMap((g) => g.types));
  const groups = GROUPS.map((g) => ({ ...g, types: g.types.filter((id) => typeById.has(id)) })).filter((g) => g.types.length);
  const extra = types.filter((t) => !listed.has(t.id)).map((t) => t.id);
  if (extra.length) groups.push({ id: "other", label: "Other", types: extra });
  const filter = { types: new Set(types.map((t) => t.id)), min: 0, voivodeship: null };
  ctx.setShowResources(true);

  const mappedMW = mwTypes.reduce((sum, t) => sum + (national[t.id]?.value || 0), 0);
  const mappedPowerSites = mwTypes.reduce((sum, t) => sum + (national[t.id]?.count || 0), 0);
  const mineIds = groups.find((g) => g.id === "mines")?.types || [];
  const oilGasIds = groups.find((g) => g.id === "oilgas")?.types || [];
  const offshore = national.offshore_wind || {};
  el.insertAdjacentHTML("beforeend", tiles([
    { label: "Mapped power", value: mw(mappedMW), sub: `${int(mappedPowerSites)} sites` },
    { label: "Mines and smelters", value: int(mineIds.reduce((sum, id) => sum + (national[id]?.count || 0), 0)), sub: "mapped sites" },
    { label: "Offshore wind", value: mw(offshore.value), sub: `${int(offshore.count || 0)} Baltic projects` },
    { label: "Oil and gas", value: int(oilGasIds.reduce((sum, id) => sum + (national[id]?.count || 0), 0)), sub: "mapped sites" },
  ]));

  const mixBody = section(el, { title: "Mapped capacity" });
  const mix = mwTypes.map((t) => ({
    key: t.id, label: t.name, value: national[t.id]?.value || 0, color: t.color,
    text: mw(national[t.id]?.value), icon: glyph(t, 14), sub: `${int(national[t.id]?.count || 0)} sites`,
  })).sort((a, b) => b.value - a.value);
  const selectType = (id) => {
    filter.types = filter.types.size === 1 && filter.types.has(id) ? new Set(types.map((t) => t.id)) : new Set([id]);
    typeChips.set(filter.types);
    apply();
  };
  const hoverType = (part) => {
    if (!part) return link.hover(null);
    link.hover({ resources: new Set(visible().filter((it) => it.type === part.key).map((it) => it.idx)), dimOthers: true });
  };
  shareBar(mixBody, { parts: mix, legend: false, onHover: hoverType, onClick: (p) => selectType(p.key) });
  const mixBars = barList(mixBody, { rows: mix, ariaLabel: "Mapped capacity by type", onHover: hoverType, onClick: (p) => selectType(p.key) });

  const filterBody = section(el, { title: "Filter the map" });
  const typeChips = chips(filterBody, {
    label: "Types",
    items: groups.flatMap((g) => g.types.map((id) => {
      const t = typeById.get(id);
      return { key: id, label: t.name, color: t.color, icon: glyph(t, 13), count: national[id]?.count ?? null };
    })),
    onChange: (on) => { filter.types = on; apply(); },
  });
  const quick = document.createElement("div");
  quick.className = "adv-row";
  quick.innerHTML = `${groups.map((g) => `<button type="button" class="adv-mini" data-group="${g.id}">${esc(g.label)}</button>`).join("")}<button type="button" class="adv-mini" data-group="all">All</button>`;
  filterBody.appendChild(quick);
  quick.addEventListener("click", (event) => {
    const id = event.target.closest("[data-group]")?.dataset.group;
    if (!id) return;
    filter.types = id === "all" ? new Set(types.map((t) => t.id)) : new Set(groups.find((g) => g.id === id)?.types || []);
    typeChips.set(filter.types);
    apply();
  });
  const slider = document.createElement("label");
  slider.className = "adv-slider";
  slider.innerHTML = `<span>Minimum power-site capacity</span><input type="range" min="0" max="5000" step="100" value="0" aria-label="Minimum capacity in MW"><b>Any size</b>`;
  filterBody.appendChild(slider);
  slider.querySelector("input").addEventListener("input", (event) => {
    filter.min = +event.target.value;
    slider.querySelector("b").textContent = filter.min ? `${int(filter.min)} MW` : "Any size";
    apply();
  });
  const activePlace = document.createElement("div");
  activePlace.className = "adv-row adv-filterbar";
  filterBody.appendChild(activePlace);
  activePlace.addEventListener("click", (event) => { if (event.target.closest("[data-clear-place]")) setVoivodeship(null); });
  const sizeKey = document.createElement("div");
  filterBody.appendChild(sizeKey);

  const sitesBody = section(el, { title: "Plants, mines and projects" });
  const siteTable = createTable(sitesBody, {
    caption: "Mapped resource sites", search: "Search sites and operators", rank: true, maxHeight: 320,
    searchText: (r) => `${r.name} ${r.operator || ""} ${typeById.get(r.type)?.name || ""}`,
    rows: [],
    columns: [
      { key: "name", label: "Site", align: "l", width: "minmax(0,1.7fr)", value: (r) => r.name, html: (r) => `<span class="ic">${glyph(typeById.get(r.type), 13)}</span>${esc(r.name)}` },
      { key: "type", label: "Type", align: "l", width: "minmax(0,1fr)", value: (r) => typeById.get(r.type)?.name, text: (r) => typeById.get(r.type)?.name || r.type },
      { key: "place", label: "Voiv.", align: "l", width: "44px", value: (r) => r.state, text: (r) => r.state || "-" },
      { key: "value", label: "Size", value: (r) => (isMW(r.type) && fin(r.value) ? r.value : null), text: sizeText },
      { key: "status", label: "Status", align: "l", value: (r) => r.status, text: (r) => statusText(r.status), hideBelow: 420 },
    ],
    sort: { key: "value", dir: "desc" },
    onHover: (r) => link.hover(r ? { resources: new Set([r.idx]), dimOthers: true, label: r.name } : null),
    onClick: (r) => focusPoint(app, r.x, r.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
  });
  function sizeText(r) {
    if (fin(r.output)) return `${fmtValue("float", r.output)}${r.output_unit ? ` ${r.output_unit}` : ""}`;
    if (!fin(r.value)) return "-";
    const unit = typeById.get(r.type)?.unit;
    if (unit === "MW") return mw(r.value);
    if (unit === "sites") return "Mapped site";
    return `${fmtValue("float", r.value)}${unit ? ` ${unit}` : ""}`;
  }

  const placeBody = section(el, { title: "Mapped power by voivodeship" });
  const placeRows = voivodeships.map((s, idx) => {
    const summary = res.summary?.states?.[s.abbr] || {};
    const parts = Object.fromEntries(mwTypes.map((t) => [t.id, summary[t.id]?.value || 0]));
    const total = Object.values(parts).reduce((sum, value) => sum + value, 0);
    return { key: s.abbr, label: s.name, idx, parts, total, text: mw(total) };
  }).filter((r) => r.total > 0).sort((a, b) => b.total - a.total);
  const placeBars = stackedBars(placeBody, {
    rows: placeRows, keys: mwTypes.map((t) => ({ key: t.id, label: t.name, color: t.color })), fmt: mw,
    ariaLabel: "Mapped power capacity by voivodeship",
    onHover: (x) => link.hover(x ? { states: new Set([x.row.idx]), dimOthers: true, label: x.row.label } : null),
    onClick: (x) => setVoivodeship(filter.voivodeship === x.row.key ? null : x.row.key, true),
  });

  const renewable = res.renewables;
  if (renewable?.rows?.length && renewable.fields?.length) {
    const renewableBody = section(el, { title: "Renewables by powiat" });
    const fields = renewable.fields;
    const rows = renewable.rows.map((row) => ({
      key: row[0], powiat: row[0], values: Object.fromEntries(fields.map((f, i) => [typeof f === "string" ? f : f.key, row[i + 1]])),
    }));
    const fieldByKey = new Map(fields.map((f) => [typeof f === "string" ? f : f.key, f]));
    const capacityKeys = fields.map((f) => typeof f === "string" ? f : f.key).filter((k) => k.endsWith("_mw") && !["cofiring_mw", "res_mw"].includes(k));
    rows.forEach((r) => { r.total = fin(r.values.res_mw) ? r.values.res_mw : capacityKeys.reduce((sum, k) => sum + (fin(r.values[k]) ? r.values[k] : 0), 0); });
    createTable(renewableBody, {
      caption: "Renewable capacity by powiat", search: "Search powiat code", rank: true, maxHeight: 300,
      rows,
      columns: [
        { key: "powiat", label: "Powiat", align: "l", value: (r) => r.powiat, text: (r) => r.powiat },
        { key: "total", label: "Renewables", value: (r) => r.total, text: (r) => mw(r.total) },
        ...capacityKeys.slice(0, 4).map((k) => ({ key: k, label: fieldByKey.get(k)?.label || k.replace(/_mw$/, "").replaceAll("_", " "), value: (r) => r.values[k], text: (r) => fin(r.values[k]) ? mw(r.values[k]) : "-", hideBelow: 400 })),
      ],
      sort: { key: "total", dir: "desc" },
    });
  }

  function visible() {
    return items.filter((it) => filter.types.has(it.type) && (!filter.min || (isMW(it.type) && fin(it.value) && it.value >= filter.min)) && (!filter.voivodeship || it.state === filter.voivodeship));
  }

  function setVoivodeship(abbr, fly = false) {
    filter.voivodeship = abbr;
    placeBars.setSelected(abbr);
    apply();
    const idx = abbr ? voivodeshipIdx.get(abbr) : null;
    if (fly && idx != null) {
      const bounds = app.highlightBounds({ states: new Set([idx]) });
      if (bounds) frameBox(app, bounds, { pad: 30, maxScale: 2.6 });
    }
  }

  function apply() {
    const mapTypes = filter.min ? new Set([...filter.types].filter(isMW)) : filter.types;
    const all = mapTypes.size === types.length && !filter.min;
    ctx.setResourceFilter(all ? null : { types: new Set(mapTypes), minValue: filter.min || undefined });
    const shown = visible();
    siteTable.setRows(shown);
    const idx = filter.voivodeship ? voivodeshipIdx.get(filter.voivodeship) : null;
    link.base({ dimOthers: true, states: idx != null ? new Set([idx]) : undefined });
    activePlace.innerHTML = idx != null ? `<span class="adv-fchip">Voivodeship: <b>${esc(voivodeships[idx]?.name || filter.voivodeship)}</b> &middot; ${int(shown.length)} sites<button type="button" data-clear-place aria-label="Clear the voivodeship filter">x</button></span>` : "";
    const values = items.filter((it) => isMW(it.type) && fin(it.value)).map((it) => it.value);
    const max = Math.max(1, ...values);
    const radius = (v) => 24 * Math.sqrt(v / max);
    sizeKey.innerHTML = sizeLegend([250, 1000, 4000].filter((v) => v <= max * 1.2), radius, (v) => `${int(v)} MW`, "Circle area = capacity");
    mixBars.setSelected(filter.types.size === 1 ? [...filter.types][0] : null);
  }
  apply();

  return {
    onMapHover(h) {
      if (!h.resource) return;
      const idx = res.items.indexOf(h.resource);
      if (idx >= 0) siteTable.setHot(String(idx));
    },
    onEscape() {
      if (!filter.voivodeship) return false;
      setVoivodeship(null);
      return true;
    },
  };
}

function statusText(status) {
  return { operating: "Operating", under_construction: "Under construction", planned: "Planned", closing: "Closing", closed: "Closed", historic: "Historic" }[status] || status || "-";
}

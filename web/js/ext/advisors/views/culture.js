// Culture advisor: Polish World Heritage, memorials, parks, universities, landmarks and the 2024 flood area.
import { esc, fin } from "../core/util.js";
import { int, count3 } from "../core/fmt.js";
import { barList } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, segmented, lensButton } from "../core/view.js";
import { focusPoint } from "../core/frame.js";
import { rowsHighlight } from "../core/data.js";

const KIND = {
  unesco: { label: "World Heritage", color: "#c9a45c" },
  memorial: { label: "Memorial site", color: "#777b82" },
  natural: { label: "National park", color: "#6e9a3c" },
  university: { label: "Research university", color: "#4a86d6" },
  landmark: { label: "National record", color: "#c46a4f" },
};

export async function mount(ctx) {
  const { app, data, el, link } = ctx;
  const [places, disasters] = await Promise.all([
    app.loadData("wonders"),
    app.loadData("disasters").catch(() => null),
  ]);
  if (!places) {
    el.innerHTML = `<p class="adv-empty pad">No cultural site data is available.</p>`;
    return {};
  }
  const all = (places.wonders || []).map((site, index) => ({ ...site, key: site.id || String(index) }));
  const rules = new Map((places.rules || []).map((rule) => [rule.id, rule]));
  const national = places.national || {};
  const memorialCount = all.filter((site) => site.kind === "memorial").length;
  el.insertAdjacentHTML("beforeend", tiles([
    { label: "World Heritage", value: int(national.unesco_properties ?? all.filter((site) => site.rule === "unesco_property").length), sub: "properties in Poland" },
    { label: "National parks", value: int(national.national_parks), sub: national.park_visits ? `${count3(national.park_visits)} visits in ${national.park_visits_year}` : "parks" },
    { label: "Memorial sites", value: int(memorialCount), sub: "shown separately" },
  ]));

  const rulesBody = section(el, { title: "What appears on the map" });
  rulesBody.insertAdjacentHTML("beforeend", [...rules.values()].map((rule) => `<p class="adv-note"><b>${esc(ruleTitle(rule.id))}:</b> ${esc(ruleSummary(rule))}</p>`).join(""));

  const siteBody = section(el, { title: "Heritage and landmarks" });
  let kind = "all";
  segmented(siteBody, {
    label: "Show",
    value: kind,
    options: [{ value: "all", label: "All" }, ...Object.entries(KIND).map(([value, item]) => ({ value, label: item.label }))],
    onChange: (value) => { kind = value; drawSites(); },
  });
  const siteTable = createTable(siteBody, {
    caption: "Mapped cultural and natural sites", search: "Search places", rank: false, maxHeight: 390, rows: [],
    columns: [
      { key: "name", label: "Place", align: "l", width: "minmax(0,1.8fr)", value: (r) => r.name, html: (r) => `<span class="dot" style="background:${KIND[r.kind]?.color || "#aaa"}"></span>${esc(r.short || r.name)}`, tip: (r) => r.name },
      { key: "kind", label: "Type", align: "l", width: "minmax(0,1fr)", value: (r) => KIND[r.kind]?.label, text: (r) => KIND[r.kind]?.label || r.kind },
      { key: "rank", label: "Rank", value: (r) => r.rank, text: (r) => r.kind === "memorial" || r.rank == null ? "-" : int(r.rank) },
      { key: "figure", label: "Figure", value: siteValue, text: siteValueText, hideBelow: 420 },
    ],
    sort: { key: "kind", dir: "asc" },
    onHover: (r) => link.hover(r ? { cells: new Set([r.cell]), dimOthers: true, label: r.name } : null),
    onClick: (r) => focusPoint(app, r.x, r.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
  });
  function drawSites() {
    siteTable.setRows(kind === "all" ? all : all.filter((site) => site.kind === kind));
  }
  drawSites();

  for (const [id, title, metric, label] of [
    ["national_park", "Most visited national parks", (site) => site.metrics?.visits, (site) => count3(site.metrics?.visits)],
    ["research_university", "Largest top-research universities", (site) => site.metrics?.students, (site) => `${int(site.metrics?.students)} students`],
  ]) {
    const rows = all.filter((site) => site.rule === id && fin(metric(site))).sort((a, b) => metric(b) - metric(a));
    if (!rows.length) continue;
    const body = section(el, { title });
    barList(body, {
      rows: rows.map((site) => ({ key: site.id, label: site.short || site.name, sub: label(site), value: metric(site), color: KIND[site.kind]?.color, site })),
      rank: true, ariaLabel: title,
      onHover: (row) => link.hover(row ? { cells: new Set([row.site.cell]), dimOthers: true, label: row.site.name } : null),
      onClick: (row) => focusPoint(app, row.site.x, row.site.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
    });
  }

  let floodTable = null;
  if (disasters?.flood_2024) {
    const flood = disasters.flood_2024;
    const summary = flood.summary || {};
    const floodBody = section(el, { title: "September 2024 flood area" });
    floodBody.insertAdjacentHTML("beforeend", tiles([
      { label: "Gminas", value: int(summary.gminas), sub: "in the declared area" },
      { label: "Powiats", value: int(summary.powiats), sub: "covered by the regulation" },
      { label: "Part-gmina entry", value: int(summary.partial_gminas), sub: "Małomice town only" },
    ]));
    const lensRow = document.createElement("div");
    lensRow.className = "adv-row";
    const floodLens = lensButton(app, "disasters", "Show the flood map") || lensButton(app, "flood_2024", "Show the flood map");
    if (floodLens) lensRow.appendChild(floodLens);
    floodBody.appendChild(lensRow);
    const columns = flood.gminas?.columns || [];
    const index = Object.fromEntries(columns.map((name, i) => [name, i]));
    const declared = new Map((flood.gminas?.rows || []).filter((row) => row[index.declared]).map((row) => [row[index.geoid], row]));
    const gminas = data.levels.counties;
    const rows = gminas ? gminas.rows.filter((row) => declared.has(row.key)).map((row) => {
      const source = declared.get(row.key);
      return { ...row, floodDate: source[index.date], partial: !!source[index.partial] };
    }) : [];
    floodTable = createTable(floodBody, {
      caption: "Gminas in the 2024 declared flood area", search: "Search gminas", rank: false, maxHeight: 300, rows,
      columns: [
        { key: "name", label: "Gmina", align: "l", width: "minmax(0,1.6fr)", value: (r) => r.name, html: (r) => `${esc(r.name)} <span class="sub">${esc(r.sub || "")}</span>` },
        { key: "date", label: "Added", value: (r) => r.floodDate, text: (r) => dateText(r.floodDate) },
        { key: "partial", label: "Coverage", align: "l", value: (r) => r.partial ? 1 : 0, text: (r) => r.partial ? "Town only" : "Whole gmina" },
      ],
      sort: { key: "date", dir: "asc" },
      onHover: (row) => link.hover(row ? rowsHighlight(gminas, [row], { dim: true, label: row.name }) : null),
      onClick: (row) => gminas.focus(row),
    });
  }

  return {
    onMapHover(event) {
      if (event.layer === "wonders" && event.item?.data?.id) siteTable.setHot(event.item.data.id);
      if (floodTable && event.cell >= 0 && data.levels.counties) {
        const row = data.levels.counties.rowAtCell(event.cell);
        floodTable.setHot(row?.key || null, false);
      }
    },
  };
}

function ruleTitle(id) {
  return {
    unesco_property: "World Heritage",
    national_park: "National parks",
    research_university: "Research universities",
    landmark: "National records",
  }[id] || id;
}

function ruleSummary(rule) {
  return {
    unesco_property: "Every World Heritage property in Poland. Serial properties use their best-known Polish component. Memorial sites remain separate and unranked.",
    national_park: "The six national parks with the most visitors in 2024.",
    research_university: "The six largest institutions by students among those with at least one A+ research category.",
    landmark: "Four national records: tallest building, busiest seaport, largest power station and busiest airport.",
  }[rule.id] || rule.text || "";
}

function siteValue(site) {
  const metrics = site.metrics || {};
  return metrics.visits ?? metrics.students ?? metrics.value ?? null;
}

function siteValueText(site) {
  const metrics = site.metrics || {};
  if (fin(metrics.visits)) return `${count3(metrics.visits)} visits`;
  if (fin(metrics.students)) return `${int(metrics.students)} students`;
  if (fin(metrics.value)) return `${count3(metrics.value)} ${metrics.unit || ""}`.trim();
  if (fin(metrics.inscribed)) return `Since ${int(metrics.inscribed)}`;
  return "-";
}

function dateText(value) {
  const text = String(value || "");
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  return text.length === 8 ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}` : "-";
}

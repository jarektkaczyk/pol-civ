// Culture advisor: Polish World Heritage, memorials, parks, universities, landmarks and the 2024 flood area.
import { esc, fin } from "../core/util.js";
import { int, count3 } from "../core/fmt.js";
import { barList } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, segmented, lensButton } from "../core/view.js";
import { focusPoint } from "../core/frame.js";
import { rowsHighlight } from "../core/data.js";
import { t, date } from "../../../i18n.js";

const KIND = {
  unesco: { label: t("World Heritage"), color: "#c9a45c" },
  memorial: { label: t("Memorial site"), color: "#777b82" },
  natural: { label: t("National park"), color: "#6e9a3c" },
  university: { label: t("Research university"), color: "#4a86d6" },
  landmark: { label: t("National record"), color: "#c46a4f" },
};

export async function mount(ctx) {
  const { app, data, el, link } = ctx;
  const [places, disasters] = await Promise.all([
    app.loadData("wonders"),
    app.loadData("disasters").catch(() => null),
  ]);
  if (!places) {
    el.innerHTML = `<p class="adv-empty pad">${esc(t("No cultural site data is available."))}</p>`;
    return {};
  }
  const all = (places.wonders || []).map((site, index) => ({ ...site, key: site.id || String(index), label: t(site.name), shortLabel: t(site.short || site.name) }));
  const rules = new Map((places.rules || []).map((rule) => [rule.id, rule]));
  const national = places.national || {};
  const memorialCount = all.filter((site) => site.kind === "memorial").length;
  el.insertAdjacentHTML("beforeend", tiles([
    { label: t("World Heritage"), value: int(national.unesco_properties ?? all.filter((site) => site.rule === "unesco_property").length), sub: t("properties in Poland") },
    { label: t("National parks"), value: int(national.national_parks), sub: national.park_visits ? t.plural(big(national.park_visits), { one: "{v} visit in {year}", other: "{v} visits in {year}" }, { v: count3(national.park_visits), year: String(national.park_visits_year ?? "") }) : t("parks") },
    { label: t("Memorial sites"), value: int(memorialCount), sub: t("shown separately") },
  ]));

  const rulesBody = section(el, { title: t("What appears on the map") });
  rulesBody.insertAdjacentHTML("beforeend", [...rules.values()].map((rule) => `<p class="adv-note"><b>${esc(ruleTitle(rule.id))}:</b> ${esc(ruleSummary(rule))}</p>`).join(""));

  // Memorial sites are never grouped with heritage sites and landmarks: they get their own quiet line below the table.
  const memorials = all.filter((site) => site.kind === "memorial");
  const sites = all.filter((site) => site.kind !== "memorial");
  const siteBody = section(el, { title: t("Heritage sites and landmarks") });
  let kind = "all";
  segmented(siteBody, {
    label: t("Show"),
    value: kind,
    options: [{ value: "all", label: t("All") }, ...Object.entries(KIND).filter(([value]) => value !== "memorial").map(([value, item]) => ({ value, label: item.label }))],
    onChange: (value) => { kind = value; drawSites(); },
  });
  const siteTable = createTable(siteBody, {
    caption: t("Mapped cultural and natural sites"), search: t("Search places"), rank: false, maxHeight: 390, rows: [],
    searchText: (r) => `${r.label} ${r.shortLabel} ${r.name}`,
    columns: [
      { key: "name", label: t("Place"), align: "l", width: "minmax(0,1.8fr)", value: (r) => r.label, html: (r) => `<span class="dot" style="background:${KIND[r.kind]?.color || "#aaa"}"></span>${esc(r.shortLabel)}`, tip: (r) => r.label },
      { key: "kind", label: t("Type"), align: "l", width: "minmax(0,1fr)", value: (r) => KIND[r.kind]?.label, text: (r) => KIND[r.kind]?.label || r.kind },
      { key: "rank", label: t("Rank"), value: (r) => r.rank, text: (r) => r.kind === "memorial" || r.rank == null ? "-" : int(r.rank) },
      { key: "figure", label: t("Figure"), value: siteValue, text: siteValueText, hideBelow: 420 },
    ],
    sort: { key: "kind", dir: "asc" },
    onHover: (r) => link.hover(r ? { cells: new Set([r.cell]), dimOthers: true, label: r.label } : null),
    onClick: (r) => focusPoint(app, r.x, r.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
  });
  function drawSites() {
    siteTable.setRows(kind === "all" ? sites : sites.filter((site) => site.kind === kind));
  }
  drawSites();
  if (memorials.length) {
    siteBody.insertAdjacentHTML("beforeend", memorials.map((site) => `<p class="adv-note">${esc(site.metrics?.inscribed ? t("Memorial site: {name}, UNESCO World Heritage since {year}.", { name: site.label, year: String(site.metrics.inscribed) }) : t("Memorial site: {name}.", { name: site.label }))}</p>`).join(""));
  }

  for (const [id, title, metric, label] of [
    ["national_park", t("Most visited national parks"), (site) => site.metrics?.visits, (site) => count3(site.metrics?.visits)],
    ["research_university", t("Largest top-research universities"), (site) => site.metrics?.students, (site) => t.plural(site.metrics?.students, { one: "{n} student", other: "{n} students" })],
  ]) {
    const rows = all.filter((site) => site.rule === id && fin(metric(site))).sort((a, b) => metric(b) - metric(a));
    if (!rows.length) continue;
    const body = section(el, { title });
    barList(body, {
      rows: rows.map((site) => ({ key: site.id, label: site.shortLabel, sub: label(site), value: metric(site), color: KIND[site.kind]?.color, site })),
      rank: true, ariaLabel: title,
      onHover: (row) => link.hover(row ? { cells: new Set([row.site.cell]), dimOthers: true, label: row.site.label } : null),
      onClick: (row) => focusPoint(app, row.site.x, row.site.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2))),
    });
  }

  let floodTable = null;
  if (disasters?.flood_2024) {
    const flood = disasters.flood_2024;
    const summary = flood.summary || {};
    const floodBody = section(el, { title: t("September 2024 flood area") });
    floodBody.insertAdjacentHTML("beforeend", tiles([
      { label: t("Gminas"), value: int(summary.gminas), sub: t("in the declared area") },
      { label: t("Powiats"), value: int(summary.powiats), sub: t("covered by the regulation") },
      { label: t("Part-gmina entry"), value: int(summary.partial_gminas), sub: t("Ma\u0142omice town only") },
    ]));
    const lensRow = document.createElement("div");
    lensRow.className = "adv-row";
    const floodLens = lensButton(app, "disasters", t("Show the flood map")) || lensButton(app, "flood_2024", t("Show the flood map"));
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
      caption: t("Gminas in the 2024 declared flood area"), search: t("Search gminas"), rank: false, maxHeight: 300, rows,
      columns: [
        { key: "name", label: t("Gmina"), align: "l", width: "minmax(0,1.6fr)", value: (r) => r.name, html: (r) => `${esc(r.name)} <span class="sub">${esc(r.sub || "")}</span>` },
        { key: "date", label: t("Added"), value: (r) => r.floodDate, text: (r) => dateText(r.floodDate) },
        { key: "partial", label: t("Coverage"), align: "l", value: (r) => r.partial ? 1 : 0, text: (r) => r.partial ? t("Town only") : t("Whole gmina") },
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
    unesco_property: t("World Heritage"),
    national_park: t("National parks"),
    research_university: t("Research universities"),
    landmark: t("National records"),
  }[id] || id;
}

function ruleSummary(rule) {
  return {
    unesco_property: t("Every World Heritage property in Poland. Serial properties use their best-known Polish component. Memorial sites remain separate and unranked."),
    national_park: t("The six national parks with the most visitors in 2024."),
    research_university: t("The six largest institutions by students among those with at least one A+ research category."),
    landmark: t("Four national records: tallest building, busiest seaport, largest power station and busiest airport."),
  }[rule.id] || (rule.text ? t(rule.text) : "");
}

// A count in short form; a scale word (K, M; tys., mln) takes the plural of a large number.
function big(v) {
  return Math.abs(v) >= 1e4 ? 1e6 : Math.round(v);
}

function siteValue(site) {
  const metrics = site.metrics || {};
  return metrics.visits ?? metrics.students ?? metrics.value ?? null;
}

function siteValueText(site) {
  const metrics = site.metrics || {};
  if (fin(metrics.visits)) return t.plural(big(metrics.visits), { one: "{v} visit", other: "{v} visits" }, { v: count3(metrics.visits) });
  if (fin(metrics.students)) return t.plural(metrics.students, { one: "{n} student", other: "{n} students" });
  if (fin(metrics.value)) return `${count3(metrics.value)} ${metrics.unit ? t(metrics.unit) : ""}`.trim();
  if (fin(metrics.inscribed)) return t("Since {year}", { year: String(metrics.inscribed) });
  return "-";
}

function dateText(value) {
  const text = String(value || "");
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return date(text);
  return text.length === 8 ? date(`${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}`) : "-";
}

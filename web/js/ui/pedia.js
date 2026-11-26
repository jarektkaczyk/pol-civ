// The Almanac: what every number means and exactly where it comes from.
import { resolveTables } from "../terrain.js";
import { esc } from "../format.js";
import { parseHex, luminance } from "../color.js";
import { icon, glyph } from "./icon.js";

const COVER_ICON = { forest_deciduous: "l-forest", forest_evergreen: "l-forest", forest_mixed: "l-forest", cropland: "l-farmland", pasture: "l-farmland", urban: "l-developed" };
// Glyph colour that reads on a resource medallion (dark on light faces such as nuclear yellow or silver).
const inkOn = (hex) => {
  try { return /^#[0-9a-f]{6}$/i.test(hex || "") && luminance(parseHex(hex)) > 0.4 ? "#1c1710" : "#f8f0d8"; } catch { return "#f8f0d8"; }
};
const CATEGORY = { energy: "Energy", mineral: "Minerals", agri: "Agriculture" };

export function initPedia(data) {
  const modal = document.getElementById("pedia");
  const card = modal.querySelector(".modal-card");
  const nav = document.getElementById("pedia-nav");
  const body = document.getElementById("pedia-body");
  const srcName = (id) => data.sources?.find((s) => s.id === id)?.title || id || "";
  let restoreFocus = null;

  const h2 = (ic, fb, text) => `<h2>${icon(ic, fb, { size: 24 })}<span>${esc(text)}</span></h2>`;

  const pages = {
    "About this map": () => `
      ${h2("pedia", "📖", "About this map")}
      <p>This is real Poland, drawn like a strategy game. Every tile, town and number comes from public data, listed
      under <i>Sources</i>.</p>
      <h4>How it is built</h4>
      <p>The country is projected (Albers equal-area) and cut into ${data.world.grid.cols} by ${data.world.grid.rows}
      hexes, each ${data.world.grid.radius * 2} km corner to corner. Each hex belongs to the voivodeship, powiat and gmina
      under its centre. Terrain comes from the elevation and land-cover samples inside each hex.</p>
      <p><b>Towns</b> are the seats of gminas with town rights, placed at the town itself. The bigger ones, the cities with
      powiat rights and the towns of 20,000 people or more, open a full town screen. A <b>metro area</b> is the functional
      urban area that Eurostat draws around a city: the city and the gminas whose people commute into it.</p>
      <h4>How to read it</h4>
      <p><b>Yields are names for real figures.</b> Gold is GDP, Food is the people who work the land, and so on: the
      <i>Yields</i> page gives each rule. Nothing is scored or simulated.</p>
      <p><b>Positions are schematic.</b> A hex is a few kilometres wide, so a town, a mine or a power station sits on the hex
      that holds it, not at its exact address. Rivers, coasts and borders follow the hexes.</p>
      <p><b>Missing data stays missing.</b> When a figure is not published for a place, the map shows a dash or leaves the
      place uncoloured. It never shows a zero or a guess.</p>
      <p><b>Selections are rules.</b> Wonders, resources and badges are picked by a published rule (for example every
      UNESCO World Heritage site, or every power station above a size), never by taste. Each rule is in this Almanac.</p>
      <h4>Controls</h4>
      <p>Drag, the arrow keys or WASD pan the map. Scroll, + and - or a double-click zoom. Click a town or a voivodeship to
      open it. Press / to search, L to change the lens, R to show or hide resources, ? for every shortcut and Esc to close.</p>
      <p>The address bar always holds a link to what you are looking at. Use <i>Share</i> to copy it or to download a picture.</p>
      <h4>Credits</h4>
      <p>This map is a fork of <a href="https://karpathy.ai/usaciv/" target="_blank" rel="noopener">usaciv</a>, which draws
      the United States the same way, and is shared under the same MIT licence.
      <a href="https://github.com/jarektkaczyk/pol-civ" target="_blank" rel="noopener">Source code</a>.</p>`,
    Yields: () => {
      // The rule behind each yield (docs/BLUEPRINT.md section 8; the builder records the exact rule in yields.py).
      const RULE = {
        food: "People working in agriculture, forestry and fishing.",
        production: "People working in industry and construction.",
        gold: "GDP: the value of everything produced in a year, counted where the work is done. Subregion GDP is shared out to each powiat by its wage bill.",
        science: "People working in information and communication, and in professional, scientific and technical activities.",
        culture: "People working in arts, entertainment and recreation, and in accommodation.",
      };
      return `
      ${h2("y-production", "⚙️", "Yields")}
      <p>The yields of a strategy game, mapped onto real figures. Job-based yields count the people working in a group of
      industries (the PKD sections of the Polish classification of activities). <b>Gold is GDP</b>.</p>
      <table>${data.nation.yields.map((y) => `<tr><td class="ic" style="color:${esc(y.color)}">${glyph(y, 26)}</td><td><b style="color:${esc(y.color)}">${esc(y.label)}${y.key === "gold" ? " (GDP)" : ""}</b><br>${esc(y.description || RULE[y.key] || "")}</td></tr>`).join("")}</table>
      <h4>Badges</h4>
      <p>A town's badge comes from the first of these rules that holds: Capital city (Warszawa); Port city (a seaport
      within 10 km); Copper town (a copper mine or smelter within 15 km); Coal town (a hard coal or lignite mine within
      15 km); Tech city (information and communication at least twice the national share of workers, and at least 4% of
      them); University town (university students equal to at least 10% of residents); Spa town ("Zdrój" in the official
      name); Tourist town (hotels and restaurants at least twice the national share of workers); Industrial town (mining
      and manufacturing at least 1.5 times the national share); Garrison town (a military unit or base within 5 km).
      Refinery town and Auto city are not awarded: no dataset in this build names refineries or car factories by town.
      Shares of workers are per powiat, so a town without powiat rights shares its powiat's.</p>
      <h4>Work</h4>
      <p>Unemployment is the registered unemployment rate: the people registered as unemployed at labour offices, as a share
      of the economically active population.</p>`;
    },
    Voivodeships: () => `
      ${h2("terrain", "🗺️", "Voivodeships")}
      <p>Click any land hex without a town to open its voivodeship. A voivodeship's numbers are the totals of all its
      powiaty, so rural areas count too (${esc(data.nation.vintage)}). Its Gold is the voivodeship GDP for
      ${esc(String(data.nation.years?.gdp_voiv ?? ""))} as Eurostat publishes it; Mazowieckie adds up its two statistical
      regions, Warsaw and the rest of the voivodeship. Its wage is the average of its powiaty, weighted by their workers.</p>
      <p><b>Ranks</b> ("#3 of 16") compare the 16 voivodeships; 1 is the largest.</p>
      <p>Kujawsko-Pomorskie and Lubuskie have two capitals: the voivode sits in Bydgoszcz and Gorzów Wielkopolski, the
      regional assembly in Toruń and Zielona Góra.</p>
      <h4>Towns and metro areas</h4>
      <p>Every town with town rights has a banner. The City View opens for the 66 cities with powiat rights and for every
      other town of 20,000 people or more. A town inside an urban-rural gmina shares its figures with the villages of
      that gmina; its population is the town's own. Wages, unemployment and the mix of jobs are published per powiat, so
      a town without powiat rights shows its powiat's.</p>
      <p>Metro areas are the functional urban areas of Eurostat: a city and the gminas from which at least 15% of working
      residents commute to it. ${esc(data.metros?.rule ? data.metros.rule.split(". ").slice(1).join(". ") : "")}</p>
      ${data.states ? "" : `<p class="muted">This data build has no voivodeship statistics.</p>`}`,
    Terrain: () => {
      const t = data.w?.tables || resolveTables(data.world.tables);
      const hasCover = Array.isArray(data.world.cover);
      const row = (x) => `<tr><td class="nm">${x.color ? `<span class="swatch" style="background:${esc(x.color)}"></span>` : ""}${
        COVER_ICON[x.key] ? icon(COVER_ICON[x.key], "", { size: 15 }) + " " : ""}<b>${esc(x.name)}</b></td><td>${esc(x.rule || "")}</td></tr>`;
      return `
      ${h2("terrain", "🗺️", "Terrain")}
      <p>Each hex averages the elevation samples inside it. Relief comes from the mean elevation and the roughness of those
      samples: the plains of the north and centre stay flat, the uplands of the south rise into hills, and the Sudety and
      the Tatra become mountains with snow on the highest peaks. Shading comes from the height of each hex against its
      neighbours, lit from the north-west.</p>
      <h4>${icon("l-forest", "🌲", { size: 16 })} Land cover</h4>
      ${hasCover
        ? `<p>The base colour of each hex is its main land cover: the largest group among the land samples inside it.
           Small symbols show the mix: trees grow with the forest share, and fields, reeds, shrubs and grass mark farmland,
           wetland, scrub and meadow.</p>
           <table>${t.cover.filter((x) => x.id > 0).map(row).join("")}</table>`
        : `<p class="muted">This data build has no land-cover layer yet; land is coloured by elevation.</p>`}
      <h4>Relief</h4>
      <table>${t.relief.map(row).join("")}</table>
      <h4>${icon("r-hydro", "💧", { size: 16 })} Water</h4>
      <table>${t.water.filter((x) => x.id > 0).map(row).join("")}</table>
      <h4>Beyond the borders</h4>
      <p class="muted">The Baltic Sea and the neighbouring countries (Germany, Czechia, Slovakia, Ukraine, Belarus,
      Lithuania and the Kaliningrad region of Russia) are drawn under a light fog: they are shown for context and not
      mapped in detail.</p>`;
    },
    Lenses: () => `
      ${h2("layers", "▤", "Lenses")}
      <p>Lenses recolour the map by one measure, built from gmina data. Each hex is sampled at 7 points. A gmina covering
      some of them is assumed to cover that share of the hex, and the hex shows the average of its gminas weighted by
      their residents. Small gminas that no sample hits are added to the hex under their centre. A measure that GUS,
      PKW or the Church publish only per powiat, voivodeship or diocese gives every gmina its area's value: the legend
      says so.</p>
      <p>The legend shows how many hexes fall at each value. Hover or drag on it to show only that range on the map.</p>
      ${(data.lenses.groups || [{ id: null, name: "" }]).map((g) => {
        const ls = data.lenses.lenses.filter((l) => !g.id || l.group === g.id);
        if (!ls.length) return "";
        return `${g.name ? `<h3 class="grp">${icon(`g-${g.id}`, "", { size: 16 })} ${esc(g.name)}</h3>` : ""}${ls.map((l) => `
          <div class="lens-entry"><div class="le-ic">${glyph(l, 26)}</div><div>
          <h4>${esc(l.name)}</h4><p>${esc(l.description)}<br>
          <i class="le-ramp" style="background:linear-gradient(90deg, ${(l.ramp || []).map(esc).join(",")})"></i>
          <span class="muted">Scale: ${esc(l.scale)}, ${l.domain[0].toLocaleString()}–${l.domain[1].toLocaleString()} ${esc(l.unit)}${
            l.higher_is === "good" ? " · higher is better" : l.higher_is === "bad" ? " · higher is worse" : ""}${l.source ? " · " + esc(srcName(l.source)) : ""}</span></p></div></div>`).join("")}`;
      }).join("")}`,
    Resources: () => {
      const r = data.resources;
      if (!r?.types?.length) return `${h2("resources", "⛏️", "Resources")}<p class="muted">This data build has no resources layer.</p>`;
      const count = new Map();
      for (const it of r.items || []) count.set(it.type, (count.get(it.type) || 0) + 1);
      const cats = [...new Set(r.types.map((t) => t.category || "other"))];
      return `
      ${h2("resources", "⛏️", "Resources")}
      <p>Resources mark the country's biggest power plants, mines and oil &amp; gas fields on the tiles where they are.
      Only meaningful sites are shown: each type's threshold is in its description. When zoomed out, a hex shows its
      highest-ranked resource; zoom in to see more. Press <b>R</b> to show or hide them.</p>
      ${cats.map((c) => `<h4>${esc(CATEGORY[c] || c)}</h4><table class="res-table">
        <tr><th></th><th>Type</th><th>What counts</th><th>Sites</th></tr>
        ${r.types.filter((t) => (t.category || "other") === c).map((t) => `<tr>
          <td class="ic"><span class="res-ic" style="background:${esc(t.color || "#24384f")};color:${inkOn(t.color)}">${glyph(t, 20)}</span></td>
          <td class="nm"><b>${esc(t.name)}</b>${t.unit ? `<br><span class="muted">value in ${esc(t.unit)}</span>` : ""}</td>
          <td>${esc(t.description || "")}<br><span class="muted">Source: ${esc(srcName(t.source))}</span></td>
          <td class="num">${count.get(t.id) || 0}</td></tr>`).join("")}</table>`).join("")}`;
    },
    Sources: () => `
      ${h2("pedia", "📖", "Sources")}
      ${data.sources.map((s) => `
        <h4>${esc(s.title)}</h4>
        <p>${esc(s.description)}<br>
        <span class="muted">${esc(s.publisher)} · ${esc(s.license)}${s.vintage ? " · " + esc(s.vintage) : ""} ·
        <a href="${esc(s.homepage)}" target="_blank" rel="noopener">homepage</a></span></p>
        <table>${(s.files || []).map((f) => `<tr><td><code>${esc(f.url)}</code></td><td class="muted" style="white-space:nowrap">${esc((f.retrieved || "").slice(0, 10))}<br>${((f.bytes || 0) / 1e6).toFixed(1)} MB</td></tr>`).join("")}</table>`).join("")}`,
  };

  const show = (name) => {
    if (!pages[name]) name = "About this map";
    body.innerHTML = pages[name]();
    body.scrollTop = 0;
    nav.querySelectorAll("button").forEach((b) => {
      const on = b.dataset.page === name;
      b.classList.toggle("active", on);
      b.setAttribute("aria-current", on ? "page" : "false");
    });
  };
  nav.innerHTML = `<div class="hd">Almanac</div>` + Object.keys(pages).map((p) => `<button data-page="${esc(p)}">${esc(p)}</button>`).join("");
  nav.onclick = (e) => {
    const b = e.target.closest("button[data-page]");
    if (b) show(b.dataset.page);
  };
  const close = () => {
    if (modal.hidden) return;
    modal.hidden = true;
    if (restoreFocus && document.contains(restoreFocus)) restoreFocus.focus();
    restoreFocus = null;
  };
  modal.onclick = (e) => {
    if (e.target === modal || e.target.closest("[data-close]")) close();
  };
  // Keep Tab inside the dialog.
  modal.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = [...card.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")].filter((x) => x.offsetParent);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  return {
    open(page = "About this map") {
      if (modal.hidden) restoreFocus = document.activeElement;
      show(page);
      modal.hidden = false;
      (nav.querySelector("button.active") || card.querySelector("[data-close]"))?.focus();
    },
    close,
    get isOpen() {
      return !modal.hidden;
    },
  };
}

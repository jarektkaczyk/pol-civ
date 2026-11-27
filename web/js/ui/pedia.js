// The Almanac: what every number means and exactly where it comes from.
import { resolveTables } from "../terrain.js";
import { esc, int } from "../format.js";
import { t, num, date } from "../i18n.js";
import { parseHex, luminance } from "../color.js";
import { icon, glyph } from "./icon.js";

// Links from data files open only as http(s); anything else (javascript:, data:) becomes an inert "#".
const safeUrl = (u) => (/^https?:\/\//i.test(String(u ?? "")) ? String(u) : "#");

const COVER_ICON = { forest_deciduous: "l-forest", forest_evergreen: "l-forest", forest_mixed: "l-forest", cropland: "l-farmland", pasture: "l-farmland", urban: "l-developed" };
// Glyph colour that reads on a resource medallion (dark on light faces such as nuclear yellow or silver).
const inkOn = (hex) => {
  try { return /^#[0-9a-f]{6}$/i.test(hex || "") && luminance(parseHex(hex)) > 0.4 ? "#1c1710" : "#f8f0d8"; } catch { return "#f8f0d8"; }
};
const CATEGORY = { energy: t("Energy"), mineral: t("Minerals"), agri: t("Agriculture") };
const SCALE = { log: t("log"), linear: t("linear") };

export function initPedia(data) {
  const modal = document.getElementById("pedia");
  const card = modal.querySelector(".modal-card");
  const nav = document.getElementById("pedia-nav");
  const body = document.getElementById("pedia-body");
  const srcName = (id) => {
    const title = data.sources?.find((s) => s.id === id)?.title;
    return title ? t(title) : id || "";
  };
  let restoreFocus = null;

  const h2 = (ic, fb, text) => `<h2>${icon(ic, fb, { size: 24 })}<span>${esc(text)}</span></h2>`;

  // A translated text with HTML pieces: the text is escaped, then each {name} of `html` is replaced by its markup.
  const th = (text, html = {}) => esc(text).replace(/\{(\w+)\}/g, (m, k) => (k in html ? html[k] : m));
  const ext = (href, text) => `<a href="${esc(safeUrl(href))}" target="_blank" rel="noopener">${esc(text)}</a>`;

  const pages = {
    "About this map": () => `
      ${h2("pedia", "📖", t("About this map"))}
      <p>${th(t("This is real Poland, drawn like a strategy game. Every tile, town and number comes from public data, listed under {sources}."), { sources: `<i>${esc(t("Sources"))}</i>` })}</p>
      <h4>${esc(t("How it is built"))}</h4>
      <p>${esc(t("The country is projected (Albers equal-area) and cut into {cols} by {rows} hexes, each {size} km corner to corner. Each hex belongs to the voivodeship, powiat and gmina under its centre. Terrain comes from the elevation and land-cover samples inside each hex.", { cols: data.world.grid.cols, rows: data.world.grid.rows, size: data.world.grid.radius * 2 }))}</p>
      <p>${th(t("{towns} are the seats of gminas with town rights, placed at the town itself. The bigger ones, the cities with powiat rights and the towns of 20,000 people or more, open a full town screen."), { towns: `<b>${esc(t("Towns"))}</b>` })}
      ${th(t("{metro} is the functional urban area that Eurostat draws around a city: the city and the gminas whose people commute into it."), { metro: `<b>${esc(t("A metro area"))}</b>` })}</p>
      <h4>${esc(t("How to read it"))}</h4>
      <p><b>${esc(t("Yields are names for real figures."))}</b> ${th(t("Gold is GDP, Food is the people who work the land, and so on: the {yields} page gives each rule. Nothing is scored or simulated."), { yields: `<i>${esc(t("Yields"))}</i>` })}</p>
      <p><b>${esc(t("Positions are schematic."))}</b> ${esc(t("A hex is a few kilometres wide, so a town, a mine or a power station sits on the hex that holds it, not at its exact address. Rivers, coasts and borders follow the hexes."))}</p>
      <p><b>${esc(t("Missing data stays missing."))}</b> ${esc(t("When a figure is not published for a place, the map shows a dash or leaves the place uncoloured. It never shows a zero or a guess."))}</p>
      <p><b>${esc(t("Selections are rules."))}</b> ${esc(t("Heritage sites and landmarks, resources and badges are picked by a published rule (for example every UNESCO World Heritage site, or every power station above a size), never by taste. Each rule is in this Almanac."))}</p>
      <h4>${esc(t("Controls"))}</h4>
      <p>${esc(t("Drag, the arrow keys or WASD pan the map. Scroll, + and - or a double-click zoom. Click a town or a voivodeship to open it. Press / to search, L to change the lens, R to show or hide resources, ? for every shortcut and Esc to close."))}</p>
      <p>${th(t("The address bar always holds a link to what you are looking at. Use {share} to copy it or to download a picture."), { share: `<i>${esc(t("Share"))}</i>` })}</p>
      <h4>${esc(t("Credits"))}</h4>
      <p>${th(t("This map uses code from {link} under the MIT licence."), { link: ext("https://karpathy.ai/usaciv/", "usaciv") })}
      ${ext("https://github.com/jarektkaczyk/pol-civ", t("Source code"))}.</p>
      <p>${th(t("The 1914 partition borders and the borders of interwar Poland use simplified lines from {dataset}. Both layers use the {licence} licence."), {
        dataset: ext("https://icr.ethz.ch/data/cshapes/", "CShapes 2.0"),
        licence: ext("https://creativecommons.org/licenses/by-nc-sa/4.0/", "CC BY-NC-SA 4.0"),
      })}</p>
      <p>Schvitz, Guy, Seraina R&uuml;egger, Luc Girardin, Lars-Erik Cederman, Nils Weidmann, and Kristian Skrede Gleditsch. 2022.
      "${ext("https://doi.org/10.1177/00220027211013563", "Mapping The International System, 1886-2017: The CShapes 2.0 Dataset")}."
      <i>Journal of Conflict Resolution</i> 66(1): 144-61.</p>`,
    Yields: () => {
      // The rule behind each yield (docs/BLUEPRINT.md section 8; the builder records the exact rule in yields.py).
      const RULE = {
        food: t("People working in agriculture, forestry and fishing."),
        production: t("People working in industry and construction."),
        gold: t("GDP: the value of everything produced in a year, counted where the work is done. Subregion GDP is shared out to each powiat by its wage bill."),
        science: t("People working in information and communication, and in professional, scientific and technical activities."),
        culture: t("People working in arts, entertainment and recreation, and in accommodation."),
      };
      return `
      ${h2("y-production", "⚙️", t("Yields"))}
      <p>${esc(t("The yields of a strategy game, mapped onto real figures. Job-based yields count the people working in a group of industries (the PKD sections of the Polish classification of activities)."))} <b>${esc(t("Gold is GDP"))}</b>.</p>
      <table>${data.nation.yields.map((y) => `<tr><td class="ic" style="color:${esc(y.color)}">${glyph(y, 26)}</td><td><b style="color:${esc(y.color)}">${esc(y.key === "gold" ? t("{yield} (GDP)", { yield: t(y.label) }) : t(y.label))}</b><br>${esc(y.description ? t(y.description) : RULE[y.key] || "")}</td></tr>`).join("")}</table>
      <h4>${esc(t("Badges"))}</h4>
      <p>${esc(t("A town's badge comes from the first of these rules that holds: Capital city (Warszawa); Port city (a seaport within 10 km); Copper town (a copper mine or smelter within 15 km); Coal town (a hard coal or lignite mine within 15 km); Tech city (information and communication at least twice the national share of workers, and at least 4% of them); University town (university students equal to at least 10% of residents); Spa town (\"Zdrój\" in the official name); Tourist town (hotels and restaurants at least twice the national share of workers); Industrial town (mining and manufacturing at least 1.5 times the national share); Garrison town (a military unit or base within 5 km)."))}
      ${esc(t("Refinery town and Auto city are not awarded: no dataset in this build names refineries or car factories by town."))}
      ${esc(t("Shares of workers are per powiat, so a town without powiat rights shares its powiat's."))}</p>
      <h4>${esc(t("Work"))}</h4>
      <p>${esc(t("Unemployment is the registered unemployment rate: the people registered as unemployed at labour offices, as a share of the economically active population."))}</p>`;
    },
    Voivodeships: () => {
      // The metro rule's first sentence repeats the one above it; show the rest.
      const metroRule = data.metros?.rule ? t(data.metros.rule).split(". ").slice(1).join(". ") : "";
      return `
      ${h2("terrain", "🗺️", t("Voivodeships"))}
      <p>${esc(t("Click any land hex without a town to open its voivodeship. A voivodeship's numbers are the totals of all its powiaty, so rural areas count too ({vintage}).", { vintage: t(data.nation.vintage) }))}
      ${esc(t("Its Gold is the voivodeship GDP for {year} as Eurostat publishes it; Mazowieckie adds up its two statistical regions, Warsaw and the rest of the voivodeship. Its wage is the average of its powiaty, weighted by their workers.", { year: String(data.nation.years?.gdp_voiv ?? "") }))}</p>
      <p>${th(t("{ranks} (\"#3 of 16\") compare the 16 voivodeships; 1 is the largest."), { ranks: `<b>${esc(t("Ranks"))}</b>` })}</p>
      <p>${esc(t("Kujawsko-Pomorskie and Lubuskie have two capitals: the voivode sits in Bydgoszcz and Gorzów Wielkopolski, the regional assembly in Toruń and Zielona Góra."))}</p>
      <h4>${esc(t("Towns and metro areas"))}</h4>
      <p>${esc(t("Every town with town rights has a banner. The City View opens for the 66 cities with powiat rights and for every other town of 20,000 people or more. A town inside an urban-rural gmina shares its figures with the villages of that gmina; its population is the town's own. Wages, unemployment and the mix of jobs are published per powiat, so a town without powiat rights shows its powiat's."))}</p>
      <p>${esc(t("Metro areas are the functional urban areas of Eurostat: a city and the gminas from which at least 15% of working residents commute to it."))} ${esc(metroRule)}</p>
      ${data.states ? "" : `<p class="muted">${esc(t("This data build has no voivodeship statistics."))}</p>`}`;
    },
    Terrain: () => {
      const tb = data.w?.tables || resolveTables(data.world.tables);
      const hasCover = Array.isArray(data.world.cover);
      // Table names and rules come from world.json (or the defaults in terrain.js).
      const row = (x) => `<tr><td class="nm">${x.color ? `<span class="swatch" style="background:${esc(x.color)}"></span>` : ""}${
        COVER_ICON[x.key] ? icon(COVER_ICON[x.key], "", { size: 15 }) + " " : ""}<b>${esc(t(x.name))}</b></td><td>${esc(x.rule ? t(x.rule) : "")}</td></tr>`;
      return `
      ${h2("terrain", "🗺️", t("Terrain"))}
      <p>${esc(t("Each hex averages the elevation samples inside it. Relief comes from the mean elevation and the roughness of those samples: the plains of the north and centre stay flat, the uplands of the south rise into hills, and the Sudety and the Tatra become mountains with snow on the highest peaks. Shading comes from the height of each hex against its neighbours, lit from the north-west."))}</p>
      <h4>${icon("l-forest", "🌲", { size: 16 })} ${esc(t("Land cover"))}</h4>
      ${hasCover
        ? `<p>${esc(t("The base colour of each hex is its main land cover: the largest group among the land samples inside it. Small symbols show the mix: trees grow with the forest share, and fields, reeds, shrubs and grass mark farmland, wetland, scrub and meadow."))}</p>
           <table>${tb.cover.filter((x) => x.id > 0).map(row).join("")}</table>`
        : `<p class="muted">${esc(t("This data build has no land-cover layer yet; land is coloured by elevation."))}</p>`}
      <h4>${esc(t("Relief"))}</h4>
      <table>${tb.relief.map(row).join("")}</table>
      <h4>${icon("r-hydro", "💧", { size: 16 })} ${esc(t("Water"))}</h4>
      <table>${tb.water.filter((x) => x.id > 0).map(row).join("")}</table>
      <h4>${esc(t("Beyond the borders"))}</h4>
      <p class="muted">${esc(t("The Baltic Sea and the neighbouring countries (Germany, Czechia, Slovakia, Ukraine, Belarus, Lithuania and the Kaliningrad region of Russia) are drawn under a light fog: they are shown for context and not mapped in detail."))}</p>`;
    },
    Lenses: () => `
      ${h2("layers", "▤", t("Lenses"))}
      <p>${esc(t("Lenses recolour the map by one measure, built from gmina data. Each hex is sampled at 7 points. A gmina covering some of them is assumed to cover that share of the hex, and the hex shows the average of its gminas weighted by their residents. Small gminas that no sample hits are added to the hex under their centre. A measure that GUS, PKW or the Church publish only per powiat, voivodeship or diocese gives every gmina its area's value: the legend says so."))}</p>
      <p>${esc(t("The legend shows how many hexes fall at each value. Hover or drag on it to show only that range on the map."))}</p>
      ${(data.lenses.groups || [{ id: null, name: "" }]).map((g) => {
        const ls = data.lenses.lenses.filter((l) => !g.id || l.group === g.id);
        if (!ls.length) return "";
        return `${g.name ? `<h3 class="grp">${icon(`g-${g.id}`, "", { size: 16 })} ${esc(t(g.name))}</h3>` : ""}${ls.map((l) => {
          const meta = [
            t("Scale: {scale}, {min}–{max} {unit}", { scale: SCALE[l.scale] || l.scale, min: num(l.domain[0], 3, { trim: true }), max: num(l.domain[1], 3, { trim: true }), unit: t(l.unit) }).trim(),
            l.higher_is === "good" ? t("higher is better") : l.higher_is === "bad" ? t("higher is worse") : "",
            l.source ? srcName(l.source) : "",
          ].filter(Boolean);
          return `
          <div class="lens-entry"><div class="le-ic">${glyph(l, 26)}</div><div>
          <h4>${esc(t(l.name))}</h4><p>${esc(t(l.description))}${l.scale_note ? ` ${esc(t(l.scale_note))}` : ""}<br>
          <i class="le-ramp" style="background:linear-gradient(90deg, ${(l.ramp || []).map(esc).join(",")})"></i>
          <span class="muted">${meta.map(esc).join(" · ")}</span></p></div></div>`;
        }).join("")}`;
      }).join("")}`,
    Resources: () => {
      const r = data.resources;
      if (!r?.types?.length) return `${h2("resources", "⛏️", t("Resources"))}<p class="muted">${esc(t("This data build has no resources layer."))}</p>`;
      const count = new Map();
      for (const it of r.items || []) count.set(it.type, (count.get(it.type) || 0) + 1);
      const cats = [...new Set(r.types.map((x) => x.category || "other"))];
      return `
      ${h2("resources", "⛏️", t("Resources"))}
      <p>${esc(t("Resources mark the country's biggest power plants, mines and oil & gas fields on the tiles where they are. Only meaningful sites are shown: each type's threshold is in its description. When zoomed out, a hex shows its highest-ranked resource; zoom in to see more."))}
      ${th(t("Press {key} to show or hide them."), { key: "<b>R</b>" })}</p>
      ${cats.map((c) => `<h4>${esc(CATEGORY[c] || c)}</h4><table class="res-table">
        <tr><th></th><th>${esc(t("Type"))}</th><th>${esc(t("What counts"))}</th><th>${esc(t("Sites"))}</th></tr>
        ${r.types.filter((x) => (x.category || "other") === c).map((x) => `<tr>
          <td class="ic"><span class="res-ic" style="background:${esc(x.color || "#24384f")};color:${inkOn(x.color)}">${glyph(x, 20)}</span></td>
          <td class="nm"><b>${esc(t(x.name))}</b>${x.unit ? `<br><span class="muted">${esc(t("value in {unit}", { unit: t(x.unit) }))}</span>` : ""}</td>
          <td>${esc(x.description ? t(x.description) : "")}<br><span class="muted">${esc(t("Source: {source}", { source: srcName(x.source) }))}</span></td>
          <td class="num">${esc(int(count.get(x.id) || 0))}</td></tr>`).join("")}</table>`).join("")}`;
    },
    // Every registered motion layer (app.motion), with the rules, sources and attribution of its data file.
    "Moving layers": () => {
      const app = data.app;
      const list = app?.motion?.layers?.() || [];
      if (!list.length) return `${h2("layers", "▤", t("Moving layers"))}<p class="muted">${esc(t("This data build has no moving layers."))}</p>`;
      const stamp = (iso) => (iso ? `${date(String(iso).slice(0, 10))} ${String(iso).slice(11, 16)} UTC` : "");
      const waiting = [];
      const entries = list.map((l) => {
        const d = l.data ? app.data?.[l.data] : null;
        if (l.data && d === undefined) waiting.push(l.data);
        const rules = Array.isArray(d?.rules) ? d.rules : d?.rules && typeof d.rules === "object" ? Object.values(d.rules) : d?.rule ? [d.rule] : [];
        const srcs = (d?.sources || []).map(srcName).filter(Boolean);
        const vintage = typeof d?.vintage === "string" ? t(d.vintage) : "";
        const a = d?.attribution && !Array.isArray(d.attribution) ? d.attribution : null;
        return `<h4>${esc(l.name || l.id)}</h4>
          ${rules.length ? `<ul>${rules.map((r) => `<li>${esc(t(r))}</li>`).join("")}</ul>` : d === undefined ? `<p class="muted">${esc(t("Loading..."))}</p>` : ""}
          ${a ? `<p>${a.created
            ? `${esc(t("Source: {source}", { source: (a.credit || []).join("; ") }))}<br>
            ${esc(t("Data created {created}; retrieved {retrieved}.", { created: stamp(a.created), retrieved: stamp(a.retrieved) }))}`
            : esc(a.retrieved ? t("Source: {source}, retrieved {retrieved}", { source: (a.credit || []).join("; "), retrieved: date(String(a.retrieved).slice(0, 10)) })
              : t("Source: {source}", { source: (a.credit || []).join("; ") }))}
            ${a.processed ? `<br>${esc(t(a.processed))}` : ""}${a.disclaimer ? `<br>${esc(t(a.disclaimer))}` : ""}
            ${a.original?.url ? `<br>${t("Original data: {link} ({size}, SHA-256 {hash})", { link: `<a href="${esc(safeUrl(a.original.url))}" rel="noopener">${esc(a.original.url.replace(/^https?:\/\//, ""))}</a>`, size: `${num((a.original.bytes || 0) / 1e6, 1)} MB`, hash: `<code style="word-break:break-all">${esc(String(a.original.sha256 || ""))}</code>` })}` : ""}</p>` : ""}
          ${srcs.length || vintage ? `<p class="muted">${esc([srcs.join(", "), vintage].filter(Boolean).join(" · "))}</p>` : ""}`;
      });
      // Data files not loaded yet: load them, then redraw this page if it is still open.
      if (waiting.length) {
        Promise.all(waiting.map((n) => app.loadData(n))).then(() => {
          if (!modal.hidden && current === "Moving layers") show("Moving layers");
        });
      }
      return `${h2("layers", "▤", t("Moving layers"))}
      <p>${esc(t("These layers play on one clock. Press play under the map, drag the slider or change the speed."))}</p>
      ${entries.join("")}`;
    },
    Sources: () => `
      ${h2("pedia", "📖", t("Sources"))}
      ${data.sources == null ? `<p class="muted">${esc(t("Loading..."))}</p>` : ""}${(data.sources || []).map((s) => `
        <h4>${esc(t(s.title))}</h4>
        <p>${esc(t(s.description))}<br>
        <span class="muted">${esc(t(s.publisher))} · ${esc(t(s.license))}${s.vintage ? " · " + esc(t(s.vintage)) : ""} ·
        <a href="${esc(safeUrl(s.homepage))}" target="_blank" rel="noopener">${esc(t("homepage"))}</a></span></p>
        <table>${(s.files || []).map((f) => `<tr><td><code>${esc(f.url)}</code></td><td class="muted" style="white-space:nowrap">${esc(date((f.retrieved || "").slice(0, 10)))}<br>${esc(num((f.bytes || 0) / 1e6, 1))} MB</td></tr>`).join("")}</table>`).join("")}`,
  };
  // Page ids stay English (other modules open pages by id); the nav shows the translated title.
  const TITLE = {
    "About this map": t("About this map"), Yields: t("Yields"), Voivodeships: t("Voivodeships"), Terrain: t("Terrain"),
    Lenses: t("Lenses"), Resources: t("Resources"), "Moving layers": t("Moving layers"), Sources: t("Sources"),
  };

  let current = null;
  const show = (name) => {
    if (!pages[name]) name = "About this map";
    current = name;
    body.innerHTML = pages[name]();
    body.scrollTop = 0;
    nav.querySelectorAll("button").forEach((b) => {
      const on = b.dataset.page === name;
      b.classList.toggle("active", on);
      b.setAttribute("aria-current", on ? "page" : "false");
    });
  };
  nav.innerHTML = `<div class="hd">${esc(t("Almanac"))}</div>` + Object.keys(pages).map((p) => `<button data-page="${esc(p)}">${esc(TITLE[p] || p)}</button>`).join("");
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
      // The source list loads with the Almanac, not with the map.
      if (data.sources == null && data.app?.loadData) {
        data.app.loadData("sources").then((d) => {
          data.sources = Array.isArray(d) ? d : [];
          if (!modal.hidden && current) show(current);
        }, () => {
          data.sources = [];
          if (!modal.hidden && current) show(current);
        });
      }
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

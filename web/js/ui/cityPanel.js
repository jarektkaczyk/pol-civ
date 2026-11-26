import { css } from "../color.js";
import { esc } from "../format.js";
import { t } from "../i18n.js";
import { isCapital } from "../world.js";
import { yieldGrid, amenities, industries, gdpRow, popLine, growthSpan, showPanel, hidePanel } from "./infoPanel.js";

/**
 * ctx: {w, nation, onClose, onPedia, onState(stateIndex)}
 */
export function openCityPanel(city, ctx) {
  const { w, nation } = ctx;
  const n = nation.nation;
  const owner = city.cell != null ? w.raw.owner[city.cell] : -1;
  const col = css(w.stateColor[owner] || [190, 190, 190]);

  // The city's states as links to their state panels.
  const states = (city.states || [])
    .map((abbr) => ({ abbr, i: w.raw.states.findIndex((s) => s.abbr === abbr) }))
    .map(({ abbr, i }) => (i >= 0 && ctx.onState
      ? `<button class="chip" data-state="${i}" title="${esc(t("Open {name}", { name: w.raw.states[i].name }))}">${esc(abbr)}</button>`
      : `<span class="chip">${esc(abbr)}</span>`))
    .join("");

  const growth = growthSpan(city, n);

  showPanel({
    kind: "city",
    stripe: col,
    title: city.name,
    kindLabel: city.kind === "city" ? t("City with powiat rights") : t("Town"),
    titleHtml: `${isCapital(city) ? `<span class="cap" title="${esc(t("Capital of Poland"))}">★</span> ` : ""}${esc(city.name)}`,
    sub: `${esc(city.full || "")}${states ? `<div class="chips">${states}</div>` : ""}`,
    headExtra: popLine(city, growth),
    sections: [
      { title: t("Yields"), html: `<div class="yield-grid">${yieldGrid(nation, city.yields)}</div>` },
      { title: city.scope === "urban-rural gmina" ? t("Prosperity · whole gmina") : t("Prosperity"), html: amenities(city, n) + gdpRow(city) },
      Object.keys(city.jobs || {}).length && { title: t("Workers by sector"), html: industries(city, nation) },
    ],
    foot: "",
    onClose: ctx.onClose,
    onPedia: ctx.onPedia,
    wire(panel) {
      panel.querySelectorAll("[data-state]").forEach((b) => (b.onclick = () => ctx.onState(+b.dataset.state)));
    },
  });
}

export const closeCityPanel = hidePanel;

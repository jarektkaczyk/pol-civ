import { css } from "../color.js";
import { esc, popShort } from "../format.js";
import { isCapital } from "../world.js";
import { t } from "../i18n.js";
import { yieldGrid, amenities, industries, gdpRow, popLine, growthSpan, showPanel } from "./infoPanel.js";

// "Bydgoszcz and Toruń": the seats of a voivodeship (one or two).
function capitalsText(capitals) {
  const names = (capitals || []).map((c) => c.name).filter(Boolean);
  if (names.length === 2) return t("{a} and {b}", { a: names[0], b: names[1] });
  return names.join(", ");
}

/**
 * Opens the panel for state `idx` (index into world.json states / states.json).
 * ctx: {w, nation, states (states.json or null), cities, onClose, onPedia, onCity(city)}
 */
export function openStatePanel(idx, ctx) {
  const { w, nation } = ctx;
  const n = nation.nation;
  const geo = w.raw.states[idx] || {};
  // states.json is in the same order as world.json states; fall back to matching by fips.
  let st = ctx.states?.[idx];
  if (st && geo.fips && st.fips && st.fips !== geo.fips) st = ctx.states.find((s) => s.fips === geo.fips);
  st = st || { ...geo };
  const name = st.name || geo.name || t("Voivodeship");
  const abbr = st.abbr || geo.abbr || "";
  const count = ctx.states?.length || w.raw.states.length;

  const cities = (ctx.cities || []).filter((c) => (c.states || []).includes(abbr)).slice(0, 8);
  const cityRows = cities.length
    ? `<div class="city-list">${cities
        .map((c) => {
          const multi = (c.states || []).length > 1 ? `<span class="muted"> · ${esc(c.states.join("–"))}</span>` : "";
          return `<button class="city-row" data-city="${esc(c.id)}" title="${esc(c.full || c.name)}">
            <span class="cr-name">${isCapital(c) ? "★ " : ""}${esc(c.name)}${multi}</span>
            <span class="cr-pop">${popShort(c.population)}</span><span class="cr-go" aria-hidden="true">›</span></button>`;
        })
        .join("")}</div>`
    : `<p class="muted">${esc(t("No towns in this voivodeship's data."))}</p>`;

  const hasEcon = st.population != null || st.yields;
  showPanel({
    kind: "state",
    stripe: css(w.stateColor[idx] || [190, 190, 190]),
    title: name,
    sub: `${esc(capitalsText(st.capitals) || abbr)}${geo.fips ? ` · TERYT ${esc(geo.fips)}` : ""}`,
    headExtra: hasEcon ? popLine(st, growthSpan(st, n)) : "",
    sections: [
      st.yields && { title: t("Yields · rank among voivodeships"), html: `<div class="yield-grid">${yieldGrid(nation, st.yields, st.ranks, count)}</div>` },
      hasEcon && { title: t("Prosperity"), html: amenities(st, n) + gdpRow(st) },
      st.jobs && Object.keys(st.jobs).length && { title: t("Top industries · workers by sector"), html: industries(st, nation, 8) },
      { title: t("Biggest towns"), html: cityRows },
    ],
    foot: "",
    onClose: ctx.onClose,
    onPedia: ctx.onPedia,
    wire(panel) {
      panel.querySelectorAll("[data-city]").forEach((b) => {
        b.onclick = () => {
          const c = ctx.cities.find((x) => x.id === b.dataset.city);
          if (c) ctx.onCity(c);
        };
      });
    },
  });
}

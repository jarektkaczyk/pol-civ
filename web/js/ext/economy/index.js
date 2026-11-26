// "Made in Poland" and "Tech and games": two Map-menu switches (off by default, kept in the URL like the other
// switches) that put product and tech sites on the map. Hover a marker (or tap it on a phone) for its card: name,
// place, one fact and its year. The game studios of one town share one marker with a count; their card lists each
// studio with its best-known game. economy.json loads the first time a switch is turned on.
//
// Static layers: markers at z 66.5 (with the forts and wonders, above city tiles) and name plates at z 68.5 (close in
// only, clear of city banners). The City View's "Made here" block is madeHereHtml() in cards.js.
import { t } from "../../i18n.js";
import { drawEconSite, drawCountBadge } from "../../render/art/economy.js";
import { drawPlaque } from "../../render/art/sites.js";
import { showHtmlTooltip } from "../../ui/tooltip.js";
import { buildMarkers, visibleMarkers, markerSize, hitMarker, MIN_RPX } from "./model.js";
import { markerCard, plateText } from "./cards.js";

const TOGGLES = [
  { id: "made", label: t("Made in Poland"), icon: "\u{1F3ED}", title: t("Places behind products Poland is known for") },
  { id: "tech", label: t("Tech and games"), icon: "\u{1F3AE}", title: t("Game studios, tech companies, supercomputers and space") },
];
const PLATE_RPX = 27;

const CSS = `
#tooltip .econ-card { max-width: 300px; line-height: 1.4; }
.econ-made { list-style: none; margin: 4px 0 10px; padding: 0; }
.econ-made li { margin: 0 0 8px; font-size: 13px; line-height: 1.4; }
`;

function injectCss() {
  if (document.getElementById("economy-css")) return;
  const s = document.createElement("style");
  s.id = "economy-css";
  s.textContent = CSS;
  document.head.appendChild(s);
}

// Hexes where the map-art layers (forts, wonders, ports, airports) already stand.
function takenCells(app) {
  const mm = app.mapArt?.model;
  const out = new Map();
  for (const it of [...(mm?.wonders || []), ...(mm?.installations || []), ...(mm?.ports || []), ...(mm?.airports || [])]) {
    const c = it.drawCell ?? it.cell;
    if (Number.isInteger(c)) out.set(c, (out.get(c) || 0) + 1);
  }
  return out;
}

export function install(app) {
  injectCss();
  const on = { made: false, tech: false };
  let doc = null, tiers = { overview: [], detail: [] }, version = 0, loading = null;
  const cache = new Map();
  const R = () => app.w.grid.R;

  const ensure = () => {
    if (doc || loading) return;
    loading = app.loadData("economy").then((d) => {
      doc = d;
      tiers = d ? buildMarkers(app.w, d, takenCells(app)) : { overview: [], detail: [] };
      cache.clear();
      version++;
      app.requestDraw();
    }, (err) => console.warn("economy: economy.json failed to load", err));
  };
  const list = (Rpx) => visibleMarkers(tiers, on, Rpx, cache, app.w);
  const anyOn = () => (on.made || on.tech) && tiers.overview.length > 0;

  const sites = {
    id: "economy-sites", z: 66.5, minRpx: MIN_RPX,
    visible: anyOn,
    sig: () => `v${version}|${on.made ? 1 : 0}${on.tech ? 1 : 0}`,
    draw(ctx, vp, w, o) {
      const s = vp.s;
      const pad = 90 / s;
      const size = markerSize(o.Rpx) / s;
      for (const m of list(o.Rpx)) {
        if (m.x < vp.x0 - pad || m.x > vp.x1 + pad || m.y < vp.y0 - pad || m.y > vp.y1 + pad) continue;
        drawEconSite(ctx, m.kind, m.x, m.y, size);
        if (m.count > 1) drawCountBadge(ctx, m.count, m.x, m.y, size);
      }
    },
    warm(ctx, vp, w, o) { sites.draw(ctx, vp, w, o); },
    hit: (x, y, Rpx) => hitMarker(list(Rpx), x, y, Rpx, app.w.grid),
    tooltip: (m) => markerCard(m),
    click(m, ev) {
      // On a phone there is no hover: a tap opens the card where the finger was.
      if (ev.pointerType === "mouse") return false;
      showHtmlTooltip(ev.x, ev.y, markerCard(m));
      return true;
    },
  };

  // Screen rects (css px) above sizeable city tiles, where banners stand (as ext/layers does for its plates).
  function bannerRects(o, vp) {
    const out = [];
    const floor = o.Rpx < 40 ? 2e4 : 0;
    const g = app.w.grid;
    const pad = 2 * g.R;
    for (const [cell, city] of app.w.cityByCell) {
      if (!(city.population >= floor)) continue;
      const x = g.cx(cell), y = g.cy(cell);
      if (x < vp.x0 - pad || x > vp.x1 + pad || y < vp.y0 - pad || y > vp.y1 + pad) continue;
      const [sx, sy] = o.toScreen(x, y);
      const half = Math.min(110, 40 + String(city.name || "").length * 4);
      out.push([sx - half - 6, sy - o.Rpx * 0.75 - (o.Rpx > 24 ? 56 : 32), sx + half + 6, sy - o.Rpx * 0.1]);
    }
    return out;
  }

  const plates = {
    id: "economy-plates", z: 68.5, minRpx: PLATE_RPX,
    visible: () => anyOn() && !app.cityView?.city,
    sig: () => `v${version}|${on.made ? 1 : 0}${on.tech ? 1 : 0}`,
    draw(ctx, vp, w, o) {
      o.screen();
      const placed = bannerRects(o, vp);
      const scale = Math.min(1.2, 0.85 + o.Rpx / 200);
      for (const m of list(o.Rpx)) {
        if (m.x < vp.x0 || m.x > vp.x1 || m.y < vp.y0 || m.y > vp.y1) continue;
        const [sx, sy] = o.toScreen(m.x, m.y);
        const text = plateText(m);
        if (!text) continue;
        const y = sy + markerSize(o.Rpx) * 0.42;
        const box = drawPlaque(ctx, text, sx, y, { kind: "econ", scale, measureOnly: true });
        if (placed.some((p) => box[0] < p[2] && p[0] < box[2] && box[1] < p[3] && p[1] < box[3])) continue;
        placed.push(box);
        drawPlaque(ctx, text, sx, y, { kind: "econ", scale });
      }
      o.world();
    },
  };

  app.registerStaticLayer(sites);
  app.registerStaticLayer(plates);
  for (const tg of TOGGLES) {
    app.ui.addMapToggle({
      id: tg.id, label: tg.label, icon: tg.icon, title: tg.title, default: false,
      get: () => on[tg.id],
      set: (v) => {
        on[tg.id] = !!v;
        if (v) ensure();
        app.requestDraw();
      },
    });
  }
  // For debugging and screenshots: the data, both tiers, the switches and the markers drawn at a zoom.
  app.economy = { get doc() { return doc; }, get tiers() { return tiers; }, on, visible: list };
}

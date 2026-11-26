// Historic borders: the borders of the partitions on 1 July 1914 (German Empire, Russian Empire, Austria-Hungary)
// and the border of interwar Poland (1921-1939), as quiet dashed lines over the map with the 1914 state names in
// their zones. Two switches in the Map menu, both off by default; history.json loads on first use.
// Data: history.json (pipeline/build/history.py, from CShapes 2.0). Nothing animates.
import { esc } from "../../format.js";
import { LABEL_FONT } from "../../world.js";
import { t } from "../../i18n.js";

const TOGGLES = [
  { id: "borders1914", layer: "borders_1914", label: t("Borders of 1914"), icon: "🕰️",
    title: t("The borders of the German Empire, the Russian Empire and Austria-Hungary on 1 July 1914") },
  { id: "interwar", layer: "borders_1930", label: t("Interwar border"), icon: "📜",
    title: t("The border of Poland from 1921 to 1939") },
];
const STYLE = {
  borders_1914: { color: "rgba(250,236,200,.92)", halo: "rgba(24,14,6,.55)", dash: [7, 5], width: 1.9 },
  borders_1930: { color: "rgba(232,196,120,.92)", halo: "rgba(24,14,6,.5)", dash: [2, 4], width: 1.9 },
};

function prepare(doc) {
  const byId = new Map();
  for (const layer of doc?.layers || []) {
    const lines = (layer.lines || []).map((ln) => {
      const p = ln.pts;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      const path = new Path2D();
      for (let k = 0; k < p.length; k += 2) {
        if (k === 0) path.moveTo(p[0], p[1]); else path.lineTo(p[k], p[k + 1]);
        x0 = Math.min(x0, p[k]); y0 = Math.min(y0, p[k + 1]);
        x1 = Math.max(x1, p[k]); y1 = Math.max(y1, p[k + 1]);
      }
      return { ...ln, path, bbox: [x0, y0, x1, y1] };
    });
    byId.set(layer.id, { ...layer, lines });
  }
  return byId;
}

function segDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const l2 = dx * dx + dy * dy;
  const u = l2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0;
  return Math.hypot(px - ax - u * dx, py - ay - u * dy);
}

export function install(app) {
  const on = Object.fromEntries(TOGGLES.map((tg) => [tg.id, false]));
  let model = null;
  let version = 0;
  let loading = null;
  const ensure = () => {
    if (model || loading) return;
    loading = app.loadData("history").then((d) => {
      model = prepare(d);
      version++;
      app.requestDraw();
    }, (err) => console.warn("history: history.json failed to load", err));
  };

  const lineLayer = (tg) => ({
    id: `history-${tg.id}`, z: 52,
    visible: () => on[tg.id] && !!model?.get(tg.layer),
    sig: () => `v${version}`,
    draw(ctx, vp) {
      const layer = model.get(tg.layer);
      const st = STYLE[tg.layer];
      const s = vp.s;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      for (const ln of layer.lines) {
        const [x0, y0, x1, y1] = ln.bbox;
        if (x1 < vp.x0 || x0 > vp.x1 || y1 < vp.y0 || y0 > vp.y1) continue;
        ctx.setLineDash([]);
        ctx.strokeStyle = st.halo;
        ctx.lineWidth = (st.width + 2.6) / s;
        ctx.stroke(ln.path);
        ctx.strokeStyle = st.color;
        ctx.lineWidth = st.width / s;
        ctx.setLineDash(st.dash.map((d) => d / s));
        ctx.stroke(ln.path);
      }
      ctx.setLineDash([]);
    },
    hit(x, y, Rpx) {
      const layer = model?.get(tg.layer);
      if (!layer) return null;
      const s = Rpx / app.w.grid.R;
      const tol = 6 / s;
      for (const ln of layer.lines) {
        const [x0, y0, x1, y1] = ln.bbox;
        if (x < x0 - tol || x > x1 + tol || y < y0 - tol || y > y1 + tol) continue;
        const p = ln.pts;
        for (let k = 2; k < p.length; k += 2) {
          if (segDist(x, y, p[k - 2], p[k - 1], p[k], p[k + 1]) < tol) return { kind: "border", data: ln };
        }
      }
      return null;
    },
    tooltip: (it) => `<b>${esc(t(it.data.tip))}</b>`,
  });

  // State names of 1914, in their zones: italic serif, quiet, above the lens colours and under voivodeship names.
  const labels = {
    id: "history-labels", z: 88,
    visible: () => on.borders1914 && !!model?.get("borders_1914"),
    sig: () => `v${version}`,
    draw(ctx, vp, w, o) {
      const layer = model.get("borders_1914");
      const px = Math.max(15, Math.min(26, 13 + o.Rpx * 0.7));
      o.screen();
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = `italic 600 ${px.toFixed(1)}px ${LABEL_FONT}`;
      ctx.lineJoin = "round";
      for (const lb of layer.labels || []) {
        const [sx, sy] = o.toScreen(lb.x, lb.y);
        ctx.lineWidth = 3.5;
        ctx.strokeStyle = "rgba(20,12,4,.62)";
        const name = t(lb.name);
        ctx.strokeText(name, sx, sy);
        ctx.fillStyle = "rgba(250,238,206,.95)";
        ctx.fillText(name, sx, sy);
      }
      o.world();
    },
  };

  for (const tg of TOGGLES) app.registerStaticLayer(lineLayer(tg));
  app.registerStaticLayer(labels);
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
  app.historyBorders = { get model() { return model; }, on };
}

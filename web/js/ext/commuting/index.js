// Commuters: the largest flows of commuters into the 12 largest cities as soft arcs, thicker for more people, with
// a switch "Commuters" in the Map menu (off by default; commuting.json loads on first use). The selection rule is
// in commuting.json (`rule`); the Almanac quotes it. The arcs are part of the cached map; the moving commuters on
// them are a motion layer (motion.js, on the shared clock). Selecting one of the 12 cities shows only its flows.
import { esc, int } from "../../format.js";
import { t } from "../../i18n.js";
import { registerCommuterMotion } from "./motion.js";

const STEPS = 14; // points per arc for hit testing
const BEND = 0.18; // sideways bow of an arc, as a share of its length

function prepare(doc) {
  const arcs = [];
  for (const c of doc?.cities || []) {
    const max = Math.max(1, ...(c.arcs || []).map((a) => a.value));
    for (const a of c.arcs || []) {
      const dx = c.x - a.x, dy = c.y - a.y;
      const len = Math.hypot(dx, dy) || 1;
      // Control point: the midpoint pushed sideways (always to the same side of the travel direction).
      const qx = (a.x + c.x) / 2 - (dy / len) * len * BEND;
      const qy = (a.y + c.y) / 2 + (dx / len) * len * BEND;
      const pts = [];
      for (let k = 0; k <= STEPS; k++) {
        const f = k / STEPS, u = 1 - f;
        pts.push(u * u * a.x + 2 * u * f * qx + f * f * c.x, u * u * a.y + 2 * u * f * qy + f * f * c.y);
      }
      const xs = pts.filter((_, i) => i % 2 === 0), ys = pts.filter((_, i) => i % 2 === 1);
      arcs.push({ ...a, city: c, q: [qx, qy], pts, share: a.value / max,
        bbox: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] });
    }
  }
  arcs.sort((p, q) => p.value - q.value); // big arcs drawn last, on top
  return { arcs, cities: doc?.cities || [], rule: doc?.rule || "" };
}

const widthPx = (a, Rpx) => (1.1 + Math.sqrt(a.value) * 0.042) * Math.max(0.85, Math.min(1.5, Rpx / 12));

function segDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const l2 = dx * dx + dy * dy;
  const u = l2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0;
  return Math.hypot(px - ax - u * dx, py - ay - u * dy);
}

export function install(app) {
  let on = false;
  let model = null;
  let version = 0;
  let loading = null;
  let focus = null; // the selected city's id when it is one of the 12, else null (all flows)
  const shown = (a) => !focus || a.city.id === focus;
  const ensure = () => {
    if (model || loading) return;
    loading = app.loadData("commuting").then((d) => {
      model = prepare(d);
      version++;
      app.requestDraw();
    }, (err) => console.warn("commuting: commuting.json failed to load", err));
  };

  const layer = {
    id: "commuters", z: 84,
    visible: () => on && !!model,
    sig: () => `v${version}|${focus || ""}`,
    draw(ctx, vp, w, o) {
      const s = vp.s;
      ctx.lineCap = "round";
      for (const a of model.arcs) {
        if (!shown(a)) continue;
        const [x0, y0, x1, y1] = a.bbox;
        if (x1 < vp.x0 || x0 > vp.x1 || y1 < vp.y0 || y0 > vp.y1) continue;
        const wpx = widthPx(a, o.Rpx);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.quadraticCurveTo(a.q[0], a.q[1], a.city.x, a.city.y);
        // Moving commuters (motion.js) travel on these arcs, so the arcs stay a quiet guide under them.
        ctx.strokeStyle = "rgba(20,12,4,.22)";
        ctx.lineWidth = (wpx * 0.8 + 1.8) / s;
        ctx.stroke();
        ctx.strokeStyle = `rgba(255,${Math.round(226 - 70 * a.share)},${Math.round(150 - 90 * a.share)},${(0.52 + 0.3 * a.share).toFixed(2)})`;
        ctx.lineWidth = (wpx * 0.8) / s;
        ctx.stroke();
      }
      // Home ends: small parchment studs.
      ctx.fillStyle = "rgba(255,240,205,.9)";
      for (const a of model.arcs) {
        if (!shown(a)) continue;
        if (a.x < vp.x0 || a.x > vp.x1 || a.y < vp.y0 || a.y > vp.y1) continue;
        ctx.beginPath();
        ctx.arc(a.x, a.y, (1.2 + a.share * 1.6) / s, 0, Math.PI * 2);
        ctx.fill();
      }
    },
    hit(x, y, Rpx) {
      if (!model) return null;
      const s = Rpx / app.w.grid.R;
      let best = null, bestD = Infinity;
      for (const a of model.arcs) {
        if (!shown(a)) continue;
        const tol = (widthPx(a, Rpx) / 2 + 4) / s;
        const [x0, y0, x1, y1] = a.bbox;
        if (x < x0 - tol || x > x1 + tol || y < y0 - tol || y > y1 + tol) continue;
        const p = a.pts;
        for (let k = 2; k < p.length; k += 2) {
          const d = segDist(x, y, p[k - 2], p[k - 1], p[k], p[k + 1]);
          if (d < tol && d < bestD) { bestD = d; best = a; }
        }
      }
      return best ? { kind: "commute", data: best } : null;
    },
    tooltip: (it) => {
      const a = it.data;
      // The templates hold no HTML (pipeline check); the names go in escaped and bold.
      return `${t("{from} to {to}", { from: `<b>${esc(a.name)}</b>`, to: `<b>${esc(a.city.name)}</b>` })}<br>${
        t.plural(a.value, { one: "{n} commuter", other: "{n} commuters" }, { n: `<b>${int(a.value)}</b>` })}`;
    },
  };
  app.registerStaticLayer(layer);
  app.ui.addMapToggle({
    id: "commuters", label: t("Commuters"), icon: "l-commute", default: false, menu: false,
    title: t("The largest flows of commuters into the 12 largest cities"),
    get: () => on,
    set: (v) => {
      on = !!v;
      if (on) ensure();
      app.requestDraw();
    },
  });
  app.commuting = { get model() { return model; }, get focus() { return focus; } };
  registerCommuterMotion(app, {
    active: () => on,
    model: () => model,
    load: () => { ensure(); return loading; },
    filter(sel) {
      const id = sel?.kind === "city" ? sel.city?.id : null;
      const next = id && model?.cities.some((c) => c.id === id) ? id : null;
      if (next !== focus) {
        focus = next;
        app.requestDraw();
      }
      return focus;
    },
    focus: () => focus,
  });
}

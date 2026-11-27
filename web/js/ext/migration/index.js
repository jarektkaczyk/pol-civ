// Migration: moves of permanent residence between the 16 voivodeships, year by year from 1995 (migration.json, GUS
// BDL). Dots run along an arc between the two capitals for every origin and destination, as many as that year's
// movers; a voivodeship that gained people glows at its capital, one that lost people shows a red ring. Hover a
// capital for its arrivals, departures and top partners; select a voivodeship (or a town in it) to see only its
// flows: arrivals green, departures orange.
import { esc } from "../../format.js";
import { t, int, num } from "../../i18n.js";

const DOTS = 1500; // slots over all pairs in the busiest year
const SPEED = 0.5; // years per second at 1x (1995 to 2025 in about a minute)
const KM_PER_YEAR = 300; // dot speed in map km per clock unit (one year)
const ALL = "#fff8e6";
const IN = "#7ee08f";
const OUT = "#ff9a6b";
const TOP = 3;

export function prepare(doc, particles) {
  const years = doc.years || [];
  const y0 = years[0];
  const regions = doc.regions || [];
  const idx = Object.fromEntries(regions.map((r, i) => [r.code, i]));
  const peak = new Float64Array(years.length);
  for (const f of doc.flows || []) (f.values || []).forEach((v, k) => { peak[k] += v || 0; });
  const per = Math.max(1, Math.max(...peak) / DOTS); // persons per dot
  const flows = (doc.flows || []).filter((f) => idx[f.from] != null && idx[f.to] != null).map((f, k) => {
    const values = (f.values || []).map((v) => (v == null ? 0 : v));
    const slots = Math.max(1, Math.ceil(Math.max(...values) / per));
    return { from: f.from, to: f.to, values, slots, path: f.path, flow: particles(f.path, { slots, speed: KM_PER_YEAR, seed: 17 + k }) };
  });
  return { years, y0, n: years.length, regions, idx, flows, per };
}

const sprites = new Map();
function halo(color, r, dpr) {
  const rr = Math.max(3, Math.round(r));
  const key = `${color}|${rr}|${dpr}`;
  let c = sprites.get(key);
  if (c) return c;
  c = document.createElement("canvas");
  c.width = c.height = Math.ceil(2 * rr * dpr);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  const grad = g.createRadialGradient(rr, rr, 0, rr, rr, rr);
  grad.addColorStop(0, "rgba(255,248,220,.95)");
  grad.addColorStop(0.3, color);
  grad.addColorStop(1, "rgba(255,210,122,0)");
  g.fillStyle = grad;
  g.beginPath();
  g.arc(rr, rr, rr, 0, Math.PI * 2);
  g.fill();
  c.css = 2 * rr;
  if (sprites.size > 200) sprites.clear();
  sprites.set(key, c);
  return c;
}

export function install(app) {
  const motion = app.motion;
  if (!motion) return;
  let on = false;
  let model = null;
  let loading = null;
  let focus = null; // voivodeship code, or null (all)

  const ensure = () => {
    if (model) return Promise.resolve(model);
    loading ??= app.loadData("migration").then((d) => {
      if (!d || !Array.isArray(d.flows) || !Array.isArray(d.years) || !d.years.length) return null;
      model = prepare(d, motion.particles);
      app.requestDraw();
      return model;
    });
    return loading;
  };

  // The year index of clock value ty.
  const yearAt = (ty) => Math.max(0, Math.min(model.n - 1, Math.floor(ty) - model.y0));
  const flowOn = (f) => !focus || f.from === focus || f.to === focus;
  const yearTotal = (k) => model.flows.reduce((s, f) => s + (flowOn(f) ? f.values[k] : 0), 0);

  function draw(ctx, vp, ty, o) {
    const k = yearAt(ty);
    const { cam, dpr } = vp;
    const s = cam.scale, cx = cam.w / 2 - cam.x * s, cy = cam.h / 2 - cam.y * s;
    const zoom = Math.max(0.8, Math.min(1.6, o.Rpx / 10));
    let dots = 0;
    // The focused voivodeship's arcs, faint.
    if (focus) {
      ctx.save();
      ctx.lineCap = "round";
      for (const f of model.flows) {
        if (!flowOn(f) || !f.values[k]) continue;
        const p = f.path;
        ctx.beginPath();
        ctx.moveTo(p[0], p[1]);
        for (let j = 2; j < p.length; j += 2) ctx.lineTo(p[j], p[j + 1]);
        ctx.lineWidth = Math.min(4, 0.6 + Math.sqrt(f.values[k]) / 40) / s;
        ctx.strokeStyle = f.to === focus ? "rgba(126,224,143,.28)" : "rgba(255,154,107,.28)";
        ctx.stroke();
      }
      ctx.restore();
    }
    // Net gain glows, net loss rings, at the capitals.
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    for (const r of model.regions) {
      const net = r.net[k];
      if (net == null) continue;
      const sx = r.x * s + cx, sy = r.y * s + cy;
      const rad = Math.max(4, Math.min(30, 3 + Math.sqrt(Math.abs(net)) * 0.28)) * zoom;
      ctx.globalAlpha = focus && focus !== r.code ? 0.45 : 1;
      if (net > 0) {
        const img = halo("rgba(255,205,100,.85)", rad * 2.2, dpr);
        ctx.drawImage(img, sx - img.css / 2, sy - img.css / 2, img.css, img.css);
      }
      ctx.beginPath();
      ctx.arc(sx, sy, rad, 0, Math.PI * 2);
      ctx.lineWidth = 4;
      ctx.strokeStyle = "rgba(20,8,4,.7)";
      ctx.stroke();
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = net > 0 ? "#ffd27a" : "#e0584f";
      ctx.stroke();
    }
    ctx.restore();
    // Movers.
    const size = Math.max(3.6, Math.min(6.5, 3 + o.Rpx * 0.12));
    for (const f of model.flows) {
      if (!flowOn(f)) continue;
      const color = !focus ? ALL : f.to === focus ? IN : OUT;
      const per = model.per;
      dots += f.flow.draw(ctx, vp, ty, {
        density: (tDepart) => f.values[yearAt(tDepart)] / (f.slots * per),
        size, color,
      });
    }
    return dots;
  }

  function card(code, k) {
    const r = model.regions[model.idx[code]];
    const year = model.years[k];
    const ins = model.flows.filter((f) => f.to === code && f.values[k] > 0).sort((a, b) => b.values[k] - a.values[k]).slice(0, TOP);
    const outs = model.flows.filter((f) => f.from === code && f.values[k] > 0).sort((a, b) => b.values[k] - a.values[k]).slice(0, TOP);
    const nm = (c) => model.regions[model.idx[c]]?.name || c;
    return `<b>${esc(r.name)}</b> <span class="muted">${esc(String(year))}</span><br>`
      + `${esc(t("Arrived from other voivodeships"))} <b>${esc(int(r.in[k]))}</b><br>`
      + `${esc(t("Left for other voivodeships"))} <b>${esc(int(r.out[k]))}</b><br>`
      + `${esc(t("Net"))} <b>${esc(num(r.net[k], 0, { signed: true }))}</b>`
      + `<br><span class="muted">${esc(t("Most came from"))}</span>${ins.map((f) => `<br>${esc(nm(f.from))} <b>${esc(int(f.values[k]))}</b>`).join("")}`
      + `<br><span class="muted">${esc(t("Most moved to"))}</span>${outs.map((f) => `<br>${esc(nm(f.to))} <b>${esc(int(f.values[k]))}</b>`).join("")}`;
  }

  function hit(mx, my) {
    if (!model) return null;
    const ty = motion.clock.axis === "year" && motion.clock.layer === "migration" ? motion.clock.t : model.y0 + model.n - 1;
    const k = yearAt(ty ?? 0);
    let best = null, bd = 18;
    for (const r of model.regions) {
      const [sx, sy] = app.cam.toScreen(r.x, r.y);
      const d = Math.hypot(sx - mx, sy - my);
      if (d < bd) { bd = d; best = r; }
    }
    return best ? { html: card(best.code, k) } : null;
  }

  motion.register({
    id: "migration",
    name: t("Migration"),
    data: "migration",
    axis: "year",
    get range() { return model ? [model.y0, model.y0 + model.n - 1] : [1995, 2025]; },
    step: 1,
    speed: SPEED,
    loop: false,
    z: 30,
    label: (ty) => (model ? String(model.years[yearAt(ty)]) : ""),
    status: (ty) => (model ? t("{n} moves between voivodeships", { n: int(yearTotal(yearAt(ty))) }) : ""),
    active: () => on,
    load: ensure,
    filter(sel) {
      focus = sel?.kind === "state" ? sel.state?.fips ?? null : sel?.kind === "city" ? sel.city?.voivodeship ?? null : null;
      app.requestDraw();
    },
    draw(ctx, vp, ty, o) {
      if (!model) return 0;
      return draw(ctx, vp, ty, o);
    },
    hit,
  });

  app.ui.addMapToggle({
    id: "migration", label: t("Migration"), icon: "l-commute", default: false,
    title: t("Moves between voivodeships, year by year"),
    get: () => on,
    set: (v) => {
      on = !!v;
      if (on) ensure();
      app.requestDraw();
    },
  });
  app.migration = {
    get model() { return model; },
    get focus() { return focus; },
    yearAt: (ty) => (model ? yearAt(ty) : null),
    card: (code, year) => (model ? card(code, model.years.indexOf(year)) : null),
  };
}

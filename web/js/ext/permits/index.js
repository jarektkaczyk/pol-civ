// New factories and warehouses, month by month: a time-lapse motion layer on the "month" axis. Each building permit
// for a new industrial or storage building (GUNB register, permits_monthly.json) pops up at its gmina in its month as
// a small hall that grows, then settles into the gmina's marker, which grows with the gmina's running total. The
// clock bar shows the running national count. Off by default, in the Map menu; the data loads on first use.
import { esc, int } from "../../format.js";
import { t, date } from "../../i18n.js";

const POP = 0.9; // months a new permit takes to grow and settle
const SPEED = 3; // months per second at 1x
const HALL = "#fff0b0"; // a new permit: a bright hall
const SETTLED = "#8ec3e0"; // the running total: steel-blue roofs, apart from the warm map colours

const sprites = new Map();
/** A small hall (sawtooth roof) sprite, css px wide, cached per size, colour and device scale. */
function hall(color, px, dpr) {
  const w = Math.max(2, Math.round(px * 2) / 2);
  const key = `${color}|${w}|${dpr}`;
  let c = sprites.get(key);
  if (c) return c;
  const pad = 2;
  const h = w * 0.78;
  c = document.createElement("canvas");
  c.width = Math.ceil((w + 2 * pad) * dpr);
  c.height = Math.ceil((h + 2 * pad) * dpr);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  g.translate(pad, pad);
  const body = h * 0.42; // roof height
  g.beginPath();
  g.moveTo(0, h);
  g.lineTo(0, body);
  const teeth = w >= 7 ? 3 : 2;
  const tw = w / teeth;
  for (let k = 0; k < teeth; k++) {
    g.lineTo(k * tw, 0);
    g.lineTo((k + 1) * tw, body);
  }
  g.lineTo(w, h);
  g.closePath();
  g.fillStyle = color;
  g.fill();
  g.lineWidth = Math.max(0.8, w / 10);
  g.strokeStyle = "rgba(24,14,6,.9)";
  g.stroke();
  if (w >= 6) {
    g.fillStyle = "rgba(24,14,6,.55)";
    g.fillRect(w * 0.4, h * 0.66, w * 0.2, h * 0.34);
  }
  c.cssW = w + 2 * pad;
  c.cssH = h + 2 * pad;
  if (sprites.size > 300) sprites.clear();
  sprites.set(key, c);
  return c;
}

// A stable 0..1 number for a (gmina, month) pair: where in its month a permit pops up.
function frac(g, m) {
  let h = Math.imul(g + 1, 2654435761) ^ Math.imul(m + 17, 2246822519);
  h ^= h >>> 13;
  h = Math.imul(h, 3266489917);
  h ^= h >>> 16;
  return ((h >>> 0) % 1000) / 1000;
}

const ease = (x) => {
  // ease-out with a small overshoot (grows, then settles)
  const c = 1.9;
  const u = x - 1;
  return 1 + (c + 1) * u * u * u + c * u * u;
};

export function prepare(doc, monthIndex) {
  const months = doc?.months || [];
  const gminas = doc?.gminas || [];
  const flat = doc?.counts || [];
  const m0 = monthIndex(months[0]);
  const n = months.length;
  // Per month: the [gmina, count, popAt] events (popAt = when in the month it shows, 0..0.9).
  const byMonth = Array.from({ length: n }, () => []);
  for (let k = 0; k + 2 < flat.length; k += 3) {
    const mi = flat[k], gi = flat[k + 1], c = flat[k + 2];
    if (mi >= 0 && mi < n && gi >= 0 && gi < gminas.length) byMonth[mi].push(gi, c, frac(gi, mi) * 0.9);
  }
  const national = doc?.national || [];
  const before = new Float64Array(n + 1); // decisions before month k
  for (let k = 0; k < n; k++) before[k + 1] = before[k] + (national[k] || 0);
  return { months, gminas, byMonth, before, m0, n, first: m0, last: m0 + n - 1 };
}

export function install(app) {
  const motion = app.motion;
  if (!motion) return;
  let on = false;
  let model = null;
  let loading = null;
  // Running totals per gmina through month `cumMonth` (inclusive), kept between frames.
  let cum = null, cumMonth = -1;
  let shown = []; // [{gi, x, y, r}] of the last frame, for hover

  const ensure = () => {
    if (model) return Promise.resolve(model);
    loading ??= app.loadData("permits_monthly").then((d) => {
      if (!d || !Array.isArray(d.months) || !d.months.length) return null;
      model = prepare(d, motion.month);
      cum = new Float64Array(model.gminas.length);
      cumMonth = -1;
      return model;
    });
    return loading;
  };

  function totalsThrough(mi) {
    if (mi < cumMonth) { cum.fill(0); cumMonth = -1; }
    for (let k = cumMonth + 1; k <= mi; k++) {
      const ev = model.byMonth[k];
      for (let j = 0; j < ev.length; j += 3) cum[ev[j]] += ev[j + 1];
    }
    cumMonth = Math.max(cumMonth, mi);
  }

  // Month index within the file (0 = first month) and the share of that month gone (0..1).
  const split = (tm) => {
    const rel = Math.min(model.n - 1e-6, Math.max(0, tm - model.m0));
    const mi = Math.floor(rel);
    return [mi, rel - mi];
  };
  const isLast = (tm) => tm >= model.last;

  function count(tm) {
    if (!model) return null;
    if (isLast(tm)) return model.before[model.n];
    const [mi, f] = split(tm);
    let n = model.before[mi];
    const ev = model.byMonth[mi];
    for (let j = 0; j < ev.length; j += 3) if (ev[j + 2] <= f) n += ev[j + 1];
    return n;
  }

  const zoomK = (o) => Math.max(1, Math.min(2.2, o.Rpx / 8));
  const settledPx = (n, o) => Math.min(15, 2.6 + 1.05 * Math.sqrt(n)) * zoomK(o);

  motion.register({
    id: "permits",
    name: t("New factories and warehouses"),
    data: "permits_monthly",
    axis: "month",
    get range() { return model ? [model.first, model.last] : [motion.month("2016-01"), motion.month("2016-01")]; },
    step: 1,
    speed: SPEED,
    loop: false,
    label: (tm) => (model ? date(motion.monthIso(Math.min(tm, model.last))) : ""),
    status: (tm) => {
      const n = count(tm);
      return n == null ? "" : t.plural(n, { one: "{n} permit", other: "{n} permits" }, { n: int(n) });
    },
    active: () => on,
    load: ensure,
    draw(ctx, vp, tm, o) {
      if (!model) return 0;
      const done = isLast(tm);
      const [mi, f] = done ? [model.n - 1, 1] : split(tm);
      totalsThrough(mi - 1);
      const { cam, dpr } = vp;
      const s = cam.scale, cx = cam.w / 2 - cam.x * s, cy = cam.h / 2 - cam.y * s;
      const pad = 20 / s;
      const inView = (g) => g.x > vp.x0 - pad && g.x < vp.x1 + pad && g.y > vp.y0 - pad && g.y < vp.y1 + pad;
      // This month's permits that already showed count toward the settled markers too.
      const now = new Map();
      const cur = model.byMonth[mi];
      for (let j = 0; j < cur.length; j += 3) if (cur[j + 2] <= f) now.set(cur[j], cur[j + 1]);
      ctx.save();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      let drawn = 0;
      const list = [];
      ctx.globalAlpha = 0.92;
      for (let gi = 0; gi < model.gminas.length; gi++) {
        const total = cum[gi] + (now.get(gi) || 0);
        if (!total) continue;
        const g = model.gminas[gi];
        if (!inView(g)) continue;
        const px = settledPx(total, o);
        const img = hall(SETTLED, px, dpr);
        const sx = g.x * s + cx, sy = g.y * s + cy;
        ctx.drawImage(img, sx - img.cssW / 2, sy - img.cssH / 2, img.cssW, img.cssH);
        list.push({ gi, x: sx, y: sy, r: Math.max(6, img.cssW / 2), total });
        drawn++;
      }
      // New permits: a bright hall that grows from nothing, overshoots and settles, then fades into the marker.
      if (!done) {
        for (const [k, base] of [[mi - 1, 1], [mi, 0]]) {
          if (k < 0) continue;
          const ev = model.byMonth[k];
          for (let j = 0; j < ev.length; j += 3) {
            const age = f + base - ev[j + 2];
            if (age < 0 || age >= POP) continue;
            const g = model.gminas[ev[j]];
            if (!inView(g)) continue;
            const x = age / POP;
            const grow = ease(Math.min(1, x / 0.45));
            const fade = x < 0.6 ? 1 : 1 - (x - 0.6) / 0.4;
            const px = (7 + 2.2 * Math.log2(1 + ev[j + 1])) * zoomK(o) * Math.max(0.05, grow);
            const img = hall(HALL, px, dpr);
            ctx.globalAlpha = Math.max(0, fade);
            const sx = g.x * s + cx, sy = g.y * s + cy - px * 0.25 * fade;
            ctx.drawImage(img, sx - img.cssW / 2, sy - img.cssH / 2, img.cssW, img.cssH);
            drawn++;
          }
        }
      }
      ctx.restore();
      shown = list;
      return drawn;
    },
    hit(mx, my) {
      if (!model || !shown.length) return null;
      let best = null, bd = Infinity;
      for (const it of shown) {
        const d = Math.hypot(mx - it.x, my - it.y);
        if (d <= it.r + 2 && d < bd) { bd = d; best = it; }
      }
      if (!best) return null;
      const g = model.gminas[best.gi];
      const kind = { 1: t("urban gmina"), 2: t("rural gmina"), 3: t("urban-rural gmina") }[String(g.code).slice(-1)] || "";
      return {
        html: `<b>${esc(g.name)}</b>${kind ? ` <span class="muted">${esc(kind)}</span>` : ""}<br>${
          t.plural(best.total, { one: "{n} permit for a new factory or warehouse since {year}", other: "{n} permits for new factories and warehouses since {year}" },
            { n: `<b>${int(best.total)}</b>`, year: model.months[0].slice(0, 4) })}`,
      };
    },
  });

  app.ui.addMapToggle({
    id: "permits", label: t("New factories and warehouses"), icon: "d-industrial-zone", default: false,
    title: t("Building permits for new factories and warehouses, month by month"),
    get: () => on,
    set: (v) => {
      on = !!v;
      if (on) ensure();
      app.requestDraw();
    },
  });
  app.permits = { get model() { return model; }, count };
}

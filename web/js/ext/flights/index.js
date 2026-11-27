// Flights: the air routes of the Polish airports month by month (flights.json, Eurostat avia_par_pl). Faint arcs run
// from each Polish airport to its partner airports (to the map edge, in the true direction, for airports beyond it);
// small planes fly along them, as many as the route's passengers that month, so the summer peak shows. Hover an
// airport for its top destinations that month; click it (or select its town) to see only its routes.
import { esc } from "../../format.js";
import { t, int, compact, date, LANG, LOCALE } from "../../i18n.js";
import { showHtmlTooltip } from "../../ui/tooltip.js";

const PLANES = 900; // planes over all routes in the busiest month
const SPEED = 0.4; // months per second at 1x (12 months in 30 s)
const KM_PER_MONTH = 520; // plane speed in map km per clock unit (one month)
const BEND = 0.14; // sideways bow of an arc, as a share of its length
const STEPS = 24; // points per arc
const PLANE = "#ffffff";
const PLANE_FOCUS = "#ffd27a";
const TOP = 10;

/** A stable 0..1 number for (seed, slot, trip). */
function rand(seed, i, k) {
  let h = Math.imul(seed ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(i + 1, 0xc2b2ae35) ^ Math.imul(k + 7, 0x27d4eb2f);
  h ^= h >>> 15;
  h = Math.imul(h, 0x2c1b3c6d);
  h ^= h >>> 12;
  return (h >>> 0) / 4294967296;
}

/** Quadratic arc from (ax, ay) to (bx, by), bowed to the left of travel, as a flat array with cumulative lengths. */
function arc(ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const len = Math.hypot(dx, dy) || 1;
  const qx = (ax + bx) / 2 + (dy / len) * len * BEND;
  const qy = (ay + by) / 2 - (dx / len) * len * BEND;
  const pts = new Float64Array(2 * (STEPS + 1));
  for (let k = 0; k <= STEPS; k++) {
    const f = k / STEPS, u = 1 - f;
    pts[2 * k] = u * u * ax + 2 * u * f * qx + f * f * bx;
    pts[2 * k + 1] = u * u * ay + 2 * u * f * qy + f * f * by;
  }
  const cum = new Float64Array(STEPS + 1);
  for (let k = 1; k <= STEPS; k++) cum[k] = cum[k - 1] + Math.hypot(pts[2 * k] - pts[2 * k - 2], pts[2 * k + 1] - pts[2 * k - 1]);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let k = 0; k <= STEPS; k++) {
    x0 = Math.min(x0, pts[2 * k]); x1 = Math.max(x1, pts[2 * k]);
    y0 = Math.min(y0, pts[2 * k + 1]); y1 = Math.max(y1, pts[2 * k + 1]);
  }
  return { pts, cum, len: cum[STEPS], bbox: [x0, y0, x1, y1] };
}

export function prepare(doc, monthIndex) {
  const months = doc.months || [];
  const m0 = monthIndex(months[0]);
  const airports = doc.airports || [];
  const routes = [];
  const peak = new Float64Array(months.length);
  (doc.routes || []).forEach((r, i) => {
    const a = airports[r.from], b = airports[r.to];
    if (!a || !b || a.x == null || !Array.isArray(r.end)) return;
    // A domestic route is reported from both ends: draw it once, from the airport listed first.
    const drawn = !(r.domestic && r.from > r.to);
    const value = (r.value || []).map((v) => (v == null ? 0 : v));
    const geo = arc(a.x, a.y, r.end[0], r.end[1]);
    routes.push({ i, from: r.from, to: r.to, domestic: r.domestic, value, total: r.total || 0, drawn, ...geo,
      peak: Math.max(0, ...value) });
    if (drawn) value.forEach((v, m) => { peak[m] += v; });
  });
  const per = Math.max(1, Math.max(...peak) / PLANES); // passengers per plane
  for (const r of routes) {
    r.slots = r.peak > 0 ? Math.max(1, Math.ceil(r.peak / per)) : 0;
    r.per = per;
  }
  return { doc, months, m0, n: months.length, airports, routes, per };
}

const planes = new Map();
/** A small plane sprite (nose towards +x), css px, cached per colour, size and device scale. */
function planeSprite(color, px, dpr) {
  const w = Math.max(4, Math.round(px * 2) / 2);
  const key = `${color}|${w}|${dpr}`;
  let c = planes.get(key);
  if (c) return c;
  const pad = 1.5;
  c = document.createElement("canvas");
  c.width = c.height = Math.ceil((w + 2 * pad) * dpr);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  g.translate(pad + w / 2, pad + w / 2);
  const h = w / 2;
  g.beginPath();
  g.moveTo(h, 0); // nose
  g.lineTo(h * 0.15, h * 0.12);
  g.lineTo(-h * 0.1, h * 0.95); // right wing
  g.lineTo(-h * 0.35, h * 0.95);
  g.lineTo(-h * 0.3, h * 0.14);
  g.lineTo(-h * 0.75, h * 0.12);
  g.lineTo(-h * 0.95, h * 0.45); // tail
  g.lineTo(-h, h * 0.45);
  g.lineTo(-h * 0.92, 0);
  g.lineTo(-h, -h * 0.45);
  g.lineTo(-h * 0.95, -h * 0.45);
  g.lineTo(-h * 0.75, -h * 0.12);
  g.lineTo(-h * 0.3, -h * 0.14);
  g.lineTo(-h * 0.35, -h * 0.95); // left wing
  g.lineTo(-h * 0.1, -h * 0.95);
  g.lineTo(h * 0.15, -h * 0.12);
  g.closePath();
  g.lineWidth = Math.max(1, w / 11);
  g.lineJoin = "round";
  g.strokeStyle = "rgba(20,12,4,.95)";
  g.stroke();
  g.fillStyle = color;
  g.fill();
  c.cssW = c.cssH = w + 2 * pad;
  if (planes.size > 200) planes.clear();
  planes.set(key, c);
  return c;
}

export function install(app) {
  const motion = app.motion;
  if (!motion) return;
  let on = false;
  let model = null;
  let loading = null;
  let focus = null; // Set of Polish airport indices, or null (all)
  let clicked = null; // a clicked airport index (wins over the selected town)
  let townSel = null;
  let version = 0;
  const out = new Float64Array(4);
  let regionNames = null;
  try { regionNames = new Intl.DisplayNames([LOCALE], { type: "region" }); } catch { regionNames = null; }
  const country = (code) => {
    if (!code) return "";
    try { return regionNames?.of(code) || code; } catch { return code; }
  };
  const label = (a) => (LANG === "pl" ? a.label_pl || a.label || a.name : a.label || a.name) || a.icao;

  const ensure = () => {
    if (model) return Promise.resolve(model);
    loading ??= app.loadData("flights").then((d) => {
      if (!d || !Array.isArray(d.routes) || !Array.isArray(d.months) || !d.months.length) return null;
      model = prepare(d, motion.month);
      refocus();
      app.requestDraw();
      return model;
    });
    return loading;
  };

  // The airports of a town: Polish airports within 30 km of a town of 100,000 people or more.
  function townAirports(city) {
    if (!model || !city || !(city.population >= 1e5)) return [];
    return model.airports.map((a, i) => [a, i]).filter(([a]) => a.polish && a.x != null && Math.hypot(a.x - city.x, a.y - city.y) <= 30).map(([, i]) => i);
  }
  function refocus() {
    const list = clicked != null ? [clicked] : townAirports(townSel);
    focus = list.length ? new Set(list) : null;
    version++;
  }
  const routeOn = (r) => (focus ? focus.has(r.from) : r.drawn);

  // The month (index into months) of clock value tm, wrapping over the 12 months.
  const monthOf = (tm) => {
    const k = Math.floor(tm) - model.m0;
    return ((k % model.n) + model.n) % model.n;
  };
  const monthTotal = (mi) => {
    let n = 0;
    for (const r of model.routes) if (routeOn(r)) n += r.value[mi];
    return n;
  };

  function drawPlanes(ctx, vp, tm, o) {
    const { cam, dpr } = vp;
    const s = cam.scale, cx = cam.w / 2 - cam.x * s, cy = cam.h / 2 - cam.y * s;
    const pad = 10 / s;
    const px = Math.max(8, Math.min(16, 7 + o.Rpx * 0.6));
    let drawn = 0;
    ctx.save();
    for (const r of model.routes) {
      if (!r.slots || !routeOn(r)) continue;
      const [x0, y0, x1, y1] = r.bbox;
      if (x1 < vp.x0 - pad || x0 > vp.x1 + pad || y1 < vp.y0 - pad || y0 > vp.y1 + pad) continue;
      const slots = r.slots;
      const travel = r.len / KM_PER_MONTH;
      if (!(travel > 0)) continue;
      const img = planeSprite(focus ? PLANE_FOCUS : PLANE, px, dpr);
      const half = img.cssW / 2;
      const phase = tm / travel;
      for (let i = 0; i < slots; i++) {
        const p = phase + i / slots + (rand(r.i, i, -1) * 0.6) / slots;
        const trip = Math.floor(p);
        const u = p - trip;
        const tDepart = tm - u * travel;
        const want = r.value[monthOf(tDepart)] / (slots * r.per);
        if (!(want > 0) || rand(r.i, i, trip) >= want) continue;
        const back = i % 2 === 1; // half the planes fly home
        const d = (back ? 1 - u : u) * r.len;
        // point and heading on the arc
        let lo = 0, hi = STEPS;
        while (hi - lo > 1) {
          const mid = (lo + hi) >> 1;
          if (r.cum[mid] <= d) lo = mid; else hi = mid;
        }
        const seg = r.cum[hi] - r.cum[lo] || 1;
        const f = Math.min(1, Math.max(0, (d - r.cum[lo]) / seg));
        const ax = r.pts[2 * lo], ay = r.pts[2 * lo + 1], bx = r.pts[2 * hi], by = r.pts[2 * hi + 1];
        out[0] = ax + (bx - ax) * f;
        out[1] = ay + (by - ay) * f;
        let dx = (bx - ax) / seg, dy = (by - ay) / seg;
        if (back) { dx = -dx; dy = -dy; }
        if (out[0] < vp.x0 - pad || out[0] > vp.x1 + pad || out[1] < vp.y0 - pad || out[1] > vp.y1 + pad) continue;
        const sx = out[0] * s + cx, sy = out[1] * s + cy;
        ctx.setTransform(dpr * dx, dpr * dy, -dpr * dy, dpr * dx, dpr * sx, dpr * sy);
        ctx.drawImage(img, -half, -half, img.cssW, img.cssH);
        drawn++;
      }
    }
    ctx.restore();
    return drawn;
  }

  motion.register({
    id: "flights",
    name: t("Flights"),
    data: "flights",
    axis: "month",
    get range() {
      if (!model) return [motion.month("2024-01"), motion.month("2024-01") + 12];
      return [model.m0, model.m0 + model.n];
    },
    step: 1,
    speed: SPEED,
    loop: true,
    z: 40,
    label: (tm) => (model ? date(model.months[monthOf(tm)]) : ""),
    status: (tm) => {
      if (!model) return "";
      const n = monthTotal(monthOf(tm));
      return t("{n} air passengers", { n: compact(n) });
    },
    active: () => on,
    load: ensure,
    filter(sel) {
      townSel = sel && sel.kind === "city" ? sel.city : null;
      clicked = null;
      refocus();
    },
    draw(ctx, vp, tm, o) {
      if (!model) return 0;
      return drawPlanes(ctx, vp, tm, o);
    },
  });

  // --- static art: the route arcs and the Polish airports -------------------------------------------------------
  const widthPx = (r) => 0.4 + Math.sqrt(r.total) * 0.0016;
  app.registerStaticLayer({
    id: "flight-routes", z: 84,
    visible: () => on && !!model,
    sig: () => `v${version}`,
    draw(ctx, vp) {
      const s = vp.s;
      ctx.lineCap = "round";
      for (const r of model.routes) {
        if (!routeOn(r)) continue;
        const [x0, y0, x1, y1] = r.bbox;
        if (x1 < vp.x0 || x0 > vp.x1 || y1 < vp.y0 || y0 > vp.y1) continue;
        ctx.beginPath();
        ctx.moveTo(r.pts[0], r.pts[1]);
        for (let k = 1; k <= STEPS; k++) ctx.lineTo(r.pts[2 * k], r.pts[2 * k + 1]);
        ctx.lineWidth = Math.min(2.4, widthPx(r) * (focus ? 1.3 : 1)) / s;
        ctx.strokeStyle = focus ? "rgba(255,214,140,.3)" : "rgba(250,244,226,.16)";
        ctx.stroke();
      }
    },
  });

  const airportR = (a, Rpx) => Math.max(5, Math.min(14, 4 + Math.sqrt((a.value || []).reduce((x, v) => x + (v || 0), 0)) / 900)) * Math.max(0.8, Math.min(1.5, Rpx / 10));
  app.registerStaticLayer({
    id: "flight-airports", z: 67,
    visible: () => on && !!model,
    sig: () => `v${version}`,
    draw(ctx, vp, w, o) {
      for (let i = 0; i < model.airports.length; i++) {
        const a = model.airports[i];
        if (!a.polish || a.x == null) continue;
        const r = airportR(a, o.Rpx) / vp.s;
        const hot = focus?.has(i);
        ctx.beginPath();
        ctx.arc(a.x, a.y, r, 0, Math.PI * 2);
        ctx.lineWidth = (hot ? 2.6 : 1.6) / vp.s;
        ctx.strokeStyle = hot ? "#ffd27a" : "rgba(244,236,210,.85)";
        ctx.stroke();
      }
    },
    hit(x, y, Rpx) {
      if (!model) return null;
      const s = app.cam.scale;
      let best = null, bd = Infinity;
      model.airports.forEach((a, i) => {
        if (!a.polish || a.x == null) return;
        const d = Math.hypot(a.x - x, a.y - y);
        if (d <= (airportR(a, Rpx) + 4) / s && d < bd) { bd = d; best = i; }
      });
      return best == null ? null : { airport: best };
    },
    tooltip: (it) => airportCard(it.airport),
    click(it, ev) {
      clicked = clicked === it.airport ? null : it.airport;
      refocus();
      if (ev.pointerType !== "mouse") showHtmlTooltip(ev.x, ev.y, airportCard(it.airport));
      app.requestDraw();
      return true;
    },
  });

  function airportCard(i) {
    const a = model.airports[i];
    const tm = motion.clock.layer === "flights" ? motion.clock.t : model.m0 + 6;
    const mi = monthOf(tm ?? model.m0);
    const rows = model.routes.filter((r) => r.from === i && r.value[mi] > 0).sort((p, q) => q.value[mi] - p.value[mi]).slice(0, TOP);
    return `<b>${esc(label(a))}</b><br><span class="muted">${esc(t("Top destinations"))}, ${esc(date(model.months[mi]))}</span>${
      rows.map((r, k) => {
        const b = model.airports[r.to];
        return `<br>${k + 1}. ${esc(label(b))} <span class="muted">${esc(country(b.country))}</span> <b>${esc(int(r.value[mi]))}</b>`;
      }).join("")}<br><span class="muted">${esc(t("passengers in both directions"))}</span>`;
  }

  app.ui.addMapToggle({
    id: "flights", label: t("Flights"), icon: "t-airport", default: false, menu: false,
    title: t("Air routes from Polish airports, month by month"),
    get: () => on,
    set: (v) => {
      on = !!v;
      if (on) ensure();
      else { clicked = null; refocus(); }
      app.requestDraw();
    },
  });
  app.flights = {
    get model() { return model; },
    monthOf: (tm) => (model ? monthOf(tm) : null),
    /** Show only one Polish airport's routes (ICAO code), as a click on it does; null shows all. */
    focus(icao) {
      return ensure().then((m) => {
        if (!m) return;
        const i = m.airports.findIndex((a) => a.icao === icao && a.polish);
        clicked = i >= 0 ? i : null;
        refocus();
        app.requestDraw();
      });
    },
  };
}

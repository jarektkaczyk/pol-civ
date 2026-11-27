// Power now: the national grid every 15 minutes (power.json, PSE). Today's figures come straight from the PSE open
// API when the layer turns on (one plain request per report, 4 s timeout); when that fails the layer plays the
// newest complete day from power.json. Flows across each border run along the border lines in their true direction,
// thicker for more megawatts; wind turbines spin with the national wind output; solar parks glow with the national
// solar output; a small card shows the generation mix at the clock's quarter of an hour.
//
// Clock: the "day" axis from 00:00. The range ends with the newest quarter, so the clock replays today up to the
// latest data and starts again.
import { esc } from "../../format.js";
import { t, int, num, date, LOCALE, ROOT } from "../../i18n.js";

const Q = 900; // s: one quarter of an hour
const DAY = 86400;
const MIN_LIVE = 4; // fewer complete quarters than this today (just after midnight): use the stored day
const LIVE_ABORT = 20000; // ms: PSE often takes 5 s or more for a day; a late answer replaces the stored day
const DOT_KM = 60 / 1440; // dot speed in km per clock second: 60 km per real second at 1x
const SPIN = (2 * Math.PI * 1.5) / 1440; // rad per clock second at full wind output (1.5 turns a second at 1x)
const WIND_MIN_MW = 20; // powiats with less installed wind or solar get no marker
const SOLAR_MIN_MW = 20;
const IMPORT = "#8fe3ff";
const EXPORT = "#ffb35c";
export const COLORS = {
  hard_coal: "#6b6259", lignite: "#9a7552", gas: "#4fa3d9", wind: "#7fe0c8", solar: "#ffd23f", biomass: "#86b84a",
  hydro: "#3d86ff", storage: "#a58cff", oil: "#c8643f", other: "#b9ae98",
};

/** Today's date in Warsaw as YYYY-MM-DD. */
export function warsawDay(now = new Date()) {
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const g = (k) => p.find((x) => x.type === k)?.value;
  return `${g("year")}-${g("month")}-${g("day")}`;
}

/** PSE numbers: a number, or text with a decimal comma ("4244,492"). */
export function pseNum(v) {
  if (v == null || typeof v === "boolean") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const x = Number(String(v).replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(x) ? x : null;
}

const secOf = (period) => {
  const m = /^\s*(\d{2}):(\d{2})/.exec(String(period || ""));
  return m ? +m[1] * 3600 + +m[2] * 60 : null;
};

/**
 * The three PSE reports of one day -> a model {t, mix, wind, solar, demand, net} with the complete quarters only
 * (demand, wind, solar, at least 10 production types and the flows of every neighbour present).
 */
export function parseLive(groups, cal, gen, flows, neighbours) {
  const byUtc = new Map();
  for (const r of cal || []) {
    const t0 = secOf(r.period);
    if (t0 == null || !r.dtime_utc) continue;
    byUtc.set(r.dtime_utc, { t: t0, wind: pseNum(r.wi), solar: pseNum(r.pv), demand: pseNum(r.demand), gen: {}, net: {}, nsec: 0 });
  }
  for (const r of gen || []) {
    const q = byUtc.get(r.dtime_utc);
    const v = pseNum(r.value);
    if (q && r.alias_entsoe && v != null) q.gen[r.alias_entsoe] = v;
  }
  for (const r of flows || []) {
    const q = byUtc.get(r.dtime_utc);
    const m = /^([A-Z]{2})(?:_\w+)?-([A-Z]{2})(?:_\w+)?$/.exec(String(r.section_code || ""));
    const v = pseNum(r.value);
    if (!q || !m || v == null) continue;
    const other = m[1] === "PL" ? m[2] : m[1];
    q.net[other] = (q.net[other] || 0) + v;
    q.nsec++;
  }
  const codes = neighbours.map((n) => n.code);
  const quarters = [...byUtc.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([, q]) => q)
    .filter((q) => q.wind != null && q.solar != null && q.demand != null && Object.keys(q.gen).length >= 10
      && codes.every((c) => q.net[c] != null));
  const known = new Set(groups.flatMap((g) => g.codes));
  const mix = Object.fromEntries(groups.map((g) => [g.key, quarters.map((q) => {
    const codesHere = Object.keys(q.gen).filter((c) => g.codes.includes(c) || (g.key === "other" && !known.has(c)));
    return codesHere.length ? codesHere.reduce((s, c) => s + q.gen[c], 0) : 0;
  })]));
  return {
    t: quarters.map((q) => q.t),
    mix,
    wind: quarters.map((q) => q.wind),
    solar: quarters.map((q) => q.solar),
    demand: quarters.map((q) => q.demand),
    net: Object.fromEntries(codes.map((c) => [c, quarters.map((q) => q.net[c])])),
  };
}

/** Index of the quarter that holds clock value tm (the last one that starts at or before it). */
export function quarterAt(ts, tm) {
  let lo = 0, hi = ts.length - 1;
  if (!(hi >= 0) || tm <= ts[0]) return 0;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (ts[mid] <= tm) lo = mid; else hi = mid;
  }
  return ts[hi] <= tm ? hi : lo;
}

async function fetchLive(doc, day) {
  const live = doc.live;
  if (!live?.base || typeof fetch !== "function") return null;
  const ctl = typeof AbortController === "function" ? new AbortController() : null;
  const timer = setTimeout(() => ctl?.abort(), LIVE_ABORT);
  try {
    const flt = encodeURIComponent(String(live.filter || "business_date eq '{day}'").replace("{day}", day));
    const get = (rep) => fetch(`${live.base}${rep}?$filter=${flt}&$first=${live.first || 2000}`,
      { signal: ctl?.signal, credentials: "omit", referrerPolicy: "no-referrer" })
      .then((r) => (r.ok ? r.json() : null));
    const [gen, cal, flows] = await Promise.all([get(live.reports.mix), get(live.reports.totals), get(live.reports.flows)]);
    if (!gen?.value || !cal?.value || !flows?.value) return null;
    const m = parseLive(doc.groups || [], cal.value, gen.value, flows.value, doc.neighbours || []);
    return m.t.length >= MIN_LIVE ? m : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

const sprites = new Map();
/** A soft round glow (css px radius), cached per colour, size and device scale. */
function glow(color, r, dpr) {
  const rr = Math.max(2, Math.round(r));
  const key = `${color}|${rr}|${dpr}`;
  let c = sprites.get(key);
  if (c) return c;
  c = document.createElement("canvas");
  c.width = c.height = Math.ceil(2 * rr * dpr);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  const grad = g.createRadialGradient(rr, rr, 0, rr, rr, rr);
  grad.addColorStop(0, "rgba(255,250,220,.95)");
  grad.addColorStop(0.25, color);
  grad.addColorStop(1, "rgba(255,210,63,0)");
  g.fillStyle = grad;
  g.beginPath();
  g.arc(rr, rr, rr, 0, Math.PI * 2);
  g.fill();
  c.css = 2 * rr;
  if (sprites.size > 200) sprites.clear();
  sprites.set(key, c);
  return c;
}

function addCss() {
  if (document.getElementById("flows-css")) return;
  const l = document.createElement("link");
  l.id = "flows-css";
  l.rel = "stylesheet";
  l.href = `${ROOT}css/flows.css`;
  document.head.appendChild(l);
}

export function install(app) {
  const motion = app.motion;
  if (!motion) return;
  addCss();
  let on = false;
  let doc = null;
  let model = null;
  let loading = null;
  let card = null;
  let cardKey = "";
  let regionNames = null;
  try { regionNames = new Intl.DisplayNames([LOCALE], { type: "region" }); } catch { regionNames = null; }
  const country = (code) => {
    try { return regionNames?.of(code) || code; } catch { return code; }
  };
  const gw = (mw) => num((mw || 0) / 1000, 1);

  function build(d, live, day) {
    const src = live || { t: d.t, mix: d.mix, wind: d.wind, solar: d.solar, demand: d.demand,
      net: Object.fromEntries(d.neighbours.map((n) => [n.code, n.net])) };
    const n = src.t.length;
    const windCap = (d.res_powiat || []).reduce((s, r) => s + (r.wind_mw || 0), 0) || 10000;
    const solarCap = (d.res_powiat || []).reduce((s, r) => s + (r.solar_mw || 0), 0) || 10000;
    // Turbine angle: the integral of the spin speed (a share of full output) over the clock, per quarter.
    const rot = new Float64Array(n);
    for (let i = 1; i < n; i++) rot[i] = rot[i - 1] + SPIN * Math.min(1, (src.wind[i - 1] || 0) / windCap) * (src.t[i] - src.t[i - 1]);
    const lines = [];
    for (const nb of d.neighbours) {
      for (const ln of nb.lines) {
        lines.push({ nb: nb.code, k: nb.lines.length, ln, flow: motion.particles(ln.path, { slots: 18, speed: DOT_KM, seed: lines.length * 31 + 7 }) });
      }
    }
    const turbines = [
      ...d.wind_farms.filter((w) => w.status === "operating").map((w) => ({ ...w, farm: true })),
      ...(d.res_powiat || []).filter((r) => r.wind_mw >= WIND_MIN_MW).map((r) => ({ name: r.name, mw: r.wind_mw, x: r.x, y: r.y, powiat: true })),
    ];
    const suns = [
      ...d.solar_farms.filter((w) => w.status === "operating").map((w) => ({ ...w, farm: true })),
      ...(d.res_powiat || []).filter((r) => r.solar_mw >= SOLAR_MIN_MW).map((r) => ({ name: r.name, mw: r.solar_mw, x: r.x, y: r.y, powiat: true })),
    ];
    const end = live ? src.t[n - 1] + Q : DAY;
    return { ...src, n, live: !!live, day, windCap, solarCap, rot, lines, turbines, suns, end, groups: d.groups };
  }

  const ensure = () => {
    if (model) return Promise.resolve(model);
    loading ??= app.loadData("power").then(async (d) => {
      if (!d || !Array.isArray(d.t) || !d.t.length) return null;
      doc = d;
      const day = warsawDay();
      // Wait up to live.timeout_ms for today; then play the stored day, and switch to today if it still arrives.
      const req = fetchLive(d, day);
      const wait = new Promise((ok) => setTimeout(() => ok(undefined), d.live?.timeout_ms || 4000));
      const live = await Promise.race([req, wait]);
      model = build(d, live || null, live ? day : d.day);
      if (live === undefined) {
        req.then((m) => {
          if (!m) return;
          model = build(d, m, day);
          cardKey = "";
          app.requestDraw();
        });
      }
      app.requestDraw();
      return model;
    });
    return loading;
  };

  // PSE stamps a quarter with its end: 00:00-00:15 is "00:15", the last one "24:00".
  const timeOf = (i) => (model.t[i] + Q >= DAY ? "24:00" : motion.hhmm(model.t[i] + Q));
  const asOf = (i) => (model.live ? t("as of {time}", { time: timeOf(i) }) : t("as of {time}", { time: `${date(model.day)} ${timeOf(i)}` }));

  // --- the mix card ---------------------------------------------------------------------------------------------
  function ensureCard() {
    if (card) return card;
    const area = document.getElementById("lens-area");
    if (!area) return null;
    card = document.createElement("div");
    card.className = "panel power-card";
    card.hidden = true;
    area.insertBefore(card, document.getElementById("motion-bar") || document.getElementById("lens-dock") || null);
    return card;
  }
  function updateCard(i) {
    const show = on && !!model && motion.clock.layer === "power";
    const el = ensureCard();
    if (!el) return;
    if (el.hidden === show) el.hidden = !show;
    if (!show) { cardKey = ""; return; }
    const key = `${i}|${model.live}`;
    if (key === cardKey) return;
    cardKey = key;
    const items = model.groups.map((g) => ({ key: g.key, label: t(g.label), mw: Math.max(0, model.mix[g.key]?.[i] || 0) }))
      .filter((x) => x.mw > 0).sort((a, b) => b.mw - a.mw);
    const total = items.reduce((s, x) => s + x.mw, 0) || 1;
    const net = Object.values(model.net).reduce((s, v) => s + (v[i] || 0), 0);
    el.innerHTML = `<div class="pc-head"><b>${esc(t("Power now"))}</b> <span class="muted">${esc(asOf(i))}</span></div>
      <div class="pc-bar">${items.map((x) => `<span style="flex:${(x.mw / total).toFixed(4)};background:${COLORS[x.key] || "#999"}"></span>`).join("")}</div>
      <ul class="pc-list">${items.slice(0, 6).map((x) => `<li><i style="background:${COLORS[x.key] || "#999"}"></i>${esc(x.label)} <b>${esc(gw(x.mw))} GW</b></li>`).join("")}
      <li class="pc-net">${esc(net >= 0 ? t("Import") : t("Export"))} <b>${esc(gw(Math.abs(net)))} GW</b></li>
      <li class="pc-net">${esc(t("Demand"))} <b>${esc(gw(model.demand[i]))} GW</b></li></ul>`;
  }

  // --- drawing ------------------------------------------------------------------------------------------------------
  function drawTurbine(ctx, sx, sy, px, ang, dpr) {
    ctx.setTransform(dpr, 0, 0, dpr, sx * dpr, sy * dpr);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(0, px * 1.1);
    ctx.lineWidth = Math.max(2, px * 0.2);
    ctx.strokeStyle = "rgba(20,12,4,.85)";
    ctx.stroke();
    ctx.lineWidth = Math.max(1, px * 0.1);
    ctx.strokeStyle = "#f4f1e6";
    ctx.stroke();
    for (let b = 0; b < 3; b++) {
      const a = ang + (b * 2 * Math.PI) / 3;
      const ex = Math.cos(a) * px, ey = Math.sin(a) * px;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(ex, ey);
      ctx.lineWidth = Math.max(2.6, px * 0.26);
      ctx.strokeStyle = "rgba(20,12,4,.85)";
      ctx.stroke();
      ctx.lineWidth = Math.max(1.4, px * 0.15);
      ctx.strokeStyle = "#fbfaf4";
      ctx.stroke();
    }
  }

  function draw(ctx, vp, tm, o) {
    const i = quarterAt(model.t, tm);
    updateCard(i);
    const { cam, dpr } = vp;
    const s = cam.scale, cx = cam.w / 2 - cam.x * s, cy = cam.h / 2 - cam.y * s;
    const inView = (x, y, m) => x > vp.x0 - m && x < vp.x1 + m && y > vp.y0 - m && y < vp.y1 + m;
    let dots = 0;
    // Solar glow under everything.
    const sun = Math.min(1, Math.max(0, (model.solar[i] || 0) / model.solarCap));
    if (sun > 0.002) {
      ctx.save();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.globalAlpha = Math.min(1, 0.25 + sun * 1.6);
      for (const p of model.suns) {
        if (!inView(p.x, p.y, 20 / s)) continue;
        const r = Math.max(7, Math.min(30, 5 + Math.sqrt(p.mw) * 1.3)) * Math.max(0.8, Math.min(1.6, o.Rpx / 10)) * (0.6 + 0.4 * Math.sqrt(sun));
        const img = glow("rgba(255,214,70,.85)", r, dpr);
        ctx.drawImage(img, p.x * s + cx - img.css / 2, p.y * s + cy - img.css / 2, img.css, img.css);
      }
      ctx.restore();
    }
    // Border flows: the line, thicker for more megawatts, and dots in the direction of the flow.
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const L of model.lines) {
      const v = (model.net[L.nb]?.[i] || 0) / L.k; // the border's flow shared evenly by its lines
      const a = Math.abs(v);
      const p = L.ln.path;
      ctx.beginPath();
      ctx.moveTo(p[0], p[1]);
      for (let k = 2; k < p.length; k += 2) ctx.lineTo(p[k], p[k + 1]);
      const wpx = Math.min(11, 2.5 + a / 200);
      ctx.lineWidth = (wpx + 2.5) / s;
      ctx.strokeStyle = "rgba(20,12,4,.6)";
      ctx.stroke();
      ctx.lineWidth = wpx / s;
      ctx.strokeStyle = a < 5 ? "rgba(230,224,206,.6)" : v > 0 ? "rgba(143,227,255,.85)" : "rgba(255,179,92,.85)";
      ctx.stroke();
      if (a >= 5) {
        dots += L.flow.draw(ctx, vp, tm, { density: Math.min(1, 0.2 + a / 700), dir: v > 0 ? -1 : 1,
          size: Math.max(4, Math.min(7, 3.4 + o.Rpx * 0.12)), color: v > 0 ? IMPORT : EXPORT });
      }
    }
    ctx.restore();
    // Turbines spin with the national wind output.
    const k = Math.min(1, (model.wind[i] || 0) / model.windCap);
    const ang = model.rot[i] + SPIN * k * (tm - model.t[i]);
    ctx.save();
    const zoom = Math.max(0.65, Math.min(1.6, o.Rpx / 10));
    const minPowiat = o.Rpx < 7 ? 60 : WIND_MIN_MW; // fewer powiat turbines at the country view
    for (const w of model.turbines) {
      if (w.powiat && w.mw < minPowiat) continue;
      if (!inView(w.x, w.y, 20 / s)) continue;
      const px = Math.max(6, Math.min(15, 4.5 + Math.sqrt(w.mw) * 0.5)) * zoom;
      drawTurbine(ctx, w.x * s + cx, w.y * s + cy, px, ang + (w.x % 7), dpr);
    }
    ctx.restore();
    return dots;
  }

  // --- hover card -------------------------------------------------------------------------------------------------
  function hit(mx, my) {
    if (!model) return null;
    const tm = motion.clock.layer === "power" ? motion.clock.t : model.t[model.n - 1];
    const i = quarterAt(model.t, tm ?? 0);
    const [wx, wy] = [(mx - app.cam.w / 2) / app.cam.scale + app.cam.x, (my - app.cam.h / 2) / app.cam.scale + app.cam.y];
    const near = (x, y) => Math.hypot(x - wx, y - wy) * app.cam.scale;
    for (const list of [model.turbines, model.suns]) {
      let best = null, bd = 12;
      for (const p of list) {
        const d = near(p.x, p.y);
        if (d < bd) { bd = d; best = p; }
      }
      if (best) {
        const kind = list === model.turbines ? t("Wind") : t("Solar");
        const out = list === model.turbines ? model.wind[i] : model.solar[i];
        return { html: `<b>${esc(best.name || "")}</b><br><span class="muted">${esc(best.powiat ? t("{kind}, installed in the powiat", { kind }) : kind)}</span><br>`
          + `${esc(t("Capacity"))} <b>${esc(int(best.mw))} MW</b><br>`
          + `${esc(t("{kind} in Poland, {time}", { kind, time: timeOf(i) }))} <b>${esc(gw(out))} GW</b>` };
      }
    }
    // Border lines: the nearest point of a line within 8 px.
    let bestL = null, bd = 8;
    for (const L of model.lines) {
      const p = L.ln.path;
      for (let k = 0; k + 3 < p.length; k += 2) {
        const ax = p[k], ay = p[k + 1], bx = p[k + 2], by = p[k + 3];
        const dx = bx - ax, dy = by - ay, den = dx * dx + dy * dy || 1;
        const f = Math.max(0, Math.min(1, ((wx - ax) * dx + (wy - ay) * dy) / den));
        const d = near(ax + f * dx, ay + f * dy);
        if (d < bd) { bd = d; bestL = L; }
      }
    }
    if (!bestL) return null;
    const v = model.net[bestL.nb]?.[i] || 0;
    const names = model.lines.filter((L) => L.nb === bestL.nb).map((L) => L.ln.name).filter(Boolean);
    const dirTxt = Math.abs(v) < 5 ? t("No flow") : v > 0 ? t("{mw} MW into Poland", { mw: int(v) }) : t("{mw} MW out of Poland", { mw: int(-v) });
    return { html: `<b>${esc(country(bestL.nb))}</b> <span class="muted">${esc(asOf(i))}</span><br>${esc(dirTxt)}`
      + `${names.length ? `<br><span class="muted">${names.map(esc).join("<br>")}</span>` : ""}` };
  }

  motion.register({
    id: "power",
    name: t("Power now"),
    data: "power",
    axis: "day",
    get range() { return [0, model ? model.end : DAY]; },
    step: Q,
    speed: 1440,
    loop: true,
    z: 20,
    label: (tm) => (model ? asOf(quarterAt(model.t, tm)) : ""),
    active: () => on,
    load: ensure,
    draw(ctx, vp, tm, o) {
      if (!model) return 0;
      return draw(ctx, vp, tm, o);
    },
    hit,
  });

  app.ui.addMapToggle({
    id: "power", label: t("Power now"), icon: "r-wind", default: false,
    title: t("Electricity generation and cross-border flows, every 15 minutes"),
    get: () => on,
    set: (v) => {
      on = !!v;
      if (on) ensure();
      else updateCard(0);
      app.requestDraw();
    },
  });
  app.power = {
    get model() { return model; },
    quarterAt: (tm) => (model ? quarterAt(model.t, tm) : null),
  };
}

// Trains: every passenger train of one ordinary Wednesday (trains.json, PKP PLK timetable) as a dot that moves along
// its line on the shared day clock, coloured by operator, long-distance trains larger. Hover or tap a train for its
// number, name, route and next stop; hover a station for its next departures; click a station (or select a town) to
// see only the trains through it. Night trains that left the evening before run in the early morning.
//
// On by default: a visit without layers= in the URL starts with the trains on, the clock at the current time in
// Poland (a #t= link still wins), and trains.json loads only once the map has drawn its first frame.
//
// Position: a trip has its stops' times and their distances along the trip's line (trains.json patterns), so a
// train between two stops sits at the linear share of the distance; it waits at a stop between arrival and departure.
import { esc } from "../../format.js";
import { t, int } from "../../i18n.js";
import { showHtmlTooltip } from "../../ui/tooltip.js";

const DAY = 86400;
const BUCKET = 900; // s: trips are indexed by the 15-minute buckets they are on the move in
const START = 7 * 3600; // the clock opens at 07:00, in the morning rush (when switched on by hand)
// Operator colours: long distance warm and large, regional operators each their own hue.
const COLORS = {
  IC: "#e8392f", LEO: "#ffd23f", RJ: "#ffd23f", PR: "#ff8c1a", KM: "#3fcf5a", KS: "#2f9bff", KD: "#a970ff",
  KW: "#f2e6c4", SKMT: "#22d3c5", LKA: "#ff5fae", SKM: "#b6f03c", KML: "#5c7cff", AR: "#e6e6e6",
};
const FALLBACK = "#e0d6bf";

const sprites = new Map();
/** A train marker: a solid disc with a dark outline (long distance: with a light ring), css px, cached. */
function sprite(color, px, long, dpr) {
  const d = Math.max(3, Math.round(px * 2) / 2);
  const key = `${color}|${d}|${long ? 1 : 0}|${dpr}`;
  let c = sprites.get(key);
  if (c) return c;
  const pad = 1.5;
  const r = d / 2;
  c = document.createElement("canvas");
  c.width = c.height = Math.ceil((d + 2 * pad) * dpr);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  const m = pad + r;
  g.beginPath();
  g.arc(m, m, r, 0, Math.PI * 2);
  g.fillStyle = "rgba(20,12,4,.95)";
  g.fill();
  if (long) {
    g.beginPath();
    g.arc(m, m, r - 1.1, 0, Math.PI * 2);
    g.fillStyle = "#fff6dc";
    g.fill();
  }
  g.beginPath();
  g.arc(m, m, r - (long ? 2.1 : 1.1), 0, Math.PI * 2);
  g.fillStyle = color;
  g.fill();
  c.cssW = c.cssH = d + 2 * pad;
  if (sprites.size > 300) sprites.clear();
  sprites.set(key, c);
  return c;
}

/** Seconds since midnight now in Poland (Europe/Warsaw, DST included). */
export function warsawSeconds(date = new Date()) {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Warsaw", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
    }).formatToParts(date);
    const g = (k) => +(parts.find((p) => p.type === k)?.value || 0);
    return (g("hour") % 24) * 3600 + g("minute") * 60 + g("second");
  } catch {
    return START;
  }
}

/** Resolves once the map has drawn a frame and the browser is idle (or after a short timeout in a background tab). */
function afterFirstFrame() {
  return new Promise((done) => {
    let fired = false;
    const go = () => { if (!fired) { fired = true; done(); } };
    requestAnimationFrame(() => {
      if (typeof requestIdleCallback === "function") requestIdleCallback(go, { timeout: 800 });
      else setTimeout(go, 100);
    });
    setTimeout(go, 1500); // rAF never fires in a background tab
  });
}

/** Decode a trip's times: [dep0, run1, dwell1, ...] -> arrival and departure per stop (trains.json). */
export function decodeTimes(tt) {
  const n = (tt.length + 1) >> 1;
  const arr = new Float64Array(n), dep = new Float64Array(n);
  arr[0] = dep[0] = tt[0];
  for (let k = 1; k < n; k++) {
    arr[k] = dep[k - 1] + tt[2 * k - 1];
    dep[k] = arr[k] + tt[2 * k];
  }
  return { arr, dep };
}

/** Where a trip is at clock value t: {d (km along its line), seg (index of the last stop passed), atStop} or null. */
export function tripAt(trip, d, t) {
  const { arr, dep } = trip;
  const n = arr.length;
  if (t < dep[0] || t > arr[n - 1]) return null;
  let lo = 0, hi = n - 1; // the last stop with dep <= t
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (dep[mid] <= t) lo = mid; else hi = mid;
  }
  if (dep[hi] <= t) lo = hi;
  if (lo >= n - 1) return { d: d[n - 1], seg: n - 1, atStop: true };
  const a = arr[lo + 1];
  if (t >= a) return { d: d[lo + 1], seg: lo + 1, atStop: true }; // waiting at the next stop
  const span = a - dep[lo];
  const f = span > 0 ? (t - dep[lo]) / span : 1;
  return { d: d[lo] + f * (d[lo + 1] - d[lo]), seg: lo, atStop: false };
}

export function prepare(doc) {
  const shapes = (doc.shapes || []).map((a) => {
    const pts = Float64Array.from(a);
    const n = pts.length >> 1;
    const cum = new Float64Array(n);
    for (let k = 1; k < n; k++) cum[k] = cum[k - 1] + Math.hypot(pts[2 * k] - pts[2 * k - 2], pts[2 * k + 1] - pts[2 * k - 1]);
    return { pts, cum, n };
  });
  const patterns = (doc.patterns || []).map((p) => ({
    shape: shapes[p.shape], stops: p.stops, d: Float64Array.from(p.d), tech: new Set(p.tech || []),
  }));
  const operators = doc.operators || [];
  const trips = [];
  const through = (doc.stations || []).map(() => []); // station -> trip indices
  for (const tr of doc.trips || []) {
    const pat = patterns[tr.p];
    if (!pat || !Array.isArray(tr.t)) continue;
    const { arr, dep } = decodeTimes(tr.t);
    const op = operators[tr.op] || {};
    const k = trips.length;
    trips.push({
      k, op: tr.op, opId: op.id, long: !!op.long_distance, cat: tr.cat, no: tr.no, name: tr.name, pat, arr, dep,
      start: dep[0], end: arr[arr.length - 1], color: COLORS[op.id] || FALLBACK,
    });
    for (const s of new Set(pat.stops)) through[s].push(k);
  }
  let b0 = Infinity, b1 = -Infinity;
  for (const tr of trips) {
    b0 = Math.min(b0, Math.floor(tr.start / BUCKET));
    b1 = Math.max(b1, Math.floor(tr.end / BUCKET));
  }
  const buckets = Array.from({ length: Math.max(0, b1 - b0 + 1) }, () => []);
  for (const tr of trips) for (let b = Math.floor(tr.start / BUCKET); b <= Math.floor(tr.end / BUCKET); b++) buckets[b - b0].push(tr.k);
  return { doc, shapes, patterns, trips, through, buckets, b0, stations: doc.stations || [], operators };
}

/** Point and direction at distance d along a shape (binary search on the cumulative lengths). */
function pointAt(sh, d, out) {
  const { pts, cum, n } = sh;
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] <= d) lo = mid; else hi = mid;
  }
  const seg = cum[hi] - cum[lo] || 1;
  const f = Math.min(1, Math.max(0, (d - cum[lo]) / seg));
  out[0] = pts[2 * lo] + (pts[2 * hi] - pts[2 * lo]) * f;
  out[1] = pts[2 * lo + 1] + (pts[2 * hi + 1] - pts[2 * lo + 1]) * f;
  return out;
}

/** Trips on the move at t (indices); the clock may sit before 00:00 or after 24:00 only through night trains. */
function activeAt(m, t) {
  const b = Math.floor(t / BUCKET) - m.b0;
  return b >= 0 && b < m.buckets.length ? m.buckets[b] : [];
}

export function install(app) {
  const motion = app.motion;
  if (!motion) return;
  // On by default. `byDefault` stays true until the
  // user switches it: the clock then opens at the current time in Poland and gives way to any other motion layer.
  // A layers= list that does not name trains (an older link) keeps them on; "-trains" turns them off.
  const listed = app.hash?.value?.("layers");
  const tokens = listed == null ? [] : String(listed).split(",").map((s) => s.trim());
  let on = !tokens.includes("-trains");
  let byDefault = !tokens.includes("trains") && !tokens.includes("-trains");
  let model = null;
  let loading = null;
  let focus = null; // {stations: Set, key} | null: only the trains through these stations
  let stationFocus = null; // a clicked station (index), wins over the selected town
  let townSel = null;
  let shown = []; // [{x, y, r, k, seg, atStop}] of the last frame (screen css px), for hover
  let version = 0;
  const tmp = new Float64Array(2);

  const ensure = () => {
    if (model) return Promise.resolve(model);
    loading ??= (byDefault ? afterFirstFrame() : Promise.resolve()).then(() => app.loadData("trains")).then((d) => {
      if (!d || !Array.isArray(d.trips)) return null;
      model = prepare(d);
      version++;
      refocus();
      app.requestDraw();
      return model;
    });
    return loading;
  };

  // Stations of a town: named after it ("Krakow Glowny", "Krakow Plaszow" in their Polish spelling) within 25 km, or within 2.5 km of it.
  function townStations(city) {
    if (!model || !city) return [];
    const name = String(city.name || "");
    const out = [];
    model.stations.forEach((s, i) => {
      const dist = Math.hypot(s.x - city.x, s.y - city.y);
      const named = s.name === name || s.name.startsWith(name + " ");
      if ((named && dist < 25) || dist < 2.5) out.push(i);
    });
    return out;
  }

  function refocus() {
    let list = null, key = "";
    if (stationFocus != null) { list = [stationFocus]; key = `s${stationFocus}`; }
    else if (townSel) { list = townStations(townSel); key = `c${townSel.id}`; }
    focus = list && list.length ? { stations: new Set(list), key } : null;
    version++;
  }
  const passes = (tr) => {
    if (!focus) return true;
    for (const s of tr.pat.stops) if (focus.stations.has(s)) return true;
    return false;
  };

  const sizes = (o) => {
    // phone country view (Rpx about 3) 0.7; laptop country view 1; close up up to 1.7
    const k = o.Rpx < 6 ? Math.max(0.7, o.Rpx / 6) : Math.min(1.7, Math.max(1, o.Rpx / 18));
    return { small: 6.5 * k, large: 9.5 * k };
  };

  motion.register({
    id: "trains",
    name: t("Trains"),
    data: "trains",
    axis: "day",
    range: [0, DAY],
    step: 60,
    speed: 1440,
    // On arrival: the current time in Poland, except between midnight and 05:00, when few trains run.
    get start() { if (!byDefault) return START; const now = warsawSeconds(); return now < 5 * 3600 ? START : now; },
    background: () => byDefault,
    z: 30,
    label: (tc) => motion.hhmm(tc),
    status: (tc) => {
      if (!model) return "";
      let n = 0;
      for (const k of activeAt(model, tc)) {
        const tr = model.trips[k];
        if (tc >= tr.start && tc <= tr.end && passes(tr)) n++;
      }
      return t.plural(n, { one: "{n} train", other: "{n} trains" }, { n: int(n) });
    },
    active: () => on,
    load: ensure,
    filter(sel) {
      townSel = sel && sel.kind === "city" ? sel.city : null;
      stationFocus = null;
      refocus();
    },
    draw(ctx, vp, tc, o) {
      if (!model) return 0;
      const { cam, dpr } = vp;
      const s = cam.scale, cx = cam.w / 2 - cam.x * s, cy = cam.h / 2 - cam.y * s;
      const pad = 8 / s;
      const sz = sizes(o);
      const list = [];
      const late = [];
      ctx.save();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      let drawn = 0;
      const put = (tr, p, dim) => {
        const sx = tmp[0] * s + cx, sy = tmp[1] * s + cy;
        const px = tr.long ? sz.large : sz.small;
        const img = sprite(tr.color, dim ? px * 0.7 : px, tr.long, dpr);
        ctx.globalAlpha = dim ? 0.22 : 1;
        ctx.drawImage(img, sx - img.cssW / 2, sy - img.cssH / 2, img.cssW, img.cssH);
        if (!dim) list.push({ x: sx, y: sy, r: Math.max(5, img.cssW / 2), k: tr.k, seg: p.seg, atStop: p.atStop });
        drawn++;
      };
      for (const k of activeAt(model, tc)) {
        const tr = model.trips[k];
        if (tc < tr.start || tc > tr.end) continue;
        const p = tripAt(tr, tr.pat.d, tc);
        if (!p) continue;
        pointAt(tr.pat.shape, p.d, tmp);
        if (tmp[0] < vp.x0 - pad || tmp[0] > vp.x1 + pad || tmp[1] < vp.y0 - pad || tmp[1] > vp.y1 + pad) continue;
        if (app.w.grid.cellAt(tmp[0], tmp[1]) < 0) continue; // beyond the drawn map (cross-border runs)
        const dim = !passes(tr);
        if (!dim && tr.long) { late.push([tr, p, tmp[0], tmp[1]]); continue; } // long distance on top
        put(tr, p, dim);
      }
      for (const [tr, p, x, y] of late) {
        tmp[0] = x; tmp[1] = y;
        put(tr, p, false);
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
        if (d <= it.r + 3 && d < bd) { bd = d; best = it; }
      }
      return best ? { html: trainCard(model.trips[best.k], best) } : null;
    },
  });

  // A stop where passengers may board, at or after index k (technical stops are skipped).
  const nextPax = (tr, k) => {
    for (let j = k; j < tr.pat.stops.length; j++) if (!tr.pat.tech.has(j)) return j;
    return tr.pat.stops.length - 1;
  };
  const stName = (i) => model.stations[i]?.name || "";
  const trainTitle = (tr) => [tr.cat, tr.no].filter(Boolean).join(" ");

  function trainCard(tr, at) {
    const stops = tr.pat.stops;
    const from = stName(stops[0]), to = stName(stops[stops.length - 1]);
    const j = nextPax(tr, at.seg + 1);
    const atEnd = at.seg >= stops.length - 1;
    const op = model.operators[tr.op]?.name || "";
    return `<b>${esc(trainTitle(tr))}</b>${tr.name ? ` ${esc(tr.name)}` : ""}<br>${esc(t("{from} to {to}", { from, to }))}${
      atEnd ? "" : `<br>${esc(t("Next stop"))}: <b>${esc(stName(stops[j]))}</b> ${esc(motion.hhmm(tr.arr[j]))}`}${
      op ? `<br><span class="muted">${esc(op)}</span>` : ""}`;
  }

  // --- stations: a static layer (small markers while the layer is on), hover for departures, click to focus ------
  const stationTrips = (i) => (model ? model.through[i].length : 0);
  const minTrains = (Rpx) => (Rpx < 12 ? 150 : Rpx < 24 ? 50 : Rpx < 48 ? 10 : 1);
  function stationList(Rpx) {
    if (!model) return [];
    const floor = minTrains(Rpx);
    const out = [];
    model.stations.forEach((s, i) => {
      if (stationTrips(i) >= floor || focus?.stations.has(i)) out.push(i);
    });
    return out;
  }

  function departures(i, tc, n = 5) {
    const rows = [];
    for (const k of model.through[i]) {
      const tr = model.trips[k];
      const stops = tr.pat.stops;
      for (let j = 0; j < stops.length - 1; j++) {
        if (stops[j] !== i || tr.pat.tech.has(j)) continue;
        let when = tr.dep[j];
        if (when < tc) when += DAY; // tomorrow's run of the same train
        if (when - tc < DAY) rows.push({ when, tr, j });
      }
    }
    rows.sort((a, b) => a.when - b.when);
    return rows.slice(0, n);
  }

  function stationCard(i) {
    const tc = motion.clock.layer === "trains" ? motion.clock.t : START;
    const n = stationTrips(i);
    const rows = departures(i, tc ?? START);
    return `<b>${esc(stName(i))}</b><br>${esc(t.plural(n, { one: "{n} train a day", other: "{n} trains a day" }, { n: int(n) }))}${
      rows.length ? `<br><span class="muted">${esc(t("Next departures"))}</span><br>${rows.map((r) => {
        const stops = r.tr.pat.stops;
        return `${esc(motion.hhmm(r.when))} ${esc(trainTitle(r.tr))} <span class="muted">${esc(stName(stops[stops.length - 1]))}</span>`;
      }).join("<br>")}` : ""}`;
  }

  app.registerStaticLayer({
    id: "train-stations", z: 66, minRpx: 4,
    visible: () => on && !!model,
    sig: () => `v${version}`,
    draw(ctx, vp, w, o) {
      const pad = 10 / vp.s;
      const r = Math.max(1.4, Math.min(3, o.Rpx * 0.07)) / vp.s;
      for (const i of stationList(o.Rpx)) {
        const st = model.stations[i];
        if (st.x < vp.x0 - pad || st.x > vp.x1 + pad || st.y < vp.y0 - pad || st.y > vp.y1 + pad) continue;
        const hot = focus?.stations.has(i);
        ctx.beginPath();
        ctx.rect(st.x - r, st.y - r, 2 * r, 2 * r);
        ctx.fillStyle = hot ? "#ffe9a8" : "rgba(40,28,14,.85)";
        ctx.fill();
        ctx.lineWidth = (hot ? 1.6 : 1) / vp.s;
        ctx.strokeStyle = hot ? "rgba(28,18,8,.9)" : "rgba(248,240,216,.9)";
        ctx.stroke();
      }
    },
    hit(x, y, Rpx) {
      if (!model) return null;
      const s = app.cam.scale;
      const tol = Math.max(5, Rpx * 0.25) / s;
      let best = null, bd = Infinity;
      for (const i of stationList(Rpx)) {
        const st = model.stations[i];
        const d = Math.hypot(st.x - x, st.y - y);
        if (d < tol && d < bd) { bd = d; best = i; }
      }
      return best == null ? null : { station: best };
    },
    tooltip: (it) => stationCard(it.station),
    click(it, ev) {
      stationFocus = stationFocus === it.station ? null : it.station;
      refocus();
      if (ev.pointerType !== "mouse") showHtmlTooltip(ev.x, ev.y, stationCard(it.station));
      app.requestDraw();
      return true;
    },
  });

  app.ui.addMapToggle({
    id: "trains", label: t("Trains"), icon: "t-rail", default: true, keepDefault: true, menu: false,
    title: t("Every passenger train of one weekday, on the move"),
    get: () => on,
    set: (v) => {
      on = !!v;
      byDefault = false;
      if (on) ensure();
      else { stationFocus = null; refocus(); }
      app.requestDraw();
    },
  });
  app.trains = { get model() { return model; }, tripAt, departures: (i, tc) => (model ? departures(i, tc) : []) };
}

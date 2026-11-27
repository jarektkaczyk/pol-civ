// Lenses that play on the shared motion clock (app.motion):
//
// * Tourist nights by month (lens tourism_monthly, month axis): nights per resident of each voivodeship for the
//   newest 36 months (timelapse.json). Seaside summers, mountain winters.
// * Smog week (lens smog_week, hour axis): hourly PM2.5 on the hexes within 40 km of a station, for the worst week
//   of winter 2025/26 (smog.json). Hover a hex for its value and the nearest stations.
// * Presidential vote over time (lenses vote_2015, vote_2020, vote; year axis): the three runoffs share one scale,
//   so the map blends their colours between runoff years. The clock label and the hover card name only the runoff
//   years and their published shares; the shown lens switches to the runoff the clock has reached.
//
// These are lenses, not Map-menu layers: the motion layer is on while its lens is shown. Each swaps its lens's
// `values` for the moment on the clock and recolours the map only when that moment changes (a whole month, a whole
// hour, a quarter-year step of the vote blend), so the static map re-renders a few times a second at most.
import { esc } from "../../format.js";
import { t, int, num, pct, date, LANG } from "../../i18n.js";
import { recolour, drawLegendHist, placeOf } from "./legend.js";

const TOURISM_SPEED = 3; // months per second at 1x (36 months in 12 s)
const SMOG_SPEED = 6; // hours per second at 1x (the week in 28 s)
const VOTE_SPEED = 1.5; // years per second at 1x (2015 to 2025 in about 7 s)
const VOTE_STEP = 0.25; // years between two recolours of the vote blend (half way falls on a step)
const STATION_KM = 40; // as the smog interpolation (pipeline/build/smog.py)

const DAYS = {
  en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
  pl: ["niedz.", "pon.", "wt.", "śr.", "czw.", "pt.", "sob."],
};
const MONTHS = {
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  pl: ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września", "października",
    "listopada", "grudnia"],
};
/** Hour axis value -> "Tue 20 Jan, 23:00" / "wt. 20 stycznia, 23:00" (the hour that starts then). */
export function hourLabel(h, lang = LANG) {
  const d = new Date(Math.floor(h) * 3600000);
  const L = lang === "pl" ? "pl" : "en";
  return `${DAYS[L][d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[L][d.getUTCMonth()]}, ${String(d.getUTCHours()).padStart(2, "0")}:00`;
}

/** The vote blend at year t: the runoff before it, the next one and how far along (0..1). */
export function voteSegment(years, tt) {
  if (tt <= years[0]) return { i: 0, f: 0 };
  for (let i = 0; i < years.length - 1; i++) {
    if (tt < years[i + 1]) return { i, f: (tt - years[i]) / (years[i + 1] - years[i]) };
  }
  return { i: years.length - 1, f: 0 };
}

export function install(app) {
  const motion = app.motion;
  if (!motion) return;
  const size = app.w.grid.size;
  const owner = app.w.raw.owner;
  const reduce = () => motion.reducedMotion;

  // A lens pick after the page loaded: the clock jumps to that lens's own start (the year axis is shared with the
  // population years and migration, the month axis with permits and flights).
  const wanted = new Map(); // layer id -> clock value to seek once the layer has the clock
  function takeWanted(id) {
    if (!wanted.has(id) || motion.clock.layer !== id) return;
    const v = wanted.get(id);
    wanted.delete(id);
    motion.clock.seek(v);
  }

  // ---- tourist nights by month -------------------------------------------------------------------------------
  const tLens = app.lensById.get("tourism_monthly");
  if (tLens) {
    const own = tLens.values;
    const arr = new Array(size).fill(null);
    let doc = null, m0 = 0, shown = -1, loading = null;
    const first = () => motion.month(tLens.time?.first), last = () => motion.month(tLens.time?.last);
    const load = () => (loading ??= app.loadData("timelapse").then((d) => {
      if (d?.tourism?.months?.length) { doc = d; m0 = motion.month(d.tourism.months[0]); }
    }));
    const idx = (tm) => (doc ? Math.max(0, Math.min(doc.tourism.months.length - 1, Math.floor(tm) - m0)) : -1);
    motion.register({
      id: "tourism-monthly",
      name: t("Tourist nights by month"),
      data: "timelapse",
      axis: "month",
      get range() { return [first(), last()]; },
      get start() { return reduce() ? last() : first(); },
      step: 1,
      speed: TOURISM_SPEED,
      loop: false,
      label: (tm) => date(motion.monthIso(Math.min(Math.floor(tm), last()))),
      status(tm) {
        const k = idx(tm);
        const n = k >= 0 ? doc.tourism.national[k] : null;
        return n == null ? "" : t.plural(n, { one: "{n} night", other: "{n} nights" }, { n: int(n) });
      },
      active: () => app.state.lens === tLens,
      load,
      draw(ctx, vp, tm) {
        takeWanted("tourism-monthly");
        const k = idx(tm);
        if (k < 0 || k === shown && tLens.values === arr) return 0;
        shown = k;
        const row = doc.tourism.per_resident[k];
        for (let i = 0; i < size; i++) arr[i] = owner[i] >= 0 ? row[owner[i]] ?? null : null;
        tLens.values = arr;
        recolour(app, tLens);
        return 0;
      },
      hit(mx, my) {
        if (!doc || shown < 0) return null;
        const cell = app.cellAt(mx, my);
        const o = cell >= 0 ? owner[cell] : -1;
        if (o < 0) return null;
        const nights = doc.tourism.nights[shown][o], per = doc.tourism.per_resident[shown][o];
        const month = date(doc.tourism.months[shown]);
        return {
          html: `<b>${esc(app.w.raw.states[o].name)}</b><br>${esc(month)}: ${nights == null ? esc(t("no data"))
            : t.plural(nights, { one: "{n} night", other: "{n} nights" }, { n: `<b>${int(nights)}</b>` })}${
            per == null ? "" : `<br>${esc(t("{v} per resident", { v: num(per, 2) }))}`}`,
        };
      },
    });
    app.on("lens", (l) => {
      if (l === tLens) wanted.set("tourism-monthly", reduce() ? last() : first());
      else if (tLens.values !== own) { tLens.values = own; shown = -1; }
    });
  }

  // ---- smog week ---------------------------------------------------------------------------------------------
  const sLens = app.lensById.get("smog_week");
  if (sLens) {
    const own = sLens.values;
    const arr = new Array(size).fill(null);
    let doc = null, shown = -1, loading = null;
    const h0 = motion.hour(sLens.time?.start);
    const n = sLens.time?.hours || 168;
    const peak = h0 + (sLens.time?.shown ?? 0);
    const load = () => (loading ??= app.loadData("smog").then((d) => {
      if (d?.cells?.length && d.values?.length) doc = d;
    }));
    const hi = (th) => Math.max(0, Math.min(n - 1, Math.floor(th) - h0));
    motion.register({
      id: "smog-week",
      name: t("Smog week"),
      data: "smog",
      axis: "hour",
      range: [h0, h0 + n - 1],
      get start() { return reduce() ? peak : h0; },
      step: 1,
      speed: SMOG_SPEED,
      loop: false,
      label: (th) => hourLabel(h0 + hi(th)),
      status(th) {
        const v = doc?.national_hourly?.[hi(th)];
        return v == null ? "" : t("Poland average {v} µg/m³", { v: int(v) });
      },
      active: () => app.state.lens === sLens,
      load,
      draw(ctx, vp, th) {
        takeWanted("smog-week");
        if (!doc) return 0;
        const k = hi(th);
        if (k === shown && sLens.values === arr) return 0;
        shown = k;
        arr.fill(null);
        const row = doc.values[k], cells = doc.cells;
        for (let j = 0; j < cells.length; j++) arr[cells[j]] = row[j];
        sLens.values = arr;
        recolour(app, sLens);
        return 0;
      },
      hit(mx, my) {
        if (!doc || shown < 0) return null;
        const cell = app.cellAt(mx, my);
        if (cell < 0 || owner[cell] < 0) return null;
        const v = arr[cell];
        const x = app.w.grid.cx(cell), y = app.w.grid.cy(cell);
        const near = doc.stations
          .map((s) => ({ s, d: Math.hypot(s.x - x, s.y - y), v: s.pm25[shown] }))
          .filter((e) => e.d <= STATION_KM && e.v != null)
          .sort((a, b) => a.d - b.d)
          .slice(0, 3);
        const lines = [`<b>${esc(placeOf(app, cell, t))}</b>`,
          `${esc(hourLabel(h0 + shown))}: <b>${v == null ? esc(t("no data")) : `${int(v)} µg/m³`}</b>`];
        if (near.length) {
          lines.push(`<span class="muted">${esc(t("Nearest stations"))}</span>`);
          for (const e of near) {
            lines.push(`${esc(e.s.name)}: <b>${int(e.v)}</b> µg/m³ <span class="muted">· ${esc(t("{km} km", { km: num(e.d, 0) }))}</span>`);
          }
        } else if (v == null) {
          lines.push(`<span class="muted">${esc(t("No station within {km} km", { km: STATION_KM }))}</span>`);
        }
        return { html: lines.join("<br>") };
      },
    });
    app.on("lens", (l) => {
      if (l === sLens) wanted.set("smog-week", reduce() ? peak : h0);
      else if (sLens.values !== own) { sLens.values = own; shown = -1; }
    });
  }

  // ---- presidential vote over time ---------------------------------------------------------------------------
  const vIds = ["vote_2015", "vote_2020", "vote"];
  const vYears = [2015, 2020, 2025];
  const vLenses = vIds.map((id) => app.lensById.get(id));
  if (vLenses.every(Boolean)) {
    const own = vLenses.map((l) => l.values);
    const blend = new Array(size).fill(null);
    let doc = null, loading = null, shownQ = null, switching = false;
    const isVote = (l) => vLenses.includes(l);
    const restore = () => vLenses.forEach((l, k) => { l.values = own[k]; });
    const frameOf = (k) => doc?.elections?.frames?.find((f) => f.year === vYears[k]) || null;
    const load = () => (loading ??= app.loadData("timelapse").then((d) => { doc = d; }));
    const quant = (tt) => Math.round(tt / VOTE_STEP) * VOTE_STEP;
    const atRunoff = (q) => vYears.findIndex((y) => Math.abs(q - y) < 1e-6);
    motion.register({
      id: "vote-morph",
      name: t("Presidential vote over time"),
      data: "timelapse",
      axis: "year",
      range: [vYears[0], vYears[vYears.length - 1]],
      get start() {
        const k = vLenses.indexOf(app.state.lens);
        return k >= 0 ? vYears[k] : vYears[vYears.length - 1];
      },
      step: 0.5, // the scrubber can rest half way between two runoffs
      speed: VOTE_SPEED,
      loop: false,
      label(tt) {
        const q = quant(tt), k = atRunoff(q);
        if (k >= 0) return String(vYears[k]);
        const { i } = voteSegment(vYears, q);
        return `${vYears[i]}-${vYears[i + 1]}`;
      },
      status(tt) {
        const k = atRunoff(quant(tt));
        const f = k >= 0 ? frameOf(k) : null;
        return f?.share == null ? "" : `${f.candidate} ${pct(f.share, 2)}`;
      },
      active: () => isVote(app.state.lens),
      load,
      draw(ctx, vp, tt) {
        takeWanted("vote-morph");
        const q = quant(tt);
        const { i, f } = voteSegment(vYears, q);
        const target = vLenses[i];
        if (q === shownQ && app.state.lens === target) return 0;
        shownQ = q;
        let values;
        if (f === 0) values = own[i];
        else {
          const a = own[i], b = own[i + 1];
          for (let c = 0; c < size; c++) {
            const va = a[c], vb = b[c];
            blend[c] = va == null ? vb : vb == null ? va : va + (vb - va) * f;
          }
          values = blend;
        }
        vLenses.forEach((l, k) => { l.values = k === i ? values : own[k]; });
        if (app.state.lens !== target) {
          switching = true;
          try { app.setLens(target); } finally { switching = false; }
          drawLegendHist(app, target);
        } else recolour(app, target);
        return 0;
      },
      hit(mx, my) {
        const cell = app.cellAt(mx, my);
        if (cell < 0 || owner[cell] < 0) return null;
        const q = quant(motion.clock.axis === "year" ? motion.clock.t : vYears[vYears.length - 1]);
        const { i, f } = voteSegment(vYears, q);
        const lines = [`<b>${esc(placeOf(app, cell, t))}</b>`];
        vYears.forEach((y, k) => {
          const v = own[k][cell];
          const fr = frameOf(k);
          const who = fr ? esc(fr.candidate) : esc(t(vLenses[k].unit));
          const txt = `${y} · ${who}: ${v == null ? esc(t("no data")) : pct(v, 1)}`;
          lines.push((k === i && f === 0) || (f > 0 && (k === i || k === i + 1)) ? `<b>${txt}</b>` : `<span class="muted">${txt}</span>`);
        });
        return { html: lines.join("<br>") };
      },
    });
    app.on("lens", (l) => {
      if (switching) return;
      if (isVote(l)) {
        restore();
        shownQ = null;
        wanted.set("vote-morph", vYears[vLenses.indexOf(l)]);
      } else {
        restore();
        shownQ = null;
      }
    });
  }

  app.timelapse = { hourLabel, voteSegment };
}

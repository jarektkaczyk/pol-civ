// Population years for the density and change lenses: 2015 to 2025 (31 December) and June 2026, on the shared
// motion clock (app.motion, year axis). Picking either lens plays the years from the first to June 2026 in the clock
// bar (play, pause, speed, scrubber); there is no second control row in the legend. The URL keeps the clock value
// (#t=2019); an old link with #year=2019 still opens that year.
//
// Data: timeline.json (pipeline/build/timeline.py), loaded when a population lens is first opened. It holds per-date
// integer arrays for the Polish land cells; they are decoded once into full per-cell arrays, so a new year only
// swaps the lens's `values` for a ready array (no allocation per step) and asks main to recolour the map.
//
// Without the motion engine (it failed to load) the legend keeps its own row: a play button and a year slider.
import { t, date } from "../../i18n.js";
import { drawLegendHist } from "../timelapse/legend.js";

const LENSES = new Set(["density", "growth"]);
const FIRST = { density: 0, growth: 1 }; // change since 2015 starts with 2016
const STEP_MS = 750;
const SPEED = 1; // years per second on the clock at 1x

const CSS = `
.tl-row { display: flex; align-items: center; gap: 8px; margin: 6px 0 2px; }
.tl-row .tl-play { flex: none; width: 26px; height: 26px; border-radius: 50%; border: 1px solid var(--line);
  background: rgba(201,164,92,.14); color: var(--gold-bright); font-size: 11px; line-height: 1; cursor: pointer; padding: 0; }
.tl-row .tl-play:hover { background: rgba(201,164,92,.28); }
.tl-row input[type=range] { flex: 1; min-width: 0; accent-color: #c9a45c; height: 22px; margin: 0; }
.tl-row .tl-year { flex: none; min-width: 66px; text-align: right; font-family: var(--serif); color: var(--gold-bright);
  font-size: 16px; font-variant-numeric: tabular-nums; }
`;

function addCss() {
  if (document.getElementById("tl-css")) return;
  const st = document.createElement("style");
  st.id = "tl-css";
  st.textContent = CSS;
  document.head.appendChild(st);
}

function decode(doc, size) {
  const out = {};
  for (const key of LENSES) {
    const k = doc.scale?.[key] || 1;
    out[key] = (doc[key] || []).map((arr) => {
      const full = new Array(size).fill(null);
      doc.cells.forEach((cell, j) => {
        const v = arr[j];
        full[cell] = v == null ? null : v / k;
      });
      return full;
    });
  }
  return out;
}

export function install(app) {
  const motion = app.motion || null;
  if (!motion) addCss();
  const legend = document.getElementById("legend");
  const size = app.w.grid.size;
  let doc = null, arrays = null, loading = null;
  let lens = null; // the population lens shown, or null
  const original = new Map(); // lens id -> its own values (the newest year)
  let idx = null; // date index shown, or null = the lens's own date
  let pendingYear = null; // year from the URL before the data arrived
  let wantYear = null; // clock year to seek to once the population layer has the clock
  let timer = 0;
  let row = null;

  const ownIndex = (l) => (doc ? doc.dates.indexOf(doc.lens_dates?.[l.id]) : -1);
  const shownIndex = () => (idx == null && lens ? ownIndex(lens) : idx);
  const yearKey = (k) => doc.dates[k].slice(0, 4);
  // The clock's year axis: 2015 ... 2025 are those 31 Decembers, 2026 is 30 June 2026 (the last date).
  const yearOf = (k) => +doc.dates[k].slice(0, 4);
  const firstYear = () => (doc && lens ? yearOf(FIRST[lens.id] ?? 0) : 2015);
  const lastYear = () => (doc ? yearOf(doc.dates.length - 1) : 2026);
  const indexOfYear = (y) => {
    if (!doc) return -1;
    const k = doc.dates.findIndex((d) => +d.slice(0, 4) === Math.floor(y));
    return k < 0 ? -1 : Math.max(FIRST[lens?.id] ?? 0, k);
  };

  function ensure() {
    if (doc || loading) return loading;
    loading = app.loadData("timeline").then((d) => {
      if (!d || !Array.isArray(d.dates)) return;
      doc = d;
      arrays = decode(d, size);
      if (pendingYear != null) setYear(pendingYear, { fromUrl: true });
      render();
    }, (err) => console.warn("timeline: timeline.json failed to load", err));
    return loading;
  }

  // Recolour the map for date index k (null = the lens's own values).
  function apply() {
    if (!lens || !arrays) return;
    if (!original.has(lens.id)) original.set(lens.id, lens.values);
    const own = ownIndex(lens);
    lens.values = idx == null || idx === own ? original.get(lens.id) : arrays[lens.id][idx];
    app.setBand(app.state.band);
    app.invalidate();
    drawLegendHist(app, lens);
    update();
  }

  function restore(l) {
    if (l && original.has(l.id)) l.values = original.get(l.id);
  }

  function setYear(y, { fromUrl = false } = {}) {
    if (!doc) { pendingYear = y; return; }
    pendingYear = null;
    if (motion) {
      // The clock owns the year: a URL year becomes a seek once the population layer has the clock.
      if (y != null) wantYear = Math.min(lastYear(), Math.max(firstYear(), +y));
      app.requestDraw();
      return;
    }
    if (y == null) { idx = null; apply(); return; }
    const first = FIRST[lens?.id] ?? 0;
    const k = doc.dates.findIndex((d) => d.slice(0, 4) === String(y));
    if (k < 0) return;
    idx = Math.max(first, k);
    apply();
    if (!fromUrl) app.hash.update();
  }

  // --- the motion clock ----------------------------------------------------------------------------------------
  if (motion) {
    motion.register({
      id: "population",
      name: t("Population over time"),
      data: "timeline",
      axis: "year",
      get range() { return [firstYear(), lastYear()]; },
      get start() { return motion.reducedMotion ? lastYear() : firstYear(); },
      step: 1,
      speed: SPEED,
      loop: false,
      label: (y) => {
        const k = indexOfYear(y);
        return k < 0 ? String(Math.floor(y)) : date(doc.labels[k]); // "2019", or "2026-06" -> June 2026
      },
      active: () => !!lens,
      load: () => ensure(),
      draw(ctx, vp, y) {
        if (wantYear != null && motion.clock.layer === "population") {
          const w = wantYear;
          wantYear = null;
          motion.clock.seek(w);
          return 0;
        }
        const k = indexOfYear(y);
        if (k < 0 || k === shownIndex()) return 0;
        idx = k;
        apply();
        return 0;
      },
    });
  }

  // --- the legend row (only without the motion engine) ---------------------------------------------------------
  function stop() {
    clearTimeout(timer);
    timer = 0;
    update();
  }
  function play() {
    if (motion) { motion.clock.play(); return; }
    if (!doc || !lens) return;
    const first = FIRST[lens.id] ?? 0, last = doc.dates.length - 1;
    if (shownIndex() >= last) { idx = first; apply(); }
    const tick = () => {
      const k = shownIndex();
      if (k >= last) { stop(); app.hash.update(); return; }
      idx = k + 1;
      apply();
      timer = setTimeout(tick, STEP_MS);
    };
    timer = setTimeout(tick, STEP_MS / 2);
    update();
  }

  function update() {
    if (!row || !doc || !lens) return;
    const k = shownIndex();
    row.querySelector("input").value = String(k);
    row.querySelector(".tl-year").textContent = date(doc.labels[k]); // "2025", or an ISO month such as "2026-06"
    const btn = row.querySelector(".tl-play");
    btn.textContent = timer ? "❚❚" : "▶";
    btn.setAttribute("aria-label", timer ? t("Pause") : t("Play the years"));
  }

  function render() {
    if (!legend) return;
    if (motion || !lens || !doc || legend.hidden) { row?.remove(); return; }
    if (!row) {
      row = document.createElement("div");
      row.className = "tl-row";
      row.innerHTML = `<button class="tl-play" type="button" aria-label="${t("Play the years")}">▶</button>
        <input type="range" step="1" aria-label="${t("Year")}">
        <span class="tl-year" aria-live="polite"></span>`;
      row.querySelector(".tl-play").onclick = () => (timer ? stop() : play());
      row.querySelector("input").oninput = (e) => {
        const k = +e.target.value; // read before stop(): it redraws the row and resets the slider to the shown year
        stop();
        idx = k;
        apply();
        app.hash.update();
      };
    }
    const input = row.querySelector("input");
    input.min = String(FIRST[lens.id] ?? 0);
    input.max = String(doc.dates.length - 1);
    if (!legend.contains(row)) {
      const anchor = legend.querySelector(".ticks");
      if (anchor) anchor.after(row); else legend.appendChild(row);
      if (idx != null) drawLegendHist(app, lens);
    }
    update();
  }

  // The lens dock rebuilds the legend's HTML (lens change, details toggle): put the row back, and redraw the
  // histogram of the year shown (the dock draws the lens's own year).
  if (legend) new MutationObserver(() => {
    if (!lens || !doc) return;
    if (row && !motion && !legend.contains(row)) render();
    if (idx != null && idx !== ownIndex(lens)) drawLegendHist(app, lens);
  }).observe(legend, { childList: true });

  app.on("lens", (l) => {
    const was = lens;
    if (lens && lens !== l) { stop(); restore(lens); }
    const keep = lens && l && LENSES.has(l.id) ? idx : null; // keep the year when switching between the two
    lens = l && LENSES.has(l.id) ? l : null;
    idx = null;
    if (!lens) { row?.remove(); app.hash.update(); return; }
    // A fresh pick plays from the first year (the year axis is shared with other layers); a switch between the
    // two population lenses keeps the year on the clock.
    if (motion && !was) wantYear = motion.reducedMotion ? 2026 : (FIRST[lens.id] ? 2016 : 2015);
    ensure()?.then(() => {
      if (keep != null && lens) {
        if (motion) { idx = Math.max(FIRST[lens.id] ?? 0, keep); apply(); } else setYear(yearKey(keep));
      }
      render();
    });
    render();
  });

  app.hash.register("year", {
    // With the motion clock the year lives in #t=; #year= is only read, for old links.
    get: () => (!motion && lens && doc && idx != null && idx !== ownIndex(lens) ? yearKey(idx) : null),
    set: (v) => {
      const y = v == null ? null : parseInt(v, 10);
      if (y == null || !Number.isFinite(y)) { if (lens && !motion) setYear(null); else pendingYear = null; return; }
      if (!lens) { pendingYear = y; return; }
      setYear(y, { fromUrl: true });
    },
  });

  // A link opened with a population lens already on (the lens was set before this extension installed).
  const cur = app.state.lens;
  if (cur && LENSES.has(cur.id)) {
    lens = cur;
    ensure();
  }
  app.timeline = { setYear, play, stop, get doc() { return doc; }, get index() { return shownIndex(); } };
}

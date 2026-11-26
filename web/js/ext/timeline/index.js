// Time slider for the population lenses (density and change since 2015): a row in the lens legend with a play button
// and a year slider, 2015 to 2025 (31 December) and June 2026. The URL keeps the year (#year=2019).
//
// Data: timeline.json (pipeline/build/timeline.py), loaded when a population lens is first opened. It holds per-date
// integer arrays for the Polish land cells; they are decoded once into full per-cell arrays, so moving the slider only
// swaps the lens's `values` for a ready array (no allocation per step) and asks main to recolour the map.
import { lensScale } from "../../world.js";
import { rampColor, parseHex } from "../../color.js";
import { t, date } from "../../i18n.js";

const LENSES = new Set(["density", "growth"]);
const FIRST = { density: 0, growth: 1 }; // change since 2015 starts with 2016
const STEP_MS = 750;
const BINS = 40; // as the legend histogram in ui/lenses.js

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
  addCss();
  const legend = document.getElementById("legend");
  const size = app.w.grid.size;
  let doc = null, arrays = null, loading = null;
  let lens = null; // the population lens shown, or null
  const original = new Map(); // lens id -> its own values (the newest year)
  let idx = null; // date index shown, or null = the lens's own date
  let pendingYear = null; // year from the URL before the data arrived
  let timer = 0;
  let row = null;

  const ownIndex = (l) => (doc ? doc.dates.indexOf(doc.lens_dates?.[l.id]) : -1);
  const shownIndex = () => (idx == null && lens ? ownIndex(lens) : idx);
  const yearKey = (k) => doc.dates[k].slice(0, 4);

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
    drawHist();
    update();
  }

  function restore(l) {
    if (l && original.has(l.id)) l.values = original.get(l.id);
  }

  function setYear(y, { fromUrl = false } = {}) {
    if (!doc) { pendingYear = y; return; }
    pendingYear = null;
    if (y == null) { idx = null; apply(); return; }
    const first = FIRST[lens?.id] ?? 0;
    let k = doc.dates.findIndex((d) => d.slice(0, 4) === String(y));
    if (k < 0) return;
    idx = Math.max(first, k);
    apply();
    if (!fromUrl) app.hash.update();
  }

  // The legend histogram is cached per lens by ui/lenses.js; redraw it for the year shown.
  function drawHist() {
    const cv = legend?.querySelector(".lg-hist");
    if (!cv || !lens?.ramp) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = cv.clientWidth || 256, cssH = cv.clientHeight || 38;
    if (cv.width !== Math.round(cssW * dpr)) cv.width = Math.round(cssW * dpr);
    if (cv.height !== Math.round(cssH * dpr)) cv.height = Math.round(cssH * dpr);
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    const counts = new Array(BINS).fill(0);
    const scale = lensScale(lens);
    const owner = app.w.raw.owner;
    for (let i = 0; i < lens.values.length; i++) {
      const v = lens.values[i];
      if (v == null || owner[i] < 0) continue;
      const tv = scale(v);
      if (!Number.isFinite(tv)) continue;
      counts[Math.max(0, Math.min(BINS - 1, Math.floor(tv * BINS)))]++;
    }
    const max = Math.max(1, ...counts);
    const stops = lens.ramp.map(parseHex);
    const bw = cssW / BINS;
    for (let b = 0; b < BINS; b++) {
      if (!counts[b]) continue;
      const hh = Math.max(1.5, Math.sqrt(counts[b] / max) * (cssH - 2));
      const [r, g, bl] = rampColor(stops, (b + 0.5) / BINS);
      ctx.fillStyle = `rgb(${r | 0},${g | 0},${bl | 0})`;
      ctx.fillRect(b * bw + 0.5, cssH - hh, Math.max(1, bw - 1), hh);
    }
    ctx.fillStyle = "rgba(201,164,92,.45)";
    ctx.fillRect(0, cssH - 1, cssW, 1);
  }

  function stop() {
    clearTimeout(timer);
    timer = 0;
    update();
  }
  function play() {
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
    if (!lens || !doc || legend.hidden) { row?.remove(); return; }
    if (!row) {
      row = document.createElement("div");
      row.className = "tl-row";
      row.innerHTML = `<button class="tl-play" type="button" aria-label="${t("Play the years")}">▶</button>
        <input type="range" step="1" aria-label="${t("Year")}">
        <span class="tl-year" aria-live="polite"></span>`;
      row.querySelector(".tl-play").onclick = () => (timer ? stop() : play());
      row.querySelector("input").oninput = (e) => {
        stop();
        idx = +e.target.value;
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
      if (idx != null) drawHist();
    }
    update();
  }

  // The lens dock rebuilds the legend's HTML (lens change, details toggle): put the row back each time.
  if (legend) new MutationObserver(() => { if (lens && doc && row && !legend.contains(row)) render(); })
    .observe(legend, { childList: true });

  app.on("lens", (l) => {
    if (lens && lens !== l) { stop(); restore(lens); }
    const keep = lens && l && LENSES.has(l.id) ? idx : null; // keep the year when switching between the two
    lens = l && LENSES.has(l.id) ? l : null;
    idx = null;
    if (!lens) { row?.remove(); app.hash.update(); return; }
    ensure()?.then(() => {
      if (keep != null && lens) setYear(yearKey(keep));
      render();
    });
    render();
  });

  app.hash.register("year", {
    get: () => (lens && doc && idx != null && idx !== ownIndex(lens) ? yearKey(idx) : null),
    set: (v) => {
      const y = v == null ? null : parseInt(v, 10);
      if (y == null || !Number.isFinite(y)) { if (lens) setYear(null); else pendingYear = null; return; }
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

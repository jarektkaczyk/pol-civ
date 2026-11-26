// Anonymous, cookieless usage counts (PostHog EU). Loaded by index.html and by every atlas page.
//
//   track(name, props)   queue an event; a no-op when analytics is off. Props are small enums and numbers only:
//                        never names of people, free text the user typed, or anything that identifies a visitor.
//
// Nothing loads when config.js has no POSTHOG_KEY, on localhost, 127.0.0.1 or file:, or under automation
// (navigator.webdriver). The PostHog script is fetched after the first map frame (app) or after the load event
// (atlas pages). It keeps state in memory only (no cookies, no localStorage), never records sessions, never
// autocaptures clicks and never calls identify. Add ?analytics=debug to a URL to print each event to the console.
//
// In the app, most events come from the extension API (window.__app events) and a few delegated DOM listeners, so
// the modules that own those actions stay untouched. Search and the Explorer call track() directly.
import { POSTHOG_KEY, POSTHOG_HOST, POSTHOG_ASSETS } from "./config.js";

const CONFIG = {
  api_host: POSTHOG_HOST,
  persistence: "memory",
  cookieless_mode: "always",
  disable_session_recording: true,
  autocapture: false,
  capture_pageview: true,
  capture_pageleave: true,
  disable_surveys: true,
  person_profiles: "identified_only",
};

const loc = globalThis.location || { protocol: "file:", hostname: "", search: "", hash: "" };
const debug = /[?&]analytics=debug\b/.test(loc.search || "");
const LOCAL = /^(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)$/;
const blocked = () => loc.protocol === "file:" || LOCAL.test(loc.hostname || "") || !!globalThis.navigator?.webdriver;
const enabled = !!POSTHOG_KEY && !blocked();
const entryHash = String(loc.hash || "");
let ph = null; // the PostHog stub (queues calls until the script arrives), then the real client
let loading = false;
const last = new Map(); // event name -> {sig, t}: drops exact repeats within a short window

const slug = (s) => String(s || "").replace(/ł/g, "l").replace(/Ł/g, "L").normalize("NFD").replace(/[̀-ͯ]/g, "")
  .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

function clean(props) {
  const out = {};
  for (const [k, v] of Object.entries(props || {})) {
    if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
    else if (typeof v === "boolean") out[k] = v;
    else if (typeof v === "string" && v) out[k] = v.slice(0, 64);
  }
  return out;
}

/** Record one event. Safe to call anywhere, any time; never throws. */
export function track(name, props = {}, { dedupeMs = 1500 } = {}) {
  try {
    const p = clean(props);
    const sig = JSON.stringify(p);
    const now = Date.now();
    const prev = last.get(name);
    if (prev && prev.sig === sig && now - prev.t < dedupeMs) return;
    last.set(name, { sig, t: now });
    if (debug) console.info("[analytics]", name, p);
    if (!enabled) return;
    stub().capture(name, p);
  } catch {
    /* analytics must never break the page */
  }
}

// The documented PostHog snippet, minus its inline script: a queue that array.js replays on load.
function stub() {
  if (ph) return ph;
  const q = [];
  q.__SV = 1;
  q._i = [[POSTHOG_KEY, CONFIG, "posthog"]];
  q.people = [];
  for (const m of ["capture", "register", "register_once", "unregister", "opt_out_capturing", "opt_in_capturing"]) {
    q[m] = (...args) => { q.push([m, ...args]); };
  }
  globalThis.posthog = q;
  ph = q;
  return q;
}

function load() {
  if (!enabled || loading) return;
  loading = true;
  stub();
  const s = document.createElement("script");
  s.src = `${POSTHOG_ASSETS}/static/array.js`;
  s.async = true;
  s.crossOrigin = "anonymous";
  s.onload = () => { if (globalThis.posthog && !Array.isArray(globalThis.posthog)) ph = globalThis.posthog; };
  document.head.appendChild(s);
}

const idle = (fn) => (globalThis.requestIdleCallback ? requestIdleCallback(fn, { timeout: 3000 }) : setTimeout(fn, 1200));

function viewportClass() {
  const w = globalThis.innerWidth || 0;
  return w <= 700 ? "phone" : w <= 1100 ? "tablet" : "desktop";
}

/** What a landing URL's hash asks for: the most specific key wins. */
export function entryKind(hash) {
  const p = new URLSearchParams(String(hash || "").replace(/^#/, ""));
  if (p.get("view") === "city" && p.get("city")) return "city_view";
  if (p.get("advisor")) return "advisor";
  if (p.get("city")) return "city";
  if (p.get("state")) return "state";
  if (p.get("lens")) return "lens";
  if (p.get("layers")) return "layers";
  if (p.get("at")) return "camera";
  return "none";
}

function watchApp() {
  const ready = () => globalThis.__app && !document.getElementById("loading");
  const go = () => {
    const app = globalThis.__app;
    requestAnimationFrame(() => {
      const kind = entryKind(entryHash);
      track("app_loaded", { ms: Math.round(performance.now()), viewport: viewportClass(), entry: kind });
      if (kind !== "none") track("deep_link_landing", { kind });
      idle(load);
    });
    app.on("lens", (lens) => { if (lens?.id) track("lens_opened", { lens: lens.id }); });
    app.on("mode", (e) => {
      if (e?.name === "city") {
        const city = app.cityById?.get(e.params?.id) || app.state?.selectedCity;
        track("city_view_opened", { town: slug(city?.name) || String(e.params?.id || "") });
      } else if (e?.name === "advisor") {
        track("advisor_opened", { advisor: e.params?.id || "council" });
      }
    });
    // The Almanac opens from several places; every path goes through pedia.open.
    const pedia = app.pedia;
    if (pedia && typeof pedia.open === "function") {
      const open = pedia.open.bind(pedia);
      pedia.open = (page, ...rest) => {
        track("almanac_opened", { page: page || "About this map" });
        return open(page, ...rest);
      };
    }
    document.addEventListener("click", (e) => {
      const t = e.target instanceof Element ? e.target : null;
      if (!t) return;
      const nav = t.closest("#pedia-nav button[data-page]");
      if (nav) track("almanac_opened", { page: nav.dataset.page });
      if (t.closest("#btn-share")) track("share_clicked", {});
      const res = t.closest("#btn-res");
      const row = t.closest("#map-layers-pop [data-toggle]");
      if (res || row) {
        // after the app's own handler has flipped the switch
        setTimeout(() => {
          if (res) track("map_layer_toggled", { layer: "resources", on: !!app.state?.showResources }, { dedupeMs: 0 });
          else {
            const id = row.dataset.toggle;
            const on = app.ui?.mapToggles?.().find((x) => x.id === id)?.on;
            track("map_layer_toggled", { layer: id, on: !!on }, { dedupeMs: 0 });
          }
        }, 0);
      }
    }, true);
  };
  if (ready()) return go();
  const mo = new MutationObserver(() => {
    if (ready()) {
      mo.disconnect();
      go();
    }
  });
  mo.observe(document.body, { childList: true });
}

function start() {
  if (typeof document === "undefined") return;
  const atlas = document.querySelector('meta[name="pc-atlas"]')?.content;
  if (atlas) {
    const [kind, page] = atlas.split(":");
    track("atlas_page_view", { kind, page });
    const later = () => idle(load);
    if (document.readyState === "complete") later();
    else addEventListener("load", later, { once: true });
    return;
  }
  if (document.getElementById("map")) watchApp();
}

start();

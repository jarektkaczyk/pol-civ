// Money for local governments: what the state transfers to every gmina, powiat and voivodeship in one year
// (money.json, Ministry of Finance): the shares in PIT and CIT and the general subsidy. Gold dots flow from the state
// budget (Warszawa) to each local government, as many as its amount. Local governments with a wealth correction
// ("korekta z tytulu zamoznosci") receive less; they carry a red ring and the card gives the amount. Hover or tap a
// local government for its figures; select a town or a voivodeship to see only its flows.
//
// Clock: the "live" axis (one year, no scrubber); the dots move while the clock plays.
import { esc } from "../../format.js";
import { t, money as zl, zloty, ROOT } from "../../i18n.js";
import { showHtmlTooltip } from "../../ui/tooltip.js";

const DOTS = 2400; // dots on the move over all local governments
const KM_PER_S = 70; // dot speed, map km per second
const BEND = 0.12; // sideways bow of a flow, as a share of its length
const GOLD = "#ffd27a";
const LESS = "#ffb070"; // flows to the local governments with a wealth correction

/** A stable 0..1 number for (seed, slot, trip). */
function rand(seed, i, k) {
  let h = Math.imul(seed ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(i + 1, 0xc2b2ae35) ^ Math.imul(k + 7, 0x27d4eb2f);
  h ^= h >>> 15;
  h = Math.imul(h, 0x2c1b3c6d);
  h ^= h >>> 12;
  return (h >>> 0) / 4294967296;
}

export function prepare(doc) {
  const st = doc.state || {};
  const units = (doc.units || []).filter((u) => u.x != null && u.y != null && u.total != null);
  const sum = units.reduce((s, u) => s + u.total, 0) || 1;
  const per = sum / DOTS; // zloty per dot
  for (const u of units) {
    const dx = u.x - st.x, dy = u.y - st.y;
    const len = Math.hypot(dx, dy);
    u.qx = (st.x + u.x) / 2 + dy * BEND;
    u.qy = (st.y + u.y) / 2 - dx * BEND;
    u.len = len * 1.02 + 1;
    u.slots = Math.max(1, Math.ceil(u.total / per));
    u.want = u.total / (u.slots * per);
  }
  return { doc, st, units, per, sum, year: doc.year };
}

const sprites = new Map();
function dotSprite(color, px, dpr) {
  const d = Math.max(2, Math.round(px * 2) / 2);
  const key = `${color}|${d}|${dpr}`;
  let c = sprites.get(key);
  if (c) return c;
  const r = d / 2 + 2;
  c = document.createElement("canvas");
  c.width = c.height = Math.ceil(2 * r * dpr);
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  const grad = g.createRadialGradient(r, r, d / 2, r, r, r);
  grad.addColorStop(0, "rgba(255,210,122,.45)");
  grad.addColorStop(1, "rgba(255,210,122,0)");
  g.fillStyle = grad;
  g.beginPath();
  g.arc(r, r, r, 0, Math.PI * 2);
  g.fill();
  g.beginPath();
  g.arc(r, r, d / 2 + 0.6, 0, Math.PI * 2);
  g.fillStyle = "rgba(40,20,0,.8)";
  g.fill();
  g.beginPath();
  g.arc(r, r, d / 2, 0, Math.PI * 2);
  g.fillStyle = color;
  g.fill();
  c.css = 2 * r;
  if (sprites.size > 100) sprites.clear();
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
  let model = null;
  let loading = null;
  let focus = null; // {codes: Set} or {prefix} or null (all)
  let version = 0;

  const ensure = () => {
    if (model) return Promise.resolve(model);
    loading ??= app.loadData("money").then((d) => {
      if (!d || !Array.isArray(d.units) || !d.state) return null;
      model = prepare(d);
      version++;
      app.requestDraw();
      return model;
    });
    return loading;
  };

  const unitOn = (u) => !focus || (focus.codes ? focus.codes.has(u.code) : u.code.startsWith(focus.prefix));
  const shownTotal = () => model.units.reduce((s, u) => s + (unitOn(u) ? u.total : 0), 0);

  function drawDots(ctx, vp, ts, o) {
    const { cam, dpr } = vp;
    const s = cam.scale, cx = cam.w / 2 - cam.x * s, cy = cam.h / 2 - cam.y * s;
    const pad = 10 / s;
    const px = Math.max(2.4, Math.min(5, 2 + o.Rpx * 0.12));
    const gold = dotSprite(GOLD, px, dpr), less = dotSprite(LESS, px, dpr);
    const { st } = model;
    let drawn = 0;
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    for (let k = 0; k < model.units.length; k++) {
      const u = model.units[k];
      if (!unitOn(u)) continue;
      const x0 = Math.min(st.x, u.x, u.qx), x1 = Math.max(st.x, u.x, u.qx);
      const y0 = Math.min(st.y, u.y, u.qy), y1 = Math.max(st.y, u.y, u.qy);
      if (x1 < vp.x0 - pad || x0 > vp.x1 + pad || y1 < vp.y0 - pad || y0 > vp.y1 + pad) continue;
      const travel = u.len / KM_PER_S;
      const phase = ts / travel;
      const img = u.correction ? less : gold;
      for (let i = 0; i < u.slots; i++) {
        const p = phase + i / u.slots + (rand(k, i, -1) * 0.6) / u.slots;
        const trip = Math.floor(p);
        if (rand(k, i, trip) >= u.want) continue;
        const f = p - trip, g = 1 - f;
        const x = g * g * st.x + 2 * g * f * u.qx + f * f * u.x;
        const y = g * g * st.y + 2 * g * f * u.qy + f * f * u.y;
        if (x < vp.x0 - pad || x > vp.x1 + pad || y < vp.y0 - pad || y > vp.y1 + pad) continue;
        ctx.drawImage(img, x * s + cx - img.css / 2, y * s + cy - img.css / 2, img.css, img.css);
        drawn++;
      }
    }
    ctx.restore();
    return drawn;
  }

  motion.register({
    id: "money",
    name: t("Money for local governments"),
    data: "money",
    axis: "live",
    range: null,
    speed: 1,
    z: 25,
    label: () => (model ? String(model.year) : ""),
    status: () => (model ? t("{n} from the state", { n: zl(shownTotal()) }) : ""),
    active: () => on,
    load: ensure,
    filter(sel) {
      if (sel?.kind === "city" && sel.city?.gmina) {
        const g = sel.city.gmina;
        focus = { codes: new Set([g, g.slice(0, 4), g.slice(0, 2)]) };
      } else if (sel?.kind === "state" && sel.state?.fips) {
        focus = { prefix: sel.state.fips };
      } else focus = null;
      version++;
      app.requestDraw();
    },
    draw(ctx, vp, ts, o) {
      if (!model) return 0;
      return drawDots(ctx, vp, ts, o);
    },
  });

  // --- static art: a marker at every local government -------------------------------------------------------------
  const markR = (u, Rpx) => {
    const base = u.level === "voivodeship" ? 5 : u.level === "powiat" ? 2.4 : 1.1;
    return (base + Math.sqrt(u.total) / 12000) * Math.max(0.7, Math.min(1.8, Rpx / 10));
  };
  app.registerStaticLayer({
    id: "money-units", z: 67,
    visible: () => on && !!model,
    sig: () => `v${version}`,
    draw(ctx, vp, w, o) {
      for (const u of model.units) {
        if (!unitOn(u)) continue;
        if (u.x < vp.x0 || u.x > vp.x1 || u.y < vp.y0 || u.y > vp.y1) continue;
        const r = markR(u, o.Rpx) / vp.s;
        ctx.beginPath();
        ctx.arc(u.x, u.y, r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255,214,130,.85)";
        ctx.fill();
        ctx.lineWidth = 0.8 / vp.s;
        ctx.strokeStyle = "rgba(40,20,0,.8)";
        ctx.stroke();
        if (u.correction) {
          ctx.beginPath();
          ctx.arc(u.x, u.y, r + 2 / vp.s, 0, Math.PI * 2);
          ctx.lineWidth = Math.max(1.4, Math.min(3.5, 1 + Math.sqrt(u.correction) / 6000)) / vp.s;
          ctx.strokeStyle = "#e0584f";
          ctx.stroke();
        }
      }
      const { st } = model;
      ctx.beginPath();
      ctx.arc(st.x, st.y, 7 / vp.s, 0, Math.PI * 2);
      ctx.lineWidth = 2.4 / vp.s;
      ctx.strokeStyle = "#ffd27a";
      ctx.stroke();
    },
    hit(x, y, Rpx) {
      if (!model) return null;
      const s = app.cam.scale;
      let best = null, bd = Infinity;
      for (const u of model.units) {
        if (!unitOn(u)) continue;
        const d = Math.hypot(u.x - x, u.y - y);
        const lim = (markR(u, Rpx) + 5) / s;
        // a gmina wins over the powiat or voivodeship drawn at the same place
        const score = d + (u.level === "gmina" ? 0 : 0.5 / s);
        if (d <= lim && score < bd) { bd = score; best = u; }
      }
      return best ? { unit: best } : null;
    },
    tooltip: (it) => unitCard(it.unit),
    click(it, ev) {
      if (ev.pointerType !== "mouse") showHtmlTooltip(ev.x, ev.y, unitCard(it.unit));
      return true;
    },
  });

  const KIND = {
    get gmina() { return t("gmina"); },
    get city_powiat() { return t("city with powiat rights"); },
    get powiat() { return t("powiat"); },
    get voivodeship() { return t("voivodeship"); },
  };
  function unitCard(u) {
    const row = (label, v) => `<br>${esc(label)} <b>${esc(zloty(v))}</b>`;
    return `<b>${esc(u.name)}</b> <span class="muted">${esc(KIND[u.kind] || "")}, ${esc(String(model.year))}</span>`
      + row(t("PIT share"), u.pit) + row(t("CIT share"), u.cit) + row(t("General subsidy"), u.subsidy)
      // The ministry's amounts due are already after the correction: it is shown as part of them, not to subtract.
      + (u.correction ? `<br>${esc(t("Wealth correction (already included)"))} <b>-${esc(zloty(u.correction))}</b>` : "")
      + row(t("Total from the state"), u.total);
  }

  app.ui.addMapToggle({
    id: "money", label: t("Money for local governments"), icon: "y-gold", default: false,
    title: t("State money for every gmina, powiat and voivodeship"),
    get: () => on,
    set: (v) => {
      on = !!v;
      if (on) ensure();
      app.requestDraw();
    },
  });
  app.money = {
    get model() { return model; },
    unitCard: (code) => {
      const u = model?.units.find((x) => x.code === code);
      return u ? unitCard(u) : null;
    },
  };
}

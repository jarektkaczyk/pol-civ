// Moving commuters on the commuter arcs (a motion layer on the "day" axis). Dots stream from the home gminas into
// each of the 12 cities in the morning and back in the afternoon, more of them on the larger flows. The census gives
// the number of commuters but not the hours they travel: the daily shape below is for show, and commuting.json
// `rules` says so for the Almanac.
//
// Budget: the slots of all arcs add up to about DOTS; at the peak of the morning nearly all are on screen at the
// country view. A slot holds one dot per trip; dots leave the start only while the hour's share is above zero.
import { t as tr } from "../../i18n.js";

const DAY = 86400;
const DOTS = 1400; // slots over all arcs (morning and evening sets each)
const SPEED = 25 / 3600; // km per clock second: a slow, readable pace
const MORNING = [5 * 3600, 9 * 3600];
const EVENING = [15 * 3600, 18 * 3600];
const START = 6 * 3600 + 30 * 60;

/** 0..1: a smooth bump over [a, b] (sin^2), 0 outside. */
export function bump(t, [a, b]) {
  const s = ((t % DAY) + DAY) % DAY;
  if (s <= a || s >= b) return 0;
  const f = Math.sin((Math.PI * (s - a)) / (b - a));
  return f * f;
}

export function registerCommuterMotion(app, { active, model, load, filter }) {
  const motion = app.motion;
  if (!motion) return null;
  let flows = null; // [{arc, am, pm}]
  let builtFor = null;
  let lastSel = null;
  const morning = (t) => bump(t, MORNING);
  const evening = (t) => bump(t, EVENING);

  function build(m) {
    const total = m.arcs.reduce((s, a) => s + a.value, 0) || 1;
    const perSlot = total / DOTS;
    flows = m.arcs.map((a, k) => {
      const slots = Math.max(1, Math.round(a.value / perSlot));
      const opts = { slots, speed: SPEED, shape: "dot", seed: 101 + k };
      return {
        arc: a,
        am: motion.particles(a.pts, { ...opts, dir: 1 }),
        pm: motion.particles(a.pts, { ...opts, seed: 7001 + k, dir: -1 }),
      };
    });
    builtFor = m;
  }

  return motion.register({
    id: "commuters",
    name: tr("Commuters"),
    data: "commuting",
    axis: "day",
    range: [0, DAY],
    step: 60,
    speed: 1440,
    start: START,
    z: 10,
    label: (t) => motion.hhmm(t),
    active,
    load: async () => {
      await load();
      if (lastSel) filter(lastSel);
    },
    filter(sel) {
      lastSel = sel;
      filter(sel);
    },
    draw(ctx, vp, t, o) {
      const m = model();
      if (!m) return 0;
      if (builtFor !== m) build(m);
      const am = morning(t), pm = evening(t);
      // Nothing leaves outside the commuting hours, but dots already on their way finish the trip.
      if (am === 0 && pm === 0 && morning(t - 4 * 3600) === 0 && evening(t - 4 * 3600) === 0) return 0;
      const focus = app.commuting?.focus || null;
      const size = Math.max(3, Math.min(6, 2.4 + o.Rpx * 0.15));
      let n = 0;
      for (const f of flows) {
        if (focus && f.arc.city.id !== focus) continue;
        n += f.am.draw(ctx, vp, t, { density: morning, size, color: "#ffd27a" });
        n += f.pm.draw(ctx, vp, t, { density: evening, size, color: "#ffb36b" });
      }
      return n;
    },
  });
}

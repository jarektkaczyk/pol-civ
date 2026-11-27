// Moving freight wagons on the trade routes (a motion layer on the "day" axis, the same clock as the commuters).
// Each train of wagons stands for the same tonnage on every route, so the busier routes carry more trains; half run
// each way, a little apart. Speed and the time of day are for show; trade.json `rules` says so for the Almanac.
// At the country view only the routes the static layer draws there carry wagons, two boxes per train.
import { OVERVIEW_ROUTES } from "../../render/art/improvements.js";
import { t } from "../../i18n.js";

const TRAINS = 150; // trains over all routes (both directions)
const SPEED = 50 / 3600; // km per clock second
const DAY = 86400;
const WAGON = "#2b1d12"; // dark boxes with a parchment rim read on the red and white rail dashes

export function registerTradeMotion(app, { model, on }) {
  const motion = app.motion;
  if (!motion) return null;
  let flows = null;
  let builtFor = null;

  function build(routes) {
    const total = routes.reduce((s, rt) => s + (rt.route.value_kt ?? rt.route.tons_k ?? 0), 0) || 1;
    const perTrain = total / TRAINS;
    flows = routes.map((rt, k) => {
      const v = rt.route.value_kt ?? rt.route.tons_k ?? 0;
      const half = Math.max(1, Math.round(v / perTrain / 2));
      const opts = { slots: half, speed: SPEED, shape: "wagon" };
      return {
        rt,
        ab: motion.particles(rt.pts, { ...opts, seed: 300 + k, dir: 1 }),
        ba: motion.particles(rt.pts, { ...opts, seed: 900 + k, dir: -1 }),
      };
    });
    builtFor = routes;
  }

  return motion.register({
    id: "trade",
    name: t("Trade routes"),
    data: "trade",
    axis: "day",
    range: [0, DAY],
    step: 60,
    speed: 1440,
    start: 6 * 3600 + 30 * 60,
    z: 20,
    label: (t) => motion.hhmm(t),
    active: () => !!on.trade,
    load: () => app.loadData("trade"),
    draw(ctx, vp, t, o) {
      const routes = model.routes || [];
      if (!routes.length) return 0;
      if (builtFor !== routes) build(routes);
      const overview = o.Rpx < 8;
      const cars = overview ? 2 : o.Rpx < 20 ? 3 : 4;
      const size = overview ? 3.2 : Math.min(5, 3 + o.Rpx * 0.06);
      const off = overview ? 0 : size * 0.9;
      let n = 0;
      for (let k = 0; k < flows.length; k++) {
        if (overview && k >= OVERVIEW_ROUTES) break;
        const f = flows[k];
        n += f.ab.draw(ctx, vp, t, { size, cars, color: WAGON, offset: off });
        n += f.ba.draw(ctx, vp, t, { size, cars, color: WAGON, offset: off });
      }
      return n;
    },
  });
}

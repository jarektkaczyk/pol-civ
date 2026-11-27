// Extension loader. Each entry is a folder under web/js/ext/ whose index.js exports install(app) (sync or async).
// `app` is the API object built in main.js (also window.__app). A missing folder is fine: it is reported with
// console.info and skipped, so an extension can be left out without breaking the app. A failing install() is logged
// as an error and does not stop the others. Modules are fetched in parallel and installed in list order.
// layers/: static map layers (roads, rail, ports, forts, wonders, trade routes) and their toggles.
// economy/: the "Made in Poland" and "Tech and games" site layers and their toggles.
// credit/: the OpenStreetMap credit in a map corner, fading after a few seconds or at the first map interaction.
// motion/: the shared clock for animated layers (app.motion) and the Animations panel in the lens dock; it installs
// first so the others can register on it.
// timeline/, timelapse/: the population years, tourist nights by month, the smog week and the presidential vote
// over time (lenses that play on the motion clock).
// permits/: the time-lapse of permits for new factories and warehouses (a motion layer).
// trains/, flights/: a day of passenger trains and a year of air routes (motion layers).
// power/, migration/, money/: the grid every 15 minutes, moves between voivodeships, state money for local
// governments (motion layers).
const MODULES = ["./credit/index.js", "./motion/index.js", "./cityView/index.js", "./advisors/index.js", "./layers/index.js", "./history/index.js", "./commuting/index.js", "./timeline/index.js", "./timelapse/index.js", "./economy/index.js", "./permits/index.js", "./trains/index.js", "./flights/index.js", "./power/index.js", "./migration/index.js", "./money/index.js"];

export async function installExtensions(app, list = MODULES) {
  const loads = list.map((spec) => import(spec).then((m) => ({ m }), (err) => ({ err })));
  const installed = [];
  for (let k = 0; k < list.length; k++) {
    const spec = list[k];
    const { m, err } = await loads[k];
    if (err) {
      console.info(`extension ${spec} not loaded (${err.message || err})`);
      continue;
    }
    if (typeof m.install !== "function") {
      console.info(`extension ${spec} has no install(app); skipped`);
      continue;
    }
    try {
      await m.install(app);
      installed.push(spec);
    } catch (e) {
      console.error(`extension ${spec} failed to install`, e);
    }
  }
  app.extensions = installed;
  app.emit?.("extensions", installed);
  return installed;
}

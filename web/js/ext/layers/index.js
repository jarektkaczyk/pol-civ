// Map-art extension: Polish motorways, expressways, railways, ports and airports,
// military forts and restricted ground, wonders and protected land, and freight trade routes, each as a static layer
// drawn into the cached map (nothing animates; an idle map draws no frames), with a switch in the "Map" menu.
//
// Data: infrastructure.json, military.json, wonders.json and trade.json (loaded eagerly by main.js right after the
// first frame; app.loadData returns the same promise). A missing file (null) leaves its layers off and their switches
// harmless. Defaults: roads, rail, ports & airports, military and wonders on (roads, rail and hubs only from the region
// view in: see each layer's minRpx), trade routes off.
import { createModel } from "./model.js";
import { makeLayers } from "./layers.js";
import { tips } from "./tips.js";
import { t } from "../../i18n.js";

const TOGGLES = [
  { id: "roads", label: t("Roads"), icon: "t-road", def: true, title: t("Motorways and expressways"), layers: ["roads"] },
  { id: "rail", label: t("Railways"), icon: "t-rail", def: true, title: t("Main and secondary railway lines"), layers: ["rail"] },
  { id: "hubs", label: t("Ports & airports"), icon: "d-harbor", def: true, title: t("Polish seaports and passenger airports"), layers: ["hubs"] },
  { id: "military", label: t("Military"), icon: "m-army", def: true, title: t("Garrisons and main training areas"), layers: ["forts", "restricted", "plates"] },
  { id: "wonders", label: t("Heritage"), icon: "w-landmark", def: true, title: t("World Heritage, memorials, parks, universities and landmarks"), layers: ["wonders", "protected", "plates"] },
  { id: "trade", label: t("Trade routes"), icon: "t-trade", def: false, title: t("The 30 largest regional freight flows at least 100 km apart"), layers: ["trade"] },
];

export function install(app) {
  const model = createModel(app.w);
  const on = Object.fromEntries(TOGGLES.map((tg) => [tg.id, tg.def]));
  const layers = makeLayers(model, on, { tips, app });
  for (const l of layers) app.registerStaticLayer(l);

  for (const tg of TOGGLES) {
    app.ui.addMapToggle({
      id: tg.id, label: tg.label, icon: tg.icon, title: tg.title, default: tg.def,
      get: () => on[tg.id],
      set: (v) => {
        on[tg.id] = !!v;
        app.requestDraw();
      },
    });
  }

  const apply = (name, data) => {
    model.setData(name, data);
    app.requestDraw();
  };
  for (const name of ["infrastructure", "military", "wonders", "trade"]) {
    if (app.data[name] !== undefined) apply(name, app.data[name]);
    else app.loadData(name).then((d) => apply(name, d), (err) => console.warn(`map layers: ${name} failed to load`, err));
  }

  // For debugging and the gallery: the model and switches.
  app.mapArt = { model, on, layers };
}

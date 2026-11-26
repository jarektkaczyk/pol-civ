// City View data model: everything the city screen and its map layer show, derived from cities.json,
// nation.json, lenses.json, world.json and resources.json. Pure functions over app.data / app.w (no DOM).
import { t, int, num } from "../../i18n.js";

// PKD section key (nation.json industries) -> short label and district colour (the medallion behind its icon).
export const INDUSTRY = {
  agriculture: { short: t("Agriculture"), color: "#4f7a2a" },
  mining: { short: t("Mining"), color: "#6a5038" },
  manufacturing: { short: t("Manufacturing"), color: "#9a5a22" },
  energy: { short: t("Power & heat"), color: "#2a5f86" },
  water: { short: t("Water & waste"), color: "#2f6f7a" },
  construction: { short: t("Construction"), color: "#8a5426" },
  trade: { short: t("Trade"), color: "#8a6a1e" },
  transport: { short: t("Transport"), color: "#3d5f73" },
  accommodation: { short: t("Hospitality"), color: "#6e3a5e" },
  information: { short: t("IT & telecoms"), color: "#25557e" },
  finance: { short: t("Finance"), color: "#7a6420" },
  real_estate: { short: t("Real estate"), color: "#6b4a2f" },
  professional: { short: t("Professional"), color: "#2b4f8a" },
  admin: { short: t("Business services"), color: "#4b5a68" },
  public_admin: { short: t("Public admin"), color: "#3a5a4a" },
  education: { short: t("Education"), color: "#2a3f7a" },
  health: { short: t("Health care"), color: "#7a2f2f" },
  arts: { short: t("Arts"), color: "#5b3a7e" },
  other: { short: t("Other services"), color: "#4b4b4b" },
};
// Icon id (icons.js i-<key>); sections without their own icon borrow the nearest one.
const ICON_ALIAS = { energy: "utilities", water: "utilities", trade: "retail", transport: "transportation", government: "public_admin" };
export const industryIcon = (k) => `i-${ICON_ALIAS[k] || k}`;

// Land-use groups shown as a hex's "tile yield" (world.json pct keys -> group). Cover ids give the map colour.
export const LAND = [
  { key: "built", label: t("Built-up"), icon: "l-developed", cover: 9, keys: ["developed"] },
  { key: "farm", label: t("Farmland"), icon: "l-farmland", cover: 7, keys: ["crop", "pasture"] },
  { key: "forest", label: t("Forest"), icon: "l-forest", cover: 3, keys: ["forest"] },
  { key: "open", label: t("Open land"), icon: null, cover: 4, keys: ["grass", "shrub", "wetland"] },
];

const sum = (o) => Object.values(o || {}).reduce((a, v) => a + (Number.isFinite(v) ? v : 0), 0);
const HEX_AREA = (R) => (3 * Math.sqrt(3) / 2) * R * R; // km2 of one hex

/** Jobs by PKD section (city.jobs, workers by employer seat) with location quotients against Poland. */
export function jobIndustries(city, nation) {
  const n = nation.nation;
  const total = sum(city.jobs) || city.employed || 1;
  const nTotal = sum(n.jobs) || n.employed || 1;
  return Object.entries(city.jobs || {})
    .filter(([, v]) => Number.isFinite(v) && v > 0)
    .map(([key, jobs]) => {
      const share = jobs / total;
      const natShare = (n.jobs?.[key] || 0) / nTotal;
      return {
        key, jobs, share, natShare, lq: natShare > 0 ? share / natShare : null,
        label: nation.industries?.[key] ? t(nation.industries[key]) : key, short: INDUSTRY[key]?.short || key,
        color: INDUSTRY[key]?.color || "#3a4a5e", icon: industryIcon(key),
      };
    })
    .sort((a, b) => b.jobs - a.jobs);
}

/**
 * Towns below the powiat (city.jobs is {}): workers by yield (Food, Production, Science, Culture, all workers),
 * plus the rest of the town's workers as one row. Shares and quotients against Poland's yields.
 */
export function yieldIndustries(city, nation) {
  const n = nation.nation;
  const total = city.employed;
  const nTotal = n.employed;
  if (!(total > 0) || !(nTotal > 0)) return [];
  const rows = [];
  let used = 0, nUsed = 0;
  for (const y of nation.yields || []) {
    if (y.unit !== "workers") continue;
    const v = city.yields?.[y.key];
    if (!Number.isFinite(v)) continue;
    const nv = n.yields?.[y.key] || 0;
    used += v;
    nUsed += nv;
    const share = v / total, natShare = nv / nTotal;
    rows.push({
      key: y.key, jobs: v, share, natShare, lq: natShare > 0 && v > 0 ? share / natShare : null,
      label: t(y.label), short: t(y.label), color: y.color, icon: y.icon, yieldDef: y,
    });
  }
  if (!rows.length) return [];
  const rest = total - used;
  if (rest > 0) {
    rows.push({
      key: "rest", jobs: rest, share: rest / total, natShare: Math.max(0, nTotal - nUsed) / nTotal, lq: null,
      label: t("Trade, services and public sector"), short: t("Services"), color: "#4b5a68", icon: "i-other",
    });
  }
  return rows.sort((a, b) => b.jobs - a.jobs);
}

function landOf(w, cell) {
  if (!w.pct) return null;
  let best = null, tot = 0;
  for (const g of LAND) {
    const v = g.keys.reduce((a, k) => a + (w.pct[k]?.[cell] || 0), 0);
    tot += v;
    if (!best || v > best.share) best = { ...g, share: v };
  }
  if (!best || tot <= 0) return null;
  return { ...best, share: best.share / 100 };
}

/**
 * Everything the City View shows for one city.
 * Per footprint hex: estimated residents (lens "density" value x hex area: an estimate, not a count) and the
 * dominant land-use group with its share of the hex's land.
 */
export function buildModel(app, city) {
  const { w } = app;
  const { nation, cities, resources, lenses } = app.data;
  const grid = w.grid;
  const N = cities.length;
  const owner = w.raw.owner;
  const stateIdx = city.cell != null ? owner[city.cell] : -1;
  const stateRGB = w.stateColor[stateIdx] || [201, 164, 92];

  const footprint = (Array.isArray(city.footprint) && city.footprint.length ? city.footprint : [city.cell])
    .filter((c) => c != null && c >= 0);
  const mask = new Set(footprint);

  // Resource sites of the town (resources.json items tagged with its id in `cbsa` or `city`), biggest first per type.
  const items = resources?.items || [];
  const typeById = new Map((resources?.types || []).map((ty) => [ty.id, ty]));
  const sites = [];
  items.forEach((it, index) => {
    if (it.cbsa === city.id || it.city === city.id) sites.push({ item: it, index, type: typeById.get(it.type) || null });
  });
  const catRank = { energy: 0, mineral: 1, agri: 2 };
  sites.sort((a, b) => (catRank[a.type?.category] ?? 3) - (catRank[b.type?.category] ?? 3)
    || (b.item.value ?? 0) - (a.item.value ?? 0));
  const siteCells = new Map(); // cell -> [site]
  for (const s of sites) {
    if (s.item.cell == null) continue;
    if (!siteCells.has(s.item.cell)) siteCells.set(s.item.cell, []);
    siteCells.get(s.item.cell).push(s);
  }

  // Per-hex tile yields.
  const density = lenses?.lenses?.find((l) => l.id === "density");
  const area = HEX_AREA(grid.R);
  const tiles = footprint.map((cell) => {
    const d = density?.values?.[cell];
    return {
      cell, x: grid.cx(cell), y: grid.cy(cell),
      residents: Number.isFinite(d) ? d * area : null,
      land: landOf(w, cell),
      isCity: cell === city.cell,
    };
  });

  // Jobs by PKD section (cities with powiat rights) or by yield (other towns). The map's districts are the real ones
  // from districts.json, placed by placeDistricts() once that file arrives; until then there are none.
  const jobsBySection = jobIndustries(city, nation);
  const inds = jobsBySection.length ? jobsBySection : yieldIndustries(city, nation);
  // District plaques go on footprint hexes near the centre that have no resource site and no other city; the rest
  // (small towns) sit in a row inside the city's own hex.
  const cx = grid.cx(city.cell), cy = grid.cy(city.cell);
  // The city's banner stands over the hexes just north of it, so those come after the other near hexes.
  const R = grid.R;
  const cost = (c) => {
    const dx = grid.cx(c) - cx, dy = grid.cy(c) - cy;
    return Math.hypot(dx, dy) + (dy < -0.5 * R && dy > -3.2 * R && Math.abs(dx) < 3 * R ? 3 * R : 0);
  };
  const free = footprint
    .filter((c) => c !== city.cell && !siteCells.has(c) && !w.cityByCell.has(c))
    .sort((a, b) => cost(a) - cost(b) || a - b);

  // Bounding box of the footprint (km).
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const c of footprint) {
    const x = grid.cx(c), y = grid.cy(c);
    x0 = Math.min(x0, x - grid.R); x1 = Math.max(x1, x + grid.R);
    y0 = Math.min(y0, y - grid.R); y1 = Math.max(y1, y + grid.R);
  }

  const peers = (city.peers || []).map((id) => app.cityById.get(id)).filter(Boolean);
  const states = (city.states || []).map((abbr) => {
    const i = w.raw.states.findIndex((s) => s.abbr === abbr);
    return { abbr, index: i, name: i >= 0 ? (app.data.states?.[i]?.name || w.raw.states[i].name) : abbr };
  });
  const residentsSum = tiles.reduce((a, tile) => a + (tile.residents || 0), 0);

  return {
    city, N, nation, stateIdx, hexArea: area, stateRGB, states, footprint, mask, tiles, residentsSum,
    sites, siteCells, inds, indsBySection: jobsBySection.length > 0, free, districts: [], placed: [], inCity: [],
    bbox: Number.isFinite(x0) ? { x0, y0, x1, y1 } : null,
    peers,
  };
}

/**
 * Put the town's districts on the map (schematic positions): the first ones on the free footprint hexes nearest
 * the city, the rest in a row inside the city's own hex. list = [{id, short, mapLq, color, icon, ...}] (districts.js
 * cityDistricts). Sets m.districts, m.placed and m.inCity; the map layer reads them on its next frame.
 */
export function placeDistricts(m, list) {
  const ds = (list || []).map((d) => ({ ...d, lq: d.mapLq ?? null }));
  m.districts = ds;
  m.placed = [];
  m.inCity = [];
  ds.forEach((d, k) => {
    if (k < m.free.length) m.placed.push({ ...d, cell: m.free[k] });
    else m.inCity.push(d);
  });
}

/** Population series [{year, value}] from pop_series (null years dropped). */
export function popSeries(city) {
  const s = city.pop_series;
  if (!s || typeof s !== "object") return [];
  return Object.entries(s)
    .filter(([, v]) => Number.isFinite(v))
    .map(([y, v]) => ({ year: +y, value: v }))
    .sort((a, b) => a.year - b.year);
}

/** How many cities have a non-null rank for this key (the "of N"). */
export function rankCount(cities, key) {
  let n = 0;
  for (const c of cities) if (c.ranks?.[key] != null) n++;
  return n;
}

/** A resource value with its unit, short ("3.9 GW", "878 workers"). */
export function resourceValue(item, type, compact) {
  const v = item.value;
  if (!Number.isFinite(v)) return "";
  const u = type?.unit || "";
  if (u === "MW") return v >= 1000 ? `${num(v / 1000, v >= 10000 ? 0 : 1)} GW` : `${int(v)} MW`;
  if (u === "employees") return t.plural(Math.abs(v) >= 1e4 ? 1e6 : Math.round(v),
    { one: "{n} worker", other: "{n} workers" }, { n: compact(v) });
  if (/tons/.test(u)) return t("{n} t/yr", { n: compact(v) });
  if (/km\u00b2/.test(u)) return t("{n} km\u00b2 play", { n: compact(v) });
  return `${compact(v)} ${u ? t(u) : ""}`.trim();
}

/**
 * A resource item's detail line in the page language: status, operator and status note joined with " - " (the
 * file's `detail` is the English join of the same parts). Items without the parts keep `detail`.
 */
export function siteDetail(item) {
  if (!item) return "";
  if (item.status_label == null && item.status_note == null) return item.detail || "";
  return [item.status_label ? t(item.status_label) : "", item.operator || "", item.status_note ? t(item.status_note) : ""]
    .filter(Boolean).join(" - ");
}

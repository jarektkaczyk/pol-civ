// The advisors' data model: "levels" (voivodeships, metros, powiaty, gminas, towns) of rows with typed fields, plus
// the links between rows and the hex map (row -> highlight, cell -> row). Built once from app.data (counties.json
// optional: the gmina level and the gmina roll-ups need it).
//
//   level = {id, label, noun, rows: [row], fields: [field], field(key), value(row, key),
//            highlight(rows, opts) -> app.state.highlight, rowAtCell(cell) -> row | null, focus(row), byKey: Map}
//   row   = {key, name, sub, full?, level, ref, v: {fieldKey: value}}
//   field = {key, label, format, unit, higher_is, source, description, lens?, group, derived?}
//
// Shared keys across levels: population, growth, gdp, gdp_pc, wage, unemployment, pit, workers, y_<yield>.
import { fin, ratio } from "./util.js";
import { frameBox } from "./frame.js";
import { t, date, num } from "../../../i18n.js";

// counties.json / powiaty.json metric key -> lenses.json lens id.
const COUNTY_LENS = {
  population: "density", density: "density", median_age: "age", growth: "growth", net_migration: "migration", elderly: "elderly",
  births: "births", ukrainians: "ukrainians", pit: "income", wage: "wage", unemployment: "unemployment", dwellings: "dwellings",
  higher_ed: "higher_ed", students: "students", tourism: "tourism", doctors: "doctors", life_f: "life_f", life_m: "life_m",
  catholic: "catholic", no_religion: "no_religion", mass: "mass", president_2025: "vote", turnout_2025: "turnout",
  sejm_2023: "sejm", pm25: "pm25", flood_2024: "flood", forest: "forest", farmland: "farmland", developed: "developed",
};
// Gmina metrics that the economic shape already carries for voivodeships, metros and towns (no roll-up needed).
const OWN = new Set(["population", "area_km2", "density", "growth", "pit", "wage", "unemployment", "workers", "gdp", "cell"]);
// A null means "none here" (no university): it counts as zero in a roll-up.
const ZERO_NULL = new Set(["students"]);
// Shares of land: weighted by area, not by people.
const BY_AREA = new Set(["forest", "farmland", "developed"]);
// Roll-ups that only approximate the area's own figure (a median, a station reading, a vote share weighted by
// residents rather than voters, a diocese figure).
const APPROX = new Set(["median_age", "pm25", "mass", "president_2025", "turnout_2025"]);
const GROUP_NAME = {
  people: t("People"), prosperity: t("Prosperity"), knowledge: t("Knowledge"), life: t("Daily life"), faith: t("Faith"), vote: t("Vote"),
  air: t("Air"), hazards: t("Hazards"), land: t("Land"),
};
const ALMOST = "\u2248"; // the approximately-equal sign, shown after a rolled-up label

const LAND_KEYS = ["forest", "crop", "pasture", "grass", "shrub", "wetland", "developed"];
export const LAND_LABEL = {
  forest: t("Forest"), crop: t("Cropland"), pasture: t("Meadow & pasture"), grass: t("Mountain meadow"), shrub: t("Scrub"), wetland: t("Wetland"), developed: t("Built-up"),
};
// One sentence per cover type (the Polish names take different cases).
const LAND_DESC = {
  forest: t("Share of the land in forest (ESA WorldCover, mean over the voivodeship's hexes)."),
  crop: t("Share of the land in cropland (ESA WorldCover, mean over the voivodeship's hexes)."),
  pasture: t("Share of the land in meadow & pasture (ESA WorldCover, mean over the voivodeship's hexes)."),
  grass: t("Share of the land in mountain meadow (ESA WorldCover, mean over the voivodeship's hexes)."),
  shrub: t("Share of the land in scrub (ESA WorldCover, mean over the voivodeship's hexes)."),
  wetland: t("Share of the land in wetland (ESA WorldCover, mean over the voivodeship's hexes)."),
  developed: t("Share of the land in built-up (ESA WorldCover, mean over the voivodeship's hexes)."),
};
export const LAND_COLOR = {
  forest: "#3f7a3a", crop: "#d2c457", pasture: "#93b852", grass: "#b9b06a", shrub: "#c9a874", wetland: "#4f9a86", developed: "#9a8f9e",
};
export { LAND_KEYS };

const F = (key, label, format, o = {}) => ({ key, label, format, unit: o.unit || null, higher_is: o.higher_is || "neutral", source: o.source || "", description: o.description || "", lens: o.lens || null, group: o.group || t("Economy"), derived: !!o.derived });

/** Column-oriented file ({columns, rows}) -> [{r, i, get(key)}]. */
function columnRows(file) {
  if (!file || !Array.isArray(file.columns) || !Array.isArray(file.rows)) return [];
  const col = Object.fromEntries(file.columns.map((k, j) => [k, j]));
  return file.rows.map((r, i) => ({ r, i, get: (k) => (col[k] == null ? null : r[col[k]] ?? null) }));
}

export function buildData(app) {
  const { cities = [], states = [], nation = {}, counties, powiaty, resources, sources = [] } = app.data;
  const metroFile = app.data.metros;
  const metroList = Array.isArray(metroFile?.metros) ? metroFile.metros : Array.isArray(metroFile) ? metroFile : [];
  const w = app.w;
  const grid = w.grid;
  const owner = w.raw.owner;
  const countyOf = w.raw.county || [];
  const worldCounties = w.raw.counties || [];
  const n = grid.size;

  // --- cell indexes ---------------------------------------------------------------------------------------------
  const stateCells = new Map();
  const countyCells = new Map(); // world county (gmina) index -> cells
  const powiatCells = new Map(); // powiat code -> cells
  for (let i = 0; i < n; i++) {
    const o = owner[i];
    if (!(o >= 0)) continue;
    if (!stateCells.has(o)) stateCells.set(o, []);
    stateCells.get(o).push(i);
    const c = countyOf[i];
    if (c >= 0) {
      if (!countyCells.has(c)) countyCells.set(c, []);
      countyCells.get(c).push(i);
      const pc = worldCounties[c]?.powiat || String(worldCounties[c]?.geoid || "").slice(0, 4);
      if (pc) {
        if (!powiatCells.has(pc)) powiatCells.set(pc, []);
        powiatCells.get(pc).push(i);
      }
    }
  }
  // cell -> metro: footprints, smaller metros first so a bigger metro's majority wins; then every metro's own cell.
  const cellMetro = new Map();
  for (let k = metroList.length - 1; k >= 0; k--) for (const cell of metroList[k].footprint || []) cellMetro.set(cell, metroList[k]);
  for (const m of metroList) if (m.cell != null) cellMetro.set(m.cell, m);
  // cell -> town, the same way (towns are sorted by population).
  const cellTown = new Map();
  for (let k = cities.length - 1; k >= 0; k--) for (const cell of cities[k].footprint || []) cellTown.set(cell, cities[k]);
  for (const c of cities) if (c.cell != null) cellTown.set(c.cell, c);

  const srcTitle = new Map(sources.map((s) => [s.id, s]));
  const nat = nation.nation || {};
  const yrs = nation.years || {};
  const vintage = nation.vintage || "GUS";
  const countyVintage = counties?.vintage || vintage;
  const growthYears = (nat.growth_years || [2015, 2025]).join("-");
  const stateName = new Map((Array.isArray(states) ? states : []).map((s) => [s.abbr, s.name]));
  const cityById = app.cityById || new Map(cities.map((c) => [c.id, c]));

  // --- economic fields (voivodeships, metros, towns) ------------------------------------------------------------
  const yieldsWorkers = (nation.yields || []).filter((y) => y.unit !== "pln" && y.unit !== "usd");
  // Years go into t() as strings: a number var is grouped (2,024).
  const Y = (v, d) => String(v || d);
  const gdpDesc = {
    states: t("Gross domestic product in current złoty, published per voivodeship (GUS regional accounts, {year}).", { year: Y(yrs.gdp_voiv, 2024) }),
    metros: t("Gross domestic product in current złoty: the member gminas' shares of their powiaty's GDP (Eurostat NUTS 3 {year}, shared by wage bill and workers). An estimate.", { year: Y(yrs.gdp_nuts3, 2023) }),
    towns: t("Gross domestic product in current złoty: the town's gmina share of its powiat's GDP (Eurostat NUTS 3 {year}). An estimate.", { year: Y(yrs.gdp_nuts3, 2023) }),
  };
  const wageYear = { year: Y(yrs.wage, 2026) }, unempYear = { year: Y(yrs.unemployment, 2026) };
  const wageDesc = {
    states: t("Average gross monthly wage by employer seat (GUS, {year}). Published per powiat; the voivodeship shows the mean of its powiaty weighted by workers.", wageYear),
    metros: t("Average gross monthly wage by employer seat (GUS, {year}). Published per powiat; the metro area shows the mean of its powiaty weighted by workers.", wageYear),
    towns: t("Average gross monthly wage by employer seat (GUS, {year}). Published per powiat; a town shows its powiat.", wageYear),
  };
  const unempDesc = {
    states: t("Registered unemployment rate (GUS, {year}). Published per powiat; the voivodeship shows the mean of its powiaty weighted by population.", unempYear),
    metros: t("Registered unemployment rate (GUS, {year}). Published per powiat; the metro area shows the mean of its powiaty weighted by population.", unempYear),
    towns: t("Registered unemployment rate (GUS, {year}). Published per powiat; a town shows its powiat.", unempYear),
  };
  const econFields = (lv) => [
    F("population", t("Population"), "int", { unit: t("people"), source: "pl_stats_population", group: t("People"), lens: "density", description: t("Residents on {date} (GUS).", { date: date(nation.population_date || `${Y(yrs.population, 2025)}-12-31`) }) }),
    F("growth", t("Change {years}", { years: growthYears }), "signed", { unit: t("population change"), source: "pl_stats_population", group: t("People"), lens: "growth", description: t("Population change {years} on today's borders (GUS).", { years: growthYears }) }),
    F("gdp", t("GDP"), "money", { unit: t("zł per year"), source: "pl_gdp", description: gdpDesc[lv] }),
    F("gdp_pc", t("GDP per person"), "pln", { unit: t("zł per resident"), higher_is: "good", source: "pl_gdp", description: t("GDP divided by residents (GDP {gdpYear}, population {popYear}).", { gdpYear: lv === "states" ? Y(yrs.gdp_voiv, 2024) : Y(yrs.gdp_nuts3, 2023), popYear: Y(yrs.population, 2025) }), derived: true }),
    F("wage", t("Average wage"), "pln", { unit: t("zł gross per month"), higher_is: "good", source: "pl_stats_labour", group: t("Prosperity"), lens: "wage", description: wageDesc[lv] }),
    F("unemployment", t("Unemployment"), "pct", { unit: t("registered rate"), higher_is: "bad", source: "pl_stats_labour", group: t("Prosperity"), lens: "unemployment", description: unempDesc[lv] }),
    F("pit", t("PIT per person"), "pln", { unit: t("zł per resident"), higher_is: "good", source: "pl_stats_prosperity", group: t("Prosperity"), lens: "income", description: t("Personal income tax revenue planned for {year} by the gminas, divided by their residents (Ministry of Finance).", { year: Y(yrs.pit, 2026) }) }),
    F("workers", t("Workers"), "int", { unit: t("people, by employer seat"), source: "pl_stats_labour", description: t("People working, counted where their employer is (GUS, {date}).", { date: date(`${Y(yrs.workers, 2025)}-12-31`) }) }),
    ...yieldsWorkers.map((y) => F(`y_${y.key}`, t("{label} workers", { label: t(y.label) }), "int", { unit: t("workers"), source: "pl_stats_labour", group: t("Yields"), description: t(y.description) })),
  ];
  const econValues = (o) => ({
    population: o.population ?? null,
    growth: o.growth ?? null,
    gdp: o.gdp ?? o.yields?.gold ?? null,
    gdp_pc: ratio(o.gdp ?? o.yields?.gold, o.population),
    wage: o.wage ?? null,
    unemployment: o.unemployment ?? null,
    pit: o.pit_per_person ?? null,
    workers: o.employed ?? null,
    ...Object.fromEntries(yieldsWorkers.map((y) => [`y_${y.key}`, o.yields?.[y.key] ?? null])),
  });

  // --- gmina roll-ups to voivodeships and metros ------------------------------------------------------------------
  const cFields = counties?.fields || [];
  const ROLL = cFields.filter((f) => ["pct", "float", "years", "int"].includes(f.format) && !OWN.has(f.key)).map((f) => f.key);
  const cRows = columnRows(counties);
  const roll = { states: new Map(), metros: new Map() };
  const add = (map, key, g) => {
    if (key == null) return;
    let a = map.get(key);
    if (!a) map.set(key, (a = { pop: 0, area: 0, s: {}, wt: {} }));
    const pop = g.get("population"), ar = g.get("area_km2");
    if (fin(pop)) a.pop += pop;
    if (fin(ar)) a.area += ar;
    for (const k of ROLL) {
      let v = g.get(k);
      if (v == null && ZERO_NULL.has(k)) v = 0;
      const wgt = BY_AREA.has(k) ? ar : pop;
      if (fin(v) && fin(wgt) && wgt > 0) {
        a.s[k] = (a.s[k] || 0) + v * wgt;
        a.wt[k] = (a.wt[k] || 0) + wgt;
      }
    }
  };
  for (const g of cRows) {
    add(roll.states, g.get("state"), g);
    add(roll.metros, g.get("cbsa"), g);
  }
  const rolled = (map, key) => {
    const a = map.get(key);
    const out = { density: null, area_km2: null };
    if (!a) return out;
    out.density = a.area > 0 ? a.pop / a.area : null;
    out.area_km2 = a.area || null;
    for (const k of ROLL) out[k] = a.wt[k] ? a.s[k] / a.wt[k] : null;
    return out;
  };
  const rollupFields = (lv) => (counties ? [
    F("density", t("Density"), "float", { unit: t("people / km\u00b2"), source: "pl_stats_population", group: t("People"), lens: "density", description: t("Residents divided by the area of the member gminas ({vintage}).", { vintage: t(countyVintage) }), derived: true }),
    F("area_km2", t("Area"), "km2", { unit: "km\u00b2", source: "pl_stats_population", group: t("Land"), description: t("The summed area of the member gminas (GUS)."), derived: true }),
    ...ROLL.map((k) => {
      const f = cFields.find((x) => x.key === k);
      // A voivodeship figure repeated in every gmina rolls up exactly to its voivodeship.
      const exact = lv === "states" && f.level === "voivodeship";
      const approx = !exact && APPROX.has(k);
      const how = exact ? "" : ZERO_NULL.has(k) ? t("Rolled up from gminas (a gmina without a university counts as zero).")
        : BY_AREA.has(k) ? t("Rolled up from gminas as an area-weighted mean.")
        : approx ? t("Rolled up from gminas as a population-weighted mean (an approximation: not the area's own figure).")
        : t("Rolled up from gminas as a population-weighted mean.");
      return F(k, t(f.label) + (approx ? ` ${ALMOST}` : ""), f.format, {
        unit: f.unit ? t(f.unit) : null, higher_is: f.higher_is, source: f.source, group: groupOf(f), lens: COUNTY_LENS[k],
        description: [t(f.description || ""), how].filter(Boolean).join(" "), derived: !exact,
      });
    }),
  ] : []);

  // --- resources by place ---------------------------------------------------------------------------------------
  const items = resources?.items || [];
  const typeById = new Map((resources?.types || []).map((t) => [t.id, t]));
  const mwByMetro = new Map();
  items.forEach((it) => {
    const m = it.fua || it.cbsa;
    if (typeById.get(it.type)?.unit !== "MW" || !fin(it.value) || !m) return;
    mwByMetro.set(m, (mwByMetro.get(m) || 0) + it.value);
  });
  const hasEnergy = (Array.isArray(states) ? states : []).some((s) => s.energy);
  const energyField = F("energy_mw", t("Mapped power"), "mw", { unit: t("MW of mapped sites"), source: "pl_energy_plants", group: t("Energy"), description: t("Capacity of the power sites mapped as resources (each type above its size threshold): not the total generating capacity.") });

  const boxOf = (cells, k = 6) => {
    if (!cells || !cells.length) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const c of cells) {
      const x = grid.cx(c), y = grid.cy(c);
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
    }
    const R = grid.R * k;
    return { x0: x0 - R, y0: y0 - R, x1: x1 + R, y1: y1 + R };
  };
  const frameCells = (cells, maxScale = 2.4) => {
    const b = boxOf(cells);
    if (b) frameBox(app, b, { pad: 24, maxScale });
    return !!b;
  };

  // --- voivodeships ---------------------------------------------------------------------------------------------
  const stateRows = (Array.isArray(states) ? states : []).map((s, idx) => ({
    key: s.abbr, name: s.name, sub: s.abbr, level: "states", ref: idx,
    v: {
      name: s.name, abbr: s.abbr, ...econValues(s), ...rolled(roll.states, s.abbr),
      ...Object.fromEntries(LAND_KEYS.map((k) => [`land_${k}`, s.land?.[k] ?? null])),
      energy_mw: s.energy ? s.energy.total : null,
    },
  }));
  const landFields = LAND_KEYS.map((k) => F(`land_${k}`, LAND_LABEL[k], "pct", { unit: t("share of land"), source: "pl_geo_worldcover", group: t("Land"), description: LAND_DESC[k], lens: k === "forest" ? "forest" : k === "developed" ? "developed" : null }));
  const states_ = makeLevel({
    id: "states", label: t("Voivodeships"), noun: t("voivodeship"),
    rows: stateRows,
    fields: [F("name", t("Voivodeship"), "text", { group: t("Name") }), ...econFields("states"), ...rollupFields("states"), ...landFields, ...(hasEnergy ? [energyField] : [])],
    highlight: (rows) => ({ states: new Set(rows.map((r) => r.ref)) }),
    rowAtCell: (cell) => (owner[cell] >= 0 ? stateRows[owner[cell]] || null : null),
    focus: (row) => app.selectState(row.ref, { fly: true }),
    cellsOf: (row) => stateCells.get(row.ref) || [],
  });

  // --- metros ---------------------------------------------------------------------------------------------------
  const metroRows = metroList.map((m) => ({
    key: m.id, name: m.name, full: m.full || m.name, sub: (m.states || []).join("-"), level: "metros", ref: m,
    v: {
      name: m.name, states: (m.states || []).join("-"), core: cityById.get(m.core)?.name ?? null, n_towns: (m.cities || []).length || null,
      n_gminas: (m.gminas || []).length || null,
      ...econValues(m), ...rolled(roll.metros, m.id), energy_mw: mwByMetro.get(m.id) ?? null,
    },
  }));
  const metroByRef = new Map(metroRows.map((r) => [r.ref, r]));
  const metroCells = (r) => r.ref.footprint || (r.ref.cell != null ? [r.ref.cell] : []);
  const metros = makeLevel({
    id: "metros", label: t("Metros"), noun: t("metro area"),
    rows: metroRows,
    fields: [
      F("name", t("Metro"), "text", { group: t("Name") }), F("states", t("Voivodeships"), "text", { group: t("Name") }),
      F("core", t("Core town"), "text", { group: t("Name"), description: t("The largest town of the metro area.") }),
      F("n_towns", t("Towns"), "int", { unit: t("towns"), source: "pl_geo_fua", group: t("Name"), description: t("Towns with town rights inside the metro area.") }),
      F("n_gminas", t("Gminas"), "int", { unit: t("gminas"), source: "pl_geo_fua", group: t("Name"), description: t("Member gminas: the city and the gminas from which at least 15% of employed residents commute to it (Eurostat functional urban area).") }),
      ...econFields("metros"), ...rollupFields("metros"), ...(mwByMetro.size ? [energyField] : []),
    ],
    highlight: (rows, o = {}) => {
      const cells = new Set();
      for (const r of rows) for (const c of metroCells(r)) cells.add(c);
      const ring = rows.length <= (o.ringMax ?? 30) ? new Set(rows.map((r) => r.ref.core).filter((id) => cityById.has(id))) : undefined;
      return { cells, cities: ring && ring.size ? ring : undefined };
    },
    rowAtCell: (cell) => { const m = cellMetro.get(cell); return m ? metroByRef.get(m) : null; },
    focus: (row) => {
      if (frameCells(metroCells(row), 2.2)) return;
      const core = cityById.get(row.ref.core);
      if (core) app.selectCity(core, { fly: true });
    },
    cellsOf: (row) => metroCells(row),
  });

  // --- powiaty --------------------------------------------------------------------------------------------------
  let powiaty_ = null;
  const pRows = columnRows(powiaty);
  if (pRows.length) {
    const pFields = powiaty.fields || [];
    const rows = pRows.map(({ r }) => {
      const v = {};
      powiaty.columns.forEach((k, j) => (v[k] = r[j]));
      // Shared keys: the powiaty file names GDP y_gold.
      v.gdp = v.y_gold ?? null;
      v.gdp_pc = ratio(v.gdp, v.population);
      return { key: v.code, name: v.name, full: `${v.name}, ${stateName.get(v.state) || v.state}`, sub: v.state, level: "powiaty", ref: v.code, v };
    });
    const pCells = (r) => powiatCells.get(r.key) || (Number.isInteger(r.v.cell) ? [r.v.cell] : []);
    const fields = [];
    for (const f of pFields) {
      if (["code", "cell", "y_gold"].includes(f.key)) continue;
      fields.push(F(f.key, f.key === "name" ? t("Powiat") : t(f.label), f.key === "growth" ? "signed" : f.format, {
        unit: f.unit ? t(f.unit) : null, higher_is: f.higher_is, source: f.source, description: t(f.description || ""), lens: COUNTY_LENS[f.key], group: groupOf(f),
      }));
    }
    fields.push(
      F("gdp", t("GDP"), "money", { unit: t("zł per year"), source: "pl_gdp", description: t("The powiat's share of its NUTS 3 subregion's GDP {year} (Eurostat), shared by wage bill. An estimate.", { year: Y(yrs.gdp_nuts3, 2023) }) }),
      F("gdp_pc", t("GDP per person"), "pln", { unit: t("zł per resident"), higher_is: "good", source: "pl_gdp", description: t("GDP divided by residents."), derived: true }),
    );
    const byPowiat = new Map(rows.map((r) => [r.key, r]));
    powiaty_ = makeLevel({
      id: "powiaty", label: t("Powiaty"), noun: t("powiat"),
      rows, fields,
      highlight: (list) => {
        const cells = new Set();
        for (const r of list) for (const c of pCells(r)) cells.add(c);
        return { cells };
      },
      rowAtCell: (cell) => {
        const c = countyOf[cell];
        if (!(c >= 0)) return null;
        const pc = worldCounties[c]?.powiat || String(worldCounties[c]?.geoid || "").slice(0, 4);
        return byPowiat.get(pc) || null;
      },
      focus: (row) => { if (!frameCells(pCells(row))) app.selectState(row.v.state, { fly: true }); },
      cellsOf: (row) => pCells(row),
    });
  }

  // --- gminas ---------------------------------------------------------------------------------------------------
  let counties_ = null;
  if (counties && cRows.length) {
    const cols = counties.columns;
    const metroName = new Map(metroList.map((m) => [m.id, m.name]));
    const catName = (lensId) => new Map((app.lensById?.get(lensId)?.categories || []).map((c) => [c.id, c.name]));
    const sejmName = catName("sejm"), floodName = catName("flood");
    // Category names come from lenses.json (translated there); the values are shown as text.
    // A rural gmina often shares its name with the town next door (Boleslawiec and gmina Boleslawiec).
    const twins = new Set();
    const seen = new Map();
    for (const g of cRows) {
      const k = `${g.get("powiat")}|${g.get("name")}`;
      seen.set(k, (seen.get(k) || 0) + 1);
    }
    for (const [k, c] of seen) if (c > 1) twins.add(k);
    const countyRows = cRows.map(({ r, i }) => {
      const v = {};
      cols.forEach((k, j) => (v[k] = r[j]));
      v.metro = v.cbsa ? metroName.get(v.cbsa) || null : null;
      v.gdp_pc = ratio(v.gdp, v.population);
      if (v.sejm_2023 != null) v.sejm_2023 = t(sejmName.get(v.sejm_2023) || v.sejm_2023);
      if (v.flood_2024 != null) v.flood_2024 = t(floodName.get(v.flood_2024) || v.flood_2024);
      const twin = twins.has(`${v.powiat}|${v.name}`) && v.type === "rural";
      const name = twin ? t("{name} (rural)", { name: v.name }) : v.name;
      return { key: v.geoid, name, full: `${name}, ${v.powiat}, ${stateName.get(v.state) || v.state}`, sub: v.state, level: "counties", ref: i, v };
    });
    // counties.json rows follow world.json counties; map by geoid anyway in case they ever diverge.
    const worldIdx = new Map(worldCounties.map((c, k) => [c.geoid, k]));
    for (const row of countyRows) row.ref = worldIdx.get(row.key) ?? row.ref;
    const rowByWorld = new Map(countyRows.map((r) => [r.ref, r]));
    // Gminas smaller than a hex own no cell: counties.json `cell` (the hex nearest the gmina's centre) stands in.
    const cellsOfRow = (r) => countyCells.get(r.ref) || (Number.isInteger(r.v.cell) ? [r.v.cell] : []);
    const fields = cFields.filter((f) => !["cbsa", "geoid", "cell"].includes(f.key)).map((f) =>
      F(f.key, f.key === "name" ? t("Gmina") : f.key === "gdp" ? t("GDP") : t(f.label), f.key === "growth" ? "signed" : f.key === "gdp" ? "money" : f.format, {
        unit: f.unit ? t(f.unit) : null, higher_is: f.higher_is, source: f.source, description: t(f.description || ""), lens: COUNTY_LENS[f.key], group: groupOf(f),
      }));
    const at = fields.findIndex((f) => f.key === "state");
    fields.splice(at + 1, 0, F("metro", t("Metro"), "text", { group: t("Name"), source: "pl_geo_fua", description: t("The metro area (Eurostat functional urban area) the gmina belongs to, if any.") }));
    const gi = fields.findIndex((f) => f.key === "gdp");
    fields.splice(gi + 1, 0, F("gdp_pc", t("GDP per person"), "pln", { unit: t("zł per resident"), higher_is: "good", source: "pl_gdp", description: t("The gmina's GDP share divided by its residents. An estimate."), derived: true }));
    counties_ = makeLevel({
      id: "counties", label: t("Gminas"), noun: t("gmina"),
      rows: countyRows, fields,
      highlight: (rows) => {
        const cells = new Set();
        for (const r of rows) for (const c of cellsOfRow(r)) cells.add(c);
        return { cells };
      },
      rowAtCell: (cell) => (countyOf[cell] >= 0 ? rowByWorld.get(countyOf[cell]) || null : null),
      focus: (row) => {
        let cells = cellsOfRow(row);
        // A gmina smaller than a hex owns no cell: frame its powiat instead, or open its voivodeship.
        if (!cells.length) cells = powiatCells.get(String(row.key).slice(0, 4)) || [];
        if (!frameCells(cells)) app.selectState(row.v.state, { fly: true });
      },
      cellsOf: (row) => cellsOfRow(row),
    });
  }

  // --- towns ----------------------------------------------------------------------------------------------------
  const townRows = cities.map((c) => ({
    key: c.id, name: c.name, full: c.full || c.name, sub: (c.states || []).join("-"), level: "towns", ref: c,
    v: {
      name: c.name, state: (c.states || []).join("-"), kind: c.kind === "city" ? t("City with powiat rights") : t("Town"),
      metro: c.fua ? metroList.find((m) => m.id === c.fua)?.name ?? null : null,
      ...econValues(c),
    },
  }));
  const townByRef = new Map(townRows.map((r) => [r.ref, r]));
  const townCells = (r) => r.ref.footprint || (r.ref.cell != null ? [r.ref.cell] : []);
  const towns = makeLevel({
    id: "towns", label: t("Towns"), noun: t("town"),
    rows: townRows,
    fields: [
      F("name", t("Town"), "text", { group: t("Name") }), F("state", t("Voivodeship"), "text", { group: t("Name") }),
      F("kind", t("Type"), "text", { group: t("Name"), source: "pl_geo_teryt", description: t("A city with powiat rights, or another town with town rights.") }),
      F("metro", t("Metro"), "text", { group: t("Name"), source: "pl_geo_fua", description: t("The metro area the town's gmina belongs to, if any.") }),
      ...econFields("towns"),
    ],
    highlight: (rows, o = {}) => {
      const cells = new Set();
      for (const r of rows) for (const c of townCells(r)) cells.add(c);
      return { cells, cities: rows.length <= (o.ringMax ?? 30) ? new Set(rows.map((r) => r.key)) : undefined };
    },
    rowAtCell: (cell) => { const c = cellTown.get(cell); return c ? townByRef.get(c) : null; },
    focus: (row) => app.selectCity(row.ref, { fly: true }),
    cellsOf: (row) => townCells(row),
  });

  const countiesOffMap = counties_ ? counties_.rows.filter((r) => !counties_.cellsOf(r).length).length : 0; // no hex, not even a stand-in
  return {
    app, nation, nat, vintage, countyVintage, countiesOffMap,
    levels: { states: states_, metros, powiaty: powiaty_, counties: counties_, towns },
    stateCells, countyCells, powiatCells, cellMetro, cellTown, metroByCity: metroByRef,
    items, typeById,
    source: (id) => srcTitle.get(id) || null,
  };
}

/** "powiat boleslawiecki" -> "boleslawiecki", "Krakow (city)" stays (tables and chart labels). */
export function shortPowiat(name) {
  return String(name || "").replace(/^powiat\s+/, "");
}
/** Kept for older views: gmina names need no shortening. */
export function shortCounty(name) {
  return String(name || "");
}

function groupOf(f) {
  if (f.group && GROUP_NAME[f.group]) return GROUP_NAME[f.group];
  const k = f.key;
  if (["name", "type", "powiat", "state", "metro", "code"].includes(k)) return t("Name");
  if (["population", "density", "growth"].includes(k)) return t("People");
  if (["area_km2"].includes(k)) return t("Land");
  if (k.startsWith("y_")) return t("Yields");
  if (["air_station"].includes(k)) return t("Air");
  return t("Economy");
}

function makeLevel(def) {
  const fieldByKey = new Map(def.fields.map((f) => [f.key, f]));
  const byKey = new Map(def.rows.map((r) => [r.key, r]));
  return {
    ...def,
    byKey,
    field: (k) => fieldByKey.get(k) || null,
    value: (row, k) => row.v[k] ?? null,
    numericFields: () => def.fields.filter((f) => f.format !== "text"),
    /** Add fields after the fact (optional files that load on demand); a key already present is skipped. */
    addFields(list) {
      for (const f of list) {
        if (fieldByKey.has(f.key)) continue;
        def.fields.push(f);
        fieldByKey.set(f.key, f);
      }
    },
  };
}

// --- fields from files that load on demand ------------------------------------------------------------------------
// extendData(data, names) loads the named files (military, districts, citizens) through app.loadData and adds their
// columns to the levels once per data model. Missing files (null) add nothing. Returns the loaded files by name.
const F4 = (key, label, format, o = {}) => F(key, label, format, { group: t("Other"), ...o });

export async function extendData(data, names) {
  const app = data.app;
  const files = Object.fromEntries(await Promise.all(names.map(async (n) => [n, await Promise.resolve(app.loadData(n)).catch(() => null)])));
  data.extended ??= new Set();
  for (const n of names) {
    if (data.extended.has(n) || !files[n]) continue;
    data.extended.add(n);
    try {
      if (n === "military") extendMilitary(data, files[n]);
      if (n === "districts") extendDistricts(data, files[n]);
      if (n === "citizens") extendCitizens(data, files[n]);
    } catch (err) {
      console.error(`advisors: could not add the ${n} columns`, err);
    }
  }
  return files;
}

// military.json for Poland has no settled shape yet: add columns only from the parts that are there (a garrison
// tier per town), and nothing otherwise.
function extendMilitary(data, mil) {
  const towns = data.levels.towns;
  const byTown = mil && typeof mil.cities === "object" && !Array.isArray(mil.cities) ? mil.cities : null;
  if (!towns || !byTown) return;
  towns.addFields([
    F4("encampment", t("Garrison"), "text", { source: (mil.sources || [])[0] || "pl_soc_military", group: t("Military"), description: [t("Garrison or fortress when the town passes the Encampment rule; blank otherwise."), typeof mil.rule === "string" ? t(mil.rule) : ""].filter(Boolean).join(" ") }),
  ]);
  for (const r of towns.rows) {
    const c = byTown[r.key];
    r.v.encampment = c && c.tier ? (c.tier === "fortress" ? t("Fortress") : t("Garrison")) : null;
  }
}

// districts.json: per City View town (keyed by town id), so its columns go on the towns level.
function extendDistricts(data, d) {
  const towns = data.levels.towns;
  if (!towns || !d?.cities) return;
  const cat = new Map((d.catalog || []).map((c) => [c.id, c]));
  const vint = d.vintage || "GUS";
  const ind = d.industries || {};
  const topTitle = (top) => (ind[top.pkd]?.title ? t(ind[top.pkd].title) : top.pkd);
  towns.addFields([
    F4("city_type", t("City type"), "text", { source: "pl_stats_labour", group: t("Districts"), description: t("The town's badge: named after its strongest trait (a port, a mine, a university, a speciality at least 3 times the national share of workers). Blank: a diversified economy.") }),
    F4("districts", t("Districts"), "text", { source: "pl_stats_labour", group: t("Districts"), description: [t("Industry districts the town qualifies for, strongest first."), d.rule?.text ? t(d.rule.text) : ""].filter(Boolean).join(" ") }),
    F4("n_districts", t("Number of districts"), "int", { source: "pl_stats_labour", group: t("Districts"), description: t("How many districts pass the rule (up to 5).") }),
    F4("dist_workers", t("Workers (district basis)"), "int", { unit: t("people, by employer seat"), source: "pl_stats_labour", group: t("Districts"), description: t("Workers by PKD section of the town's powiat, or of the city itself for a city with powiat rights ({vintage}).", { vintage: t(vint) }) }),
    F4("dist_scope", t("Counted over"), "text", { source: "pl_stats_labour", group: t("Districts"), description: d.rule?.scope_note ? t(d.rule.scope_note) : t("The unit the district figures describe: the city itself, or the town's powiat.") }),
    F4("top_industry", t("Most specialised industry"), "text", { source: "pl_stats_labour", group: t("Districts"), description: t("The PKD section with the highest location quotient and at least 1,000 workers.") }),
    F4("top_lq", t("Its location quotient"), "lq", { unit: t("times the national share of workers"), source: "pl_stats_labour", group: t("Districts"), description: t("The section's share of the area's workers divided by its share of Poland's workers.") }),
  ]);
  for (const r of towns.rows) {
    const c = d.cities[r.key];
    const top = c?.top?.[0];
    Object.assign(r.v, {
      city_type: c?.badge?.label ? t(c.badge.label) : null,
      districts: c ? (c.districts || []).map((x) => (cat.get(x.id)?.name ? t(cat.get(x.id).name) : x.id)).join(", ") || null : null,
      n_districts: c ? (c.districts || []).length : null,
      dist_workers: c?.emp ?? null,
      dist_scope: c?.scope ?? null,
      top_industry: top ? (top.lower_bound ? t("{industry} (at least)", { industry: topTitle(top) }) : topTitle(top)) : null,
      top_lq: top?.lq ?? null,
    });
  }
}

// citizens.json: the citizen mix per City View town (keyed by town id): a few telling shares go on the towns level.
const CZ = [
  ["workforce", "farmer"], ["workforce", "maker"], ["workforce", "builder"], ["workforce", "clerk"], ["workforce", "engineer"],
  ["workforce", "scholar"], ["workforce", "healer"], ["workforce", "service"],
  ["age", "child"], ["age", "young"], ["age", "elder"],
  ["sex", "female"],
  ["nativity", "foreign_born"],
];
function extendCitizens(data, cz) {
  const towns = data.levels.towns;
  if (!towns || !cz?.cities) return;
  const vint = cz.vintage || "GUS";
  const label = new Map(Object.entries(cz.groups || {}).flatMap(([row, list]) => (list || []).map((g) => [`${row}.${g.key}`, t(g.label)])));
  const grp = { workforce: t("Citizens: work"), age: t("Citizens: age"), sex: t("Citizens: age"), education: t("Citizens: education"), nativity: t("Citizens: origin") };
  // The unit and the area each figure is counted over, per citizens.json row.
  const unitOf = {
    workforce: t("share of workers by sector"), age: t("share of residents by age"), sex: t("share of residents by sex"), nativity: t("share of residents by origin"),
  };
  const descOf = (row, lab) => (row === "workforce" || row === "education" || row === "nativity"
    ? t("{label}: {unit}, counted over the powiat (the city itself for a city with powiat rights) ({vintage}).", { label: lab, unit: unitOf[row], vintage: t(vint) })
    : t("{label}: {unit}, counted over the gmina ({vintage}).", { label: lab, unit: unitOf[row], vintage: t(vint) }));
  towns.addFields([
    ...CZ.map(([row, key]) => F4(`cz_${key}`, label.get(`${row}.${key}`) || key, "pct", {
      unit: unitOf[row], source: row === "nativity" ? "pl_foreigners" : row === "workforce" ? "pl_stats_labour" : "pl_stats_population", group: grp[row],
      description: descOf(row, label.get(`${row}.${key}`) || key),
    })),
    F4("cz_median_age", t("Median age"), "years", { unit: t("years"), source: "pl_stats_population", group: grp.age, description: t("Median age of the residents of the town's gmina ({vintage}).", { vintage: t(vint) }) }),
    F4("cz_degree", t("Higher education"), "pct", { unit: t("of residents 13+"), source: "pl_census_2021", group: grp.education, description: t("Residents aged 13 or more with a higher-education diploma, in the town's powiat (NSP 2021 census).") }),
    F4("cz_specialist", t("Most over-represented citizen"), "text", { source: "pl_stats_labour", group: t("Citizens"), description: [t("The citizen group most over-represented against Poland as a whole (at least 1.5 times)."), cz.rule?.text ? t(cz.rule.text) : ""].filter(Boolean).join(" ") }),
  ]);
  for (const r of towns.rows) {
    const c = cz.cities[r.key];
    for (const [row, key] of CZ) r.v[`cz_${key}`] = c?.[row]?.shares?.[key] ?? null;
    r.v.cz_median_age = c?.age?.median ?? null;
    r.v.cz_degree = c?.education?.bachelors_plus ?? null;
    const sp = (c?.specialists || []).find((s) => s.ratio >= 1);
    const spText = sp ? `${label.get(`${sp.row}.${sp.key}`) || sp.key} x${num(sp.ratio, 1)}` : null;
    r.v.cz_specialist = sp ? (c.reliable === false ? t("{text} (rough)", { text: spText }) : spText) : null;
  }
}

/** The highlight for a set of rows of one level, with defaults (gold outline, other land dimmed when asked). */
export function rowsHighlight(level, rows, opts = {}) {
  if (!level || !rows || !rows.length) return null;
  const one = rows.length === 1 ? rows[0] : null;
  const label = opts.label ?? (one ? (one.level === "states" ? one.name : `${one.full || one.name}${one.sub && !one.full ? `, ${one.sub}` : ""}`) : "");
  return { ...level.highlight(rows, opts), dimOthers: !!opts.dim, color: opts.color, label };
}

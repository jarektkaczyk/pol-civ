// Where each economy marker stands, in two zoom tiers, laid out per zoom in screen space so no marker sits under a
// town banner.
//
//   * Overview (Rpx < DETAIL_RPX): one marker per layer and town (gmina). A town with one site shows that site; a town
//     with several shows one token with a count (its most common kind's glyph). The game studios of a town are always
//     their own marker with a count, apart from the town's other sites.
//   * Detail (Rpx >= DETAIL_RPX): every curated site has its own marker; the studios of a town stay one marker
//     (Wikidata places them all at the town's point). A town's markers gather around the town's point.
//
// Layout (visibleMarkers, cached per 0.25 px zoom bucket): markers go in priority order. Each tries its anchor (the
// free hex chosen by buildMarkers; for a town in the detail tier, the town's point), then rings of spots around it,
// and takes the first spot that is on land, clear of the estimated banner boxes at that zoom (the same rules as
// render/banners.js: population floor, plate size, lift above the city tile) and clear of the markers placed before
// it. A marker with no free spot within its ring limit is left out at that zoom. Tooltips always describe the true
// sites.
//
//   buildMarkers(w, doc, taken) -> {overview: [marker], detail: [marker]}
//     marker = {id, layer, kind, items, count, cluster, studios, cell, ax, ay (anchor km), skipAnchor, prio}
//   visibleMarkers(tiers, on, Rpx, cache, w) -> [{...marker, x, y}] drawn at this zoom
//   markerSize(Rpx) -> css px;  hitMarker(list, x, y, Rpx, grid) -> marker | null
import { metroSpill } from "../../render/art/city.js";

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const MIN_RPX = 1.2; // phones show the whole country at about 2 px per hex radius
// The camera stops at about 30 px per hex radius (6 css px per km, 5 km hexes).
export const DETAIL_RPX = 18;
export const markerSize = (Rpx) => (Rpx < DETAIL_RPX ? clamp(19 + Rpx * 2, 24, 32) : clamp(Rpx * 0.95, 24, 28));

function blockedCells(w) {
  const out = new Set(w.cityByCell.keys());
  try { for (const c of metroSpill(w).keys()) out.add(c); } catch { /* no spill art */ }
  for (const [cell, city] of w.cityByCell) {
    if (!(city.population >= 2.5e5)) continue;
    for (const d of [4, 5]) {
      const j = w.grid.neighbour(cell, d);
      if (j >= 0) out.add(j);
    }
  }
  return out;
}

/** The nearest free land hex to the marker's true point, up to 4 rings out (one marker per hex). */
function chooseCell(w, m, blocked, load) {
  const { grid } = w;
  const free = (c) => c >= 0 && !blocked.has(c) && !w.water?.[c] && !load.get(c) && (w.raw?.owner?.[c] ?? 0) >= 0;
  if (free(m.cell)) return m.cell;
  let ring = new Set([m.cell]);
  const seen = new Set(ring);
  for (let r = 1; r <= 4; r++) {
    const next = new Set();
    for (const c of ring) for (let d = 0; d < 6; d++) {
      const j = grid.neighbour(c, d);
      if (j >= 0 && !seen.has(j)) { seen.add(j); next.add(j); }
    }
    let best = -1, bestS = Infinity;
    for (const c of next) {
      if (!free(c)) continue;
      const sc = Math.hypot(grid.cx(c) - m.tx, grid.cy(c) - m.ty);
      if (sc < bestS) { bestS = sc; best = c; }
    }
    if (best >= 0) return best;
    ring = next;
  }
  return m.cell;
}

const isStudio = (it) => it.kind === "studio" && !it.fact;

function marker(id, layer, items, order) {
  const counts = new Map();
  for (const it of items) counts.set(it.kind, (counts.get(it.kind) || 0) + 1);
  const kind = [...counts].sort((a, b) => b[1] - a[1] || order(a[0]) - order(b[0]))[0][0];
  const first = items[0];
  return {
    id, layer, kind, items, count: items.length, cluster: items.length > 1, studios: items.every(isStudio),
    cell: first.cell, tx: first.x, ty: first.y,
  };
}

export function buildMarkers(w, doc, taken = new Map()) {
  const { grid } = w;
  const okCell = (it) => Number.isInteger(it.cell) && it.cell >= 0 && it.cell < grid.size;
  const items = (doc?.items || []).filter(okCell);
  const kinds = (doc?.kinds || []).map((k) => k.id);
  const order = (k) => { const i = kinds.indexOf(k); return i < 0 ? 99 : i; };
  const groups = (keyOf) => {
    const map = new Map();
    for (const it of items) {
      const key = keyOf(it);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(it);
    }
    return map;
  };
  const town = (it) => it.county || `c${it.cell}`;
  const overview = [...groups((it) => `${it.layer}|${isStudio(it) ? "studio" : "site"}|${town(it)}`)].map(([key, list]) =>
    marker(`o:${key}`, list[0].layer, list, order));
  const detail = [...groups((it) => (isStudio(it) ? `studio|${town(it)}` : `site|${it.id}`))].map(([key, list]) =>
    marker(`d:${key}`, list[0].layer, list, order));
  overview.forEach((m, k) => { m.prio = -m.count * 10 + k * 0.001; });
  detail.forEach((m, k) => { m.prio = (m.studios ? -m.count : 0) * 10 + k * 0.001; });

  // overview anchors: a free hex near the true point, one marker per hex, off city tiles and big banners' hexes
  const blocked = blockedCells(w);
  const load = new Map(taken);
  overview.sort((a, b) => a.prio - b.prio);
  for (const m of overview) {
    const c = chooseCell(w, m, blocked, load);
    load.set(c, 1);
    m.ax = grid.cx(c);
    m.ay = grid.cy(c);
  }
  // detail anchors: a town with two or more markers gathers them around its point (the city tile stays visible);
  // a lone site stands at its true point unless that covers a town tile
  const perTown = new Map();
  for (const m of detail) perTown.set(town(m.items[0]), (perTown.get(town(m.items[0])) || 0) + 1);
  const cityCell = new Map();
  for (const [cell, city] of w.cityByCell) cityCell.set(city.id, cell);
  detail.sort((a, b) => a.prio - b.prio);
  for (const m of detail) {
    const key = town(m.items[0]);
    const c = cityCell.get(key);
    if (perTown.get(key) > 1 && c != null) {
      m.ax = grid.cx(c);
      m.ay = grid.cy(c);
      m.skipAnchor = true;
    } else {
      m.ax = m.tx;
      m.ay = m.ty;
      m.skipAnchor = w.cityByCell.has(grid.cellAt(m.tx, m.ty));
    }
  }
  return { overview, detail };
}

// --- banner boxes (an estimate of render/banners.js at a zoom) ---------------------------------------------------------

function popFloor(Rpx) {
  return Rpx < 5 ? 5e5 : Rpx < 8 ? 2e5 : Rpx < 14 ? 9e4 : Rpx < 24 ? 5e4 : Rpx < 40 ? 2e4 : Rpx < 70 ? 8e3 : 0;
}

/** Boxes [x0, y0, x1, y1] in map css px (km x css px per km) where banners may stand at this zoom. */
function bannerBoxes(w, Rpx) {
  const { grid } = w;
  const s = Rpx / grid.R;
  const floor = popFloor(Rpx);
  const compact = Rpx < 8;
  const out = [];
  for (const [cell, city] of w.cityByCell) {
    const pop = city.population || 0;
    if (pop < floor) continue;
    const name = String(city.name || "");
    const plate = compact ? 7 * name.length + 64 : 8.4 * name.length + 92;
    const tiered = Rpx > 24 && pop >= 1e5;
    const width = tiered ? Math.max(plate, 250) : plate;
    const height = (compact ? 18 : 22) + (tiered ? 15 + 12 : 0); // yield row and city-type tab
    const sx = grid.cx(cell) * s, sy = grid.cy(cell) * s;
    const bottom = sy - Math.max(10, Rpx * 0.55) + 7; // plate bottom plus its pointer (a dot lifts it least)
    const top = sy - Math.max(10, Rpx * 0.75) - height - 4;
    out.push([sx - width / 2 - 4, top, sx + width / 2 + 4, bottom]);
  }
  return out;
}

// --- layout -------------------------------------------------------------------------------------------------------

/** Spots around an anchor (css px offsets): the anchor, then rings starting below and alternating sides. */
function spots(step, rings) {
  const out = [[0, 0, 0]];
  for (let k = 1; k <= rings; k++) {
    const n = Math.max(6, Math.round(2 * Math.PI * k));
    for (let i = 0; i < n; i++) {
      const j = i === 0 ? 0 : (i % 2 ? (i + 1) / 2 : -i / 2); // 0, +1, -1, +2, -2, ...
      const a = Math.PI / 2 + (j * 2 * Math.PI) / n;
      out.push([k * step * Math.cos(a), k * step * Math.sin(a), k]);
    }
  }
  return out;
}

function layout(w, list, on, Rpx) {
  const { grid } = w;
  const s = Rpx / grid.R;
  const size = markerSize(Rpx);
  const detail = Rpx >= DETAIL_RPX;
  const rings = detail ? 6 : 1; // zoomed out a ring is ~30 km: a crowded marker hides rather than wander off
  const cand = spots(size * 1.04, rings);
  const banners = bannerBoxes(w, Rpx);
  const placed = [];
  const out = [];
  const hw = size * 0.5, top = size * 0.62, bottom = size * 0.42; // the glyph's box around its point
  for (const m of list) {
    if (!on[m.layer]) continue;
    const ax = m.ax * s, ay = m.ay * s;
    const near = banners.filter((b) => b[0] < ax + 400 && b[2] > ax - 400 && b[1] < ay + 400 && b[3] > ay - 400);
    let pick = null;
    for (const [dx, dy, k] of cand) {
      if (k === 0 && m.skipAnchor) continue;
      const x = ax + dx, y = ay + dy;
      if (near.some((b) => x - hw < b[2] && x + hw > b[0] && y - top < b[3] && y + bottom > b[1])) continue;
      if (placed.some(([px, py]) => (px - x) ** 2 + (py - y) ** 2 < (size * 0.92) ** 2)) continue;
      if (k > 0) {
        const c = grid.cellAt(x / s, y / s);
        if (c < 0 || w.water?.[c] || (w.raw?.owner?.[c] ?? 0) < 0) continue;
      }
      pick = [x, y];
      break;
    }
    if (!pick) continue;
    placed.push(pick);
    out.push({ ...m, x: pick[0] / s, y: pick[1] / s });
  }
  return out;
}

/** The markers of the switched-on layers at this zoom, laid out clear of banners; cached per 0.25 px bucket. */
export function visibleMarkers(tiers, on, Rpx, cache, w) {
  const b = Math.round(Rpx * 4) / 4;
  const key = `${on.made ? 1 : 0}${on.tech ? 1 : 0}|${b}`;
  let out = cache.get(key);
  if (out) return out;
  out = b < MIN_RPX ? [] : layout(w, b >= DETAIL_RPX ? tiers.detail : tiers.overview, on, b);
  if (cache.size > 200) cache.clear();
  cache.set(key, out);
  return out;
}

export function hitMarker(list, x, y, Rpx, grid) {
  const s = Rpx / grid.R;
  const r = (markerSize(Rpx) / 2) * 0.9 / s;
  for (let k = list.length - 1; k >= 0; k--) {
    const m = list[k];
    if ((m.x - x) ** 2 + (m.y - y) ** 2 <= r * r) return m;
  }
  return null;
}

// Hover tooltips for Polish map layers. Values come from the layer files and every string is escaped.
import { esc, compact, int } from "../../format.js";
import { FORT_KINDS, fortKind, WONDER_KINDS } from "../../render/art/sites.js";

const muted = (s) => `<span class="muted">${s}</span>`;
const num = (n) => (n == null || !Number.isFinite(n) ? "-" : compact(n));
const join = (...xs) => xs.filter((x) => x != null && x !== "").map(esc).join(" &middot; ");

const PORT_TYPE = { seaport: "Seaport", lng_terminal: "LNG terminal", coastal: "Seaport", small: "Local port" };
const STATUS = { operating: "Operating", under_construction: "Under construction", planned: "Planned", forming: "Forming", active: "Active" };

export const tips = {
  port(p) {
    const lines = [`<b>${esc(p.name)}</b> ${muted(join(PORT_TYPE[p.type] || "Port", p.state))}`];
    if (p.cargo_kt != null) lines.push(`<b>${num(p.cargo_kt * 1000)}</b> tonnes handled${p.year ? ` (${esc(p.year)})` : ""}`);
    if (p.international_kt != null) lines.push(`International cargo ${num(p.international_kt * 1000)} tonnes`);
    if (p.teu != null) lines.push(`${num(p.teu)} TEU`);
    if (p.status && p.status !== "operating") lines.push(muted(esc(STATUS[p.status] || p.status)));
    return lines.join("<br>");
  },
  airport(a) {
    const code = a.iata || a.icao;
    const title = code ? `${esc(code)} &middot; ${esc(a.name)}` : esc(a.name);
    const lines = [`<b>${title}</b> ${muted(join(a.state))}`];
    if (a.passengers != null) {
      let change = "";
      if (a.passengers_prev > 0) change = `, ${((a.passengers / a.passengers_prev - 1) * 100).toFixed(1)}% from the prior year`;
      lines.push(`<b>${num(a.passengers)}</b> passengers${a.year ? ` (${esc(a.year)})` : ""}${change}`);
    }
    if (a.freight_t != null) lines.push(`${num(a.freight_t)} tonnes of freight and mail`);
    if (a.status && a.status !== "operating") {
      let status = STATUS[a.status] || a.status;
      if (a.status === "planned" && a.opening_planned) status += `, first stage by ${a.opening_planned}`;
      lines.push(muted(esc(status)));
    }
    return lines.join("<br>");
  },
  fort(f, m) {
    const comp = m.data.military?.components?.find((c) => c.id === f.component || c.id === f.branch);
    const branch = f.component || f.branch;
    const name = comp?.name || FORT_KINDS[fortKind(branch)]?.name || "Military site";
    const lines = [
      `<b>${esc(f.name)}</b> ${muted(join(f.garrison, f.state))}`,
      join(name, f.kind_label, STATUS[f.status] || f.status),
    ];
    if (f.note) lines.push(muted(esc(f.note)));
    return lines.filter(Boolean).join("<br>");
  },
  range(r, m) {
    const comp = m.data.military?.components?.find((c) => c.id === r.component || c.id === r.branch);
    const lines = [
      `<b>${esc(r.name)}</b> ${muted(join(r.garrison, r.state))}`,
      join("Restricted training ground", comp?.name || r.component || r.branch),
    ];
    if (r.area_km2 != null) lines.push(`${num(r.area_km2)} km2`);
    return lines.join("<br>");
  },
  wonder(x, m) {
    const rule = m.data.wonders?.rules?.find((r) => r.id === x.rule);
    const mt = x.metrics || {};
    const memorial = x.kind === "memorial";
    const kind = memorial ? "Memorial site" : WONDER_KINDS[x.kind]?.name || x.kind_label || "Landmark";
    const lines = [`<b>${esc(x.name)}</b> ${muted(join(x.state))}`, esc(kind)];
    if (x.kind === "university" && mt.students != null) lines.push(`${int(mt.students)} students`);
    if (mt.visits_latest != null) lines.push(`${num(mt.visits_latest)} visitors${mt.latest_year ? ` (${esc(mt.latest_year)})` : ""}`);
    if (mt.visits != null) lines.push(`${num(mt.visits)} visitors${mt.year ? ` (${esc(mt.year)})` : ""}`);
    if (mt.record) lines.push(esc(mt.record));
    if (mt.value != null) lines.push(`${num(mt.value)} ${esc(mt.unit || "")}`.trim());
    if (rule?.text && !memorial) lines.push(muted(esc(rule.text)));
    return lines.join("<br>");
  },
  route(rt) {
    const r = rt.route;
    const a = rt.a?.short || rt.a?.name || r.a;
    const b = rt.b?.short || rt.b?.name || r.b;
    const lines = [
      `<b>${esc(a)} and ${esc(b)}</b> ${muted(`route ${esc(r.rank)}`)}`,
      `<b>${num((r.value_kt ?? r.tons_k) * 1000)}</b> tonnes by rail`,
    ];
    if (r.dist_km != null) lines.push(`${int(r.dist_km)} km between the capital cities`);
    return lines.join("<br>");
  },
};

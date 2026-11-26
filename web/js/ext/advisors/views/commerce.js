// Commerce advisor: Polish transport network, freight flows, seaports and airports.
import { esc, fin } from "../core/util.js";
import { int, count3 } from "../core/fmt.js";
import { barList } from "../core/charts.js";
import { createTable } from "../core/table.js";
import { section, tiles, segmented } from "../core/view.js";
import { frameBox, focusPoint } from "../core/frame.js";

export async function mount(ctx) {
  const { app, el, link } = ctx;
  const [infra, trade] = await Promise.all([
    app.loadData("infrastructure"),
    app.loadData("trade").catch(() => null),
  ]);
  if (!infra) {
    el.innerHTML = `<p class="adv-empty pad">No transport data is available.</p>`;
    return {};
  }
  const network = infra.totals?.network || {};
  const portTotal = infra.totals?.ports || {};
  const airportTotal = infra.totals?.airports || {};
  el.insertAdjacentHTML("beforeend", tiles([
    { label: "Motorways", value: fin(network.motorway_km) ? `${int(network.motorway_km)} km` : "-", sub: "network length" },
    { label: "Railways", value: fin(network.rail_line_km) ? `${int(network.rail_line_km)} km` : "-", sub: fin(network.rail_electrified_km) ? `${int(network.rail_electrified_km)} km electrified` : "" },
    { label: "Seaport cargo", value: fin(portTotal.cargo_kt) ? `${count3(portTotal.cargo_kt * 1000)} t` : "-", sub: "2025" },
    { label: "Airport passengers", value: count3(airportTotal.passengers), sub: "2025" },
  ]));

  let routeTable = null;
  let routeBars = null;
  let pinnedRoute = null;
  if (trade?.routes?.length) {
    const zones = new Map((trade.zones || []).map((zone) => [zone.id, zone]));
    const routes = trade.routes.map((route) => ({
      ...route,
      key: `${route.a}-${route.b}`,
      fromName: zones.get(route.a)?.name || route.a,
      toName: zones.get(route.b)?.name || route.b,
      value: route.value_kt ?? route.tons_k,
    }));
    const routesBody = section(el, { title: "Largest regional freight flows" });
    routesBody.insertAdjacentHTML("beforeend", `<p class="adv-callout">This advisor shows all 30 published rail-freight pairs whose voivodeship capital cities are at least 100 km apart.</p>`);
    routeBars = barList(routesBody, {
      rows: routes.slice(0, 12).map((route) => ({ key: route.key, label: `${route.fromName} - ${route.toName}`, sub: `${count3(route.value * 1000)} tonnes`, value: route.value, color: "#d2402f", route })),
      rank: true, ariaLabel: "Largest regional rail-freight flows",
      onHover: (row) => highlightRoute(row?.route || null, false),
      onClick: (row) => pinRoute(row.route),
    });
    routeTable = createTable(routesBody, {
      caption: "Regional freight flows", search: "Search regions", rank: true, maxHeight: 300, rows: routes,
      columns: [
        { key: "from", label: "From", align: "l", width: "minmax(0,1.2fr)", value: (r) => r.fromName, text: (r) => r.fromName },
        { key: "to", label: "To", align: "l", width: "minmax(0,1.2fr)", value: (r) => r.toName, text: (r) => r.toName },
        { key: "value", label: "Freight", value: (r) => r.value, text: (r) => `${count3(r.value * 1000)} t` },
        { key: "distance", label: "Distance", value: (r) => r.dist_km, text: (r) => fin(r.dist_km) ? `${int(r.dist_km)} km` : "-", hideBelow: 400 },
      ],
      sort: { key: "value", dir: "desc" },
      onHover: (route) => highlightRoute(route, false),
      onClick: pinRoute,
    });
    function highlightRoute(route, base) {
      const highlight = route ? { cells: new Set(route.path || []), dimOthers: true, label: `${route.fromName} - ${route.toName}` } : null;
      if (base) link.base(highlight);
      else link.hover(highlight);
    }
    function pinRoute(route) {
      pinnedRoute = pinnedRoute?.key === route.key ? null : route;
      highlightRoute(pinnedRoute, true);
      routeBars.setSelected(pinnedRoute?.key || null);
      routeTable.setSelected(pinnedRoute?.key || null);
      if (!pinnedRoute) return;
      const bounds = app.highlightBounds({ cells: new Set(pinnedRoute.path || []) });
      if (bounds) frameBox(app, bounds, { pad: 40, maxScale: 2.4 });
    }
  }

  const hubsBody = section(el, { title: "Ports and airports" });
  let hubMode = "ports";
  const hubsHost = document.createElement("div");
  segmented(hubsBody, {
    label: "Show", value: hubMode,
    options: [{ value: "ports", label: "Seaports" }, { value: "airports", label: "Airports" }],
    onChange: (value) => { hubMode = value; drawHubs(); },
  });
  hubsBody.appendChild(hubsHost);
  let hubTable = null;
  function drawHubs() {
    hubsHost.innerHTML = "";
    if (hubMode === "ports") {
      const rows = [...(infra.ports || [])].filter((p) => fin(p.cargo_kt)).sort((a, b) => b.cargo_kt - a.cargo_kt);
      barList(hubsHost, {
        rows: rows.slice(0, 10).map((p) => ({ key: p.id, label: p.name, sub: p.teu != null ? `${count3(p.teu)} TEU` : "", value: p.cargo_kt, text: `${count3(p.cargo_kt * 1000)} t`, color: "#2f7fa7", item: p })),
        rank: true, ariaLabel: "Busiest Polish seaports",
        onHover: (r) => link.hover(r ? { cells: new Set([r.item.cell]), dimOthers: true, label: r.item.name } : null),
        onClick: (r) => fly(r.item),
      });
      hubTable = createTable(hubsHost, {
        caption: "Polish seaports", rows: infra.ports || [], maxHeight: 260,
        columns: [
          { key: "name", label: "Port", align: "l", width: "minmax(0,1.5fr)", value: (r) => r.name, text: (r) => r.name },
          { key: "cargo", label: "Cargo", value: (r) => r.cargo_kt, text: (r) => fin(r.cargo_kt) ? `${count3(r.cargo_kt * 1000)} t` : "-" },
          { key: "teu", label: "Containers", value: (r) => r.teu, text: (r) => fin(r.teu) ? `${count3(r.teu)} TEU` : "-", hideBelow: 400 },
        ],
        sort: { key: "cargo", dir: "desc" },
        onHover: (r) => link.hover(r ? { cells: new Set([r.cell]), dimOthers: true, label: r.name } : null),
        onClick: fly,
      });
    } else {
      const rows = [...(infra.airports || [])].sort((a, b) => (b.passengers || 0) - (a.passengers || 0));
      barList(hubsHost, {
        rows: rows.filter((a) => fin(a.passengers)).slice(0, 10).map((a) => ({ key: a.id, label: a.name, sub: a.iata || a.icao, value: a.passengers, text: count3(a.passengers), color: "#5f76a8", item: a })),
        rank: true, ariaLabel: "Busiest Polish airports",
        onHover: (r) => link.hover(r ? { cells: new Set([r.item.cell]), dimOthers: true, label: r.item.name } : null),
        onClick: (r) => fly(r.item),
      });
      hubTable = createTable(hubsHost, {
        caption: "Polish airports", rows, maxHeight: 260,
        columns: [
          { key: "name", label: "Airport", align: "l", width: "minmax(0,1.5fr)", value: (r) => r.name, text: (r) => r.name },
          { key: "passengers", label: "Passengers", value: (r) => r.passengers, text: (r) => fin(r.passengers) ? count3(r.passengers) : "-" },
          { key: "status", label: "Status", align: "l", value: (r) => r.status,
            text: (r) => r.status === "planned" ? `Planned ${r.opening_planned || ""}`.trim() : "Operating" },
          { key: "freight", label: "Freight", value: (r) => r.freight_t, text: (r) => fin(r.freight_t) ? `${count3(r.freight_t)} t` : "-", hideBelow: 600 },
        ],
        sort: { key: "passengers", dir: "desc" },
        onHover: (r) => link.hover(r ? { cells: new Set([r.cell]), dimOthers: true, label: r.name } : null),
        onClick: fly,
      });
    }
  }
  function fly(item) {
    focusPoint(app, item.x, item.y, Math.min(app.cam.maxScale, Math.max(app.cam.scale, (app.cam.fitScale || 1) * 3.2)));
  }
  drawHubs();

  return {
    onMapHover(event) {
      if (event.layer === "hubs" && event.item?.data?.id) hubTable?.setHot(event.item.data.id);
      if (event.layer === "trade" && event.item?.data?.route) routeTable?.setHot(`${event.item.data.route.a}-${event.item.data.route.b}`);
    },
    onEscape() {
      if (!pinnedRoute) return false;
      pinnedRoute = null;
      link.base(null);
      routeBars?.setSelected(null);
      routeTable?.setSelected(null);
      return true;
    },
  };
}

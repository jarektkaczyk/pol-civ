"""Towns (cities.json), metros (metros.json) and the nation (nation.json) of Poland.

Towns: every town with town rights (GUS, 1 January 2026; source pl_geo_places) gets a banner at its true position
(the OSM place node). The banner cell is the cell under the town, snapped to Polish land and nudged one ring when a
bigger town already holds it. The City View opens for the 66 cities with powiat rights and every other town of
20,000 or more people (`city_view`).

Economic fields come from the town's gmina: a town with its own urban gmina (TERYT type 1) is that gmina; a town
inside an urban-rural gmina (type 4) reports the whole urban-rural gmina (type 3, town and villages) and says so
in `scope`. `population` is always the town's own population (GUS Tabl. 20). Powiat-level figures (wage,
unemployment, PKD jobs) are the town's powiat; for a city with powiat rights that is the city itself.

Metros are Eurostat functional urban areas (FUA: a city and its commuting zone, source pl_geo_fua), with two
merges published in metros.json `rule`: Trójmiasto (the Gdańsk and Gdynia FUAs) and the Górnośląsko-Zagłębiowska
metro (the FUAs of Katowice, Gliwice, Tychy and Dąbrowa Górnicza, all members of the GZM metropolitan union).
"""

from __future__ import annotations

import math

from ..core.geo import MapProjection
from ..core.hexgrid import HexGrid
from ..core.store import load_interim, write_web
from .plstats import Stats, Units, num, optional
from .yields import INDUSTRIES, YIELD_KEYS, YIELDS, Economy

REQUIRES = ["_world", "pl_geo_teryt", "pl_geo_places", "pl_geo_fua", "pl_stats_population", "pl_stats_labour",
            "pl_stats_prosperity", "pl_gdp"]
PRODUCES = ["cities.json", "metros.json", "nation.json"]

CAPITAL = "1465011"  # Warszawa
CITY_VIEW_POP = 20000
FOOTPRINT_MAJORITY = 4  # of a cell's 7 gmina samples
PEERS = 5
RANK_KEYS = ["population", "gdp", "gdp_per_capita", "growth"] + YIELD_KEYS
METRO_MERGES = {
    "PL006F": ("Trójmiasto", ["PL006F", "PL053F"]),
    "PL010F": ("Górnośląsko-Zagłębiowska", ["PL010F", "PL055F", "PL061F", "PL070F"]),
}
METRO_RULE = (
    "Metros are the Eurostat functional urban areas (FUA) of Poland: a city and the gminas from which at least 15% "
    "of employed residents commute to it (Eurostat LAU 2025 correspondence). Two are merged: Trójmiasto = the FUAs "
    "of Gdańsk (with Sopot) and Gdynia; Górnośląsko-Zagłębiowska = the FUAs of Katowice, Gliwice, Tychy and "
    "Dąbrowa Górnicza, the four FUA core cities in the GZM metropolitan union (metropoliagzm.pl)."
)
METRO_REF = "https://metropoliagzm.pl/"


def ring_search(grid: HexGrid, start: int, max_rings: int):
    """(ring, cell) for every cell within `max_rings` of `start`, nearest rings first."""
    seen, frontier = {start}, [start]
    yield 0, start
    for ring in range(1, max_rings + 1):
        nxt = []
        for c in frontier:
            for n in grid.neighbours(c):
                if n not in seen:
                    seen.add(n)
                    nxt.append(n)
                    yield ring, n
        frontier = nxt


def nearest_land(grid: HexGrid, owner: list[int], cell: int, x: float, y: float, max_rings=8) -> int:
    """Nearest Polish land cell to (x, y): the first ring with land, plus one more ring to compare distances."""
    found, best = None, None
    for ring, c in ring_search(grid, max(cell, 0), max_rings):
        if found is not None and ring > found + 1:
            break
        if owner[c] < 0:
            continue
        found = ring if found is None else found
        cx, cy = grid.center(*grid.col_row(c))
        d = math.hypot(cx - x, cy - y)
        if best is None or d < best[0]:
            best = (d, c)
    return best[1] if best else -1


def free_cell(grid: HexGrid, owner, taken: set, cell: int, x: float, y: float, max_rings=1):
    best = None
    for _, c in ring_search(grid, cell, max_rings):
        if owner[c] < 0 or c in taken:
            continue
        cx, cy = grid.center(*grid.col_row(c))
        d = math.hypot(cx - x, cy - y)
        if best is None or d < best[0]:
            best = (d, c)
    return best[1] if best else None


def footprints(world: dict, members: dict[str, list[str]]) -> dict[str, set[int]]:
    """id -> Polish land cells where at least FOOTPRINT_MAJORITY of the 7 gmina samples are member gminas."""
    idx = {g: i for i, g in enumerate(world["counties"])}
    owner_of = {}
    for key, gms in members.items():
        for g in gms:
            if g in idx:
                owner_of.setdefault(idx[g], []).append(key)
    out: dict[str, set[int]] = {}
    for cell, s in enumerate(world["county_samples"]):
        if not s or world["owner"][cell] < 0:
            continue
        votes: dict[str, int] = {}
        for k in s:
            for key in owner_of.get(k, ()):
                votes[key] = votes.get(key, 0) + 1
        for key, n in votes.items():
            if n >= FOOTPRINT_MAJORITY:
                out.setdefault(key, set()).add(cell)
    return out


def gmina_centres(world: dict, grid: HexGrid) -> dict[str, tuple[float, float]]:
    """Mean position of the hexes whose centre sample lies in each gmina (map km)."""
    acc: dict[int, list] = {}
    for cell, s in enumerate(world["county_samples"]):
        if s and s[0] >= 0:
            a = acc.setdefault(s[0], [0.0, 0.0, 0])
            x, y = grid.center(*grid.col_row(cell))
            a[0] += x
            a[1] += y
            a[2] += 1
    return {world["counties"][k]: (a[0] / a[2], a[1] / a[2]) for k, a in acc.items()}


def value_of(c: dict, key: str):
    if key == "gdp_per_capita":  # GDP covers the gmina: divide by the gmina's people, not the town's
        pop = c.get("gmina_population") or c.get("population")
        return c["gdp"] / pop if c.get("gdp") is not None and pop else None
    if key in ("population", "gdp", "growth"):
        return c.get(key)
    return c["yields"].get(key)


def add_ranks(rows: list[dict], peer_pool: list[dict] | None = None) -> None:
    """ranks: 1 = highest among `rows` (null where the value is null; ties keep population order).
    peers: the PEERS rows of `peer_pool` (default all) closest in population by ratio, for members of the pool."""
    for c in rows:
        c["ranks"] = {}
    for key in RANK_KEYS:
        have = [c for c in rows if value_of(c, key) is not None]
        have.sort(key=lambda c: -value_of(c, key))
        for r, c in enumerate(have, 1):
            c["ranks"][key] = r
        for c in rows:
            c["ranks"].setdefault(key, None)
    pool = peer_pool if peer_pool is not None else rows
    ids = {id(c) for c in pool}
    for c in rows:
        if id(c) not in ids or not c.get("population"):
            c["peers"] = []
            continue
        lp = math.log(c["population"])
        near = sorted((abs(math.log(o["population"]) - lp), o["id"]) for o in pool if o is not c and o.get("population"))
        c["peers"] = [i for _, i in near[:PEERS]]


def metro_groups(fua: dict, by6: dict[str, str]) -> list[dict]:
    """FUAs after the published merges: [{id, name, fuas, gminas (TERYT7)}]."""
    merged_into = {f: key for key, (_, fs) in METRO_MERGES.items() for f in fs}
    groups: dict[str, dict] = {}
    for code, f in sorted(fua.get("fuas", {}).items()):
        key = merged_into.get(code, code)
        g = groups.setdefault(key, {"id": key, "name": METRO_MERGES[key][0] if key in METRO_MERGES else f["name"],
                                    "fuas": [], "gminas": []})
        g["fuas"].append(code)
        g["gminas"] += [by6[t6] for t6 in f["gminas"] if t6 in by6]
    for g in groups.values():
        g["gminas"] = sorted(set(g["gminas"]))
    return list(groups.values())


def build() -> None:
    from .world import ABBR

    world = load_interim("_world")
    teryt = load_interim("pl_geo_teryt")
    places = (optional("pl_geo_places") or {}).get("data") or {}
    units = Units(world, teryt)
    stats = Stats()
    econ = Economy(units, stats)
    proj = MapProjection(**{k: world["projection"][k] for k in ("min_x", "max_y", "margin")})
    grid = HexGrid(**world["grid"])
    owner = world["owner"]
    centres = gmina_centres(world, grid)
    fua = stats.data("pl_geo_fua")
    fua_of6 = {t6: g.get("fua") for t6, g in (fua.get("gminas") or {}).items()}
    groups = metro_groups(fua, units.by6)
    metro_of_fua = {f: g["id"] for g in groups for f in g["fuas"]}

    towns = []
    no_pos, off_gmina = [], []
    for p in places.get("points", []):
        props = p["props"]
        g = props["gmina"]
        if g not in units.index:
            print(f"    ! town {p['id']} {p['name']}: gmina {g} not on the map")
            continue
        if p.get("lon") is not None:
            x, y = proj(p["lon"], p["lat"])
        elif g in centres:
            x, y = centres[g]
            no_pos.append(p["name"])
        else:
            continue
        own_gmina = p["id"][-1] == "1"
        powiat_rights = bool(props.get("powiat_rights"))
        prof = econ.profile([g], powiaty=[g[:4]] if powiat_rights else None)
        town_pop = num(props.get("population"))
        gmina_pop = prof["population"]
        voiv = g[:2]
        scope = ("city" if powiat_rights else "gmina") if own_gmina else "urban-rural gmina"
        if not own_gmina:  # the gmina's series and growth are not the town's
            prof["pop_series"] = None
            prof["growth"] = None
        c = {
            "id": p["id"],
            "name": p["name"],
            "full": f"{p['name']}, {units.powiat_label(g[:4]) + ', ' if not powiat_rights else ''}{units.voiv_name.get(voiv, voiv)}",
            "states": [ABBR.get(voiv, voiv)],
            "voivodeship": voiv,
            "powiat": g[:4],
            "gmina": g,
            "kind": "city" if powiat_rights else "town",
            "city_view": powiat_rights or (town_pop or 0) >= CITY_VIEW_POP,
            "metro": powiat_rights or (town_pop or 0) >= CITY_VIEW_POP,
            "fua": metro_of_fua.get(fua_of6.get(g[:6])),
            "capital": p["id"] == CAPITAL,
            "x": round(x, 1),
            "y": round(y, 1),
            "cell": grid.cell_at(x, y),
            **prof,
            "population": town_pop,
            "gmina_population": gmina_pop,
            "scope": scope,
        }
        cell = c["cell"]
        if cell >= 0 and world["county"][cell] >= 0 and world["counties"][world["county"][cell]] != g:
            off_gmina.append(p["name"])
        towns.append(c)
    towns.sort(key=lambda c: -(c["population"] or 0))

    taken: set[int] = set()
    snapped, moved, shared = [], [], []
    for c in towns:
        cell = c["cell"]
        if cell < 0 or owner[cell] < 0:
            cell = nearest_land(grid, owner, cell, c["x"], c["y"])
            snapped.append(c["name"])
        if cell in taken:
            alt = free_cell(grid, owner, taken, cell, c["x"], c["y"]) or free_cell(grid, owner, taken, cell, c["x"], c["y"], 2)
            if alt is None:
                shared.append(c["name"])
            else:
                cell = alt
                moved.append(c["name"])
        taken.add(cell)
        c["cell"] = cell

    feet = footprints(world, {c["id"]: [c["gmina"]] for c in towns if c["id"][-1] == "1"})
    for c in towns:
        cells = feet.get(c["id"], set()) | {c["cell"]}
        c["footprint"] = sorted(cells)
    view = [c for c in towns if c["city_view"]]
    add_ranks(towns, view)

    # Metros.
    town_by_gmina = {}
    for c in towns:
        town_by_gmina.setdefault(c["gmina"], c)
    mfeet = footprints(world, {g["id"]: g["gminas"] for g in groups})
    metros = []
    for g in groups:
        member_towns = [c for c in towns if c["gmina"] in set(g["gminas"])]
        core = max(member_towns, key=lambda c: c["population"] or 0) if member_towns else None
        prof = econ.profile(g["gminas"])
        voivs = {}
        for gm in g["gminas"]:
            voivs[gm[:2]] = voivs.get(gm[:2], 0) + (econ.pop.get(gm) or 0)
        states = [ABBR.get(v, v) for v, _ in sorted(voivs.items(), key=lambda kv: -kv[1])]
        cells = mfeet.get(g["id"], set()) | ({core["cell"]} if core else set())
        metros.append({
            "id": g["id"], "name": g["name"],
            "full": f"{g['name']} metro area" if g["id"] not in METRO_MERGES else f"{g['name']} metro area ({', '.join(g['fuas'])})",
            "fuas": g["fuas"], "states": states, "metro": True, "capital": bool(core and core["capital"]),
            "core": core["id"] if core else None,
            "cities": [c["id"] for c in member_towns],
            "x": core["x"] if core else None, "y": core["y"] if core else None,
            "cell": core["cell"] if core else (min(cells) if cells else None),
            **prof,
            "gminas": g["gminas"],
            "footprint": sorted(cells),
        })
    metros.sort(key=lambda m: -(m["population"] or 0))
    add_ranks(metros)

    # Nation: all gminas as whole powiaty, with the published national figures where GUS has them.
    nat = econ.profile(units.gminas, powiaty=units.powiaty)
    head_pop = stats.rows("pl_stats_population", "headline").get("PL") or {}
    head_lab = stats.rows("pl_stats_labour", "national_headlines").get("PL") or {}
    gdp_c = stats.rows("pl_gdp", "gdp_country").get("PL") or {}
    if num(head_pop.get("population")) is not None:
        nat["population"] = head_pop["population"]
    if num(gdp_c.get("gdp_pln")) is not None:
        nat["gdp"] = nat["yields"]["gold"] = round(gdp_c["gdp_pln"])
        nat["gdp_year"] = econ.years["gdp_nation"]
        nat["gdp_estimated"] = False
    if num(head_lab.get("registered_unemployment_rate")) is not None:
        nat["unemployment"] = round(head_lab["registered_unemployment_rate"] / 100, 4)
    if num(head_lab.get("average_gross_monthly_wage")) is not None:
        nat["wage"] = round(head_lab["average_gross_monthly_wage"])
        nat["wage_exact"] = True

    print(f"    {len(towns)} towns, {len(view)} with a City View, {len(metros)} metros")
    for label, items in (("placed at their gmina centre (no OSM node)", no_pos),
                         ("whose point falls in a hex centred on a neighbouring gmina (normal at 5 km hexes)", off_gmina),
                         ("snapped onto land", snapped), ("moved to a free neighbouring cell", moved),
                         ("sharing a cell", shared),
                         ("NUTS 3 subregions shared by workers (no wage)", econ.by_workers_only)):
        if items:
            print(f"    {len(items)} {label}: {', '.join(items[:8])}{' ...' if len(items) > 8 else ''}")

    write_web("cities.json", towns)
    write_web("metros.json", {"version": 1, "rule": METRO_RULE, "ref": METRO_REF,
                              "vintage": stats.vintage("pl_geo_fua"), "metros": metros})
    write_web("nation.json", {
        "vintage": stats.vintage("pl_stats_population") or "GUS",
        "year": econ.years["population"] or 2025,
        "gdp_vintage": stats.vintage("pl_gdp"),
        "years": econ.years,
        "nation": nat,
        "yields": YIELDS,
        "industries": INDUSTRIES,
    })

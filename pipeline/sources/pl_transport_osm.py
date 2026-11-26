"""Poland's motorways, expressways and main railway lines from OpenStreetMap (Overpass API).

Two layers, each fetched as 15 bbox tiles clipped to the Poland area (a whole-country query runs
longer than some networks keep an idle request open):

* roads: `highway=motorway` and `highway=trunk` with an S-road `ref` (Polish expressways are tagged
  trunk). Ways under construction carry `highway=construction` and are left out, so this is the
  network as built on the OSM extract date.
* rail: `railway=rail` + `usage=main` (the main network of PKP PLK and others), without sidings and
  crossovers (`service=*`).

Output is `lines` (an extension of the interim contract: each line is a chain of ways with the same
class and ref, simplified to about 200 m) and a country table of lengths. Lengths are measured on the
unsimplified OSM geometry.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from ..core.source import Source, SourceInfo
from .pl_transport_util import (
    ODBL_NOTE, chain_ways, line_length_km, osm_elements, osm_timestamp, overpass_tiled, round_coords,
    simplify,
)

ROADS_BODY = ('way["highway"="motorway"](area.pl)({bbox});'
              'way["highway"="trunk"]["ref"~"(^|;) *S *[0-9]"](area.pl)({bbox});')
RAIL_BODY = 'way["railway"="rail"]["usage"="main"][!"service"](area.pl)({bbox});'
TOLERANCE_M = 200.0
CMK_REF = "4"  # PKP PLK line 4, Centralna Magistrala Kolejowa (Grodzisk Mazowiecki - Zawiercie)


def road_ref(tags: dict) -> str | None:
    """First A- or S-road number in `ref` ('A1;E75' -> 'A1', 'S 7' -> 'S7'), else None."""
    for part in re.split(r"[;,]", tags.get("ref") or ""):
        m = re.fullmatch(r"\s*([AS])\s*(\d+[a-z]?)\s*", part)
        if m:
            return m.group(1) + m.group(2)
    return None


def road_class(tags: dict) -> str:
    ref = road_ref(tags)
    if ref and ref.startswith("A"):
        return "motorway"
    if ref and ref.startswith("S"):
        return "expressway"
    return "motorway_other"  # highway=motorway without an A/S number (short connectors)


def is_oneway(tags: dict) -> bool:
    """One carriageway of a dual road. highway=motorway is one-way unless tagged otherwise."""
    ow = (tags.get("oneway") or "").lower()
    if ow in ("yes", "-1", "true", "1"):
        return True
    if ow in ("no", "false", "0"):
        return False
    return tags.get("highway") == "motorway"


def _coords(el: dict) -> list[tuple[float, float]]:
    return [(g["lon"], g["lat"]) for g in el.get("geometry") or [] if g]


def _maxspeed(tags: dict) -> int | None:
    m = re.match(r"\s*(\d+)", tags.get("maxspeed") or "")
    return int(m.group(1)) if m else None


def summarize_roads(elements: list[dict]) -> tuple[dict, list[dict]]:
    """(km by class, lines). Road km counts a one-way carriageway as half a road."""
    km: dict[str, float] = defaultdict(float)
    carriageway_km: dict[str, float] = defaultdict(float)
    groups: dict[tuple, list] = defaultdict(list)
    names: dict[tuple, Counter] = defaultdict(Counter)
    for el in elements:
        tags = el.get("tags") or {}
        coords = _coords(el)
        if len(coords) < 2:
            continue
        cls = road_class(tags)
        length = line_length_km(coords)
        carriageway_km[cls] += length
        km[cls] += length / 2 if is_oneway(tags) else length
        key = (cls, road_ref(tags))
        groups[key].append(coords)
        if tags.get("name"):
            names[key][tags["name"]] += 1
    lines = []
    for (cls, ref), ways in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        for i, chain in enumerate(chain_ways(ways)):
            pts = simplify(chain, TOLERANCE_M)
            lines.append({"id": f"{cls}:{ref or '-'}:{i}", "kind": cls, "ref": ref,
                          "name": names[(cls, ref)].most_common(1)[0][0] if names[(cls, ref)] else None,
                          "coords": round_coords(pts)})
    return {"km": dict(km), "carriageway_km": dict(carriageway_km)}, lines


def summarize_rail(elements: list[dict]) -> tuple[dict, list[dict]]:
    """(lengths, lines). Line km per PLK line number = its longest track; track km = all tracks."""
    track_km = 0.0
    per_track: dict[tuple, float] = defaultdict(float)  # (line ref, track ref) -> km
    electrified_track: dict[tuple, float] = defaultdict(float)
    groups: dict[tuple, list] = defaultdict(list)
    meta: dict[tuple, dict] = defaultdict(lambda: {"names": Counter(), "maxspeed": None, "highspeed": False})
    for el in elements:
        tags = el.get("tags") or {}
        coords = _coords(el)
        if len(coords) < 2:
            continue
        length = line_length_km(coords)
        track_km += length
        ref = (tags.get("ref") or "").strip() or None
        track = (tags.get("railway:track_ref") or "").strip() or None
        line_key = (ref or f"way{el['id']}", track)
        per_track[line_key] += length
        elec = (tags.get("electrified") or "no") not in ("no", "")
        if elec:
            electrified_track[line_key] += length
        key = (ref, track, elec)
        groups[key].append(coords)
        m = meta[key]
        if tags.get("name"):
            m["names"][tags["name"]] += 1
        sp = _maxspeed(tags)
        if sp and (m["maxspeed"] is None or sp > m["maxspeed"]):
            m["maxspeed"] = sp
        m["highspeed"] = m["highspeed"] or tags.get("highspeed") == "yes"
    line_km: dict[str, float] = defaultdict(float)
    line_elec_km: dict[str, float] = defaultdict(float)
    for (ref, track), km in per_track.items():
        if km > line_km[ref]:
            line_km[ref] = km
            line_elec_km[ref] = electrified_track[(ref, track)]
    lines = []
    for (ref, track, elec), ways in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        m = meta[(ref, track, elec)]
        for i, chain in enumerate(chain_ways(ways)):
            lines.append({"id": f"rail:{ref or '-'}:{track or '-'}:{'e' if elec else 'n'}:{i}", "kind": "rail_main",
                          "ref": ref, "track": track, "electrified": elec, "maxspeed": m["maxspeed"],
                          "highspeed": m["highspeed"], "cmk": ref == CMK_REF,
                          "name": m["names"].most_common(1)[0][0] if m["names"] else None,
                          "coords": round_coords(simplify(chain, TOLERANCE_M))})
    return {"track_km": track_km, "line_km": sum(line_km.values()), "electrified_line_km": sum(line_elec_km.values()),
            "lines_count": len(line_km), "cmk_line_km": line_km.get(CMK_REF)}, lines


class PlTransportOsm(Source):
    info = SourceInfo(
        id="pl_transport_osm",
        title="Motorways, expressways and main railway lines of Poland (OpenStreetMap)",
        publisher="OpenStreetMap contributors (via the Overpass API)",
        homepage="https://www.openstreetmap.org/",
        license="ODbL 1.0. " + ODBL_NOTE,
        description="The motorways (A-roads) and expressways (S-roads) open to traffic, and the main railway "
        "lines (including the CMK high-speed line), as mapped in OpenStreetMap on the extract date. "
        "Geometry is simplified to about 200 m.",
        used_for=["Roads and railways on the map (tile improvements)", "Commerce advisor network lengths"],
    )

    def _paths(self, force=False):
        roads = overpass_tiled(self, ROADS_BODY, "roads", force=force)
        rail = overpass_tiled(self, RAIL_BODY, "rail", force=force)
        return roads, rail

    def fetch(self, force=False):
        self._paths(force=force)

    def process(self):
        roads_p, rail_p = self._paths()
        road_stats, road_lines = summarize_roads(osm_elements(roads_p))
        rail_stats, rail_lines = summarize_rail(osm_elements(rail_p))
        stamp = osm_timestamp(list(roads_p) + list(rail_p))
        date = stamp[:10] if stamp else None
        year = int(date[:4]) if date else None
        r1 = lambda v: None if v is None else round(v, 1)  # noqa: E731
        row = {
            "motorway_km": r1(road_stats["km"].get("motorway")),
            "expressway_km": r1(road_stats["km"].get("expressway")),
            "motorway_other_km": r1(road_stats["km"].get("motorway_other")),
            "rail_main_line_km": r1(rail_stats["line_km"]),
            "rail_main_electrified_line_km": r1(rail_stats["electrified_line_km"]),
            "rail_main_track_km": r1(rail_stats["track_km"]),
            "cmk_line_km": r1(rail_stats["cmk_line_km"]),
        }
        note = f"OSM extract {date}"
        fields = {
            "motorway_km": {"label": "Motorways (A-roads) open", "unit": "km", "year": year,
                            "note": note + "; a one-way carriageway counts as half a road"},
            "expressway_km": {"label": "Expressways (S-roads) open", "unit": "km", "year": year,
                              "note": note + "; a one-way carriageway counts as half a road"},
            "motorway_other_km": {"label": "Other motorway-class roads (no A/S number)", "unit": "km", "year": year,
                                  "note": note},
            "rail_main_line_km": {"label": "Main railway lines", "unit": "km", "year": year,
                                  "note": note + "; per PLK line number, the length of its longest track"},
            "rail_main_electrified_line_km": {"label": "Main railway lines, electrified", "unit": "km", "year": year,
                                              "note": note},
            "rail_main_track_km": {"label": "Main-line track (all tracks)", "unit": "km", "year": year, "note": note},
            "cmk_line_km": {"label": "CMK high-speed line (PLK line 4)", "unit": "km", "year": year, "note": note},
        }
        files = [str(p.relative_to(self.raw_dir)) for p in list(roads_p) + list(rail_p)]
        return {
            "vintage": f"OpenStreetMap extract {date}" if date else "OpenStreetMap",
            "osm_timestamp": stamp,
            "tables": {"network_length": {"level": "country", "fields": fields, "rows": {"PL": row}}},
            "lines": road_lines + rail_lines,
            "notes": [
                ODBL_NOTE,
                f"OSM data as of {stamp} (Overpass timestamp_osm_base).",
                "Rule (roads): highway=motorway, plus highway=trunk whose ref holds an S-road number. Class from the "
                "ref: A = motorway, S = expressway, none = motorway_other. Sections under construction are excluded.",
                "Rule (rail): railway=rail with usage=main and no service tag. `track` is railway:track_ref; draw one "
                "track per ref to avoid doubled lines. cmk=true marks PLK line 4 (Centralna Magistrala Kolejowa).",
                "`lines` extends the interim contract: {id, kind, ref, name, coords: [[lon, lat], ...]} simplified "
                f"with Douglas-Peucker at {TOLERANCE_M:g} m; lengths use the full OSM geometry.",
            ],
            "_files": files,
        }

"""Parsing helpers of the pol-civ transport, energy and mines sources (no network)."""

import json
import tempfile
import unittest
from pathlib import Path

from pipeline.sources import pl_energy_plants as plants
from pipeline.sources import pl_energy_res as res
from pipeline.sources import pl_mines as mines
from pipeline.sources import pl_transport_ports as ports
from pipeline.sources import pl_transport_airports as airports
from pipeline.sources import pl_transport_freight as freight
from pipeline.sources import pl_transport_osm as osm
from pipeline.sources import pl_transport_util as util


def jsonstat(dims: dict[str, list[str]], values: dict[tuple, float], labels: dict | None = None) -> dict:
    """A tiny JSON-stat 2.0 document with the given dimensions (in order) and cells."""
    ids = list(dims)
    sizes = [len(v) for v in dims.values()]
    strides = [1] * len(ids)
    for i in range(len(ids) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]
    flat = {}
    for key, v in values.items():
        flat[str(sum(dims[d].index(k) * s for d, k, s in zip(ids, key, strides)))] = v
    dimension = {d: {"category": {"index": {c: i for i, c in enumerate(cs)},
                                  "label": (labels or {}).get(d, {c: c for c in cs})}} for d, cs in dims.items()}
    return {"id": ids, "size": sizes, "dimension": dimension, "value": flat}


class JsonStatTest(unittest.TestCase):
    def test_decodes_cells_by_dimension(self):
        doc = jsonstat({"geo": ["PL", "DE"], "time": ["2024", "2025"]}, {("PL", "2025"): 5.0, ("DE", "2024"): 7.0})
        ids, cells = util.jsonstat_cells(doc)
        self.assertEqual(ids, ["geo", "time"])
        self.assertEqual(cells, {("PL", "2025"): 5.0, ("DE", "2024"): 7.0})

    def test_list_values(self):
        doc = jsonstat({"a": ["x", "y"]}, {})
        doc["value"] = [1, 2]
        self.assertEqual(util.jsonstat_cells(doc)[1], {("x",): 1, ("y",): 2})


class PowerParseTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(util.parse_mw("5102 MW"), 5102)
        self.assertAlmostEqual(util.parse_mw("4,5 MW"), 4.5)
        self.assertAlmostEqual(util.parse_mw("900 kW"), 0.9)
        self.assertEqual(util.parse_mw("1.2 GW"), 1200)
        self.assertAlmostEqual(util.parse_mw("40 MWp"), 40)
        self.assertIsNone(util.parse_mw("yes"))
        self.assertIsNone(util.parse_mw(None))
        self.assertIsNone(util.parse_mw("50"))  # ambiguous bare number
        self.assertEqual(util.parse_mw("5000000"), 5)  # bare watts


class GeometryTest(unittest.TestCase):
    def test_length(self):
        # one degree of latitude is about 111.2 km
        self.assertAlmostEqual(util.line_length_km([(19.0, 50.0), (19.0, 51.0)]), 111.2, delta=0.2)

    def test_simplify_drops_points_within_tolerance(self):
        line = [(19.0 + i * 0.001, 50.0 + (0.0005 if i % 2 else 0.0)) for i in range(50)]  # ~55 m zigzag
        out = util.simplify(line, 200.0)
        self.assertEqual(out, [line[0], line[-1]])
        corner = [(19.0, 50.0), (19.1, 50.0), (19.1, 50.1)]
        self.assertEqual(util.simplify(corner, 200.0), corner)

    def test_chain_joins_in_any_direction(self):
        a = [(0, 0), (1, 0)]
        b = [(2, 0), (1, 0)]  # reversed
        c = [(-1, 0), (0, 0)]
        d = [(5, 5), (6, 6)]
        chains = util.chain_ways([a, b, c, d])
        self.assertEqual(len(chains), 2)
        main = max(chains, key=len)
        self.assertEqual(sorted(main), [(-1, 0), (0, 0), (1, 0), (2, 0)])
        xs = [p[0] for p in main]
        self.assertTrue(xs == sorted(xs) or xs == sorted(xs, reverse=True))


class OverpassTest(unittest.TestCase):
    def test_incomplete_answers_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.json"
            p.write_text(json.dumps({"elements": [], "remark": "runtime error: Query timed out in \"query\""}))
            self.assertIn("incomplete", util.overpass_ok(p))
            p.write_text(json.dumps({"elements": [{"type": "way", "id": 1}]}))
            self.assertIsNone(util.overpass_ok(p))
            p.write_text("<html>busy</html>")
            self.assertIn("not JSON", util.overpass_ok(p))

    def test_tiles_cover_poland(self):
        south = min(t[0] for t in util.POLAND_TILES)
        north = max(t[2] for t in util.POLAND_TILES)
        west = min(t[1] for t in util.POLAND_TILES)
        east = max(t[3] for t in util.POLAND_TILES)
        self.assertLessEqual(south, 49.0)
        self.assertGreaterEqual(north, 54.9)
        self.assertLessEqual(west, 14.1)
        self.assertGreaterEqual(east, 24.15)


class RoadRailTest(unittest.TestCase):
    def test_refs_and_classes(self):
        self.assertEqual(osm.road_ref({"ref": "A1;E75"}), "A1")
        self.assertEqual(osm.road_ref({"ref": "E77;S 7"}), "S7")
        self.assertIsNone(osm.road_ref({"ref": "DK94"}))
        self.assertEqual(osm.road_class({"ref": "S3"}), "expressway")
        self.assertEqual(osm.road_class({"ref": "A4"}), "motorway")
        self.assertEqual(osm.road_class({}), "motorway_other")
        self.assertTrue(osm.is_oneway({"highway": "motorway"}))
        self.assertFalse(osm.is_oneway({"highway": "trunk"}))
        self.assertFalse(osm.is_oneway({"highway": "motorway", "oneway": "no"}))

    def test_dual_carriageway_counts_once(self):
        way = lambda i, lat: {"type": "way", "id": i, "tags": {"highway": "motorway", "ref": "A2"},  # noqa: E731
                              "geometry": [{"lon": 19.0, "lat": lat}, {"lon": 20.0, "lat": lat}]}
        stats, lines = osm.summarize_roads([way(1, 52.0), way(2, 52.0002)])
        one = util.line_length_km([(19.0, 52.0), (20.0, 52.0)])
        self.assertAlmostEqual(stats["km"]["motorway"], one, delta=0.1)
        self.assertAlmostEqual(stats["carriageway_km"]["motorway"], 2 * one, delta=0.1)
        self.assertTrue(all(ln["kind"] == "motorway" and ln["ref"] == "A2" for ln in lines))

    def test_rail_line_km_is_longest_track(self):
        def way(i, track, lon1, lon2):
            return {"type": "way", "id": i,
                    "tags": {"railway": "rail", "usage": "main", "ref": "4", "railway:track_ref": track,
                             "electrified": "contact_line", "maxspeed": "200"},
                    "geometry": [{"lon": lon1, "lat": 51.0}, {"lon": lon2, "lat": 51.0}]}
        stats, lines = osm.summarize_rail([way(1, "1", 19.0, 20.0), way(2, "2", 19.0, 19.5)])
        one = util.line_length_km([(19.0, 51.0), (20.0, 51.0)])
        self.assertAlmostEqual(stats["line_km"], one, delta=0.1)
        self.assertAlmostEqual(stats["cmk_line_km"], one, delta=0.1)
        self.assertAlmostEqual(stats["electrified_line_km"], one, delta=0.1)
        self.assertAlmostEqual(stats["track_km"], one * 1.5, delta=0.1)
        self.assertTrue(all(ln["cmk"] and ln["maxspeed"] == 200 for ln in lines))


class FreightTest(unittest.TestCase):
    def test_nuts2_mapping_checks_labels(self):
        self.assertEqual(freight.nuts2_to_voiv("PL71", "Łódzkie"), "10")
        self.assertEqual(freight.nuts2_to_voiv("PL11", "Lódzkie (NUTS 2013)"), "10")
        self.assertEqual(freight.nuts2_to_voiv("PL91", "Warszawski stołeczny"), "14")
        self.assertIsNone(freight.nuts2_to_voiv("DE11", "Stuttgart"))
        with self.assertRaises(ValueError):
            freight.nuts2_to_voiv("PL22", "Pomorskie")

    def test_rail_flows_sum_mazowieckie_and_split_within(self):
        codes = ["PL91", "PL92", "PL22", "DE11", "PLXX"]
        labels = {"c_load": {"PL91": "Warszawski stołeczny", "PL92": "Mazowiecki regionalny", "PL22": "Śląskie",
                             "DE11": "Stuttgart", "PLXX": "Not regionalised"}}
        labels["c_unload"] = labels["c_load"]
        doc = jsonstat({"c_load": codes, "c_unload": codes, "time": ["2020"]},
                       {("PL22", "PL91", "2020"): 1000.0, ("PL22", "PL92", "2020"): 500.0,
                        ("PL91", "PL92", "2020"): 300.0, ("DE11", "PL22", "2020"): 9.0,
                        ("PLXX", "PL22", "2020"): 9.0}, labels)
        year, flows, within = freight.rail_flows(doc)
        self.assertEqual(year, 2020)
        self.assertEqual([(f["from"], f["to"], f["value"]) for f in flows], [("24", "14", 1.5)])
        self.assertEqual(within, {"14": 0.3})

    def test_newest_year_table_takes_polish_nuts3(self):
        doc = jsonstat({"geo": ["PL213", "PL21", "DE111"], "time": ["2024", "2025"]},
                       {("PL213", "2025"): 10.0, ("PL21", "2025"): 99.0, ("DE111", "2025"): 5.0,
                        ("PL213", "2024"): 8.0})
        self.assertEqual(freight.newest_year_table(doc), (2025, {"PL213": 10.0}))


class AirportTest(unittest.TestCase):
    def test_values_by_year_and_icao(self):
        dims = {"unit": ["PAS"], "tra_meas": ["PAS_CRD"], "rep_airp": ["PL_EPWA", "DE_EDDF"],
                "schedule": ["TOTAL"], "tra_cov": ["TOTAL"], "time": ["2024", "2025"]}
        doc = jsonstat(dims, {("PAS", "PAS_CRD", "PL_EPWA", "TOTAL", "TOTAL", "2025"): 100.0,
                              ("PAS", "PAS_CRD", "DE_EDDF", "TOTAL", "TOTAL", "2025"): 5.0})
        vals, labels = airports.airport_values(doc, "PAS_CRD", "PAS")
        self.assertEqual(vals, {2025: {"EPWA": 100.0}})
        self.assertIn("EPWA", labels)


class ResTest(unittest.TestCase):
    PAGES = [{"results": [
        {"id": "011212161000", "name": "Powiat m. Kraków", "kind": "2"},
        {"id": "011212006000", "name": "Powiat krakowski", "kind": "1"},
        {"id": "030210363000", "name": "Powiat m. Wałbrzych do 2002", "kind": "2"},
        {"id": "030210365000", "name": "Powiat m. Wałbrzych od 2013", "kind": "2"},
        {"id": "030210321000", "name": "Powiat wałbrzyski", "kind": "1"},
    ]}]

    def test_powiat_codes(self):
        p = res.bdl_powiats(self.PAGES)
        self.assertEqual(p[("12", "krakow", True)], "1261")
        self.assertEqual(p[("12", "krakowski", False)], "1206")
        self.assertEqual(p[("02", "walbrzych", True)], "0265")
        self.assertEqual(p[("02", "walbrzyski", False)], "0221")

    def test_aggregate_by_type(self):
        rows = [
            {"A": "Lp."},
            {"A": "1", "D": "małopolskie", "E": "m. Kraków", "G": "1.5", "H": "PVA"},
            {"A": "2", "D": "małopolskie", "E": "Kraków", "G": "0.5", "H": "PVA"},
            {"A": "3", "D": "małopolskie", "E": "krakowski", "G": "10", "H": "WIL"},
            {"A": "4", "D": "małopolskie", "E": "krakowski", "G": "100", "H": "WS"},
            {"A": "5", "D": "śląskie", "E": "tczewski", "G": "1", "H": "PVA"},
        ]
        table, unmatched, n = res.aggregate(rows, res.bdl_powiats(self.PAGES))
        self.assertEqual(n, 4)
        self.assertEqual(table["1261"]["solar_mw"], 2.0)
        self.assertIsNone(table["1261"]["wind_mw"])
        self.assertEqual(table["1206"]["res_mw"], 10.0)  # co-firing kept apart
        self.assertEqual(table["1206"]["cofiring_mw"], 100.0)
        self.assertEqual(unmatched, ["24 tczewski"])


class PortsTest(unittest.TestCase):
    def test_gus_table_and_yearbook(self):
        rows = [{"A": "TOTAL", "B": "128033.6", "D": "103.1", "E": "1", "F": "2", "G": "3"},
                {"A": "Gdańsk", "B": "75323.6", "D": "106.0"}, {"A": "liquid bulk", "B": "5"}]
        t = ports.gus_port_table(rows)
        self.assertEqual(t["Gdańsk"]["cargo_kt"], 75323.6)
        self.assertNotIn("liquid bulk", t)
        yb = [{"A": "Lp.", "B": "X", "C": "1990", "D": "2000", "E": "2010", "F": "2020", "G": "2023", "H": "2024"},
              {"A": "7", "B": "Kołobrzeg", "C": "264", "H": "223"}, {"A": "24", "B": "Kołobrzeg", "H": "101"}]
        self.assertEqual(ports.yearbook_port(yb, "Kołobrzeg"), (2024, 223.0))

    def test_teu_needs_four_quarters(self):
        q = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1"]
        doc = jsonstat({"rep_mar": ["PL_0PLGDN"], "time": q},
                       {("PL_0PLGDN", t): 10.0 for t in q})
        self.assertEqual(ports.teu_by_port(doc), (2025, {"PL_0PLGDN": 40.0}))


class PlantsTest(unittest.TestCase):
    def el(self, i, typ="way", **tags):
        return {"type": typ, "id": i, "center": {"lon": 19.0, "lat": 51.0}, "tags": tags}

    def test_size_rule_fuel_and_dedupe(self):
        els = [
            self.el(592157961, power="plant", **{"plant:source": "coal", "plant:output:electricity": "5472 MW"}),
            self.el(2, power="plant", **{"plant:source": "solar", "plant:output:electricity": "60 MW"}),
            self.el(3, power="plant", **{"plant:source": "wind", "plant:output:electricity": "60 MW"}),
            self.el(4, name="Farm X", **{"construction:power": "plant", "plant:source": "wind",
                                         "plant:output:electricity": "720 MW"}),
            self.el(5, "relation", name="Farm X", **{"construction:power": "plant", "plant:source": "wind",
                                                     "plant:output:electricity": "720 MW"}),
        ]
        pts = plants.select_plants(els)
        ids = {p["props"]["osm_id"] for p in pts}
        self.assertEqual(ids, {"way/592157961", "way/2", "relation/5"})
        by = {p["props"]["osm_id"]: p for p in pts}
        self.assertEqual(by["way/592157961"]["props"]["fuel"], "lignite")
        self.assertEqual(by["relation/5"]["props"]["status"], "under_construction")
        missing = plants.apply_overrides(pts, {"way/2": {"mw": 61.0, "ref": "x"}, "way/9": {"mw": 1}})
        self.assertEqual(missing, ["way/9"])
        self.assertEqual(by["way/2"]["props"]["mw_source"], "ref")

    def test_pumped_storage(self):
        self.assertEqual(plants.fuel_of({"plant:source": "hydro", "plant:method": "water-pumped-storage"}, "way/1"),
                         "pumped_storage")
        self.assertEqual(plants.fuel_of({"plant:source": "hydro", "plant:method": "water-storage"}, "way/1"), "hydro")

    def test_totals_skip_non_operating(self):
        pts = [{"props": {"status": "operating", "mw": 10.0, "fuel": "gas"}},
               {"props": {"status": "planned", "mw": 99.0, "fuel": "gas"}}]
        self.assertEqual(plants.totals_by_fuel(pts), {"gas": {"count": 1, "mw": 10.0}})


class CuratedTest(unittest.TestCase):
    def test_wrong_qid_is_caught(self):
        wd = {"Q1": {"labels": {"pl": "Kopalnia Konin"}, "lonlat": (18.2, 52.3)}}
        pts, problems = util.curated_points(
            [{"id": "a", "name": "A", "kind": "mine", "qid": "Q1", "expect": "Tomisławice"},
             {"id": "b", "name": "B", "kind": "mine", "qid": "Q1", "expect": "Konin", "output": 1.0}], wd)
        self.assertIsNone(pts[0]["lon"])
        self.assertEqual((pts[1]["lon"], pts[1]["lat"]), (18.2, 52.3))
        self.assertEqual(pts[1]["props"]["output"], 1.0)
        self.assertEqual(len(problems), 2)  # wrong label, then no coordinates

    def test_mine_ids_are_ascii_and_unique(self):
        ids = [m["id"] for m in mines.MINES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.isascii() for i in ids))
        self.assertEqual(mines.osm_query(["way/1", "node/2"]),
                         "[out:json][timeout:60];(way(1);node(2););out center tags qt;")


if __name__ == "__main__":
    unittest.main()

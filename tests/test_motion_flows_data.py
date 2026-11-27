"""Parsers and geometry for the motion-flow data: PSE power, BDL migration matrix, MF local finance."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline.build import migration, money, power
from pipeline.build.flowgeo import arc, bearing_deg, clip_to_rect, flat
from pipeline.sources import pl_local_finance_flows as mf
from pipeline.sources import pl_migration_od as od
from pipeline.sources import pl_power_pse as pse


def _cal(i, wi=100.0, pv=0.0):
    hh, mm = divmod(i * 15, 60)
    return {"dtime_utc": f"u{i:03d}", "period": f"{hh:02d}:{mm:02d} - xx", "wi": wi, "pv": pv, "demand": 18000.5, "swm_p": -200.0,
            "swm_np": 600.0}


class PseParseTest(unittest.TestCase):
    def test_num(self):
        self.assertEqual(pse.num("4244,492"), 4244.492)
        self.assertEqual(pse.num(12.5), 12.5)
        self.assertIsNone(pse.num(None))
        self.assertIsNone(pse.num("x"))

    def test_section_pair(self):
        self.assertEqual(pse.section_pair("DE-PL"), ("DE", "PL"))
        self.assertEqual(pse.section_pair("PL-UA_DOB"), ("PL", "UA"))
        self.assertIsNone(pse.section_pair("PLDE"))

    def test_url_is_one_request_per_day(self):
        url = pse.pse_url("his-gen-pal", "2026-11-26")
        self.assertTrue(url.startswith("https://api.raporty.pse.pl/api/his-gen-pal?$filter="))
        self.assertIn("2026-11-26", url)
        self.assertTrue(url.endswith("&$first=2000"))

    def test_parse_day_net_flows_and_generation(self):
        cal = [_cal(i) for i in range(96)]
        gen = [{"dtime_utc": f"u{i:03d}", "alias_entsoe": c, "value": "1,5"} for i in range(96)
               for c in ("B01", "B02", "B04", "B05", "B06", "B10", "B11", "B12", "B16", "B19")]
        flows = []
        for i in range(96):
            for nb in ("DE", "CZ", "SK", "LT", "UA", "SE"):
                flows.append({"dtime_utc": f"u{i:03d}", "section_code": f"{nb}-PL", "value": 100.0})
                flows.append({"dtime_utc": f"u{i:03d}", "section_code": f"PL-{nb}", "value": -40.0})
        day = pse.parse_day(gen, cal, flows)
        self.assertEqual(len(day["utc"]), 96)
        self.assertEqual(day["start"][0], "00:00")
        self.assertEqual(day["start"][57], "14:15")
        self.assertEqual(day["generation"]["B05"][3], 1.5)
        self.assertEqual(day["net"]["DE"][0], 60.0)  # import 100, export 40: net import 60
        self.assertEqual(day["balance"][0], 400.0)
        self.assertIsNone(pse.day_complete(day))
        cal[10]["wi"] = None
        self.assertIn("wind", pse.day_complete(pse.parse_day(gen, cal, flows)))

    def test_short_day_is_incomplete(self):
        day = pse.parse_day([], [_cal(i) for i in range(40)], [])
        self.assertEqual(pse.day_complete(day), "40 quarters")


class InterconnectorTest(unittest.TestCase):
    # Poland is the square lon 15..20, lat 50..54; Germany lies west of it.
    COUNTRIES = {
        "Poland": [[[15.0, 50.0], [20.0, 50.0], [20.0, 54.0], [15.0, 54.0]]],
        "Germany": [[[10.0, 50.0], [15.0, 50.0], [15.0, 54.0], [10.0, 54.0]]],
        "Belarus": [[[20.0, 50.0], [25.0, 50.0], [25.0, 54.0], [20.0, 54.0]]],
    }

    def way(self, wid, coords, **tags):
        return {"id": wid, "tags": {"power": "line", "voltage": "400000", **tags}, "coords": coords}

    def test_crossing_through_ways_split_at_the_border(self):
        ways = [self.way(1, [(16.0, 52.0), (15.2, 52.0)], name="A - B"), self.way(2, [(15.2, 52.0), (14.0, 52.0)]),
                self.way(3, [(19.0, 51.0), (21.0, 51.0)])]
        points, notes = pse.find_crossings(ways, self.COUNTRIES)
        self.assertEqual([p["props"]["neighbour"] for p in points], ["DE"])
        p = points[0]
        self.assertAlmostEqual(p["lon"], 15.0, places=4)
        self.assertEqual(p["name"], "A - B")
        self.assertEqual(p["props"]["voltage_kv"], [400])
        self.assertGreater(p["props"]["path"][0][0], p["props"]["path"][-1][0])  # Polish side first
        self.assertIn("Belarus", notes[0])

    def test_border_substation_counts_on_the_far_side(self):
        # the foreign part is short (0.3 km to a substation) but the line ends there
        ways = [self.way(1, [(15.1, 52.0), (15.0005, 52.0)]), self.way(2, [(15.0005, 52.0), (14.996, 52.0)])]
        points, _ = pse.find_crossings(ways, self.COUNTRIES)
        self.assertEqual([p["props"]["neighbour"] for p in points], ["DE"])

    def test_double_circuit_is_one_interconnector(self):
        ways = [self.way(1, [(16.0, 52.0), (14.0, 52.0)]), self.way(2, [(16.0, 52.001), (14.0, 52.001)])]
        points, _ = pse.find_crossings(ways, self.COUNTRIES)
        self.assertEqual(len(points), 1)
        self.assertEqual(len(points[0]["props"]["osm_ways"]), 2)

    def test_sea_crossing_only_for_hvdc(self):
        ways = [self.way(1, [(17.0, 53.0), (17.0, 54.5)], power="cable"),
                self.way(2, [(18.0, 53.0), (18.0, 54.5)], power="cable", voltage="450000", frequency="0")]
        points, _ = pse.find_crossings(ways, self.COUNTRIES)
        self.assertEqual([(p["props"]["neighbour"], p["props"]["hvdc"]) for p in points], [("SE", True)])

    def test_line_across_a_border_river_and_back_is_not_a_crossing(self):
        ways = [self.way(1, [(16.0, 51.0), (15.003, 51.0), (14.997, 51.2), (15.003, 51.4), (16.0, 51.4)])]
        self.assertEqual(pse.find_crossings(ways, self.COUNTRIES)[0], [])

    def test_latin_name_preferred(self):
        ways = [self.way(1, [(16.0, 52.0), (15.0005, 52.0)], name="Rzeszów–Chmielnicka"),
                self.way(2, [(15.0005, 52.0), (14.0, 52.0)], name="Хмельницька АЕС")]
        self.assertEqual(pse.find_crossings(ways, self.COUNTRIES)[0][0]["name"], "Rzeszów–Chmielnicka")


class FlowGeoTest(unittest.TestCase):
    def test_flat_rounds_and_simplifies(self):
        self.assertEqual(flat([(0, 0), (1.04, 0.01), (2.0, 0)]), [0.0, 0.0, 2.0, 0.0])

    def test_clip_to_rect(self):
        pts, clipped = clip_to_rect([(5, 5), (5, -5)], 10, 10)
        self.assertTrue(clipped)
        self.assertEqual(pts[-1], (5.0, 0.0))
        self.assertEqual(clip_to_rect([(1, 1), (2, 2)], 10, 10), ([(1, 1), (2, 2)], False))

    def test_arc_bows_to_opposite_sides(self):
        ab = arc((0, 0), (10, 0))
        ba = arc((10, 0), (0, 0))
        self.assertEqual(ab[0], (0.0, 0.0))
        self.assertEqual(ab[-1], (10.0, 0.0))
        self.assertLess(ab[8][1], 0)
        self.assertGreater(ba[8][1], 0)

    def test_bearing(self):
        self.assertEqual(bearing_deg((0, 0), (0, -1)), 0.0)  # up = north
        self.assertEqual(bearing_deg((0, 0), (1, 0)), 90.0)


class MigrationTest(unittest.TestCase):
    def doc(self, rows):
        return {"results": [{"id": uid, "name": name, "values": vals} for uid, name, vals in rows]}

    def test_variable_is_destination_unit_is_origin(self):
        names = {"3804": "mazowieckie", "3800": "lubelskie"}
        docs = {
            "3804": self.doc([("071400000000", "MAZOWIECKIE", [{"year": "2024", "val": 0, "attrId": 0}]),
                              ("060600000000", "LUBELSKIE", [{"year": "2024", "val": 4657, "attrId": 1}])]),
            "3800": self.doc([("071400000000", "MAZOWIECKIE", [{"year": "2024", "val": 1200, "attrId": 1}]),
                              ("060600000000", "LUBELSKIE", [{"year": "2024", "val": 0, "attrId": 0}])]),
        }
        matrix, units = od.parse_matrix(docs, names)
        self.assertEqual(matrix[2024], {("06", "14"): 4657, ("14", "06"): 1200})
        self.assertEqual(units["14"], "MAZOWIECKIE")
        bal = od.balances(matrix[2024])
        self.assertEqual(bal["14"], {"in": 4657, "out": 1200, "net": 3457})

    def test_qualified_value_is_null(self):
        self.assertIsNone(od.value({"year": "2024", "val": 5, "attrId": 2}))
        self.assertEqual(od.value({"year": "2024", "val": 5, "attrId": 1}), 5)

    def test_parse_variables_drops_total(self):
        doc = {"results": [{"id": 79243, "n1": "ogółem"}, {"id": 3798, "n1": "dolnośląskie"}]}
        self.assertEqual(od.parse_variables(doc), {"3798": "dolnośląskie"})

    def test_capitals_use_the_voivode_seat(self):
        states = [{"fips": "04", "name": "Kujawsko-Pomorskie",
                   "capitals": [{"gmina": "0461011", "role": "voivode"}, {"gmina": "0463011", "role": "sejmik"}]}]
        cities = [{"gmina": "0461011", "name": "Bydgoszcz", "x": 1, "y": 2},
                  {"gmina": "0463011", "name": "Toruń", "x": 3, "y": 4}]
        self.assertEqual(migration.capitals(states, cities)["04"]["name"], "Bydgoszcz")


class LocalFinanceTest(unittest.TestCase):
    HEAD = [
        ["title"] + [None] * 20,
        ["WK", "PK", "GK", "GT", "typ", "kodGUS", "Nazwa JST", "Dochód PIT naliczony na 2026 r. ",
         "Dochód CIT naliczony na 2026 r. ", "KWOTA KALKULACYJNA", "Potrzeby finansowe ", "z tego:", None, None, None,
         None, "Korekta z tytułu zamożnosci ", "2026  KWOTY NALEŻNE", None, None, None],
        [None] * 11 + ["potrzeby wyrównawcze", "potrzeby ekologiczne", "potrzeby rozwojowe", "potrzeby oświatowe",
                       "potrzeby uzupełniające", None, "PIT należny", "CIT należny", "Subwencja należna", "RAZEM"],
    ]
    ROWS = [
        [2, 1, 3, 2, "G", 201032, "GROMADKA", 18058569, 1190344, 1, 14160786, 0, 1769026, 1518486, 7850130, 3023144,
         7655034, 13906948, 1190344, 0, 15097292],
        [14, 65, 0, 0, "M", 1465000, "m. st. Warszawa", 15008095026, 3374553800, 1, 6771300679, 0, 1757868, 456029610,
         6313513201, 0, 941414099, 15008095026, 3374553800, 302443273, 18685092099],
        [2, 1, 0, 0, "P", 201000, "bolesławiecki", 1, 2, 3, 4, 0, 0, 0, 4, 0, 0, 1, 2, 3, 6],
        [2, 0, 0, 0, "W", 200000, "dolnośląskie", 1, 2, 3, 4, 0, 0, 0, 4, 0, 0, 1, 2, 3, 6],
    ]

    def test_parse_levels_and_codes(self):
        units = mf.parse(self.HEAD + self.ROWS)
        self.assertEqual(sorted(units["gmina"]), ["0201032", "1465011"])
        self.assertEqual(units["gmina"]["1465011"]["wealth_correction"], 941414099)
        self.assertEqual(units["gmina"]["1465011"]["subsidy_due"], 302443273)
        self.assertEqual(units["gmina"]["0201032"]["pit_due"], 13906948)
        self.assertEqual(list(units["powiat"]), ["0201"])
        self.assertEqual(list(units["voivodeship"]), ["02"])

    def test_header_change_fails(self):
        head = [list(r) for r in self.HEAD]
        head[2][19] = "Subwencja"
        with self.assertRaises(RuntimeError):
            mf.parse(head + self.ROWS)

    def test_remap_type_digit(self):
        rows, moved = mf.remap_gminas({"0201032": {"a": 1}, "0201011": {"a": 2}}, {"0201033", "0201011"})
        self.assertEqual(sorted(rows), ["0201011", "0201033"])
        self.assertEqual(moved, ["0201032->0201033"])


class BuilderHelpersTest(unittest.TestCase):
    def test_group_mix(self):
        gen = {"B05": [1.0, 2.0], "B19": [3.0, None], "B18": [1.0, 1.0], "B99": [5.0, 5.0]}
        mix = power.group_mix(gen, 2)
        self.assertEqual(mix["hard_coal"], [1.0, 2.0])
        self.assertEqual(mix["wind"], [4.0, None])
        self.assertEqual(mix["other"], [5.0, 5.0])  # unknown codes go to other
        self.assertNotIn("gas", mix)

    def test_seconds(self):
        self.assertEqual(power.seconds("14:15"), 51300)
        self.assertIsNone(power.seconds(None))

    def test_checks_on_tiny_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for mod in (power, migration, money):
                self.assertEqual(mod.check(d)[0][0], "NOTE")
            (d / "money.json").write_text(json.dumps({
                "version": 1, "rules": ["r"], "sources": ["s"], "fields": [{"key": "pit"}, {"key": "total"}],
                "units": [{"code": "1", "level": "gmina", "pit": 1, "cit": 1, "subsidy": 1, "total": 9}]}))
            self.assertEqual(money.check(d)[0][0], "FAIL")


if __name__ == "__main__":
    unittest.main()

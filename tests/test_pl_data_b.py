"""Parsing and allocation rules of the identity, population history, commuting, EU funds and historic border sources."""

import unittest

from pipeline.build.commuting import pick
from pipeline.build.lenses_more_b import gmina_values
from pipeline.sources.pl_eu_funds import GminaIndex, allocate, parse_place
from pipeline.sources.pl_flows_commuting import gmina_code, internal_flows, parse_matrix, parse_totals
from pipeline.sources.pl_hist_borders import shared_lines, simplify, valid_on
from pipeline.sources.pl_hist_population import field_key, gmina_rows, on_current_codes
from pipeline.sources.pl_identity import identity_record, parse_gmina_table


class IdentityTest(unittest.TestCase):
    ROWS = [
        [None, "Województwo", "Powiat", "Gmina", "Kod gminy", "Identyfikacja", "W liczbach", "W procentach"],
        [None, "ŚLĄSKIE", "raciborski", "gm. w. Krzanowice", "2412022", "Ogółem", 1000, 100],
        [None, None, None, None, "2412022", "Polska", 700, 70],
        [None, None, None, None, "2412022", "Inna niż polska\n       w tym:", 480, 48],
        [None, None, None, None, "2412022", "       śląska", 460, 46],
        [None, None, None, None, "2412022", "       niemiecka", 120, 12],
        [None, None, None, None, "2412022", "       śląsko-cieszyńska", 500, 50],
        [None, None, None, None, "2412022", "Nieustalona", 15, 1.5],
        [None, "1 W tablicy zaprezentowano dane ... co najmniej 10 osób."],
    ]

    def test_parse_and_shares(self):
        t = parse_gmina_table(self.ROWS)
        self.assertEqual(list(t), ["2412022"])
        self.assertEqual(t["2412022"]["slaska"], 460)
        self.assertEqual(t["2412022"]["inna_niz_polska"], 480)
        rec = identity_record(t["2412022"])
        self.assertEqual(rec["silesian_share"], 46.0)
        self.assertEqual(rec["german"], 120)
        self.assertIsNone(rec["kashubian"])  # fewer than 10: not listed, stays null
        self.assertIsNone(rec["kashubian_share"])
        # the separate 'slasko-cieszynska' answer and 'Nieustalona' are not one identity
        self.assertEqual(rec["largest_minority"], "silesian")

    def test_no_minority(self):
        rec = identity_record({"ogolem": 50, "polska": 50})
        self.assertIsNone(rec["largest_minority"])

    def test_other_identity(self):
        rec = identity_record({"ogolem": 500, "polska": 480, "angielska": 12})
        self.assertEqual(rec["largest_minority"], "other")
        self.assertEqual(rec["largest_minority_label"], "angielska")


class PopulationHistoryTest(unittest.TestCase):
    def test_gmina_rows_and_codes(self):
        sheets = [[["Polska", "", 38000000], ["M.Bolesławiec", "0201011", 39000], ["M.Kępice", 2212054, 3207],
                   ["G.Kobylnica", "2212065", 9415], ["M-W.Kobylnica", 2212063, 14589], ["0 - 4", "   ", 300]]]
        rows = gmina_rows(sheets)
        self.assertEqual(rows, {"0201011": 39000, "2212063": 14589})  # town and rural parts (4, 5) left out

    def test_on_current_codes(self):
        out = on_current_codes({"0601052": 100, "0201011": 5}, ["0601053", "0201011", "1207132"])
        self.assertEqual(out, {"0601053": 100, "0201011": 5, "1207132": None})

    def test_field_key(self):
        self.assertEqual(field_key("2019-12-31"), "pop_2019")
        self.assertEqual(field_key("2026-06-30"), "pop_2026_06")


class CommutingTest(unittest.TestCase):
    MATRIX = [
        ["Kod gminy zamieszkania", "Nazwa", "Kod gminy pracy", "Nazwa", "Dojeżdżający"],
        ["0201044", "Nowogrodziec - miasto", "0201011", "Bolesławiec", 100],
        ["0201045", "Nowogrodziec - obszar wiejski", "0201011", "Bolesławiec", 50],
        ["0201045", "Nowogrodziec - obszar wiejski", "0201044", "Nowogrodziec - miasto", 30],
        ["0201011", "Bolesławiec", "0201044", "Nowogrodziec - miasto", 7],
    ]

    def test_parts_add_up(self):
        self.assertEqual(gmina_code("0201044"), "0201043")
        self.assertEqual(gmina_code("1465011"), "1465011")
        flows = parse_matrix(self.MATRIX)
        self.assertEqual(flows, {("0201043", "0201011"): 150, ("0201011", "0201043"): 7})
        self.assertEqual(internal_flows(self.MATRIX), {"0201043": 30})

    def test_totals(self):
        tot = parse_totals([["Kod", "Nazwa", "Przyjeżdżający"], ["0201044", "m", 40], ["0201045", "w", 2]])
        self.assertEqual(tot, {"0201043": 42})

    def test_pick_rule(self):
        flows = [{"from": "1418043", "to": "1465011", "value": 15550}, {"from": "1465011", "to": "1465011", "value": 9e9},
                 {"from": "1417011", "to": "1465011", "value": 100}, {"from": "1434011", "to": "1465011", "value": 400}]
        got = pick(flows, "146501")
        self.assertEqual([f["from"] for f in got], ["1418043", "1434011"])


class EuFundsTest(unittest.TestCase):
    TERYT = {"powiaty": [{"code": "0601", "name": "Powiat bialski"}, {"code": "0661", "name": "Powiat m. Biała Podlaska"}],
             "gminy": [{"code": "0661011", "name": "Biała Podlaska", "type": "urban"},
                       {"code": "0601032", "name": "Biała Podlaska", "type": "rural"},
                       {"code": "0601011", "name": "Międzyrzec Podlaski", "type": "urban"},
                       {"code": "0601082", "name": "Międzyrzec Podlaski", "type": "rural"}]}

    def test_parse_place(self):
        p = parse_place("WOJ.: LUBELSKIE, POW.: bialski, GM.: Biała Podlaska - Gmina wiejska")
        self.assertEqual(p, {"voiv": "06", "powiat": "bialski", "gmina": "Biała Podlaska - Gmina wiejska"})
        self.assertEqual(parse_place("WOJ.: LUBELSKIE, POW.: bialski")["gmina"], None)

    def test_match_and_allocate(self):
        idx = GminaIndex(self.TERYT)
        self.assertEqual(idx.find("06", "bialski", "Biała Podlaska - Gmina wiejska"), "0601032")
        self.assertEqual(idx.find("06", "Biała Podlaska", "Biała Podlaska"), "0661011")
        self.assertEqual(idx.find("06", "bialski", "Międzyrzec Podlaski"), "0601011")
        row = [None] * 16
        two = list(row)
        two[13], two[15] = 1000.0, ("WOJ.: LUBELSKIE, POW.: bialski, GM.: Międzyrzec Podlaski | "
                                    "WOJ.: LUBELSKIE, POW.: Biała Podlaska, GM.: Biała Podlaska")
        nation = list(row)
        nation[13], nation[15] = 500.0, "Cały Kraj"
        powiat = list(row)
        powiat[13], powiat[15] = 70.0, "WOJ.: LUBELSKIE, POW.: bialski"
        eu, count, st = allocate([two, nation, powiat], idx)
        self.assertEqual(eu, {"0601011": 500.0, "0661011": 500.0})
        self.assertEqual(count["0601011"], 0.5)
        self.assertEqual(st["country"], 500.0)
        self.assertEqual(st["powiat_only"], 70.0)
        self.assertEqual(st["total"], 1570.0)


class BordersTest(unittest.TestCase):
    def test_valid_on(self):
        p = {"gwsyear": 1914, "gwsmonth": 4, "gwsday": 17, "gweyear": 1917, "gwemonth": 12, "gweday": 5}
        self.assertTrue(valid_on(p, (1914, 7, 1)))
        self.assertFalse(valid_on(p, (1918, 1, 1)))

    def test_shared_edge_only(self):
        # Two squares sharing the edge x = 19 from lat 50 to 51; A's other sides are a "coast".
        a = [[[18.0, 50.0], [19.0, 50.0], [19.0, 51.0], [18.0, 51.0], [18.0, 50.0]]]
        b = [[[19.0, 50.0], [20.0, 50.0], [20.0, 51.0], [19.0, 51.0], [19.0, 50.0]]]
        lines = shared_lines(a, b, box=(10, 40, 30, 60))
        self.assertEqual(len(lines), 1)
        self.assertTrue(all(abs(x - 19.0) < 1e-9 for x, _ in lines[0]))

    def test_simplify_keeps_ends(self):
        line = [[19.0, 50.0], [19.00001, 50.5], [19.0, 51.0]]
        self.assertEqual(simplify(line, 0.4), [[19.0, 50.0], [19.0, 51.0]])


class LensValuesTest(unittest.TestCase):
    def test_per_resident_and_percent(self):
        cache = {
            ("payload", "src"): {"data": {"tables": {"t": {"rows": {"0201011": {"x": 50.0}}},
                                                     "p": {"rows": {"0201011": {"pop": 200}}}}}},
        }
        spec_pct = {"source": "src", "table": "t", "field": "x", "format": "pct"}
        self.assertEqual(gmina_values(spec_pct, ["0201011", "0201022"], cache), [0.5, None])
        spec_per = {"source": "src", "table": "t", "field": "x", "format": "float", "per": ("src", "p", "pop"),
                    "scale_by": 1000}
        self.assertEqual(gmina_values(spec_per, ["0201011"], cache), [250.0])


if __name__ == "__main__":
    unittest.main()

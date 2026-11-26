"""pl_soc_parks and pl_soc_universities parsing and joining helpers."""

import unittest

from pipeline.sources import pl_soc_parks as parks
from pipeline.sources import pl_soc_universities as uni


class ParksTest(unittest.TestCase):
    def test_park_key(self):
        self.assertEqual(parks.park_key("S\u0142owi\u0144skia \u2026\u2026\u2026\u2026.\u2026\u2026\u2026\u2026"), "slowinski")
        self.assertEqual(parks.park_key("Park Narodowy G\u00f3r Sto\u0142owych"), "gor_stolowych")
        self.assertEqual(parks.park_key("Park Narodowy \u201eUj\u015bcie Warty\u201d"), "ujscie_warty")
        self.assertEqual(parks.park_key("Tatrza\u0144ski Park Narodowy"), "tatrzanski")
        self.assertEqual(parks.park_key("Bory Tucholskie"), "bory_tucholskie")

    def test_gus_table(self):
        rows = [
            {"A": "PARK NARODOWY NATIONAL PARK", "M": "Liczba turyst\u00f3w"},
            {"A": "O G \u00d3 \u0141 E M", "M": "16390.532"},
            {"A": "Tatrza\u0144ski", "M": "5091.772"},
            {"A": "Narwia\u0144ski", "D": "\u2013", "M": "31.4"},
            {"A": "Bia\u0142owieski", "M": "\u2013"},
            {"A": "a Footnote text.", "M": ""},
        ]
        t = parks.gus_table(rows, "M")
        self.assertEqual(t, {"tatrzanski": 5091.772, "narwianski": 31.4, "bialowieski": None})

    def test_parse_point(self):
        self.assertEqual(parks.parse_point("Point(19.933333 49.25)"), (19.933333, 49.25))
        self.assertIsNone(parks.parse_point(""))


class UniversitiesTest(unittest.TestCase):
    def test_name_keys(self):
        k = uni.name_keys("UNIWERSYTET JAGIELLO\u0143SKI W KRAKOWIE")
        self.assertEqual(k[0], "uniwersytet_jagiellonski_w_krakowie")
        self.assertIn("uniwersytet_jagiellonski", k)
        k = uni.name_keys("Uniwersytet im. Adama Mickiewicza w Poznaniu")
        self.assertIn("uniwersytet_w_poznaniu", k)
        self.assertEqual(uni.name_keys("Szko\u0142a X w likwidacji")[0], "szkola_x")
        self.assertEqual(uni.name_keys("Wy\u017csza Szko\u0142a Medyczna w Legnicy z siedzib\u0105 w Legnicy")[0],
                         "wyzsza_szkola_medyczna_w_legnicy")
        self.assertEqual(uni.name_keys("Akademia X imienia genera\u0142a Y Z")[0], "akademia_x_im_gen_y_z")

    def test_unique_index_drops_ambiguous_short_keys(self):
        a, b = {"id": "a"}, {"id": "b"}
        idx = uni.unique_index([(a, ["Uniwersytet Ekonomiczny w Poznaniu"]),
                                (b, ["Uniwersytet Ekonomiczny w Krakowie"])])
        self.assertIs(idx["uniwersytet_ekonomiczny_w_poznaniu"], a)
        self.assertNotIn("uniwersytet_ekonomiczny", idx)  # two candidates
        idx = uni.unique_index([(a, ["Uniwersytet Jagiello\u0144ski w Krakowie"])])
        self.assertIs(idx["uniwersytet_jagiellonski"], a)

    def test_city_ok_and_units(self):
        self.assertTrue(uni.city_ok("Uniwersytet Jagiello\u0144ski", ["Krak\u00f3w"]))
        self.assertTrue(uni.city_ok("Akademia Nauk Stosowanych w Pile", ["Pi\u0142a"]))
        self.assertTrue(uni.city_ok("Uniwersytet Ekonomiczny we Wroc\u0142awiu", ["Wroc\u0142aw"]))
        self.assertFalse(uni.city_ok("Wy\u017csza Szko\u0142a X w Inowroc\u0142awiu", ["Warszawa"]))
        self.assertTrue(uni.is_unit_label("Wydzia\u0142 Farmaceutyczny Uniwersytetu Medycznego"))
        self.assertFalse(uni.is_unit_label("Uniwersytet Medyczny w Lublinie"))

    def test_domain(self):
        self.assertEqual(uni.domain("https://www.uj.edu.pl/"), "uj.edu.pl")
        self.assertEqual(uni.domain("pw.edu.pl"), "pw.edu.pl")
        self.assertIsNone(uni.domain(None))

    def test_gus_institutions(self):
        base = {"D": "og\u00f3\u0142em", "E": "Og\u00f3\u0142em", "F": "Og\u00f3\u0142em", "G": "Og\u00f3\u0142em", "H": "a"}
        rows = [
            {**base, "A": "Polska", "B": "Og\u00f3\u0142em", "C": "Og\u00f3\u0142em", "I": "100"},
            {**base, "A": "Ma\u0142opolskie", "B": "Og\u00f3\u0142em", "C": "Og\u00f3\u0142em", "I": "60"},
            {**base, "A": "Ma\u0142opolskie", "B": "UNIWERSYTET X", "C": "Krak\u00f3w", "I": "50"},
            {**base, "A": "Ma\u0142opolskie", "B": "UNIWERSYTET X", "C": "Tarn\u00f3w", "I": "10"},
            {**base, "A": "REGION WARSZAWSKI STO\u0141ECZNY", "B": "SZKO\u0141A Y", "C": "Warszawa", "I": "40"},
            {**base, "A": "Mazowieckie", "B": "SZKO\u0141A Y", "C": "Warszawa", "I": "40"},
            {**base, "A": "Mazowieckie", "B": "SZKO\u0141A Z", "C": "Warszawa", "I": "-"},
            {**base, "A": "Mazowieckie", "B": "SZKO\u0141A W", "C": "Warszawa", "I": "."},
            {**base, "A": "Mazowieckie", "B": "SZKO\u0141A Y", "C": "Warszawa", "I": "40", "H": "b"},
            {**base, "A": "Mazowieckie", "B": "SZKO\u0141A Y", "C": "Warszawa", "I": "40", "D": "zdrowie"},
        ]
        inst, national = uni.gus_institutions(rows)
        self.assertEqual(national, 100)
        self.assertEqual(inst["UNIWERSYTET X"]["campuses"], {"Krak\u00f3w": 50, "Tarn\u00f3w": 10})
        self.assertEqual(inst["SZKO\u0141A Y"]["campuses"], {"Warszawa": 40})  # region duplicate dropped
        self.assertNotIn("SZKO\u0141A Z", inst)  # no students
        self.assertEqual(inst["SZKO\u0141A W"]["campuses"], {"Warszawa": None})  # withheld -> None

    def test_newest_categories(self):
        recs = [{"institutionUuid": "a", "evaluationYear": 2022, "evaluationPeriod": "2017-2021",
                 "disciplines": [{"disciplineName": "x", "category": "B+"}, {"disciplineName": "y", "category": "A"}]},
                {"institutionUuid": "a", "evaluationYear": 2026, "evaluationPeriod": "2022-2025",
                 "disciplines": [{"disciplineName": "x", "category": "A+"}]}]
        self.assertEqual(uni.newest_categories(recs),
                         {"a": {"x": ("A+", "2022-2025"), "y": ("A", "2017-2021")}})

if __name__ == "__main__":
    unittest.main()

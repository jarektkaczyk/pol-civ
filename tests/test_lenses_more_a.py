import unittest

from pipeline.build.lenses_more_a import LENSES_A, lens_values


class FakeStats:
    def __init__(self, tables):
        self.tables = tables
        self.payload = {source: {} for source, _ in tables}

    def rows(self, source, table):
        return self.tables.get((source, table), {})


class MoreLensesTest(unittest.TestCase):
    def test_reads_powiat_values_for_each_gmina(self):
        data = next(spec[6]["_data"] for spec in LENSES_A if spec[0] == "dwelling_price_median")
        stats = FakeStats({("pl_stats_prosperity", "housing_prices_powiat"): {
            "1261": {"median_dwelling_price_m2": 15000},
        }})
        metric, values = lens_values(data, stats, ["1261011", "1261022", "0201011"])
        self.assertEqual("powiat", metric["level"])
        self.assertEqual([15000, 15000, None], values)

    def test_computes_candidate_named_vote_shift(self):
        data = next(spec[6]["_data"] for spec in LENSES_A if spec[0] == "vote_shift_2020_2025")
        stats = FakeStats({
            ("pl_soc_elections", "president_2025_r2"): {"1261011": {"nawrocki_share": 42.0}},
            ("pl_soc_elections", "president_2020_r2"): {"1261011": {"duda_share": 36.5}},
        })
        _, values = lens_values(data, stats, ["1261011", "0201011"])
        self.assertAlmostEqual(5.5, values[0])
        self.assertIsNone(values[1])

    def test_each_lens_has_level_and_year_caveat(self):
        for lens_id, *_rest, extra in LENSES_A:
            note = extra.get("note", "")
            self.assertIn("Per ", note, lens_id)
            self.assertRegex(note, r"20\d\d", lens_id)


if __name__ == "__main__":
    unittest.main()

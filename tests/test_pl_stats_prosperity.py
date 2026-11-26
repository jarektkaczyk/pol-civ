import unittest

from pipeline.sources.pl_stats_prosperity import (
    build_housing_table,
    build_income_table,
    build_property_tables,
    build_tourism_table,
    positive_price,
)


class PlStatsProsperityTest(unittest.TestCase):
    def test_builds_ministry_income_per_person(self):
        income = [
            [2, 1, 1, 1, "G", 201011, "BOLESLAWIEC", 1000000],
            [14, 65, 0, 0, "M", 1465000, "WARSZAWA", 3000000],
            [2, 1, 0, 0, "P", 201000, "powiat", 999],
        ]
        indicators = [
            [2, 1, 1, 1, "G", 201011, "BOLESLAWIEC", 5224.08],
            [14, 65, 0, 0, "M", 1465000, "WARSZAWA", 9999.5],
        ]

        table = build_income_table(income, indicators, {"0201011": 4000, "1465011": 1000})

        self.assertEqual("gmina", table["level"])
        self.assertEqual(250, table["rows"]["0201011"]["pit_revenue_per_person"])
        self.assertEqual(3000, table["rows"]["1465011"]["pit_revenue_per_person"])
        self.assertEqual(5224.08, table["rows"]["0201011"]["tax_income_indicator_per_person"])
        self.assertNotIn("0201", table["rows"])

    def test_income_preserves_missing_population_as_null(self):
        income = [[2, 1, 1, 1, "G", 201011, "BOLESLAWIEC", 1000000]]
        table = build_income_table(income, [], {})
        self.assertIsNone(table["rows"]["0201011"]["pit_revenue_per_person"])

    def test_builds_voivodeship_housing_rate(self):
        housing = [[None, "Dolnoslaskie", 20, 15, 10]]
        populations = {"0201011": 1000, "0201022": 3000, "1465011": 2000}
        table = build_housing_table(housing, populations)
        self.assertEqual("voivodeship", table["level"])
        self.assertEqual(10, table["rows"]["02"]["dwellings_completed"])
        self.assertEqual(2.5, table["rows"]["02"]["dwellings_completed_per_1000"])

    def test_builds_voivodeship_tourism(self):
        beds = [["Pomorskie", None, 120000]]
        nights = [["Pomorskie", None, 11000000]]
        table = build_tourism_table(beds, nights)
        self.assertEqual(120000, table["rows"]["22"]["tourist_beds"])
        self.assertEqual(11000000, table["rows"]["22"]["overnight_stays"])

    def test_property_price_per_m2_remains_null(self):
        tables = build_property_tables([["Ogolem", 104.9, 216.8]])
        row = tables["housing_prices_country"]["rows"]["PL"]
        self.assertIsNone(row["average_dwelling_price_m2"])
        self.assertEqual(104.9, row["dwelling_price_index_2024_100"])
        self.assertEqual(216.8, row["dwelling_price_index_2015_100"])

    def test_zero_transaction_price_stays_null(self):
        self.assertIsNone(positive_price(0))
        self.assertEqual(14561, positive_price(14561))


if __name__ == "__main__":
    unittest.main()

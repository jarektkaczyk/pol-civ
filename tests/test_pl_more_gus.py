import unittest

from pipeline.sources.pl_more_gus import farm_area_denominators, farm_rows, parse_bdl_series
from pipeline.sources.pl_stats_prosperity import build_local_tourism, tourism_city_rates


class LocalGusTest(unittest.TestCase):
    def test_bdl_keeps_whole_units_and_preserves_suppression(self):
        records = [
            {"id": "011212001011", "values": [{"year": "2025", "val": 7.4, "attrId": 1}]},
            {"id": "011212001022", "values": [{"year": "2025", "val": 0, "attrId": 91}]},
            {"id": "011212001033", "values": [{"year": "2024", "val": 8.3, "attrId": 1}]},
            {"id": "011212001034", "values": [{"year": "2025", "val": 23, "attrId": 1}]},
            {"id": "011212001035", "values": [{"year": "2025", "val": 10, "attrId": 1}]},
            {"id": "011212001042", "values": [{"year": "2025", "val": 0, "attrId": 1}]},
            {"id": "011212001052", "values": [{"year": "2025", "val": 0, "attrId": 0}]},
        ]
        self.assertEqual(
            parse_bdl_series(records, 6, 2025),
            {"1201011": 7.4, "1201022": None, "1201033": None, "1201042": 0, "1201052": 0},
        )

    def test_tourism_converts_units_and_adds_only_same_area_city_gminas(self):
        tables = build_local_tourism(
            {"1261": 4123.4, "1201": 1000, "1465": None},
            {"1261011", "1201011", "1465011"},
            {"1261011": 99.9, "1201011": 25.0},
        )
        powiat = tables["tourism_powiat"]["rows"]
        gmina = tables["tourism_gmina"]["rows"]
        self.assertAlmostEqual(powiat["1261"]["overnight_stays_per_person"], 4.1234)
        self.assertEqual(gmina, {
            "1261011": powiat["1261"],
            "1465011": powiat["1465"],
            "1201011": {"overnight_stays_per_person": 25.0},
        })

    def test_city_nights_use_total_nights_and_year_end_population(self):
        dimensions = [{"id-wymiar": 1101, "id-pozycja": 42, "symbol": "10023015717011"}]
        all_visitors = {
            "id-pozycja-1": 42,
            "id-pozycja-2": 6874517,
            "id-sposob-prezentacji-miara": 39,
            "id-brak-wartosci": 253,
            "id-tajnosci": 43,
            "wartosc": 4.8,
        }
        domestic = {**all_visitors, "id-pozycja-2": 6874518, "wartosc": 2.4}
        self.assertEqual(tourism_city_rates(dimensions, [all_visitors, domestic], {"3017011": 6000}), {
            "3017011": 0.8,
        })

    def test_farm_land_share_uses_2020_territorial_denominator(self):
        denoms = farm_area_denominators([
            ["TERYT", None, "ha"],
            ["020101 2", "A", 2000],
            ["020102 3", "B", 400],
            ["020102 4", "B town", 150],
            ["020103 2", "C", 3000],
        ])
        rows = farm_rows(
            ["0201013", "0201023", "0201032", "0201042"],
            {"0201012": 14.2, "0201023": 18, "0201042": 12},
            {"0201012": 500, "0201023": 800, "0201032": 0},
            denoms,
        )
        self.assertEqual(rows["0201013"], {"average_farm_area_ha": 14.2, "farm_land_share": 25})
        self.assertIsNone(rows["0201023"]["farm_land_share"])
        self.assertEqual(rows["0201032"]["farm_land_share"], 0)
        self.assertIsNone(rows["0201042"]["farm_land_share"])

    def test_zero_average_with_no_holding_stays_null(self):
        rows = farm_rows(["0201012"], {"0201012": 0}, {"0201012": 0}, {"0201012": 100})
        self.assertIsNone(rows["0201012"]["average_farm_area_ha"])
        self.assertEqual(0, rows["0201012"]["farm_land_share"])


if __name__ == "__main__":
    unittest.main()

"""pl_soc_health: BDL unit ids, value grouping and rates."""

import unittest

from pipeline.sources import pl_soc_health as h


class HealthTest(unittest.TestCase):
    def test_unit_to_powiat(self):
        self.assertEqual(h.unit_to_powiat("011213061000"), "1261")  # Krakow city powiat
        self.assertEqual(h.unit_to_powiat("011212001000"), "1201")
        self.assertIsNone(h.unit_to_powiat("12"))

    def test_values_by_year_and_rate(self):
        pages = [{"results": [
            {"id": "011213061000", "values": [{"year": 2025, "val": 5000}, {"year": 2024, "val": None}]},
            {"id": "011212001000", "values": [{"year": 2025, "val": 100}]},
        ]}]
        v = h.values_by_year(pages)
        self.assertEqual(v, {2025: {"1261": 5000.0, "1201": 100.0}})
        self.assertEqual(h.per_10k(100, 105000), 9.5)
        self.assertIsNone(h.per_10k(None, 1000))
        self.assertIsNone(h.per_10k(5, 0))


if __name__ == "__main__":
    unittest.main()

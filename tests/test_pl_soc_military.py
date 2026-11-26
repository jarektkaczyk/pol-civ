"""pl_soc_military: curated list sanity and garrison counts."""

import unittest

from pipeline.sources import pl_soc_military as m
from pipeline.sources.pl_soc_common import load_curated, voivodeship_code


class MilitaryTest(unittest.TestCase):
    def test_curated_items_are_complete_and_in_poland(self):
        items = load_curated(m.__file__, "pl_soc_military.json")["items"]
        ids = [i["id"] for i in items]
        self.assertEqual(len(ids), len(set(ids)))
        for it in items:
            self.assertTrue(it["ref"].startswith("https://"), it["id"])
            self.assertTrue(13.6 < it["lon"] < 24.6 and 48.75 < it["lat"] < 55.15, it["id"])
            self.assertIsNotNone(voivodeship_code(it["voivodeship"]), it["id"])
            self.assertNotEqual(it["status"], "planned")

    def test_garrison_counts(self):
        items = [
            {"id": "a", "kind": "unit_land", "garrison": "X", "voivodeship": "pomorskie"},
            {"id": "b", "kind": "air_base", "garrison": "X", "voivodeship": "pomorskie"},
            {"id": "c", "kind": "allied_site", "garrison": "Y", "voivodeship": "pomorskie"},
            {"id": "d", "kind": "unit_navy", "garrison": "Z", "voivodeship": "zachodniopomorskie"},
        ]
        self.assertEqual(m.garrison_counts(items), {
            "22": {"garrison_towns": 1, "units": 1, "bases": 1},
            "32": {"garrison_towns": 1, "units": 1, "bases": 0},
        })


if __name__ == "__main__":
    unittest.main()

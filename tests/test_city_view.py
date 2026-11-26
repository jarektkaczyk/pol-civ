"""Builder helpers for the City view, Explorer and Advisors: footprints, ranks, peers, metros,
resource summaries and voivodeship land shares (pure functions on tiny inputs)."""

import unittest

from pipeline.build import cities, counties, resources, states


class FootprintTest(unittest.TestCase):
    def test_majority_of_samples(self):
        world = {
            "owner": [0, 0, 0, -1],
            "counties": ["1261011", "1206011", "1206022"],
            # cell 0: 4 of 7 in A -> A; cell 1: 3 A + 3 B + 1 none -> nobody; cell 2: all B; cell 3: water
            "county_samples": [[0, 0, 1, 1, -1, 0, 0], [0, 0, 0, 2, 2, 2, -1], [2] * 7, []],
        }
        members = {"A": ["1261011", "1206011"], "B": ["1206022"]}
        self.assertEqual(cities.footprints(world, members), {"A": {0}, "B": {2}})

    def test_water_cell_never_in_footprint(self):
        world = {"owner": [-1], "counties": ["1261011"], "county_samples": [[0] * 7]}
        self.assertEqual(cities.footprints(world, {"A": ["1261011"]}), {})


class RanksTest(unittest.TestCase):
    def city(self, id, pop, gdp, growth, food):
        return {"id": id, "population": pop, "gdp": gdp, "growth": growth,
                "yields": {"food": food, "production": 1, "gold": gdp, "science": None, "culture": 1}}

    def test_ranks_and_peers(self):
        cs = [self.city("A", 1000, 100.0, 0.01, 5), self.city("B", 500, 100.0, None, 9),
              self.city("C", 450, None, 0.05, 1), self.city("D", 100, 1.0, 0.02, 1)]
        cities.add_ranks(cs, cs[:3])
        r = {c["id"]: c["ranks"] for c in cs}
        self.assertEqual([r[i]["population"] for i in "ABCD"], [1, 2, 3, 4])
        self.assertEqual([r[i]["gdp_per_capita"] for i in "ABCD"], [2, 1, None, 3])
        self.assertEqual([r[i]["growth"] for i in "ABCD"], [3, None, 1, 2])
        self.assertEqual([r[i]["food"] for i in "ABCD"], [2, 1, 3, 4])  # tie C/D keeps population order
        self.assertIsNone(r["A"]["science"])
        self.assertEqual(set(r["A"]), set(cities.RANK_KEYS))
        self.assertEqual(cs[1]["peers"], ["C", "A"])  # by ratio: 450/500 is closer than 1000/500
        self.assertEqual(cs[3]["peers"], [])  # not in the peer pool (no City View)


class MetroGroupsTest(unittest.TestCase):
    def test_published_merges(self):
        fua = {"fuas": {"PL006F": {"name": "Gdańsk", "gminas": ["226101", "226401"]},
                        "PL053F": {"name": "Gdynia", "gminas": ["226201"]},
                        "PL003F": {"name": "Kraków", "gminas": ["126101"]}}}
        by6 = {"226101": "2261011", "226401": "2264011", "226201": "2262011", "126101": "1261011"}
        groups = {g["id"]: g for g in cities.metro_groups(fua, by6)}
        self.assertEqual(set(groups), {"PL006F", "PL003F"})
        self.assertEqual(groups["PL006F"]["name"], "Trójmiasto")
        self.assertEqual(groups["PL006F"]["gminas"], ["2261011", "2262011", "2264011"])
        self.assertEqual(groups["PL006F"]["fuas"], ["PL006F", "PL053F"])


class ResourceSummaryTest(unittest.TestCase):
    def test_summary(self):
        types = [{"id": "wind", "unit": "MW"}, {"id": "oil", "unit": "km² play area"}, {"id": "gold", "unit": "employees"}]
        items = [{"type": "wind", "value": 500, "state": "TX"}, {"type": "wind", "value": 700.4, "state": "TX"},
                 {"type": "wind", "value": 600, "state": "IA"}, {"type": "oil", "value": 9000, "state": "TX"},
                 {"type": "oil", "value": 9000, "state": "TX"}]
        s = resources.summarize(items, types)
        self.assertEqual(s["national"]["wind"], {"count": 3, "value": 1800, "unit": "MW"})
        self.assertEqual(s["national"]["oil"], {"count": 2, "value": None, "unit": "km² play area"})
        self.assertEqual(s["national"]["gold"], {"count": 0, "value": 0, "unit": "employees"})
        self.assertEqual(list(s["states"]), ["IA", "TX"])
        self.assertEqual(s["states"]["TX"]["wind"]["value"], 1200)
        self.assertNotIn("gold", s["states"]["TX"])
        self.assertTrue(s["note"])


class StateLandTest(unittest.TestCase):
    def test_land_shares(self):
        keys = states.PCT_KEYS
        world = {"owner": [0, 0, 0, 1], "cover": [1, 7, 0, 1],
                 "pct": {k: ([100, 50, 0, 10] if k == "forest" else [0, 50, 0, 0] if k == "crop" else [0] * 4) for k in keys}}
        land = states.land_shares(world, 0)  # cell 2 has no land-cover samples: left out
        self.assertEqual(land["forest"], 0.75)
        self.assertEqual(land["crop"], 0.25)
        self.assertIsNone(states.land_shares(world, 5))


class CountyFieldsTest(unittest.TestCase):
    def test_fields_unique_and_described(self):
        fields = counties.gmina_fields()
        keys = [f["key"] for f in fields]
        self.assertEqual(len(keys), len(set(keys)))
        for k in ("geoid", "name", "powiat", "state", "population", "density", "pit", "wage", "unemployment",
                  "president_2025", "forest", "cbsa", "cell"):
            self.assertIn(k, keys)
        for f in fields:
            if f["level"] in ("powiat", "voivodeship") and f["key"] in counties.METRIC:
                self.assertIn("Published per", f["description"])


if __name__ == "__main__":
    unittest.main()

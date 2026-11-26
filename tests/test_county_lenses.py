"""Polish people and economy: sources (FUA, towns), shared helpers, yields, lenses, citizens and districts."""

import unittest

from pipeline.build import citizens, counties, districts, lenses, plstats
from pipeline.build.yields import Economy
from pipeline.sources import pl_geo_fua, pl_geo_places


class FuaSourceTest(unittest.TestCase):
    def test_lau_code_to_teryt6(self):
        self.assertEqual(pl_geo_fua.teryt6_of_lau("1001121216101"), "126101")  # Krakow, GISCO form
        self.assertEqual(pl_geo_fua.teryt6_of_lau("PL_1001121216101"), "126101")
        self.assertEqual(pl_geo_fua.teryt6_of_lau("1261011"), "126101")
        self.assertIsNone(pl_geo_fua.teryt6_of_lau("abc"))

    def test_header_row(self):
        rows = [["title"], ["NUTS3", "LAU CODE", "FUA ID", "FUA_NAME"], ["PL213", "1001121216101", "PL003F", "Kraków"]]
        h, col = pl_geo_fua.find_header(rows, "LAU CODE", "FUA ID")
        self.assertEqual((h, col), (1, {"LAU CODE": 1, "FUA ID": 2}))


class PlacesSourceTest(unittest.TestCase):
    def test_fold_handles_l_stroke(self):
        self.assertEqual(pl_geo_places.fold("Łódź"), "lodz")
        self.assertEqual(pl_geo_places.fold("Głogów Małopolski"), "glogow malopolski")

    def test_gus_towns(self):
        rows = [["126101 1", "Kraków", "Kraków", 32687, 327, 816614, 2498],
                ["146501 1", "m.st. Warszawa", "M.st. Warszawa", 51720, 517, 1866729, 3609],
                ["022401 4", "Bardo", "Ząbkowicki", 471, 5, 2239, 475], ["", "WOJ. X", None]]
        towns = {t["code"]: t for t in pl_geo_places.gus_towns(rows)}
        self.assertEqual(set(towns), {"1261011", "1465011", "0224014"})
        self.assertEqual(towns["1465011"]["name"], "Warszawa")
        self.assertTrue(towns["1261011"]["powiat_rights"])
        self.assertFalse(towns["0224014"]["powiat_rights"])
        self.assertEqual(towns["0224014"]["gmina"], "0224013")

    def test_match_by_terc_then_name(self):
        towns = [{"code": "0224014", "name": "Bardo"}, {"code": "1261011", "name": "Kraków"},
                 {"code": "1001011", "name": "Nowhere"}]
        nodes = [{"lon": 16.74, "lat": 50.5, "tags": {"name": "Bardo", "teryt:terc": "0224014"}},
                 {"lon": 19.94, "lat": 50.06, "tags": {"name": "Kraków"}}]
        pos, missing = pl_geo_places.match_osm(towns, nodes)
        self.assertEqual(pos["0224014"], (16.74, 50.5))
        self.assertEqual(pos["1261011"], (19.94, 50.06))
        self.assertEqual(missing, ["1001011 Nowhere"])


class HelpersTest(unittest.TestCase):
    def test_median_from_groups(self):
        # 100 people: 50 in 0-4, 50 in 5-9 -> the median is the top of the first group
        self.assertEqual(plstats.median_from_groups([(0, 5, 50), (5, 10, 50), (10, None, 0)]), 5.0)
        self.assertEqual(plstats.median_from_groups([(0, 5, 10), (5, 10, 30), (10, None, 0)]), 6.7)
        self.assertIsNone(plstats.median_from_groups([(0, 5, None), (5, None, 5)]))
        self.assertIsNone(plstats.median_from_groups([(0, 5, 1), (5, None, 9)]))  # median in the open group

    def test_spread_population_weighted(self):
        weights = [[(0, 100.0), (1, 300.0)], [(1, 10.0)], []]
        self.assertEqual(plstats.spread(weights, [1.0, 3.0], 2), [2.5, 3.0, None])
        self.assertEqual(plstats.spread(weights, [None, 3.0]), [3.0, 3.0, None])

    def test_sums(self):
        self.assertIsNone(plstats.total([None, None]))
        self.assertEqual(plstats.total([1, None, 2]), 3)
        self.assertIsNone(plstats.full_sum([1, None]))


class EconomyTest(unittest.TestCase):
    """Two powiaty in one NUTS 3: a city with powiat rights (one gmina) and a land powiat of two gminas."""

    def setUp(self):
        world = {"counties": ["1261011", "1201011", "1201022"], "states": ["12"], "powiaty": ["1201", "1261"]}
        teryt = {"gminy": [{"code": g, "name": g, "type": "urban"} for g in world["counties"]],
                 "powiaty": [{"code": "1201", "name": "Powiat bocheński"}, {"code": "1261", "name": "Powiat m. Kraków"}],
                 "voivodeships": [{"code": "12", "name": "Małopolskie"}]}
        pkd = lambda tot, j, m, i, r: {"workers_total": tot, **{f"workers_{s}": 0 for s in "ABCDEFGHKLNOPQS"},
                                       "workers_A": 10, "workers_C": 100, "workers_J": j, "workers_M": m,
                                       "workers_I": i, "workers_R": r}
        tables = {
            "pl_stats_population": {"population": {"rows": {
                "1261011": {"population": 800, "population_2015": 700},
                "1201011": {"population": 100, "population_2015": 200},  # 2015 covers 1201022 too
                "1201022": {"population": 100, "population_2015": None}}}},
            "pl_stats_labour": {
                "employment_sectors_gmina": {"rows": {
                    "1261011": {"workers_total": 500, "workers_agriculture": 1, "workers_industry": 50, "workers_services": 449},
                    "1201011": {"workers_total": 60, "workers_agriculture": 5, "workers_industry": 25, "workers_services": 30},
                    "1201022": {"workers_total": 40, "workers_agriculture": 20, "workers_industry": 10, "workers_services": 10}}},
                "employment_pkd_powiat": {"rows": {"1261": pkd(600, 100, 50, 20, 10), "1201": pkd(100, 8, 2, 4, 0)}},
                "labour_powiat": {"rows": {"1261": {"average_gross_monthly_wage": 10000, "registered_unemployed": 10,
                                                    "registered_unemployment_rate": 2.5},
                                           "1201": {"average_gross_monthly_wage": 5000, "registered_unemployed": 5,
                                                    "registered_unemployment_rate": 5.0}}}},
            "pl_gdp": {"gdp_nuts3": {"rows": {"PL213": {"gdp_pln": 1300.0}}}},
        }
        payload = {s: {"data": {"tables": t}} for s, t in tables.items()}
        payload["pl_geo_fua"] = {"data": {"gminas": {"126101": {"nuts3": "PL213"}, "120101": {"nuts3": "PL213"},
                                                     "120102": {"nuts3": "PL213"}}}}
        self.units = plstats.Units(world, teryt)
        self.econ = Economy(self.units, plstats.Stats(list(payload), loader=lambda n: payload.get(n)))

    def test_gdp_shared_by_wage_bill_then_workers(self):
        # wage bills: Krakow 600 x 10000 = 6.0M, Bochnia 100 x 5000 = 0.5M -> 1200 and 100
        self.assertAlmostEqual(self.econ.powiat_gdp["1261"], 1200.0)
        self.assertAlmostEqual(self.econ.powiat_gdp["1201"], 100.0)
        self.assertEqual(self.econ.gmina_gdp["1201011"], 60)  # 60 of the powiat's 100 workers

    def test_science_shared_by_service_workers(self):
        self.assertEqual(self.econ.gmina_yields("1261011")["science"], 150)  # city powiat: J + M exactly
        self.assertEqual(self.econ.gmina_yields("1201011")["science"], 8)  # 10 x 30 / 40 service workers

    def test_profiles(self):
        city = self.econ.profile(["1261011"], powiaty=["1261"])
        self.assertEqual(city["yields"]["production"], 100)  # PKD B-F, not the sector table
        self.assertEqual(city["unemployment"], 0.025)
        self.assertAlmostEqual(city["growth"], 800 / 700 - 1, places=4)
        land = self.econ.profile(["1201011", "1201022"], powiaty=["1201"])
        self.assertAlmostEqual(land["growth"], 0.0)  # the new gmina is covered by its parent's 2015 figure
        self.assertIsNone(self.econ.profile(["1201022"])["growth"])
        self.assertEqual(self.units.powiat_label("1261"), "Kraków (city)")


class LensHelpersTest(unittest.TestCase):
    def test_nearest_station(self):
        st = [{"lon": 19.9, "lat": 50.06, "name": "A", "value": 20.0}, {"lon": 21.0, "lat": 52.2, "name": "B", "value": 9.0}]
        hit = counties.nearest_station(19.95, 50.06, st)
        self.assertEqual(hit[:2], (20.0, "A"))
        self.assertIsNone(counties.nearest_station(17.0, 54.0, st))

    def test_largest_committee(self):
        rec = {counties.SEJM[0][0]: 30.0, counties.SEJM[1][0]: 41.5, counties.SEJM[2][0]: None}
        self.assertEqual(counties.largest(rec, counties.SEJM), 1)
        self.assertIsNone(counties.largest({}, counties.SEJM))

    def test_dominant_category(self):
        weights = [[(0, 10.0), (1, 30.0)], [(0, 5.0)], [(2, 1.0)]]
        self.assertEqual(lenses.dominant(weights, [0, 1, None]), [1, 0, None])

    def test_vote_ramp_is_neutral(self):
        lens = next(l for l in lenses.LENSES if l[0] == "vote")
        self.assertEqual(lens[4], "vote")
        self.assertNotIn("#B3262E", lenses.R["vote"])


class CitizensTest(unittest.TestCase):
    def test_largest_remainder(self):
        f = citizens.largest_remainder({"a": 1, "b": 1, "c": 1}, 10)
        self.assertEqual(sum(f.values()), 10)
        self.assertEqual(citizens.largest_remainder({"a": 0}, 5), {"a": 0})

    def test_rows(self):
        rec = {f"age_{a}_{a + 4}": 10 for a in range(0, 85, 5)} | {"age_85_plus": 10}
        ages = citizens.age_counts(rec)
        self.assertEqual(ages, {"child": 30, "young": 30, "midlife": 70, "elder": 50})
        row = citizens.make_row("age", ages, "Kraków")
        self.assertEqual(sum(row["figures"].values()), citizens.FIGURES["age"])
        self.assertIsNone(citizens.make_row("sex", {"female": None, "male": 3}, "x"))


class DistrictsTest(unittest.TestCase):
    nat = {"workers_total": 1000, **{f"workers_{s}": 50 for s in "ABCDEFGHIJKLMNOPQRS"}}

    def test_lq_and_rule(self):
        self.assertAlmostEqual(districts.lq(30, 100, 50, 1000), 6.0)
        rec = {"workers_total": 10000, **{f"workers_{s}": 400 for s in "ABCDEFGHIJKLMNOPQRS"}, "workers_J": 2000}
        ds = districts.evaluate(rec, self.nat, wet=False)
        self.assertEqual(ds[0]["id"], "campus")
        self.assertFalse(any(d["id"] == "harbor" for d in ds))

    def test_badges(self):
        rec = {"workers_total": 1000, **{f"workers_{s}": 50 for s in "ABCDEFGHIJKLMNOPQRS"}}
        ctx = {"ports": [], "mines": [], "military": [], "mil_kinds": set(), "students": {}}
        town = {"name": "Krynica-Zdrój", "gmina": "1210041", "capital": False, "lon": None}
        self.assertEqual(districts.badge_for(town, rec, self.nat, ctx)["label"], "Spa town")
        town = {"name": "Warszawa", "gmina": "1465011", "capital": True, "lon": None}
        self.assertEqual(districts.badge_for(town, rec, self.nat, ctx)["label"], "Capital city")
        self.assertIsNone(districts.badge_for({"name": "X", "gmina": "1", "lon": None}, rec, self.nat, ctx))
        self.assertTrue(all(rule for *_, rule in districts.BADGE_RULES))


if __name__ == "__main__":
    unittest.main()

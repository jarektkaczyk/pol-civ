import unittest

from pipeline.sources.pl_census_2021 import education_rows, parse_final_education_rows


class CensusEducationTest(unittest.TestCase):
    def test_shares_use_the_matching_census_population(self):
        rows = education_rows(
            {"0201", "0202", "0203", "0204"},
            {"0201": 3000, "0202": 500, "0204": 0},
            {"0201": 1000, "0202": 0, "0204": 100},
        )
        self.assertEqual(
            rows["0201"],
            {"population_13_plus": 3000, "higher": 1000, "higher_share": 33.3333},
        )
        self.assertEqual(rows["0202"]["higher_share"], 0)
        self.assertIsNone(rows["0203"]["higher_share"])
        self.assertIsNone(rows["0204"]["higher_share"])

    def test_matches_type_changes_and_keeps_new_gminas_null(self):
        rows = education_rows(
            {"0604123", "0604152"}, {"0604122": 200}, {"0604122": 75}, map_gminas=True,
        )
        self.assertEqual(rows["0604123"]["higher_share"], 37.5)
        self.assertIsNone(rows["0604152"]["higher_share"])

    def test_parses_final_name_rows_with_combined_categories(self):
        rows = [
            ["Powiaty", "Ogolem Total", "Wyzsze Higher", "Srednie i policealne"],
            ["Powiat bytowski", 100, 20, 30],
            ["Powiat m. Gdansk", 200, 80, 60],
        ]
        lookup = {("22", "bytowski"): "2201", ("22", "gdansk"): "2261"}
        parsed = parse_final_education_rows(rows, "22", lookup)
        self.assertEqual(parsed["2201"]["population_13_plus"], 100)
        self.assertEqual(parsed["2261"]["higher"], 80)

    def test_rejects_percentage_distribution_as_person_counts(self):
        rows = [
            ["Powiaty", "Ogolem Total", "Wyzsze Higher", "Srednie i policealne"],
            ["Powiat bytowski", 100, 14.2, 28.8],
            ["Powiat m. Gdansk", 100, 36.5, 31.1],
        ]
        lookup = {("22", "bytowski"): "2201", ("22", "gdansk"): "2261"}
        self.assertEqual(parse_final_education_rows(rows, "22", lookup), {})

    def test_stops_before_percentage_distribution_after_counts(self):
        rows = [
            ["Powiaty", "Rok", "Ogolem Total", "Wyzsze Higher"],
            ["Powiat bytowski", 2011, 90, 10],
            [None, 2021, 1000, 200],
            ["Powiat m. Gdansk", 2011, 180, 30],
            [None, 2021, 2000, 800],
            ["Powiat bytowski", 2011, 100, 11.1],
            [None, 2021, 100, 20.0],
        ]
        lookup = {("22", "bytowski"): "2201", ("22", "gdansk"): "2261"}
        parsed = parse_final_education_rows(rows, "22", lookup)
        self.assertEqual(parsed["2201"]["population_13_plus"], 1000)
        self.assertEqual(parsed["2261"]["higher"], 800)


if __name__ == "__main__":
    unittest.main()

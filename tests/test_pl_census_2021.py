import unittest

from pipeline.sources.pl_census_2021 import (
    _category_columns,
    parse_education_map,
    parse_education_rows,
    parse_final_education_rows,
)


class CensusWorkbookTest(unittest.TestCase):
    def test_maps_full_header(self):
        header = [
            "Wyszczegolnienie", "Ogolem", "Wyzsze doktor", "Wyzsze magister",
            "Dyplom ukonczenia kolegium", "Policealne", "Srednie ogolnoksztalcace",
            "Srednie zawodowe", "Zasadnicze zawodowe", "Gimnazjalne",
            "Podstawowe ukonczone", "Podstawowe nieukonczone", "Nieustalony",
        ]
        columns = _category_columns(header)
        self.assertEqual(columns["higher"], [2, 3, 4])
        self.assertTrue(all(columns.values()))

    def test_parses_land_and_city_powiat_rows_and_sums_higher(self):
        rows = [
            ["Tablica. Ludnosc w wieku 13 lat i wiecej wedlug poziomu wyksztalcenia i powiatow"],
            ["Wyszczegolnienie", "Ogolem", "Wyzsze doktor", "Wyzsze magister", "Dyplom ukonczenia kolegium", "Policealne", "Srednie ogolnoksztalcace", "Srednie zawodowe", "Zasadnicze zawodowe", "Gimnazjalne", "Podstawowe ukonczone", "Podstawowe nieukonczone", "Nieustalony"],
            ["Powiaty:"],
            ["bytowski", 100, 1, 10, 2, 3, 20, 21, 15, 4, 12, 5, 7],
            ["m. Gdansk", 200, 2, 20, 4, 6, 40, 42, 30, 8, 24, 10, 14],
            ["Mezczyzni"],
            ["bytowski", 50, 1, 5, 1, 2, 10, 10, 8, 2, 6, 2, 3],
        ]
        parsed = parse_education_rows(
            rows,
            "22",
            {("22", "bytowski"): "2201", ("22", "gdansk"): "2261"},
        )
        self.assertEqual(parsed["2201"]["higher"], 13)
        self.assertEqual(parsed["2201"]["population_13_plus"], 100)
        self.assertEqual(parsed["2261"]["higher"], 26)
        self.assertEqual(parsed["2261"]["population_13_plus"], 200)
        self.assertEqual(len(parsed), 2)

    def test_parses_preliminary_map_for_land_and_city_powiat(self):
        rows = [
            ["Share with higher education"],
            ["TERYT", "Powiat", "Udzial osob z wyksztalceniem wyzszym"],
            ["2201", "bytowski", 14.2],
            ["2261", "m. Gdansk", 36.5],
        ]
        lookup = {("22", "bytowski"): "2201", ("22", "gdansk"): "2261"}
        parsed = parse_education_map(rows, "22", lookup)
        self.assertEqual(parsed["2201"]["higher_share"], 14.2)
        self.assertEqual(parsed["2261"]["higher_share"], 36.5)

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

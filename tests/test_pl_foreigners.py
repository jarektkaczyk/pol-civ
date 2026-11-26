import unittest

from pipeline.sources.pl_foreigners import POWIAT_RELEASES, parse_powiat_rows, parse_voivodeship_rows


class ForeignersParsingTest(unittest.TestCase):
    def test_powiat_suppression_stays_null(self):
        rows = [["1261", "KRAKOW", "MALOPOLSKIE", 100, "<2", 101]]
        self.assertEqual(parse_powiat_rows(rows)["1261"], {
            "pesel_ukr": 101, "pesel_ukr_men": None, "pesel_ukr_women": 100,
        })

    def test_voivodeship_name_maps_to_teryt(self):
        rows = [["Ma\u0142opolskie", 12, 5, 7]]
        self.assertEqual(parse_voivodeship_rows(rows), {
            "12": {"pesel_ukr": 12, "pesel_ukr_men": 5, "pesel_ukr_women": 7}
        })

    def test_newest_powiat_release_is_first(self):
        self.assertEqual(POWIAT_RELEASES[0][0], "2026-11-11")
        self.assertTrue(POWIAT_RELEASES[0][1].startswith("https://api.dane.gov.pl/"))


if __name__ == "__main__":
    unittest.main()

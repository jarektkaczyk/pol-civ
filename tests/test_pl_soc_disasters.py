"""pl_soc_disasters: act text checks and resolution of the declared area."""

import unittest

from pipeline.sources import pl_soc_disasters as d

PKW = [
    {"teryt": "21501", "gmina": "m. Ola", "powiat": "olawski", "woj": "dolnoslaskie"},
    {"teryt": "21504", "gmina": "gm. Ola", "powiat": "olawski", "woj": "dolnoslaskie"},
    {"teryt": "160501", "gmina": "gm. Gogolin", "powiat": "krapkowicki", "woj": "opolskie"},
    {"teryt": "160503", "gmina": "gm. Strzeleczki", "powiat": "krapkowicki", "woj": "opolskie"},
    {"teryt": "81005", "gmina": "gm. Malomice", "powiat": "zaganski", "woj": "lubuskie"},
    {"teryt": "26501", "gmina": "Walbrzych", "powiat": "Walbrzych", "woj": "dolnoslaskie"},
]


class DisastersTest(unittest.TestCase):
    def test_act_text_and_phrase(self):
        t = d.act_text("<p>w wojew&oacute;dztwie opolskim - powiaty <b>nyski</b></p>")
        self.assertTrue(d.phrase_in("nyski", t))
        self.assertFalse(d.phrase_in("opolski", t))

    def test_resolve(self):
        areas = [
            {"voivodeship": "opolskie", "unit": "gmina", "pkw_powiat": "krapkowicki", "pkw_gmina": "gm. Strzeleczki",
             "date": "2024-09-16"},
            {"voivodeship": "opolskie", "unit": "powiat", "pkw_powiat": "krapkowicki", "date": "2024-09-17"},
            {"voivodeship": "dolnoslaskie", "unit": "gmina", "pkw_powiat": "olawski", "pkw_gmina": "m. Ola",
             "date": "2024-09-21"},
            {"voivodeship": "lubuskie", "unit": "gmina_part", "pkw_powiat": "zaganski", "pkw_gmina": "gm. Malomice",
             "date": "2024-09-21"},
            {"voivodeship": "dolnoslaskie", "unit": "powiat", "pkw_powiat": "Walbrzych", "date": "2024-09-16"},
        ]
        g, p, problems = d.resolve(areas, PKW)
        self.assertEqual(problems, [])
        self.assertEqual(g["160503"], ("2024-09-16", False))
        self.assertEqual(g["160501"], ("2024-09-17", False))
        self.assertEqual(g["021501"], ("2024-09-21", False))
        self.assertNotIn("021504", g)
        self.assertEqual(g["081005"], ("2024-09-21", True))
        self.assertEqual(p, {"1605": "2024-09-17", "0265": "2024-09-16"})
        _, _, problems = d.resolve([{"voivodeship": "opolskie", "unit": "powiat", "pkw_powiat": "nope",
                                     "date": "2024-09-16"}], PKW)
        self.assertEqual(len(problems), 1)


if __name__ == "__main__":
    unittest.main()

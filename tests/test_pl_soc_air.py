"""pl_soc_air: GIOS archive page parsing, row choice and station matching."""

import unittest

from pipeline.sources import pl_soc_air as a

HTML = """
<li> <a class="" href = "/pjp/archives/downloadFile/643">
  <div class="col-sm-10 col-xs-6"><p class = "archive_file_name">Metadane oraz kody stacji i stanowisk pomiarowych</p></div>
<li> <a class="" href = "/pjp/archives/downloadFile/642">
  <div class="col-sm-10 col-xs-6"><p class = "archive_file_name">Statystyki z lat 2000-2025</p></div>
<li> <a class="" href = "/pjp/archives/downloadFile/600">
  <div class="col-sm-10 col-xs-6"><p class = "archive_file_name">Statystyki z lat 2000-2024</p></div>
<li> <a class="" href = "/pjp/archives/downloadFile/223">
  <div class="col-sm-10 col-xs-6"><p class = "archive_file_name">2000</p></div>
"""


class AirTest(unittest.TestCase):
    def test_pick_stats(self):
        self.assertEqual(a.pick_stats(HTML), (2025, "642", "643"))

    def test_best_rows_prefers_completeness_then_24h(self):
        rows = [
            {"rok": "2025", "kod_stacji": "X", "srednia": "18.4", "kompletnosc": "99.8", "czas_usredniania": "1g"},
            {"rok": "2025", "kod_stacji": "X", "srednia": "17.0", "kompletnosc": "90", "czas_usredniania": "24g"},
            {"rok": "2025", "kod_stacji": "Y", "srednia": "10", "kompletnosc": "100", "czas_usredniania": "1g"},
            {"rok": "2025", "kod_stacji": "Y", "srednia": "11", "kompletnosc": "100", "czas_usredniania": "24g"},
            {"rok": "2024", "kod_stacji": "Z", "srednia": "9", "kompletnosc": "100", "czas_usredniania": "24g"},
        ]
        best = a.best_rows(rows, 2025)
        self.assertEqual(best["X"]["srednia"], "18.4")
        self.assertEqual(best["Y"]["srednia"], "11")
        self.assertNotIn("Z", best)

    def test_find_station(self):
        st = {"OpBrzegPoprz": {"kod_stacji": "OpBrzegPoprz"},
              "SlGoczaUzdroMOB": {"kod_stacji": "SlGoczaUzdroMOB"},
              "MpNew": {"kod_stacji": "MpNew", a.OLD_CODE: "MpOld"}}
        self.assertEqual(a.find_station("OpBrzegPoprzMOB", st)["kod_stacji"], "OpBrzegPoprz")
        self.assertEqual(a.find_station("SlGoczaUzdro", st)["kod_stacji"], "SlGoczaUzdroMOB")
        self.assertEqual(a.find_station("MpOld", st)["kod_stacji"], "MpNew")
        self.assertIsNone(a.find_station("Nope", st))


if __name__ == "__main__":
    unittest.main()

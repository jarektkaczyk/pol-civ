import unittest

from pipeline.sources.pl_more_exams import parse_e8, parse_matura


class ExamWorkbookTest(unittest.TestCase):
    def test_e8_combines_parts_and_uses_whole_row_when_present(self):
        rows = [
            [None, "j\u0119zyk polski", None, "matematyka", None, "j\u0119zyk angielski", None],
            ["Kod teryt gminy", *(["liczba zdaj\u0105cych", "wynik \u015bredni (%)"] * 3)],
            ["0201034", 10, 70, 10, 50, 4, ""],
            ["0201035", 30, 50, 30, 60, 30, 60],
            ["0201042", 10, 53.13, 10, 0, 10, 65],
            ["0201053", 20, 75, 20, 50, 20, 82],
            ["0201054", 10, 65, 10, 50, 10, 89],
            ["9999991", 10, 80, 10, 65, 10, 43],
        ]
        result, unmatched, recoded = parse_e8(rows, {"0201033", "0201043", "0201053", "0201061"})
        self.assertEqual(
            result["0201033"],
            {"e8_polish_mean_pct": 55.0, "e8_math_mean_pct": 57.5, "e8_english_mean_pct": None},
        )
        self.assertEqual(result["0201043"]["e8_math_mean_pct"], 0.0)
        self.assertEqual(result["0201053"]["e8_polish_mean_pct"], 75.0)
        self.assertEqual(result["0201061"]["e8_math_mean_pct"], None)
        self.assertEqual(unmatched, {"9999991"})
        self.assertEqual(recoded, {("0201042", "0201043")})

    def test_matura_uses_whole_exam_and_ignores_commission_rows(self):
        rows = [
            [],
            [None, None, "dla ca\u0142ego egzaminu dojrza\u0142o\u015bci", None, "matematyka"],
            ["powiat - nazwa", "Kod teryt powiatu", "Liczba zdaj\u0105cych", "* zdawalno\u015b\u0107 (%)",
             "* zdawalno\u015b\u0107 (%)"],
            ["Krakow", "1261", 100, 89.789, 98],
            ["OKR\u0118GOWA KOMISJA EGZAMINACYJNA W KRAKOWIE", "1261", 10, 30, 90],
            ["Boleslawiecki", 201, 4, "", 80],
            ["Old county", "9999", 100, 80, 80],
        ]
        result, unmatched, missing = parse_matura(rows, {"0201", "1261", "1426"})
        self.assertEqual(result, {
            "0201": {"matura_pass_pct": None},
            "1261": {"matura_pass_pct": 89.79},
            "1426": {"matura_pass_pct": None},
        })
        self.assertEqual(unmatched, {"9999"})
        self.assertEqual(missing, {"1426"})


if __name__ == "__main__":
    unittest.main()

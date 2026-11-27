"""The motion layers' data: permits month by month (permits_monthly.py and the pl_econ_permits helpers)."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.build import permits_monthly as pm
from pipeline.core.geo import MapProjection
from pipeline.sources import pl_econ_permits as permits

HEADER = ("\ufeffnumer_urzad;nazwa_organu;numer_decyzji_urzedu;data_wydania_decyzji;nazwa_inwestor;terc;"
          "kategoria;nazwa_zamierzenia_bud;projektant_nazwisko;projektant_imie")
NEW = "budowa nowego/nowych obiektow budowlanych"


def lines(*rows):
    return [HEADER + "\n"] + [r + "\n" for r in rows]


class MonthlyPermitsTest(unittest.TestCase):
    def first(self):
        rows = permits.iter_rows(lines(
            f"1;Starosta A;5/2018;2018-06-12 00:00:00;Jan Kowalski;1607054;XVIII;{NEW};Nowak;Anna",  # town part
            f"2;Starosta A;5/2018;2018-06-12 00:00:00;x;1607055;XVIII;{NEW};x;x",  # same decision, rural part
            f"3;Starosta A;5/2018;2018-07-02 00:00:00;x;1607053;XVIII;{NEW};x;x",  # amendment row, later date
            f"4;Starosta A;6/2018;2018-06-30 00:00:00;x;1607053;XVIII;{NEW};x;x",
            f"5;Starosta A;7/2018;2018-06-30 00:00:00;x;1607053;XVII;{NEW};x;x",  # other category
            f"6;Prezydent B;9/2026;2026-10-01 00:00:00;x;1465048;XVIII;{NEW};x;x",  # Warsaw district
            f"7;Prezydent B;9/2026;2026-10-01 00:00:00;x;1418043;XVIII;{NEW};x;x",  # same number, other gmina
            f"8;Prezydent B;10/2026;2026-07-01 00:00:00;x;;XVIII;{NEW};x;x",  # no TERC
            f"9;Prezydent B;11/2026;bad;x;1465011;XVIII;{NEW};x;x",  # no date
            f"10;Prezydent B;12/2026;2026-11-20 00:00:00;x;1465011;XVIII;{NEW};x;x",  # after the last full month
        ))
        first, stats = {}, {}
        by6 = {"160705": "1607053", "146501": "1465011", "141804": "1418043"}
        permits.first_decisions(rows, by6, first, stats)
        return first, stats

    def test_a_decision_counts_once_per_gmina_in_its_first_month(self):
        first, stats = self.first()
        counts = permits.monthly_counts(first, "2016-01", "2026-10")
        self.assertEqual({("1607053", "2018-06"): 2, ("1465011", "2026-10"): 1, ("1418043", "2026-10"): 1}, counts)
        self.assertEqual(1, len(stats["unmapped"]))
        self.assertEqual(1, stats["undated"])

    def test_names_never_reach_the_rows(self):
        first, _ = self.first()
        flat = json.dumps([list(k) for k in first])
        self.assertNotIn("Kowalski", flat)
        self.assertNotIn("Nowak", flat)

    def test_last_full_month(self):
        self.assertEqual("2026-10", permits.last_full_month(dt.date(2026, 11, 25)))
        self.assertEqual("2026-11", permits.last_full_month(dt.date(2026, 11, 30)))
        self.assertEqual("2025-12", permits.last_full_month(dt.date(2026, 1, 3)))

    def test_month_list_and_pack(self):
        months = pm.month_list("2025-11", "2026-02")
        self.assertEqual(["2025-11", "2025-12", "2026-01", "2026-02"], months)
        gminas = [{"code": "1465011"}, {"code": "1607053"}]
        counts = {("1607053", "2026-01"): 2, ("1465011", "2026-01"): 1, ("1465011", "2025-11"): 3, ("9999999", "2026-01"): 5}
        flat, national = pm.pack(counts, months, gminas)
        self.assertEqual([0, 0, 3, 2, 0, 1, 2, 1, 2], flat)
        self.assertEqual([3, 0, 3, 0], national)

    def test_centroid_of_a_square_with_a_hole(self):
        proj = MapProjection(min_x=0.0, max_y=0.0, margin=0.0)
        # A square ring around (19.3, 52.0) and a smaller hole wound the other way: the centroid stays at the centre.
        outer = [(19.0, 51.8), (19.6, 51.8), (19.6, 52.2), (19.0, 52.2)]
        hole = [(19.2, 51.9), (19.2, 52.1), (19.4, 52.1), (19.4, 51.9)]
        cx, cy = pm.ring_centroid([outer, hole], proj)
        x0, y0 = proj(19.3, 52.0)
        self.assertAlmostEqual(x0, cx, delta=0.5)
        self.assertAlmostEqual(y0, cy, delta=0.5)

    def test_check(self):
        doc = {"version": 1, "vintage": "v", "sources": ["pl_econ_permits"], "rules": ["r"], "unit": "decisions",
               "months": ["2016-01", "2016-02"], "gminas": [{"code": "1465011", "name": "Warszawa", "x": 1.0, "y": 2.0}],
               "counts": [0, 0, 2, 1, 0, 1], "national": [2, 1], "total": 3}
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual("NOTE", pm.check(tmp)[0][0])
            (Path(tmp) / "permits_monthly.json").write_text(json.dumps(doc))
            self.assertEqual(["PASS"], [lv for lv, _ in pm.check(tmp)])
            doc["counts"] = [1, 0, 2, 0, 0, 1]
            doc["national"] = [1, 1]
            (Path(tmp) / "permits_monthly.json").write_text(json.dumps(doc))
            levels = [lv for lv, _ in pm.check(tmp)]
            self.assertIn("FAIL", levels)


if __name__ == "__main__":
    unittest.main()

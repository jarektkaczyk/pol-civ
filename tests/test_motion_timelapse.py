"""Time-lapse data: monthly tourism (BDL P2882), the GIOS smog week, the smog hex interpolation and timelapse.json."""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from pipeline.build import smog, timelapse
from pipeline.sources import pl_air_hourly as air
from pipeline.sources import pl_tourism_monthly as tour


def bdl_record(code2: str, values: dict) -> dict:
    return {"id": f"01{code2}00000000", "name": code2,
            "values": [{"year": str(y), "val": v, "attrId": a} for y, (v, a) in values.items()]}


class TourismSourceTest(unittest.TestCase):
    def test_years_needed_covers_the_window_and_the_publication_lag(self):
        self.assertEqual(tour.years_needed(date(2026, 11, 27)), [2023, 2024, 2025, 2026])
        self.assertEqual(tour.years_needed(date(2027, 1, 15)), [2023, 2024, 2025, 2026, 2027])

    def test_month_variables_picks_all_nights_in_all_establishments(self):
        rows = []
        for i, m in enumerate(tour.MONTHS_PL):
            rows.append({"id": 1000 + i, "n1": m, "n2": tour.ESTABLISHMENTS, "n3": tour.MEASURE})
            rows.append({"id": 2000 + i, "n1": m, "n2": "obiekty hotelowe ogółem", "n3": tour.MEASURE})
            rows.append({"id": 3000 + i, "n1": m, "n2": tour.ESTABLISHMENTS, "n3": "turyści (korzystający) ogółem"})
        got = tour.month_variables(rows)
        self.assertEqual(got[1], 1000)
        self.assertEqual(got[12], 1011)
        with self.assertRaises(RuntimeError):
            tour.month_variables(rows[3:])

    def test_monthly_rows_keeps_flags_null(self):
        rows = tour.monthly_rows({7: [bdl_record("32", {2025: (3000, 1), 2026: (3100, 2)})]})
        self.assertEqual(rows["2025-07"]["32"], 3000)
        self.assertIsNone(rows["2026-07"]["32"])

    def test_newest_months_ends_at_the_last_complete_month(self):
        rows = {f"{y}-{m:02d}": {"02": 1, "04": 2} for y in (2025, 2026) for m in range(1, 13)}
        for m in (10, 11, 12):
            rows[f"2026-{m:02d}"] = {"02": None, "04": None}
        got = tour.newest_months(rows, n=12, units=2)
        self.assertEqual((got[0], got[-1], len(got)), ("2025-10", "2026-09", 12))
        with self.assertRaises(RuntimeError):
            tour.newest_months(rows, n=24, units=2)  # 2024 is not in the download


class AirSourceTest(unittest.TestCase):
    def test_excel_hour(self):
        self.assertEqual(air.excel_hour(45658.041666666664), datetime(2025, 1, 1, 1))
        self.assertEqual(air.excel_hour(46023.00050682871), datetime(2026, 1, 1, 0))

    def test_archive_series_keeps_1h_pm25_columns_in_range(self):
        rows = [
            ["Nr", 1, 2, 3],
            ["Kod stacji", "A", "B", "C"],
            ["Wskaźnik", "PM2.5", "PM2.5", "PM10"],
            ["Czas uśredniania", "1g", "24g", "1g"],
            ["Jednostka", "ug/m3", "ug/m3", "ug/m3"],
            ["Kod stanowiska", "A-PM2.5-1g", "B-PM2.5-24g", "C-PM10-1g"],
            [45992.041666666664, 50.5, 9, 70],  # 2025-12-01 01:00
            [45992.083333333336, None, 9, 70],
            [45900.5, 3.0, 9, 70],  # August: out of range
        ]
        got = air.archive_series(rows, datetime(2025, 12, 1, 1), datetime(2026, 1, 1, 0))
        self.assertEqual(list(got), ["A"])
        self.assertEqual(got["A"], {datetime(2025, 12, 1, 1): 50.5})

    def test_api_rows(self):
        pages = [{"Lista archiwalnych wyników pomiarów": [
            {"Kod stanowiska": "MpKrakAlKras-PM2.5-1g", "Data": "2026-01-02 05:00:00", "Wartość": 88.1},
            {"Kod stanowiska": "MpKrakAlKras-PM2.5-1g", "Data": "2026-01-02 04:00:00", "Wartość": None},
        ]}]
        code, rows = air.api_rows(pages)
        self.assertEqual(code, "MpKrakAlKras-PM2.5-1g")
        self.assertEqual(rows, {datetime(2026, 1, 2, 5): 88.1})
        self.assertEqual(air.station_code(code), "MpKrakAlKras")

    def test_rank_weeks_uses_hourly_national_means(self):
        hours = [datetime(2025, 12, 1, 1) + timedelta(hours=i) for i in range(10 * 24)]
        low = {h: 10.0 for h in hours}
        high = {h: (90.0 if h >= datetime(2025, 12, 4, 1) else 30.0) for h in hours}
        means = air.national_means({"A": low, "B": high}, hours)
        self.assertEqual(means[0], 20.0)
        ranked = air.rank_weeks(hours, means)
        self.assertEqual(len(ranked), 4)  # windows starting 1, 2, 3 and 4 December
        self.assertEqual(ranked[0][1], datetime(2025, 12, 4, 1))
        self.assertAlmostEqual(ranked[0][0], 50.0)

    def test_national_means_skip_hours_with_too_few_stations(self):
        hours = [datetime(2025, 12, 1, 1) + timedelta(hours=i) for i in range(4)]
        full = {h: 10.0 for h in hours}
        series = {"A": full, "B": dict(full), "C": {h: 40.0 for h in hours[:3]}, "D": {h: 20.0 for h in hours[:3]}}
        series["B"].pop(hours[3])
        means = air.national_means(series, hours)
        self.assertEqual(means[0], 20.0)
        self.assertIsNone(means[3])  # 1 station of a median 4

    def test_rank_weeks_skips_windows_with_gaps(self):
        hours = [datetime(2025, 12, 1, 1) + timedelta(hours=i) for i in range(7 * 24)]
        means = [None if i < 20 else 5.0 for i in range(len(hours))]
        self.assertEqual(air.rank_weeks(hours, means), [])


class SmogBuilderTest(unittest.TestCase):
    def test_neighbours_and_idw(self):
        near = smog.neighbours({0: (0.0, 0.0), 1: (100.0, 0.0)}, [(0.0, 0.0), (20.0, 0.0)])
        self.assertNotIn(1, near)  # 80 km from the nearest station
        self.assertEqual([j for j, _ in near[0]], [0, 1])
        # station 0 sits in the hex (counted at 1 km), station 1 at 20 km: weights 1 and 1/400
        self.assertAlmostEqual(smog.idw(near[0], [100.0, 500.0]), (100 + 500 / 400) / (1 + 1 / 400))
        self.assertEqual(smog.idw(near[0], [None, 40.0]), 40.0)
        self.assertIsNone(smog.idw(near[0], [None, None]))

    def test_check_flags_shape_errors(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "smog.json").write_text(json.dumps({"hours": 2, "cells": [5], "values": [[1]],
                                                        "stations": []}))
            levels = [lvl for lvl, _ in smog.check(d)]
            self.assertIn("FAIL", levels)
            self.assertEqual(smog.check(tempfile.gettempdir() + "/nope")[0][0], "NOTE")


class TimelapseBuilderTest(unittest.TestCase):
    def test_tourism_block_orders_by_states_and_divides_by_population(self):
        interim = {"months": ["2026-01", "2026-07"], "tables": {"nights_monthly": {"rows": {
            "32": {"nights_2026_01": 700, "nights_2026_07": 3000},
            "02": {"nights_2026_01": 500, "nights_2026_07": None},
        }}}}
        got = timelapse.tourism_block(interim, ["02", "32"], {"02": 1000, "32": 1500})
        self.assertEqual(got["nights"], [[500, 700], [None, 3000]])
        self.assertEqual(got["per_resident"], [[0.5, 0.467], [None, 2.0]])
        self.assertEqual(got["national"], [1200, None])

    def test_elections_block_reads_national_shares(self):
        lenses = {"lenses": [{"id": "vote_2015"}, {"id": "vote_2020"}, {"id": "vote"}]}
        tables = {t: {"rows": {"PL": {f"{w}_share": 51.55, "turnout": 55.34}}}
                  for _, _, _, t, w, _ in timelapse.RUNOFFS}
        got = timelapse.elections_block(lenses, {"tables": tables})
        self.assertEqual([f["year"] for f in got["frames"]], [2015, 2020, 2025])
        self.assertEqual(got["frames"][2]["candidate"], "Karol Nawrocki")
        self.assertEqual(got["frames"][0]["share"], 0.5155)

    def test_check_requires_one_scale_for_the_runoffs(self):
        with tempfile.TemporaryDirectory() as d:
            frames = [{"year": 2015, "lens": "a"}, {"year": 2020, "lens": "b"}]
            Path(d, "timelapse.json").write_text(json.dumps({"states": [], "tourism": {}, "elections": {"frames": frames}}))
            Path(d, "lenses.json").write_text(json.dumps({"lenses": [
                {"id": "a", "ramp": ["#000"], "domain": [0.2, 0.8], "scale": "linear"},
                {"id": "b", "ramp": ["#000"], "domain": [0.1, 0.9], "scale": "linear"}]}))
            self.assertIn("FAIL", [lvl for lvl, _ in timelapse.check(d)])


if __name__ == "__main__":
    unittest.main()

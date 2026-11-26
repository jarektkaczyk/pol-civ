import ssl
import tempfile
import unittest
from pathlib import Path

from pipeline.sources.pl_stats_labour import (
    PKD_SECTIONS,
    _gus_trust_chain,
    parse_median_wages,
    parse_pkd_powiat,
    parse_sectors_gmina,
    parse_unemployment,
    parse_wages,
)


class PlStatsLabourTest(unittest.TestCase):
    def test_parses_powiat_unemployment_and_country(self):
        rows = [
            [0, 0, "POLSKA", 907.0, 5.8],
            ["12", "61", "Krakow", 14.6, 2.8],
            ["12", "00", "Malopolskie", 73.4, 5.0],
        ]
        powiats, country = parse_unemployment(rows)
        self.assertEqual(
            {"registered_unemployed": 14600, "registered_unemployment_rate": 2.8},
            powiats["1261"],
        )
        self.assertEqual(907000, country["registered_unemployed"])

    def test_parses_powiat_wages_and_suppressed_sections(self):
        wage_rows = [
            [None, None, None, None, None, None, "TOTAL", 9178.16],
            [None, None, "12", None, None, 61, "Krakow", 11296.94],
        ]
        median_rows = [
            [None, None, None, None, None, None, "TOTAL", 7550.32],
            [None, None, "12", None, None, 61, "Krakow", 8974.34],
        ]
        powiats, country = parse_wages(wage_rows)
        parse_median_wages(median_rows, powiats, country)
        self.assertEqual(11296.94, powiats["1261"]["average_gross_monthly_wage"])
        self.assertEqual(8974.34, powiats["1261"]["median_gross_monthly_wage"])
        self.assertEqual(9178.16, country["average_gross_monthly_wage"])

        row = [None] * 47
        row[2], row[5], row[7] = "12", "61", 535510
        for index in range(len(PKD_SECTIONS)):
            row[9 + index * 2] = index + 1
        row[11] = "."
        parsed = parse_pkd_powiat([row])["1261"]
        self.assertEqual(535510, parsed["workers_total"])
        self.assertEqual(1, parsed["workers_A"])
        self.assertIsNone(parsed["workers_B"])
        self.assertEqual(19, parsed["workers_S"])

    def test_parses_only_whole_gminas(self):
        whole = [None, None, "12", None, None, "61", "01", 1, "Krakow", 10, 1, 2, 7]
        part = [None, None, "12", None, None, "05", "06", 4, "Town", 10, 1, 2, 7]
        rows = parse_sectors_gmina([whole, part])
        self.assertEqual({"1261011"}, set(rows))
        self.assertEqual(7, rows["1261011"]["workers_services"])

    def test_trust_chain_rejects_invalid_intermediate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.cer"
            path.write_bytes(b"not a certificate")
            with self.assertRaises(ssl.SSLError):
                with _gus_trust_chain(path):
                    pass


if __name__ == "__main__":
    unittest.main()

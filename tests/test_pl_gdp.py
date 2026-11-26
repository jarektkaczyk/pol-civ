import gzip
import tempfile
import unittest
from pathlib import Path

from pipeline.sources.pl_gdp import _number, jsonstat_rows, read_eurostat_tsv


class EurostatParsingTest(unittest.TestCase):
    def test_number_strips_flags_and_missing_values(self):
        self.assertEqual(_number(" 123.4 p "), 123.4)
        self.assertIsNone(_number(": "))

    def test_tsv_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.tsv.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                f.write("freq,unit,geo\\TIME_PERIOD\t2023 \t2024\n")
                f.write("A,MIO_EUR,PL213\t10.5 p\t: \n")
            self.assertEqual(
                list(read_eurostat_tsv(path)),
                [({"freq": "A", "unit": "MIO_EUR", "geo": "PL213"}, 2023, 10.5)],
            )

    def test_jsonstat_sparse_values(self):
        payload = {
            "id": ["unit", "time"], "size": [2, 2],
            "dimension": {
                "unit": {"category": {"index": {"EUR": 0, "PLN": 1}}},
                "time": {"category": {"index": ["2024", "2025"]}},
            },
            "value": {"1": 20, "3": 40},
        }
        self.assertEqual(list(jsonstat_rows(payload)), [
            ({"unit": "EUR", "time": "2025"}, 20.0),
            ({"unit": "PLN", "time": "2025"}, 40.0),
        ])


if __name__ == "__main__":
    unittest.main()

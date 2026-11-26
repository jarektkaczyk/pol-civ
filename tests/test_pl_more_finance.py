import io
import struct
import unittest
from decimal import Decimal

from pipeline.sources.pl_more_finance import aggregate_report, calculate_rates, dbf_rows


def row(**overrides):
    return {
        "WK": "12", "PK": "01", "GK": "01", "GT": "2", "PT": "0",
        "KODMSWIA": "", "ROK": "25", "KWARTAL": "4", "WERSJA": "0",
        "PAR": "001", "GRUPA": "1600", "R4": "100.00", "E": "432.10",
        **overrides,
    }


class FinanceReportTest(unittest.TestCase):
    def test_dbf_selects_columns_and_ignores_deleted_record(self):
        header = struct.pack("<BBBBIHH20x", 3, 26, 3, 18, 2, 97, 8)
        fields = (
            struct.pack("<11sc4xBB14x", b"WK", b"C", 2, 0)
            + struct.pack("<11sc4xBB14x", b"R4", b"N", 5, 2)
        )
        dbf = io.BytesIO(header + fields + b"\r 02 1.23*04 7.89\x1a")
        self.assertEqual(list(dbf_rows(dbf, ("R4", "WK"))), [{"R4": "1.23", "WK": "02"}])

    def test_income_excludes_transfers_and_uses_latest_filing(self):
        rows = [
            row(),
            row(WERSJA="1", R4="271.66"),
            row(WERSJA="0", R4="900.00"),
            row(WERSJA="1", PAR="292", R4="800.00"),
            row(WERSJA="1", PAR="031", R4="100.12"),
            row(PT="1", GK="00", GT="0"),
            row(PT="2", PK="61", GK="00", GT="0"),
            row(KODMSWIA="1234"),
            row(KWARTAL="3"),
        ]
        self.assertEqual(
            aggregate_report(rows, "rb27s.zip"),
            {"1201012": Decimal("371.78"), "1261011": Decimal("100.00")},
        )

    def test_investment_spending_keeps_only_capital_investment(self):
        rows = [
            row(PAR="605", R4="150.00"),
            row(PAR="630", GRUPA="1610", R4="50.00"),
            row(PAR="601", GRUPA="1620", R4="750.00"),
            row(PAR="668", GRUPA="1100", R4="12.00"),
            row(PAR="401", GRUPA="1400", R4="900.00"),
        ]
        self.assertEqual(aggregate_report(rows, "rb28s.zip"), {"1201012": Decimal("200.00")})

    def test_rates_preserve_missing_and_zero_debt_and_recodes_type(self):
        report = aggregate_report(
            [row(E="0.00"), row(GK="02", E=""), row(GK="03"), row(GK="04", E="100")], "rbz.zip"
        )
        result, unmatched, recoded = calculate_rates(
            {"debt_per_resident": report}, {"1201012": 123, "1201022": 100, "1201042": 8},
            {"1201013", "1201022", "1201032"},
        )
        self.assertEqual(
            result, {
                "1201013": {"debt_per_resident": 0.0},
                "1201022": {"debt_per_resident": None},
                "1201032": {"debt_per_resident": None},
            },
        )
        self.assertEqual(unmatched, {"1201042"})
        self.assertEqual(recoded, {("1201012", "1201013")})


if __name__ == "__main__":
    unittest.main()

import struct
import unittest

from pipeline.sources.pl_stats_population import (
    _age_key,
    _ascii_name,
    _decode_rk,
    _on_current_code,
    _territorial_code,
    _teryt,
)


class PopulationParsingTests(unittest.TestCase):
    def test_teryt_from_biff_number(self):
        self.assertEqual(_teryt(1261011.0), "1261011")
        self.assertEqual(_teryt(1465011), "1465011")

    def test_teryt_from_area_workbook_text(self):
        self.assertEqual(_teryt("020101 1"), "0201011")
        self.assertIsNone(_teryt("020104 4"))
        self.assertIsNone(_teryt("020104 5"))
        self.assertEqual(_territorial_code("020104 4"), "0201044")

    def test_five_year_age_labels(self):
        self.assertEqual(_age_key("    0    -    4"), (0, 4))
        self.assertEqual(_age_key("80-84"), (80, 84))
        self.assertEqual(_age_key("85 lat i wiecej"), (85, None))
        self.assertIsNone(_age_key("65 lat i wiecej"))
        self.assertIsNone(_age_key("14"))

    def test_rk_integer(self):
        self.assertEqual(_decode_rk((123 << 2) | 0x02), 123)

    def test_rk_divided_by_100(self):
        self.assertEqual(_decode_rk((1234 << 2) | 0x03), 12.34)

    def test_rk_float(self):
        raw_high = struct.unpack("<I", struct.pack("<d", 41.5)[4:])[0]
        self.assertEqual(_decode_rk(raw_high), 41.5)

    def test_type_only_teryt_change(self):
        self.assertEqual(_on_current_code({"0601052": 123}, "0601053"), 123)

    def test_voivodeship_name_normalizes_hyphen_spacing(self):
        self.assertEqual(_ascii_name("Warmi\u0144sko - Mazurskie"), "warminsko-mazurskie")


if __name__ == "__main__":
    unittest.main()

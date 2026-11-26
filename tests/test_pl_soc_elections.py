"""pl_soc_common TERYT helpers and pl_soc_elections parsing."""

import unittest

from pipeline.sources import pl_soc_common as c
from pipeline.sources import pl_soc_elections as e


class TerytTest(unittest.TestCase):
    def test_bdl_id_to_teryt7(self):
        self.assertEqual(c.bdl_id_to_teryt7("011212001011"), "1201011")
        self.assertEqual(c.bdl_id_to_teryt7("011213061011"), "1261011")  # Krakow
        with self.assertRaises(ValueError):
            c.bdl_id_to_teryt7("1261011")

    def test_index_prefers_urban_rural_and_maps_warsaw(self):
        units = {
            "1206142": {"name": "Swiatniki Gorne", "kind": "2"},  # before 1997
            "1206143": {"name": "Swiatniki Gorne", "kind": "3"},
            "1206144": {"name": "Swiatniki Gorne - miasto", "kind": "4"},
            "2211021": {"name": "Jastarnia", "kind": "1"},
            "2211023": {"name": "Jastarnia", "kind": "3"},
            "1465011": {"name": "Warszawa", "kind": "1"},
            "1465028": {"name": "Bemowo", "kind": "8"},
            "1261049": {"name": "Krakow-Nowa Huta", "kind": "9"},
            "0201011": {"name": "Boleslawiec", "kind": "1"},
        }
        idx = c.teryt6_index(units)
        self.assertEqual(idx["120614"], "1206143")
        self.assertEqual(idx["221102"], "2211023")
        self.assertEqual(idx["146502"], "1465011")
        self.assertNotIn("126104", idx)
        self.assertEqual(c.teryt7_from6("20101", idx), "0201011")  # PKW drops the leading zero
        self.assertIsNone(c.teryt7_from6("", idx))

    def test_num_and_slug(self):
        self.assertEqual(c.num("1 234,5"), 1234.5)
        self.assertIsNone(c.num("-"))
        self.assertIsNone(c.num(""))
        self.assertEqual(c.slug("Prawo i Sprawiedliwość"), "prawo_i_sprawiedliwosc")
        self.assertEqual(c.slug("Łódź"), "lodz")
        self.assertEqual(c.pct(1, 4), 25.0)
        self.assertIsNone(c.pct(1, 0))


class ElectionsTest(unittest.TestCase):
    def test_blob_timestamp(self):
        blob = b"\x0a\x2awyniki_gl_na_kandydatow_po_gminach_csv.zip\x10\xc5\xbf\xcb\xc6\x06\x0a"
        self.assertEqual(e.blob_timestamp(blob, "wyniki_gl_na_kandydatow_po_gminach_csv.zip"), 1758650309)
        self.assertIsNone(e.blob_timestamp(blob, "other.zip"))

    def test_aggregate_sums_warsaw_and_splits_outside(self):
        text = (
            '\ufeff"TERYT Gminy";"Gmina";"Powiat";"A";"B"\n'
            '146502;"Bemowo";"Warszawa";10;\n'
            '146503;"Białołęka";"Warszawa";5;2\n'
            '20101;"m. Bolesławiec";"bolesławiecki";7;\n'
            ';"Albania";"zagranica";3;1\n'
            ';"statki";"statki";1;0\n'
            '999999;"x";"y";1;1\n'
        )
        rows = c.read_semicolon_csv(text)
        idx = {"146502": "1465011", "146503": "1465011", "020101": "0201011"}
        gm, out, bad = e.aggregate(rows, idx, ["A", "B"])
        self.assertEqual(gm["1465011"], {"A": 15, "B": 2})
        self.assertEqual(gm["0201011"], {"A": 7, "B": None})  # blank = not on the ballot -> None
        self.assertEqual(out["abroad"], {"A": 3, "B": 1})
        self.assertEqual(out["ships"], {"A": 1, "B": 0})
        self.assertEqual(bad, ["999999"])

    def test_find_col(self):
        h = ["Liczba kart ważnych", "X"]
        self.assertEqual(e.find_col(h, e.S_VALID_CARDS), h[0])


if __name__ == "__main__":
    unittest.main()

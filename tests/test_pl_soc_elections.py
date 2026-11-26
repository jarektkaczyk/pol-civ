"""pl_soc_common TERYT helpers and pl_soc_elections parsing."""

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(bad, {"999999": {"A": 1, "B": 1}})

    def test_find_col(self):
        h = ["Liczba kart ważnych", "X"]
        self.assertEqual(e.find_col(h, e.S_VALID_CARDS), h[0])

    def test_2015_xls_maps_current_codes_and_keeps_unmatched_votes(self):
        header = [
            "TERYT", "Gmina", "Powiat", "Typ", e.S_ELIGIBLE, e.S_ISSUED_HISTORICAL,
            e.S_VALID_CARDS, "Liczba glosow waznych", "Duda Andrzej Sebastian", "Komorowski Bronislaw Maria",
        ]
        sheet = [
            header,
            ["061108", "Stoczek Lukowski", "lukowski", "2", 100, 51, 50, 49, 25, 24],
            ["021803", "Miekinia", "sredzki", "2", 30, None, 19, 18, 9, 9],
            ["320304", "Ostrowice", "drawski", "2", 25, 10, 10, 10, 3, 7],
            ["149901", "Zagranica", "Zagranica", "Z", 11, 10, 10, 9, 5, 4],
            ["229901", "Statki", "statki", "S", 5, 5, 5, 4, 1, 3],
        ]
        with tempfile.TemporaryDirectory() as directory, patch.object(e, "read_xls", return_value=[sheet]):
            path = Path(directory) / "round2.xls"
            path.write_bytes(b"fixture")
            rows = e.read_historical_runoff(path, 2015)
        idx = e.current_gmina_index({"061108": "0611083", "021803": "0218033", "320304": "3203042"})
        table, totals, bad = e.PlSocElections._build(
            rows, idx, e.S_VALID_PRES, 2015, "2015 runoff", with_votes=True, historical=True,
        )
        self.assertEqual(bad, ["320304"])
        self.assertEqual(set(table["rows"]), {"0611082", "0218033"})
        self.assertEqual(table["rows"]["0611082"]["turnout"], 50.0)
        self.assertEqual(table["rows"]["0611082"]["komorowski_votes"], 24)
        self.assertEqual(table["rows"]["0218033"]["duda_share"], 50.0)
        self.assertIsNone(table["rows"]["0218033"]["ballots_issued"])
        self.assertEqual(totals["rows"]["PL"]["valid_votes"], 90)
        self.assertEqual(totals["rows"]["PL_domestic"]["valid_votes"], 77)
        self.assertEqual(totals["rows"]["abroad"]["duda_votes"], 5)
        self.assertEqual(totals["rows"]["ships"]["komorowski_votes"], 3)

    def test_2020_csv_keeps_votes_and_ignores_precinct_count(self):
        csv = (
            f"Kod TERYT;Rodzaj jednostki;Gmina;Powiat;{e.S_ELIGIBLE};{e.S_ISSUED_HISTORICAL};"
            f"{e.S_VALID_CARDS};{e.S_VALID_PRES};Andrzej Sebastian DUDA;Rafal Kazimierz TRZASKOWSKI;Liczba obwodow\n"
            "020101;gmina miejska;m. Boleslawiec;boleslawiecki;100;50;80;75;30;45;3\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "round2.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("gminy.csv", csv.encode("utf-8-sig"))
            rows = e.read_historical_runoff(path, 2020)
        table, _, bad = e.PlSocElections._build(
            rows, {"020101": "0201011"}, e.S_VALID_PRES, 2020, "2020 runoff", with_votes=True, historical=True,
        )
        self.assertEqual(bad, [])
        row = table["rows"]["0201011"]
        self.assertEqual(set(row), {
            "eligible", "ballots_issued", "valid_ballots", "valid_votes", "turnout",
            "duda_votes", "duda_share", "trzaskowski_votes", "trzaskowski_share",
        })
        self.assertEqual(row["duda_votes"], 30)
        self.assertEqual(row["duda_share"], 40.0)
        self.assertEqual(row["trzaskowski_votes"], 45)
        self.assertEqual(row["trzaskowski_share"], 60.0)


if __name__ == "__main__":
    unittest.main()

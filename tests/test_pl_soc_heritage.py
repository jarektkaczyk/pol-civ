"""pl_soc_heritage: UNESCO component handling and the NID CSV grouping."""

import json
import unittest

from pipeline.sources import pl_soc_heritage as h


def rec(sid, year, comps, iso=("PL",), name="Site"):
    return {"id_no": sid, "name_en": name, "date_inscribed": f"{year}-01-01", "iso_codes": list(iso),
            "geo_point_2d": {"lon": 1.0, "lat": 2.0}, "components_list": json.dumps(comps),
            "category": "Cultural", "area_hectares": "5.5", "danger": "false", "secondary_dates": None}


class HeritageTest(unittest.TestCase):
    def test_memorial_and_components(self):
        comps = [{"name": "Auschwitz", "ref": "31-001", "latitude": 50.02, "longitude": 19.2},
                 {"name": "Birkenau", "ref": "31-002", "latitude": 50.04, "longitude": 19.18}]
        pts, _ = h.unesco_points([rec("31", 1979, comps)])
        site = pts[0]
        self.assertEqual(site["kind"], "memorial")
        self.assertAlmostEqual(site["lon"], 19.19)
        self.assertEqual([p["kind"] for p in pts[1:]], ["memorial_component"] * 2)

    def test_transboundary_keeps_polish_components_only(self):
        comps = [{"name": f"c{i}", "ref": f"1424-{i:03d}", "latitude": 49.0 + i / 100, "longitude": 22.0}
                 for i in range(1, 17)]
        pts, _ = h.unesco_points([rec("1424", 2013, comps, iso=("PL", "UA"))])
        self.assertEqual(pts[0]["props"]["components_in_poland"], 8)
        self.assertEqual(len(pts), 9)
        with self.assertRaises(RuntimeError):
            h.unesco_points([rec("9999", 2000, comps, iso=("PL", "DE"))])

    def test_ph_grouping(self):
        text = ("INSPIRE_ID;NAZWA;DOKLADNOSC_POLOZENIA;RODZAJ_POMNIKA_HISTORII;DATA_WPISU;WOJEWODZTWO;POWIAT;"
                "GMINA;MIEJSCOWOSC;ULICA;NR_ADRESOWY;E;N;LINK\n"
                "A1;Ksiaz;dokladny;zespol;31.07.2025;dolnoslaskie;p;g;m;;;16,2917;50,8403;http://x\n"
                "A2;Ksiaz;dokladny;zespol;31.07.2025;dolnoslaskie;p;g;m;;;16,3090;50,8293;http://x\n"
                "B1;Jawor;dokladny;zespol;15.03.2017;dolnoslaskie;p;g;m;;;16,1886;51,0542;\n")
        ms = {m["name"]: m for m in h.ph_monuments(text)}
        self.assertEqual(ms["Ksiaz"]["components"], 2)
        self.assertAlmostEqual(ms["Ksiaz"]["lon"], 16.30035)
        self.assertEqual(ms["Ksiaz"]["date"], "2025-07-31")
        self.assertIsNone(ms["Jawor"]["link"])


if __name__ == "__main__":
    unittest.main()

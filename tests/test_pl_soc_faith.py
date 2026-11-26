"""pl_soc_faith parsers: NSP row grouping, ISKK docx table, point-in-polygon and the parish vote."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from pipeline.sources import pl_soc_faith as f

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(path: Path, caption: str, rows: list[list[str]]):
    def cell(t):
        return f"<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"
    # split the first word over two runs, as Word does
    body = (f'<w:p><w:r><w:t>{caption[:3]}</w:t></w:r><w:r><w:t>{caption[3:]}</w:t></w:r></w:p>'
            "<w:tbl>" + "".join("<w:tr>" + "".join(cell(c) for c in r) + "</w:tr>" for r in rows) + "</w:tbl>")
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml.encode("utf-8"))


class NspTest(unittest.TestCase):
    ROWS = [
        {"B": "TABL.7. LUDNOŚĆ GMIN"},
        {"B": "Województwo", "C": "Powiat", "D": "Gmina", "E": "Kod gminy", "H": "Przynależność",
         "I": "W liczbach bezwzględnych", "J": "Procent ogółu ludności"},
        {"D": "gm. m. Boleławiec", "E": "0201011", "F": "Ogółem", "I": "37559", "J": "100"},
        {"E": "0201011", "G": "należący do wyznania\n    w tym:", "I": "24973", "J": "66.49"},
        {"E": "0201011", "H": "Kościół katolicki - obrządek łaciński "
         "(Kościół rzymskokatolicki)", "I": "24601", "J": "65.4996"},
        {"E": "0201011", "H": "Kościół Prawosławny", "I": "46", "J": "x"},
        {"E": "0201011", "H": "Wyznawcy Słońca", "I": "13", "J": "0.03"},
        {"E": "0201011", "F": "Odmawiający odpowiedzi na pytanie o wyznanie", "I": "9328", "J": "24.8"},
        {"D": "gm. w. Gromadka", "E": "0201032", "F": "Ogółem", "I": "5156", "J": "100"},
    ]

    def test_rows_grouped_by_code_and_label(self):
        units = f.nsp_rows(self.ROWS, "kod_gminy", f.GMINA_LABELS)
        self.assertEqual(units["0201011"]["roman_catholic"], (24601.0, 65.4996))
        self.assertEqual(units["0201011"]["religious"], (24973.0, 66.49))
        self.assertEqual(units["0201011"]["orthodox"], (46.0, None))
        self.assertNotIn("wyznawcy_slonca", units["0201011"])
        self.assertEqual(set(units), {"0201011", "0201032"})
        names = f.nsp_names(self.ROWS, "kod_gminy", "gmina")
        self.assertEqual(names["0201032"], "gm. w. Gromadka")

    def test_table_nulls_suppressed_and_computes_missing_share(self):
        units = f.nsp_rows(self.ROWS, "kod_gminy", f.GMINA_LABELS)
        rows = f.nsp_table(units, ["total", "orthodox", "lutheran"])
        self.assertEqual(rows["0201011"]["total"], 37559)
        self.assertAlmostEqual(rows["0201011"]["orthodox_share"], 0.122, places=3)  # 46 / 37559
        self.assertIsNone(rows["0201011"]["lutheran"])  # not published: under 10 people
        self.assertIsNone(rows["0201032"]["orthodox_share"])


class IskkTest(unittest.TestCase):
    def test_table_16(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.docx"
            _docx(p, "Tab. 16. Wskaźniki dominicantes i communicantes w 2024 roku według diecezji", [
                ["Diecezja", "Dominicantes", "Communicantes"],
                ["Ogółem", "29,57", "14,64"],
                ["tarnowska", "62,34", "26,17"],
                ["Ordynariat Polowy WP", "28,61", "13,64"],
                ["Obrządki wschodnie"],
                ["ormiańska", "bd", "bd"],
            ])
            tables = f.docx_tables(p)
            self.assertTrue(tables[0][0].startswith("Tab. 16"))
            vals, names = f.iskk_attendance(tables)
        self.assertEqual(vals["PL"], {"dominicantes": 29.57, "communicantes": 14.64})
        self.assertEqual(vals["tarnowska"]["dominicantes"], 62.34)
        self.assertIn("ordynariat_polowy_wp", vals)
        self.assertEqual(vals["eastern_ormianska"], {"dominicantes": None, "communicantes": None})
        self.assertEqual(f.diocese_key("Archidiecezja Krakowska"), "krakowska")
        self.assertEqual(f.diocese_key("Diecezja zamojsko-lubaczowska"), "zamojsko_lubaczowska")


class GeometryTest(unittest.TestCase):
    SQUARE_WITH_HOLE = [
        (0, 0, 10, 0), (10, 0, 10, 10), (10, 10, 0, 10), (0, 10, 0, 0),  # outer, any order
        (4, 4, 6, 4), (6, 6, 4, 6), (6, 4, 6, 6), (4, 6, 4, 4),          # inner
    ]

    def test_point_in_segments(self):
        self.assertTrue(f.point_in_segments(2, 2, self.SQUARE_WITH_HOLE))
        self.assertFalse(f.point_in_segments(5, 5, self.SQUARE_WITH_HOLE))
        self.assertFalse(f.point_in_segments(11, 5, self.SQUARE_WITH_HOLE))
        self.assertTrue(f.segments_closed(self.SQUARE_WITH_HOLE))
        self.assertFalse(f.segments_closed(self.SQUARE_WITH_HOLE[:3]))

    def test_vote_and_assign(self):
        parishes = [(0.1, 0.1, "a"), (0.2, 0.1, "a"), (0.3, 0.1, "b"), (5, 5, "b"), (5.1, 5, "b")]
        self.assertEqual(f.nearest_vote(0, 0, parishes, k=3), "a")
        outlines = {"b": {"closed": True, "bbox": (0, 0, 10, 10), "segments": self.SQUARE_WITH_HOLE}}
        self.assertEqual(f.assign(2, 2, outlines, parishes, k=3)[:2], ("b", "osm"))
        self.assertEqual(f.assign(-1, -1, outlines, parishes, k=3)[:2], ("a", "parishes"))
        self.assertEqual(f.parse_wkt_point("Point(19.93 50.06)"), (19.93, 50.06))

    def test_unit_points_prefer_seat(self):
        data = {"elements": [
            {"type": "relation", "tags": {"teryt:terc": "1465011"}, "center": {"lon": 21.06, "lat": 52.23}},
            {"type": "node", "lon": 21.0067, "lat": 52.2320, "tags": {"name": "Warszawa"}},
            {"type": "node", "lon": 99, "lat": 99},
            {"type": "relation", "tags": {"teryt:terc": "2005"}, "center": {"lon": 23.5, "lat": 52.8}},
            {"type": "relation", "tags": {"teryt:terc": "PL"}, "center": {"lon": 0, "lat": 0}},
            {"type": "node", "lon": 1, "lat": 1},
        ]}
        pts, seats = f.unit_points(data)
        self.assertEqual(pts, {"1465011": (21.0067, 52.2320), "2005": (23.5, 52.8)})
        self.assertEqual(seats, 1)
        self.assertEqual(f.PlSocFaith.remap_codes(["0218032", "1261011", "9999992"], {"0218033", "1261011"}),
                         {"0218032": "0218033", "1261011": "1261011"})


if __name__ == "__main__":
    unittest.main()

"""Parsers for the newest vintages: GUS regional GDP 2024 and the 30 June 2026 population balance."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from pipeline.sources.pl_gdp import gus_regional_gdp
from pipeline.sources.pl_geo_places import june_population
from pipeline.sources.pl_stats_population import _sex_xlsx


def _xlsx(rows: list[list]) -> bytes:
    """A one-sheet XLSX with inline strings and numbers."""
    def col(i):
        return chr(ord("A") + i)

    body = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{col(c)}{r}"
            if v is None:
                continue
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             f'spreadsheetml/2006/main"><sheetData>{"".join(body)}</sheetData></worksheet>')
    workbook = ('<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships"><sheets><sheet name="Tabl. 11" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


class GusRegionalGdpTest(unittest.TestCase):
    ROWS = [
        ["REGIONY\nREGIONS", "Ogółem \nTotal", None, None, "Na 1 mieszkańca"],
        ["P O L S K A    P O L A N D ….…...….", 3669531, 100, 107.4, 97786],
        ["Lubelskie ", 135536, 3.7, 109.6, 69026],
        ["Mazowiecki regionalny", 197312, 5.4, 106.3, 88094],
        ["Warszawski stołeczny ", 683617, 18.6, 109.3, 197889],
        ["Łódzkie ", 219773, 6, 106.5, 92344],
    ]

    def test_regions_to_voivodeships(self):
        rows, poland = gus_regional_gdp(self.ROWS)
        self.assertEqual(poland, 3_669_531_000_000)
        self.assertEqual(rows["06"]["gdp_pln"], 135_536_000_000)
        self.assertEqual(rows["10"]["gdp_pln"], 219_773_000_000)

    def test_mazowieckie_sums_its_two_regions(self):
        rows, _ = gus_regional_gdp(self.ROWS)
        self.assertEqual(rows["14"]["gdp_pln"], 880_929_000_000)
        self.assertEqual(rows["14"]["parts"], 2)
        per_person = rows["14"]["gdp_pln"] / rows["14"]["population"]
        self.assertTrue(88094 < per_person < 197889)


class JunePopulationTest(unittest.TestCase):
    def setUp(self):
        rows = [
            ["TABL. 11. LUDNOŚĆ"],
            ["Wyszczególnienie", "Identyfikator terytorialny", "Ogółem", "Mężczyźni", "Kobiety", "Miasta"],
            ["Woj.Małopolskie", "1200000", 3428677, 1, 1, 1],
            ["  Powiat bocheński", "1201000", 107000, 1, 1, 1],
            ["    m. Bochnia", "1201011", 29000, 14000, 15000, 29000],
            ["    gm.m-w. Nowy Wiśnicz", "1201043", 13000, 6500, 6500, 2800],
            ["Kraków", 1261011, 819493, 384315, 435178, 819493],
        ]
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "june.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("tabela11.xlsx", _xlsx(rows))
        self.by_gmina = _sex_xlsx(path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_whole_gminas_only(self):
        self.assertEqual(set(self.by_gmina), {"1201011", "1201043", "1261011"})
        self.assertEqual(self.by_gmina["1261011"]["population"], 819493)
        self.assertEqual(self.by_gmina["1261011"]["female"], 435178)

    def test_town_of_an_urban_rural_gmina_takes_the_urban_total(self):
        towns = [{"code": "1261011"}, {"code": "1201044"}, {"code": "1201011"}]
        self.assertEqual(june_population(towns, self.by_gmina),
                         {"1261011": 819493, "1201044": 2800, "1201011": 29000})


if __name__ == "__main__":
    unittest.main()

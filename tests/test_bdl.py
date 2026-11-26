from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import json

from pipeline.core import bdl

from pipeline.core.bdl import (
    bdl_url,
    is_whole_gmina,
    latest_value,
    load_pages,
    read_xlsx,
    teryt_from_bdl,
    value_for_year,
)


WORKBOOK = '''<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Dane" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
RELS = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Target="worksheets/sheet1.xml"
  Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
</Relationships>'''
SHARED = '''<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">
 <si><t>TERYT</t></si><si><r><t>Krak</t></r><r><t>ow</t></r></si>
</sst>'''
SHEET = '''<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Value</t></is></c></row>
 <row r="2"><c r="A2" t="s"><v>1</v></c><c r="C2"><v>42</v></c><c r="D2"><v>3.5</v></c><c r="E2" t="b"><v>1</v></c></row>
</sheetData></worksheet>'''


class TerytConversionTests(unittest.TestCase):
    def test_converts_known_city_and_rural_gminas(self):
        self.assertEqual(teryt_from_bdl("011212161011", 6), "1261011")  # Krakow
        self.assertEqual(teryt_from_bdl("031499165011", 6), "1465011")  # Warszawa
        self.assertEqual(teryt_from_bdl("012212305042", 6), "2205042")  # Sierakowice, rural

    def test_converts_parent_levels(self):
        unit = "011212161011"
        self.assertEqual(teryt_from_bdl(unit, 2), "12")
        self.assertEqual(teryt_from_bdl(unit, 5), "1261")

    def test_rejects_parts_as_whole_gminas(self):
        self.assertTrue(is_whole_gmina("1261011"))
        self.assertTrue(is_whole_gmina("2205042"))
        self.assertFalse(is_whole_gmina("3014044"))
        self.assertFalse(is_whole_gmina("1465028"))

    def test_rejects_malformed_ids_and_levels(self):
        with self.assertRaises(ValueError):
            teryt_from_bdl("1261011", 6)
        with self.assertRaises(ValueError):
            teryt_from_bdl("011212161011", 4)


class XlsxReaderTests(unittest.TestCase):
    def test_reads_shared_inline_numeric_boolean_and_blank_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.xlsx"
            with zipfile.ZipFile(path, "w") as book:
                book.writestr("xl/workbook.xml", WORKBOOK)
                book.writestr("xl/_rels/workbook.xml.rels", RELS)
                book.writestr("xl/sharedStrings.xml", SHARED)
                book.writestr("xl/worksheets/sheet1.xml", SHEET)
            self.assertEqual(
                read_xlsx(path, "Dane"),
                [["TERYT", "Value"], ["Krakow", None, 42, 3.5, True]],
            )


class BdlPageTests(unittest.TestCase):
    def test_builds_stable_url_with_repeated_years(self):
        self.assertEqual(
            bdl_url("data/by-variable/1", {"year": [2020, 2025], "unit-level": 6}),
            "https://bdl.stat.gov.pl/api/v1/data/by-variable/1?format=json&unit-level=6&year=2020&year=2025",
        )

    def test_loads_cached_pages_and_selects_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            page_dir = Path(tmp) / "population"
            page_dir.mkdir()
            records = [
                {"id": "a", "values": [{"year": "2020", "value": 2}, {"year": "2025", "value": 3}]},
                {"id": "b", "values": []},
            ]
            for page, record in enumerate(records):
                (page_dir / f"page-{page:03d}.json").write_text(
                    json.dumps({"totalRecords": 2, "page": page, "pageSize": 1, "results": [record]})
                )
            loaded = load_pages(Path(tmp), "population")
            self.assertEqual(loaded, records)
            self.assertEqual(value_for_year(loaded[0], 2020), 2)
            self.assertIsNone(value_for_year(loaded[1], 2025))
            self.assertEqual(latest_value(loaded[0]), (2025, 3))

    def test_qualified_bdl_values_stay_null(self):
        record = {"values": [
            {"year": "2024", "value": 10, "attrId": 1},
            {"year": "2025", "value": 11, "attrId": 91},
        ]}
        self.assertEqual(value_for_year(record, 2024), 10)
        self.assertIsNone(value_for_year(record, 2025))
        self.assertEqual(latest_value(record), (2024, 10))

    def test_published_zero_stays_zero(self):
        record = {"values": [{"year": "2025", "value": 0, "attrId": 0}]}
        self.assertEqual(value_for_year(record, 2025), 0)
        self.assertEqual(latest_value(record), (2025, 0))

    def test_stops_before_request_91(self):
        class FakeSource:
            id = "test"

            def __init__(self, raw_dir):
                self.raw_dir = raw_dir

            def download(self, *args, **kwargs):
                raise AssertionError("request must not start")

        with tempfile.TemporaryDirectory() as tmp:
            previous = bdl._request_count
            bdl._request_count = bdl.MAX_REQUESTS_PER_RUN
            try:
                with self.assertRaisesRegex(RuntimeError, "stopped before request 91"):
                    bdl.download_pages(FakeSource(Path(tmp)), "variables", "variables")
            finally:
                bdl._request_count = previous


if __name__ == "__main__":
    unittest.main()

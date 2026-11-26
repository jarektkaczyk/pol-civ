"""Enterprise sources (REGON, DBW innovation, GUNB permits) and their lenses."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from pipeline.build.lenses_more_a import lens_values
from pipeline.build.lenses_more_c import GROUPS_C, LENSES_C
from pipeline.sources import pl_econ_innovation as inno
from pipeline.sources import pl_econ_permits as permits
from pipeline.sources import pl_econ_regon as regon

T3 = """<!--
PAZDZIERNIK 2026
TABLICA 3: Podmioty gospodarki narodowej wedlug sekcji Polskiej Klasyfikacji Dzialalnosci (PKD 2007) oraz gmin
-->
<TABLICA_T3>
{rows}
</TABLICA_T3>
"""


def t3_row(code: str, total: int, j: int) -> str:
    return (f"<dane_tablica_T3><TERYT_WO_kod>{code[:2]}</TERYT_WO_kod><TERYT_WO_nazwa>X</TERYT_WO_nazwa>"
            f"<TERYT_POW_kod>{code[2:4]}</TERYT_POW_kod><TERYT_GMI_kod>{code[4:]}</TERYT_GMI_kod>"
            f"<TERYT_GMI_nazwa>X</TERYT_GMI_nazwa><Ogolem>{total}</Ogolem><DZIAL_J>{j}</DZIAL_J></dane_tablica_T3>")


class RegonTest(unittest.TestCase):
    def setUp(self):
        rows = [
            t3_row("1261011", 10, 1),   # Krakow: entities without a delegation
            t3_row("1261029", 100, 20),  # Krakow delegations
            t3_row("1261039", 50, 5),
            t3_row("0201043", 30, 3),   # urban-rural gmina
            t3_row("0201044", 20, 2),   # its town (repeats part of type 3)
            t3_row("0201045", 10, 1),   # its rural area
            t3_row("0201022", 7, 0),
        ]
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t03.xml"
        self.path.write_text(T3.format(rows="\n".join(rows)), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_header_and_rows(self):
        header, rows = regon.read_table(self.path)
        self.assertIn("PKD 2007", header)
        self.assertEqual({"OGOLEM": 30, "DZIAL_J": 3}, rows["0201043"])

    def test_city_adds_delegations_and_parts_are_not_counted_twice(self):
        _, rows = regon.read_table(self.path)
        whole = regon.whole_gminas(rows)
        self.assertEqual({"1261011", "0201043", "0201022"}, set(whole))
        self.assertEqual({"OGOLEM": 160, "DZIAL_J": 26}, whole["1261011"])
        self.assertEqual(30, whole["0201043"]["OGOLEM"])

    def test_old_type_digit_maps_to_current_code(self):
        rows, lost = regon.on_current({"0201022": {"OGOLEM": 7}, "9999992": {"OGOLEM": 1}}, ["0201023"])
        self.assertEqual({"0201023": {"OGOLEM": 7}}, rows)
        self.assertEqual(["9999992"], lost)

    def test_release_links_and_months(self):
        html = ('<a href="/obszary-tematyczne/podmioty-gospodarcze-wyniki-finansowe/zmiany-strukturalne-grup-podmiotow/'
                'miesieczna-informacja-o-podmiotach-gospodarki-narodowej-w-rejestrze-regon-pazdziernik-2026,4,118.html">'
                '<a href="/download/gfx/portalinformacyjny/pl/defaultaktualnosci/5504/4/118/1/'
                '202610_t06_dane_teryt_sfp_nowe.xml">')
        links = regon.release_links(html)
        self.assertEqual(["202610"], list(links))
        self.assertTrue(links["202610"].startswith("https://stat.gov.pl/"))
        self.assertTrue(regon.table_link(html, "202610", "t06").endswith("202610_t06_dane_teryt_sfp_nowe.xml"))
        self.assertIsNone(regon.table_link(html, "202610", "t03"))
        self.assertEqual("202511", regon.shift("202610", 11))
        self.assertEqual("October 2026", regon.month_label("202610"))

    def test_rate_needs_population(self):
        self.assertEqual(5.0, regon.per(5, 1000, 1000, 2))
        self.assertIsNone(regon.per(5, None, 1000, 2))
        self.assertIsNone(regon.per(None, 1000, 1000, 2))


class InnovationTest(unittest.TestCase):
    def test_symbol_to_teryt(self):
        self.assertEqual("PL", inno.teryt("10000000000000"))
        self.assertEqual("12", inno.teryt("10011200000000"))
        self.assertEqual("1261", inno.teryt("10011212161000"))
        self.assertEqual("0264", inno.teryt("10030210564000"))

    def test_flags(self):
        self.assertEqual(7, inno.cell_value({"id-brak-wartosci": 253, "wartosc": 7}))
        self.assertEqual(0, inno.cell_value({"id-brak-wartosci": 42, "wartosc": 0.0}))
        self.assertIsNone(inno.cell_value({"id-brak-wartosci": 42, "wartosc": 4.0}))  # contradictory
        self.assertIsNone(inno.cell_value({"id-brak-wartosci": 38, "wartosc": 0.0}))

    def test_retired_units_are_dropped_and_total_applicants_kept(self):
        positions = [
            {"id-wymiar": 10, "id-pozycja": 1, "symbol": "10011212161000", "data-konca": "9999-12-31"},
            {"id-wymiar": 10, "id-pozycja": 2, "symbol": "10071412831000", "data-konca": "2001-12-31"},
            {"id-wymiar": 203, "id-pozycja": inno.ALL_APPLICANTS, "symbol": "1", "data-konca": "9999-12-31"},
        ]
        codes = inno.units(positions, 10)
        self.assertEqual({1: "1261"}, codes)
        rows = [
            {"id-pozycja-1": 1, "id-pozycja-2": inno.ALL_APPLICANTS, "id-sposob-prezentacji-miara": 94,
             "id-brak-wartosci": 253, "wartosc": 12.0},
            {"id-pozycja-1": 1, "id-pozycja-2": 2541632, "id-sposob-prezentacji-miara": 94,
             "id-brak-wartosci": 253, "wartosc": 5.0},
            {"id-pozycja-1": 2, "id-pozycja-2": inno.ALL_APPLICANTS, "id-sposob-prezentacji-miara": 94,
             "id-brak-wartosci": 253, "wartosc": 3.0},
        ]
        self.assertEqual({"1261": 12.0}, inno.patents_by_unit(rows, codes))


class PermitsTest(unittest.TestCase):
    HEADER = ("﻿numer_urzad;nazwa_organu;numer_decyzji_urzedu;data_wydania_decyzji;nazwa_inwestor;terc;"
              "kategoria;nazwa_zamierzenia_bud;projektant_nazwisko;projektant_imie")

    def lines(self, *rows):
        return [self.HEADER + "\n"] + [r + "\n" for r in rows]

    def test_names_are_dropped_at_read_time(self):
        rows = list(permits.iter_rows(self.lines(
            "1;Starosta A;5/2026;2026-05-01 00:00:00;Jan Kowalski;1661011;XVIII;budowa nowego/nowych obiektow;"
            "Nowak;Anna")))
        self.assertEqual(set(permits.KEEP), set(rows[0]))
        self.assertNotIn("Jan Kowalski", rows[0].values())
        self.assertNotIn("Nowak", rows[0].values())

    def test_counts_unique_decisions_in_window(self):
        new = "budowa nowego/nowych obiektow budowlanych"
        rows = permits.iter_rows(self.lines(
            f"1;Starosta A;5/2026;2026-05-01 00:00:00;x;1607054;XVIII;{new};x;x",  # town part -> 1607053
            f"2;Starosta A;5/2026;2026-05-01 00:00:00;x;1607055;XVIII;{new};x;x",  # same decision, rural part
            f"3;Starosta A;6/2026;2026-06-01 00:00:00;x;1607053;XVIII;{new};x;x",
            f"4;Starosta A;7/2026;2026-06-01 00:00:00;x;1607053;XVII;{new};x;x",  # other category
            f"5;Starosta A;8/2026;2026-06-01 00:00:00;x;1607053;XVIII;rozbudowa istniejacego;x;x",  # extension
            f"6;Starosta A;1/2024;2024-01-01 00:00:00;x;1607053;XVIII;{new};x;x",  # before the window
            f"7;Prezydent B;9/2026;2026-07-01 00:00:00;x;1465048;XVIII;{new};x;x",  # Warsaw district
            f"8;Prezydent B;10/2026;2026-07-01 00:00:00;x;;XVIII;{new};x;x",  # no TERC
        ))
        decisions, stats = {}, {}
        by6 = {"160705": "1607053", "146501": "1465011"}
        permits.count_decisions(rows, dt.date(2024, 11, 25), dt.date(2026, 11, 25), by6, decisions, stats)
        self.assertEqual(2, len(decisions["1607053"]))
        self.assertEqual(1, len(decisions["1465011"]))
        self.assertEqual(1, len(stats["unmapped"]))

    def test_part_codes_and_window(self):
        self.assertEqual("1607053", permits.whole_gmina("1607055"))
        self.assertEqual("1261011", permits.whole_gmina("1261029"))
        self.assertEqual("0201022", permits.whole_gmina("0201022"))
        self.assertIsNone(permits.whole_gmina(""))
        self.assertEqual(dt.date(2024, 11, 25), permits.months_before(dt.date(2026, 11, 25), 24))
        self.assertEqual(dt.date(2026, 2, 28), permits.months_before(dt.date(2026, 3, 31), 1))


class FakeStats:
    def __init__(self, tables):
        self.tables = tables
        self.payload = {source: {} for source, _ in tables}

    def rows(self, source, table):
        return self.tables.get((source, table), {})


class EnterpriseLensesTest(unittest.TestCase):
    def test_lens_set(self):
        ids = [spec[0] for spec in LENSES_C]
        self.assertEqual(["tech_firms", "new_firms", "sole_traders", "patents", "rd_spending", "new_industry"], ids)
        for spec in LENSES_C:
            data = spec[6]["_data"]
            self.assertEqual("enterprise", data["metric"]["group"])
            self.assertTrue(spec[6]["note"].startswith("Per "), spec[0])
        self.assertEqual("enterprise", GROUPS_C[0]["id"])

    def test_share_is_a_fraction_and_powiat_reaches_gminas(self):
        tech = next(spec[6]["_data"] for spec in LENSES_C if spec[0] == "tech_firms")
        stats = FakeStats({("pl_econ_regon", "regon_gmina"): {"1261011": {"ict_share": 13.4}}})
        _, values = lens_values(tech, stats, ["1261011", "0201011"])
        self.assertAlmostEqual(0.134, values[0])
        self.assertIsNone(values[1])
        pat = next(spec[6]["_data"] for spec in LENSES_C if spec[0] == "patents")
        stats = FakeStats({("pl_econ_innovation", "patents_powiat"): {"1863": {"patents_per_100k": 123.8}}})
        _, values = lens_values(pat, stats, ["1863011", "1816012"])
        self.assertEqual([123.8, None], values)


if __name__ == "__main__":
    unittest.main()

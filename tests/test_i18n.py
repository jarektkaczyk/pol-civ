"""English and Polish: the catalogue lookup, plurals, number and date formats, ISO dates in data, the missing-key check.

The browser half (web/js/i18n.js) runs under node when it is installed.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline.build import i18n as i18n_check
from pipeline.core import i18n

ROOT = Path(__file__).resolve().parent.parent
I18N_JS = ROOT / "web" / "js" / "i18n.js"
NBSP = " "
CAT = {
    "Median age": "Mediana wieku",
    "{name} in {year}": "{name} w roku {year}",
    "{n} towns": {"one": "{n} miasto", "few": "{n} miasta", "many": "{n} miast"},
    "Population on {date}": "Ludność {date}",
}


class IsoDatesTest(unittest.TestCase):
    def test_english_dates_become_iso(self):
        self.assertEqual(i18n.iso_dates("GUS population 30 June 2026; students 31 Dec 2025"),
                         "GUS population 2026-06-30; students 2025-12-31")
        self.assertEqual(i18n.iso_dates("GUS, October 2026, May 2026, and December 2025"),
                         "GUS, 2026-10, 2026-05, and 2025-12")
        self.assertEqual(i18n.iso_dates("June 30, 2026"), "2026-06-30")
        self.assertEqual(i18n.iso_dates("closed 31 Sept 2025"), "closed 31 Sept 2025")  # not a real date

    def test_other_text_is_left_alone(self):
        for s in ["Varso Tower", "Sejm 2023", "2015 to 2025", "Plac 3 Maja", "May I help", "2017-2021"]:
            self.assertEqual(i18n.iso_dates(s), s)

    def test_deep_skips_links_and_ids(self):
        doc = {"note": "as of 1 January 2026", "ref": "https://x/1 January 2026", "items": [{"vintage": "May 2026"}]}
        self.assertEqual(i18n.iso_dates_deep(doc),
                         {"note": "as of 2026-01-01", "ref": "https://x/1 January 2026", "items": [{"vintage": "2026-05"}]})


class FormatTest(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(i18n.fmt_date("2026-06-30", "en"), "30 June 2026")
        self.assertEqual(i18n.fmt_date("2026-06-30", "pl"), "30 czerwca 2026")
        self.assertEqual(i18n.fmt_date("2026-10", "pl"), "październik 2026")
        self.assertEqual(i18n.fmt_date("2025", "pl"), "2025")

    def test_dates_inside_text(self):
        self.assertEqual(i18n.localize_dates("GUS, 2025-12-31 and 2026-10.", "pl"),
                         "GUS, 31 grudnia 2025 and październik 2026.")
        # links, file names and year spans stay
        for s in ["https://x.pl/2026-04/a", "regional/2026-01/x.xlsx", "2017-2021", "rounds 2015-2025", "?d=2026-10-01"]:
            self.assertEqual(i18n.localize_dates(s, "pl"), s)

    def test_numbers(self):
        self.assertEqual(i18n.fmt_num(1866929, 0, "en"), "1,866,929")
        self.assertEqual(i18n.fmt_num(1866929, 0, "pl"), f"1{NBSP}866{NBSP}929")
        self.assertEqual(i18n.fmt_num(9178, 0, "pl"), "9178")  # Polish groups from five digits
        self.assertEqual(i18n.fmt_num(12.5, 1, "pl"), "12,5")
        self.assertEqual(i18n.fmt_num(-12345.25, 2, "pl"), f"-12{NBSP}345,25")
        self.assertEqual(i18n.fmt_pct(0.163, 1, "pl"), "16,3%")
        self.assertEqual(i18n.fmt_pct(0.163, 1, "en"), "16.3%")


class CatalogueTest(unittest.TestCase):
    def test_lookup_and_placeholders(self):
        self.assertEqual(i18n.t("Median age", "pl", CAT), "Mediana wieku")
        self.assertEqual(i18n.t("Median age", "en", CAT), "Median age")
        self.assertEqual(i18n.t("{name} in {year}", "pl", CAT, name="Kraków", year="2025"), "Kraków w roku 2025")
        self.assertEqual(i18n.t("Not there", "pl", CAT), "Not there")  # falls back to English
        self.assertEqual(i18n.t("Population on {date}", "pl", CAT, date="2026-06-30"), "Ludność 30 czerwca 2026")
        self.assertEqual(i18n.t("{name} in {year}", "en", CAT, name="X", year=2024), "X in 2024")  # no "2,024"

    def test_polish_plural_rules(self):
        cats = {n: i18n.plural_category(n, "pl") for n in [0, 1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 104, 112, 1.5]}
        self.assertEqual(cats, {0: "many", 1: "one", 2: "few", 4: "few", 5: "many", 11: "many", 12: "many", 14: "many",
                                21: "many", 22: "few", 25: "many", 104: "few", 112: "many", 1.5: "other"})
        forms = {"one": "{n} town", "other": "{n} towns"}
        got = [i18n.plural(n, forms, "pl", CAT) for n in (1, 3, 5, 22, 12345)]
        self.assertEqual(got, ["1 miasto", "3 miasta", "5 miast", "22 miasta", f"12{NBSP}345 miast"])
        self.assertEqual([i18n.plural(n, forms, "en", CAT) for n in (1, 2)], ["1 town", "2 towns"])


class ExtractTest(unittest.TestCase):
    def make_site(self, cat):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / "js" / "ui").mkdir(parents=True)
        (tmp / "data").mkdir()
        (tmp / "i18n").mkdir()
        (tmp / "js" / "ui" / "a.js").write_text(
            'const a = t("Open the map");\n'
            "const b = t('It\\'s here', {x: 1});\n"
            "// t(\"In a comment\")\n"
            "const c = t(`Plain template`);\n"
            "const d = t(`Has ${x}`);\n"
            'const e = t.plural(n, { one: "{n} town", other: "{n} towns" });\n'
            "const f = t(lens.name);\n"
            'const g = format("not a key");\n', encoding="utf-8")
        (tmp / "data" / "lenses.json").write_text(json.dumps(
            {"vintage": "GUS 2026-06-30", "groups": [{"name": "People"}],
             "lenses": [{"id": "age", "name": "Median age", "unit": "years", "description": None, "color": "#fff"}]}))
        (tmp / "index.html").write_text(
            '<html><head><title>Polska</title><meta name="description" content="A map of Poland"></head>'
            '<body><button aria-label="Share this view"></button><p>Text version</p><script>var x="no";</script></body></html>')
        (tmp / "i18n" / "pl.json").write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
        return tmp

    def test_keys_from_js_data_and_html(self):
        web = self.make_site({})
        keys = i18n.all_keys(web)
        for k in ["Open the map", "It's here", "Plain template", "{n} towns", "People", "Median age", "years",
                  "GUS 2026-06-30", "A map of Poland", "Share this view", "Text version", "Polska"]:
            self.assertIn(k, keys)
        for k in ["In a comment", "not a key", "#fff", "age", "no"]:
            self.assertNotIn(k, keys)
        self.assertTrue(keys["{n} towns"]["plural"])
        self.assertTrue(any(w.startswith("js/ui/a.js:1") for w in keys["Open the map"]["where"]))

    def test_missing_and_check(self):
        web = self.make_site({"Open the map": "Otwórz mapę", "{n} towns": {"one": "{n} miasto"}})
        miss = i18n.missing(web, i18n.load_catalogue(web / "i18n" / "pl.json"))
        self.assertNotIn("Open the map", miss)
        self.assertIn("{n} towns", miss)  # a plural entry needs one, few and many
        self.assertIn("Median age", miss)
        lines = i18n_check.check(web / "data")
        self.assertEqual(lines[0][0], "FAIL")
        self.assertIn(f"{len(miss)} of", lines[0][1])

    def test_complete_catalogue_passes(self):
        web = self.make_site({})
        full = {k: ({"one": "a {n}", "few": "b {n}", "many": "c {n}"} if v["plural"] else "x " + k)
                for k, v in i18n.all_keys(web).items()}
        (web / "i18n" / "pl.json").write_text(json.dumps(full), encoding="utf-8")
        i18n._CACHE.clear()
        self.assertEqual([lv for lv, _ in i18n_check.check(web / "data")], ["PASS"])

    def test_placeholder_problems(self):
        probs = i18n.placeholder_problems({"{a} and {b}": "{a} i {c}", "Bold": "<b>Pogrubione</b>", "Fine {n}": "Dobrze {n}"})
        self.assertEqual(len(probs), 2)


JS = r"""
const m = await import(process.argv[1]);
const en = {
  t: m.t("Median age"), num: m.num(1866929), pct: m.pct(0.163), compact: m.compact(3.92e12), money: m.money(3.92e12),
  zloty: m.zloty(9178), date: m.date("2026-06-30"), month: m.date("2026-10"), plural: [1, 2].map((n) => m.t.plural(n, {one: "{n} town", other: "{n} towns"})),
  text: m.t("GUS, 2025-12-31"), href: m.langHref("pl", {pathname: "/pol-civ/", search: "", hash: "#city=1261011"}),
  bare: m.langHref("pl", {pathname: "/pol-civ", search: "", hash: ""}), year: m.t("{name} in {year}", {name: "X", year: 2024}),
  small: m.sig(0.000456), mid: m.sig(12.345),
};
m.setLocale("pl", JSON.parse(process.argv[2]));
const pl = {
  t: m.t("Median age"), vars: m.t("{name} in {year}", {name: "Kraków", year: 2025}), missing: m.t("Not there"),
  num: m.num(1866929), small: m.num(9178), dec: m.num(12.5, 1), pct: m.pct(0.163), compact: m.compact(3.92e12),
  money: m.money(3.92e12), mln: m.compact(18.6e6), tys: m.compact(12000), zloty: m.zloty(19178), pop: m.popShort(1866929),
  date: m.date("2026-06-30"), month: m.date("2026-10"),
  plural: [1, 2, 5, 12, 22, 1.5].map((n) => m.t.plural(n, {one: "{n} town", other: "{n} towns"})),
  cats: [0, 1, 3, 13, 23, 111].map((n) => m.pluralCategory(n)),
  text: m.t("Population on {date}", {date: "2026-06-30"}),
  href: m.langHref("en", {pathname: "/pol-civ/pl/", search: "", hash: "#lens=age"}),
};
console.log(JSON.stringify({en, pl}));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BrowserI18nTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run(["node", "--input-type=module", "-e", JS, I18N_JS.as_uri(), json.dumps(CAT)],
                             capture_output=True, text=True, timeout=30, check=True)
        cls.out = json.loads(run.stdout)

    def test_english(self):
        en = self.out["en"]
        self.assertEqual(en["t"], "Median age")
        self.assertEqual((en["num"], en["pct"], en["compact"], en["money"]), ("1,866,929", "16.3%", "3.92T", f"3.92T{NBSP}zł"))
        self.assertEqual((en["date"], en["month"]), ("30 June 2026", "October 2026"))
        self.assertEqual(en["plural"], ["1 town", "2 towns"])
        self.assertEqual(en["text"], "GUS, 31 December 2025")
        self.assertEqual(en["href"], "/pol-civ/pl/#city=1261011")
        self.assertEqual((en["bare"], en["year"]), ("/pol-civ/pl/", "X in 2024"))
        self.assertEqual((en["small"], en["mid"]), ("0.000456", "12.3"))

    def test_polish(self):
        pl = self.out["pl"]
        self.assertEqual((pl["t"], pl["vars"], pl["missing"]), ("Mediana wieku", "Kraków w roku 2025", "Not there"))
        self.assertEqual((pl["num"], pl["small"], pl["dec"], pl["pct"]), (f"1{NBSP}866{NBSP}929", "9178", "12,5", "16,3%"))
        self.assertEqual((pl["compact"], pl["money"], pl["mln"], pl["tys"]),
                         (f"3,92{NBSP}bln", f"3,92{NBSP}bln{NBSP}zł", f"18,6{NBSP}mln", f"12{NBSP}tys."))
        self.assertEqual((pl["zloty"], pl["pop"]), (f"19{NBSP}178{NBSP}zł", f"1,9{NBSP}mln"))
        self.assertEqual((pl["date"], pl["month"]), ("30 czerwca 2026", "październik 2026"))
        self.assertEqual(pl["plural"], ["1 miasto", "2 miasta", "5 miast", "12 miast", "22 miasta", "1,5 miasta"])
        self.assertEqual(pl["cats"], ["many", "one", "few", "many", "few", "many"])
        self.assertEqual(pl["text"], "Ludność 30 czerwca 2026")
        self.assertEqual(pl["href"], "/pol-civ/#lens=age")



class DatePatternTest(unittest.TestCase):
    """A source line whose dates move keeps one catalogue entry (pipeline/core/i18n.py date_pattern, lookup)."""

    CAT = {"GUS, {d1}, {d2}, and {d3}": "GUS, {d1}, {d2} i {d3}", "Change 2015-2025": "Zmiana 2015-2025",
           "Exact 2026-10": "Dokladnie 2026-10"}

    def test_pattern(self):
        self.assertEqual(i18n.date_pattern("GUS, 2026-10, 2026-05, and 2025-12"),
                         ("GUS, {d1}, {d2}, and {d3}", ["2026-10", "2026-05", "2025-12"]))
        self.assertEqual(i18n.date_pattern("Change 2015-2025")[1], [])  # a range stays literal
        self.assertEqual(i18n.date_pattern("Census 2021-03-31")[0], "Census {d1}")

    def test_lookup_by_pattern(self):
        self.assertEqual(i18n.lookup("GUS, 2026-11, 2026-05, and 2025-12", self.CAT), "GUS, 2026-11, 2026-05 i 2025-12")
        self.assertEqual(i18n.t("GUS, 2026-11, 2026-05, and 2025-12", "pl", self.CAT),
                         "GUS, listopad 2026, maj 2026 i grudzień 2025")

    def test_exact_entry_wins(self):
        self.assertEqual(i18n.lookup("Exact 2026-10", {**self.CAT, "Exact {d1}": "Wzor {d1}"}), "Dokladnie 2026-10")
        self.assertIsNone(i18n.lookup("Nothing 2026-10", self.CAT))


if __name__ == "__main__":
    unittest.main()

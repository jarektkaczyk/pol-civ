"""Economy site layers: curated fact lists (pl_econ_champions, pl_tech_sites), Wikidata studio parsing, the builder."""

import json
import unittest

from pipeline.build import economy as eco
from pipeline.core.geo import Shape
from pipeline.core.i18n import CATALOGUE, iso_dates_deep
from pipeline.sources import _econ_sites as common
from pipeline.sources import pl_econ_champions as champ
from pipeline.sources import pl_tech_sites as tech

CATALOG = json.loads(CATALOGUE.read_text(encoding="utf-8"))


def curated(module, name):
    return common.load_json(module.__file__, name)


class CuratedListsTest(unittest.TestCase):
    def check_list(self, doc, low, high):
        kinds = {k["id"] for k in doc["kinds"]}
        items = doc["items"]
        self.assertTrue(low <= len(items) <= high, len(items))
        ids = [it["id"] for it in items]
        self.assertEqual(len(ids), len(set(ids)))
        for it in items:
            self.assertEqual(common.check_item(it, kinds), [], it["id"])
            self.assertIn(it["kind"], eco.KIND_LAYER, it["id"])
            # The Polish UI shows the Polish fact from the catalogue; its key is the text as written to web/data
            # (dates in ISO, which the browser formats per language).
            self.assertEqual(CATALOG.get(iso_dates_deep(it["fact"])), it["fact_pl"], it["id"])
            if it.get("label"):
                self.assertEqual(CATALOG.get(it["label"]), it["label_pl"], it["id"])

    def test_made_in_poland(self):
        doc = curated(champ, champ.CURATED)
        self.check_list(doc, 25, 35)
        names = " ".join(it["name"] for it in doc["items"])
        for gone in ("Intel", "Volvo", "Philip Morris", "KGHM", "Orlen", "Be\u0142chat\u00f3w", "Baltic Hub"):
            self.assertNotIn(gone, names)
        lges = next(it for it in doc["items"] if it["id"] == "mp_lges_wroclaw")
        self.assertNotIn("GWh", lges["fact"])

    def test_tech_landmarks(self):
        self.check_list(curated(tech, tech.CURATED), 25, 50)

    def test_check_item_flags_problems(self):
        bad = {"id": "x", "name": "X", "place": "P", "kind": "cars", "lon": 30.0, "lat": 52.0,
               "fact": "A \u2014 B", "fact_pl": "A", "year": 2031, "ref": "http://example.org"}
        problems = " ".join(common.check_item(bad, {"cars"}))
        for word in ("outside Poland", "https", "year", "dash"):
            self.assertIn(word, problems)


def binding(**kw):
    return {k: {"value": v} for k, v in kw.items()}


class WikidataStudiosTest(unittest.TestCase):
    def test_studio_rows_keep_active_studios_with_a_town_in_poland(self):
        rows = [
            binding(studio="http://www.wikidata.org/entity/Q1", studioLabel="A", hq="http://www.wikidata.org/entity/Q270",
                    hqLabel="Warszawa", coord="Point(21.0 52.2)", sitelinks="9"),
            binding(studio="http://www.wikidata.org/entity/Q1", studioLabel="A", hq="http://www.wikidata.org/entity/Q580",
                    hqLabel="Zielonka", coord="Point(21.15 52.3)", sitelinks="9"),
            binding(studio="http://www.wikidata.org/entity/Q2", studioLabel="B", hq="http://www.wikidata.org/entity/Q36",
                    hqLabel="Polska", coord="Point(19.0 52.0)", sitelinks="1"),
            binding(studio="http://www.wikidata.org/entity/Q3", studioLabel="C", hq="http://www.wikidata.org/entity/Q31",
                    hqLabel="Dover", coord="Point(-75.5 39.1)", sitelinks="1"),
            binding(studio="http://www.wikidata.org/entity/Q4", studioLabel="D", hq="http://www.wikidata.org/entity/Q31487",
                    hqLabel="Krakow", coord="Point(19.9 50.06)", dissolved="2010-01-01T00:00:00Z", sitelinks="2"),
        ]
        out = tech.studio_rows(rows)
        self.assertEqual(list(out), ["Q1"])
        self.assertEqual(out["Q1"]["hq_name"], "Warszawa")  # first by name
        self.assertEqual(tech.studio_rows(rows, {"Q1": "Q580"})["Q1"]["hq_name"], "Zielonka")

    def test_best_game_skips_announced_and_unlabelled_games(self):
        rows = [
            binding(studio="x/Q1", game="x/Q10", gameLabel="Old Hit", year="2015", links="30"),
            binding(studio="x/Q1", game="x/Q11", gameLabel="Announced", year="2027", links="40"),
            binding(studio="x/Q1", game="x/Q12", gameLabel="Q12", year="2020", links="50"),
            binding(studio="x/Q1", game="x/Q13", gameLabel="New", year="2024", links="30"),
        ]
        games = tech.best_games(rows)["Q1"]
        self.assertEqual([g["title"] for g in games], ["New", "Old Hit"])


class BuilderTest(unittest.TestCase):
    def test_gmina_by_point_in_polygon(self):
        square = lambda x0, y0: [[(x0, y0), (x0 + 1, y0), (x0 + 1, y0 + 1), (x0, y0 + 1)]]
        index = [("1465011", Shape(square(20, 52))), ("1418042", Shape(square(21, 52)))]
        self.assertEqual(eco.gmina_at(index, 20.5, 52.5), "1465011")
        self.assertEqual(eco.gmina_at(index, 21.5, 52.5), "1418042")
        self.assertIsNone(eco.gmina_at(index, 25.0, 52.5))

    def test_every_kind_has_a_layer(self):
        self.assertEqual({k["layer"] for k in eco.KINDS}, {"made", "tech"})
        self.assertEqual({k["id"] for k in eco.KINDS}, set(eco.KIND_LAYER))


if __name__ == "__main__":
    unittest.main()

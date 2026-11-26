"""pipeline/build/seo.py: slugs, page model, JSON-LD, sitemap, llms.txt and check() on a tiny synthetic site."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from pipeline.build import seo

SOURCES = [
    {"id": "pl_stats_population", "publisher": "Statistics Poland (GUS)", "title": "Population", "vintage": "GUS population 31 December 2025",
     "homepage": "https://stat.gov.pl/"},
    {"id": "pl_stats_labour", "publisher": "Statistics Poland (GUS)", "title": "Labour", "vintage": "2026", "homepage": "https://stat.gov.pl/"},
    {"id": "pl_geo_places", "publisher": "GUS; OpenStreetMap contributors", "title": "Towns", "vintage": "2026", "homepage": "https://stat.gov.pl/"},
    {"id": "pl_gdp", "publisher": "Eurostat", "title": "GDP", "vintage": "2024", "homepage": "https://ec.europa.eu/eurostat"},
    {"id": "pl_soc_air", "publisher": "GIOŚ", "title": "Air", "vintage": "2025", "homepage": "https://powietrze.gios.gov.pl/"},
]


def econ(pop, growth, wage, unemp, gdp=None, year=None):
    return {"population": pop, "employed": pop // 2, "wage": wage, "unemployment": unemp, "pit_per_person": 4000.0 + pop % 997,
            "gdp": gdp, "gdp_year": year, "growth": growth, "growth_years": [2015, 2025],
            "pop_series": {"2015": round(pop / (1 + growth)) if growth is not None else None, "2025": pop}}


def town(id_, name, voiv, pop, rank, growth, view=True, kind="city", x=100.0, y=100.0):
    return {"id": id_, "name": name, "full": f"{name}, Test", "voivodeship": voiv, "powiat": id_[:4], "gmina": id_, "kind": kind,
            "city_view": view, "capital": rank == 1, "x": x, "y": y, "cell": 0, "fua": None, "scope": "city",
            "footprint": [0], "ranks": {"population": rank}, "peers": [], **econ(pop, growth, 9000 + rank, 0.05)}


def dataset():
    world = {"grid": {"radius": 5, "cols": 4, "rows": 2}, "owner": [0, 0, 1, 1, 0, 1, -1, -2],
             "projection": {"min_x": -362.16, "max_y": 350.3, "margin": 0}, "states": [], "counties": []}
    states = [
        {"fips": "12", "abbr": "MA", "name": "Małopolskie", "capitals": [{"gmina": "1261011", "name": "Kraków", "role": "both"}],
         "land": {"forest": 0.3}, **econ(3_400_000, 0.04, 9100, 0.04, 3e11, 2024)},
        {"fips": "10", "abbr": "LD", "name": "Łódzkie", "capitals": [{"gmina": "1061011", "name": "Łódź", "role": "both"}],
         "land": {"forest": 0.2}, **econ(2_300_000, -0.06, 8500, 0.06, 2e11, 2024)},
    ]
    cities = [town("1261011", "Kraków", "12", 816614, 2, 0.073, x=400, y=560),
              town("1061011", "Łódź", "10", 639890, 3, -0.09, x=360, y=420),
              town("1001022", "Bełchatów", "10", 55000, 50, -0.1, view=False, kind="town")]
    nation = {"vintage": "GUS population 31 December 2025", "years": {"population": 2025, "wage": 2026, "unemployment": 2026, "pit": 2026},
              "nation": econ(37_332_510, -0.0287, 9178, 0.058, 3.9e12, 2025)}
    cols = ["geoid", "name", "type", "powiat", "state", "population", "median_age", "pm25", "air_station", "turnout_2025", "president_2025"]
    counties = {"columns": cols, "fields": [{"key": "wage", "description": "GUS wage distribution, May 2026."},
                                            {"key": "unemployment", "description": "Registered rate, end of October 2026 (GUS)."}],
                "rows": [["1261011", "Kraków", "urban", "Kraków (city)", "MA", 816614, 41.3, 18.4, "Kraków, Aleja (4 km)", 0.797, 0.378],
                         ["1061011", "Łódź", "urban", "Łódź (city)", "LD", 639890, 46.0, None, None, 0.70, 0.40]]}
    return {"world.json": world, "states.json": states, "cities.json": cities, "nation.json": nation,
            "counties.json": counties, "sources.json": SOURCES}


class SeoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.web = Path(self.tmp.name) / "web"
        (self.web / "data").mkdir(parents=True)
        for name, doc in dataset().items():
            (self.web / "data" / name).write_text(json.dumps(doc, ensure_ascii=False))
        (self.web / "og-image.png").write_bytes(b"x")
        (self.web / "index.html").write_text(
            '<html><head><meta http-equiv="Content-Security-Policy" content="' + seo.APP_CSP.replace("'", "&#x27;") + '">'
            "<!-- seo:jsonld --><!-- /seo:jsonld --></head><body><!-- seo:beacon --><!-- /seo:beacon --></body></html>")
        self.res = seo.build_site(self.web, date="2026-11-26")

    def tearDown(self):
        self.tmp.cleanup()

    def test_slugs_fold_polish_letters(self):
        self.assertEqual(seo.slug("Łódź"), "lodz")
        self.assertEqual(seo.slug("Kraków"), "krakow")
        self.assertEqual(seo.slug("Gdańsk"), "gdansk")
        self.assertEqual(seo.slug("Bielsko-Biała"), "bielsko-biala")
        self.assertEqual(seo.slug("Świętokrzyskie"), "swietokrzyskie")
        self.assertEqual(seo.slug("Ostrów Wielkopolski"), "ostrow-wielkopolski")

    def test_pages_for_every_voivodeship_and_view_town(self):
        self.assertEqual(self.res["pages"], 1 + 2 + 2)
        for p in ("atlas", "atlas/malopolskie", "atlas/lodzkie", "atlas/krakow", "atlas/lodz"):
            self.assertTrue((self.web / p / "index.html").exists(), p)
            self.assertTrue((self.web / p / "index.md").exists(), p)
        self.assertFalse((self.web / "atlas" / "belchatow").exists())

    def test_jsonld_parses_and_has_required_keys(self):
        text = (self.web / "atlas" / "krakow" / "index.html").read_text()
        (ld,) = seo.jsonld_of(text)
        self.assertEqual(ld["@context"], "https://schema.org")
        nodes = {n["@type"]: n for n in ld["@graph"]}
        self.assertEqual(set(nodes), {"WebPage", "BreadcrumbList", "City", "Observation"})
        page, city, obs = nodes["WebPage"], nodes["City"], nodes["Observation"]
        for k in ("url", "name", "description", "dateModified", "author", "isPartOf", "breadcrumb", "about"):
            self.assertIn(k, page)
        self.assertEqual(page["url"], seo.SITE_URL + "atlas/krakow/")
        self.assertEqual(city["containedInPlace"]["name"], "Małopolskie Voivodeship")
        self.assertEqual(city["identifier"]["value"], "1261011")
        self.assertTrue(49 < city["geo"]["latitude"] < 55 and 14 < city["geo"]["longitude"] < 25)
        self.assertEqual(obs["value"], 816614)
        self.assertEqual(obs["observationDate"], "2025-12-31")
        self.assertEqual(obs["observationAbout"]["@id"], city["@id"])
        crumbs = [i["name"] for i in nodes["BreadcrumbList"]["itemListElement"]]
        self.assertEqual(crumbs, ["Polska", "Atlas", "Małopolskie", "Kraków"])

    def test_page_text_leads_with_a_computed_fact_and_cites_sources(self):
        md = (self.web / "atlas" / "krakow" / "index.md").read_text()
        # growth ranks 1st of the 2 towns, size 2nd: the better rank leads
        self.assertIn("Kraków grew by 7.3% between 2015 and 2025, the fastest growth of the 2 Polish towns", md)
        self.assertNotIn("pl_stats_prosperity:", md)
        self.assertIn("Statistics Poland (GUS)", md.split("## Sources")[1])
        self.assertIn("#city=1261011&view=city", md)
        self.assertNotRegex(md, "[–—→“”]")  # no dashes, arrows or curly quotes
        lodz = (self.web / "atlas" / "lodzkie" / "index.md").read_text()
        self.assertIn("Łódzkie", lodz)

    def test_sitemap_urls_match_files(self):
        locs = re.findall(r"<loc>(.*?)</loc>", (self.web / "sitemap.xml").read_text())
        self.assertEqual(locs[0], seo.SITE_URL)
        pages = {p.parent.relative_to(self.web).as_posix() + "/" for p in (self.web / "atlas").rglob("index.html")}
        self.assertEqual({u[len(seo.SITE_URL):] for u in locs[1:]}, pages)
        self.assertIn("<lastmod>2026-11-26</lastmod>", (self.web / "sitemap.xml").read_text())

    def test_llms_txt_structure(self):
        text = (self.web / "llms.txt").read_text()
        self.assertEqual(seo.llms_problems(text, self.web), [])
        self.assertTrue(text.startswith("# "))
        for h in ("## App", "## Atlas", "## Data", "## Sources", "## How to cite"):
            self.assertIn(h, text)
        self.assertIn("Kraków", (self.web / "llms-full.txt").read_text())
        self.assertEqual(seo.llms_problems("no heading\n"), ["first line is not an H1", "no blockquote summary after the H1",
                                                            "fewer than three H2 sections", "more than one H1"])

    def test_catalog_and_index_html(self):
        cat = json.loads((self.web / "data" / "index.json").read_text())
        paths = {f["path"] for f in cat["files"]}
        self.assertIn("data/cities.json", paths)
        self.assertTrue(all((self.web / p).exists() for p in paths))
        self.assertIn("MIT", cat["license"]["code"])
        html = (self.web / "index.html").read_text()
        (ld,) = seo.jsonld_of(html)
        types = {n["@type"] for n in ld["@graph"]}
        self.assertEqual(types, {"WebSite", "WebApplication", "Dataset"})
        self.assertIn(seo.CF_BEACON, html)

    def test_check_passes_on_built_site_and_notes_missing(self):
        lines = seo.check(self.web / "data")
        self.assertFalse([m for lv, m in lines if lv == "FAIL"], lines)
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "data").mkdir()
            self.assertEqual([lv for lv, _ in seo.check(Path(t) / "data")], ["NOTE"])

    def test_check_flags_a_broken_page(self):
        p = self.web / "atlas" / "krakow" / "index.html"
        p.write_text(p.read_text().replace('rel="canonical"', 'rel="x"'))
        self.assertTrue(any(lv == "FAIL" and "canonical" in m for lv, m in seo.check(self.web / "data")))


if __name__ == "__main__":
    unittest.main()

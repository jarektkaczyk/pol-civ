"""pipeline/build/seo.py: slugs, page model, JSON-LD, sitemap, llms.txt and check() on a tiny synthetic site."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.build import seo
from pipeline.core import i18n

# A fixed Polish catalogue for the tests (the real web/i18n/pl.json changes while translators work).
CATALOGUE = {"Statistics Poland (GUS)": "Główny Urząd Statystyczny (GUS)", "Population": "Ludność",
             "Polska: Poland as a strategy map built from real data": "Polska: mapa strategiczna z prawdziwych danych",
             "Text version": "Wersja tekstowa", "Language": "Język", "Search towns": "Szukaj miast",
             "A short description.": "Krótki opis."}

SOURCES = [
    {"id": "pl_stats_population", "publisher": "Statistics Poland (GUS)", "title": "Population", "vintage": "GUS population 31 December 2025",
     "homepage": "https://stat.gov.pl/"},
    {"id": "pl_stats_labour", "publisher": "Statistics Poland (GUS)", "title": "Labour", "vintage": "2026", "homepage": "https://stat.gov.pl/"},
    {"id": "pl_geo_places", "publisher": "GUS; OpenStreetMap contributors", "title": "Towns", "vintage": "2026", "homepage": "https://stat.gov.pl/"},
    {"id": "pl_gdp", "publisher": "Eurostat", "title": "GDP", "vintage": "2024", "homepage": "https://ec.europa.eu/eurostat"},
    {"id": "pl_soc_air", "publisher": "GIOŚ", "title": "Air", "vintage": "2025", "homepage": "https://powietrze.gios.gov.pl/"},
    {"id": "pl_hist_borders", "publisher": "ETH Zurich", "title": "CShapes 2.0", "vintage": "2022",
     "homepage": "https://icr.ethz.ch/data/cshapes/", "license": "CC BY-NC-SA 4.0"},
    {"id": "pl_flows_commuting", "publisher": "Statistics Poland (GUS)", "title": "Commuting", "vintage": "2021",
     "homepage": "https://stat.gov.pl/", "license": "GUS CC BY 4.0"},
    {"id": "pl_hist_population", "publisher": "Statistics Poland (GUS)", "title": "Population history", "vintage": "2015-2026",
     "homepage": "https://stat.gov.pl/", "license": "GUS CC BY 4.0"},
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
        patcher = mock.patch.dict(i18n._CACHE, {str(i18n.CATALOGUE): CATALOGUE})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.web = Path(self.tmp.name) / "web"
        (self.web / "data").mkdir(parents=True)
        for name, doc in dataset().items():
            (self.web / "data" / name).write_text(json.dumps(doc, ensure_ascii=False))
        (self.web / "og-image.png").write_bytes(b"x")
        (self.web / "index.html").write_text(
            '<html lang="en"><head><meta http-equiv="Content-Security-Policy" content="' + seo.APP_CSP.replace("'", "&#x27;") + '">'
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
        text = (self.web / "sitemap.xml").read_text()
        locs = re.findall(r"<loc>(.*?)</loc>", text)
        self.assertEqual(locs[:2], [seo.SITE_URL, seo.SITE_URL + "pl/"])
        pages = {p.parent.relative_to(self.web).as_posix() + "/"
                 for root in ("atlas", "pl/atlas") for p in (self.web / root).rglob("index.html")}
        self.assertEqual({u[len(seo.SITE_URL):] for u in locs[2:]}, pages)
        self.assertEqual(len(pages), 10)
        self.assertIn("<lastmod>2026-11-26</lastmod>", text)

    def test_sitemap_lists_hreflang_alternates(self):
        text = (self.web / "sitemap.xml").read_text()
        self.assertIn('xmlns:xhtml="http://www.w3.org/1999/xhtml"', text)
        block = re.search(r"<url><loc>%spl/atlas/krakow/</loc>(.*?)</url>" % re.escape(seo.SITE_URL), text).group(1)
        alts = dict(re.findall(r'<xhtml:link rel="alternate" hreflang="([^"]+)" href="([^"]+)"/>', block))
        self.assertEqual(alts, {"en": seo.SITE_URL + "atlas/krakow/", "pl": seo.SITE_URL + "pl/atlas/krakow/",
                                "x-default": seo.SITE_URL + "atlas/krakow/"})
        self.assertEqual(len(re.findall("<url>", text)), len(re.findall('hreflang="x-default"', text)))

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
        self.assertNotIn(seo.CF_BEACON_HOST, html)

    def test_catalog_includes_history_commuting_and_timeline_licenses(self):
        docs = {
            "history.json": {"sources": ["pl_hist_borders"], "layers": [{}, {}],
                             "licence": "CShapes 2.0, CC BY-NC-SA 4.0"},
            "commuting.json": {"sources": ["pl_flows_commuting"], "cities": [{}]},
            "timeline.json": {"sources": ["pl_hist_population"], "cells": [1, 2, 3]},
        }
        for name, doc in docs.items():
            (self.web / "data" / name).write_text(json.dumps(doc))
        cat = seo.data_catalog(seo.Data(self.web / "data"), self.web, "2026-11-26")
        files = {f["path"]: f for f in cat["files"]}
        self.assertEqual(files["data/history.json"]["rows"], 2)
        self.assertEqual(files["data/history.json"]["licenses"],
                         [{"source": "pl_hist_borders", "terms": "CC BY-NC-SA 4.0"}])
        self.assertEqual(files["data/commuting.json"]["sources"], ["pl_flows_commuting"])
        self.assertEqual(files["data/timeline.json"]["rows"], 3)

    def test_check_passes_on_built_site_and_notes_missing(self):
        lines = seo.check(self.web / "data")
        self.assertFalse([m for lv, m in lines if lv == "FAIL"], lines)
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "data").mkdir()
            self.assertEqual([lv for lv, _ in seo.check(Path(t) / "data")], ["NOTE"])

    def test_check_flags_a_missing_polish_twin(self):
        (self.web / "pl" / "atlas" / "krakow" / "index.html").unlink()
        fails = [m for lv, m in seo.check(self.web / "data") if lv == "FAIL"]
        self.assertTrue(any("atlas/krakow/" in m and "no page" in m for m in fails), fails)

    def test_check_warns_when_polish_index_is_stale(self):
        self.assertFalse([m for lv, m in seo.check(self.web / "data") if "older than" in m])
        p = self.web / "index.html"
        p.write_text(p.read_text().replace("<body>", "<body><p>Text version</p>"))
        self.assertTrue([m for lv, m in seo.check(self.web / "data") if lv == "WARN" and "older than" in m])

    def test_check_flags_a_broken_page(self):
        p = self.web / "atlas" / "krakow" / "index.html"
        p.write_text(p.read_text().replace('rel="canonical"', 'rel="x"'))
        self.assertTrue(any(lv == "FAIL" and "canonical" in m for lv, m in seo.check(self.web / "data")))


    # --- Polish ---------------------------------------------------------------------------------------------------

    def test_polish_pages_for_every_english_page(self):
        self.assertEqual(self.res["pages_pl"], self.res["pages"])
        for p in ("pl/atlas", "pl/atlas/malopolskie", "pl/atlas/lodzkie", "pl/atlas/krakow", "pl/atlas/lodz"):
            self.assertTrue((self.web / p / "index.html").exists(), p)
            self.assertTrue((self.web / p / "index.md").exists(), p)

    def test_polish_page_head_hreflang_and_canonical(self):
        text = (self.web / "pl" / "atlas" / "krakow" / "index.html").read_text()
        self.assertTrue(text.startswith('<!doctype html>\n<html lang="pl">'))
        head = seo._head(text)
        self.assertEqual(head["link:canonical"], seo.SITE_URL + "pl/atlas/krakow/")
        self.assertEqual(head["og:locale"], "pl_PL")
        self.assertEqual(seo.hreflangs(text), {"en": seo.SITE_URL + "atlas/krakow/", "pl": seo.SITE_URL + "pl/atlas/krakow/",
                                               "x-default": seo.SITE_URL + "atlas/krakow/"})
        en = (self.web / "atlas" / "krakow" / "index.html").read_text()
        self.assertEqual(seo.hreflangs(en), seo.hreflangs(text))
        self.assertEqual(seo._head(en)["link:canonical"], seo.SITE_URL + "atlas/krakow/")
        # links stay in the language: the app, the crumbs and the other towns
        self.assertIn('<a class="brand" href="../../../pl/">', text)
        self.assertIn('href="../../../pl/#city=1261011&amp;view=city"', text)
        self.assertIn('<a href="../../../pl/atlas/">Atlas</a>', text)
        self.assertIn('<a href="../../../atlas/krakow/" hreflang="en" lang="en">EN</a>', text)
        self.assertIn('hreflang="pl" lang="pl" aria-current="page">PL</a>', text)

    def test_polish_jsonld(self):
        (ld,) = seo.jsonld_of((self.web / "pl" / "atlas" / "krakow" / "index.html").read_text())
        nodes = {n["@type"]: n for n in ld["@graph"]}
        self.assertEqual(nodes["WebPage"]["inLanguage"], "pl")
        self.assertEqual(nodes["WebPage"]["url"], seo.SITE_URL + "pl/atlas/krakow/")
        self.assertEqual(nodes["City"]["containedInPlace"]["name"], "Województwo małopolskie")
        self.assertEqual(nodes["Observation"]["name"], "Ludność: Kraków")
        self.assertEqual([i["item"] for i in nodes["BreadcrumbList"]["itemListElement"]][:2],
                         [seo.SITE_URL + "pl/", seo.SITE_URL + "pl/atlas/"])
        (ld,) = seo.jsonld_of((self.web / "pl" / "atlas" / "malopolskie" / "index.html").read_text())
        nodes = {n["@type"]: n for n in ld["@graph"]}
        self.assertEqual(nodes["AdministrativeArea"]["name"], "Województwo małopolskie")
        self.assertEqual(nodes["AdministrativeArea"]["containedInPlace"]["name"], "Polska")

    def test_polish_sentences(self):
        md = (self.web / "pl" / "atlas" / "krakow" / "index.md").read_text()
        self.assertIn("W latach 2015-2025 liczba mieszkańców miasta wzrosła o 7,3%. Pod względem tempa wzrostu "
                      "Kraków zajmuje pierwsze miejsce wśród 2 miast liczących co najmniej 20 tys. mieszkańców.", md)
        self.assertIn("Kraków to miasto na prawach powiatu w województwie małopolskim. Jest stolicą województwa.", md)
        self.assertIn("| Ludność | 816\u00a0614 | 31 grudnia 2025 | GUS; OpenStreetMap contributors |", md)
        self.assertIn("| Zmiana od 2015 r. | +7,3% (z 761\u00a0057) | 2015-2025 | Główny Urząd Statystyczny (GUS) |", md)
        self.assertIn("| Przeciętne miesięczne wynagrodzenie brutto | 9002 zł | maj 2026 |", md)
        self.assertIn("W 2025 r. średnie roczne stężenie pyłu PM2,5 na stacji GIOŚ Kraków, Aleja (4 km) wyniosło 18,4 µg/m³.", md)
        lodz = (self.web / "pl" / "atlas" / "lodzkie" / "index.md").read_text()
        self.assertIn("31 grudnia 2025 r. województwo łódzkie liczyło 2\u00a0300\u00a0000 mieszkańców. "
                      "To najniższy wynik wśród województw.", lodz)
        self.assertIn("W województwie są 2 miasta. 1 z nich liczy co najmniej 20 tys. mieszkańców.", lodz)
        self.assertNotRegex(md + lodz, "[–—→“”]")
        self.assertNotIn(" the ", md)

    def test_polish_cases_and_counts(self):
        self.assertEqual(seo.pl_voiv("Małopolskie", "loc"), "województwie małopolskim")
        self.assertEqual(seo.pl_voiv("Dolnośląskie", "loc"), "województwie dolnośląskim")
        self.assertEqual(seo.pl_voiv("Świętokrzyskie", "loc"), "województwie świętokrzyskim")
        self.assertEqual(seo.pl_voiv("Warmińsko-Mazurskie", "loc"), "województwie warmińsko-mazurskim")
        self.assertEqual(seo.pl_voiv("Łódzkie", "gen"), "województwa łódzkiego")
        self.assertEqual(seo.pl_voiv("Kujawsko-Pomorskie"), "województwo kujawsko-pomorskie")
        self.assertEqual(seo.pl_powiat("powiat lubiński", "loc"), "powiecie lubińskim")
        self.assertEqual(seo.pl_powiat("powiat bielski", "gen"), "powiatu bielskiego")
        self.assertEqual(seo.pl_powiat("powiat łódzki wschodni", "loc"), "powiecie łódzkim wschodnim")
        self.assertEqual(seo.pl_powiat("powiat średzki"), "powiat średzki")
        self.assertEqual(seo.pl_powiat("powiat kędzierzyńsko-kozielski", "loc"), "powiecie kędzierzyńsko-kozielskim")
        self.assertEqual(seo.pl_powiat("powiat warszawski zachodni", "gen"), "powiatu warszawskiego zachodniego")
        self.assertEqual(seo.pl_voiv("Kujawsko-Pomorskie", "gen"), "województwa kujawsko-pomorskiego")
        self.assertEqual(seo.pl_result(3, False, "wśród województw"), "To trzecie miejsce od końca wśród województw.")
        forms = ("miasto", "miasta", "miast")
        self.assertEqual([seo.pl_count(n, *forms) for n in (1, 2, 4, 5, 12, 22, 25, 1026)],
                         ["1 miasto", "2 miasta", "4 miasta", "5 miast", "12 miast", "22 miasta", "25 miast", "1026 miast"])
        self.assertEqual(seo.pl_count(28425, "mieszkańca", "mieszkańców", "mieszkańców"), "28\u00a0425 mieszkańców")
        for name in ("Katowice", "Kielce", "Suwałki", "Tychy", "Tarnowskie Góry", "Piekary Śląskie", "Łaziska Górne",
                     "Czechowice-Dziedzice"):
            self.assertTrue(seo.pl_is_plural(name), name)
        for name in ("Kraków", "Warszawa", "Nowy Sącz", "Bielsk Podlaski", "Zakopane", "Świecie", "Łódź", "Ostrołęka"):
            self.assertFalse(seo.pl_is_plural(name), name)

    def test_polish_town_headline_forms(self):
        d = seo.Data(self.web / "data")
        f = seo.Fmt("pl")
        c = dict(d.city_by_id["1261011"], name="Katowice", ranks={"population": 11}, growth=None, wage=None,
                 unemployment=None, pit_per_person=None, gmina="none")
        self.assertEqual(seo.town_headline(d, c, f)[0], "Katowice zajmują jedenaste miejsce w Polsce pod względem liczby "
                         "mieszkańców. Liczą 816\u00a0614 mieszkańców (stan na 31 grudnia 2025 r.).")
        c = dict(c, name="Augustów", ranks={"population": 154})
        self.assertEqual(seo.town_headline(d, c, f)[0], "Augustów liczy 816\u00a0614 mieszkańców (stan na 31 grudnia 2025 r.).")
        c = dict(c, name="Żory")
        self.assertEqual(seo.town_headline(d, c, f)[0], "Żory liczą 816\u00a0614 mieszkańców (stan na 31 grudnia 2025 r.).")
        self.assertEqual(f.when_pl("2026-05"), "w maju 2026 r.")
        self.assertEqual(f.when_pl("2026-10"), "w październiku 2026 r.")
        self.assertEqual(f.when_pl("2026-06-30"), "30 czerwca 2026 r.")
        self.assertEqual(f.big(3.915e12, "zł"), "3,92 bln zł")
        self.assertEqual(seo.Fmt("en").big(3.915e12, "zł"), "3.92 trillion zł")

    def test_polish_state_growth_handles_zero(self):
        d = seo.Data(self.web / "data")
        metrics, _, _ = seo._state_metrics(d, seo.Fmt("pl"))
        growth_sentence = next(sentence for key, _, _, _, sentence, _ in metrics if key == "growth")
        state = {"name": "Pomorskie"}
        self.assertEqual(
            growth_sentence(state, 0, 8, True),
            "W latach 2015-2025 liczba ludności województwa pomorskiego nie zmieniła się. "
            "To ósme miejsce w rankingu zmiany liczby ludności województw.",
        )

    def test_dates_read_from_iso_data(self):
        self.assertEqual(seo._when("GUS population 2026-06-30; population 2025-12-31", None), "2026-06-30")
        self.assertEqual(seo._when("Average wage (GUS wage distribution, 2026-05).", 2026), "2026-05")
        self.assertEqual(seo._when("Change 2015-2025 (GUS, 2025).", 2025), "2025")
        self.assertEqual(seo._when("GUS population 30 June 2026", None), "2026-06-30")
        md = (self.web / "atlas" / "krakow" / "index.md").read_text()
        self.assertIn("| Median age | 41.3 years | 31 December 2025 |", md)
        self.assertIn("| Average gross wage | 9,002 zł a month | May 2026 |", md)

    def test_polish_index_html(self):
        en = ('<!doctype html>\n<html lang="en">\n<head>\n  <meta http-equiv="Content-Security-Policy" content="'
              + seo.APP_CSP + '">\n  <title>Polska: Poland as a strategy map built from real data</title>\n'
              '  <meta name="description" content="A short description.">\n'
              '  <link rel="canonical" href="https://softonsofa.com/pol-civ/">\n'
              '  <link rel="alternate" type="text/plain" title="llms.txt" href="llms.txt">\n'
              '  <link rel="sitemap" type="application/xml" href="sitemap.xml">\n'
              '  <meta property="og:url" content="https://softonsofa.com/pol-civ/">\n'
              '  <meta property="og:locale" content="en_GB">\n'
              '  <!-- seo:jsonld --><!-- /seo:jsonld -->\n  <style>.a { color: red; }</style>\n'
              '  <script type="module" src="js/app/analytics.js"></script>\n  <link rel="stylesheet" href="css/style.css">\n'
              '</head>\n<body>\n  <a class="text-version" href="atlas/">Text version</a>\n'
              '  <input type="search" placeholder="Search towns" aria-label="Search towns">\n'
              '  <a href="data/index.json">Data</a>\n'
              '  <nav id="lang-switch" aria-label="Language"><a href="./" hreflang="en" lang="en" data-lang="en" '
              'aria-current="page">EN</a><a href="pl/" hreflang="pl" lang="pl" data-lang="pl">PL</a></nav>\n'
              '  <script type="module" src="js/main.js"></script>\n</body>\n</html>\n')
        ld = {"@context": "https://schema.org", "@graph": [{"@type": "WebSite", "inLanguage": "pl"}]}
        pl = seo.polish_index(en, ld)
        head = seo._head(pl)
        self.assertIn('<html lang="pl">', pl)
        self.assertIn("<title>Polska: mapa strategiczna z prawdziwych danych</title>", pl)
        self.assertEqual(head["description"], "Krótki opis.")
        self.assertEqual(head["Content-Security-Policy"], seo.APP_CSP)
        self.assertEqual(head["link:canonical"], seo.SITE_URL + "pl/")
        self.assertEqual(head["og:url"], seo.SITE_URL + "pl/")
        self.assertEqual(head["og:locale"], "pl_PL")
        self.assertIn('<meta property="og:locale:alternate" content="en_GB">', pl)
        self.assertEqual(seo.hreflangs(pl), {"en": seo.SITE_URL, "pl": seo.SITE_URL + "pl/", "x-default": seo.SITE_URL})
        for want in ('src="../js/app/analytics.js"', 'href="../css/style.css"', 'href="../sitemap.xml"', 'href="llms.txt"',
                     '<a class="text-version" href="atlas/">Wersja tekstowa</a>', 'placeholder="Szukaj miast"',
                     'aria-label="Szukaj miast"', 'href="../data/index.json"', 'src="../js/main.js"', 'aria-label="Język"',
                     '<a href="../" hreflang="en" lang="en" data-lang="en">EN</a>',
                     '<a href="./" hreflang="pl" lang="pl" data-lang="pl" aria-current="page">PL</a>',
                     "<style>.a { color: red; }</style>"):
            self.assertIn(want, pl)
        self.assertEqual(seo.jsonld_of(pl), [ld])

    def test_built_polish_index_and_llms(self):
        text = (self.web / "pl" / "index.html").read_text()
        self.assertIn('<html lang="pl">', text)
        (ld,) = seo.jsonld_of(text)
        self.assertEqual({n["inLanguage"] for n in ld["@graph"]}, {"pl"})
        self.assertEqual({n["@type"] for n in ld["@graph"]}, {"WebSite", "WebApplication", "Dataset"})
        en = (self.web / "index.html").read_text()
        self.assertEqual(seo.hreflangs(en)["pl"], seo.SITE_URL + "pl/")
        llms = (self.web / "pl" / "llms.txt").read_text()
        self.assertEqual(seo.llms_problems(llms, self.web), [])
        for h in ("## Aplikacja", "## Atlas", "## Dane", "## Źródła", "## Jak cytować"):
            self.assertIn(h, llms)
        self.assertIn(f"]({seo.SITE_URL}pl/atlas/krakow/index.md)", llms)
        self.assertIn("Polska w liczbach", (self.web / "pl" / "llms-full.txt").read_text())

    def test_share_images_and_og_plan(self):
        plan = self.res["plan"]
        pl = [p for p in plan if p.get("lang") == "pl"]
        self.assertEqual(len(pl), len(plan) - len(pl))
        krakow = next(p for p in pl if p["slug"] == "krakow")
        self.assertEqual(krakow["out"], "og/pl/krakow.jpg")
        self.assertEqual(krakow["number"], "816\u00a0614 mieszkańców")
        self.assertNotIn("lang", next(p for p in plan if p["slug"] == "krakow" and p is not krakow))
        # a Polish page uses og/pl/<slug>.jpg when it exists, else the English image
        (self.web / "og" / "pl").mkdir(parents=True)
        (self.web / "og" / "krakow.jpg").write_bytes(b"x")
        self.assertEqual(seo._og_for(self.web, "krakow", "pl"), "og/krakow.jpg")
        (self.web / "og" / "pl" / "krakow.jpg").write_bytes(b"x")
        self.assertEqual(seo._og_for(self.web, "krakow", "pl"), "og/pl/krakow.jpg")
        self.assertEqual(seo._og_for(self.web, "krakow", "en"), "og/krakow.jpg")


if __name__ == "__main__":
    unittest.main()

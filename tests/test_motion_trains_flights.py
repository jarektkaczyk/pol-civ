"""pl_rail_gtfs / trains and pl_air_routes / flights: weekday choice, night trains, encoding, map edges."""

import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pipeline.build import flights, trains
from pipeline.core.geo import MapProjection
from pipeline.sources import pl_air_routes as air
from pipeline.sources import pl_rail_gtfs as gtfs


def _csv(rows: list[list]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def make_feed(path: Path) -> None:
    """Two days (Tue 2026-12-15, Wed 2026-12-16): a daily regional train, a nightly IC that passes midnight,
    a Tuesday-only train and a replacement bus."""
    files = {
        "feed_info.txt": [["feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_version",
                           "feed_start_date", "feed_end_date"],
                          ["M K", "https://example.org", "pl", "2026-12-01T02:00:00+01:00", "20261215", "20261216"]],
        "attributions.txt": [["attribution_id", "organization_name"], ["PLK", "Data: PKP PLK"]],
        "agency.txt": [["agency_id", "agency_name", "agency_url"], ["IC", "PKP Intercity", "https://ic"],
                       ["PR", "PolRegio", "https://pr"]],
        "routes.txt": [["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
                       ["IC_IC", "IC", "IC", "InterCity", "2"], ["PR_R", "PR", "R", "Regio", "2"],
                       ["PR_BUS", "PR", "ZKA", "Bus", "3"]],
        "calendar_dates.txt": [["date", "service_id", "exception_type"],
                               ["20261215", "DAILY", "1"], ["20261216", "DAILY", "1"],
                               ["20261215", "TUE", "1"], ["20261216", "BUS", "1"]],
        "trips.txt": [["trip_id", "route_id", "service_id", "shape_id", "trip_short_name", "trip_headsign",
                       "plk_category_code", "plk_train_number", "plk_train_name"],
                      ["R1", "PR_R", "DAILY", "S1", "50101", "B", "R", "50101", ""],
                      ["N1", "IC_IC", "DAILY", "S1", "406 Chopin (P12)", "B", "IC", "406", "CHOPIN"],
                      ["T1", "PR_R", "TUE", "S1", "50103", "B", "R", "50103", ""],
                      ["B1", "PR_BUS", "BUS", "", "ZKA 1", "B", "BUS", "1", ""]],
        "stop_times.txt": [["trip_id", "stop_sequence", "stop_id", "arrival_time", "departure_time",
                            "shape_dist_traveled", "pickup_type", "drop_off_type"],
                           ["R1", "0", "A_1", "08:00:00", "08:00:00", "0.0", "0", "1"],
                           ["R1", "1", "B_1", "08:30:00", "08:30:00", "20.0", "1", "0"],
                           ["N1", "0", "A_1", "23:00:00", "23:00:00", "0.0", "0", "1"],
                           ["N1", "1", "B_1", "25:30:00", "25:30:00", "20.0", "1", "0"],
                           ["T1", "0", "A_1", "10:00:00", "10:00:00", "0.0", "0", "1"],
                           ["T1", "1", "B_1", "10:30:00", "10:30:00", "20.0", "1", "0"],
                           ["B1", "0", "A_1", "11:00:00", "11:00:00", "", "0", "1"],
                           ["B1", "1", "B_1", "11:40:00", "11:40:00", "", "1", "0"]],
        "stops.txt": [["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station", "country"],
                      ["A", "Alfa", "52.0", "19.0", "1", "", "PL"], ["A_1", "Alfa", "52.0", "19.0", "0", "A", "PL"],
                      ["B", "Beta", "52.0", "19.3", "1", "", "PL"], ["B_1", "Beta", "52.0", "19.3", "0", "B", "PL"]],
        "shapes.txt": [["shape_id", "shape_pt_sequence", "shape_pt_lat", "shape_pt_lon", "shape_dist_traveled"],
                       ["S1", "0", "52.0", "19.0", "0.0"], ["S1", "1", "52.0001", "19.15", "10.0"],
                       ["S1", "2", "52.0", "19.3", "20.0"]],
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, rows in files.items():
            z.writestr(name, _csv(rows))


class RailGtfsTest(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(gtfs.gtfs_seconds("25:07:30"), 90450)
        self.assertEqual(gtfs.split_name("13120/1 Karłowicz (P12)", "13120/1"), "Karłowicz")
        self.assertIsNone(gtfs.split_name("1300/1 Ex03", "1300/1"))
        self.assertIsNone(gtfs.split_name("50829", "50829"))
        self.assertEqual(gtfs.split_name("Ursa 430", ""), "Ursa 430")

    def test_pick_weekday_skips_holidays(self):
        days = {"20261202": 10, "20261209": 12, "20261216": 15, "20261223": 99, "20261210": 50,
                "20261111": 999}
        self.assertEqual(gtfs.pick_weekday(days), "20261216")
        with self.assertRaises(RuntimeError):
            gtfs.pick_weekday({"20261223": 1, "20261230": 1})

    def test_process_keeps_night_trains_and_drops_buses(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_feed(Path(tmp) / gtfs.PlRailGtfs.ZIP)
            src = gtfs.PlRailGtfs()
            with mock.patch.object(gtfs.PlRailGtfs, "raw_dir", new=Path(tmp)):
                out = src.process()
        self.assertEqual(out["day"], "2026-12-16")
        by_id = {t["id"]: t for t in out["trips"]}
        self.assertEqual(set(by_id), {"R1", "N1", "N1@prev"})  # T1 runs Tuesday and ends before midnight
        self.assertEqual(by_id["N1@prev"]["dep"][0], 23 * 3600 - 86400)
        self.assertEqual(by_id["N1@prev"]["arr"][-1], 1 * 3600 + 1800)
        self.assertEqual(by_id["N1"]["arr"][-1], 25 * 3600 + 1800)
        self.assertEqual(by_id["N1"]["name"], "Chopin")
        self.assertIsNone(by_id["R1"]["name"])
        self.assertEqual(by_id["R1"]["stops"], ["A", "B"])
        self.assertEqual({p["name"] for p in out["points"]}, {"Alfa", "Beta"})
        self.assertIn("S1", out["shapes"])


class TrainsBuildTest(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_feed(Path(tmp) / gtfs.PlRailGtfs.ZIP)
            with mock.patch.object(gtfs.PlRailGtfs, "raw_dir", new=Path(tmp)):
                self.data = gtfs.PlRailGtfs().process()
        self.proj = MapProjection(min_x=-362.16, max_y=350.3, margin=0.0)

    def test_times_roundtrip(self):
        arr, dep = [100, 200, 400], [100, 260, 400]
        t = trains.encode_times(arr, dep)
        self.assertEqual(t, [100, 100, 60, 140, 0])
        self.assertEqual(trains.decode_times(t), (arr, dep))

    def test_map_dist(self):
        self.assertEqual(trains.map_dist(5.0, [0.0, 10.0, 20.0], [0.0, 12.0, 22.0]), 6.0)
        self.assertEqual(trains.map_dist(25.0, [0.0, 10.0], [0.0, 12.0]), 12.0)
        self.assertEqual(trains.map_dist(None, [0.0, 10.0], [0.0, 12.0]), 0.0)

    def test_build_doc(self):
        doc = trains.build_doc(self.data, self.proj, "v")
        self.assertEqual(len(doc["trips"]), 3)
        self.assertEqual(len(doc["shapes"]), 1)  # one line, shared
        self.assertEqual(len(doc["patterns"]), 1)  # same stops and distances
        self.assertEqual(doc["operators"][0]["id"], "IC")  # long distance first
        pat = doc["patterns"][0]
        self.assertEqual(pat["d"][0], 0.0)
        shape = doc["shapes"][0]
        length = sum(((shape[i + 2] - shape[i]) ** 2 + (shape[i + 3] - shape[i + 1]) ** 2) ** 0.5
                     for i in range(0, len(shape) - 2, 2))
        self.assertAlmostEqual(pat["d"][-1], length, places=1)
        self.assertEqual(doc["range"][0], 23 * 3600 - 86400)
        self.assertEqual(doc["attribution"]["created"], "2026-12-01T01:00Z")  # feed version 02:00+01:00
        self.assertIsNone(doc["attribution"]["retrieved"])
        self.assertIn("PKP Polskie Linie Kolejowe S.A.", doc["attribution"]["credit"])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "trains.json").write_text(json.dumps(doc))
            levels = [lvl for lvl, _ in trains.check(tmp)]
        self.assertNotIn("FAIL", levels)


class AirRoutesTest(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(air.parse_pair("PL_EPWA_UK_EGLL"), ("EPWA", "GB", "EGLL"))
        self.assertIsNone(air.parse_pair("DE_EDDF_PL_EPWA"))
        self.assertEqual(air.last_months({"2024-11": 1, "2024-12": 2, "2025-01": 0}, 3),
                         ["2024-10", "2024-11", "2024-12"])
        self.assertEqual(air.clean_city("Paris (Roissy-en-France, Val-d'Oise)"), "Paris")
        self.assertEqual(air.clean_city("Luton, Luton"), "Luton")

    def test_short_label(self):
        self.assertEqual(air.short_label("Milan Malpensa Airport", "en"), "Milan Malpensa")
        self.assertEqual(air.short_label("Antalya International Airport", "en"), "Antalya")
        self.assertEqual(air.short_label("Port lotniczy Mediolan-Malpensa", "pl"), "Mediolan-Malpensa")
        self.assertIsNone(air.short_label(None, "pl"))

    def test_wikidata_airports(self):
        def row(qid, aen, city, pop, pl=None):
            b = {"icao": {"value": "LFSB"}, "airport": {"value": f"http://www.wikidata.org/entity/{qid}"},
                 "aen": {"value": aen}, "en": {"value": city}, "pop": {"value": pop}}
            if pl:
                b["pl"] = {"value": pl}
            return b
        doc = {"results": {"bindings": [
            row("Q9", "EuroAirport Basel Mulhouse Freiburg", "Mulhouse", "100000"),
            row("Q9", "EuroAirport Basel Mulhouse Freiburg", "Basel", "170000", "Bazylea"),
            row("Q12", "Another entity Airport", "Basel", "999999"),
        ]}}
        got = air.wikidata_airports(doc)["LFSB"]
        self.assertEqual(got["qid"], "Q9")
        self.assertEqual(got["city"], "Basel")
        self.assertEqual(got["city_pl"], "Bazylea")
        self.assertEqual(got["label"], "EuroAirport Basel Mulhouse Freiburg")


class FlightsBuildTest(unittest.TestCase):
    def test_bearing_and_edge(self):
        self.assertAlmostEqual(flights.bearing_deg(21.0, 52.0, 21.0, 60.0), 0.0, places=6)
        self.assertAlmostEqual(flights.bearing_deg(21.0, 52.0, 21.0, 40.0), 180.0, places=6)
        self.assertEqual(flights.edge_point(10, 10, -1, 0, 100, 100), (0, 10))
        self.assertEqual(flights.edge_point(50, 50, 1, 1, 100, 80), (80, 80))

    def test_build_doc(self):
        def pt(icao, lon, lat, polish):
            return {"name": icao, "lon": lon, "lat": lat,
                    "props": {"icao": icao, "polish": polish, "city": icao, "country": "PL" if polish else "GB"}}
        data = {
            "months": ["2024-01", "2024-02"],
            "points": [pt("EPWA", 20.97, 52.17, True), pt("EGLL", -0.46, 51.47, False),
                       pt("EPGD", 18.47, 54.38, True)],
            "routes": [
                {"from": "EPWA", "to": "EGLL", "domestic": False, "passengers": [100.0, None]},
                {"from": "EPWA", "to": "EPGD", "domestic": True, "passengers": [10.0, 20.0]},
            ],
        }
        proj = MapProjection(min_x=-362.16, max_y=350.3, margin=0.0)
        doc = flights.build_doc(data, proj, 699.0, 695.3, "v", "2026-11-27T07:00:17+00:00")
        att = doc["attribution"]
        self.assertEqual(att["credit"], ["Eurostat (avia_par_pl)"])
        self.assertEqual(att["retrieved"], "2026-11-27T07:00Z")
        self.assertEqual(att["disclaimer"], "Eurostat is not responsible for the changes.")
        ap = {a["icao"]: a for a in doc["airports"]}
        self.assertFalse(ap["EGLL"]["on_map"])
        self.assertIsNone(ap["EGLL"]["x"])
        london = doc["routes"][0]
        self.assertEqual(london["value"], [100, None])
        self.assertEqual(london["end"][0], 0.0)  # leaves through the west edge
        self.assertTrue(0 < london["end"][1] < 695.3)
        gdansk = doc["routes"][1]
        self.assertEqual(gdansk["end"], [ap["EPGD"]["x"], ap["EPGD"]["y"]])
        self.assertEqual(ap["EPWA"]["top"], [0, 1])
        self.assertEqual(ap["EPWA"]["value"], [110, 20])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "flights.json").write_text(json.dumps(doc))
            levels = [lvl for lvl, _ in flights.check(tmp)]
        self.assertNotIn("FAIL", levels)


if __name__ == "__main__":
    unittest.main()

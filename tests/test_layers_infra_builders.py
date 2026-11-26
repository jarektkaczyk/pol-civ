import unittest

from pipeline.build import infrastructure, resources, trade
from pipeline.core.hexgrid import HexGrid


class InfrastructureBuilderTests(unittest.TestCase):
    def test_planned_airport_keeps_status_year_and_refs(self):
        class Locator:
            def place(self, lon, lat):
                return {"x": lon, "y": lat, "cell": 1, "state": "MZ"}

        airports = infrastructure.build_airports(Locator(), [{
            "id": "airport:CPK", "name": "Port Polska (CPK)", "lon": 20.4, "lat": 52.1,
            "props": {"status": "planned", "opening_planned": 2032, "ref": "https://www.gov.pl/web/priorytety/p32",
                      "wikidata": "Q48840381", "passengers": None},
        }])

        self.assertEqual("planned", airports[0]["status"])
        self.assertEqual(2032, airports[0]["opening_planned"])
        self.assertEqual("Q48840381", airports[0]["wikidata"])

    def test_motorway_wins_when_classes_share_a_link(self):
        grid = HexGrid(radius=5, cols=5, rows=4)
        a, b = grid.index(1, 1), grid.index(2, 1)
        p0 = grid.center(*grid.col_row(a))
        p1 = grid.center(*grid.col_row(b))
        lines = [
            {"kind": "expressway", "ref": "S7", "coords": [p0, p1]},
            {"kind": "motorway", "ref": "A2", "coords": [p0, p1]},
        ]
        built = infrastructure.build_roads(grid, lambda x, y: (x, y), [0] * grid.size, lines)
        self.assertEqual([[a, b, 0, "A2"]], built)

    def test_unnumbered_motorway_keeps_motorway_class(self):
        grid = HexGrid(radius=5, cols=5, rows=4)
        a, b = grid.index(1, 1), grid.index(2, 1)
        p0 = grid.center(*grid.col_row(a))
        p1 = grid.center(*grid.col_row(b))
        built = infrastructure.build_roads(
            grid, lambda x, y: (x, y), [0] * grid.size,
            [{"kind": "motorway_other", "ref": None, "coords": [p0, p1]}],
        )
        self.assertEqual([[a, b, 0, None]], built)

    def test_hex_walk_is_a_neighbour_chain(self):
        grid = HexGrid(radius=5, cols=8, rows=8)
        path = infrastructure.hex_walk(grid, grid.index(1, 1), grid.index(6, 5))
        self.assertGreater(len(path), 2)
        self.assertTrue(all(b in grid.neighbours(a) for a, b in zip(path, path[1:])))


class ResourcesBuilderTests(unittest.TestCase):
    def test_renewable_rows_keep_missing_values_null(self):
        data = {
            "as_of": "2026-09-30",
            "tables": {"res_capacity_powiat": {
                "fields": {
                    "wind_mw": {"label": "Wind", "unit": "MW", "year": 2026},
                    "solar_mw": {"label": "Solar", "unit": "MW", "year": 2026},
                },
                "rows": {"0201": {"wind_mw": None, "solar_mw": 12.5}},
            }},
        }
        built = resources.renewables(data)
        self.assertEqual([["0201", None, 12.5]], built["rows"])

    def test_summary_separates_statuses(self):
        items = [
            {"type": "nuclear", "status": "planned", "value": 3750, "state": "PM"},
            {"type": "nuclear", "status": "operating", "value": 1000, "state": "PM"},
        ]
        summary = resources._summary(items)
        self.assertEqual(4750, summary["national"]["nuclear"]["value"])
        self.assertEqual(3750, summary["national"]["nuclear"]["by_status"]["planned"]["value"])

    def test_site_count_is_additive_when_output_is_not_published(self):
        summary = resources._summary([
            {"type": "copper", "status": "operating", "value": 1, "state": "DS"},
        ])
        self.assertEqual(1, summary["national"]["copper"]["value"])
        self.assertEqual(1, summary["states"]["DS"]["copper"]["value"])

    def test_plant_items_preserve_published_capacity_year(self):
        class Locator:
            def place(self, lon, lat, **kwargs):
                return {"x": lon, "y": lat, "state": "PM"}

        points = [{
            "id": "plant:test",
            "name": "Test plant",
            "kind": "solar_plant",
            "lon": 19.0,
            "lat": 52.0,
            "props": {"mw": 120, "mw_year": 2024},
        }]

        items = resources.plant_items(Locator(), points)

        self.assertEqual(2024, items[0]["year"])

    def test_oil_and_gas_items_keep_published_capacities(self):
        class Locator:
            def place(self, lon, lat, **kwargs):
                return {"x": lon, "y": lat, "state": "PM"}

        points = [
            {"id": "gas:pipe", "name": "Pipe", "kind": "gas_pipeline_landfall", "lon": 15, "lat": 54,
             "props": {"capacity_bcm": 10, "status": "operating", "operator": "Gaz-System",
                       "status_note": "Placed at the receiving station"}},
            {"id": "gas:field", "name": "Field", "kind": "gas_field", "lon": 16, "lat": 53,
             "props": {"output": None, "status": "operating"}},
            {"id": "refinery:test", "name": "Refinery", "kind": "refinery", "lon": 18, "lat": 54,
             "props": {"capacity_mt": 10.5, "status": "operating"}},
        ]

        items = resources.oil_gas_items(Locator(), points)

        self.assertEqual([10, 1, 10.5], [item["value"] for item in items])
        self.assertIsNone(items[1]["output"])
        self.assertEqual("Operating - Gaz-System", items[0]["detail"])


class TradeBuilderTests(unittest.TestCase):
    def test_zone_anchor_uses_voivode_seat(self):
        grid = HexGrid(radius=5, cols=4, rows=3)
        gorzow_cell = grid.index(1, 1)
        zielona_cell = grid.index(2, 1)
        world = {
            "grid": {"radius": 5, "cols": 4, "rows": 3},
            "states": ["08"],
            "owner": [0] * grid.size,
            "counties": ["0801"],
        }
        teryt = {"voivodeships": [{"code": "08", "name": "Lubuskie"}]}
        states = [{"fips": "08", "capitals": [
            {"gmina": "0861011", "name": "Gorz\u00f3w Wielkopolski", "role": "voivode"},
            {"gmina": "0862011", "name": "Zielona G\u00f3ra", "role": "sejmik"},
        ]}]
        cities = [
            {"id": "0861011", "name": "Gorz\u00f3w Wielkopolski", "cell": gorzow_cell, "x": 11.2, "y": 12.3},
            {"id": "0862011", "name": "Zielona G\u00f3ra", "cell": zielona_cell, "x": 21.2, "y": 12.3},
        ]

        zones = trade.build_zones(world, teryt, states, cities)

        self.assertEqual("Gorz\u00f3w Wielkopolski", zones["08"]["anchor"]["city"])
        self.assertEqual(gorzow_cell, zones["08"]["anchor"]["cell"])

    def test_flow_directions_are_summed_once(self):
        zones = {"02": {}, "04": {}}
        flows = [
            {"from": "02", "to": "04", "level": "voivodeship", "mode": "rail", "value": 10},
            {"from": "04", "to": "02", "level": "voivodeship", "mode": "rail", "value": 7.5},
            {"from": "02", "to": "04", "level": "voivodeship", "mode": "road", "value": 99},
        ]
        self.assertEqual({("02", "04"): 17.5}, trade.aggregate_flows(flows, zones))


if __name__ == "__main__":
    unittest.main()

"""Focused tests for the Poland society layer builders."""

from __future__ import annotations

import unittest

from pipeline.build import disasters, military, wonders


class MilitaryBuilderTests(unittest.TestCase):
    def test_tiers_follow_garrison_entry_count(self):
        self.assertEqual(military._tier(1), "site")
        self.assertEqual(military._tier(2), "base")
        self.assertEqual(military._tier(4), "major")

    def test_national_keeps_both_named_budget_figures(self):
        data = military._national({
            "defence_budget_2026": 124_800_000_000,
            "defence_budget_2026_pct_gdp": 3.0,
            "defence_total_2026_with_fwsz": 200_000_000_000,
            "defence_total_2026_with_fwsz_pct_gdp": 4.81,
        })
        spending = data["spending"]
        self.assertEqual(spending["budget_act"]["name"], "The budget act")
        self.assertEqual(spending["budget_act"]["total_pln"], 124_800_000_000)
        self.assertEqual(spending["with_support_fund"]["name"],
                         "The total with the Armed Forces Support Fund")
        self.assertEqual(spending["with_support_fund"]["pct_gdp"], 4.81)


class WondersBuilderTests(unittest.TestCase):
    def test_serial_unesco_property_uses_selected_component(self):
        points = [
            {"id": "whc_32", "kind": "unesco_site", "name": "Mines"},
            {"id": "whc_32bis-001", "kind": "unesco_component", "name": "Wieliczka"},
        ]
        selected = wonders.select_unesco(points)
        self.assertEqual(selected[0][0]["id"], "whc_32")
        self.assertEqual(selected[0][1]["id"], "whc_32bis-001")

    def test_parks_use_visitor_rank(self):
        points = [{"name": f"P{i}", "props": {"visitors": value}}
                  for i, value in enumerate((10, 70, 30, 90, 20, 80, 40))]
        selected = wonders.select_parks(points)
        self.assertEqual([point["props"]["visitors"] for point in selected], [90, 80, 70, 40, 30, 20])

    def test_universities_require_a_plus_and_rank_by_students(self):
        points = [
            {"name": "A", "lon": 1, "lat": 1, "props": {"count_a_plus": 1, "students_total": 100}},
            {"name": "B", "lon": 1, "lat": 1, "props": {"count_a_plus": 0, "students_total": 300}},
            {"name": "C", "lon": 1, "lat": 1, "props": {"count_a_plus": 2, "students_total": 200}},
        ]
        self.assertEqual([point["name"] for point in wonders.select_universities(points)], ["C", "A"])


class DisastersBuilderTests(unittest.TestCase):
    def test_declaration_helper_marks_only_named_gminas(self):
        source = {"tables": {"flood_2024_gmina": {"rows": {
            "0201011": {"declared_2024": 1, "declared_2024_date": 20240920},
        }}}}
        result = disasters.county_declarations(source, ["0201011", "0201022"])
        self.assertEqual(result["0201011"], {"total": 1, "flood": 1, "last_date": "2024-09-20"})
        self.assertEqual(result["0201022"], {"total": 0, "flood": 0, "last_date": None})


if __name__ == "__main__":
    unittest.main()

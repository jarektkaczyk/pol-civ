"""The valley-floor relief rule (build/world.py)."""

import unittest

from pipeline.build.world import is_valley_floor


class ValleyFloorTest(unittest.TestCase):
    def test_flat_lowland_with_a_range_at_the_edge(self):
        # The Vistula valley floor under a scarp: the lower 60% within 15 m and under 300 m.
        self.assertTrue(is_valley_floor([100, 102, 104, 106, 108, 110, 112, 300, 450, 600]))

    def test_real_mountains(self):
        self.assertFalse(is_valley_floor([600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500]))

    def test_too_few_samples(self):
        self.assertFalse(is_valley_floor([10, 20, 1500]))


if __name__ == "__main__":
    unittest.main()

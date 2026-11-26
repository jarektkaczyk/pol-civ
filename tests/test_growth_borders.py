import unittest

from pipeline.build.growth import BORDER_CHANGED, comparable


class BorderChangeTest(unittest.TestCase):
    def test_single_changed_gmina_is_not_comparable(self):
        self.assertFalse(comparable(["1661011"]))  # Opole took land in 2017
        self.assertFalse(comparable(["1207132"]))  # Szczawa, split from Kamienica in 2025

    def test_whole_exchange_group_is_comparable(self):
        self.assertTrue(comparable(["1661011", "1609022", "1609032", "1609042", "1609103", "1261011"]))
        self.assertTrue(comparable(["1207052", "1207132"]))

    def test_unrelated_gminas_are_comparable(self):
        self.assertTrue(comparable(["1261011", "1465011"]))
        self.assertTrue(comparable([]))

    def test_list_is_nine_gminas(self):
        self.assertEqual(len(BORDER_CHANGED), 9)


if __name__ == "__main__":
    unittest.main()

import unittest

from board.shortage import rows, supply


class ShortageTest(unittest.TestCase):
    def test_supply_counts_what_is_on_hand_and_coming(self) -> None:
        self.assertEqual(supply({"quantity": 10, "reserved": 0, "incoming": 5}), 15)

    def test_a_bin_is_short_when_picks_exceed_supply(self) -> None:
        bins = [{"bin": "B01", "quantity": 10, "reserved": 0, "incoming": 0}]
        (row,) = rows(bins, {"B01": 14})
        self.assertTrue(row.short)
        self.assertEqual(row.shortfall, 4)


if __name__ == "__main__":
    unittest.main()

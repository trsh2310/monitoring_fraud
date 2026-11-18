import unittest

from scripts.check_dashboards import has_numeric_data


def frame(types, columns):
    return {"schema": {"fields": [{"type": kind} for kind in types]},
            "data": {"values": columns}}


class DashboardDataTests(unittest.TestCase):
    def test_empty_columns_are_not_data(self):
        self.assertFalse(has_numeric_data([]))
        self.assertFalse(has_numeric_data([frame(["time", "number"], [[], []])]))

    def test_timestamps_and_labels_do_not_mask_null_measurements(self):
        self.assertFalse(has_numeric_data([
            frame(["time", "number"], [[1700000000000], [None]]),
            frame(["string", "number"], [["CA"], [None]]),
        ]))

    def test_nonfinite_values_are_not_measurements(self):
        self.assertFalse(has_numeric_data([
            frame(["number"], [[float("nan"), float("inf"), -float("inf"), None]]),
        ]))

    def test_zero_is_valid_data(self):
        self.assertTrue(has_numeric_data([
            frame(["time", "number"], [[1700000000000], [0]]),
        ]))

    def test_table_and_multiple_frames(self):
        self.assertTrue(has_numeric_data([
            frame(["time", "number"], [[], []]),
            frame(["string", "number", "number"], [["v2"], [15], [0.2]]),
        ]))


if __name__ == "__main__":
    unittest.main()

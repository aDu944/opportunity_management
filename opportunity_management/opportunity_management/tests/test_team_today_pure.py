"""
Bench-free tests for `team_today_pure` (late cutoff + attendance roll-up).

    python3 opportunity_management/opportunity_management/tests/test_team_today_pure.py
"""

import datetime as dt
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "team_today_pure.py")
    spec = importlib.util.spec_from_file_location("team_today_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()
D = dt.date(2026, 10, 6)


def at(h, m, s=0):
    return dt.datetime.combine(D, dt.time(h, m, s))


class TestCutoff(unittest.TestCase):
    def test_default(self):
        self.assertEqual(P.late_cutoff(None, None), dt.time(9, 15))

    def test_settings(self):
        self.assertEqual(P.late_cutoff(8, 30), dt.time(8, 30))
        self.assertEqual(P.late_cutoff("9", "45"), dt.time(9, 45))
        self.assertEqual(P.late_cutoff(9, 75), dt.time(10, 15))

    def test_garbage(self):
        self.assertEqual(P.late_cutoff("x", "y"), dt.time(9, 15))
        self.assertEqual(P.late_cutoff(30, -5), dt.time(9, 15))

    def test_boundary_is_on_time(self):
        c = dt.time(9, 15)
        self.assertFalse(P.is_late(at(9, 15, 0), c))
        self.assertTrue(P.is_late(at(9, 15, 1), c))
        self.assertFalse(P.is_late(None, c))


class TestSummarize(unittest.TestCase):
    def test_empty(self):
        s = P.empty_summary()
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["late_names"], [])

    def test_rollup(self):
        rows = [
            {"employee_name": "Ali", "first_in": at(9, 40), "last_in": at(9, 40),
             "last_out": at(17, 0), "on_leave": 0},
            {"employee_name": "Sara", "first_in": at(9, 20), "last_in": at(13, 0),
             "last_out": at(12, 0), "on_leave": 0},
            {"employee_name": "Omar", "first_in": at(8, 55), "last_in": at(8, 55),
             "last_out": None, "on_leave": 1},
            {"employee_name": "Huda", "first_in": None, "on_leave": 1},
            {"employee_name": "zaid", "first_in": None, "on_leave": 0},
            {"employee_name": "Bashar", "first_in": None, "on_leave": 0},
        ]
        s = P.summarize(rows, dt.time(9, 15))
        self.assertEqual(s["total"], 6)
        self.assertEqual(s["checked_in"], 3)
        self.assertEqual(s["late"], 2)
        self.assertEqual(s["on_leave"], 1)  # Omar came in, so not on leave
        self.assertEqual(s["not_in"], 2)
        self.assertEqual(s["checked_out"], 1)  # Sara re-checked in after OUT
        self.assertEqual(s["late_names"], ["Sara", "Ali"])
        self.assertEqual(s["not_in_names"], ["Bashar", "zaid"])

    def test_name_limit(self):
        rows = [{"employee_name": f"E{i}", "first_in": None} for i in range(8)]
        s = P.summarize(rows, dt.time(9, 15))
        self.assertEqual(s["not_in"], 8)
        self.assertEqual(len(s["not_in_names"]), 5)


if __name__ == "__main__":
    unittest.main()

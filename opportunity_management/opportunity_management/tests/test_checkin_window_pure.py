"""
Bench-free tests for `checkin_window_pure`.

    python3 opportunity_management/opportunity_management/tests/test_checkin_window_pure.py
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "checkin_window_pure.py")
    spec = importlib.util.spec_from_file_location("checkin_window_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


W = _load()


def _settings(**values):
    return lambda key: values.get(key)


class TestWindow(unittest.TestCase):
    def test_reads_the_production_window(self):
        self.assertEqual(W.window(_settings(checkin_window_start_hour=5,
                                            checkin_window_end_hour=12)), (5, 12))

    def test_strings_are_accepted(self):
        self.assertEqual(W.window(_settings(checkin_window_start_hour="9",
                                            checkin_window_end_hour="10")), (9, 10))

    def test_unset_or_misconfigured_is_none(self):
        self.assertIsNone(W.window(_settings()))
        self.assertIsNone(W.window(_settings(checkin_window_start_hour=9,
                                             checkin_window_end_hour=9)))
        self.assertIsNone(W.window(_settings(checkin_window_start_hour=12,
                                             checkin_window_end_hour=5)))
        self.assertIsNone(W.window(_settings(checkin_window_start_hour="x",
                                             checkin_window_end_hour=12)))


class TestIsOpen(unittest.TestCase):
    def test_half_open_interval(self):
        self.assertTrue(W.is_open(5, (5, 12)))
        self.assertTrue(W.is_open(11, (5, 12)))
        self.assertFalse(W.is_open(12, (5, 12)))
        self.assertFalse(W.is_open(4, (5, 12)))

    def test_no_window_is_closed(self):
        self.assertFalse(W.is_open(9, None))


class TestRecordPunch(unittest.TestCase):
    def test_late_tap_inside_the_window_records_an_in(self):
        # Haider Ghaith, 16 Nov 2026 09:15 — old app showed "Submit late check-in".
        self.assertTrue(W.record_punch(9, (5, 12), has_in_today=False))

    def test_never_a_second_in(self):
        self.assertFalse(W.record_punch(9, (5, 12), has_in_today=True))

    def test_closed_window_keeps_the_leave_only_meaning(self):
        self.assertFalse(W.record_punch(12, (5, 12), has_in_today=False))
        self.assertFalse(W.record_punch(10, (9, 10), has_in_today=False))

    def test_unset_window_never_punches(self):
        self.assertFalse(W.record_punch(9, None, has_in_today=False))


if __name__ == "__main__":
    unittest.main()

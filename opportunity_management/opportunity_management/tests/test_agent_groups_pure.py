"""
Bench-free tests for agent_groups_pure:

    python3 opportunity_management/opportunity_management/tests/test_agent_groups_pure.py

The module imports nothing from frappe, so it is loaded straight off disk.
"""

import datetime
import importlib.util
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


G = _load("_agent_groups_pure_under_test", "agent_groups_pure.py")

A, B, C = "a@x.com", "b@x.com", "c@x.com"
DT = datetime.datetime
H = 3600
# 2026-10-31 is a Saturday, 2026-11-06 a Friday.
SAT_THU = {"sat", "sun", "mon", "tue", "wed", "thu"}
NINE_FOUR = (9 * H, 16 * H)


class TestRoundRobin(unittest.TestCase):
    def test_cycles(self):
        self.assertEqual(G.pick_round_robin([A, B, C], 0), (A, 1))
        self.assertEqual(G.pick_round_robin([A, B, C], 1), (B, 2))
        self.assertEqual(G.pick_round_robin([A, B, C], 2), (C, 0))

    def test_pointer_wraps_when_members_shrink(self):
        self.assertEqual(G.pick_round_robin([A, B], 5), (B, 0))

    def test_skips_away(self):
        self.assertEqual(G.pick_round_robin([A, B, C], 0, away={A}), (B, 2))
        self.assertEqual(G.pick_round_robin([A, B, C], 2, away={C}), (A, 1))

    def test_all_away_or_empty(self):
        self.assertEqual(G.pick_round_robin([A, B], 1, away={A, B}), (None, 1))
        self.assertEqual(G.pick_round_robin([], 3), (None, 0))
        self.assertEqual(G.pick_round_robin(None, None), (None, 0))

    def test_bad_pointer_and_duplicates(self):
        self.assertEqual(G.pick_round_robin([A, A, " ", B], "x"), (A, 1))


class TestMembersToAlert(unittest.TestCase):
    def test_filters_muted_and_away(self):
        self.assertEqual(G.members_to_alert([A, B, C], muted={B}, away={C}), [A])

    def test_dedupes_keeps_order(self):
        self.assertEqual(G.members_to_alert([C, A, C, "", None]), [C, A])


class TestIsOverdue(unittest.TestCase):
    def fn(self, minutes):
        return lambda _start: minutes

    def test_overdue(self):
        self.assertTrue(G.is_overdue(DT(2026, 11, 1, 9), None, 30, self.fn(30)))
        self.assertFalse(G.is_overdue(DT(2026, 11, 1, 9), None, 30, self.fn(29)))

    def test_answered_or_unassigned_never_overdue(self):
        self.assertFalse(G.is_overdue(DT(2026, 11, 1, 9), 120, 30, self.fn(999)))
        self.assertFalse(G.is_overdue(None, None, 30, self.fn(999)))

    def test_zero_timeout_disables(self):
        self.assertFalse(G.is_overdue(DT(2026, 11, 1, 9), None, 0, self.fn(999)))
        self.assertFalse(G.is_overdue(DT(2026, 11, 1, 9), None, "bad", self.fn(999)))


class TestHold(unittest.TestCase):
    def test_hold(self):
        self.assertTrue(G.hold_out_of_hours(G.ROUND_ROBIN, G.HOLD, False))
        self.assertTrue(G.hold_out_of_hours(G.ROUND_ROBIN, None, False))
        self.assertFalse(G.hold_out_of_hours(G.ROUND_ROBIN, G.HOLD, True))
        self.assertFalse(G.hold_out_of_hours(G.ROUND_ROBIN, G.ROUND_ROBIN_ANYWAY, False))
        self.assertFalse(G.hold_out_of_hours(G.RING, G.HOLD, False))


class TestBusinessMinutes(unittest.TestCase):
    def bm(self, start, end, **kw):
        kw.setdefault("business_days", SAT_THU)
        kw.setdefault("window", NINE_FOUR)
        return G.business_minutes_between(start, end, **kw)

    def test_inside_one_day(self):
        self.assertEqual(self.bm(DT(2026, 11, 1, 10), DT(2026, 11, 1, 10, 45)), 45)

    def test_before_opening_counts_from_open(self):
        self.assertEqual(self.bm(DT(2026, 11, 1, 7), DT(2026, 11, 1, 9, 20)), 20)

    def test_overnight_counts_only_hours(self):
        # Sun 15:50 → Mon 9:25 = 10 + 25 minutes.
        self.assertEqual(self.bm(DT(2026, 11, 1, 15, 50), DT(2026, 11, 2, 9, 25)), 35)

    def test_friday_skipped(self):
        # Thu 15:45 → Sat 9:15: 15 (Thu) + 0 (Fri) + 15 (Sat).
        self.assertEqual(self.bm(DT(2026, 11, 5, 15, 45), DT(2026, 11, 7, 9, 15)), 30)

    def test_chat_created_on_day_off_waits(self):
        self.assertEqual(self.bm(DT(2026, 11, 6, 10), DT(2026, 11, 6, 23)), 0)

    def test_short_day(self):
        short = ("sat", 9 * H, 15 * H)
        self.assertEqual(self.bm(DT(2026, 10, 31, 14, 30), DT(2026, 10, 31, 15, 30), short_day=short), 30)
        self.assertEqual(self.bm(DT(2026, 11, 1, 14, 30), DT(2026, 11, 1, 15, 30), short_day=short), 60)

    def test_no_window_counts_whole_day(self):
        self.assertEqual(self.bm(DT(2026, 11, 1, 23), DT(2026, 11, 2, 1), window=None), 120)

    def test_no_days_means_every_day(self):
        self.assertEqual(self.bm(DT(2026, 11, 6, 10), DT(2026, 11, 6, 11), business_days=None), 60)

    def test_overnight_window(self):
        night = (22 * H, 2 * H)
        self.assertEqual(self.bm(DT(2026, 11, 1, 21), DT(2026, 11, 2, 3), window=night, business_days=None), 240)

    def test_reversed_or_missing(self):
        self.assertEqual(self.bm(DT(2026, 11, 2), DT(2026, 11, 1)), 0)
        self.assertEqual(self.bm(None, DT(2026, 11, 1)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

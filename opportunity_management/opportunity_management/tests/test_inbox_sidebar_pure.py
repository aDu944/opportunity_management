"""
Bench-free tests for `inbox_sidebar_pure` (web Team Inbox sidebar: the
opportunity filter, the today maths, the per-user state stamp, the
Opportunity card, quick reply / tag name helpers).

    python3 opportunity_management/opportunity_management/tests/test_inbox_sidebar_pure.py

The module has no `frappe` import, so it is loaded straight off disk.
"""

import datetime as dt
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "inbox_sidebar_pure.py")
    spec = importlib.util.spec_from_file_location("inbox_sidebar_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()


class TestOpportunityClause(unittest.TestCase):
    def test_no_filter(self):
        for value in (None, "", "   "):
            self.assertEqual(P.opportunity_clause(value), ("", {}))

    def test_unknown_raises(self):
        for value in ("Lost", "Replied", "anything", "1"):
            with self.assertRaises(ValueError, msg=value):
                P.opportunity_clause(value)

    def test_any(self):
        sql, params = P.opportunity_clause("any")
        self.assertIn("o.name IS NOT NULL", sql)
        self.assertIn("c.opportunity", sql)
        self.assertEqual(params, {})

    def test_none_hides_resolved(self):
        sql, params = P.opportunity_clause("none")
        self.assertIn("o.name IS NULL", sql)
        self.assertIn("c.status != 'Resolved'", sql)
        self.assertEqual(params, {})

    def test_single_status(self):
        for value in ("Open", "Quotation", "Converted"):
            sql, params = P.opportunity_clause(value)
            self.assertEqual(sql, "o.status IN (%(opp_0)s)")
            self.assertEqual(params, {"opp_0": value})

    def test_closed_means_closed_or_lost(self):
        sql, params = P.opportunity_clause("Closed", key="k")
        self.assertEqual(sql, "o.status IN (%(k_0)s, %(k_1)s)")
        self.assertEqual(params, {"k_0": "Closed", "k_1": "Lost"})

    def test_case_insensitive(self):
        self.assertEqual(P.opportunity_clause("open"), P.opportunity_clause("Open"))
        self.assertEqual(P.normalize_opportunity_filter(" ANY "), "any")

    def test_no_literal_percent_outside_placeholders(self):
        for value in P.OPPORTUNITY_FILTERS:
            sql, params = P.opportunity_clause(value)
            stripped = sql
            for name in params:
                stripped = stripped.replace("%({0})s".format(name), "")
            self.assertNotIn("%", stripped, value)

    def test_buckets_have_distinct_params(self):
        merged = {}
        for value in P.OPPORTUNITY_BUCKETS:
            _sql, params = P.opportunity_clause(value, key="opp_" + value.lower())
            self.assertFalse(set(params) & set(merged))
            merged.update(params)

    def test_select(self):
        sel = P.opportunity_select(True, True)
        for col in ("opportunity_status", "opportunity_stage", "opportunity_closing", "opportunity_title"):
            self.assertIn("AS " + col, sel)
        self.assertTrue(sel.endswith(", "))
        self.assertIn("NULL AS opportunity_stage", P.opportunity_select(False, True))


class TestOpportunityFields(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(P.opportunity_fields(None), dict.fromkeys(P.OPPORTUNITY_KEYS))

    def test_values(self):
        out = P.opportunity_fields({
            "opportunity_status": "Open", "opportunity_stage": " Received ",
            "opportunity_closing": dt.date(2026, 11, 30), "opportunity_title": "",
        })
        self.assertEqual(out, {"opportunity_status": "Open", "opportunity_stage": "Received",
                               "opportunity_closing": "2026-11-30", "opportunity_title": None})

    def test_date_str(self):
        self.assertEqual(P.date_str("2026-11-30 00:00:00"), "2026-11-30")
        self.assertEqual(P.date_str(dt.datetime(2026, 1, 2, 3, 4)), "2026-01-02")
        self.assertIsNone(P.date_str("soon"))
        self.assertIsNone(P.date_str(""))


class TestApplyUserState(unittest.TestCase):
    def test_marked_unread_bumps_zero(self):
        out = P.apply_user_state({"unread_count": 0, "name": "x"}, {"marked_unread": True})
        self.assertEqual(out["unread_count"], 1)
        self.assertTrue(out["marked_unread"])
        self.assertFalse(out["pinned"])

    def test_marked_unread_keeps_real_count(self):
        out = P.apply_user_state({"unread_count": 5}, {"marked_unread": 1, "pinned": 1})
        self.assertEqual(out["unread_count"], 5)
        self.assertTrue(out["pinned"])

    def test_not_marked(self):
        row = {"unread_count": 0, "pinned": True}
        out = P.apply_user_state(row, {})
        self.assertEqual(out["unread_count"], 0)
        self.assertFalse(out["pinned"])  # the recipient's own flags win
        self.assertFalse(out["marked_unread"])
        self.assertTrue(row["pinned"])  # input untouched


class TestToday(unittest.TestCase):
    NOW = dt.datetime(2026, 11, 19, 14, 30, 45)

    def test_day_start(self):
        self.assertEqual(P.day_start(self.NOW), dt.datetime(2026, 11, 19, 0, 0))

    def test_minutes_since(self):
        self.assertEqual(P.minutes_since(dt.datetime(2026, 11, 19, 13, 0, 0), self.NOW), 90)
        self.assertEqual(P.minutes_since("2026-11-19 14:30:00.123456", self.NOW), 0)
        self.assertEqual(P.minutes_since("2026-11-18T14:30:45", self.NOW), 1440)

    def test_minutes_since_never_negative_or_garbage(self):
        self.assertEqual(P.minutes_since(dt.datetime(2026, 11, 19, 15, 0), self.NOW), 0)
        self.assertIsNone(P.minutes_since(None, self.NOW))
        self.assertIsNone(P.minutes_since("yesterday", self.NOW))


class TestCard(unittest.TestCase):
    def test_stages(self):
        self.assertEqual(P.stages_from_options("\nReceived\n Quoted \n\nReceived\nWon"),
                         ["Received", "Quoted", "Won"])
        self.assertEqual(P.stages_from_options(None), [])

    def test_card(self):
        row = {"name": "INQ-1", "title": "", "status": "Open", "custom_agent_status": "Received",
               "expected_closing": dt.date(2026, 12, 1), "opportunity_amount": "1500.5",
               "currency": "USD", "modified": dt.datetime(2026, 11, 19, 10, 0)}
        card = P.opportunity_card(row, ["Received", "Quoted"], ["Ali", "", "Sara"],
                                  iso=lambda v: v.isoformat())
        self.assertEqual(card, {
            "name": "INQ-1", "title": "INQ-1", "status": "Open", "stage": "Received",
            "stages": ["Received", "Quoted"], "expected_closing": "2026-12-01",
            "responsible": ["Ali", "Sara"], "amount": 1500.5, "currency": "USD",
            "modified": "2026-11-19T10:00:00",
        })

    def test_card_missing(self):
        self.assertIsNone(P.opportunity_card(None))
        card = P.opportunity_card({"name": "X", "opportunity_amount": None})
        self.assertEqual((card["amount"], card["stage"], card["modified"]), (0.0, None, None))


class TestQuickReplyAndTags(unittest.TestCase):
    def test_default_title(self):
        text = "Hello   there,\nthanks for reaching out to us today, we will reply soon"
        out = P.quick_reply_fields(text)
        self.assertEqual(out["title"], "Hello there, thanks for reaching out to")
        self.assertLessEqual(len(out["title"]), 40)
        self.assertEqual(out["text_en"], text)
        self.assertNotIn("text_ar", out)

    def test_arabic_goes_to_text_ar(self):
        out = P.quick_reply_fields("  شكراً لتواصلك  ", title=" Thanks ")
        self.assertEqual(out, {"title": "Thanks", "text_ar": "شكراً لتواصلك"})

    def test_empty_text(self):
        for value in (None, "", "  \n "):
            with self.assertRaises(ValueError):
                P.quick_reply_fields(value)

    def test_tag_name(self):
        self.assertEqual(P.clean_tag_name("  Hot   lead "), "Hot lead")
        for bad in (None, "", "   ", "x" * 141):
            with self.assertRaises(ValueError):
                P.clean_tag_name(bad)


class TestScopeFragments(unittest.TestCase):
    def test_shared_scope_clauses(self):
        self.assertEqual(set(P.MINE_CLAUSES), {"c.assigned_to = %(me)s", "c.status != 'Resolved'"})
        self.assertIn("c.status != 'Resolved'", P.UNASSIGNED_CLAUSES)
        self.assertEqual(P.RESOLVED_CLAUSES, ("c.status = 'Resolved'",))


if __name__ == "__main__":
    unittest.main()

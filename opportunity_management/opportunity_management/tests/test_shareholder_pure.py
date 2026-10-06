"""
Bench-free tests for `shareholder_pure` (the shareholder app's date maths,
aging buckets, deltas, labels and indicative split).

    python3 opportunity_management/opportunity_management/tests/test_shareholder_pure.py

The module has no `frappe` import, so it is loaded straight off disk.
"""

import datetime
import importlib.util
import os
import unittest
from decimal import Decimal

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "shareholder_pure.py")
    spec = importlib.util.spec_from_file_location("shareholder_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()
D = datetime.date


class TestDates(unittest.TestCase):
    def test_six_month_labels(self):
        self.assertEqual(
            P.six_month_labels(D(2026, 10, 6)),
            ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"],
        )

    def test_six_month_labels_cross_year(self):
        self.assertEqual(
            P.six_month_labels(D(2026, 2, 28)),
            ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"],
        )

    def test_series_start(self):
        self.assertEqual(P.series_start(D(2026, 10, 6)), D(2026, 5, 1))

    def test_previous_month_end(self):
        self.assertEqual(P.previous_month_end(D(2026, 3, 15)), D(2026, 2, 28))
        self.assertEqual(P.previous_month_end(D(2026, 1, 1)), D(2025, 12, 31))

    def test_same_day_last_month_clamps(self):
        self.assertEqual(P.same_day_last_month(D(2026, 3, 31)), D(2026, 2, 28))
        self.assertEqual(P.same_day_last_month(D(2024, 3, 31)), D(2024, 2, 29))
        self.assertEqual(P.same_day_last_month(D(2026, 1, 15)), D(2025, 12, 15))

    def test_to_date_accepts_strings_and_datetimes(self):
        self.assertEqual(P.to_date("2026-10-06 12:00:00"), D(2026, 10, 6))
        self.assertEqual(P.to_date(datetime.datetime(2026, 10, 6, 9)), D(2026, 10, 6))
        self.assertIsNone(P.to_date(""))
        self.assertIsNone(P.to_date("not a date"))


class TestMaths(unittest.TestCase):
    def test_num_converts_decimal(self):
        v = P.num(Decimal("1234.5678"))
        self.assertIsInstance(v, float)
        self.assertEqual(v, 1234.57)
        self.assertEqual(P.num(None), 0.0)
        self.assertEqual(P.num("x"), 0.0)

    def test_delta_pct(self):
        self.assertEqual(P.delta_pct(110, 100), 10.0)
        self.assertEqual(P.delta_pct(50, 100), -50.0)
        self.assertIsNone(P.delta_pct(10, 0))
        # Negative base: improvement reads positive.
        self.assertEqual(P.delta_pct(-50, -100), 50.0)

    def test_aging_bucket(self):
        today = D(2026, 10, 6)
        self.assertEqual(P.aging_bucket(D(2026, 10, 20), today), "0-30")  # not yet due
        self.assertEqual(P.aging_bucket(None, today), "0-30")
        self.assertEqual(P.aging_bucket(D(2026, 9, 6), today), "0-30")   # 30 days
        self.assertEqual(P.aging_bucket(D(2026, 9, 5), today), "31-60")  # 31 days
        self.assertEqual(P.aging_bucket(D(2026, 8, 7), today), "31-60")  # 60 days
        self.assertEqual(P.aging_bucket(D(2026, 8, 6), today), "61-90")  # 61 days
        self.assertEqual(P.aging_bucket(D(2026, 7, 8), today), "61-90")  # 90 days
        self.assertEqual(P.aging_bucket("2026-07-07", today), "90+")

    def test_aging_summary_order_and_zero_fill(self):
        rows = [
            {"due_date": D(2026, 10, 1), "amount": Decimal("100")},
            {"due_date": D(2026, 1, 1), "amount": 50},
        ]
        out = P.aging_summary(rows, D(2026, 10, 6))
        self.assertEqual([b["bucket"] for b in out], ["0-30", "31-60", "61-90", "90+"])
        self.assertEqual([b["amount"] for b in out], [100.0, 0.0, 0.0, 50.0])
        self.assertEqual(P.aging_summary([], D(2026, 10, 6))[3], {"bucket": "90+", "amount": 0.0})

    def test_top_parties(self):
        rows = [
            {"party": "A", "party_name": "Alpha", "due_date": D(2026, 9, 1), "amount": 10},
            {"party": "A", "party_name": "Alpha", "due_date": D(2026, 8, 1), "amount": 15},
            {"party": "B", "party_name": None, "due_date": None, "amount": 30},
            {"party": None, "amount": 99},
        ]
        out = P.top_parties(rows, 5)
        self.assertEqual(out[0], {"party": "B", "party_name": "B",
                                  "outstanding": 30.0, "oldest_due_date": None})
        self.assertEqual(out[1], {"party": "A", "party_name": "Alpha",
                                  "outstanding": 25.0, "oldest_due_date": "2026-08-01"})
        self.assertEqual(len(P.top_parties(rows, 1)), 1)

    def test_build_series_zero_fills(self):
        labels = ["2026-08", "2026-09", "2026-10"]
        rows = [{"month": "2026-10", "revenue": Decimal("5"), "expenses": 2},
                {"month": "2026-08", "revenue": 1, "expenses": None}]
        self.assertEqual(P.build_series(rows, labels), [
            {"month": "2026-08", "revenue": 1.0, "expenses": 0.0},
            {"month": "2026-09", "revenue": 0.0, "expenses": 0.0},
            {"month": "2026-10", "revenue": 5.0, "expenses": 2.0},
        ])

    def test_indicative_split(self):
        owners = [{"shareholder": "S1", "share_pct": 50}, {"shareholder": "S2", "share_pct": None}]
        out = P.indicative_split(Decimal("1000"), owners)
        self.assertEqual(out[0]["indicative"], 500.0)
        self.assertEqual(out[1]["indicative"], 0.0)
        self.assertEqual(out[1]["share_pct"], 0.0)
        self.assertNotIn("indicative", owners[0])  # input untouched

    def test_totals_by_currency_never_converts(self):
        out = P.totals_by_currency([
            {"currency": "USD", "balance": 10}, {"currency": "IQD", "balance": 1000},
            {"currency": "USD", "balance": Decimal("5.5")},
        ])
        self.assertEqual(out, [{"currency": "IQD", "total": 1000.0},
                               {"currency": "USD", "total": 15.5}])


class TestLabels(unittest.TestCase):
    def test_invoice_status_passthrough(self):
        for s in P.INVOICE_STATUSES:
            self.assertEqual(P.invoice_status_label(s), s)

    def test_invoice_status_discounted_variants(self):
        self.assertEqual(P.invoice_status_label("Overdue and Discounted"), "Overdue")
        self.assertEqual(P.invoice_status_label("Partly Paid and Discounted"), "Partly Paid")
        self.assertEqual(P.invoice_status_label("Unpaid and Discounted"), "Unpaid")

    def test_invoice_status_fallback(self):
        today = D(2026, 10, 6)
        self.assertEqual(P.invoice_status_label("Internal Transfer", 0), "Paid")
        self.assertEqual(P.invoice_status_label("", 10, D(2026, 9, 1), today), "Overdue")
        self.assertEqual(P.invoice_status_label("", 10, D(2026, 11, 1), today), "Unpaid")
        self.assertEqual(P.invoice_status_label("", -5, None, today, is_return=1), "Return")

    def test_account_label(self):
        self.assertEqual(P.account_label("1110 - Cash Box - AK", "Cash Box", "AK"), "Cash Box")
        self.assertEqual(P.account_label("1110 - Cash Box - AK", None, "AK"), "Cash Box")
        self.assertEqual(P.account_label("Rafidain Bank - AK", "Rafidain Bank - AK", "AK"),
                         "Rafidain Bank")
        self.assertEqual(P.account_label("1.2.3 - USD Account - AK", None, "AK"), "USD Account")
        self.assertEqual(P.account_label("Cash", "Cash", None), "Cash")


if __name__ == "__main__":
    unittest.main()

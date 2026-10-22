"""
Bench-free tests for `expenses_pure` (validation, Journal Entry shape,
history filtering, balance and receipt checks of the expenses endpoints).

    python3 opportunity_management/opportunity_management/tests/test_expenses_pure.py

The module has no `frappe` import, so it is loaded straight off disk.
"""

import datetime
import importlib.util
import json
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "expenses_pure.py")
    spec = importlib.util.spec_from_file_location("expenses_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()
D = datetime.date
FUEL = "5210 - Fuel - AK"
MEALS = "5220 - Meals - AK"
ALLOWED = {FUEL, MEALS}
CC = "1001 - Main - AK"


class TestScalars(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(P.to_date("2026-10-22"), D(2026, 10, 22))
        self.assertEqual(P.to_date("2026-10-22 08:00:00"), D(2026, 10, 22))
        self.assertEqual(P.to_date(datetime.datetime(2026, 1, 2, 3)), D(2026, 1, 2))
        with self.assertRaises(ValueError):
            P.to_date("22/10/2026")
        with self.assertRaises(ValueError):
            P.to_date(None)

    def test_posting_date_not_future(self):
        self.assertEqual(P.validate_posting_date("2026-10-22", "2026-10-22"), D(2026, 10, 22))
        self.assertEqual(P.validate_posting_date("2026-01-01", "2026-10-22"), D(2026, 1, 1))
        with self.assertRaises(ValueError):
            P.validate_posting_date("2026-10-23", "2026-10-22")

    def test_money(self):
        self.assertEqual(P.money("1,250.005"), 1250.01)
        self.assertEqual(P.money(25000), 25000.0)
        for bad in (0, -5, "0.004", "abc", None, "nan", "inf"):
            with self.assertRaises(ValueError, msg=bad):
                P.money(bad)

    def test_clean_text(self):
        self.assertEqual(P.clean_text("  taxi  "), "taxi")
        self.assertEqual(P.clean_text(None), "")
        self.assertEqual(len(P.clean_text("x" * 500)), 500)
        with self.assertRaises(ValueError):
            P.clean_text("x" * 501)

    def test_like_pattern_escapes(self):
        self.assertEqual(P.like_pattern("abc"), "%abc%")
        self.assertEqual(P.like_pattern(None), "%%")
        self.assertEqual(P.like_pattern("50%_a\\b"), "%50\\%\\_a\\\\b%")

    def test_clamp_limit(self):
        self.assertEqual(P.clamp_limit("50"), 50)
        self.assertEqual(P.clamp_limit(None), 200)
        self.assertEqual(P.clamp_limit(0), 1)
        self.assertEqual(P.clamp_limit(9999), 500)


class TestRows(unittest.TestCase):
    def _rows(self, **over):
        row = {"account": FUEL, "amount": 15000, "project": "PROJ-0001", "remark": " taxi "}
        row.update(over)
        return [row]

    def test_json_and_list_accepted(self):
        rows = self._rows()
        self.assertEqual(P.normalise_rows(json.dumps(rows), ALLOWED, CC),
                         P.normalise_rows(rows, ALLOWED, CC))

    def test_normalised_shape(self):
        out = P.normalise_rows(self._rows(), ALLOWED, CC)
        self.assertEqual(out, [{"account": FUEL, "amount": 15000.0, "cost_center": CC,
                                "project": "PROJ-0001", "opportunity": "", "remark": "taxi"}])

    def test_row_cost_center_override(self):
        out = P.normalise_rows(self._rows(cost_center="2000 - Branch - AK"), ALLOWED, CC)
        self.assertEqual(out[0]["cost_center"], "2000 - Branch - AK")

    def test_account_whitelist(self):
        for acc in ("1110 - Cash - AK", "", None):
            with self.assertRaises(ValueError):
                P.normalise_rows(self._rows(account=acc), ALLOWED, CC)
        with self.assertRaises(ValueError):
            P.normalise_rows(self._rows(), {""}, CC)

    def test_exactly_one_link(self):
        with self.assertRaises(ValueError):
            P.normalise_rows(self._rows(project=""), ALLOWED, CC)
        with self.assertRaises(ValueError):
            P.normalise_rows(self._rows(opportunity="CRM-OPP-1"), ALLOWED, CC)
        out = P.normalise_rows(self._rows(project=None, opportunity="CRM-OPP-1"), ALLOWED, CC)
        self.assertEqual(out[0]["opportunity"], "CRM-OPP-1")

    def test_bad_rows(self):
        for raw in ("", "[]", "{}", "not json", [], ["x"], None):
            with self.assertRaises(ValueError, msg=raw):
                P.normalise_rows(raw, ALLOWED, CC)
        with self.assertRaises(ValueError):
            P.normalise_rows(self._rows() * (P.MAX_ROWS + 1), ALLOWED, CC)
        with self.assertRaises(ValueError):
            P.normalise_rows(self._rows(amount=0), ALLOWED, CC)
        with self.assertRaises(ValueError):
            P.normalise_rows(self._rows(remark="y" * 501), ALLOWED, CC)


class TestJournalEntry(unittest.TestCase):
    def setUp(self):
        self.rows = P.normalise_rows([
            {"account": FUEL, "amount": "10000.10", "project": "PROJ-1", "remark": "fuel"},
            {"account": MEALS, "amount": 5000, "opportunity": "CRM-OPP-9"},
        ], ALLOWED, CC)

    def test_structure_matches_app(self):
        je = P.build_journal_entry("AL KHORA", "2026-10-22", "2140 - Advances - AK",
                                   "HR-EMP-0007", CC, self.rows)
        self.assertEqual(je, {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "posting_date": "2026-10-22",
            "company": "AL KHORA",
            "user_remark": "fuel",
            "accounts": [
                {"account": FUEL, "debit_in_account_currency": 10000.1,
                 "credit_in_account_currency": 0, "cost_center": CC,
                 "project": "PROJ-1", "user_remark": "fuel"},
                {"account": MEALS, "debit_in_account_currency": 5000.0,
                 "credit_in_account_currency": 0, "cost_center": CC,
                 "custom_opportunity": "CRM-OPP-9"},
                {"account": "2140 - Advances - AK", "debit_in_account_currency": 0,
                 "credit_in_account_currency": 15000.1, "party_type": "Employee",
                 "party": "HR-EMP-0007", "cost_center": CC},
            ],
        })
        self.assertNotIn("docstatus", je)

    def test_remarks(self):
        rows = [dict(r, remark=x) for r, x in zip(self.rows, ("a", "b"))]
        self.assertEqual(P.combined_remark(rows), "a | b")
        self.assertEqual(P.combined_remark(rows, "  claim  "), "claim")
        self.assertEqual(P.combined_remark([dict(r, remark="") for r in rows]), "")

    def test_total_rounding(self):
        rows = [{"amount": 0.1}, {"amount": 0.2}]
        self.assertEqual(P.total_amount(rows), 0.3)


class TestReadSide(unittest.TestCase):
    def test_history_filters_other_lines(self):
        rows = [
            {"name": "ACC-JV-1", "posting_date": D(2026, 10, 1), "user_remark": None,
             "docstatus": 1, "account": "ADV", "party": "EMP-1",
             "debit_in_account_currency": 0, "credit_in_account_currency": 5000,
             "account_currency": "IQD"},
            {"name": "ACC-JV-1", "posting_date": D(2026, 10, 1), "account": "ADV",
             "party": "EMP-2", "credit_in_account_currency": 9},
            {"name": "ACC-JV-1", "posting_date": D(2026, 10, 1), "account": FUEL,
             "party": None, "debit_in_account_currency": 5000},
        ]
        out = P.history_rows(rows, "ADV", "EMP-1")
        self.assertEqual(out, [{
            "name": "ACC-JV-1", "posting_date": "2026-10-01", "user_remark": "",
            "docstatus": 1, "account": "ADV", "party": "EMP-1",
            "debit_in_account_currency": 0.0, "credit_in_account_currency": 5000.0,
            "account_currency": "IQD",
        }])

    def test_balance(self):
        self.assertEqual(P.balance(15000, 5000), 10000.0)
        self.assertEqual(P.balance(None, 250.5), -250.5)
        self.assertEqual(P.balance(0, 0), 0.0)


class TestReceipts(unittest.TestCase):
    JPG = b"\xff\xd8\xff\xe0" + b"0" * 32
    PDF = b"%PDF-1.7\n" + b"0" * 32
    HEIC = b"\x00\x00\x00\x18ftypheic" + b"0" * 32

    def test_accepts_images_and_pdf(self):
        self.assertEqual(P.check_receipt("receipt_1.jpg", self.JPG), "receipt_1.jpg")
        self.assertEqual(P.check_receipt("Scan.PDF", self.PDF), "Scan.pdf")
        self.assertEqual(P.check_receipt("IMG 1.heic", self.HEIC), "IMG1.heic")
        self.assertEqual(P.check_receipt("../../x/%%.png", b"\x89PNG\r\n" + b"0" * 9), "receipt.png")

    def test_rejects(self):
        cases = [("a.exe", self.JPG), ("a.jpg", b"MZ" + b"0" * 30), ("a.pdf", self.JPG),
                 ("a.jpg", self.PDF), ("a.jpg", b""), ("noext", self.JPG),
                 ("a.html", b"<html>")]
        for name, content in cases:
            with self.assertRaises(ValueError, msg=name):
                P.check_receipt(name, content)

    def test_size(self):
        big = self.JPG + b"0" * (P.MAX_RECEIPT_BYTES)
        with self.assertRaises(ValueError):
            P.check_receipt("a.jpg", big)
        with self.assertRaises(ValueError):
            P.check_receipt("a.jpg", self.JPG, max_bytes=10)

    def test_limit_setting(self):
        self.assertEqual(P.receipt_limit_bytes(0), P.MAX_RECEIPT_BYTES)
        self.assertEqual(P.receipt_limit_bytes(None), P.MAX_RECEIPT_BYTES)
        self.assertEqual(P.receipt_limit_bytes(2), 2 * 1024 * 1024)
        self.assertEqual(P.receipt_limit_bytes(50), P.MAX_RECEIPT_BYTES)


if __name__ == "__main__":
    unittest.main()

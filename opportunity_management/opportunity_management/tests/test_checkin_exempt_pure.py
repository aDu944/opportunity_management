"""
Bench-free tests for the pure parts of `checkin_exempt` (SQL fragment and
the seed patch's email matching).

    python3 opportunity_management/opportunity_management/tests/test_checkin_exempt_pure.py

`checkin_exempt` imports `frappe` lazily, so it is loaded straight off disk.
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "checkin_exempt.py")
    spec = importlib.util.spec_from_file_location("checkin_exempt_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load()


class TestSqlClause(unittest.TestCase):
    def test_fragment(self):
        self.assertEqual(C.EXEMPT_SQL, "COALESCE(e.custom_checkin_exempt, 0) = 0")

    def test_clause_with_column(self):
        self.assertEqual(C.exempt_sql_clause(True),
                         " AND COALESCE(e.custom_checkin_exempt, 0) = 0")

    def test_clause_before_migrate_is_empty(self):
        self.assertEqual(C.exempt_sql_clause(False), "")

    def test_clause_has_no_percent(self):
        # Appended to %s-parameterised queries; a bare % would break pymysql.
        self.assertNotIn("%", C.exempt_sql_clause(True))


class TestSplitFound(unittest.TestCase):
    def test_seed_users(self):
        self.assertEqual(
            set(C.SEED_EXEMPT_USERS),
            {"as@alkhora.com", "ali.s@alkhora.com", "a.kh@alkhora.com", "aziz@alkhora.com"},
        )

    def test_some_missing(self):
        found, missing = C.split_found(
            C.SEED_EXEMPT_USERS, ["as@alkhora.com", "AZIZ@alkhora.com ", "x@alkhora.com"])
        self.assertEqual(found, ["as@alkhora.com", "aziz@alkhora.com"])
        self.assertEqual(missing, ["ali.s@alkhora.com", "a.kh@alkhora.com"])

    def test_none_and_blanks(self):
        self.assertEqual(C.split_found(["", None, "a@b.c"], None), ([], ["a@b.c"]))
        self.assertEqual(C.split_found(None, ["a@b.c"]), ([], []))


if __name__ == "__main__":
    unittest.main()

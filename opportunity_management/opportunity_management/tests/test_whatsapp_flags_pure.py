"""
Bench-free tests for the shared team flag on WhatsApp conversations:

    whatsapp_chat_state   the `flagged` list scope's WHERE / ORDER BY
    whatsapp_flags        note text, note cleaning, flag parsing, the values
                          set_flag writes and the ConvRow flag keys

    PYTHONPATH=. python3 opportunity_management/opportunity_management/tests/test_whatsapp_flags_pure.py

A stub `frappe` is injected when none is importable; each module is loaded
straight off disk.
"""

import importlib.util
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _install_stubs():
    if "frappe" in sys.modules:
        return

    def _no_bench(*args, **kwargs):
        raise RuntimeError("no bench available in this test run")

    stub = types.ModuleType("frappe")
    stub._dict = dict
    stub.local = types.SimpleNamespace()
    stub.flags = {}
    stub.get_doc = _no_bench
    stub.get_all = _no_bench
    stub.db = types.SimpleNamespace(get_value=_no_bench, exists=_no_bench, has_column=_no_bench)
    utils = types.ModuleType("frappe.utils")
    utils.cint = lambda v: int(float(v or 0)) if str(v or "0").strip() else 0
    stub.utils = utils
    sys.modules["frappe"] = stub
    sys.modules["frappe.utils"] = utils


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_stubs()
CS = _load("_wa_chat_state_flags_under_test", "whatsapp_chat_state.py")
FL = _load("_wa_flags_under_test", "whatsapp_flags.py")


class TestFlaggedScope(unittest.TestCase):
    def test_where_is_open_and_flagged(self):
        self.assertEqual(CS.SCOPE_CLAUSES["flagged"], CS.FLAGGED_CLAUSES)
        self.assertEqual(set(CS.FLAGGED_CLAUSES), {
            "c.status != 'Resolved'",
            "COALESCE(c.is_flagged, 0) = 1",
        })

    def test_oldest_flag_first_and_pins_do_not_jump(self):
        _, _, pinned = CS.list_sql(True)
        self.assertEqual(CS.scope_order("flagged", pinned), "c.flagged_at ASC, c.modified DESC")
        self.assertEqual(CS.scope_order("waiting", pinned), CS.WAITING_ORDER)
        for scope in ("all", "mine", "unassigned", "expired", "resolved"):
            self.assertEqual(CS.scope_order(scope, pinned), pinned)
            self.assertNotIn(scope, CS.SCOPE_CLAUSES)

    def test_no_literal_percent(self):
        sql = " ".join(CS.FLAGGED_CLAUSES) + CS.FLAGGED_ORDER
        sql += FL.list_select("c") + FL.count_select()
        self.assertNotIn("%", sql)

    def test_select_falls_back_before_migrate(self):
        # The stub's has_column raises → treated as "no column yet".
        self.assertFalse(FL.has_columns())
        self.assertEqual(
            FL.list_select("c"),
            "0 AS is_flagged, NULL AS flagged_by, NULL AS flagged_at, NULL AS flag_note, ",
        )
        self.assertEqual(FL.count_select(), "0 AS flagged_open")


class TestFlagHelpers(unittest.TestCase):
    def test_note_text(self):
        self.assertEqual(FL.note_text(True, "Sara", "VIP — call back"), "Flagged by Sara: VIP — call back")
        self.assertEqual(FL.note_text(True, "Sara"), "Flagged by Sara")
        self.assertEqual(FL.note_text(False, "Sara", "ignored"), "Flag removed by Sara")
        upper = FL.note_text(True, "Sara", translate=lambda s: s.upper())
        self.assertEqual(upper, "FLAGGED BY Sara")

    def test_clean_note(self):
        self.assertIsNone(FL.clean_note(None))
        self.assertIsNone(FL.clean_note("   \n "))
        self.assertEqual(FL.clean_note("  needs\n\na  quote "), "needs a quote")
        self.assertEqual(len(FL.clean_note("x" * 300)), FL.NOTE_MAX)

    def test_parse_flag(self):
        for yes in (1, "1", "true", "True", True, "yes"):
            self.assertTrue(FL.parse_flag(yes), yes)
        for no in (0, "0", "false", False, None, "", "no"):
            self.assertFalse(FL.parse_flag(no), no)

    def test_flag_values_keep_queue_position(self):
        fresh = FL.flag_values({"is_flagged": 0}, "a@x", "n", "NOW")
        self.assertEqual(fresh, {"is_flagged": 1, "flagged_by": "a@x", "flagged_at": "NOW", "flag_note": "n"})
        again = FL.flag_values({"is_flagged": 1, "flagged_at": "THEN"}, "b@x", None, "NOW")
        self.assertEqual(again["flagged_at"], "THEN")
        self.assertEqual(again["flagged_by"], "b@x")

    def test_cleared_matches_fields(self):
        self.assertEqual(set(FL.CLEARED), set(FL.FIELDS))
        self.assertEqual(FL.CLEARED["is_flagged"], 0)

    def test_conv_row_fields(self):
        self.assertEqual(FL.flag_fields({"is_flagged": 0, "flagged_by": "a@x"}), FL.UNFLAGGED_ROW)
        row = FL.flag_fields(
            {"is_flagged": 1, "flagged_by": "a@x", "flagged_at": "2026-10-14 09:00:00", "flag_note": ""},
            "Sara", iso=lambda v: "iso:" + v,
        )
        self.assertEqual(row, {
            "is_flagged": True, "flagged_by": "a@x", "flagged_by_name": "Sara",
            "flagged_at": "iso:2026-10-14 09:00:00", "flag_note": None,
        })
        # Batched "" (unknown user) falls back to the id, no lookup.
        self.assertEqual(FL.flag_fields({"is_flagged": 1, "flagged_by": "a@x"}, "")["flagged_by_name"], "a@x")


if __name__ == "__main__":
    unittest.main(verbosity=1)

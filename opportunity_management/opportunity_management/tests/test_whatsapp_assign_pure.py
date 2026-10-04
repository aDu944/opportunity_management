"""
Bench-free tests for the conversation hand-off rule:

    whatsapp_assign_rules.may_assign / may_transfer

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_assign_pure.py

The module imports nothing from frappe, so it is loaded straight off disk.
"""

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


AR = _load("_wa_assign_rules_under_test", "whatsapp_assign_rules.py")

ME, BOB, CAROL = "me@x.com", "bob@x.com", "carol@x.com"
ROSTER = {ME, BOB, CAROL}


class TestManager(unittest.TestCase):
    def test_unassigned_to_anyone(self):
        self.assertEqual(AR.may_assign(True, ME, None, BOB, ROSTER), (True, AR.ASSIGN))

    def test_someone_elses_chat_reassigned(self):
        self.assertEqual(AR.may_assign(True, ME, BOB, CAROL, ROSTER), (True, AR.ASSIGN))

    def test_take_over(self):
        self.assertEqual(AR.may_assign(True, ME, BOB, ME, ROSTER), (True, AR.ASSIGN))

    def test_own_chat_is_a_transfer(self):
        self.assertEqual(AR.may_assign(True, ME, ME, BOB, ROSTER), (True, AR.TRANSFER))

    def test_target_outside_roster_refused(self):
        self.assertEqual(
            AR.may_assign(True, ME, BOB, "ghost@x.com", ROSTER), (False, AR.TARGET_NOT_AGENT)
        )

    def test_same_owner_is_noop(self):
        self.assertEqual(AR.may_assign(True, ME, BOB, BOB, ROSTER), (True, AR.NOOP))


class TestAgent(unittest.TestCase):
    def test_own_chat_transfer_allowed(self):
        self.assertEqual(AR.may_assign(False, ME, ME, BOB, ROSTER), (True, AR.TRANSFER))

    def test_own_chat_to_outsider_refused(self):
        self.assertEqual(
            AR.may_assign(False, ME, ME, "ghost@x.com", ROSTER), (False, AR.TARGET_NOT_AGENT)
        )

    def test_unassigned_chat_to_other_refused(self):
        self.assertEqual(
            AR.may_assign(False, ME, None, BOB, ROSTER), (False, AR.NOT_OWNER_UNASSIGNED)
        )
        self.assertEqual(
            AR.may_assign(False, ME, "", BOB, ROSTER), (False, AR.NOT_OWNER_UNASSIGNED)
        )

    def test_unassigned_chat_to_self_is_a_claim(self):
        self.assertEqual(AR.may_assign(False, ME, None, ME, ROSTER), (True, AR.CLAIM))

    def test_someone_elses_chat_refused(self):
        self.assertEqual(AR.may_assign(False, ME, BOB, CAROL, ROSTER), (False, AR.NOT_OWNER))

    def test_someone_elses_chat_take_over_refused(self):
        self.assertEqual(AR.may_assign(False, ME, BOB, ME, ROSTER), (False, AR.NOT_OWNER))

    def test_someone_elses_chat_noop_still_refused(self):
        # Permission comes first: no "no-op" answer leaks for a chat you cannot touch.
        self.assertEqual(AR.may_assign(False, ME, BOB, BOB, ROSTER), (False, AR.NOT_OWNER))


class TestTargetIsCaller(unittest.TestCase):
    def test_owner_to_self_is_noop(self):
        self.assertEqual(AR.may_assign(False, ME, ME, ME, ROSTER), (True, AR.NOOP))
        self.assertEqual(AR.may_assign(True, ME, ME, ME, ROSTER), (True, AR.NOOP))

    def test_empty_target_refused(self):
        self.assertEqual(AR.may_assign(True, ME, BOB, "", ROSTER), (False, AR.NO_TARGET))
        self.assertEqual(AR.may_assign(False, ME, ME, None, ROSTER), (False, AR.NO_TARGET))

    def test_no_roster_skips_target_check(self):
        self.assertEqual(AR.may_assign(False, ME, ME, "x@x.com"), (True, AR.TRANSFER))


class TestMayTransfer(unittest.TestCase):
    def test_flags(self):
        self.assertTrue(AR.may_transfer(True, ME, None))
        self.assertTrue(AR.may_transfer(True, ME, BOB))
        self.assertTrue(AR.may_transfer(False, ME, ME))
        self.assertFalse(AR.may_transfer(False, ME, None))
        self.assertFalse(AR.may_transfer(False, ME, BOB))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
Unit tests for `whatsapp_identity` — phone numbers vs. Meta's business-scoped
user IDs (BSUIDs) and WhatsApp usernames.

Runnable **without a bench**, like `test_whatsapp_utils.py`:

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_identity.py

A stub `frappe` is injected when none is importable, `whatsapp_utils` is
loaded off disk and registered under its dotted name, and only then is
`whatsapp_identity` loaded — so its `from …whatsapp_utils import` resolves to
the already-loaded module without touching the app's package `__init__`s.
"""

import importlib.util
import os
import sys
import types
import unittest

_UTILS_NAME = "opportunity_management.opportunity_management.whatsapp_utils"
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _install_frappe_stub():
    if "frappe" in sys.modules:
        return

    def _no_bench(*args, **kwargs):
        raise RuntimeError("no bench available in this test run")

    stub = types.ModuleType("frappe")
    stub._dict = dict
    stub.local = types.SimpleNamespace()
    stub.get_cached_doc = _no_bench
    stub.get_all = _no_bench
    stub.db = types.SimpleNamespace(get_value=_no_bench)
    sys.modules["frappe"] = stub


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_frappe_stub()
wu = sys.modules.get(_UTILS_NAME) or _load(_UTILS_NAME, "whatsapp_utils.py")
wi = _load("_wa_identity_under_test", "whatsapp_identity.py")

CC = "964"


class TestIsBsuid(unittest.TestCase):
    def test_table(self):
        cases = [
            ("IQ.1858675848823706", True),
            ("US.ENT.123", True),
            ("  IQ.4719688614983810 ", True),   # surrounding whitespace
            ("iq.1858675848823706", False),     # lowercase country code
            ("1858675848823706", False),        # digits only (the old mangling)
            ("+9647738524563", False),          # phone with +
            ("9647738524563", False),
            ("IQ.", False),
            ("", False),
            (None, False),
            (9647738524563, False),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(wi.is_bsuid(value), expected)


class TestNormalizeWaIdentifier(unittest.TestCase):
    def test_bsuid_preserved(self):
        self.assertEqual(wi.normalize_wa_identifier("IQ.1858675848823706", CC), "IQ.1858675848823706")
        self.assertEqual(wi.normalize_wa_identifier(" US.ENT.123 ", CC), "US.ENT.123")

    def test_phones_match_normalize_phone(self):
        for raw in (
            "0770 123 4567", "+964 770 123 4567", "00964 770 123 4567",
            "964 0770 123 4567", "9647701234567", "7701234567", "+1 415 555 2671",
            "(0770) 123-4567", None, "", "abc", "12345", "+964",
            "iq.1858675848823706", "1858675848823706",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    wi.normalize_wa_identifier(raw, default_cc=CC),
                    wu.normalize_phone(raw, default_cc=CC),
                )


class TestHandle(unittest.TestCase):
    def test_four_cases(self):
        self.assertEqual(wi.render_handle("9647738524563", "20_plo"), "+9647738524563 · @20_plo")
        self.assertEqual(wi.render_handle("9647738524563", None), "+9647738524563")
        self.assertEqual(wi.render_handle("IQ.1858675848823706", "20_plo"), "@20_plo")
        self.assertEqual(wi.render_handle("IQ.1858675848823706", None), "")

    def test_leading_at_not_doubled(self):
        self.assertEqual(wi.render_handle("IQ.1858675848823706", "@20_plo"), "@20_plo")

    def test_has_phone(self):
        self.assertTrue(wi.has_phone("9647738524563"))
        self.assertFalse(wi.has_phone("IQ.1858675848823706"))
        self.assertFalse(wi.has_phone(""))


class TestDisplayLabel(unittest.TestCase):
    BSUID = "IQ.1858675848823706"

    def test_name_wins(self):
        self.assertEqual(wi.display_label("Maher", self.BSUID, "20_plo"), "Maher")

    def test_never_a_raw_bsuid(self):
        for stored in ("", None, self.BSUID, "1858675848823706"):
            with self.subTest(stored=stored):
                self.assertEqual(wi.display_label(stored, self.BSUID, "20_plo"), "@20_plo")
                self.assertEqual(wi.display_label(stored, self.BSUID, None), "WhatsApp user")

    def test_phone_fallback(self):
        self.assertEqual(wi.display_label("", "9647738524563", None), "9647738524563")
        self.assertEqual(wi.display_label("9647738524563", "9647738524563", "20_plo"), "@20_plo")


_LIVE_PAYLOAD = {
    "entry": [{"changes": [{"value": {
        "contacts": [{"profile": {"name": "ماهر", "username": "20_plo"},
                      "user_id": "IQ.1858675848823706"}],
        "messages": [{"from_user_id": "IQ.1858675848823706", "id": "wamid.x",
                      "type": "text", "text": {"body": "hi"}}],
    }}]}],
}


class TestSenderContacts(unittest.TestCase):
    def test_hidden_number_payload(self):
        contacts = wi.contacts_by_sender(_LIVE_PAYLOAD)
        info = wi.lookup_sender(contacts, "IQ.1858675848823706")
        self.assertEqual(info["username"], "20_plo")
        self.assertEqual(info["user_id"], "IQ.1858675848823706")
        self.assertIsNone(info["wa_id"])

    def test_keyed_by_both_addresses(self):
        payload = {"entry": [{"changes": [{"value": {"contacts": [
            {"wa_id": "9647738524563", "user_id": "IQ.42", "profile": {"username": "@x"}}
        ]}}]}]}
        contacts = wi.contacts_by_sender(payload)
        self.assertEqual(wi.lookup_sender(contacts, "9647738524563")["username"], "x")
        self.assertEqual(wi.lookup_sender(contacts, "+964 773 852 4563")["user_id"], "IQ.42")
        self.assertEqual(wi.lookup_sender(contacts, "IQ.42")["wa_id"], "9647738524563")

    def test_malformed_never_raises(self):
        for data in (None, {}, {"entry": "x"}, {"entry": [{"changes": [{"value": {"contacts": [1]}}]}]}):
            with self.subTest(data=data):
                self.assertEqual(wi.contacts_by_sender(data), {})
        self.assertEqual(wi.lookup_sender(None, "IQ.1"), {})
        self.assertEqual(wi.lookup_sender({}, "IQ.1"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)

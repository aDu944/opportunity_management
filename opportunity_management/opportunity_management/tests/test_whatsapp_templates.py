"""
Unit tests for `whatsapp_templates.is_hidden_template` — the check that keeps
the web shop's OTP templates and Meta's `hello_world` sample out of the inbox.

Runnable **without a bench**, like `test_whatsapp_identity.py`:

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_templates.py

A stub `frappe` is injected when none is importable and the module is loaded
straight off disk; `whatsapp_templates` keeps every `frappe.*` call inside a
function body, so nothing here touches the database.
"""

import importlib.util
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _install_frappe_stub():
    if "frappe" in sys.modules:
        return

    def _no_bench(*args, **kwargs):
        raise RuntimeError("no bench available in this test run")

    stub = types.ModuleType("frappe")
    stub._dict = dict
    stub.local = types.SimpleNamespace()
    stub.get_doc = _no_bench
    stub.get_single = _no_bench
    stub.db = types.SimpleNamespace(get_value=_no_bench, exists=_no_bench)
    sys.modules["frappe"] = stub


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_frappe_stub()
wt = _load("_wa_templates_under_test", "whatsapp_templates.py")


class _Doc:
    """Just enough of a Document: `.get(key)` over attributes."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class TestIsHiddenTemplate(unittest.TestCase):
    def test_table(self):
        cases = [
            ({"category": "AUTHENTICATION", "actual_name": "shop_otp_en"}, True),
            ({"category": "otp", "template_name": "login_code"}, True),         # lower-case
            ({"category": " Authentication ", "template_name": "x"}, True),
            ({"category": "UTILITY", "actual_name": "hello_world"}, True),      # via actual_name
            ({"category": "UTILITY", "template_name": "hello_world"}, True),    # via template_name
            ({"category": "UTILITY", "template_name": "Hello World"}, True),    # upstream normalisation
            ({"category": "UTILITY", "actual_name": "", "template_name": "hello_world"}, True),
            ({"category": "UTILITY", "actual_name": "follow_up", "template_name": "follow_up"}, False),
            ({"category": "MARKETING", "template_name": "hello_world_promo"}, False),
            ({}, False),
            (None, False),
        ]
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(wt.is_hidden_template(row), expected)

    def test_document_like(self):
        self.assertTrue(wt.is_hidden_template(_Doc(category="AUTHENTICATION", actual_name="shop_otp_ar")))
        self.assertTrue(wt.is_hidden_template(_Doc(category="UTILITY", template_name="hello_world")))
        self.assertFalse(wt.is_hidden_template(_Doc(category="UTILITY", actual_name="follow_up_reply")))

    def test_has_permission_hook(self):
        self.assertIs(wt.template_has_permission({"category": "AUTHENTICATION"}, "delete"), False)
        self.assertIsNone(wt.template_has_permission({"category": "UTILITY", "actual_name": "follow_up"}, "read"))


class TestFollowupSet(unittest.TestCase):
    def test_names_and_placeholders(self):
        names = []
        for template_name, samples, bodies in wt.FOLLOWUP_TEMPLATES:
            self.assertEqual(set(bodies), {"ar", "en"})
            for lang, body in bodies.items():
                names.append(wt._doc_name(template_name, lang))
                # One sample value per distinct {{n}} placeholder.
                count = len({p for p in range(1, 10) if "{{%d}}" % p in body})
                self.assertEqual(count, len(samples.split(",")), (template_name, lang))
            self.assertFalse(wt.is_hidden_template({"category": wt.FOLLOWUP_CATEGORY, "template_name": template_name}))
        self.assertIn(wt.FOLLOWUP_DEFAULT, names)
        self.assertEqual(len(names), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)

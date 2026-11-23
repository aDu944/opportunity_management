"""Bench-free tests for whatsapp_media_repair.fixes (python3 tests/test_whatsapp_media_repair_pure.py)."""

import importlib.util
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    fake = types.ModuleType("frappe")
    fake.whitelist = lambda *a, **kw: (lambda f: f)
    sys.modules.setdefault("frappe", fake)
    spec = importlib.util.spec_from_file_location("media_repair_under_test", os.path.join(_HERE, "whatsapp_media_repair.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load()


class TestFixes(unittest.TestCase):
    def test_duplicate_picture_case_from_23_nov(self):
        # First message still says the old URL; its File was re-pointed by Frappe.
        messages = [{"name": "ejbqqt5k2g", "attach": "/private/files/c5331b3c81.jpeg"},
                    {"name": "fq2c74987o", "attach": "/private/files/c4c68bdb3e.jpeg"}]
        files = [{"attached_to_name": "ejbqqt5k2g", "file_url": "/private/files/c4c68bdb3e.jpeg", "is_private": 1},
                 {"attached_to_name": "fq2c74987o", "file_url": "/private/files/c4c68bdb3e.jpeg", "is_private": 1}]
        self.assertEqual(R.fixes(messages, files), [("ejbqqt5k2g", "/private/files/c4c68bdb3e.jpeg", True)])

    def test_aligned_rows_untouched(self):
        messages = [{"name": "a", "attach": "/private/files/x.jpeg"}]
        files = [{"attached_to_name": "a", "file_url": "/private/files/x.jpeg", "is_private": 1}]
        self.assertEqual(R.fixes(messages, files), [])

    def test_no_file_or_no_attach_is_skipped(self):
        messages = [{"name": "a", "attach": "/private/files/x.jpeg"}, {"name": "b", "attach": ""}]
        files = [{"attached_to_name": "b", "file_url": "/private/files/y.jpeg", "is_private": 1}]
        self.assertEqual(R.fixes(messages, files), [])

    def test_first_file_per_message_wins_and_privacy_follows(self):
        messages = [{"name": "a", "attach": "/files/old.jpeg"}]
        files = [{"attached_to_name": "a", "file_url": "/files/new.jpeg", "is_private": 0},
                 {"attached_to_name": "a", "file_url": "/private/files/other.jpeg", "is_private": 1}]
        self.assertEqual(R.fixes(messages, files), [("a", "/files/new.jpeg", False)])


if __name__ == "__main__":
    unittest.main()

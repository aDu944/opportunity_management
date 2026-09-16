"""
Unit tests for the pure helpers in `whatsapp_utils`.

Deliberately runnable **without a bench**:

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_utils.py

A stub `frappe` module is injected into `sys.modules` and the module under
test is loaded straight off disk, so none of the app's package `__init__`
chain (which does import frappe for real) is touched. That is also why
`whatsapp_utils` keeps every `frappe.*` call inside a function body.

`bench --site <site> run-tests --module
opportunity_management.opportunity_management.tests.test_whatsapp_utils`
works too — the stub only replaces `frappe` if it is not already imported.
"""

import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime, timedelta


# ── stub frappe (only when running outside a bench) ──────────────────────────

def _install_frappe_stub():
    if "frappe" in sys.modules:
        return

    class _Dict(dict):
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError:
                raise AttributeError(key)

        def __setattr__(self, key, value):
            self[key] = value

    def _no_bench(*args, **kwargs):
        raise RuntimeError("no bench available in this test run")

    stub = types.ModuleType("frappe")
    stub._dict = _Dict
    stub.local = types.SimpleNamespace()
    stub.get_cached_doc = _no_bench
    stub.get_single = _no_bench
    stub.get_doc = _no_bench
    stub.get_all = _no_bench
    stub.log_error = lambda *a, **k: None
    stub.get_traceback = lambda *a, **k: ""
    stub.db = types.SimpleNamespace(
        get_value=_no_bench, exists=_no_bench, get_single_value=_no_bench
    )
    sys.modules["frappe"] = stub


_install_frappe_stub()

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "whatsapp_utils.py"
)
_spec = importlib.util.spec_from_file_location("_wa_utils_under_test", _MODULE_PATH)
wu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wu)


# ── helpers ──────────────────────────────────────────────────────────────────

def _on(weekday: str, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A datetime on the next occurrence of `weekday` ("Wed", "Fri", …).

    Beats hard-coding calendar dates that nobody can verify by eye.
    """
    day = datetime(2026, 1, 1)
    for _ in range(7):
        if day.strftime("%a") == weekday:
            break
        day += timedelta(days=1)
    else:  # pragma: no cover
        raise ValueError(f"unknown weekday {weekday}")
    return day.replace(hour=hour, minute=minute, second=second)


_WORK_WEEK = {
    "business_days": "Sun,Mon,Tue,Wed,Thu",
    "business_hours_start": "09:00:00",
    "business_hours_end": "17:00:00",
}


class TestNormalizePhone(unittest.TestCase):
    CC = "964"

    def test_table(self):
        cases = [
            # (raw, expected)
            ("0770 123 4567", "9647701234567"),      # local with trunk zero
            ("+964 770 123 4567", "9647701234567"),  # E.164
            ("00964 770 123 4567", "9647701234567"), # international prefix
            ("964 0770 123 4567", "9647701234567"),  # cc + trunk zero
            ("9647701234567", "9647701234567"),      # already normalized
            ("7701234567", "9647701234567"),         # bare national number
            ("+1 415 555 2671", "14155552671"),      # foreign — left alone
            ("(0770) 123-4567", "9647701234567"),    # punctuation
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(wu.normalize_phone(raw, default_cc=self.CC), expected)

    def test_junk_returns_empty(self):
        for raw in (None, "", "   ", "abc", "12345", "+964"):
            with self.subTest(raw=raw):
                self.assertEqual(wu.normalize_phone(raw, default_cc=self.CC), "")

    def test_no_country_code_configured(self):
        # Without a cc we must not invent one, but a trunk zero still goes.
        self.assertEqual(wu.normalize_phone("07701234567", default_cc=""), "7701234567")
        self.assertEqual(wu.normalize_phone("9647701234567", default_cc=""), "9647701234567")

    def test_idempotent(self):
        once = wu.normalize_phone("0770 123 4567", default_cc=self.CC)
        self.assertEqual(wu.normalize_phone(once, default_cc=self.CC), once)


class TestDetectLanguage(unittest.TestCase):
    def test_arabic(self):
        self.assertEqual(wu.detect_language("مرحبا، أريد عرض سعر"), "ar")

    def test_english(self):
        self.assertEqual(wu.detect_language("Hello, I need a quotation"), "en")

    def test_mixed_prefers_arabic(self):
        self.assertEqual(wu.detect_language("Hello مرحبا"), "ar")

    def test_undetectable(self):
        for raw in ("", "   ", "12345", "👍", None):
            with self.subTest(raw=raw):
                self.assertEqual(wu.detect_language(raw), "")


class TestIsBusinessHours(unittest.TestCase):
    def test_inside_window(self):
        self.assertTrue(wu.is_business_hours(_on("Wed", 10), settings=_WORK_WEEK))

    def test_start_boundary_is_inclusive(self):
        self.assertTrue(wu.is_business_hours(_on("Wed", 9, 0, 0), settings=_WORK_WEEK))
        self.assertFalse(wu.is_business_hours(_on("Wed", 8, 59, 59), settings=_WORK_WEEK))

    def test_end_boundary_is_exclusive(self):
        self.assertTrue(wu.is_business_hours(_on("Wed", 16, 59, 59), settings=_WORK_WEEK))
        self.assertFalse(wu.is_business_hours(_on("Wed", 17, 0, 0), settings=_WORK_WEEK))

    def test_midnight_is_out_of_hours(self):
        self.assertFalse(wu.is_business_hours(_on("Wed", 0, 0, 0), settings=_WORK_WEEK))
        self.assertFalse(wu.is_business_hours(_on("Wed", 23, 59, 59), settings=_WORK_WEEK))

    def test_weekend_day_is_out_of_hours(self):
        self.assertFalse(wu.is_business_hours(_on("Fri", 10), settings=_WORK_WEEK))
        self.assertFalse(wu.is_business_hours(_on("Sat", 10), settings=_WORK_WEEK))
        self.assertTrue(wu.is_business_hours(_on("Sun", 10), settings=_WORK_WEEK))

    def test_overnight_window_wraps(self):
        night = {
            "business_days": "Sun,Mon,Tue,Wed,Thu",
            "business_hours_start": "18:00:00",
            "business_hours_end": "02:00:00",
        }
        self.assertTrue(wu.is_business_hours(_on("Wed", 23), settings=night))
        self.assertTrue(wu.is_business_hours(_on("Wed", 1), settings=night))
        self.assertFalse(wu.is_business_hours(_on("Wed", 12), settings=night))

    def test_unconfigured_window_is_always_open(self):
        # Better to send no out-of-hours reply than to send one all day.
        self.assertTrue(wu.is_business_hours(_on("Wed", 3), settings={}))

    def test_timedelta_times_from_frappe(self):
        # Frappe Time fields deserialize as timedelta, not "HH:MM:SS".
        settings = {
            "business_days": "Sun,Mon,Tue,Wed,Thu",
            "business_hours_start": timedelta(hours=9),
            "business_hours_end": timedelta(hours=17),
        }
        self.assertTrue(wu.is_business_hours(_on("Wed", 10), settings=settings))
        self.assertFalse(wu.is_business_hours(_on("Wed", 18), settings=settings))


class TestNormalizeBody(unittest.TestCase):
    def test_plain_text(self):
        doc = {"content_type": "text", "message": "Hello there"}
        self.assertEqual(wu.normalize_body(doc), "Hello there")

    def test_html_is_stripped(self):
        doc = {"content_type": "text", "message": "<p>Hello</p><p>world</p>"}
        self.assertEqual(wu.normalize_body(doc), "Hello\nworld")

    def test_media_labels(self):
        cases = [
            ("image", "\U0001F4F7 Photo"),
            ("document", "\U0001F4C4 Document"),
            ("audio", "\U0001F3A4 Voice note"),
            ("video", "\U0001F3AC Video"),
            ("sticker", "\U0001F9E9 Sticker"),
        ]
        for content_type, label in cases:
            with self.subTest(content_type=content_type):
                doc = {
                    "content_type": content_type,
                    "message": "",
                    "attach": "/files/x.bin",
                }
                self.assertEqual(wu.normalize_body(doc), label)

    def test_media_with_caption(self):
        doc = {
            "content_type": "image",
            "message": "Invoice photo",
            "attach": "/files/x.jpg",
        }
        self.assertEqual(wu.normalize_body(doc), "\U0001F4F7 Photo — Invoice photo")

    def test_dict_repr_becomes_marker(self):
        doc = {"content_type": "location", "message": "{'latitude': 33.3, 'longitude': 44.3}"}
        self.assertEqual(wu.normalize_body(doc), "[unsupported message]")

    def test_truncates(self):
        doc = {"content_type": "text", "message": "x" * 2000}
        self.assertEqual(len(wu.normalize_body(doc, max_length=100)), 100)


class TestTemplateHelpers(unittest.TestCase):
    def test_render_from_dict(self):
        self.assertEqual(
            wu.render_template_body("Hi {{1}}, your order {{2}} shipped", {"1": "Ali", "2": "SO-9"}),
            "Hi Ali, your order SO-9 shipped",
        )

    def test_render_from_list_and_json(self):
        self.assertEqual(wu.render_template_body("Hi {{1}}", ["Ali"]), "Hi Ali")
        self.assertEqual(wu.render_template_body("Hi {{1}}", '["Ali"]'), "Hi Ali")

    def test_missing_params_left_intact(self):
        self.assertEqual(wu.render_template_body("Hi {{1}} {{2}}", ["Ali"]), "Hi Ali {{2}}")

    def test_param_count(self):
        self.assertEqual(wu.count_template_params("Hi {{1}}, ref {{2}}, total {{3}}"), 3)
        self.assertEqual(wu.count_template_params("No placeholders"), 0)
        self.assertEqual(wu.count_template_params(None), 0)


class TestStripHtml(unittest.TestCase):
    def test_preserves_word_boundaries(self):
        self.assertEqual(wu.strip_html("<b>Hello</b><i>world</i>"), "Hello world")

    def test_unescapes_entities(self):
        self.assertEqual(wu.strip_html("Tom &amp; Jerry"), "Tom & Jerry")

    def test_br_becomes_newline(self):
        self.assertEqual(wu.strip_html("a<br>b"), "a\nb")


if __name__ == "__main__":
    unittest.main(verbosity=2)

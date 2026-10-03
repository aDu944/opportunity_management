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

    def test_weekday_evening_is_out_of_hours(self):
        self.assertFalse(wu.is_business_hours(_on("Wed", 21, 45), settings=_WORK_WEEK))
        self.assertTrue(wu.is_business_hours(_on("Wed", 10), settings=_WORK_WEEK))

    def test_nowtime_artefact_is_always_open(self):
        # Frappe stamps `nowtime()` into a fresh Single's Time fields; a pair
        # microseconds apart is no window at all, never a zero-length one.
        garbage = {
            "business_days": "Sun,Mon,Tue,Wed,Thu",
            "business_hours_start": "17:26:35.827006",
            "business_hours_end": "17:26:35.827074",
        }
        self.assertTrue(wu.is_business_hours(_on("Wed", 21, 45), settings=garbage))
        self.assertTrue(wu.is_business_hours(_on("Wed", 17, 26, 35), settings=garbage))
        near = dict(garbage, business_hours_end=timedelta(hours=17, minutes=27, seconds=20))
        self.assertTrue(wu.is_business_hours(_on("Wed", 3), settings=near))


_SAT_THU = {
    "business_days": "Sat,Sun,Mon,Tue,Wed,Thu",
    "business_hours_start": "09:00:00",
    "business_hours_end": "16:00:00",
}


class TestSatThuWindow(unittest.TestCase):
    def test_weekday_after_four_is_out_of_hours(self):
        self.assertFalse(wu.is_business_hours(_on("Wed", 16, 30), settings=_SAT_THU))
        self.assertTrue(wu.is_business_hours(_on("Wed", 15, 59, 59), settings=_SAT_THU))

    def test_saturday_morning_is_in_hours(self):
        self.assertTrue(wu.is_business_hours(_on("Sat", 10), settings=_SAT_THU))
        self.assertFalse(wu.is_business_hours(_on("Fri", 10), settings=_SAT_THU))


class TestBusinessHoursLabel(unittest.TestCase):
    def test_contiguous_run_en(self):
        self.assertEqual(wu.business_hours_label(_SAT_THU, "en"), "Sat–Thu, 9:00 AM – 4:00 PM")

    def test_contiguous_run_ar(self):
        self.assertEqual(
            wu.business_hours_label(_SAT_THU, "ar"), "السبت–الخميس، 9:00 ص – 4:00 م"
        )

    def test_day_order_starts_saturday_regardless_of_input_order(self):
        settings = dict(_SAT_THU, business_days="Thu, wed,TUE,Mon,Sun,Sat")
        self.assertEqual(wu.business_hours_label(settings, "en"), "Sat–Thu, 9:00 AM – 4:00 PM")

    def test_non_contiguous_days(self):
        settings = dict(_SAT_THU, business_days="Sun,Tue,Thu")
        self.assertEqual(wu.business_hours_label(settings, "en"), "Sun, Tue, Thu, 9:00 AM – 4:00 PM")
        self.assertEqual(
            wu.business_hours_label(settings, "ar"),
            "الأحد، الثلاثاء، الخميس، 9:00 ص – 4:00 م",
        )

    def test_mixed_runs(self):
        settings = dict(_SAT_THU, business_days="Sat,Sun,Mon,Wed,Thu")
        self.assertEqual(wu.business_hours_label(settings, "en"), "Sat–Mon, Wed–Thu, 9:00 AM – 4:00 PM")

    def test_single_day(self):
        settings = dict(_SAT_THU, business_days="Fri")
        self.assertEqual(wu.business_hours_label(settings, "en"), "Fri, 9:00 AM – 4:00 PM")
        self.assertEqual(wu.business_hours_label(settings, "ar"), "الجمعة، 9:00 ص – 4:00 م")

    def test_noon_midnight_and_minutes(self):
        settings = {
            "business_days": "Sat",
            "business_hours_start": "12:00:00",
            "business_hours_end": "00:30:00",
        }
        self.assertEqual(wu.business_hours_label(settings, "en"), "Sat, 12:00 PM – 12:30 AM")
        self.assertEqual(wu.business_hours_label(settings, "ar"), "السبت، 12:00 م – 12:30 ص")

    def test_afternoon_and_timedelta(self):
        settings = {
            "business_days": "Mon",
            "business_hours_start": timedelta(hours=13, minutes=5),
            "business_hours_end": timedelta(hours=23, minutes=45),
        }
        self.assertEqual(wu.business_hours_label(settings, "en"), "Mon, 1:05 PM – 11:45 PM")

    def test_unset_window_or_days(self):
        garbage = dict(_SAT_THU, business_hours_start="17:26:35", business_hours_end="17:26:35")
        self.assertEqual(wu.business_hours_label(garbage, "en"), "Sat–Thu")
        no_days = dict(_SAT_THU, business_days="")
        self.assertEqual(wu.business_hours_label(no_days, "en"), "9:00 AM – 4:00 PM")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(wu.business_hours_label(_SAT_THU, None), "Sat–Thu, 9:00 AM – 4:00 PM")
        self.assertEqual(wu.business_hours_label(_SAT_THU, "AR"), "السبت–الخميس، 9:00 ص – 4:00 م")

    def test_clock_12h(self):
        for value, en, ar in (
            ("00:00:00", "12:00 AM", "12:00 ص"),
            ("09:00:00", "9:00 AM", "9:00 ص"),
            ("12:00:00", "12:00 PM", "12:00 م"),
            ("16:00:00", "4:00 PM", "4:00 م"),
            ("23:59:00", "11:59 PM", "11:59 م"),
        ):
            with self.subTest(value=value):
                self.assertEqual(wu.clock_12h(value, "en"), en)
                self.assertEqual(wu.clock_12h(value, "ar"), ar)


class TestBusinessWindowUnset(unittest.TestCase):
    def test_unset_pairs(self):
        for start, end in (
            (None, None),
            ("", "17:00:00"),
            ("09:00:00", None),
            ("17:26:35.827006", "17:26:35.827074"),
            ("10:00:00", "10:00:59"),
            (timedelta(hours=9), timedelta(hours=9, seconds=30)),
        ):
            with self.subTest(start=start, end=end):
                self.assertTrue(wu.business_window_unset(start, end))

    def test_real_windows(self):
        for start, end in (
            ("09:00:00", "17:00:00"),
            ("18:00:00", "02:00:00"),
            ("10:00:00", "10:01:00"),
            (timedelta(hours=9), timedelta(hours=17)),
        ):
            with self.subTest(start=start, end=end):
                self.assertFalse(wu.business_window_unset(start, end))


class TestReplyLanguage(unittest.TestCase):
    SETTINGS = {"default_country_code": "964", "default_language": "en"}

    def test_detected_language_wins(self):
        self.assertEqual(wu.reply_language("en", "9647701234567", self.SETTINGS), "en")
        self.assertEqual(wu.reply_language("AR", "14155552671", self.SETTINGS), "ar")

    def test_home_country_guesses_arabic(self):
        for phone in ("9647701234567", "+964 770 123 4567", "07701234567"):
            with self.subTest(phone=phone):
                self.assertEqual(wu.reply_language("", phone, self.SETTINGS), "ar")
        self.assertEqual(wu.reply_language(None, "9647701234567", self.SETTINGS), "ar")

    def test_foreign_number_uses_default_language(self):
        self.assertEqual(wu.reply_language("", "14155552671", self.SETTINGS), "en")
        settings = dict(self.SETTINGS, default_language="ar")
        self.assertEqual(wu.reply_language("", "14155552671", settings), "ar")

    def test_no_country_code_configured(self):
        settings = {"default_country_code": "", "default_language": ""}
        self.assertEqual(wu.reply_language("", "9647701234567", settings), "en")
        self.assertEqual(wu.reply_language("", "", {}), "en")


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

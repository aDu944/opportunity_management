"""
Bench-free tests for the pure pieces of the reactions / template-language /
voice-note work:

    whatsapp_template_picker.pick_default / order_templates
    whatsapp_reactions.latest_reactions
    whatsapp_audio.needs_transcode
    whatsapp_audio.failure_action / cron_should_try / stderr_tail / m4a_args

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_inbox_pure.py

Like the other bench-free tests, a stub `frappe` is injected when none is
importable and each module is loaded straight off disk.
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
    stub.flags = {}
    stub.get_doc = _no_bench
    stub.get_all = _no_bench
    stub.db = types.SimpleNamespace(get_value=_no_bench, exists=_no_bench)
    sys.modules["frappe"] = stub


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_frappe_stub()
picker = _load("_wa_picker_under_test", "whatsapp_template_picker.py")
reactions = _load("_wa_reactions_under_test", "whatsapp_reactions.py")
audio = _load("_wa_audio_under_test", "whatsapp_audio.py")


def _t(name, template_name, code):
    return {"name": name, "template_name": template_name, "language_code": code}


ROWS = [
    _t("follow_up-ar", "follow_up", "ar"),
    _t("follow_up_en-en", "follow_up_en", "en"),
    _t("follow_up_reply-ar", "follow_up_reply", "ar"),
    _t("follow_up_reply_en-en", "follow_up_reply_en", "en_US"),
    _t("promo_ar-ar", "promo_ar", "ar"),
]


class TestPickDefault(unittest.TestCase):
    def test_english_customer_gets_the_english_counterpart(self):
        self.assertEqual(picker.pick_default(ROWS, "follow_up-ar", "en"), "follow_up_en-en")

    def test_arabic_customer_keeps_the_configured_default(self):
        self.assertEqual(picker.pick_default(ROWS, "follow_up-ar", "ar"), "follow_up-ar")

    def test_no_counterpart_falls_to_first_in_language(self):
        # promo_ar has no English twin → first English template alphabetically.
        self.assertEqual(picker.pick_default(ROWS, "promo_ar-ar", "en"), "follow_up_en-en")

    def test_language_without_templates_keeps_the_configured_default(self):
        self.assertEqual(picker.pick_default(ROWS, "follow_up-ar", "fr"), "follow_up-ar")

    def test_empty_list(self):
        self.assertEqual(picker.pick_default([], "follow_up-ar", "en"), "")

    def test_no_configured_default(self):
        self.assertEqual(picker.pick_default(ROWS, "", "en"), "follow_up_en-en")
        self.assertEqual(picker.pick_default(ROWS, "", "fr"), "follow_up-ar")

    def test_region_codes_and_base_names(self):
        self.assertEqual(picker.lang_of("en_US"), "en")
        self.assertEqual(picker.lang_of("pt-BR"), "pt")
        self.assertEqual(picker.base_name(ROWS[3]), "follow_up_reply")
        self.assertEqual(picker.pick_default(ROWS, "follow_up_reply-ar", "en"), "follow_up_reply_en-en")

    def test_order_templates(self):
        rows = [dict(r, default=1 if r["name"] == "follow_up-ar" else 0) for r in ROWS]
        out = picker.order_templates(rows, "follow_up-ar", "en")
        self.assertEqual([r["name"] for r in out][:2], ["follow_up_en-en", "follow_up_reply_en-en"])
        self.assertEqual(sum(r["default"] for r in out), 1)
        self.assertEqual(out[0]["default"], 1)
        self.assertEqual({r["language"] for r in out}, {"ar", "en"})
        # Without a customer language: unchanged default, default first.
        rows = [dict(r, default=1 if r["name"] == "promo_ar-ar" else 0) for r in ROWS]
        self.assertEqual(picker.order_templates(rows, "promo_ar-ar")[0]["name"], "promo_ar-ar")


def _r(name, creation, direction, emoji, target="wamid.A", by=None):
    return {
        "name": name,
        "creation": creation,
        "type": "Incoming" if direction == "in" else "Outgoing",
        "message": emoji,
        "reply_to_message_id": target,
        "custom_sent_by": by,
    }


class TestLatestReactions(unittest.TestCase):
    def test_latest_per_side_and_removal(self):
        rows = [
            _r("m3", "2026-10-01 10:02", "in", "❤️"),
            _r("m1", "2026-10-01 10:00", "in", "👍"),
            _r("m2", "2026-10-01 10:01", "out", "🙏", by="a@x.com"),
            _r("m4", "2026-10-01 10:00", "in", "😂", target="wamid.B"),
            _r("m5", "2026-10-01 10:05", "in", "", target="wamid.B"),  # removed
        ]
        out = reactions.latest_reactions(rows, {"a@x.com": "Agent A"})
        self.assertEqual(
            out["wamid.A"],
            [
                {"emoji": "❤️", "direction": "in", "by": None, "by_name": ""},
                {"emoji": "🙏", "direction": "out", "by": "a@x.com", "by_name": "Agent A"},
            ],
        )
        self.assertEqual(out["wamid.B"], [])

    def test_html_wrapped_emoji_and_empty(self):
        out = reactions.latest_reactions([_r("m1", "1", "out", "<p>👍</p>", by="b@x.com")])
        self.assertEqual(out["wamid.A"][0]["emoji"], "👍")
        self.assertEqual(out["wamid.A"][0]["by_name"], "b@x.com")
        self.assertEqual(reactions.latest_reactions([]), {})

    def test_legacy_key(self):
        item = {}
        reactions.set_item_reactions(item, [{"emoji": "👍", "direction": "in", "by": None, "by_name": ""}])
        self.assertEqual(item["reaction"], "👍")
        reactions.set_item_reactions(item, [])
        self.assertEqual((item["reaction"], item["reactions"]), ("", []))


class TestNeedsTranscode(unittest.TestCase):
    def test_table(self):
        cases = [
            ("/files/a.ogg", True),
            ("/private/files/A.OGA", True),
            ("/files/x.opus", True),
            ("/files/v.ogg; codecs=opus", True),
            ("/files/v.ogg%3B%20codecs%3Dopus", True),
            ("/files/a.ogg?fid=1", True),
            ("/files/a.m4a", False),
            ("/files/a.mp3", False),
            ("", False),
            (None, False),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(audio.needs_transcode(url), expected)


class TestTranscodeBackoff(unittest.TestCase):
    def test_missing_source_is_always_a_plain_retry(self):
        for attempts in (0, 1, audio.MAX_ATTEMPTS, 99):
            self.assertEqual(audio.failure_action(attempts, audio.MISSING), audio.RETRY)

    def test_ffmpeg_failures_back_off_then_give_up(self):
        for attempts in range(1, audio.MAX_ATTEMPTS):
            self.assertEqual(audio.failure_action(attempts, audio.FFMPEG), audio.BACKOFF)
        self.assertEqual(audio.failure_action(audio.MAX_ATTEMPTS, audio.FFMPEG), audio.GIVE_UP)
        self.assertEqual(audio.failure_action(audio.MAX_ATTEMPTS + 1, audio.FFMPEG), audio.GIVE_UP)
        self.assertEqual(audio.failure_action(None, audio.FFMPEG), audio.BACKOFF)

    def test_limits(self):
        self.assertEqual(audio.FAILURE_BACKOFF, 30 * 60)
        self.assertEqual(audio.MAX_ATTEMPTS, 6)
        self.assertEqual(audio.ATTEMPTS_TTL, 24 * 60 * 60)

    def test_cron_should_try(self):
        self.assertTrue(audio.cron_should_try(0, False))
        self.assertTrue(audio.cron_should_try(None, False))
        self.assertTrue(audio.cron_should_try(audio.MAX_ATTEMPTS - 1, False))
        self.assertFalse(audio.cron_should_try(1, True))
        self.assertFalse(audio.cron_should_try(audio.MAX_ATTEMPTS, False))

    def test_stderr_tail(self):
        self.assertEqual(audio.stderr_tail(None), "")
        self.assertEqual(audio.stderr_tail(b""), "")
        self.assertEqual(audio.stderr_tail(b"  No such file\n"), "No such file")
        long = "x" * 600 + "END"
        self.assertEqual(len(audio.stderr_tail(long)), 500)
        self.assertTrue(audio.stderr_tail(long).endswith("END"))
        self.assertEqual(audio.stderr_tail(b"\xff ok"), "� ok")

    def test_m4a_args(self):
        self.assertEqual(
            audio.m4a_args("/usr/bin/ffmpeg", "/abs/in.ogg", "out.m4a"),
            ["/usr/bin/ffmpeg", "-nostdin", "-y", "-i", "/abs/in.ogg", "-vn", "-ac", "1",
             "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", "out.m4a"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

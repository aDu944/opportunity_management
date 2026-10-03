"""
Bench-free tests for the round-3 WhatsApp inbox helpers:

    whatsapp_payloads        options, location / contact / voice / typing /
                             block bodies, Meta errors, status fields,
                             `around` maths, ThreadItem decoration
    whatsapp_chat_state      the pin-first list ordering fragments
    whatsapp_audio           the Ogg/Opus voice-note ffmpeg arguments
    whatsapp_message_override  pass-through vs. the inbox send path

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_round3_pure.py

A stub `frappe` (and a stub `frappe_whatsapp` upstream controller) is
injected when none is importable; each module is loaded straight off disk.
"""

import importlib.util
import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _install_stubs():
    if "frappe" not in sys.modules:

        def _no_bench(*args, **kwargs):
            raise RuntimeError("no bench available in this test run")

        def _throw(msg, *args, **kwargs):
            raise RuntimeError(msg)

        stub = types.ModuleType("frappe")
        stub._dict = dict
        stub.local = types.SimpleNamespace()
        stub.flags = {}
        stub.get_doc = _no_bench
        stub.get_all = _no_bench
        stub.throw = _throw
        stub.db = types.SimpleNamespace(get_value=_no_bench, exists=_no_bench)
        utils = types.ModuleType("frappe.utils")
        utils.cint = lambda v: int(float(v or 0)) if str(v or "0").strip() else 0
        utils.get_url = lambda uri=None: "https://erp.example" + (uri or "")
        stub.utils = utils
        sys.modules["frappe"] = stub
        sys.modules["frappe.utils"] = utils

    if "frappe_whatsapp" not in sys.modules:
        names = [
            "frappe_whatsapp",
            "frappe_whatsapp.frappe_whatsapp",
            "frappe_whatsapp.frappe_whatsapp.doctype",
            "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message",
            "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message",
            "frappe_whatsapp.utils",
        ]
        for name in names:
            sys.modules[name] = types.ModuleType(name)
        upstream = sys.modules[names[4]]
        sys.modules[names[3]].whatsapp_message = upstream

        class Upstream:
            def __init__(self, **fields):
                self.__dict__.update(fields)
                self.sent = []
                self.upstream_called = False

            def get(self, key, default=None):
                return self.__dict__.get(key, default)

            def send_outgoing(self):
                self.upstream_called = True

            def notify(self, data):
                self.sent.append(data)
                self.message_id = "wamid.OUT"

        def apply_recipient(data):
            to = data.get("to") or ""
            if to[:2].isalpha() and "." in to:
                data["recipient"] = data.pop("to")
                data["recipient_type"] = "individual"
            return data

        upstream.WhatsAppMessage = Upstream
        upstream.apply_recipient = apply_recipient
        sys.modules["frappe_whatsapp.utils"].format_number = lambda n: str(n).lstrip("+")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_stubs()
P = _load("opportunity_management.opportunity_management.whatsapp_payloads", "whatsapp_payloads.py")
CS = _load("_wa_chat_state_under_test", "whatsapp_chat_state.py")
audio = _load("_wa_audio_round3_under_test", "whatsapp_audio.py")
override = _load("_wa_override_under_test", "whatsapp_message_override.py")


class TestOptions(unittest.TestCase):
    def test_parses_json_and_trims(self):
        self.assertEqual(P.parse_options('[" Yes ", "No"]'), ["Yes", "No"])

    def test_rejects_bad_counts_lengths_and_duplicates(self):
        for bad in ("[]", json.dumps([str(i) for i in range(11)]), '["x" ]'.replace("x", "a" * 21),
                    '["Yes", "yes"]', '["ok", ""]', "not json", "{}"):
            with self.assertRaises(P.PayloadError, msg=bad):
                P.parse_options(bad)

    def test_twenty_chars_is_allowed(self):
        self.assertEqual(P.parse_options(["a" * 20]), ["a" * 20])

    def test_body_limits_depend_on_button_or_list(self):
        self.assertEqual(P.check_options_body(" Pick ", 3), "Pick")
        with self.assertRaises(P.PayloadError):
            P.check_options_body("x" * 1025, 3)
        self.assertEqual(len(P.check_options_body("x" * 1025, 4)), 1025)
        with self.assertRaises(P.PayloadError):
            P.check_options_body("", 2)

    def test_buttons_shape_and_titles_round_trip(self):
        buttons = P.option_buttons(["Yes", "No"])
        self.assertEqual(buttons, [{"id": "opt_1", "title": "Yes"}, {"id": "opt_2", "title": "No"}])
        self.assertEqual(P.option_titles(json.dumps(buttons)), ["Yes", "No"])
        self.assertIsNone(P.option_titles("garbage"))


class TestBodies(unittest.TestCase):
    def test_location_body(self):
        card = P.location_card("33.3", 44.4, " Office ", None)
        self.assertEqual(
            P.message_body("location", "9647701234567", {"location": card}, reply_to="wamid.Q"),
            {
                "messaging_product": "whatsapp",
                "to": "9647701234567",
                "type": "location",
                "location": {"latitude": 33.3, "longitude": 44.4, "name": "Office"},
                "context": {"message_id": "wamid.Q"},
            },
        )

    def test_location_validation(self):
        for lat, lng in (("x", 1), (91, 0), (0, 181)):
            with self.assertRaises(P.PayloadError):
                P.location_card(lat, lng)

    def test_contact_body(self):
        card = P.contact_card("Ali Hassan", "+964 770 123 4567")
        self.assertEqual(
            P.message_body("contact", "9647700000000", {"contacts": [card]}),
            {
                "messaging_product": "whatsapp",
                "to": "9647700000000",
                "type": "contacts",
                "contacts": [
                    {
                        "name": {"formatted_name": "Ali Hassan", "first_name": "Ali Hassan"},
                        "phones": [{"phone": "+9647701234567", "type": "CELL", "wa_id": "9647701234567"}],
                    }
                ],
            },
        )
        with self.assertRaises(P.PayloadError):
            P.contact_card("", "123456")
        with self.assertRaises(P.PayloadError):
            P.contact_card("Ali", "12")

    def test_voice_body_with_and_without_flag(self):
        link = "https://erp.example/files/v.ogg"
        self.assertEqual(
            P.message_body("voice", "964", {"voice": True}, link=link),
            {"messaging_product": "whatsapp", "to": "964", "type": "audio",
             "audio": {"link": link, "voice": True}},
        )
        self.assertEqual(P.message_body("voice", "964", {"voice": False}, link=link)["audio"], {"link": link})

    def test_typing_body(self):
        self.assertEqual(
            P.typing_body("wamid.IN"),
            {"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.IN",
             "typing_indicator": {"type": "text"}},
        )

    def test_block_body(self):
        self.assertEqual(
            P.block_body("9647701234567"),
            {"messaging_product": "whatsapp", "block_users": [{"user": "+9647701234567"}]},
        )
        self.assertEqual(P.block_body("IQ.4719688614983810")["block_users"][0]["user"], "IQ.4719688614983810")

    def test_custom_kind_needs_marker_and_type(self):
        self.assertEqual(P.custom_kind("location", 0, {"kind": "location"}), "location")
        self.assertEqual(P.custom_kind("contact", 0, {"kind": "contact"}), "contact")
        self.assertEqual(P.custom_kind("audio", 1, {"kind": "voice"}), "voice")
        self.assertEqual(P.custom_kind("audio", 0, {"kind": "voice"}), "")
        self.assertEqual(P.custom_kind("text", 0, {"kind": "location"}), "")
        self.assertEqual(P.custom_kind("location", 0, {}), "")


class TestInboundAndErrors(unittest.TestCase):
    def test_inbound_contacts_to_cards(self):
        cards = P.contacts_from_meta([
            {"name": {"formatted_name": "Sara"}, "phones": [{"phone": "+1 555", "wa_id": "1555"}],
             "emails": [{"email": "s@x.io"}], "org": {"company": "ACME"}},
            "junk",
        ])
        self.assertEqual(cards, [{"name": "Sara", "phones": ["+1 555"], "emails": ["s@x.io"], "org": "ACME"}])

    def test_inbound_location_is_tolerant(self):
        self.assertEqual(
            P.location_from_meta({"latitude": "1.5", "longitude": None}),
            {"latitude": 1.5, "longitude": None, "name": "", "address": ""},
        )

    def test_block_partial_failure_message(self):
        payload = {"block_users": {"failed_users": [{"errors": [{"code": 131047}]}]},
                   "error": {"code": 139100, "message": "(#139100) Failed"}}
        self.assertIn("24 hours", P.error_message(payload))
        self.assertEqual(
            P.error_message({"error": {"code": 100, "message": "Bad", "error_data": {"details": "why"}}}),
            "(100) Bad — why",
        )

    def test_status_failure_reason(self):
        payload = {"entry": [{"changes": [{"value": {"statuses": [
            {"id": "other", "status": "failed", "errors": [{"code": 1, "title": "x"}]},
            {"id": "wamid.A", "status": "failed", "errors": [
                {"code": 131049, "title": "Not delivered", "message": "Not delivered",
                 "error_data": {"details": "ecosystem"}}]},
        ]}}]}]}
        self.assertEqual(P.status_failure(payload, "wamid.A"), "(131049) Not delivered — ecosystem")
        self.assertEqual(P.status_failure({}, "wamid.A"), "")

    def test_status_fields(self):
        self.assertEqual(P.status_field("Delivered"), "custom_delivered_at")
        self.assertEqual(P.status_field("read"), "custom_read_at")
        self.assertEqual(P.status_field("sent"), "custom_sent_at")
        self.assertEqual(P.status_field("failed"), "")
        self.assertEqual(P.status_field("Success"), "")


class TestPagingOrderingAndDecoration(unittest.TestCase):
    def test_around_split(self):
        self.assertEqual(P.around_split(40), (20, 20))
        self.assertEqual(P.around_split(41), (21, 20))
        self.assertEqual(P.around_split(1), (1, 1))

    def test_pin_first_order(self):
        select, join, order = CS.list_sql(True)
        self.assertTrue(order.startswith("COALESCE(s.pinned, 0) DESC, c.last_message_at DESC"))
        self.assertIn("%(state_user)s", join)
        self.assertIn("AS pinned", select)
        self.assertNotIn("%", select + order)  # no literal % to double
        select, join, order = CS.list_sql(False)
        self.assertEqual((join, order), ("", "c.last_message_at DESC, c.modified DESC"))

    def test_decorate_location_row(self):
        row = {"custom_payload": json.dumps({"kind": "location", "location": {"latitude": 1.0}}),
               "custom_read_at": "2026-10-03 10:00:00.123456", "custom_error": ""}
        item = P.decorate_item({"content_type": "text"}, row.get)
        self.assertEqual(item["content_type"], "location")
        self.assertEqual(item["location"], {"latitude": 1.0})
        self.assertEqual(item["read_at"], "2026-10-03 10:00:00")
        self.assertIsNone(item["error"])
        self.assertFalse(item["is_voice"])

    def test_decorate_interactive_and_voice(self):
        row = {"buttons": json.dumps([{"id": "opt_1", "title": "Yes"}]), "custom_is_voice": 1}
        item = P.decorate_item({"content_type": "interactive"}, row.get)
        self.assertEqual(item["options"], ["Yes"])
        self.assertTrue(item["is_voice"])


class TestVoiceArgs(unittest.TestCase):
    def test_ogg_opus_mono(self):
        self.assertEqual(
            audio.voice_ogg_args("ffmpeg", "in.m4a", "out.ogg"),
            ["ffmpeg", "-nostdin", "-y", "-i", "in.m4a", "-vn", "-c:a", "libopus",
             "-b:a", "32k", "-ac", "1", "-ar", "48000", "out.ogg"],
        )


class TestOverride(unittest.TestCase):
    def _doc(self, **fields):
        base = {"type": "Outgoing", "template": None, "message_type": "Manual", "to": "+9647701234567",
                "is_reply": 0, "reply_to_message_id": None, "attach": None, "custom_is_voice": 0,
                "custom_payload": None, "content_type": "text"}
        base.update(fields)
        return override.WhatsAppMessage(**base)

    def test_plain_rows_pass_through(self):
        for fields in ({}, {"content_type": "image", "attach": "/files/a.jpg"},
                       {"content_type": "audio", "attach": "/files/a.ogg"},
                       {"content_type": "location"},  # no marker
                       {"template": "t1", "content_type": "location",
                        "custom_payload": json.dumps({"kind": "location"})}):
            doc = self._doc(**fields)
            doc.send_outgoing()
            self.assertTrue(doc.upstream_called, fields)
            self.assertEqual(doc.sent, [])

    def test_location_goes_through_inbox_path(self):
        card = P.location_card(1, 2, "HQ")
        doc = self._doc(content_type="location", is_reply=1, reply_to_message_id="wamid.R",
                        custom_payload=json.dumps({"kind": "location", "location": card}))
        doc.send_outgoing()
        self.assertFalse(doc.upstream_called)
        self.assertEqual(doc.status, "Success")
        self.assertEqual(doc.sent, [{
            "messaging_product": "whatsapp", "to": "9647701234567", "type": "location",
            "location": {"latitude": 1.0, "longitude": 2.0, "name": "HQ"},
            "context": {"message_id": "wamid.R"},
        }])

    def test_voice_to_bsuid_uses_recipient(self):
        doc = self._doc(content_type="audio", custom_is_voice=1, to="IQ.4719688614983810",
                        attach="/files/v.ogg", custom_payload=json.dumps({"kind": "voice", "voice": True}))
        doc.send_outgoing()
        self.assertEqual(doc.sent[0]["recipient"], "IQ.4719688614983810")
        self.assertNotIn("to", doc.sent[0])
        self.assertEqual(doc.sent[0]["audio"], {"link": "https://erp.example/files/v.ogg", "voice": True})


if __name__ == "__main__":
    unittest.main(verbosity=1)

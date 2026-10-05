"""
Bench-free tests for replies sent from another Meta app on the number
(`external_replies`) and the override's no-send guard:

    placeholder rule (status × category × recipient × own send), the row
    builder, timestamp sanity, conversation bookkeeping, the echo parser,
    the placeholder → echo upgrade rule, ThreadItem `external` flags,
    `WhatsAppMessage.before_insert` / `send_outgoing` for store-only rows.

    python3 opportunity_management/opportunity_management/tests/test_external_replies_pure.py

A stub `frappe` (and a stub `frappe_whatsapp` upstream controller) is
injected when none is importable; each module is loaded straight off disk.
"""

import importlib.util
import json
import os
import sys
import types
import unittest
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG = "opportunity_management.opportunity_management."


class _Cache:
    def __init__(self):
        self.store = {}

    def set_value(self, key, value, expires_in_sec=None):
        self.store[key] = value

    def get_value(self, key):
        return self.store.get(key)


def _install_stubs():
    if "frappe" not in sys.modules:

        def _no_bench(*args, **kwargs):
            raise RuntimeError("no bench available in this test run")

        stub = types.ModuleType("frappe")
        stub._dict = dict
        stub.local = types.SimpleNamespace()
        stub.flags = {}
        stub.get_doc = _no_bench
        stub.get_all = _no_bench
        stub.db = types.SimpleNamespace(get_value=_no_bench, exists=_no_bench)
        utils = types.ModuleType("frappe.utils")
        utils.cint = lambda v: int(float(v or 0)) if str(v or "0").strip() else 0
        utils.get_datetime = lambda v: v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
        utils.get_url = lambda uri=None: "https://erp.example" + (uri or "")
        utils.now_datetime = datetime.now
        stub.utils = utils
        sys.modules["frappe"] = stub
        sys.modules["frappe.utils"] = utils
    cache = _Cache()
    sys.modules["frappe"].cache = lambda: cache

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
                self.calls = []

            def get(self, key, default=None):
                return self.__dict__.get(key, default)

            def before_insert(self):
                self.calls.append("before_insert")
                self.send_outgoing()

            def send_outgoing(self):
                self.calls.append("upstream_send")
                self.message_id = "wamid.OURS"

        upstream.WhatsAppMessage = Upstream
        sys.modules["frappe_whatsapp.utils"].format_number = lambda n: str(n).lstrip("+")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_stubs()
P = _load(_PKG + "whatsapp_payloads", "whatsapp_payloads.py")
ER = _load(_PKG + "external_replies", "external_replies.py")
override = _load("_wa_override_external_under_test", "whatsapp_message_override.py")

NOW = datetime(2026, 10, 5, 12, 0, 0)
NOW_EPOCH = 1_791_000_000


def _status(status="sent", category="service", **extra):
    out = {"id": "wamid.PBX", "status": status, "timestamp": str(NOW_EPOCH - 5),
           "recipient_id": "9647701234567", "recipient_user_id": "IQ.1106000000000000"}
    if category is not None:
        out["pricing"] = {"billable": False, "pricing_model": "PMP", "category": category,
                          "type": "free_customer_service"}
    out.update(extra)
    return out


CONV = {"name": "WAC-1", "phone": "9647701234567", "whatsapp_account": "ALKHORA WA"}


class TestPlaceholderRule(unittest.TestCase):
    def test_matrix(self):
        for status in ("sent", "delivered", "read", "failed", "deleted"):
            for category in ("service", "utility", "marketing", "authentication", None):
                for conv in (CONV, None):
                    for known in (False, True):
                        want = (status in ("sent", "delivered", "read") and category != "authentication"
                                and conv is not None and not known)
                        got = ER.should_record(_status(status, category), known, conv)
                        self.assertEqual(got, want, (status, category, bool(conv), known))

    def test_own_send_never_a_placeholder(self):
        self.assertFalse(ER.should_record(_status(), False, CONV, own=True))

    def test_old_shape_category_from_conversation_origin(self):
        st = _status(category=None, conversation={"id": "c", "origin": {"type": "authentication"}})
        self.assertEqual(ER.status_category(st), "authentication")
        self.assertFalse(ER.is_staff_reply_status(st))
        self.assertTrue(ER.is_staff_reply_status(_status(category=None)))

    def test_malformed(self):
        for bad in (None, "x", {}, {"status": "sent"}, {"id": "w"}):
            self.assertFalse(ER.is_staff_reply_status(bad))

    def test_latest_status_per_id(self):
        data = {"entry": [{"changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": "PN"},
            "statuses": [_status("delivered"), _status("sent"), _status("read", id="wamid.OTHER")]}}]}]}
        got = ER.latest_statuses(data, {"wamid.PBX"})
        self.assertEqual(list(got), ["wamid.PBX"])
        self.assertEqual(got["wamid.PBX"][0]["status"], "delivered")
        self.assertEqual(got["wamid.PBX"][1], "PN")


class TestLookups(unittest.TestCase):
    def test_phone_then_bsuid(self):
        got = ER.conversation_lookups("+964 770 123 4567", "IQ.1", lambda r: "9647701234567")
        self.assertEqual(got, [{"phone": "9647701234567"}, {"wa_user_id": "IQ.1"}, {"phone": "IQ.1"}])

    def test_nothing(self):
        self.assertEqual(ER.conversation_lookups(None, "", lambda r: ""), [])


class TestRowFields(unittest.TestCase):
    def test_placeholder(self):
        when = NOW - timedelta(seconds=5)
        f = ER.placeholder_fields(_status("delivered"), CONV, when)
        self.assertEqual((f["doctype"], f["type"], f["message_id"], f["to"]),
                         ("WhatsApp Message", "Outgoing", "wamid.PBX", "9647701234567"))
        self.assertEqual((f["content_type"], f["message"], f["custom_body_text"]), ("text", "", ""))
        self.assertEqual((f["custom_conversation"], f["custom_read"], f["status"]), ("WAC-1", 1, "delivered"))
        self.assertEqual(json.loads(f["custom_payload"]), {"kind": "external", "category": "service"})
        self.assertEqual((f["creation"], f["custom_delivered_at"]), (when, when))
        self.assertNotIn("custom_sent_by", f)
        self.assertEqual(f["whatsapp_account"], "ALKHORA WA")

    def test_timestamp_sanity(self):
        self.assertEqual(ER.reply_time(NOW_EPOCH - 60, NOW_EPOCH, NOW), NOW - timedelta(seconds=60))
        self.assertEqual(ER.reply_time(NOW_EPOCH - 7 * 86400, NOW_EPOCH, NOW), NOW - timedelta(days=7))
        for bad in (NOW_EPOCH - 7 * 86400 - 1, NOW_EPOCH + 30, None, "", "junk"):
            self.assertEqual(ER.reply_time(bad, NOW_EPOCH, NOW), NOW, bad)


class TestConversationValues(unittest.TestCase):
    def test_answers_waiting_customer(self):
        conv = {"status": "Open", "awaiting_reply_since": NOW - timedelta(minutes=10),
                "last_message_at": NOW - timedelta(minutes=10), "assigned_to": "a@x"}
        v = ER.conversation_values(conv, NOW)
        self.assertEqual(v["first_response_seconds"], 600)
        self.assertIsNone(v["awaiting_reply_since"])
        self.assertEqual((v["status"], v["last_message_direction"]), ("Pending", "Out"))
        self.assertEqual(v["last_message_preview"], "Replied from another app")
        self.assertEqual((v["last_message_at"], v["last_outbound_at"]), (NOW, NOW))
        self.assertNotIn("assigned_to", v)

    def test_keeps_first_response_and_resolved(self):
        conv = {"status": "Resolved", "awaiting_reply_since": NOW - timedelta(minutes=1),
                "first_response_seconds": 30}
        v = ER.conversation_values(conv, NOW)
        self.assertNotIn("first_response_seconds", v)
        self.assertNotIn("status", v)
        self.assertIsNone(v["awaiting_reply_since"])

    def test_older_than_latest_customer_message(self):
        conv = {"status": "Open", "awaiting_reply_since": NOW, "last_message_at": NOW,
                "last_outbound_at": NOW - timedelta(hours=1)}
        v = ER.conversation_values(conv, NOW - timedelta(minutes=1))
        self.assertEqual(v, {"last_outbound_at": NOW - timedelta(minutes=1)})


def _echo_payload(items, field="smb_message_echoes"):
    return {"entry": [{"changes": [{"field": field, "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "PN"}, "message_echoes": items}}]}]}


class TestEchoes(unittest.TestCase):
    def test_parse_text_and_media(self):
        items = [
            {"from": "964770", "to": "9647701234567", "id": "wamid.E1", "timestamp": "1", "type": "text",
             "text": {"body": "Hello"}},
            {"from": "964770", "to": "9647701234567", "id": "wamid.E2", "type": "image",
             "image": {"id": "MEDIA", "caption": "Price list"}},
            {"to": "9647701234567", "id": "wamid.E3", "type": "document", "document": {"id": "M"}},
            {"id": "wamid.NOTO", "type": "text"}, "junk",
        ]
        got = ER.parse_echoes(_echo_payload(items))
        self.assertEqual([e["id"] for e in got], ["wamid.E1", "wamid.E2", "wamid.E3"])
        self.assertEqual(got[0]["text"], "Hello")
        self.assertEqual(got[1]["text"], "\U0001F4F7 Photo — Price list")
        self.assertEqual(got[2]["text"], "\U0001F4C4 Document")
        self.assertEqual(got[0]["phone_number_id"], "PN")

    def test_noop_for_normal_payloads(self):
        normal = {"entry": [{"changes": [{"field": "messages", "value": {
            "messages": [{"id": "wamid.IN", "type": "text"}], "statuses": [_status()]}}]}]}
        for data in (normal, {}, {"entry": "junk"}, None):
            self.assertEqual(ER.parse_echoes(data), [])

    def test_upgrade_rule(self):
        echo = {"type": "text", "text": "Hi there"}
        placeholder = json.dumps({"kind": "external", "category": "service"})
        v = ER.upgrade_values(placeholder, echo)
        self.assertEqual((v["message"], v["custom_body_text"]), ("Hi there", "Hi there"))
        self.assertEqual(json.loads(v["custom_payload"]),
                         {"kind": "echo", "external": True, "category": "service", "echo_type": "text"})
        for other in (None, "", json.dumps({"kind": "echo", "external": True}),
                      json.dumps({"kind": "location"})):
            self.assertIsNone(ER.upgrade_values(other, echo), other)


class TestThreadItemFlags(unittest.TestCase):
    def _item(self, payload):
        row = {"custom_payload": json.dumps(payload) if payload is not None else None}
        return P.decorate_item({}, row.get)

    def test_flags(self):
        self.assertEqual(self._item({"kind": "external", "category": "service"})["external"], True)
        self.assertEqual(self._item({"kind": "external", "category": "utility"})["external_category"], "utility")
        self.assertTrue(self._item({"kind": "echo", "external": True})["external"])
        for plain in (None, {"kind": "echo"}, {"kind": "voice", "voice": True}):
            item = self._item(plain)
            self.assertEqual((item["external"], item["external_category"]), (False, ""), plain)


class TestOverrideNoSend(unittest.TestCase):
    def _doc(self, **fields):
        base = {"type": "Outgoing", "template": None, "message_type": "Manual", "to": "9647701234567",
                "content_type": "text", "custom_payload": None, "custom_is_voice": 0, "is_reply": 0}
        base.update(fields)
        return override.WhatsAppMessage(**base)

    def test_store_only_rows_never_reach_upstream(self):
        for kind in ("external", "echo"):
            doc = self._doc(custom_payload=json.dumps({"kind": kind}))
            doc.before_insert()
            doc.send_outgoing()
            self.assertEqual(doc.calls, [], kind)

    def test_plain_row_sends_and_is_marked_own(self):
        doc = self._doc(message="hi")
        doc.before_insert()
        self.assertEqual(doc.calls, ["before_insert", "upstream_send"])
        self.assertTrue(ER._is_own("wamid.OURS"))
        self.assertFalse(ER._is_own("wamid.PBX"))


if __name__ == "__main__":
    unittest.main(verbosity=1)

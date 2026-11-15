"""
Bench-free tests for "delete message" (team-side soft delete):

    whatsapp_api_delete     may_delete (who may delete what)
    whatsapp_payloads       tombstone / mark_deleted (content blanking)
    whatsapp_serializers    the deleted_* defaults on every ThreadItem

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_delete_pure.py

A stub `frappe` is injected when none is importable; the package directories
are registered so the serializer's absolute imports resolve off disk.
"""

import datetime
import importlib.util
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG = "opportunity_management.opportunity_management"


def _install_stubs():
    if "frappe" not in sys.modules:

        def _no_bench(*args, **kwargs):
            raise RuntimeError("no bench available in this test run")

        def _throw(msg, *args, **kwargs):
            raise RuntimeError(msg)

        stub = types.ModuleType("frappe")
        stub._dict = dict
        stub._ = lambda s, *a, **k: s
        stub.local = types.SimpleNamespace()
        stub.flags = {}
        stub.session = types.SimpleNamespace(user="agent@x")
        stub.get_doc = _no_bench
        stub.get_all = _no_bench
        stub.throw = _throw
        stub.whitelist = lambda *a, **k: (lambda fn: fn)
        stub.db = types.SimpleNamespace(get_value=_no_bench, exists=_no_bench, has_column=_no_bench)
        utils = types.ModuleType("frappe.utils")
        utils.cint = lambda v: int(float(v or 0)) if str(v or "0").strip() else 0
        utils.get_url = lambda uri=None: "https://erp.example" + (uri or "")
        utils.now_datetime = datetime.datetime.now
        utils.get_datetime = lambda v=None: v
        stub.utils = utils
        sys.modules["frappe"] = stub
        sys.modules["frappe.utils"] = utils
    # Package shells so `from opportunity_management.opportunity_management
    # import x` loads x straight off disk.
    for name, path in (("opportunity_management", os.path.dirname(_HERE)), (_PKG, _HERE)):
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = [path]
            sys.modules[name] = pkg


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_stubs()
P = _load(_PKG + ".whatsapp_payloads", "whatsapp_payloads.py")
D = _load("_wa_delete_under_test", "whatsapp_api_delete.py")
try:
    S = _load(_PKG + ".whatsapp_serializers", "whatsapp_serializers.py")
except Exception:  # pragma: no cover - a dependency needs a real bench
    S = None

DELETED_KEYS = ("deleted", "deleted_at", "deleted_by", "deleted_by_name")


class TestMayDelete(unittest.TestCase):
    def test_incoming_is_refused_for_everyone(self):
        self.assertEqual(D.may_delete("in", "a@x", "a@x", False), "incoming")
        self.assertEqual(D.may_delete("in", None, "m@x", True), "incoming")

    def test_agent_may_delete_own_outgoing(self):
        self.assertEqual(D.may_delete("out", "a@x", "a@x", False), "")

    def test_agent_may_not_delete_someone_elses(self):
        self.assertEqual(D.may_delete("out", "b@x", "a@x", False), "not_sender")

    def test_manager_may_delete_any_outgoing(self):
        self.assertEqual(D.may_delete("out", "b@x", "m@x", True), "")
        self.assertEqual(D.may_delete("out", None, "m@x", True), "")

    def test_no_sender_is_not_the_agents(self):
        self.assertEqual(D.may_delete("out", None, "a@x", False), "not_sender")
        self.assertEqual(D.may_delete("out", "", "a@x", False), "not_sender")


def _full_item():
    return {
        "id": "MSG-1", "kind": "message", "direction": "out", "creation": "2026-11-15T10:00:00",
        "text": "secret", "caption": "cap", "content_type": "image",
        "media_url": "/private/files/a.jpg", "media_mime": "image/jpeg", "media_size": 1234,
        "audio_url": "/files/a.m4a", "audio_duration": 7, "location": {"latitude": 1},
        "contacts": [{"name": "x"}], "options": ["Yes"], "reply_to_message_id": "wamid.Q",
        "reply_to_text": "quoted", "is_sticker": True, "referral": {"source_url": "u"},
        "status": "read", "sent_at": "2026-11-15 10:00:01", "sender_user": "a@x",
        "sender_name": "Agent A", "reactions": [{"emoji": "x", "count": 1}], "message_id": "wamid.M",
    }


class TestTombstone(unittest.TestCase):
    def test_content_is_blanked(self):
        item = P.tombstone(_full_item(), datetime.datetime(2026, 11, 15, 11, 0, 0, 123), "m@x", "Mgr")
        for key, blank in (("text", ""), ("caption", ""), ("media_url", None), ("media_mime", ""),
                           ("media_size", None), ("audio_url", None), ("audio_duration", None),
                           ("location", None), ("contacts", None), ("options", None),
                           ("reply_to_text", ""), ("is_sticker", False), ("referral", None)):
            self.assertEqual(item[key], blank, key)

    def test_metadata_is_kept(self):
        item = P.tombstone(_full_item(), "2026-11-15 11:00:00", "m@x", "Mgr")
        full = _full_item()
        for key in ("id", "content_type", "status", "creation", "sent_at", "sender_user",
                    "sender_name", "reactions", "reply_to_message_id", "message_id", "direction"):
            self.assertEqual(item[key], full[key], key)

    def test_deleted_keys(self):
        item = P.tombstone(_full_item(), datetime.datetime(2026, 11, 15, 11, 0, 0, 123), "m@x", "Mgr")
        self.assertEqual(
            {k: item[k] for k in DELETED_KEYS},
            {"deleted": 1, "deleted_at": "2026-11-15 11:00:00", "deleted_by": "m@x", "deleted_by_name": "Mgr"},
        )

    def test_mark_deleted_skips_live_rows(self):
        item = _full_item()
        self.assertIs(P.mark_deleted(item, {}.get), item)
        self.assertEqual(item["text"], "secret")
        self.assertNotIn("deleted", item)

    def test_mark_deleted_names_from_page_then_lookup(self):
        row = {"custom_deleted_at": "2026-11-15 11:00:00", "custom_deleted_by": "m@x"}
        item = P.mark_deleted(_full_item(), row.get, {"m@x": "Mgr"})
        self.assertEqual((item["deleted"], item["deleted_by_name"]), (1, "Mgr"))
        looked = []
        item = P.mark_deleted(_full_item(), row.get, {}, lambda us: looked.extend(us) or {"m@x": "M"})
        self.assertEqual((looked, item["deleted_by_name"]), (["m@x"], "M"))
        item = P.mark_deleted(_full_item(), row.get)
        self.assertEqual(item["deleted_by_name"], "m@x")  # no lookup: user id

    def test_mark_deleted_without_user(self):
        row = {"custom_deleted_at": "2026-11-15 11:00:00"}
        item = P.mark_deleted(_full_item(), row.get, {})
        self.assertEqual((item["deleted_by"], item["deleted_by_name"]), (None, ""))


class TestDefaults(unittest.TestCase):
    def test_deleted_blank(self):
        self.assertEqual(P.DELETED_BLANK, {"deleted": 0, "deleted_at": None, "deleted_by": None,
                                           "deleted_by_name": ""})

    @unittest.skipIf(S is None, "serializer dependencies need a bench")
    def test_thread_item_blank_carries_deleted_defaults(self):
        for key, value in P.DELETED_BLANK.items():
            self.assertIn(key, S._THREAD_ITEM_BLANK)
            self.assertEqual(S._THREAD_ITEM_BLANK[key], value)


    @unittest.skipIf(S is None, "serializer dependencies need a bench")
    def test_message_item_serializes_a_deleted_row_as_tombstone(self):
        row = {"name": "MSG-1", "type": "Outgoing", "creation": "2026-11-15 10:00:00",
               "custom_body_text": "secret", "content_type": "text", "status": "read",
               "custom_sent_by": "a@x", "custom_deleted_at": "2026-11-15 11:00:00.5",
               "custom_deleted_by": "m@x"}
        item = S.message_item(row, sender_names={"a@x": "Agent A", "m@x": "Mgr"}, sizes={})
        self.assertEqual((item["text"], item["status"], item["sender_name"]), ("", "read", "Agent A"))
        self.assertEqual({k: item[k] for k in DELETED_KEYS},
                         {"deleted": 1, "deleted_at": "2026-11-15 11:00:00", "deleted_by": "m@x",
                          "deleted_by_name": "Mgr"})
        live = S.message_item(dict(row, custom_deleted_at=None), sender_names={"a@x": "A"}, sizes={})
        self.assertEqual((live["text"], live["deleted"], live["deleted_at"]), ("secret", 0, None))


if __name__ == "__main__":
    unittest.main()

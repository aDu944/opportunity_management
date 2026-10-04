"""
Bench-free tests for the webhook's foreign-status filter:

    whatsapp_webhook.status_ids / filter_statuses

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_status_filter_pure.py

A stub `frappe` is injected when none is importable and the module is
loaded straight off disk.
"""

import copy
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
    stub.whitelist = lambda **kwargs: (lambda fn: fn)
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
ww = _load("_wa_webhook_under_test", "whatsapp_webhook.py")


def _status(mid, status="sent"):
    return {"id": mid, "status": status, "recipient_id": "9647700000000"}


def _payload(statuses=None, messages=None):
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "1"}}
    if statuses is not None:
        value["statuses"] = statuses
    if messages is not None:
        value["messages"] = messages
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "x", "changes": [{"field": "messages", "value": value}]}]}


def _value(data):
    return data["entry"][0]["changes"][0]["value"]


class TestFilterStatuses(unittest.TestCase):
    def test_mixed_known_and_unknown(self):
        data = _payload([_status("wamid.OURS"), _status("wamid.SHOP", "delivered"), _status("wamid.OURS", "read")])
        self.assertEqual(ww.status_ids(data), {"wamid.OURS", "wamid.SHOP"})
        self.assertEqual(ww.filter_statuses(data, {"wamid.OURS"}), 1)
        self.assertEqual([s["status"] for s in _value(data)["statuses"]], ["sent", "read"])
        self.assertTrue(ww._has_payload(data))

    def test_all_unknown_leaves_nothing_to_delegate(self):
        data = _payload([_status("wamid.SHOP"), _status("wamid.PBX")])
        self.assertEqual(ww.filter_statuses(data, set()), 2)
        self.assertNotIn("statuses", _value(data))
        self.assertFalse(ww._has_payload(data))

    def test_messages_kept_when_statuses_dropped(self):
        msg = {"id": "wamid.IN", "type": "text", "text": {"body": "hi"}}
        data = _payload([_status("wamid.SHOP")], messages=[msg])
        self.assertEqual(ww.filter_statuses(data, set()), 1)
        self.assertEqual(_value(data)["messages"], [msg])
        self.assertNotIn("statuses", _value(data))
        self.assertTrue(ww._has_payload(data))

    def test_payload_without_statuses_untouched(self):
        msg = {"id": "wamid.IN", "type": "text", "text": {"body": "hi"}}
        for data in (_payload(messages=[msg]), _payload(statuses=[]), {"entry": "junk"}, {}):
            before = copy.deepcopy(data)
            self.assertEqual(ww.status_ids(data), set())
            self.assertEqual(ww.filter_statuses(data, set()), 0)
            self.assertEqual(data, before)

    def test_all_known_untouched(self):
        data = _payload([_status("wamid.A"), _status("wamid.B")])
        before = copy.deepcopy(data)
        self.assertEqual(ww.filter_statuses(data, {"wamid.A", "wamid.B"}), 0)
        self.assertEqual(data, before)

    def test_malformed_entries_are_dropped(self):
        data = _payload([_status("wamid.A"), {"status": "sent"}, "junk"])
        self.assertEqual(ww.status_ids(data), {"wamid.A"})
        self.assertEqual(ww.filter_statuses(data, {"wamid.A"}), 2)
        self.assertEqual(_value(data)["statuses"], [_status("wamid.A")])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
Bench-free tests for the WhatsApp push sound / channel:

    fcm_utils               split_private_keys / apply_private_keys, and the
                            full FCM v1 message `send_fcm` POSTs (Google auth
                            stubbed) — with the private keys and without
    whatsapp_message_extras add_wa_sound

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_push_sound_pure.py

A stub `frappe` (and stub google-auth modules) are injected; each module is
loaded straight off disk.
"""

import importlib.util
import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_POSTED = []


def _install_stubs():
    if "frappe" not in sys.modules:

        def _no_bench(*args, **kwargs):
            raise RuntimeError("no bench available in this test run")

        stub = types.ModuleType("frappe")
        stub._dict = dict
        stub.local = types.SimpleNamespace()
        stub.flags = {}
        stub.get_doc = _no_bench
        stub.db = types.SimpleNamespace(get_value=_no_bench, sql=_no_bench, set_value=_no_bench)
        utils = types.ModuleType("frappe.utils")
        utils.cint = lambda v: int(float(v or 0)) if str(v or "0").strip() else 0
        utils.now_datetime = lambda: None
        stub.utils = utils
        sys.modules["frappe"] = stub
        sys.modules["frappe.utils"] = utils
    frappe = sys.modules["frappe"]
    frappe.conf = {"firebase_service_account": json.dumps({"project_id": "demo"})}
    frappe.log_error = lambda *a, **k: _POSTED.append(("error", a, k))

    # google-auth: capture the POSTed JSON instead of calling FCM.
    class _Resp:
        status_code = 200
        text = ""

    class _Session:
        def __init__(self, creds):
            pass

        def post(self, url, json=None, timeout=None):
            _POSTED.append(json)
            return _Resp()

    sa = types.ModuleType("google.oauth2.service_account")
    sa.Credentials = types.SimpleNamespace(from_service_account_info=lambda info, scopes=None: object())
    req = types.ModuleType("google.auth.transport.requests")
    req.AuthorizedSession = _Session
    for name in ("google", "google.oauth2", "google.auth", "google.auth.transport"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["google.oauth2.service_account"] = sa
    sys.modules["google.oauth2"].service_account = sa
    sys.modules["google.auth.transport.requests"] = req

    # `whatsapp_message_extras` imports its sibling `whatsapp_payloads` from
    # the package; an empty stand-in is enough for `add_wa_sound`.
    for name in ("opportunity_management", "opportunity_management.opportunity_management"):
        sys.modules.setdefault(name, types.ModuleType(name))
    payloads = types.ModuleType("opportunity_management.opportunity_management.whatsapp_payloads")
    sys.modules.setdefault(payloads.__name__, payloads)
    sys.modules["opportunity_management.opportunity_management"].whatsapp_payloads = (
        sys.modules[payloads.__name__]
    )


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_stubs()
fcm = _load("_fcm_utils_under_test", "fcm_utils.py")
fcm._unread_badge_for_token = lambda token: 3
extras = _load("_wa_message_extras_under_test", "whatsapp_message_extras.py")

# The message `send_fcm` produced before this change, for a payload without
# private keys — must stay byte-for-byte identical.
_DEFAULT = {
    "message": {
        "token": "tok",
        "notification": {"title": "T", "body": "B"},
        "data": {"type": "broadcast"},
        "android": {
            "priority": "high",
            "notification": {"channel_id": "alkhora_ess_main", "sound": "bell", "notification_count": 3},
        },
        "apns": {"payload": {"aps": {"sound": "bell.caf", "badge": 3}}},
    }
}


def _send(data):
    del _POSTED[:]
    assert fcm.send_fcm("tok", "T", "B", data) is True, _POSTED
    return _POSTED[-1]


def _base():
    return json.loads(json.dumps(_DEFAULT["message"]))


class TestApplyPrivateKeys(unittest.TestCase):
    def test_no_keys_leaves_defaults(self):
        self.assertEqual(fcm.apply_private_keys(_base(), {}), _DEFAULT["message"])

    def test_empty_values_leave_defaults(self):
        private = {"_sound_ios": "", "_sound_android": None, "_android_channel": ""}
        self.assertEqual(fcm.apply_private_keys(_base(), private), _DEFAULT["message"])

    def test_keys_set_sound_and_channel(self):
        msg = fcm.apply_private_keys(_base(), dict(extras.WA_PUSH_SOUND))
        self.assertEqual(msg["apns"]["payload"]["aps"], {"sound": "wa_message.caf", "badge": 3})
        self.assertEqual(msg["android"]["notification"], {
            "channel_id": "alkhora_ess_whatsapp", "sound": "wa_message", "notification_count": 3,
        })

    def test_split_does_not_mutate_caller(self):
        data = {"type": "x", "_sound_ios": "a.caf", "_apns_category": "WA_REPLY"}
        clean, private = fcm.split_private_keys(data)
        self.assertEqual(clean, {"type": "x"})
        self.assertEqual(private, {"_sound_ios": "a.caf", "_apns_category": "WA_REPLY"})
        self.assertIn("_sound_ios", data)

    def test_split_none(self):
        self.assertEqual(fcm.split_private_keys(None), ({}, {}))


class TestSendFcmPayload(unittest.TestCase):
    def test_plain_push_is_byte_for_byte_unchanged(self):
        self.assertEqual(json.dumps(_send({"type": "broadcast"})), json.dumps(_DEFAULT))

    def test_category_only_matches_previous_shape(self):
        sent = _send({"type": "broadcast", "_apns_category": "WA_REPLY"})
        expected = json.loads(json.dumps(_DEFAULT))
        expected["message"]["apns"]["payload"]["aps"]["category"] = "WA_REPLY"
        self.assertEqual(json.dumps(sent), json.dumps(expected))

    def test_whatsapp_push(self):
        data = extras.add_wa_sound({"type": "whatsapp_message", "screen": "whatsapp", "name": "WAC-1"})
        data["_apns_category"] = "WA_REPLY"
        msg = _send(data)["message"]
        self.assertEqual(msg["data"], {"type": "whatsapp_message", "screen": "whatsapp", "name": "WAC-1"})
        self.assertEqual(msg["android"], {
            "priority": "high",
            "notification": {
                "channel_id": "alkhora_ess_whatsapp", "sound": "wa_message", "notification_count": 3,
            },
        })
        self.assertEqual(msg["apns"], {
            "payload": {"aps": {"sound": "wa_message.caf", "badge": 3, "category": "WA_REPLY"}},
        })


class TestAddWaSound(unittest.TestCase):
    def test_adds_private_keys_in_place(self):
        data = {"type": "whatsapp_assigned"}
        self.assertIs(extras.add_wa_sound(data), data)
        self.assertEqual(data, {
            "type": "whatsapp_assigned",
            "_sound_ios": "wa_message.caf",
            "_sound_android": "wa_message",
            "_android_channel": "alkhora_ess_whatsapp",
        })

    def test_keys_are_all_private(self):
        self.assertTrue(set(extras.WA_PUSH_SOUND) <= set(fcm._PRIVATE_KEYS))


if __name__ == "__main__":
    unittest.main(verbosity=1)

"""
Bench-free tests for multi-device (web) push:

    fcm_webpush    build_webpush / inbox_link / merge_targets / is_bad_token_response
    fcm_utils      send_fcm(platform="web") payload, _fan_out, send_fcm_to_employee,
                   send_fcm_to_user (dead device tokens disabled, phone token never)
    push_devices   normalize_platform / clean_token / clean_label

    python3 opportunity_management/opportunity_management/tests/test_fcm_webpush_pure.py

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
_PKG = "opportunity_management.opportunity_management"
_POSTED = []
_RESPONSES = {}  # token → (status, text); default 200


def _no_bench(*args, **kwargs):
    raise RuntimeError("no bench available in this test run")


def _install_stubs():
    if "frappe" not in sys.modules:
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
    frappe.log_error = lambda *a, **k: None
    frappe.get_traceback = lambda: ""
    if not hasattr(frappe, "_"):
        frappe._ = lambda s: s
    if not hasattr(frappe, "whitelist"):
        frappe.whitelist = lambda *a, **k: (lambda fn: fn)
    for exc in ("PermissionError", "DuplicateEntryError"):
        if not hasattr(frappe, exc):
            setattr(frappe, exc, type(exc, (Exception,), {}))
    if not hasattr(sys.modules["frappe.utils"], "now_datetime"):
        sys.modules["frappe.utils"].now_datetime = lambda: None

    class _Resp:
        def __init__(self, status, text):
            self.status_code, self.text = status, text

    class _Session:
        def __init__(self, creds):
            pass

        def post(self, url, json=None, timeout=None):
            _POSTED.append(json)
            return _Resp(*_RESPONSES.get(json["message"]["token"], (200, "")))

    sa = types.ModuleType("google.oauth2.service_account")
    sa.Credentials = types.SimpleNamespace(from_service_account_info=lambda info, scopes=None: object())
    req = types.ModuleType("google.auth.transport.requests")
    req.AuthorizedSession = _Session
    for name in ("google", "google.oauth2", "google.auth", "google.auth.transport"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["google.oauth2.service_account"] = sa
    sys.modules["google.oauth2"].service_account = sa
    sys.modules["google.auth.transport.requests"] = req
    for name in ("opportunity_management", _PKG):
        sys.modules.setdefault(name, types.ModuleType(name))


def _load(name, filename, alias=None):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if alias:
        sys.modules[alias] = module
        setattr(sys.modules[_PKG], alias.rsplit(".", 1)[1], module)
    return module


_install_stubs()
wp = _load("_fcm_webpush_under_test", "fcm_webpush.py", alias=_PKG + ".fcm_webpush")
fcm = _load("_fcm_utils_webpush_under_test", "fcm_utils.py")
fcm._unread_badge_for_token = lambda token: 2
fcm._site_url = lambda: "https://erp.example.com/"
pd = _load("_push_devices_under_test", "push_devices.py")

SITE = "https://erp.example.com"
CONV = {"type": "whatsapp_message", "screen": "whatsapp", "doctype": "WhatsApp Conversation", "name": "WAC-00042"}


class TestInboxLink(unittest.TestCase):
    def test_conversation(self):
        self.assertEqual(wp.inbox_link(CONV, SITE + "/"), SITE + "/inbox#/chats/WAC-00042")

    def test_screen_whatsapp_without_doctype(self):
        self.assertEqual(wp.inbox_link({"screen": "whatsapp", "name": "WAC-1"}, SITE), SITE + "/inbox#/chats/WAC-1")

    def test_other_doctype_goes_to_inbox_root(self):
        data = {"doctype": "Leave Application", "name": "HR-LAP-1", "screen": "leave"}
        self.assertEqual(wp.inbox_link(data, SITE), SITE + "/inbox")

    def test_conversation_without_name(self):
        self.assertEqual(wp.inbox_link({"doctype": "WhatsApp Conversation"}, SITE), SITE + "/inbox")

    def test_name_is_url_quoted(self):
        self.assertEqual(wp.inbox_link({"screen": "whatsapp", "name": "a b/c"}, SITE), SITE + "/inbox#/chats/a%20b%2Fc")

    def test_no_site_url(self):
        self.assertEqual(wp.inbox_link(None, ""), "/inbox")


class TestBuildWebpush(unittest.TestCase):
    def test_shape(self):
        block = wp.build_webpush("T", "B", dict(CONV, unread=3), SITE)
        self.assertEqual(block, {
            "headers": {"Urgency": "high"},
            "notification": {"title": "T", "body": "B", "icon": wp.WEB_ICON},
            "fcm_options": {"link": SITE + "/inbox#/chats/WAC-00042"},
            "data": dict(CONV, unread="3"),
        })
        self.assertEqual(wp.WEB_ICON, "/assets/opportunity_management/inbox/icons/Icon-192.png")

    def test_no_sound_anywhere(self):
        self.assertNotIn("sound", json.dumps(wp.build_webpush("T", "B", CONV, SITE)))

    def test_none_data(self):
        block = wp.build_webpush("T", "B", None, SITE)
        self.assertEqual(block["data"], {})
        self.assertEqual(block["fcm_options"], {"link": SITE + "/inbox"})


class TestMergeTargets(unittest.TestCase):
    def test_primary_first_then_devices_deduplicated(self):
        rows = [
            {"name": "d1", "token": "web1", "platform": "web"},
            {"name": "d2", "token": "phone", "platform": "ios"},  # same as primary
            {"name": "d3", "token": "web1", "platform": "web"},   # duplicate row
            {"name": "d4", "token": "", "platform": "web"},
            {"name": "d5", "token": "web2", "platform": ""},
        ]
        self.assertEqual(wp.merge_targets("phone", rows), [
            {"token": "phone", "platform": None, "device": None},
            {"token": "web1", "platform": "web", "device": "d1"},
            {"token": "web2", "platform": None, "device": "d5"},
        ])

    def test_no_primary(self):
        self.assertEqual(wp.merge_targets(None, [{"name": "d1", "token": "w", "platform": "web"}]),
                         [{"token": "w", "platform": "web", "device": "d1"}])

    def test_nothing(self):
        self.assertEqual(wp.merge_targets("", None), [])


class TestBadToken(unittest.TestCase):
    def test_unregistered(self):
        text = '{"error": {"code": 404, "status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}'
        self.assertTrue(wp.is_bad_token_response(404, text))

    def test_invalid_token(self):
        text = '{"error": {"status": "INVALID_ARGUMENT", "message": "The registration token is not a valid FCM registration token"}}'
        self.assertTrue(wp.is_bad_token_response(400, text))

    def test_invalid_payload_is_not_a_bad_token(self):
        text = '{"error": {"status": "INVALID_ARGUMENT", "message": "Invalid value at \'message.data\'"}}'
        self.assertFalse(wp.is_bad_token_response(400, text))

    def test_auth_and_server_errors(self):
        self.assertFalse(wp.is_bad_token_response(401, "THIRD_PARTY_AUTH_ERROR"))
        self.assertFalse(wp.is_bad_token_response(500, "UNREGISTERED"))
        self.assertFalse(wp.is_bad_token_response(404, ""))


class TestSendFcmWeb(unittest.TestCase):
    def setUp(self):
        del _POSTED[:]
        _RESPONSES.clear()

    def test_web_adds_webpush_and_keeps_phone_blocks(self):
        data = dict(CONV, _sound_ios="wa_message.caf", _sound_android="wa_message",
                    _android_channel="alkhora_ess_whatsapp")
        self.assertTrue(fcm.send_fcm("w", "T", "B", data, platform="web"))
        msg = _POSTED[-1]["message"]
        self.assertEqual(msg["webpush"], wp.build_webpush("T", "B", CONV, SITE))
        self.assertEqual(msg["data"], CONV)
        self.assertEqual(msg["android"]["notification"]["sound"], "wa_message")
        self.assertEqual(msg["apns"]["payload"]["aps"]["sound"], "wa_message.caf")

    def test_phone_payload_has_no_webpush(self):
        self.assertTrue(fcm.send_fcm("p", "T", "B", CONV))
        self.assertNotIn("webpush", _POSTED[-1]["message"])

    def test_result_flags_bad_token(self):
        _RESPONSES["dead"] = (404, '{"details": [{"errorCode": "UNREGISTERED"}]}')
        ok, bad, error = fcm._send_fcm_result("dead", "T", "B", {}, "web")
        self.assertEqual((ok, bad), (False, True))
        self.assertIn("404", error)
        self.assertFalse(fcm.send_fcm("dead", "T", "B", {}))


class TestFanOut(unittest.TestCase):
    def setUp(self):
        del _POSTED[:]
        _RESPONSES.clear()
        self.disabled, self.logs = [], []
        self.devices = {"u@x": [{"name": "d1", "token": "web1", "platform": "web"},
                                {"name": "d2", "token": "phone", "platform": "ios"}]}
        self.saved = {k: getattr(fcm, k) for k in ("_enabled_devices", "_disable_device", "_create_notification_log")}
        fcm._enabled_devices = lambda user: list(self.devices.get(user, []))
        fcm._disable_device = lambda name, error: self.disabled.append(name)
        fcm._create_notification_log = lambda user, title, body: self.logs.append(user)
        self.frappe = sys.modules["frappe"]
        self.saved_db = self.frappe.db
        self.employees = {"EMP-1": {"custom_fcm_token": "phone", "user_id": "u@x"}}
        self.users = {"u@x": "EMP-1"}

        def get_value(doctype, filters, fields=None, as_dict=False):
            if doctype != "Employee":
                raise AssertionError(doctype)
            if isinstance(filters, dict):
                return self.users.get(filters.get("user_id"))
            return self.employees.get(filters)

        fcm.frappe.db = types.SimpleNamespace(get_value=get_value)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(fcm, k, v)
        fcm.frappe.db = self.saved_db

    def tokens(self):
        return [(p["message"]["token"], "webpush" in p["message"]) for p in _POSTED]

    def test_employee_gets_phone_plus_web_once_each(self):
        self.assertTrue(fcm.send_fcm_to_employee("EMP-1", "T", "B", CONV))
        self.assertEqual(self.tokens(), [("phone", False), ("web1", True)])
        self.assertEqual(self.logs, ["u@x"])

    def test_dead_web_token_disabled_phone_still_ok(self):
        _RESPONSES["web1"] = (404, "UNREGISTERED")
        self.assertTrue(fcm.send_fcm_to_employee("EMP-1", "T", "B", CONV))
        self.assertEqual(self.disabled, ["d1"])

    def test_dead_phone_token_never_disabled(self):
        _RESPONSES["phone"] = (404, "UNREGISTERED")
        self.assertTrue(fcm.send_fcm_to_employee("EMP-1", "T", "B", CONV))
        self.assertEqual(self.disabled, [])  # d2 shares the phone token: primary wins

    def test_all_fail_no_log(self):
        _RESPONSES["phone"] = (500, "boom")
        _RESPONSES["web1"] = (500, "boom")
        self.assertFalse(fcm.send_fcm_to_employee("EMP-1", "T", "B", CONV))
        self.assertEqual((self.logs, self.disabled), ([], []))

    def test_employee_without_phone_token_still_gets_web(self):
        self.employees["EMP-1"]["custom_fcm_token"] = None
        self.assertTrue(fcm.send_fcm_to_employee("EMP-1", "T", "B", CONV))
        self.assertEqual(self.tokens(), [("web1", True), ("phone", False)])

    def test_user_without_employee_uses_devices(self):
        self.devices["sm@x"] = [{"name": "d9", "token": "web9", "platform": "web"}]
        self.assertTrue(fcm.send_fcm_to_user("sm@x", "T", "B", CONV))
        self.assertEqual(self.tokens(), [("web9", True)])
        self.assertEqual(self.logs, ["sm@x"])

    def test_user_with_nothing(self):
        self.assertFalse(fcm.send_fcm_to_user("nobody@x", "T", "B", CONV))
        self.assertFalse(fcm.send_fcm_to_user("", "T", "B", CONV))
        self.assertEqual(_POSTED, [])

    def test_unknown_employee(self):
        self.assertFalse(fcm.send_fcm_to_employee("EMP-404", "T", "B", CONV))


class TestPushDeviceInputs(unittest.TestCase):
    def test_platform(self):
        self.assertEqual(pd.normalize_platform(" Web "), "web")
        self.assertEqual(pd.normalize_platform("iOS"), "ios")
        self.assertIsNone(pd.normalize_platform("windows"))
        self.assertIsNone(pd.normalize_platform(None))

    def test_token(self):
        self.assertEqual(pd.clean_token("  abc:DEF_1-2 "), "abc:DEF_1-2")
        self.assertIsNone(pd.clean_token(""))
        self.assertIsNone(pd.clean_token("a b"))
        self.assertIsNone(pd.clean_token("x" * (pd.MAX_TOKEN + 1)))

    def test_label(self):
        self.assertEqual(pd.clean_label("  Chrome \n on  macOS "), "Chrome on macOS")
        self.assertIsNone(pd.clean_label(None))
        self.assertEqual(len(pd.clean_label("y" * 500)), pd.MAX_LABEL)


if __name__ == "__main__":
    unittest.main(verbosity=1)

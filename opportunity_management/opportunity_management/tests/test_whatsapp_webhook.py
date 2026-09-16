"""
Tests for the webhook wrapper (dedupe, type coercion, HMAC).

    bench --site <site> run-tests --app opportunity_management \\
        --module opportunity_management.opportunity_management.tests.test_whatsapp_webhook

The wrapper's whole job is to protect frappe_whatsapp's handler from Meta's
real-world traffic, so these tests operate on the payload dicts directly
rather than going through HTTP — the delegation itself is covered by
`whatsapp_webhook.simulate` and the manual QA in the plan.
"""

import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from opportunity_management.opportunity_management import whatsapp_webhook as ww

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TEST_SECRET = "test-app-secret"


def load_fixture(name):
    with open(os.path.join(FIXTURE_DIR, f"meta_{name}.json")) as handle:
        return json.load(handle)


def _messages(payload):
    out = []
    for value in ww._values(payload):
        out.extend(value.get("messages") or [])
    return out


class TestWebhookFixtures(FrappeTestCase):
    def test_every_fixture_parses_and_is_reachable(self):
        for name in ("text_inbound", "image_inbound", "status_delivered", "location_inbound"):
            with self.subTest(fixture=name):
                payload = load_fixture(name)
                values = list(ww._values(payload))
                self.assertEqual(len(values), 1)
                self.assertTrue(ww._has_payload(payload))


class TestCoercion(FrappeTestCase):
    def test_location_becomes_text_with_a_maps_link(self):
        payload = load_fixture("location_inbound")
        ww._coerce_unsupported(payload)
        message = _messages(payload)[0]
        self.assertEqual(message["type"], "text")
        body = message["text"]["body"]
        self.assertIn("33.315241,44.366145", body)
        self.assertIn("https://maps.google.com/?q=", body)
        self.assertIn("AL KHORA", body)

    def test_supported_types_are_untouched(self):
        for name, expected in (("text_inbound", "text"), ("image_inbound", "image")):
            with self.subTest(fixture=name):
                payload = load_fixture(name)
                ww._coerce_unsupported(payload)
                self.assertEqual(_messages(payload)[0]["type"], expected)

    def test_contacts_becomes_a_summary(self):
        payload = load_fixture("text_inbound")
        message = _messages(payload)[0]
        message["type"] = "contacts"
        message.pop("text")
        message["contacts"] = [
            {"name": {"formatted_name": "Ali Hassan"}, "phones": [{"phone": "+964 770 111 2222"}]}
        ]
        ww._coerce_unsupported(payload)
        body = _messages(payload)[0]["text"]["body"]
        self.assertIn("Ali Hassan", body)
        self.assertIn("770 111 2222", body)

    def test_unknown_type_becomes_a_marker(self):
        payload = load_fixture("text_inbound")
        message = _messages(payload)[0]
        message["type"] = "sticker"
        ww._coerce_unsupported(payload)
        self.assertEqual(_messages(payload)[0]["type"], "text")
        self.assertIn("unsupported", _messages(payload)[0]["text"]["body"])


class TestDedupe(FrappeTestCase):
    def test_known_message_id_is_dropped(self):
        payload = load_fixture("text_inbound")
        with patch("frappe.db.exists", lambda *a, **k: True):
            dropped = ww._dedupe_messages(payload)
        self.assertEqual(dropped, 1)
        self.assertEqual(_messages(payload), [])
        self.assertFalse(ww._has_payload(payload))

    def test_unknown_message_id_is_kept(self):
        payload = load_fixture("text_inbound")
        with patch("frappe.db.exists", lambda *a, **k: False):
            dropped = ww._dedupe_messages(payload)
        self.assertEqual(dropped, 0)
        self.assertEqual(len(_messages(payload)), 1)

    def test_status_callbacks_are_never_deduped(self):
        payload = load_fixture("status_delivered")
        with patch("frappe.db.exists", lambda *a, **k: True):
            dropped = ww._dedupe_messages(payload)
        self.assertEqual(dropped, 0)
        self.assertTrue(ww._has_payload(payload))


class TestSignature(FrappeTestCase):
    def _run(self, body, header, secret=TEST_SECRET):
        conf = {"whatsapp_app_secret": secret} if secret else {}
        with patch.object(frappe, "conf", frappe._dict(conf)), patch.object(
            frappe, "get_request_header", lambda name: header
        ), patch.object(
            frappe, "request", frappe._dict({"get_data": lambda: body, "method": "POST"})
        ):
            return ww._verify_signature()

    def test_valid_signature_passes(self):
        body = b'{"object":"whatsapp_business_account"}'
        digest = hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(self._run(body, f"sha256={digest}"))

    def test_tampered_body_fails(self):
        body = b'{"object":"whatsapp_business_account"}'
        digest = hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertFalse(self._run(b'{"object":"tampered"}', f"sha256={digest}"))

    def test_missing_header_fails(self):
        self.assertFalse(self._run(b"{}", None))

    def test_unset_secret_allows_through(self):
        # Plan assumption 1: without the Meta App Secret we log and allow,
        # so the integration keeps working until it is provisioned.
        self.assertTrue(self._run(b"{}", None, secret=None))


if __name__ == "__main__":
    unittest.main()

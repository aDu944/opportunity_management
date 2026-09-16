"""
Integration tests for the WhatsApp inbox hook flow.

Needs a bench with `frappe_whatsapp` installed:

    bench --site <site> run-tests --app opportunity_management \\
        --module opportunity_management.opportunity_management.tests.test_whatsapp_conversation

`WhatsAppMessage.before_insert` is patched out in every test — un-patched it
POSTs to Meta synchronously, which would make the suite send real WhatsApp
messages. `frappe.enqueue`, `_send_to_users` and `publish_realtime` are
patched so the assertions are about conversation state, not side effects.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from opportunity_management.opportunity_management import whatsapp_api, whatsapp_hooks

_WHATSAPP_MESSAGE_CLASS = (
    "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message.WhatsAppMessage"
)
TEST_PHONE = "9647709999001"
TEST_ACCOUNT = "_Test WhatsApp Account"


def _ensure_account():
    if frappe.db.exists("WhatsApp Account", TEST_ACCOUNT):
        return TEST_ACCOUNT
    doc = frappe.get_doc(
        {
            "doctype": "WhatsApp Account",
            "account_name": TEST_ACCOUNT,
            "url": "https://graph.facebook.com",
            "version": "v19.0",
            "phone_id": "TEST_PHONE_ID",
            "business_id": "TEST_BUSINESS_ID",
            "app_id": "TEST_APP_ID",
            "token": "test-token",
            "status": "Active",
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


class WhatsAppInboxTestCase(FrappeTestCase):
    def setUp(self):
        self.account = _ensure_account()
        self._cleanup()
        self.patchers = [
            patch(f"{_WHATSAPP_MESSAGE_CLASS}.before_insert", lambda self: None),
            patch("frappe.enqueue", lambda *a, **k: None),
            patch("frappe.publish_realtime", lambda *a, **k: None),
            patch(
                "opportunity_management.opportunity_management.business_hooks._send_to_users",
                lambda *a, **k: None,
            ),
        ]
        for p in self.patchers:
            p.start()
        self.addCleanup(self._stop_patchers)
        self.addCleanup(self._cleanup)

    def _stop_patchers(self):
        for p in self.patchers:
            p.stop()

    def _cleanup(self):
        for name in frappe.get_all(
            "WhatsApp Conversation", filters={"phone": TEST_PHONE}, pluck="name"
        ):
            frappe.db.delete("WhatsApp Internal Note", {"conversation": name})
            frappe.db.delete("WhatsApp Message", {"custom_conversation": name})
            frappe.delete_doc(
                "WhatsApp Conversation", name, force=True, ignore_permissions=True
            )
        frappe.db.commit()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _inbound(self, text="Hello", message_id=None, content_type="text"):
        doc = frappe.get_doc(
            {
                "doctype": "WhatsApp Message",
                "type": "Incoming",
                "from": TEST_PHONE,
                "message": text,
                "message_id": message_id or frappe.generate_hash(length=12),
                "content_type": content_type,
                "profile_name": "Test Customer",
                "whatsapp_account": self.account,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _agent_outbound(self, text="On it"):
        doc = frappe.get_doc(
            {
                "doctype": "WhatsApp Message",
                "type": "Outgoing",
                "to": TEST_PHONE,
                "message": text,
                "content_type": "text",
                "whatsapp_account": self.account,
                "custom_sent_by": frappe.session.user,
                "custom_read": 1,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def _conv(self):
        name = frappe.db.get_value("WhatsApp Conversation", {"phone": TEST_PHONE}, "name")
        self.assertTrue(name, "no conversation was created for the test phone")
        return frappe.get_doc("WhatsApp Conversation", name)

    # ── tests ───────────────────────────────────────────────────────────────

    def test_inbound_creates_and_threads_conversation(self):
        msg = self._inbound("مرحبا")
        conv = self._conv()

        self.assertEqual(conv.conversation_key, f"{self.account}:{TEST_PHONE}")
        self.assertEqual(conv.status, "Open")
        self.assertEqual(conv.customer_language, "ar")
        self.assertEqual(conv.display_name, "Test Customer")
        self.assertIsNotNone(conv.first_contact_at)
        self.assertEqual(
            frappe.db.get_value("WhatsApp Message", msg.name, "custom_conversation"),
            conv.name,
        )

    def test_second_inbound_reuses_the_same_conversation(self):
        self._inbound("one")
        self._inbound("two")
        self.assertEqual(
            frappe.db.count("WhatsApp Conversation", {"phone": TEST_PHONE}), 1
        )

    def test_unread_and_preview_track_inbound(self):
        self._inbound("first")
        self._inbound("second message")
        conv = self._conv()
        self.assertEqual(conv.unread_count, 2)
        self.assertEqual(conv.last_message_preview, "second message")
        self.assertEqual(conv.last_message_direction, "In")
        self.assertIsNotNone(conv.awaiting_reply_since)

    def test_resolved_conversation_reopens_on_inbound(self):
        self._inbound("first")
        conv = self._conv()
        frappe.db.set_value(
            "WhatsApp Conversation",
            conv.name,
            {"status": "Resolved", "resolved_at": now_datetime()},
        )
        self._inbound("are you there?")
        conv = self._conv()
        self.assertEqual(conv.status, "Open")
        self.assertIsNone(conv.resolved_at)

    def test_agent_reply_sets_first_response_seconds_once(self):
        self._inbound("hello")
        conv = self._conv()
        # Backdate the wait so the measured response time is non-zero.
        frappe.db.set_value(
            "WhatsApp Conversation",
            conv.name,
            "awaiting_reply_since",
            add_to_date(now_datetime(), minutes=-5),
        )

        self._agent_outbound("on it")
        conv = self._conv()
        first = conv.first_response_seconds
        self.assertGreaterEqual(first, 240)
        self.assertIsNone(conv.awaiting_reply_since)
        self.assertEqual(conv.status, "Pending")

        self._inbound("thanks")
        self._agent_outbound("welcome")
        self.assertEqual(self._conv().first_response_seconds, first)

    def test_window_math(self):
        self._inbound("hello")
        conv = self._conv()
        self.assertTrue(conv.window_open())
        self.assertGreater(conv.window_seconds_remaining(), 23 * 3600)

        frappe.db.set_value(
            "WhatsApp Conversation",
            conv.name,
            "last_inbound_at",
            add_to_date(now_datetime(), hours=-25),
        )
        conv.reload()
        self.assertFalse(conv.window_open())
        self.assertEqual(conv.window_seconds_remaining(), 0)

    def test_send_message_outside_window_raises_window_closed(self):
        self._inbound("hello")
        conv = self._conv()
        frappe.db.set_value(
            "WhatsApp Conversation",
            conv.name,
            "last_inbound_at",
            add_to_date(now_datetime(), hours=-25),
        )
        with self.assertRaises(whatsapp_api.WindowClosedError):
            whatsapp_api.send_message(conv.name, text="too late")

    def test_failed_send_leaves_a_note_and_raises_meta_send_error(self):
        self._inbound("hello")
        conv = self._conv()

        def _boom(self):
            frappe.throw("(#131026) Message undeliverable")

        with patch(f"{_WHATSAPP_MESSAGE_CLASS}.before_insert", _boom):
            with self.assertRaises(whatsapp_api.MetaSendError):
                whatsapp_api.send_message(conv.name, text="will fail")

        notes = frappe.get_all(
            "WhatsApp Internal Note",
            filters={"conversation": conv.name, "note_type": "Failed Send"},
            pluck="name",
        )
        self.assertTrue(notes, "a Failed Send note should record the rejection")
        self.assertFalse(
            frappe.db.exists("WhatsApp Message", {"custom_conversation": conv.name, "type": "Outgoing"}),
            "nothing should be persisted when Meta rejects the send",
        )

    def test_send_message_auto_claims_an_unassigned_conversation(self):
        self._inbound("hello")
        conv = self._conv()
        self.assertFalse(conv.assigned_to)
        whatsapp_api.send_message(conv.name, text="claiming this")
        self.assertEqual(self._conv().assigned_to, frappe.session.user)

    def test_mark_read_zeroes_the_counter(self):
        self._inbound("one")
        self._inbound("two")
        conv = self._conv()
        self.assertEqual(whatsapp_api.mark_read(conv.name), {"unread_count": 0})
        self.assertEqual(self._conv().unread_count, 0)
        self.assertEqual(
            frappe.db.count(
                "WhatsApp Message",
                {"custom_conversation": conv.name, "type": "Incoming", "custom_read": 0},
            ),
            0,
        )

    def test_upsert_conversation_is_race_safe(self):
        first = whatsapp_hooks.upsert_conversation(
            TEST_PHONE, self.account, profile_name="A", notify=False
        )
        second = whatsapp_hooks.upsert_conversation(
            TEST_PHONE, self.account, profile_name="A", notify=False
        )
        self.assertEqual(first.name, second.name)


if __name__ == "__main__":
    unittest.main()

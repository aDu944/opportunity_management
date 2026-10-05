# Controller for WhatsApp Conversation — the thread object the shared team
# inbox is built on. One row per (whatsapp_account, normalized phone — or the
# business-scoped user ID when the customer hides their number).
#
# Deliberately thin, per house style: every mutation lives in
# `opportunity_management.opportunity_management.whatsapp_hooks` (webhook-side
# upserts, unread/preview bookkeeping, auto-replies) and
# `...whatsapp_api` (the whitelisted agent-facing contract). The only logic
# kept here is what a *reader* of the document needs, i.e. the Meta 24-hour
# customer-service window, because Desk forms, the API serializer and the
# auto-reply job all ask the same question.

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

# Meta's customer-service window: free-form text may only be sent within
# 24h of the customer's last inbound message. Outside it, only an approved
# template goes through (error 131047).
WINDOW_SECONDS = 24 * 60 * 60


class WhatsAppConversation(Document):
    def validate(self):
        """Normalize the thread identity before every write.

        `conversation_key` is unique and is what `upsert_conversation()`
        races on, so it must be derived here rather than by the caller —
        a hand-edited Desk row would otherwise be able to break the key.
        """
        from opportunity_management.opportunity_management.whatsapp_identity import (
            clean_username,
            is_bsuid,
            normalize_wa_identifier,
        )

        # A BSUID (hidden-number customer) is kept verbatim — it is what goes
        # out in `to`; only real phones are reduced to digits.
        self.phone = normalize_wa_identifier(self.phone) or (self.phone or "").strip()
        if is_bsuid(self.phone):
            self.wa_user_id = self.phone
        self.wa_username = clean_username(self.wa_username) or None
        if not self.display_name and not is_bsuid(self.phone):
            self.display_name = self.phone
        if (self.get("channel") or "") == "Messenger":
            # messenger:<page_id>:<psid>, set by messenger_ingest — keep it.
            if not str(self.conversation_key or "").startswith("messenger:"):
                self.conversation_key = "messenger::{0}".format(str(self.phone or "")[3:])
        else:
            self.conversation_key = "{0}:{1}".format(self.whatsapp_account or "", self.phone or "")

        if self.unread_count and self.unread_count < 0:
            self.unread_count = 0
        if self.notes_count and self.notes_count < 0:
            self.notes_count = 0

    # ── 24h window ───────────────────────────────────────────────────────────

    def window_seconds_remaining(self, now=None) -> int:
        """Seconds of free-text window left; 0 when closed (or never opened).
        A Messenger thread follows its own rule (inbox_channels.window_state:
        24 h, then 7 days with the Human Agent tag when enabled)."""
        if (self.get("channel") or "") == "Messenger":
            from opportunity_management.opportunity_management.inbox_channels import conv_window

            return conv_window(self, now=now)[1]
        if not self.last_inbound_at:
            return 0
        try:
            last = get_datetime(self.last_inbound_at)
        except Exception:
            return 0
        current = get_datetime(now) if now else now_datetime()
        elapsed = (current - last).total_seconds()
        remaining = WINDOW_SECONDS - elapsed
        return int(remaining) if remaining > 0 else 0

    def window_open(self, now=None) -> bool:
        return self.window_seconds_remaining(now=now) > 0

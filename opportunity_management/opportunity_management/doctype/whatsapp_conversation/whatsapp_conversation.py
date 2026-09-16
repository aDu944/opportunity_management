# Controller for WhatsApp Conversation — the thread object the shared team
# inbox is built on. One row per (whatsapp_account, normalized phone).
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
        from opportunity_management.opportunity_management.whatsapp_utils import (
            normalize_phone,
        )

        self.phone = normalize_phone(self.phone) or (self.phone or "").strip()
        if not self.display_name:
            self.display_name = self.phone
        self.conversation_key = "{0}:{1}".format(self.whatsapp_account or "", self.phone or "")

        if self.unread_count and self.unread_count < 0:
            self.unread_count = 0
        if self.notes_count and self.notes_count < 0:
            self.notes_count = 0

    # ── 24h window ───────────────────────────────────────────────────────────

    def window_seconds_remaining(self, now=None) -> int:
        """Seconds of free-text window left; 0 when closed (or never opened)."""
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

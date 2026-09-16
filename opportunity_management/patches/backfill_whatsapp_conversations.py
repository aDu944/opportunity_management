"""
Stand up the WhatsApp team inbox on an existing site (plan §1.2).

Runs in `[post_model_sync]`, so the new doctypes exist by the time it fires.
Everything is idempotent — `bench migrate` runs patches once, but a
re-migrate after a failed run, a restore, or `after_install` on a fresh site
all take the same path through `setup_whatsapp_inbox()`.

The backfill itself groups the WhatsApp Messages already in the table into
conversations. Design choices, per plan assumption 9:

  * history is marked **read** (`custom_read=1`, `unread_count=0`) so the
    badge does not open at 138;
  * `welcome_sent_at` is set to `first_contact_at`, so nobody who wrote in
    months ago gets a "welcome" the first time they message again;
  * threads idle for more than 7 days start **Resolved**;
  * nothing is assigned — everything lands in the Unassigned queue.

No FCM and no realtime: `upsert_conversation(..., notify=False)`.
"""

import frappe
from frappe.utils import add_days, get_datetime, now_datetime

BACKFILL_IDLE_DAYS = 7
BATCH_SIZE = 500


def execute():
    if not frappe.db.table_exists("WhatsApp Message"):
        print("frappe_whatsapp is not installed — skipping WhatsApp inbox backfill")
        return

    from opportunity_management.opportunity_management.setup.install import (
        setup_whatsapp_inbox,
    )

    setup_whatsapp_inbox()
    backfill_conversations()
    frappe.db.commit()


def backfill_conversations():
    """Group existing WhatsApp Messages into WhatsApp Conversations."""
    from opportunity_management.opportunity_management.whatsapp_hooks import (
        upsert_conversation,
    )
    from opportunity_management.opportunity_management.whatsapp_utils import (
        normalize_body,
        detect_language,
        normalize_phone,
    )

    rows = frappe.db.sql(
        """
        SELECT name, `type`, `from`, `to`, message, content_type, attach,
               template, use_template, body_param, message_type, profile_name,
               whatsapp_account, creation, custom_conversation
        FROM `tabWhatsApp Message`
        ORDER BY creation ASC
        """,
        as_dict=True,
    )
    if not rows:
        print("WhatsApp inbox backfill: no messages to group")
        return

    idle_cutoff = add_days(now_datetime(), -BACKFILL_IDLE_DAYS)
    conversations = {}
    grouped = 0

    for index, row in enumerate(rows, start=1):
        incoming = (row.get("type") or "") == "Incoming"
        phone = normalize_phone(row.get("from") if incoming else row.get("to"))
        if not phone:
            continue

        try:
            conv = upsert_conversation(
                phone,
                row.get("whatsapp_account"),
                profile_name=row.get("profile_name"),
                language=detect_language(row.get("message")) if incoming else None,
                notify=False,
            )
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), "WhatsApp backfill: upsert failed"
            )
            continue
        if not conv:
            continue

        body = normalize_body(row)
        frappe.db.set_value(
            "WhatsApp Message",
            row["name"],
            {
                "custom_conversation": conv.name,
                "custom_body_text": body,
                "custom_read": 1,
            },
            update_modified=False,
        )

        state = conversations.setdefault(
            conv.name,
            {
                "first_contact_at": row["creation"],
                "last_message_at": row["creation"],
                "last_inbound_at": None,
                "last_outbound_at": None,
                "last_message_preview": "",
                "last_message_direction": "",
            },
        )
        state["last_message_at"] = row["creation"]
        state["last_message_preview"] = (body or "")[:120]
        state["last_message_direction"] = "In" if incoming else "Out"
        if incoming:
            state["last_inbound_at"] = row["creation"]
        else:
            state["last_outbound_at"] = row["creation"]
        grouped += 1

        if index % BATCH_SIZE == 0:
            frappe.db.commit()

    for conv_name, state in conversations.items():
        last = get_datetime(state["last_message_at"])
        values = {
            "first_contact_at": state["first_contact_at"],
            "welcome_sent_at": state["first_contact_at"],
            "last_message_at": state["last_message_at"],
            "last_inbound_at": state["last_inbound_at"],
            "last_outbound_at": state["last_outbound_at"],
            "last_message_preview": state["last_message_preview"],
            "last_message_direction": state["last_message_direction"],
            "unread_count": 0,
            "awaiting_reply_since": None,
            "assigned_to": None,
            "assigned_at": None,
            "assigned_by": None,
        }
        if last < get_datetime(idle_cutoff):
            values["status"] = "Resolved"
            values["resolved_at"] = state["last_message_at"]
        frappe.db.set_value(
            "WhatsApp Conversation", conv_name, values, update_modified=False
        )

    frappe.db.commit()
    print(
        f"WhatsApp inbox backfill: grouped {grouped} messages "
        f"into {len(conversations)} conversations"
    )

"""
Out-of-band work for the WhatsApp team inbox: the auto-reply RQ job and the
two `*/5` cron sweeps.

Split out of `whatsapp_hooks` for size, but the boundary is also the right
one: nothing here runs inside Meta's webhook request. `send_auto_reply` in
particular **must** run out-of-process and after commit — composing the
reply inserts an Outgoing `WhatsApp Message`, whose `before_insert` calls
Meta synchronously and `frappe.throw`s on any API error.

Import direction is one-way: `whatsapp_hooks` imports this module (for
`_auto_reply_kind`, the cheap pre-filter it uses before enqueueing), and
this module imports nothing from it. Shared settings access lives in
`whatsapp_utils.setting`.
"""

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from opportunity_management.opportunity_management.whatsapp_utils import (
    get_inbox_settings,
    is_business_hours,
    setting,
)

# Terminal Meta statuses (plus the app-side spellings frappe_whatsapp writes).
_TERMINAL_STATUSES = ("sent", "delivered", "read", "failed", "Success", "Failed", "marked as read")



# ── auto-replies (plan §4) ───────────────────────────────────────────────────

def _auto_reply_kind(conv):
    """Which canned reply, if any, this inbound message earns.

    Returns "welcome", "out_of_hours", "welcome+out_of_hours" or "".
    Re-checked inside the job under a row lock — this is only the cheap
    pre-filter that avoids enqueueing a no-op.
    """
    settings = get_inbox_settings()
    parts = []
    if cint(settings.get("enable_welcome")) and not conv.welcome_sent_at:
        parts.append("welcome")
    if cint(settings.get("enable_out_of_hours")) and not is_business_hours(settings=settings):
        throttle = cint(settings.get("out_of_hours_throttle_hours") or 0)
        last = conv.last_out_of_hours_reply_at
        if not last or not throttle:
            parts.append("out_of_hours")
        elif now_datetime() >= add_to_date(get_datetime(last), hours=throttle):
            parts.append("out_of_hours")
    return "+".join(parts)


def send_auto_reply(conversation, kind=None):
    """RQ job: send the welcome and/or out-of-hours reply.

    Runs out-of-process and after commit because the Outgoing insert talks to
    Meta synchronously in `before_insert` and throws on failure. The
    conversation is re-read `for_update=True` so a burst of five inbound
    messages cannot produce five welcome messages.
    """
    try:
        conv = frappe.get_doc("WhatsApp Conversation", conversation, for_update=True)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp auto-reply: conversation missing")
        return

    settings = get_inbox_settings()
    wanted = set((kind or _auto_reply_kind(conv)).split("+")) - {""}
    if not wanted:
        frappe.db.commit()
        return

    # Re-verify under the lock.
    send_welcome = "welcome" in wanted and cint(settings.get("enable_welcome")) and not conv.welcome_sent_at
    send_ooh = "out_of_hours" in wanted and cint(settings.get("enable_out_of_hours"))
    if send_ooh:
        throttle = cint(settings.get("out_of_hours_throttle_hours") or 0)
        last = conv.last_out_of_hours_reply_at
        if last and throttle and now_datetime() < add_to_date(get_datetime(last), hours=throttle):
            send_ooh = False

    if not (send_welcome or send_ooh):
        frappe.db.commit()
        return

    lang = (conv.customer_language or settings.get("default_language") or "en").lower()
    suffix = "ar" if lang == "ar" else "en"

    parts = []
    if send_welcome:
        parts.append((settings.get(f"welcome_text_{suffix}") or "").strip())
    if send_ooh:
        parts.append((settings.get(f"out_of_hours_text_{suffix}") or "").strip())
    text = "\n\n".join(p for p in parts if p)
    if not text:
        frappe.db.commit()
        return

    # Stamp BEFORE the send: an exception inside Meta's call must not leave
    # the conversation eligible for a retry storm of welcome messages.
    stamps = {}
    now = now_datetime()
    if send_welcome:
        stamps["welcome_sent_at"] = now
    if send_ooh:
        stamps["last_out_of_hours_reply_at"] = now
    frappe.db.set_value("WhatsApp Conversation", conv.name, stamps, update_modified=False)
    frappe.db.commit()

    try:
        message = frappe.get_doc(
            {
                "doctype": "WhatsApp Message",
                "type": "Outgoing",
                "to": conv.phone,
                "content_type": "text",
                "message": text,
                "whatsapp_account": conv.whatsapp_account,
                "custom_conversation": conv.name,
                "custom_is_auto": 1,
                "custom_read": 1,
            }
        )
        message.flags.ignore_permissions = True
        message.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(
            frappe.get_traceback(), f"WhatsApp auto-reply failed for {conversation}"
        )


# ── scheduled jobs (cron */5, registered in hooks.py) ────────────────────────

def privatize_sent_outbound_media():
    """Flip outbound media files private once Meta is done fetching them.

    Outbound attachments MUST be public at send time — frappe_whatsapp hands
    Meta `get_url() + attach` as a link Meta downloads itself. This job closes
    that window ~10 minutes after a terminal status, and only when
    `privatize_outbound_after_sent` is on (off in M1, on in M6).
    """
    try:
        if not cint(setting("privatize_outbound_after_sent", 0)):
            return
        cutoff = add_to_date(now_datetime(), minutes=-10)
        rows = frappe.get_all(
            "WhatsApp Message",
            filters={
                "type": "Outgoing",
                "attach": ["is", "set"],
                "custom_media_private": 0,
                "custom_conversation": ["is", "set"],
                "status": ["in", list(_TERMINAL_STATUSES)],
                "creation": ["<", cutoff],
            },
            fields=["name", "attach"],
            limit_page_length=200,
        )
        for row in rows:
            try:
                _privatize_outbound_row(row)
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"WhatsApp inbox: outbound privatize failed for {row['name']}",
                )
        if rows:
            frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: privatize_sent_outbound_media")


def _privatize_outbound_row(row):
    file_name = frappe.db.get_value("File", {"file_url": row["attach"]}, "name")
    if not file_name:
        frappe.db.set_value(
            "WhatsApp Message", row["name"], "custom_media_private", 1, update_modified=False
        )
        return
    file_doc = frappe.get_doc("File", file_name)
    if not file_doc.is_private:
        file_doc.is_private = 1
        file_doc.save(ignore_permissions=True)
    frappe.db.set_value(
        "WhatsApp Message",
        row["name"],
        {"attach": file_doc.file_url, "custom_media_private": 1},
        update_modified=False,
    )


def auto_resolve_stale_conversations():
    """Close threads nobody has touched for `auto_resolve_after_days` (0=off)."""
    try:
        days = cint(setting("auto_resolve_after_days", 0))
        if days <= 0:
            return
        cutoff = add_to_date(now_datetime(), days=-days)
        rows = frappe.get_all(
            "WhatsApp Conversation",
            filters={"status": ["in", ["Open", "Pending"]], "last_message_at": ["<", cutoff]},
            fields=["name"],
            limit_page_length=200,
        )
        for row in rows:
            frappe.db.set_value(
                "WhatsApp Conversation",
                row["name"],
                {
                    "status": "Resolved",
                    "resolved_at": now_datetime(),
                    "resolved_by": None,
                    "awaiting_reply_since": None,
                },
                update_modified=False,
            )
        if rows:
            frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: auto_resolve_stale_conversations")

"""
Document hooks for the WhatsApp team inbox.

Registered in hooks.py against frappe_whatsapp's `WhatsApp Message`:

    after_insert -> on_message_after_insert   (inbound + outbound bookkeeping)
    on_update    -> on_message_on_update      (Meta status ticks)

**Every step is individually wrapped in try/except + log_error.** These hooks
run inside Meta's webhook request; an exception here would roll back the
`WhatsApp Message` insert, Meta would see a 500 and retry-storm, and the
message would be lost. A broken conversation counter is always preferable to
a dropped customer message.

The auto-reply is the one thing that must NOT run inline: composing the reply
inserts an Outgoing `WhatsApp Message`, whose `before_insert` calls Meta
synchronously and `frappe.throw`s on any API error. So it is enqueued with
`enqueue_after_commit=True` onto the short queue — see `whatsapp_jobs`,
which also owns the two `*/5` cron sweeps.
"""

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from opportunity_management.opportunity_management import whatsapp_crm
from opportunity_management.opportunity_management import whatsapp_jobs
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_utils import (
    detect_language,
    inbox_users,
    normalize_body,
    normalize_phone,
    setting,
)

PREVIEW_LENGTH = 120


# ── serializer aliases (one implementation, whatsapp_serializers) ────────────

def _conv_row(conv):
    return S.conv_row(conv)


def _thread_item(row, kind="message", **kwargs):
    return S.thread_item(row, kind=kind, **kwargs)


# ── entry points ─────────────────────────────────────────────────────────────

def on_message_after_insert(doc, method=None):
    """Thread a freshly inserted WhatsApp Message (plan §1.4)."""
    try:
        incoming = (doc.get("type") or "") == "Incoming"
        raw_number = doc.get("from") if incoming else doc.get("to")
        phone = normalize_phone(raw_number)
        if not phone:
            return
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: phone normalization failed")
        return

    conv = None
    try:
        conv = upsert_conversation(
            phone,
            doc.get("whatsapp_account"),
            profile_name=doc.get("profile_name"),
            language=detect_language(doc.get("message")) if incoming else None,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: conversation upsert failed")
        return
    if not conv:
        return

    body_text = ""
    try:
        body_text = normalize_body(doc)
        frappe.db.set_value(
            "WhatsApp Message",
            doc.name,
            {
                "custom_conversation": conv.name,
                "custom_body_text": body_text,
                "custom_read": 0 if incoming else 1,
            },
            update_modified=False,
        )
        doc.custom_conversation = conv.name
        doc.custom_body_text = body_text
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: message stamping failed")

    try:
        _apply_message_to_conversation(conv, doc, incoming, body_text)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: conversation update failed")

    if incoming:
        try:
            _privatize_inbound_media(doc)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: media privatization failed")

        try:
            if not (conv.contact or conv.lead or conv.customer):
                whatsapp_crm.apply_crm_match(conv)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: CRM auto-link failed")

    try:
        publish_inbox_event("message", conv, item=S.message_item(doc))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: realtime publish failed")

    if incoming:
        try:
            _push_inbound(conv, doc)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: FCM dispatch failed")

        try:
            kind = whatsapp_jobs._auto_reply_kind(conv)
            if kind:
                frappe.enqueue(
                    "opportunity_management.opportunity_management.whatsapp_jobs.send_auto_reply",
                    queue="short",
                    enqueue_after_commit=True,
                    conversation=conv.name,
                    kind=kind,
                )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: auto-reply enqueue failed")


def on_message_on_update(doc, method=None):
    """Meta status callbacks land here.

    frappe_whatsapp's `update_message_status` does `doc.save(ignore_permissions=True)`
    so `on_update` fires for every sent/delivered/read/failed tick. We only
    republish the tick — nothing is written, which keeps this cheap and
    keeps `doc.save()` from recursing.
    """
    try:
        if not doc.get("custom_conversation"):
            return
        if not doc.has_value_changed("status"):
            return
        conv = frappe.get_doc("WhatsApp Conversation", doc.custom_conversation)
        publish_inbox_event(
            "status",
            conv,
            extra={"message_id": doc.get("message_id"), "status": doc.get("status")},
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: status tick publish failed")


# ── conversation upsert ──────────────────────────────────────────────────────

def upsert_conversation(phone, account, profile_name=None, language=None, notify=True):
    """Get-or-create the thread for (account, phone).

    `conversation_key` is unique, so two webhook workers racing on the first
    message of a new customer both try to insert; the loser catches
    DuplicateEntryError and re-reads. `notify=False` is what the backfill
    patch passes so importing 138 rows of history sends no push and no
    realtime event.
    """
    phone = normalize_phone(phone)
    if not phone:
        return None
    key = "{0}:{1}".format(account or "", phone)

    name = frappe.db.get_value("WhatsApp Conversation", {"conversation_key": key}, "name")
    if name:
        conv = frappe.get_doc("WhatsApp Conversation", name)
        updates = {}
        if profile_name and (not conv.display_name or conv.display_name == conv.phone):
            updates["display_name"] = profile_name
        if language and not conv.customer_language:
            updates["customer_language"] = language
        if updates:
            for field, value in updates.items():
                conv.set(field, value)
            frappe.db.set_value("WhatsApp Conversation", conv.name, updates, update_modified=False)
        return conv

    now = now_datetime()
    try:
        conv = frappe.get_doc(
            {
                "doctype": "WhatsApp Conversation",
                "phone": phone,
                "display_name": profile_name or phone,
                "whatsapp_account": account,
                "status": "Open",
                "first_contact_at": now,
                "customer_language": language or "",
                "unread_count": 0,
                "notes_count": 0,
            }
        )
        conv.flags.ignore_permissions = True
        conv.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        # Two webhook workers raced on the first message of a new customer.
        # The unique `conversation_key` picked a winner; re-read its row.
        name = frappe.db.get_value("WhatsApp Conversation", {"conversation_key": key}, "name")
        if not name:
            raise
        return frappe.get_doc("WhatsApp Conversation", name)

    if notify:
        try:
            publish_inbox_event("conversation", conv)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), "WhatsApp inbox: new-conversation publish failed"
            )
    return conv


def _apply_message_to_conversation(conv, doc, incoming, body_text):
    """Step 4 of plan §1.4 — the counters the inbox list is rendered from."""
    now = now_datetime()
    preview = (body_text or "")[:PREVIEW_LENGTH]
    values = {
        "last_message_at": now,
        "last_message_preview": preview,
        "last_message_direction": "In" if incoming else "Out",
    }

    if incoming:
        values["last_inbound_at"] = now
        values["unread_count"] = cint(conv.unread_count) + 1
        if not conv.awaiting_reply_since:
            values["awaiting_reply_since"] = now
        if conv.status == "Resolved":
            # The customer came back — a resolved thread must reopen, or it
            # stays invisible in every agent's list.
            values["status"] = "Open"
            values["resolved_at"] = None
            values["resolved_by"] = None
        elif conv.status == "Pending":
            values["status"] = "Open"
        if not conv.customer_language:
            detected = detect_language(doc.get("message"))
            if detected:
                values["customer_language"] = detected
    else:
        values["last_outbound_at"] = now
        agent_reply = bool(doc.get("custom_sent_by")) and not cint(doc.get("custom_is_auto"))
        if agent_reply:
            if conv.awaiting_reply_since and not cint(conv.first_response_seconds):
                delta = (now - get_datetime(conv.awaiting_reply_since)).total_seconds()
                values["first_response_seconds"] = int(max(delta, 0))
            values["awaiting_reply_since"] = None
            if conv.status == "Open":
                values["status"] = "Pending"

    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)


# ── media ────────────────────────────────────────────────────────────────────

def _privatize_inbound_media(doc):
    """frappe_whatsapp saves inbound media as a **public** File, i.e. anyone
    with the URL can read a customer's photo. Flip it private on arrival.

    Frappe serves /private/files/… only to users who pass
    `File.has_permission`, which delegates to the attached
    `WhatsApp Message` — satisfied by the Agent/Manager read DocPerm.
    """
    if not doc.get("attach"):
        return
    if cint(doc.get("custom_media_private")):
        return
    if not cint(setting("privatize_inbound_media", 1)):
        return

    file_name = frappe.db.get_value(
        "File",
        {"attached_to_doctype": "WhatsApp Message", "attached_to_name": doc.name},
        "name",
    )
    if not file_name:
        return
    file_doc = frappe.get_doc("File", file_name)
    if file_doc.is_private:
        new_url = file_doc.file_url
    else:
        file_doc.is_private = 1
        file_doc.save(ignore_permissions=True)
        new_url = file_doc.file_url

    frappe.db.set_value(
        "WhatsApp Message",
        doc.name,
        {"attach": new_url, "custom_media_private": 1},
        update_modified=False,
    )
    doc.attach = new_url
    doc.custom_media_private = 1


# ── notifications ────────────────────────────────────────────────────────────

def publish_inbox_event(event, conv, item=None, extra=None):
    """Fan a realtime payload out to every inbox user + the assignee.

    The team is small enough that per-user publishes beat inventing a custom
    socket.io room, and `user=` is the only room Frappe gives us that a Desk
    client is guaranteed to have joined.
    """
    payload = {"event": event, "conversation": S.conv_row(conv)}
    if item is not None:
        payload["item"] = item
    if extra:
        payload.update(extra)

    recipients = set(inbox_users())
    if conv.get("assigned_to"):
        recipients.add(conv.get("assigned_to"))
    for user in recipients:
        try:
            frappe.publish_realtime("whatsapp_inbox", payload, user=user)
        except Exception:
            continue


def _push_inbound(conv, doc):
    """FCM for an inbound message: the assignee always; the whole team when
    the thread is unassigned and the throttle has elapsed."""
    from opportunity_management.opportunity_management import notification_templates as T
    from opportunity_management.opportunity_management.business_hooks import _send_to_users

    seen = set()
    if conv.assigned_to:
        title, body, data = T.whatsapp_inbound(conv, doc)
        _send_to_users([conv.assigned_to], title, body, data, dedupe_seen=seen)
        return

    if not cint(setting("notify_team_on_unassigned", 1)):
        return

    throttle = cint(setting("team_alert_throttle_minutes", 10))
    if throttle and conv.last_team_alert_at:
        next_allowed = add_to_date(get_datetime(conv.last_team_alert_at), minutes=throttle)
        if now_datetime() < next_allowed:
            return

    title, body, data = T.whatsapp_inbound(conv, doc)
    _send_to_users(inbox_users(), title, body, data, dedupe_seen=seen)
    stamp = now_datetime()
    conv.last_team_alert_at = stamp
    frappe.db.set_value(
        "WhatsApp Conversation", conv.name, "last_team_alert_at", stamp, update_modified=False
    )

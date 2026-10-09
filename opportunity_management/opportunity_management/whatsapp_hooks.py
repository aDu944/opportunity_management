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

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import whatsapp_crm
from opportunity_management.opportunity_management import whatsapp_jobs
from opportunity_management.opportunity_management import whatsapp_message_extras as X
from opportunity_management.opportunity_management import inbox_referrals as R
from opportunity_management.opportunity_management.whatsapp_chat_state import (
    NO_STATE,
    muted_users,
    states_by_user,
)
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_identity import (
    SENDER_CONTACTS_FLAG,
    STICKER_IDS_FLAG,
    clean_username,
    is_bsuid,
    lookup_sender,
    normalize_wa_identifier,
)
from opportunity_management.opportunity_management.whatsapp_utils import (
    detect_language,
    normalize_body,
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
    if (doc.get("custom_channel") or "") == IC.MESSENGER:  # keyed by PSID, no CRM / auto-reply
        from opportunity_management.opportunity_management.messenger_ingest import after_insert

        return after_insert(doc)
    try:
        incoming = (doc.get("type") or "") == "Incoming"
        raw_number = doc.get("from") if incoming else doc.get("to")
        # A hidden-number customer's BSUID is kept verbatim (see whatsapp_identity).
        phone = normalize_wa_identifier(raw_number)
        if not phone:
            return
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: phone normalization failed")
        return

    sender = {}
    if incoming:
        try:
            # Stashed by the webhook wrapper; absent for messages inserted any
            # other way, which simply means no username update this time.
            sender = lookup_sender(frappe.flags.get(SENDER_CONTACTS_FLAG), raw_number)
        except Exception:
            sender = {}

    # A reaction is its own WhatsApp Message row but not a message: see
    # `_thread_reaction`. An emoji says nothing about the customer's language.
    reaction = (doc.get("content_type") or "") == "reaction"

    conv = None
    try:
        conv = upsert_conversation(
            phone,
            doc.get("whatsapp_account"),
            profile_name=doc.get("profile_name"),
            language=detect_language(doc.get("message")) if incoming and not reaction else None,
            username=sender.get("username"),
            user_id=sender.get("user_id"),
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: conversation upsert failed")
        return
    if not conv:
        return

    if reaction:
        _thread_reaction(conv, doc)
        return

    sticker = False
    if incoming:
        try:
            # The webhook wrapper presented the sticker to upstream as an image.
            sticker = doc.get("message_id") in (frappe.flags.get(STICKER_IDS_FLAG) or ())
            if sticker:
                doc.custom_is_sticker = 1
        except Exception:
            sticker = False

    body_text = ""
    try:
        body_text = normalize_body(doc)
        values = {
            "custom_conversation": conv.name,
            "custom_body_text": body_text,
            "custom_read": 0 if incoming else 1,
        }
        if sticker:
            values["custom_is_sticker"] = 1
        frappe.db.set_value("WhatsApp Message", doc.name, values, update_modified=False)
        doc.custom_conversation = conv.name
        doc.custom_body_text = body_text
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: message stamping failed")

    try:
        if incoming:  # location / contacts: back to a card (custom_payload)
            R.stamp_inbound_referral(conv, doc)  # ad referral; never raises
            X.stamp_inbound_card(doc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: card stamping failed")

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

    It is also where inbound media first has an `attach`: upstream inserts
    the row, then saves the File, then sets `attach` and calls `save()`.
    `whatsapp_media.on_attach_landed` handles that moment (set_value only).
    """
    try:
        if (
            (doc.get("type") or "") == "Incoming"
            and doc.get("custom_conversation")
            and doc.get("attach")
            and doc.has_value_changed("attach")
        ):
            from opportunity_management.opportunity_management import whatsapp_media

            whatsapp_media.on_attach_landed(doc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: attach landing failed")

    try:
        if not doc.get("custom_conversation"):
            return
        if not doc.has_value_changed("status"):
            return
        extra = {"message_id": doc.get("message_id"), "status": doc.get("status")}
        try:
            # Message info: sent/delivered/read times + Meta's failure reason.
            extra.update(X.record_status(doc))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: status stamp failed")
        conv = frappe.get_doc("WhatsApp Conversation", doc.custom_conversation)
        publish_inbox_event("status", conv, extra=extra)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: status tick publish failed")


# ── conversation upsert ──────────────────────────────────────────────────────

def upsert_conversation(
    phone, account, profile_name=None, language=None, notify=True, username=None, user_id=None
):
    """Get-or-create the thread for (account, phone).

    `phone` is the customer identifier: normalized digits, or the verbatim
    BSUID for a customer who hides their number. `username` / `user_id` come
    from the webhook's `contacts[]` and are written whenever they are new or
    changed (a username can change; the latest wins).

    `conversation_key` is unique, so two webhook workers racing on the first
    message of a new customer both try to insert; the loser catches
    DuplicateEntryError and re-reads. `notify=False` is what the backfill
    patch passes so importing 138 rows of history sends no push and no
    realtime event.
    """
    phone = normalize_wa_identifier(phone)
    if not phone:
        return None
    key = "{0}:{1}".format(account or "", phone)
    username = clean_username(username) or None
    user_id = (str(user_id).strip() if user_id else "") or (phone if is_bsuid(phone) else None)

    name = frappe.db.get_value("WhatsApp Conversation", {"conversation_key": key}, "name")
    if not name and is_bsuid(phone):
        # The same customer's earlier thread, keyed on the phone they used to
        # share — keep the history in one place.
        filters = {"wa_user_id": phone}
        if account:
            filters["whatsapp_account"] = account
        name = frappe.db.get_value("WhatsApp Conversation", filters, "name")
    if name:
        conv = frappe.get_doc("WhatsApp Conversation", name)
        updates = {}
        if profile_name and (
            not conv.display_name or conv.display_name == conv.phone or is_bsuid(conv.display_name)
        ):
            updates["display_name"] = profile_name
        if language and not conv.customer_language:
            updates["customer_language"] = language
        if username and conv.get("wa_username") != username:
            updates["wa_username"] = username
        if user_id and conv.get("wa_user_id") != user_id:
            updates["wa_user_id"] = user_id
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
                # Never a raw BSUID as the name — the serializer falls back
                # to @username / "WhatsApp user" instead.
                "display_name": profile_name or ("" if is_bsuid(phone) else phone),
                "wa_username": username,
                "wa_user_id": user_id,
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


def _thread_reaction(conv, doc):
    """A reaction row (either direction) joins the thread but is not a
    message: no preview / last-message / unread / status / first-response
    change, no push, no auto-reply. Meta's rule is that a reaction does not
    open the customer-service window either, so `last_inbound_at` stays put.
    Clients get a `reaction` event to patch the target bubble instead."""
    try:
        frappe.db.set_value(
            "WhatsApp Message",
            doc.name,
            {"custom_conversation": conv.name, "custom_read": 1},
            update_modified=False,
        )
        doc.custom_conversation = conv.name
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: reaction stamping failed")
        return
    try:
        if doc.get("reply_to_message_id"):
            from opportunity_management.opportunity_management import whatsapp_reactions

            whatsapp_reactions.publish_reaction(conv, doc.reply_to_message_id)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: reaction publish failed")


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

    # Only users of this conversation's channel (WhatsApp: inbox_users()).
    recipients = set(IC.channel_users(IC.conv_channel(conv)))
    if IC.reaches_assignee(conv):  # Messenger: only while they hold a Messenger role
        recipients.add(conv.get("assigned_to"))
    # pinned / muted are per user: each recipient gets their own flags.
    states = states_by_user(conv.name)
    for user in recipients:
        try:
            row = dict(payload["conversation"], **states.get(user, NO_STATE))
            frappe.publish_realtime("whatsapp_inbox", dict(payload, conversation=row), user=user)
        except Exception:
            continue


def _push_inbound(conv, doc):
    """FCM for an inbound message: the assignee always; the whole team when
    the thread is unassigned and the throttle has elapsed."""
    from opportunity_management.opportunity_management import notification_templates as T
    from opportunity_management.opportunity_management.business_hooks import _send_to_users

    # A user who muted this thread gets no push (counts are unaffected).
    seen = set(muted_users(conv.name))
    channel = IC.conv_channel(conv)
    if channel == IC.MESSENGER:
        from opportunity_management.opportunity_management.messenger_ingest import inbound_push as build
    else:
        build = T.whatsapp_inbound
    build = R.with_ad(build)  # "Ad: <headline>" + data.ad for an ad-originated message
    frappe.get_attr("opportunity_management.opportunity_management.whatsapp_shareholder_push.notify_shareholders")(conv, *build(conv, doc), seen)
    frappe.get_attr("opportunity_management.opportunity_management.messenger_push.notify_messenger_managers")(conv, *build(conv, doc), seen)
    if conv.assigned_to:
        title, body, data = build(conv, doc)
        _send_to_users([conv.assigned_to], title, body, data, dedupe_seen=seen)
        return

    if not cint(setting("notify_team_on_unassigned", 1)):
        return

    throttle = cint(setting("team_alert_throttle_minutes", 10))
    if throttle and conv.last_team_alert_at:
        next_allowed = add_to_date(get_datetime(conv.last_team_alert_at), minutes=throttle)
        if now_datetime() < next_allowed:
            return

    title, body, data = build(conv, doc)
    _send_to_users(IC.channel_users(channel), title, body, data, dedupe_seen=seen)
    stamp = now_datetime()
    conv.last_team_alert_at = stamp
    frappe.db.set_value(
        "WhatsApp Conversation", conv.name, "last_team_alert_at", stamp, update_modified=False
    )

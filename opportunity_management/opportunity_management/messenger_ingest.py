"""
Messenger events → inbox rows (the webhook side of the Messenger channel).

`handle(event)` takes one normalised event from `messenger_events.parse` and
writes `WhatsApp Conversation` / `WhatsApp Message` rows exactly the way the
WhatsApp channel's are shaped, so every inbox endpoint reads them unchanged:

    message (customer)  Incoming row per text / attachment (dedupe on mid)
    message (echo)      Outgoing row with `custom_payload {"kind": "echo"}`,
                        not sent (a reply typed in Meta Business Suite); an
                        echo of OUR send (metadata marker / known mid) is dropped
    delivery / read     watermark → outgoing rows delivered / read
    reaction            a `reaction` row, like WhatsApp's (chips)
    postback            the button title as an incoming text
    referral            (bare `messaging_referrals`) a System note carrying
                        the ad / link referral (inbox_referrals.on_standalone);
                        a referral on a message / postback rides on its row

`after_insert(doc)` is what `whatsapp_hooks.on_message_after_insert` hands a
Messenger row to: the same unread / preview / reopen / realtime / push
bookkeeping as WhatsApp, but no CRM phone matching and no auto-replies.

Attachment URLs from Meta expire, so the row goes in first and
`download_attachment` (RQ, after commit) saves the file and runs the
WhatsApp attach-landed flow (`whatsapp_media.on_attach_landed`). The
customer's profile (name + picture) is fetched the same way, at most every
`PROFILE_REFRESH_DAYS`.
"""

import os
from urllib.parse import unquote, urlparse

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import messenger_api as API
from opportunity_management.opportunity_management import messenger_events as EV
from opportunity_management.opportunity_management import inbox_referrals as R

MSG = "WhatsApp Message"
CONV = "WhatsApp Conversation"
PROFILE_REFRESH_DAYS = 7
DOWNLOAD_TIMEOUT = 30
_JOB = "opportunity_management.opportunity_management.messenger_ingest."
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
        "video/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac",
        "audio/ogg": ".ogg", "application/pdf": ".pdf"}


def handle(event):
    kind = event.get("kind")
    if kind == "message":
        return _on_message(event)
    if kind == "postback":
        return _on_message(dict(event, attachments=[], reply_to=None, echo=False, ours=False))
    if kind in ("delivery", "read"):
        return _on_watermark(event)
    if kind == "reaction":
        return _on_reaction(event)
    if kind == "referral":
        return R.on_standalone(upsert_conversation(event["psid"], event["page_id"]), event.get("referral"))


# ── conversation ─────────────────────────────────────────────────────────────

def upsert_conversation(psid, page_id, notify=True):
    key = API.conversation_key(page_id, psid)
    name = frappe.db.get_value(CONV, {"conversation_key": key}, "name")
    if name:
        conv = frappe.get_doc(CONV, name)
        _maybe_refresh_profile(conv)
        return conv
    try:
        conv = frappe.get_doc({
            "doctype": CONV,
            "channel": IC.MESSENGER,
            "phone": API.identifier_for(psid),
            "conversation_key": key,
            "display_name": "",
            "status": "Open",
            "first_contact_at": now_datetime(),
            "unread_count": 0,
            "notes_count": 0,
        })
        conv.flags.ignore_permissions = True
        conv.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        name = frappe.db.get_value(CONV, {"conversation_key": key}, "name")
        if not name:
            raise
        return frappe.get_doc(CONV, name)
    _maybe_refresh_profile(conv)
    if notify:
        try:
            from opportunity_management.opportunity_management.whatsapp_hooks import publish_inbox_event

            publish_inbox_event("conversation", conv)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Messenger: new-conversation publish failed")
    return conv


def _find_conversation(psid, page_id):
    name = frappe.db.get_value(CONV, {"conversation_key": API.conversation_key(page_id, psid)}, "name")
    return frappe.get_doc(CONV, name) if name else None


# ── messages ─────────────────────────────────────────────────────────────────

def _known(mid) -> bool:
    return bool(mid) and bool(frappe.db.exists(MSG, {"message_id": mid}))


def _on_message(event):
    mid = event.get("mid")
    if event.get("echo") and (event.get("ours") or _sent_by_us(mid)):
        return
    if _known(mid):
        return
    conv = upsert_conversation(event["psid"], event["page_id"])
    incoming = not event.get("echo")
    rows = [(a["type"], a) for a in event.get("attachments") or []] or [("text", None)]
    text = event.get("text") or ""
    for i, (content_type, att) in enumerate(rows):
        fields = {
            "content_type": content_type,
            "message": text if i == 0 else "",
            # One mid per row: the first keeps Meta's (replies / reactions
            # point at it), the rest are suffixed.
            "message_id": mid if i == 0 or not mid else "{0}:{1}".format(mid, i),
        }
        if att and att.get("sticker"):
            fields["custom_is_sticker"] = 1
        if i == 0 and event.get("reply_to"):
            fields.update({"is_reply": 1, "reply_to_message_id": event["reply_to"]})
        if i == 0 and incoming and event.get("referral"):
            R.remember_messenger(fields["message_id"], event["referral"])  # stamped in after_insert
        doc = _insert(conv, incoming, fields)
        if att and att.get("url"):
            frappe.enqueue(_JOB + "download_attachment", queue="short", enqueue_after_commit=True,
                           message_name=doc.name, url=att["url"])


def _insert(conv, incoming, fields):
    psid_ident = conv.phone
    row = {
        "doctype": MSG,
        "type": "Incoming" if incoming else "Outgoing",
        "custom_channel": IC.MESSENGER,
        "custom_conversation": conv.name,
        "status": "" if incoming else "sent",
    }
    row["from" if incoming else "to"] = psid_ident
    if not incoming:
        # A reply typed in Meta Business Suite: shown, never sent again.
        row["custom_payload"] = '{"kind":"echo"}'
        row["custom_sent_at"] = now_datetime()
    row.update(fields)
    doc = frappe.get_doc(row)
    doc.flags.ignore_permissions = True
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    return doc


def _sent_by_us(mid) -> bool:
    try:
        return bool(mid) and bool(frappe.cache().get_value("messenger_sent_mid:" + mid))
    except Exception:
        return False


def _on_reaction(event):
    conv = _find_conversation(event["psid"], event["page_id"])
    if not conv or not frappe.db.exists(MSG, {"message_id": event["mid"], "custom_conversation": conv.name}):
        return
    _insert(conv, True, {"content_type": "reaction", "message": event.get("emoji") or "",
                         "reply_to_message_id": event["mid"]})


# ── delivery / read ──────────────────────────────────────────────────────────

def _epoch_ms(value):
    from zoneinfo import ZoneInfo

    from frappe.utils import get_system_timezone

    try:
        dt = get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone()))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _on_watermark(event):
    conv = _find_conversation(event["psid"], event["page_id"])
    if not conv:
        return
    target = "delivered" if event["kind"] == "delivery" else "read"
    rows = frappe.get_all(
        MSG,
        filters={"custom_conversation": conv.name, "type": "Outgoing",
                 "status": ["in", ["sent", "Success", "delivered"]]},
        fields=["name", "message_id", "status", "creation"],
        order_by="creation desc", limit_page_length=200,
    )
    for row in rows:
        row["sent_ms"] = _epoch_ms(row.get("creation"))
    names = EV.watermark_targets(rows, target, event.get("watermark"), event.get("mids") or ())
    from opportunity_management.opportunity_management.whatsapp_hooks import publish_inbox_event

    now = now_datetime()
    for row in rows:
        if row["name"] not in names:
            continue
        values = {"status": target}
        if frappe.db.has_column(MSG, "custom_delivered_at"):
            values["custom_delivered_at"] = now
            if target == "read":
                values["custom_read_at"] = now
            existing = frappe.db.get_value(MSG, row["name"], ["custom_delivered_at"], as_dict=True)
            if existing and existing.custom_delivered_at:
                values.pop("custom_delivered_at")
        frappe.db.set_value(MSG, row["name"], values, update_modified=False)
        extra = {"message_id": row["message_id"], "status": target}
        for key, value in values.items():
            if key != "status":
                extra[key.replace("custom_", "", 1)] = str(value)[:19]
        try:
            publish_inbox_event("status", conv, extra=extra)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Messenger: status publish failed")


# ── after_insert (from whatsapp_hooks) ───────────────────────────────────────

def after_insert(doc):
    """Bookkeeping for a Messenger row, mirroring the WhatsApp hook step by
    step (each step isolated: never lose a customer message to a counter)."""
    from opportunity_management.opportunity_management import whatsapp_hooks as H
    from opportunity_management.opportunity_management import whatsapp_serializers as S
    from opportunity_management.opportunity_management.whatsapp_utils import normalize_body

    try:
        conv = frappe.get_doc(CONV, doc.get("custom_conversation"))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Messenger: row without conversation")
        return
    incoming = doc.get("type") == "Incoming"
    if (doc.get("content_type") or "") == "reaction":
        H._thread_reaction(conv, doc)
        return
    body_text = ""
    try:
        body_text = normalize_body(doc)
        values = {"custom_body_text": body_text, "custom_read": 0 if incoming else 1}
        frappe.db.set_value(MSG, doc.name, values, update_modified=False)
        doc.custom_body_text, doc.custom_read = body_text, values["custom_read"]
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Messenger: message stamping failed")
    if incoming:
        R.stamp_inbound_referral(conv, doc)  # ad / link referral; never raises
    try:
        H._apply_message_to_conversation(conv, doc, incoming, body_text)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Messenger: conversation update failed")
    try:
        H.publish_inbox_event("message", conv, item=S.message_item(doc))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Messenger: realtime publish failed")
    if incoming:
        try:
            H._push_inbound(conv, doc)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Messenger: FCM dispatch failed")


def display_name(conv) -> str:
    from opportunity_management.opportunity_management.whatsapp_identity import display_label

    return display_label(conv.get("display_name"), conv.get("phone"), None, "Messenger user").strip()


def inbound_push(conv, doc):
    """The WhatsApp push, re-titled for Messenger (`data.channel`)."""
    from opportunity_management.opportunity_management import notification_templates as T

    _title, body, data = T.whatsapp_inbound(conv, doc)
    text = body.split("\n", 1)[1] if "\n" in body else body
    data["channel"] = IC.MESSENGER
    return "💬 Messenger", "{0}\n{1}".format(display_name(conv), text), data


# ── background jobs ──────────────────────────────────────────────────────────

def _file_name(url, mime, fallback):
    base = os.path.basename(unquote(urlparse(url or "").path)) or fallback
    stem, ext = os.path.splitext(base)
    if not ext:
        ext = _EXT.get((mime or "").split(";")[0].strip().lower(), "")
    return (stem or fallback)[:80] + ext


def _download(url, limit):
    import requests

    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)
    response.raise_for_status()
    chunks, size = [], 0
    for chunk in response.iter_content(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise ValueError("attachment larger than {0} bytes".format(limit))
        chunks.append(chunk)
    return b"".join(chunks), response.headers.get("content-type") or ""


def download_attachment(message_name, url):
    """RQ: fetch an expiring Meta attachment URL into a File on the row and
    run the WhatsApp attach-landed flow (privatise / body / publish / audio)."""
    try:
        from opportunity_management.opportunity_management import whatsapp_media as M

        doc = frappe.get_doc(MSG, message_name)
        if doc.get("attach"):
            return
        content, mime = _download(url, API.MAX_ATTACHMENT_MB * 1024 * 1024)
        private = 1 if (doc.type == "Outgoing" or M.privacy_on()) else 0
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": _file_name(url, mime, doc.content_type or "file"),
            "attached_to_doctype": MSG,
            "attached_to_name": doc.name,
            "attached_to_field": "attach",
            "is_private": private,
            "content": content,
        })
        file_doc.save(ignore_permissions=True)
        values = {"attach": file_doc.file_url, "custom_media_private": private}
        frappe.db.set_value(MSG, doc.name, values, update_modified=False)
        doc.update(values)
        if doc.type == "Incoming":
            M.on_attach_landed(doc)
        else:
            M.publish_message_update(doc, frappe.get_doc(CONV, doc.custom_conversation))
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Messenger: attachment download failed for " + str(message_name))


def _maybe_refresh_profile(conv):
    last = conv.get("profile_fetched_at")
    if last and get_datetime(last) > add_to_date(now_datetime(), days=-PROFILE_REFRESH_DAYS):
        return
    try:
        frappe.enqueue(_JOB + "refresh_profile", queue="short", enqueue_after_commit=True,
                       conversation=conv.name)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Messenger: profile enqueue failed")


def refresh_profile(conversation):
    """RQ: name + picture from the User Profile API. Never raises."""
    try:
        conv = frappe.get_doc(CONV, conversation)
        values = {"profile_fetched_at": now_datetime()}
        try:
            profile = API.graph_request(IC.messenger_settings(), "GET", API.psid_of(conv.phone),
                                        params={"fields": "first_name,last_name,profile_pic"})
        except API.GraphError as exc:
            # e.g. 2018218 "No profile available" (phone-only accounts) or a
            # missing Business Asset User Profile Access feature.
            profile = {}
            # Keyword args: a single-line first positional is taken as the
            # *title* by frappe.log_error and overflows its 140 chars.
            frappe.log_error(title="Messenger: profile fetch failed",
                             message=f"{conv.phone}: {exc}")
        name = " ".join(p for p in (profile.get("first_name"), profile.get("last_name")) if p).strip()
        if name and (not conv.display_name or conv.display_name == conv.phone):
            values["display_name"] = name
        if profile.get("profile_pic"):
            url = _save_avatar(conv, profile["profile_pic"])
            if url:
                values["avatar_url"] = url
        frappe.db.set_value(CONV, conv.name, values, update_modified=False)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Messenger: profile refresh failed")


def _save_avatar(conv, url):
    try:
        content, mime = _download(url, 5 * 1024 * 1024)
    except Exception:
        return None
    old = conv.get("avatar_url")
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": _file_name("", mime or "image/jpeg", "avatar-" + conv.name),
        "attached_to_doctype": CONV,
        "attached_to_name": conv.name,
        "is_private": 1,
        "content": content,
    })
    file_doc.save(ignore_permissions=True)
    if old and old != file_doc.file_url:
        for name in frappe.get_all("File", filters={"file_url": old, "attached_to_name": conv.name}, pluck="name"):
            frappe.delete_doc("File", name, ignore_permissions=True, force=True)
    return file_doc.file_url


def stamp_webhook(error=None):
    try:
        values = {"last_webhook_at": now_datetime()}
        if error is not None:
            values["last_error"] = str(error)[:1000]
        for field, value in values.items():
            frappe.db.set_single_value("Messenger Settings", field, value)
    except Exception:
        pass

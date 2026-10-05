"""
Ad referrals in the team inbox — the frappe side (ad_referral_contract.md).
The pure parsing / shaping lives in `ad_referrals`.

Flow, both channels:

1. Webhook side: the referral of each inbound message is stashed in
   `frappe.flags[REFERRALS_FLAG]` keyed by message id (WhatsApp: the wrapper
   walks the payload, `stash_whatsapp`; Messenger: `messenger_ingest` calls
   `remember_messenger` right before inserting the row).
2. after_insert (`stamp_inbound_referral`): the referral is written to
   `WhatsApp Message.custom_referral`, the conversation's `ad_referral` /
   `ad_headline` / `ad_id` are updated, and the preview picture is queued.
3. `download_preview` (RQ, after commit) saves Meta's expiring preview as a
   private File and puts its path into `image_url`, then republishes.

A bare Messenger `referral` event (an existing customer reopened the chat
from an ad / m.me link) becomes a System note carrying the referral
(`on_standalone`). Nothing here may fail a webhook: every entry point
catches and logs.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from opportunity_management.opportunity_management import ad_referrals as AR

MSG = "WhatsApp Message"
CONV = "WhatsApp Conversation"
NOTE = "WhatsApp Internal Note"
REFERRALS_FLAG = "inbox_inbound_referrals"
MSG_FIELD = "custom_referral"
NOTE_FIELD = "referral"
PREVIEW_MAX_BYTES = 5 * 1024 * 1024
DATA_MAX = 140  # Data column width
_JOB = "opportunity_management.opportunity_management.inbox_referrals.download_preview"


def _has(doctype, field) -> bool:
    try:
        return bool(frappe.db.has_column(doctype, field))
    except Exception:
        return False


# ── 1. webhook side ──────────────────────────────────────────────────────────

def _remember(key, ref, preview):
    pending = frappe.flags.get(REFERRALS_FLAG)
    if not isinstance(pending, dict):
        pending = frappe.flags[REFERRALS_FLAG] = {}
    pending[key or ""] = (ref, preview or "")


def stash_whatsapp(data):
    """WhatsApp wrapper: remember every `messages[].referral` by wamid."""
    try:
        for mid, (ref, preview) in AR.referrals_in_payload(data).items():
            _remember(mid, ref, preview)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: referral stash failed")


def remember_messenger(mid, raw):
    """Messenger ingest: the referral of the row about to be inserted."""
    try:
        ref = AR.from_messenger(raw)
        if ref:
            _remember(mid, ref, AR.messenger_preview(raw))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Messenger: referral parse failed")


# ── 2. after_insert ──────────────────────────────────────────────────────────

def stamp_inbound_referral(conv, doc):
    """Persist the stashed referral of `doc` (an inbound row). Never raises."""
    try:
        pending = frappe.flags.get(REFERRALS_FLAG)
        if not isinstance(pending, dict):
            return
        found = pending.pop(doc.get("message_id") or "", None)
        if not found:
            return
        ref, preview = found
        ref = dict(ref, channel=conv.get("channel") or "WhatsApp")
        raw = AR.dump(ref)
        if _has(MSG, MSG_FIELD):
            frappe.db.set_value(MSG, doc.name, MSG_FIELD, raw, update_modified=False)
        doc.set(MSG_FIELD, raw)
        update_conversation(conv, ref, now_datetime())
        _enqueue_preview(MSG, doc.name, preview, conv.name)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Inbox: referral stamping failed")


def update_conversation(conv, ref, at):
    """The conversation's latest referral (ConvRow `ad`), headline and ad id."""
    if not _has(CONV, "ad_referral"):
        return
    values = {
        "ad_referral": AR.dump(AR.conv_ad(ref, at)),
        "ad_headline": (ref.get("headline") or "")[:DATA_MAX],
        "ad_id": (ref.get("ad_id") or "")[:DATA_MAX],
    }
    frappe.db.set_value(CONV, conv.name, values, update_modified=False)
    for field, value in values.items():
        conv.set(field, value)


def on_standalone(conv, raw):
    """A bare Messenger referral: a System note carrying it. Never raises."""
    try:
        ref = AR.from_messenger(raw)
        if not conv or not ref:
            return
        ref = dict(ref, channel=conv.get("channel") or "Messenger")
        stored = AR.dump(ref)
        text = AR.note_text(ref)
        if _recent_duplicate(conv.name, text, stored):
            return  # Meta re-delivered the same event
        from opportunity_management.opportunity_management.whatsapp_api_common import _note

        note = _note(conv.name, text, note_type="System", author="")
        if _has(NOTE, NOTE_FIELD):
            frappe.db.set_value(NOTE, note.name, NOTE_FIELD, stored, update_modified=False)
        note.set(NOTE_FIELD, stored)
        update_conversation(conv, ref, now_datetime())
        _enqueue_preview(NOTE, note.name, AR.messenger_preview(raw), conv.name)
        _publish(conv, NOTE, note)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Messenger: referral note failed")


def _recent_duplicate(conversation, text, stored) -> bool:
    filters = {
        "conversation": conversation,
        "note_type": "System",
        "text": text,
        "creation": [">", add_to_date(now_datetime(), minutes=-5)],
    }
    if _has(NOTE, NOTE_FIELD):
        filters[NOTE_FIELD] = stored
    return bool(frappe.db.exists(NOTE, filters))


def _publish(conv, doctype, doc):
    from opportunity_management.opportunity_management import whatsapp_serializers as S
    from opportunity_management.opportunity_management.whatsapp_hooks import publish_inbox_event

    try:
        item = S.note_item(doc) if doctype == NOTE else S.message_item(doc)
        publish_inbox_event("message", conv, item=item)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Inbox: referral publish failed")


# ── 3. preview picture ───────────────────────────────────────────────────────

def _enqueue_preview(doctype, name, url, conversation):
    if not url:
        return
    frappe.enqueue(_JOB, queue="short", enqueue_after_commit=True,
                   doctype=doctype, name=name, url=url, conversation=conversation)


def download_preview(doctype, name, url, conversation):
    """RQ: Meta's expiring preview → private File → `image_url`. Image types
    only, at most 5 MB. A failure leaves `image_url` "" (logged)."""
    try:
        from opportunity_management.opportunity_management import messenger_ingest as MI

        field = NOTE_FIELD if doctype == NOTE else MSG_FIELD
        if not AR.http_url(url) or not _has(doctype, field):
            return
        ref = AR.decode_json(frappe.db.get_value(doctype, name, field))
        if not ref or ref.get("image_url"):
            return
        content, mime = MI._download(url, PREVIEW_MAX_BYTES)
        mime = (mime or "").split(";")[0].strip().lower()
        if not mime.startswith("image/") or not content:
            return
        # A standalone referral's note has no attach slot of its own: the
        # picture belongs to the conversation, like the Messenger avatar.
        attach_to = (CONV, conversation) if doctype == NOTE else (doctype, name)
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": MI._file_name(url, mime, "ad-preview"),
            "attached_to_doctype": attach_to[0],
            "attached_to_name": attach_to[1],
            "is_private": 1,
            "content": content,
        })
        file_doc.save(ignore_permissions=True)
        ref["image_url"] = file_doc.file_url
        frappe.db.set_value(doctype, name, field, AR.dump(ref), update_modified=False)
        conv = frappe.get_doc(CONV, conversation)
        _patch_conversation_image(conv, ref)
        frappe.db.commit()
        # The `message` event carries the ConvRow too, so the list's / side
        # panel's `ad` picks up the picture from the same publish.
        _publish(conv, doctype, frappe.get_doc(doctype, name))
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Inbox: referral preview download failed")


def _patch_conversation_image(conv, ref):
    """The conversation's `ad` gets the picture too while it is still this
    referral (a newer one may have replaced it meanwhile)."""
    current = AR.decode_json(conv.get("ad_referral"))
    if not current or current.get("image_url"):
        return
    if any((current.get(k) or "") != (ref.get(k) or "") for k in ("source", "ad_id", "headline")):
        return
    current["image_url"] = ref["image_url"]
    raw = AR.dump(current)
    frappe.db.set_value(CONV, conv.name, "ad_referral", raw, update_modified=False)
    conv.set("ad_referral", raw)


# ── read side ────────────────────────────────────────────────────────────────

def list_select(alias) -> str:
    """`ad_referral` for the list query (NULL before the migrate), with the
    trailing comma."""
    if not _has(CONV, "ad_referral"):
        return "NULL AS ad_referral, "
    return "{0}.ad_referral, ".format(alias)


def search_sql(alias) -> str:
    """Extra OR for the list search (placeholder only — no literal %)."""
    if not _has(CONV, "ad_headline"):
        return ""
    return "\n                OR {0}.ad_headline LIKE %(search)s".format(alias)


def conv_list_fields() -> list:
    return ["ad_referral"] if _has(CONV, "ad_referral") else []


def note_fields(base) -> list:
    return list(base) + ([NOTE_FIELD] if _has(NOTE, NOTE_FIELD) else [])


def with_ad(build):
    """Wrap a push builder `(conv, doc) -> (title, body, data)` so a message
    that came from an ad gets the `Ad: <headline>` line and `data.ad`."""
    def wrapped(conv, doc):
        title, body, data = build(conv, doc)
        try:
            ref = AR.public(doc.get(MSG_FIELD))
            if ref:
                return AR.add_to_push(title, body, data, ref)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Inbox: referral push line failed")
        return title, body, data

    return wrapped

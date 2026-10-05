"""
Round-3 send endpoints of the WhatsApp inbox API: voice notes, location and
contact cards, interactive options and forwarding.

All of them follow `send_message`'s rules through `_open_for_send` +
`_insert` (inbox access, refuse a blocked contact, `_auto_claim`, the 24h
window → `WindowClosedError`, and on a Meta rejection: rollback, a Failed
Send note, `MetaSendError`).

Location / contact / voice rows are sent by `whatsapp_message_override`
(upstream has no branch for them); the row's `custom_payload` carries what
to send. Options use upstream's own `interactive` branch via `buttons`.

Re-exported by `whatsapp_api.py`, which is the path clients call.
"""

import os
from urllib.parse import unquote

import frappe
from frappe import _
from frappe.utils import cint

from opportunity_management.opportunity_management import whatsapp_payloads as P
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _channel_fields,
    _get_conv,
    _refuse_blocked,
    _refuse_cap,
    _window_closed_message,
    _require_inbox_access,
    MetaSendError,
    WindowClosedError,
)
from opportunity_management.opportunity_management.whatsapp_api_messages import (
    _auto_claim,
    _content_type_for,
    _is_window_error,
    _record_failed_send,
)
from opportunity_management.opportunity_management.whatsapp_media import (
    check_video_size,
    public_copy,
)
from opportunity_management.opportunity_management.whatsapp_utils import strip_html

# Kinds `forward_message` accepts (contract); stickers and cards are refused.
FORWARDABLE = ("text", "image", "video", "document", "audio")
# A recording already in one of these plays on iPhone as-is.
PLAYABLE_EXTENSIONS = (".m4a", ".mp3", ".aac", ".mp4")


def _throw_payload(exc):
    # PayloadError messages are written for the agent (whatsapp_payloads).
    frappe.throw(str(exc))


# ── shared send path ─────────────────────────────────────────────────────────

def _open_for_send(conversation, cap=None, label=None):
    """`cap`: the `caps` key this send needs (Messenger has no location /
    contact cards); refused before anything is claimed."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    if cap:
        _refuse_cap(conv, cap, label or cap)
    _refuse_blocked(conv)
    _auto_claim(conv)
    if not conv.window_open():
        frappe.throw(_window_closed_message(conv), exc=WindowClosedError)
    return conv


def _insert(conv, fields, note_text, reply_to=None):
    """Insert (= send) one Outgoing row; the ThreadItem, or a typed error."""
    payload = {
        "doctype": "WhatsApp Message",
        "type": "Outgoing",
        "to": conv.phone,
        "whatsapp_account": conv.whatsapp_account,
        "custom_conversation": conv.name,
        "custom_sent_by": frappe.session.user,
        "custom_read": 1,
    }
    payload.update(_channel_fields(conv))
    payload.update(fields)
    if reply_to:
        payload["is_reply"] = 1
        payload["reply_to_message_id"] = reply_to
    try:
        doc = frappe.get_doc(payload)
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
    except Exception as exc:
        _record_failed_send(conv.name, note_text, exc)
        if _is_window_error(exc):
            frappe.throw(
                _("The 24-hour reply window has closed. Send an approved template."),
                exc=WindowClosedError,
            )
        if isinstance(exc, MetaSendError):  # Messenger: already worded
            frappe.throw(str(exc)[:400], exc=MetaSendError)
        frappe.throw(_("WhatsApp rejected the message: {0}").format(str(exc)[:300]), exc=MetaSendError)
    return S.message_item(doc)


# ── location / contact / options ─────────────────────────────────────────────

@frappe.whitelist()
def send_location(conversation, latitude, longitude, name=None, address=None, reply_to=None):
    try:
        card = P.location_card(latitude, longitude, name, address)
    except P.PayloadError as exc:
        _throw_payload(exc)
    conv = _open_for_send(conversation, "location", _("Locations"))
    text = P.location_text(card)
    fields = {
        "content_type": "location",
        "message": text,
        "custom_payload": P.dump_payload({"kind": "location", "location": card}),
    }
    return _insert(conv, fields, text, reply_to)


@frappe.whitelist()
def send_contact(conversation, name, phone, reply_to=None):
    try:
        cards = [P.contact_card(name, phone)]
    except P.PayloadError as exc:
        _throw_payload(exc)
    conv = _open_for_send(conversation, "contact", _("Contact cards"))
    text = P.contacts_text(cards)
    fields = {
        "content_type": "contact",
        "message": text,
        "custom_payload": P.dump_payload({"kind": "contact", "contacts": cards}),
    }
    return _insert(conv, fields, text, reply_to)


@frappe.whitelist()
def send_options(conversation, text, options, reply_to=None):
    """≤3 options → reply buttons, 4–10 → a list message (upstream's
    `interactive` branch builds both from `buttons`)."""
    try:
        titles = P.parse_options(options)
        body = P.check_options_body(text, len(titles))
    except P.PayloadError as exc:
        _throw_payload(exc)
    conv = _open_for_send(conversation)
    fields = {
        "content_type": "interactive",
        "message": body,
        "buttons": frappe.as_json(P.option_buttons(titles)),
    }
    return _insert(conv, fields, body + "\n" + " / ".join(titles), reply_to)


# ── voice ────────────────────────────────────────────────────────────────────

def _file_doc(file_url):
    name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not name:
        frappe.throw(_("File {0} not found").format(file_url))
    return frappe.get_doc("File", name)


@frappe.whitelist()
def send_voice(conversation, attachment, reply_to=None, duration=None):
    """A recorded voice note. With ffmpeg the upload is re-encoded to
    Ogg/Opus mono (a new public File on the conversation) and sent with
    Meta's `voice` flag; without it the upload goes out as plain audio."""
    if not attachment:
        frappe.throw(_("A recording is required"))
    conv = _open_for_send(conversation)
    if IC.conv_channel(conv) == IC.MESSENGER:
        from opportunity_management.opportunity_management.messenger_send import voice_fields

        return _insert(conv, voice_fields(conv, attachment, duration), _("[voice note]"), reply_to)
    from opportunity_management.opportunity_management.whatsapp_audio import (
        needs_transcode,
        to_voice_ogg,
    )

    source = _file_doc(attachment)
    ext = os.path.splitext(unquote(str(attachment)).split("?")[0])[1].lower()
    seconds = cint(duration) or None
    send_url, playable, voice = attachment, None, needs_transcode(attachment)
    if not voice:
        content, probed = to_voice_ogg(source.get_full_path())
        if content:
            stem = os.path.splitext(source.file_name or "voice")[0] or "voice"
            ogg = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": f"{stem}.ogg",
                    "attached_to_doctype": "WhatsApp Conversation",
                    "attached_to_name": conv.name,
                    "is_private": 0,
                    "content": content,
                }
            )
            ogg.save(ignore_permissions=True)
            send_url, voice = ogg.file_url, True
            seconds = seconds or probed or None
            # iPhones cannot play the Ogg: the original m4a/mp3 IS the
            # playable copy (a .webm from Desk is left to the cron).
            if ext in PLAYABLE_EXTENSIONS:
                playable = public_copy(attachment, conv.name)
    # Meta fetches the link itself, so it must be public.
    send_url = public_copy(send_url, conv.name)

    fields = {
        "content_type": "audio",
        "attach": send_url,
        "message": "",
        "custom_is_voice": 1,
        "custom_payload": P.dump_payload({"kind": "voice", "voice": bool(voice), "duration": seconds}),
    }
    if playable:
        fields["custom_audio_url"] = playable
    if seconds:
        fields["custom_audio_duration"] = seconds
    return _insert(conv, fields, _("[voice note]"), reply_to)


# ── forward ──────────────────────────────────────────────────────────────────

@frappe.whitelist()
def forward_message(message, to_conversation):
    """Re-send one thread message to another conversation. Media reuses the
    same public URL; a private original gets a public copy on the target."""
    _require_inbox_access()
    if not message or not frappe.db.exists("WhatsApp Message", message):
        frappe.throw(_("Message {0} not found").format(message or ""))
    src = frappe.get_doc("WhatsApp Message", message)
    if not src.get("custom_conversation"):
        frappe.throw(_("Only inbox messages can be forwarded"))
    kind = (src.content_type or "").lower()
    if kind not in FORWARDABLE or cint(src.get("custom_is_sticker")) or P.load_payload(
        src.get("custom_payload")
    ).get("kind") in P.CARD_KINDS:
        frappe.throw(_("Only text, photos, videos, documents and audio can be forwarded"))

    source_conv = _get_conv(src.custom_conversation)  # caller must see the source too
    target = IC.channel_of(
        frappe.db.get_value("WhatsApp Conversation", to_conversation, "channel")
        if IC.has_channel_column() else None
    )
    if target != IC.conv_channel(source_conv):  # checked before _auto_claim
        frappe.throw(_("Messages can only be forwarded to a conversation on the same channel"))
    conv = _open_for_send(to_conversation)
    if kind == "text" or not src.attach:
        text = (src.get("custom_body_text") or strip_html(src.message) or "").strip()
        if not text:
            frappe.throw(_("This message has no text to forward"))
        return _insert(conv, {"content_type": "text", "message": text}, text)

    attach = public_copy(src.attach, conv.name)
    content_type = _content_type_for(attach) if kind != "document" else "document"
    check_video_size(content_type, attach)
    caption = strip_html(src.message) if kind != "audio" else ""
    return _insert(
        conv,
        {"content_type": content_type, "attach": attach, "message": caption},
        caption or f"[{content_type}]",
    )

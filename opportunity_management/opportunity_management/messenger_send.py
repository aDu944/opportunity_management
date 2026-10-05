"""
Us → Meta for the Messenger channel.

`send_row(doc)` is what `whatsapp_message_override` runs in `before_insert`
for an Outgoing, non-echo Messenger row — the counterpart of upstream's
WhatsApp `send_outgoing`. Same contract: on success the row carries Meta's
`message_id` and is inserted; on failure a typed error is raised so the
insert aborts and the endpoint writes its Failed Send note
(`whatsapp_api_messages._record_failed_send`).

    text         ≤ 2000-char chunks (one Send API call each)
    media        attachment by public URL, then the caption as text
                 (Messenger attachments carry no caption)
    options      the body text with `quick_replies` (send_options)
    reaction     `sender_action: react / unreact` (whatsapp_api.react)
    reply-to     top-level `reply_to: {mid}` on the first call

`messaging_type` comes from the window rule (`inbox_channels.conv_window`):
RESPONSE inside 24 h, MESSAGE_TAG + HUMAN_AGENT up to 7 days when enabled,
otherwise nothing is sent (WindowClosedError). Bodies: `messenger_api`.
"""

import os
from urllib.parse import unquote

import frappe
from frappe import _
from frappe.utils import cint, get_url, now_datetime

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import messenger_api as API
from opportunity_management.opportunity_management.whatsapp_api_common import (
    MetaSendError,
    WindowClosedError,
    _window_closed_message,
)

# Audio Messenger plays as-is; anything else (Desk's .webm, an .ogg) is
# re-encoded to AAC .m4a with ffmpeg first. Meta does not publish a format
# list for audio attachments; these are the ones its apps record / accept.
MESSENGER_AUDIO = (".mp3", ".m4a", ".mp4", ".aac", ".wav")
SENT_MID_TTL = 300


def _settings():
    settings = IC.messenger_settings()
    if not cint(settings.get("enabled")):
        frappe.throw(_("Messenger is turned off in Messenger Settings"), exc=MetaSendError)
    return settings


def _graph(settings, body):
    try:
        return API.send(settings, body)
    except API.GraphError as exc:
        if exc.window:
            frappe.throw(
                _("Messenger refused the message: this customer must message you again before you can reply. ({0})").format(str(exc)[:200]),
                exc=WindowClosedError,
            )
        frappe.throw(_("Messenger rejected the message: {0}").format(str(exc)[:300]), exc=MetaSendError)


def _public_url(doc, conv):
    from opportunity_management.opportunity_management.whatsapp_media import public_copy

    url = public_copy(doc.attach, conv.name)
    return url if str(url).startswith("http") else get_url(url)


def _check_size(attach, content_type):
    size = cint(frappe.db.get_value("File", {"file_url": attach}, "file_size"))
    limit = API.max_bytes(content_type)
    if size > limit:
        frappe.throw(
            _("This file is {0} MB — Messenger accepts up to {1} MB.").format(
                round(size / 1048576.0, 1), limit // 1048576
            ),
            exc=MetaSendError,
        )


def bodies_for(doc, conv, mode):
    """The Send API bodies for one row, in order."""
    from opportunity_management.opportunity_management.whatsapp_payloads import option_titles
    from opportunity_management.opportunity_management.whatsapp_utils import strip_html

    psid = conv.phone
    content_type = (doc.content_type or "text").lower()
    reply_to = doc.reply_to_message_id if cint(doc.is_reply) else None
    if content_type == "reaction":
        return [API.reaction_body(psid, doc.reply_to_message_id, strip_html(doc.message))]
    bodies = []
    if doc.attach and content_type in API.ATTACHMENT_TYPES:
        _check_size(doc.attach, content_type)
        bodies.append(API.attachment_body(psid, content_type, _public_url(doc, conv), mode, reply_to))
        reply_to = None
    text = strip_html(doc.message)
    if text:
        options = option_titles(doc.get("buttons")) if content_type == "interactive" else None
        bodies += API.text_bodies(psid, text, mode, reply_to, options)
    return bodies


def send_row(doc):
    """`before_insert` of an Outgoing Messenger row: send it or raise."""
    conv = frappe.get_doc("WhatsApp Conversation", doc.custom_conversation)
    mode, _remaining = IC.conv_window(conv)
    if mode == IC.CLOSED:
        frappe.throw(_window_closed_message(conv), exc=WindowClosedError)
    settings = _settings()
    bodies = bodies_for(doc, conv, mode)
    if not bodies:
        frappe.throw(_("Message text or an attachment is required"))
    mids = []
    for body in bodies:
        response = _graph(settings, body) or {}
        if response.get("message_id"):
            mids.append(response["message_id"])
    cache = frappe.cache()
    for mid in mids:
        # The echo of our own send can beat this row's commit to the webhook.
        cache.set_value("messenger_sent_mid:" + mid, 1, expires_in_sec=SENT_MID_TTL)
    if mids:
        doc.message_id = mids[0]
    doc.status = "sent"
    doc.custom_sent_at = now_datetime()


# ── sender actions ───────────────────────────────────────────────────────────

def sender_action(conv, action) -> bool:
    """typing_on / mark_seen. Best-effort: never raises, never msgprints."""
    try:
        API.send(IC.messenger_settings(), API.sender_action_body(conv.phone, action))
        return True
    except Exception:
        frappe.clear_messages()
        frappe.log_error(frappe.get_traceback(), "Messenger: sender action {0} failed".format(action))
        return False


# ── voice ────────────────────────────────────────────────────────────────────

def voice_fields(conv, attachment, duration=None) -> dict:
    """Row fields for a recorded voice message on Messenger: the upload as
    an audio attachment (re-encoded to .m4a only when Messenger would not
    take its format)."""
    from opportunity_management.opportunity_management import whatsapp_audio as A
    from opportunity_management.opportunity_management.whatsapp_payloads import dump_payload

    ext = os.path.splitext(unquote(str(attachment)).split("?")[0])[1].lower()
    seconds = cint(duration) or None
    url = attachment
    if ext not in MESSENGER_AUDIO:
        url, probed = _to_m4a(conv, attachment, A)
        seconds = seconds or probed or None
    fields = {
        "content_type": "audio",
        "attach": url,
        "message": "",
        "custom_is_voice": 1,
        "custom_payload": dump_payload({"kind": "voice", "voice": False, "duration": seconds}),
    }
    if seconds:
        fields["custom_audio_duration"] = seconds
    return fields


def _to_m4a(conv, attachment, A):
    import subprocess
    import tempfile

    ffmpeg = A.ffmpeg_path()
    if not ffmpeg:
        frappe.throw(_("This recording format cannot be sent on Messenger (no ffmpeg on the server)"))
    name = frappe.db.get_value("File", {"file_url": attachment}, "name")
    if not name:
        frappe.throw(_("File {0} not found").format(attachment))
    source = frappe.get_doc("File", name)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "voice.m4a")
        try:
            subprocess.run(A.m4a_args(ffmpeg, source.get_full_path(), out),
                           timeout=A.FFMPEG_TIMEOUT, capture_output=True, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            frappe.log_error(frappe.get_traceback(), "Messenger: voice conversion failed")
            frappe.throw(_("Could not convert the recording for Messenger"))
        duration = A.probe_duration(out)
        with open(out, "rb") as handle:
            content = handle.read()
    stem = os.path.splitext(source.file_name or "voice")[0] or "voice"
    copy = frappe.get_doc({
        "doctype": "File", "file_name": "{0}.m4a".format(stem),
        "attached_to_doctype": "WhatsApp Conversation", "attached_to_name": conv.name,
        "is_private": 0, "content": content,
    })
    copy.save(ignore_permissions=True)
    return copy.file_url, duration

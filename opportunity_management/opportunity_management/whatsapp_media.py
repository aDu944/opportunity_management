"""
Inbound media in the WhatsApp team inbox: privatising it, and the moment its
`attach` actually lands.

frappe_whatsapp's media branch INSERTS the `WhatsApp Message` first, then
saves the `File`, then sets `attach` and calls `message_doc.save()`. So in
`after_insert` the attach is always empty — the privatise step there never
had anything to work on — and the attachment only becomes visible in
`on_update`. `on_attach_landed` is what `whatsapp_hooks.on_message_on_update`
runs at that moment: privatise, refresh the display text, republish the item
(now with `media_url`) and queue the playable copy of a voice note.

Writes go through `frappe.db.set_value`, never `save()`, so nothing here
re-enters `on_update`; a per-request flag guards against it anyway.
"""

import frappe
from frappe.utils import cint

from opportunity_management.opportunity_management.whatsapp_utils import normalize_body, setting

MSG = "WhatsApp Message"
PREVIEW_LENGTH = 120
_BUSY_FLAG = "whatsapp_attach_landing"

# Optional columns: added by `whatsapp_setup` during migrate. Read only when
# present so a deploy that has not migrated yet keeps serving the thread.
OPTIONAL_MESSAGE_FIELDS = (
    "custom_is_sticker", "custom_audio_url", "custom_audio_duration",
    # round 3: cards / voice / message info; `buttons` is upstream's (options).
    "custom_payload", "custom_is_voice", "custom_sent_at", "custom_delivered_at",
    "custom_read_at", "custom_error", "buttons",
)


def optional_message_fields():
    try:
        return [f for f in OPTIONAL_MESSAGE_FIELDS if frappe.db.has_column(MSG, f)]
    except Exception:
        return []


def check_video_size(content_type, file_url):
    """Meta caps video at 16 MB (mp4 / 3gpp); refuse before it fails there."""
    from frappe import _

    from opportunity_management.opportunity_management.whatsapp_payloads import MAX_VIDEO_MB

    if content_type != "video" or not file_url:
        return
    size = cint(frappe.db.get_value("File", {"file_url": file_url}, "file_size"))
    if size > MAX_VIDEO_MB * 1024 * 1024:
        frappe.throw(
            _("This video is {0} MB — WhatsApp accepts videos up to {1} MB.").format(
                round(size / 1048576.0, 1), MAX_VIDEO_MB
            ),
            title=_("Video too large"),
        )


def public_copy(file_url, conversation):
    """A public File with the content of `file_url`, attached to the
    conversation — Meta fetches outbound media by URL, and a private
    original (inbound media is privatised) must stay private."""
    if is_public_file_url(file_url) or str(file_url or "").startswith("http"):
        return file_url
    name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not name:
        frappe.throw(frappe._("File {0} not found").format(file_url))
    source = frappe.get_doc("File", name)
    copy = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": source.file_name,
            "attached_to_doctype": "WhatsApp Conversation",
            "attached_to_name": conversation,
            "is_private": 0,
            "content": source.get_content(),
        }
    )
    copy.save(ignore_permissions=True)
    return copy.file_url


def is_public_file_url(url) -> bool:
    """Only `/files/…` is ours to flip; `/private/files/…` is done, and an
    `/assets/…` or http URL is not a File we own."""
    return str(url or "").startswith("/files/")


def _attached_file(name, attach):
    """The File upstream saved for this message — never a File that merely
    shares the URL with something else."""
    base = {"attached_to_doctype": MSG, "attached_to_name": name}
    return frappe.db.get_value("File", dict(base, file_url=attach), "name") or frappe.db.get_value(
        "File", dict(base, attached_to_field="attach"), "name"
    )


def privatize_message_media(name, attach):
    """Flip one message's attached File private and point `attach` at the new
    URL. Returns the private URL, or None when there is nothing to do."""
    if not is_public_file_url(attach):
        return None
    file_name = _attached_file(name, attach)
    if not file_name:
        return None
    file_doc = frappe.get_doc("File", file_name)
    if not file_doc.is_private:
        file_doc.is_private = 1
        file_doc.save(ignore_permissions=True)
    new_url = file_doc.file_url
    frappe.db.set_value(MSG, name, {"attach": new_url, "custom_media_private": 1}, update_modified=False)
    return new_url


def privacy_on() -> bool:
    return bool(cint(setting("privatize_inbound_media", 1)))


# ── the attach-landed moment (on_update) ─────────────────────────────────────

def on_attach_landed(doc):
    """Incoming row whose `attach` was just set by upstream's `save()`."""
    if frappe.flags.get(_BUSY_FLAG) == doc.name:
        return
    frappe.flags[_BUSY_FLAG] = doc.name
    try:
        _land(doc)
    finally:
        frappe.flags[_BUSY_FLAG] = None


def _land(doc):
    if privacy_on() and not cint(doc.get("custom_media_private")) and is_public_file_url(doc.attach):
        try:
            new_url = privatize_message_media(doc.name, doc.attach)
            if new_url:
                doc.attach = new_url
                doc.custom_media_private = 1
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: media privatization failed")

    conv = None
    try:
        conv = frappe.get_doc("WhatsApp Conversation", doc.custom_conversation)
        _refresh_body(doc, conv)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: media body refresh failed")

    if conv is not None:
        publish_message_update(doc, conv)

    try:
        from opportunity_management.opportunity_management.whatsapp_audio import needs_transcode

        if (doc.get("content_type") or "") == "audio" and needs_transcode(doc.attach):
            frappe.enqueue(
                "opportunity_management.opportunity_management.whatsapp_audio.transcode_message_audio",
                queue="short",
                enqueue_after_commit=True,
                message_name=doc.name,
            )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: voice transcode enqueue failed")


def _refresh_body(doc, conv):
    """At insert the attach was empty, so a captioned photo was stored as
    bare caption text. Now the label can be prefixed; the list preview
    follows only if it still shows this message."""
    old = doc.get("custom_body_text") or ""
    new = normalize_body(doc)
    if not new or new == old:
        return
    frappe.db.set_value(MSG, doc.name, "custom_body_text", new, update_modified=False)
    doc.custom_body_text = new
    if (conv.last_message_preview or "") == old[:PREVIEW_LENGTH]:
        conv.last_message_preview = new[:PREVIEW_LENGTH]
        frappe.db.set_value(
            "WhatsApp Conversation", conv.name, "last_message_preview",
            conv.last_message_preview, update_modified=False,
        )


def publish_message_update(doc, conv):
    """Re-send a ThreadItem the clients already have (same `id`) — the
    `message` event replaces an existing item rather than appending."""
    try:
        from opportunity_management.opportunity_management import whatsapp_reactions as R
        from opportunity_management.opportunity_management import whatsapp_serializers as S
        from opportunity_management.opportunity_management.whatsapp_hooks import publish_inbox_event

        item = S.message_item(doc)
        R.attach_reactions([item], conv.name)
        publish_inbox_event("message", conv, item=item)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: media update publish failed")


# ── backlog (cron, via whatsapp_jobs) ────────────────────────────────────────

def privatize_pending(limit=50):
    """Incoming rows still on a public `/files/` attach. Newest first, so a
    row without its File (which cannot be fixed) never starves new ones.
    Outgoing rows are `whatsapp_jobs.privatize_sent_outbound_media`'s."""
    if not privacy_on():
        return 0
    rows = frappe.get_all(
        MSG,
        filters=[
            [MSG, "type", "=", "Incoming"],
            [MSG, "attach", "like", "/files/%"],
            [MSG, "custom_media_private", "=", 0],
        ],
        fields=["name", "attach"],
        order_by="creation desc",
        limit_page_length=limit,
    )
    done = 0
    for row in rows:
        try:
            if privatize_message_media(row["name"], row["attach"]):
                done += 1
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), f"WhatsApp inbox: inbound privatize failed for {row['name']}"
            )
    return done

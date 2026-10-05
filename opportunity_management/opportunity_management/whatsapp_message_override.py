"""
`override_doctype_class` for frappe_whatsapp's `WhatsApp Message`.

Upstream's `send_outgoing` has no branch for `location` or `contact` and no
way to flag an audio send as a voice note. For WhatsApp rows this subclass
changes ONLY `send_outgoing`, and only for an Outgoing, non-template row the inbox built
itself (`whatsapp_payloads.custom_kind` — content type AND a matching
`custom_payload` marker). Every other row — ERPNext notifications, bulk
messages, templates, plain text / media — goes straight to
`super().send_outgoing()` untouched.

The error handling mirrors upstream's non-template branch: `notify()` sets
`message_id` or raises; on failure the row is marked Failed and the
exception re-thrown so `before_insert` aborts the insert.

If the installed frappe_whatsapp has no `send_outgoing` (an older build that
sends inline in `before_insert`), the class adds nothing for WhatsApp rows.

**Messenger rows** (`custom_channel == "Messenger"`, see inbox_channels) must
be inert to everything WhatsApp: `before_insert` / `validate` / `on_update`
skip upstream entirely for them (no default WhatsApp Account, no WhatsApp
send, no `create_whatsapp_profile` / `update_profile_name`), and only an
Outgoing, non-echo row is sent — through `messenger_send.send_row`. Every
non-Messenger row takes the plain `super()` path, exactly as before —
except a row with `custom_payload` kind `external` / `echo` (another app's
reply, `external_replies`): `before_insert` and `send_outgoing` return
without sending, on every channel.
"""

import frappe
from frappe.utils import cint, get_url

from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message import whatsapp_message as _upstream
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message import (
    WhatsAppMessage as Upstream,
)


class WhatsAppMessage(Upstream):
    def before_insert(self):
        if not _is_messenger(self):
            if _is_store_only(self):
                return  # placeholder / echo of another app's reply: never sent
            result = super().before_insert()
            _mark_own(self)
            return result
        # No WhatsApp Account on a Messenger row: skip upstream's mandatory one.
        self.flags.ignore_mandatory = True
        _send_messenger(self)

    def validate(self):
        if not _is_messenger(self):
            parent = getattr(super(), "validate", None)
            return parent() if parent else None

    def on_update(self):
        if not _is_messenger(self):
            parent = getattr(super(), "on_update", None)
            return parent() if parent else None

    def create_whatsapp_profile(self):
        if not _is_messenger(self):
            return super().create_whatsapp_profile()

    def update_profile_name(self):
        if not _is_messenger(self):
            return super().update_profile_name()

    if hasattr(Upstream, "send_outgoing"):

        def send_outgoing(self):
            if _is_messenger(self):
                return _send_messenger(self)
            if _is_store_only(self):
                return
            kind = _inbox_kind(self)
            if not kind:
                return super().send_outgoing()
            _send_inbox_kind(self, kind)


def _is_messenger(doc) -> bool:
    return (doc.get("custom_channel") or "") == "Messenger"


def _is_store_only(doc) -> bool:
    """Guard 1 against sending a row that only records another app's reply
    (`external_replies`): custom_payload kind `external` / `echo`."""
    from opportunity_management.opportunity_management.whatsapp_payloads import load_payload

    return load_payload(doc.get("custom_payload")).get("kind") in ("external", "echo")


def _mark_own(doc):
    """Our send's wamid, before its row commits: its first status must not
    become an "external reply" placeholder."""
    if doc.get("type") != "Outgoing" or not doc.get("message_id"):
        return
    try:
        from opportunity_management.opportunity_management.external_replies import mark_own

        mark_own(doc.get("message_id"))
    except Exception:
        pass


def _send_messenger(doc):
    """Only an Outgoing row we composed goes to Meta; an Incoming row or an
    echo (a reply already sent from Meta Business Suite) is just stored."""
    if doc.type != "Outgoing":
        return
    from opportunity_management.opportunity_management.whatsapp_payloads import load_payload

    if load_payload(doc.get("custom_payload")).get("kind") == "echo":
        return
    from opportunity_management.opportunity_management.messenger_send import send_row

    send_row(doc)


def _inbox_kind(doc) -> str:
    if doc.type != "Outgoing" or doc.template or doc.message_type == "Template":
        return ""
    from opportunity_management.opportunity_management.whatsapp_payloads import (
        custom_kind,
        load_payload,
    )

    return custom_kind(
        doc.content_type, cint(doc.get("custom_is_voice")), load_payload(doc.get("custom_payload"))
    )


def _send_inbox_kind(doc, kind):
    from frappe_whatsapp.utils import format_number
    from opportunity_management.opportunity_management.whatsapp_payloads import (
        load_payload,
        message_body,
    )

    link = None
    if kind == "voice":
        link = doc.attach if str(doc.attach or "").startswith("http") else get_url(doc.attach)
    reply_to = doc.reply_to_message_id if doc.is_reply else None
    data = message_body(
        kind, format_number(doc.to), load_payload(doc.custom_payload), link=link, reply_to=reply_to
    )
    # A hidden-number customer's BSUID must travel in `recipient`, not `to`.
    apply_recipient = getattr(_upstream, "apply_recipient", None)
    if callable(apply_recipient):
        apply_recipient(data)
    try:
        doc.notify(data)
        doc.status = "Success"
    except Exception as exc:
        doc.status = "Failed"
        frappe.throw(f"Failed to send message {str(exc)}")

"""
`override_doctype_class` for frappe_whatsapp's `WhatsApp Message`.

Upstream's `send_outgoing` has no branch for `location` or `contact` and no
way to flag an audio send as a voice note. This subclass overrides ONLY
`send_outgoing`, and only for an Outgoing, non-template row the inbox built
itself (`whatsapp_payloads.custom_kind` — content type AND a matching
`custom_payload` marker). Every other row — ERPNext notifications, bulk
messages, templates, plain text / media — goes straight to
`super().send_outgoing()` untouched.

The error handling mirrors upstream's non-template branch: `notify()` sets
`message_id` or raises; on failure the row is marked Failed and the
exception re-thrown so `before_insert` aborts the insert.

If the installed frappe_whatsapp has no `send_outgoing` (an older build that
sends inline in `before_insert`), the class adds nothing at all.
"""

import frappe
from frappe.utils import cint, get_url

from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message import whatsapp_message as _upstream
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message import (
    WhatsAppMessage as Upstream,
)


class WhatsAppMessage(Upstream):
    if hasattr(Upstream, "send_outgoing"):

        def send_outgoing(self):
            kind = _inbox_kind(self)
            if not kind:
                return super().send_outgoing()
            _send_inbox_kind(self, kind)


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

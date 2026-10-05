"""
Reacting to a message from the inbox (`whatsapp_api.react`).

Re-exported by `whatsapp_api.py`, which is the path clients call. The
serialization and realtime side lives in `whatsapp_reactions`.
"""

import frappe
from frappe import _

from opportunity_management.opportunity_management import whatsapp_reactions as R
from opportunity_management.opportunity_management.whatsapp_api_common import (
    MetaSendError,
    WindowClosedError,
    _channel_fields,
    _get_conv,
    _refuse_cap,
    _refuse_blocked,
    _require_assignee,
    _require_inbox_access,
)
from opportunity_management.opportunity_management.whatsapp_utils import WINDOW_CLOSED_ERROR_CODE


@frappe.whitelist()
def react(conversation, message_id, emoji=None):
    """Set (or, with `emoji=""`, remove) our reaction on one message.

    `message_id` is the target's wamid (ThreadItem `message_id`). A reaction
    is a free-form message as far as Meta is concerned, so the 24h window
    must be open. Assignee rules as for any write, but reacting never claims
    an unassigned thread.

    Returns `{"message_id": <target wamid>, "reactions": [...]}`.
    """
    _require_inbox_access()
    conv = _get_conv(conversation)
    _refuse_cap(conv, "reactions", _("Reactions"))
    _refuse_blocked(conv)
    _require_assignee(conv)

    message_id = (message_id or "").strip()
    if not message_id:
        frappe.throw(_("message_id is required"))
    target = frappe.db.get_value(
        "WhatsApp Message",
        {"message_id": message_id, "custom_conversation": conv.name},
        ["name", "content_type"],
        as_dict=True,
    )
    if not target or (target.content_type or "") == R.REACTION:
        frappe.throw(_("That message is not part of this conversation"))

    if not conv.window_open():
        frappe.throw(
            _("The 24-hour reply window for this conversation has closed. Reactions cannot be sent."),
            exc=WindowClosedError,
        )

    emoji = (emoji or "").strip()
    if len(emoji) > 16:
        frappe.throw(_("A reaction is a single emoji"))

    payload = {
        "doctype": "WhatsApp Message",
        "type": "Outgoing",
        "to": conv.phone,
        "content_type": R.REACTION,
        # Upstream sends {"reaction": {"message_id": reply_to_message_id,
        # "emoji": message}}; an empty emoji removes ours on WhatsApp.
        "message": emoji,
        "reply_to_message_id": message_id,
        "whatsapp_account": conv.whatsapp_account,
        "custom_conversation": conv.name,
        "custom_sent_by": frappe.session.user,
        "custom_read": 1,
    }
    payload.update(_channel_fields(conv))
    try:
        doc = frappe.get_doc(payload)
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
    except Exception as exc:
        # No Failed Send note: a lost reaction is not worth a thread entry.
        frappe.db.rollback()
        text = str(exc)
        if isinstance(exc, (WindowClosedError, MetaSendError)):  # Messenger: worded already
            frappe.throw(text, exc=type(exc))
        if WINDOW_CLOSED_ERROR_CODE in text or "24 hour" in text.lower():
            frappe.throw(_("The 24-hour reply window has closed."), exc=WindowClosedError)
        frappe.throw(_("WhatsApp rejected the reaction: {0}").format(text[:300]), exc=MetaSendError)

    return {
        "message_id": message_id,
        "reactions": R.reactions_for(conv.name, [message_id]).get(message_id, []),
    }

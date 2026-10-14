"""
The shared team flag on a conversation (`set_flag`).

Any agent of the conversation's channel may flag or unflag it — a flag is a
"someone needs to look at this" marker for the whole team, not an ownership
action, so there is no assignee check. Helpers: whatsapp_flags.

Re-exported by `whatsapp_api.py`, which is the path clients call.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from opportunity_management.opportunity_management import whatsapp_flags as FL
from opportunity_management.opportunity_management import whatsapp_hooks
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _get_conv,
    _note,
    _require_inbox_access,
)


@frappe.whitelist()
def set_flag(conversation, flagged, note=None):
    """Flag (with an optional note of at most 140 characters) or unflag a
    thread. Writes a System note and publishes the usual `conversation`
    realtime event; nothing else (status, unread, ordering) changes.
    Returns the ConvRow."""
    _require_inbox_access()
    if not FL.has_columns():
        frappe.throw(_("Flags are not available until the site is migrated"))
    flagged = FL.parse_flag(flagged)
    conv = _get_conv(conversation, for_update=True)
    is_flagged = bool(cint(conv.get("is_flagged")))
    me = frappe.session.user

    if flagged:
        if conv.status == "Resolved":
            frappe.throw(_("Reopen this conversation before flagging it"))
        note = FL.clean_note(note)
        if is_flagged and (conv.get("flag_note") or None) == note:
            return S.conv_row(conv)
        values = FL.flag_values(conv, me, note, now_datetime())
    else:
        if not is_flagged:
            return S.conv_row(conv)
        note = None
        values = dict(FL.CLEARED)

    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    who = frappe.db.get_value("User", me, "full_name") or me
    _note(conv.name, FL.note_text(flagged, who, note, translate=_))
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return S.conv_row(conv)

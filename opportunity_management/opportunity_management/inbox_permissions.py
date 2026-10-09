"""
Doctype-level channel scoping for the inbox rows.

The inbox API already limits every list and thread to the caller's channels
(`inbox_channels.user_channels`), but the Messenger / WhatsApp roles also
carry plain `read` on `WhatsApp Conversation` and `WhatsApp Message`, so the
Desk list views and `/api/resource` would otherwise show every channel. These
hooks close that gap: a Messenger-only agent never sees WhatsApp rows and
vice versa. System Managers get no bypass: they hold WhatsApp, and Messenger
only with an explicit Messenger role (`permission_query_conditions` runs for
them too). Administrator holds every role, so every channel → no filter.
"""

import frappe

from opportunity_management.opportunity_management import inbox_channels as IC

CONV_COLUMN = "`tabWhatsApp Conversation`.`channel`"
MSG_COLUMN = "`tabWhatsApp Message`.`custom_channel`"


def _channels(user):
    return IC.user_channels(user or frappe.session.user)


def conversation_query_conditions(user=None):
    if not IC.has_channel_column():
        return ""
    return IC.channel_sql(CONV_COLUMN, _channels(user))


def message_query_conditions(user=None):
    try:
        if not frappe.db.has_column("WhatsApp Message", "custom_channel"):
            return ""
    except Exception:
        return ""
    return IC.channel_sql(MSG_COLUMN, _channels(user))


def conversation_has_permission(doc, ptype=None, user=None):
    return IC.conv_channel(doc) in _channels(user)


def message_has_permission(doc, ptype=None, user=None):
    return IC.channel_of(doc.get("custom_channel")) in _channels(user)

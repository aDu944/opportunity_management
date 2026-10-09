"""
Shareholders get a push for EVERY inbound customer message, on every chat —
assigned, unassigned, inside or outside the team-alert throttle
(shareholder_contract.md, decision 3). Gated by WhatsApp Inbox Settings
`notify_shareholders_all_chats` (default on).

Called once from `whatsapp_hooks._push_inbound`, before the assignee / team
fan-out. It shares that step's `seen` set, so a shareholder who muted the
thread (already in `seen`) gets nothing, and one who is also the assignee or
on the team list is pushed once, not twice. A Messenger message reaches only
shareholders who also hold a Messenger role.

Never raises: a failure here must not stop the assignee's push.
"""

import frappe
from frappe.utils import cint

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management.whatsapp_utils import setting

SHAREHOLDER_ROLE = "Shareholder"


def shareholder_users():
    """Enabled users holding the Shareholder role (Administrator excluded)."""
    from opportunity_management.opportunity_management.business_hooks import _users_with_role

    return _users_with_role(SHAREHOLDER_ROLE)


def notify_shareholders(conv, title, body, data, seen):
    try:
        if not cint(setting("notify_shareholders_all_chats", 1)):
            return
        users = [u for u in shareholder_users() if u and u not in seen]
        if users and IC.conv_channel(conv) == IC.MESSENGER:
            # Messenger exists only for Messenger Agent / Manager holders.
            allowed = set(IC.channel_users(IC.MESSENGER))
            users = [u for u in users if u in allowed]
        if not users:
            return
        from opportunity_management.opportunity_management.business_hooks import _send_to_users

        _send_to_users(users, title, body, data, dedupe_seen=seen)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"WhatsApp: shareholder push failed for {conv.get('name') if conv else '?'}",
        )

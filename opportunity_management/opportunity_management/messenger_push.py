"""
Messenger Managers get a push for EVERY inbound Messenger message — assigned
or not, to anyone, inside or outside the team-alert throttle. Messenger
Agents keep the normal fan-out (assignee, else the throttled team alert over
`inbox_channels.channel_users("Messenger")`).

Called once from `whatsapp_hooks._push_inbound`, right after the shareholder
push and before the assignee / team fan-out. It shares that step's `seen`
set (muted users + everyone already pushed), so a manager who muted the
thread gets nothing and one who is also the assignee / on the team list is
pushed once.

It also closes the channel for an assignee who no longer holds a Messenger
role (an assignment left over from before the role change): they are added
to `seen`, so the assignee branch skips them.

Never raises: a failure here must not stop the assignee's push.
"""

import frappe

from opportunity_management.opportunity_management import inbox_channels as IC


def messenger_managers():
    """Enabled users holding Messenger Manager (Administrator excluded)."""
    from opportunity_management.opportunity_management.business_hooks import _users_with_role

    return _users_with_role(IC.MESSENGER_MANAGER)


def notify_messenger_managers(conv, title, body, data, seen):
    try:
        if IC.conv_channel(conv) != IC.MESSENGER:
            return
        assignee = conv.get("assigned_to")
        if assignee and not IC.reaches_assignee(conv):
            seen.add(assignee)
        users = IC.messenger_recipients(messenger_managers(), seen)
        if not users:
            return
        from opportunity_management.opportunity_management.business_hooks import _send_to_users

        _send_to_users(users, title, body, data, dedupe_seen=seen)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Messenger: manager push failed for {conv.get('name') if conv else '?'}",
        )

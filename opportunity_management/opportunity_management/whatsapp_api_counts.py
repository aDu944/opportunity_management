"""
The WhatsApp inbox badge / home-card counts (`get_unread_count`).

Lives apart from `whatsapp_api_inbox` only for size; that module re-exports
it and `whatsapp_api.py` is still the path clients call.
"""

import frappe
from frappe.utils import cint

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _require_inbox_access,
)


@frappe.whitelist()
def get_unread_count():
    """Badge source: **conversations**, not messages. The unassigned queue is
    everyone's job, so it counts for every agent. Unread-based only — there is
    deliberately no `expired` count (an expired thread is not unread work).

    `waiting_mine` / `waiting_unassigned` are "needs a reply" counts for the
    mobile home card: `awaiting_reply_since` is stamped by the first customer
    message after the last agent reply (whatsapp_hooks) and cleared by an
    agent reply (not auto-replies), Resolve, block and the stale auto-resolve
    job. Unlike `unread_count`, reading a thread does not clear it. Blocked
    contacts are excluded; Resolved threads already are, by the WHERE.

    The totals cover every channel the caller may use; `by_channel` splits
    them ({"WhatsApp": {mine, unassigned, waiting_mine, waiting_unassigned,
    mine_open, unassigned_open}}).
    """
    _require_inbox_access()
    channels = IC.user_channels()
    where = IC.list_channel_sql("", channels)
    grouped = IC.has_channel_column()
    rows = frappe.db.sql(
        """
        SELECT {channel}
            SUM(CASE WHEN assigned_to = %(me)s AND COALESCE(unread_count, 0) > 0
                     THEN 1 ELSE 0 END) AS mine,
            SUM(CASE WHEN (assigned_to IS NULL OR assigned_to = '')
                      AND COALESCE(unread_count, 0) > 0
                     THEN 1 ELSE 0 END) AS unassigned,
            SUM(CASE WHEN assigned_to = %(me)s AND awaiting_reply_since IS NOT NULL
                      AND COALESCE(is_blocked, 0) = 0
                     THEN 1 ELSE 0 END) AS waiting_mine,
            SUM(CASE WHEN (assigned_to IS NULL OR assigned_to = '')
                      AND awaiting_reply_since IS NOT NULL
                      AND COALESCE(is_blocked, 0) = 0
                     THEN 1 ELSE 0 END) AS waiting_unassigned,
            SUM(CASE WHEN assigned_to = %(me)s THEN 1 ELSE 0 END) AS mine_open,
            SUM(CASE WHEN assigned_to IS NULL OR assigned_to = '' THEN 1 ELSE 0 END) AS unassigned_open
        FROM `tabWhatsApp Conversation`
        WHERE status != 'Resolved' {where}
        {group}
        """.format(
            channel="COALESCE(NULLIF(channel, ''), 'WhatsApp') AS channel," if grouped else "",
            where="AND " + where if where else "",
            group="GROUP BY COALESCE(NULLIF(channel, ''), 'WhatsApp')" if grouped else "",
        ),
        {"me": frappe.session.user},
        as_dict=True,
    )
    keys = ("mine", "unassigned", "waiting_mine", "waiting_unassigned", "mine_open", "unassigned_open")
    by_channel = {ch: dict.fromkeys(keys, 0) for ch in channels}
    for r in rows:
        ch = IC.channel_of(r.get("channel"))
        if ch in by_channel:
            by_channel[ch] = {k: cint(r.get(k)) for k in keys}
    out = {k: sum(c[k] for c in by_channel.values()) for k in keys}
    return {
        "mine": out["mine"],
        "unassigned": out["unassigned"],
        "total": out["mine"] + out["unassigned"],
        "waiting_mine": out["waiting_mine"],
        "waiting_unassigned": out["waiting_unassigned"],
        # Open (not Resolved) chats per scope, unread or not — the inbox
        # filter chips show these so "My Chats (2)" means two chats.
        "mine_open": out["mine_open"],
        "unassigned_open": out["unassigned_open"],
        "by_channel": by_channel,
    }

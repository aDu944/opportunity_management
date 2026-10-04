"""
The WhatsApp inbox badge / home-card counts (`get_unread_count`).

Lives apart from `whatsapp_api_inbox` only for size; that module re-exports
it and `whatsapp_api.py` is still the path clients call.
"""

import frappe
from frappe.utils import cint

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
    """
    _require_inbox_access()
    row = frappe.db.sql(
        """
        SELECT
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
                     THEN 1 ELSE 0 END) AS waiting_unassigned
        FROM `tabWhatsApp Conversation`
        WHERE status != 'Resolved'
        """,
        {"me": frappe.session.user},
        as_dict=True,
    )
    r = row[0] if row else {}
    mine = cint(r.get("mine"))
    unassigned = cint(r.get("unassigned"))
    return {
        "mine": mine,
        "unassigned": unassigned,
        "total": mine + unassigned,
        "waiting_mine": cint(r.get("waiting_mine")),
        "waiting_unassigned": cint(r.get("waiting_unassigned")),
    }

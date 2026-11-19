"""
The WhatsApp inbox badge / home-card counts (`get_unread_count`) and the web
Team Inbox sidebar counts (`get_sidebar_counts`).

Lives apart from `whatsapp_api_inbox` only for size; `whatsapp_api.py` is
still the path clients call.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import inbox_sidebar as SB
from opportunity_management.opportunity_management import inbox_sidebar_pure as SBP
from opportunity_management.opportunity_management import whatsapp_chat_state as CS
from opportunity_management.opportunity_management import whatsapp_flags as FL
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _require_inbox_access,
)
from opportunity_management.opportunity_management.whatsapp_identity import display_label
from opportunity_management.opportunity_management.whatsapp_utils import WINDOW_SECONDS

CONV_TABLE = "`tabWhatsApp Conversation`"


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
    mine_open, unassigned_open, flagged_open}}). `flagged_open`: open chats
    carrying the shared team flag (whatsapp_flags), whoever they belong to.

    `mine` / `unassigned` also count a chat the caller marked unread
    (mark_unread → WhatsApp Chat State.marked_unread), for the caller only.
    """
    _require_inbox_access()
    channels = IC.user_channels()
    where = IC.list_channel_sql("", channels)
    grouped = IC.has_channel_column()
    unread_join, unread = CS.unread_count_sql(CONV_TABLE)
    rows = frappe.db.sql(
        """
        SELECT {channel}
            SUM(CASE WHEN assigned_to = %(me)s AND {unread}
                     THEN 1 ELSE 0 END) AS mine,
            SUM(CASE WHEN (assigned_to IS NULL OR assigned_to = '')
                      AND {unread}
                     THEN 1 ELSE 0 END) AS unassigned,
            SUM(CASE WHEN assigned_to = %(me)s AND awaiting_reply_since IS NOT NULL
                      AND COALESCE(is_blocked, 0) = 0
                     THEN 1 ELSE 0 END) AS waiting_mine,
            SUM(CASE WHEN (assigned_to IS NULL OR assigned_to = '')
                      AND awaiting_reply_since IS NOT NULL
                      AND COALESCE(is_blocked, 0) = 0
                     THEN 1 ELSE 0 END) AS waiting_unassigned,
            SUM(CASE WHEN assigned_to = %(me)s THEN 1 ELSE 0 END) AS mine_open,
            SUM(CASE WHEN assigned_to IS NULL OR assigned_to = '' THEN 1 ELSE 0 END) AS unassigned_open,
            {flagged}
        FROM `tabWhatsApp Conversation`
        {unread_join}
        WHERE status != 'Resolved' {where}
        {group}
        """.format(
            unread=unread,
            unread_join=unread_join,
            flagged=FL.count_select(),
            channel="COALESCE(NULLIF(channel, ''), 'WhatsApp') AS channel," if grouped else "",
            where="AND " + where if where else "",
            group="GROUP BY COALESCE(NULLIF(channel, ''), 'WhatsApp')" if grouped else "",
        ),
        {"me": frappe.session.user},
        as_dict=True,
    )
    keys = ("mine", "unassigned", "waiting_mine", "waiting_unassigned", "mine_open", "unassigned_open",
            "flagged_open")
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
        "flagged_open": out["flagged_open"],
        "by_channel": by_channel,
    }


# ── web Team Inbox sidebar ───────────────────────────────────────────────────

def _bucket_sql(channels, params):
    """{key: WHERE-expression} of every sidebar count, built from the same
    fragments list_conversations filters with (alias `c`, Opportunity `o`)."""
    open_sql = SBP.OPEN_SQL
    buckets = {
        "inbox": open_sql,  # what scope "all" lists
        "waiting": " AND ".join(CS.WAITING_CLAUSES),
        "mine": " AND ".join(SBP.MINE_CLAUSES),
        "unassigned": " AND ".join(SBP.UNASSIGNED_CLAUSES),
        "flagged": " AND ".join(CS.FLAGGED_CLAUSES) if FL.has_columns() else "1 = 0",
        "expired": open_sql + " AND " + IC.expired_sql("c", channels, params),
        "resolved": " AND ".join(SBP.RESOLVED_CLAUSES),
        # First inbound (first_contact_at is stamped when it creates the
        # thread), else the row's creation (agent-started threads).
        "today_new": "COALESCE(c.first_contact_at, c.creation) >= %(day_start)s",
    }
    # Opportunity buckets = list_conversations(scope="all", opportunity=X).
    for value in SBP.OPPORTUNITY_BUCKETS:
        sql, extra = SBP.opportunity_clause(value, key="opp_" + value.lower())
        buckets["opp_" + value] = open_sql + " AND " + sql
        params.update(extra)
    buckets["no_opportunity"] = SBP.opportunity_clause("none")[0]
    return buckets


def _oldest_waiting(where, params):
    rows = frappe.db.sql(
        """SELECT c.name, c.display_name, c.phone, c.wa_username, c.awaiting_reply_since,
                  {channel} AS channel
           FROM `tabWhatsApp Conversation` c
           WHERE {waiting} AND {where}
           ORDER BY c.awaiting_reply_since ASC
           LIMIT 1""".format(
            channel="c.channel" if IC.has_channel_column() else "''",
            waiting=" AND ".join(CS.WAITING_CLAUSES),
            where=where,
        ),
        params,
        as_dict=True,
    )
    return rows[0] if rows else None


@frappe.whitelist()
def get_sidebar_counts():
    """Counts for the web Team Inbox sidebar, over the caller's channels.

    inbox / waiting / mine / unassigned / flagged / expired / resolved use
    the list scopes' own rules. opportunities.X and no_opportunity are what
    list_conversations(scope="all", opportunity=X / "none") lists. today:
    `new` = threads first seen today (site time), `answered` = threads that
    got an agent (non-auto) outgoing message today, `oldest_waiting_*` = the
    open, unblocked thread owed a reply the longest (scope "waiting" order).
    """
    _require_inbox_access()
    channels = IC.user_channels()
    now = now_datetime()
    params = {
        "me": frappe.session.user,
        "window_cutoff": add_to_date(now, seconds=-WINDOW_SECONDS),
        "day_start": SBP.day_start(now),
    }
    where = IC.list_channel_sql("c", channels) or "1 = 1"
    buckets = _bucket_sql(channels, params)
    select = ",\n".join(
        "SUM(CASE WHEN {0} THEN 1 ELSE 0 END) AS `{1}`".format(sql, key) for key, sql in buckets.items()
    )
    row = frappe.db.sql(
        """SELECT {select}
           FROM `tabWhatsApp Conversation` c
           {join}
           WHERE {where}""".format(select=select, join=SB.LIST_JOIN, where=where),
        params,
        as_dict=True,
    )
    counts = {key: cint((row[0] if row else {}).get(key)) for key in buckets}

    answered = frappe.db.sql(
        """SELECT COUNT(DISTINCT m.custom_conversation) AS n
           FROM `tabWhatsApp Message` m
           JOIN `tabWhatsApp Conversation` c ON c.name = m.custom_conversation
           WHERE m.type = 'Outgoing' AND m.creation >= %(day_start)s
             AND COALESCE(m.custom_is_auto, 0) = 0 AND {where}""".format(where=where),
        params,
        as_dict=True,
    )

    oldest = _oldest_waiting(where, params)
    title = None
    if oldest:
        messenger = IC.channel_of(oldest.get("channel")) == IC.MESSENGER
        title = display_label(oldest.get("display_name"), oldest.get("phone"), oldest.get("wa_username"),
                              fallback=_("Messenger user") if messenger else _("WhatsApp user"))
    return {
        **{key: counts[key] for key in ("inbox", "waiting", "mine", "unassigned", "flagged", "expired",
                                        "resolved", "no_opportunity")},
        "opportunities": {value: counts["opp_" + value] for value in SBP.OPPORTUNITY_BUCKETS},
        "today": {
            "new": counts["today_new"],
            "answered": cint(answered[0].get("n")) if answered else 0,
            "oldest_waiting_minutes": SBP.minutes_since(oldest.get("awaiting_reply_since"), now) if oldest else None,
            "oldest_waiting_conversation": oldest.get("name") if oldest else None,
            "oldest_waiting_title": title,
        },
    }

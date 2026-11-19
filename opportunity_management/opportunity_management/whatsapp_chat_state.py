"""
Per-user pin / mute / marked-unread of WhatsApp conversations
(`WhatsApp Chat State`).

Pinned, muted and marked_unread are the CALLING user's view of a thread, so
they are not columns on the conversation. Three consumers:

    list_conversations   LEFT JOINs the caller's row and sorts pinned first
                         (`list_sql`) — in SQL, so OFFSET paging stays exact
    publish_inbox_event  stamps each recipient's own flags into the ConvRow
                         it sends that user (`states_by_user`)
    _push_inbound        drops users who muted the thread (`muted_users`)

Counts and badges ignore pin and mute. `marked_unread` (mark_unread, cleared
by that user's mark_read) makes the chat unread for that user only: their
ConvRow shows `unread_count` >= 1 (`apply_state`) and their get_unread_count
counts it (`unread_count_sql`). Everything degrades to "nothing pinned,
nothing muted, nothing marked" until the doctype / column exists (pre-migrate).
"""

import frappe
from frappe.utils import cint

DOCTYPE = "WhatsApp Chat State"
NO_STATE = {"pinned": False, "muted": False, "marked_unread": False}
UNREAD = "marked_unread"


def _ready() -> bool:
    try:
        return bool(frappe.db.table_exists(DOCTYPE))
    except Exception:
        return False


def unread_ready() -> bool:
    """The `marked_unread` column exists (after the migrate)."""
    try:
        return _ready() and bool(frappe.db.has_column(DOCTYPE, UNREAD))
    except Exception:
        return False


def apply_state(row, state):
    """ConvRow `row` with one user's flags (inbox_sidebar_pure.apply_user_state;
    imported here so the bench-free tests can load this module off disk)."""
    from opportunity_management.opportunity_management.inbox_sidebar_pure import apply_user_state

    return apply_user_state(row, state)


def list_sql(ready, unread=False):
    """(select, join, order) fragments for the list query; the join reads
    the `%(state_user)s` parameter. Without the table, constant columns."""
    if not ready:
        return ("0 AS pinned, 0 AS muted, 0 AS marked_unread", "",
                "c.last_message_at DESC, c.modified DESC")
    return (
        "COALESCE(s.pinned, 0) AS pinned, COALESCE(s.muted, 0) AS muted, "
        + ("COALESCE(s.marked_unread, 0)" if unread else "0") + " AS marked_unread",
        "LEFT JOIN `tabWhatsApp Chat State` s ON s.conversation = c.name AND s.user = %(state_user)s",
        "COALESCE(s.pinned, 0) DESC, c.last_message_at DESC, c.modified DESC",
    )


def unread_count_sql(table, user_param="me"):
    """(join, condition) for counting a conversation as unread for one user:
    its own counter, or that user's mark. `table` is how the query names the
    conversation table (an alias or the backticked table name)."""
    own = "COALESCE({0}.unread_count, 0) > 0".format(table)
    if not unread_ready():
        return "", own
    join = ("LEFT JOIN `tabWhatsApp Chat State` us ON us.conversation = {0}.name"
            " AND us.user = %({1})s").format(table, user_param)
    return join, "({0} OR COALESCE(us.marked_unread, 0) = 1)".format(own)


# `list_conversations(scope="waiting")`: open threads whose customer is owed a
# reply (same rule as get_unread_count's waiting_* counts), longest wait first.
WAITING_CLAUSES = (
    "c.status != 'Resolved'",
    "COALESCE(c.is_blocked, 0) = 0",
    "c.awaiting_reply_since IS NOT NULL",
)
WAITING_ORDER = "c.awaiting_reply_since ASC, c.modified DESC"

# `list_conversations(scope="flagged")`: open threads carrying the shared team
# flag (whatsapp_flags), oldest flag first.
FLAGGED_CLAUSES = (
    "c.status != 'Resolved'",
    "COALESCE(c.is_flagged, 0) = 1",
)
FLAGGED_ORDER = "c.flagged_at ASC, c.modified DESC"

# The queue scopes: their own WHERE clauses and their own ORDER BY.
SCOPE_CLAUSES = {"waiting": WAITING_CLAUSES, "flagged": FLAGGED_CLAUSES}
SCOPE_ORDERS = {"waiting": WAITING_ORDER, "flagged": FLAGGED_ORDER}


def scope_order(scope, order):
    """ORDER BY for a list scope: `waiting` and `flagged` are queues (oldest
    first, pins do not jump them); every other scope keeps `order`."""
    return SCOPE_ORDERS.get(scope, order)


def list_fragments(user):
    select, join, order = list_sql(_ready(), unread_ready())
    return select, join, order, {"state_user": user}


def _fields():
    return ["pinned", "muted"] + ([UNREAD] if unread_ready() else [])


def _state(row) -> dict:
    return {"pinned": bool(cint(row.get("pinned"))), "muted": bool(cint(row.get("muted"))),
            "marked_unread": bool(cint(row.get(UNREAD)))}


def own_state(conv):
    """The session user's flags: from the list query's join columns when
    present, else one lookup."""
    if isinstance(conv, dict) and "pinned" in conv:
        return _state(conv)
    name = conv.get("name") if isinstance(conv, dict) else getattr(conv, "name", None)
    try:
        return state_for(name, frappe.session.user)
    except Exception:
        return dict(NO_STATE)


def state_for(conversation, user) -> dict:
    if not _ready():
        return dict(NO_STATE)
    row = frappe.db.get_value(
        DOCTYPE, {"conversation": conversation, "user": user}, _fields(), as_dict=True
    )
    if not row:
        return dict(NO_STATE)
    return _state(row)


def states_for(conversations, user) -> dict:
    """{conversation: {pinned, muted}} of one user for a page of threads."""
    wanted = sorted({c for c in conversations if c})
    if not wanted or not user or not _ready():
        return {}
    rows = frappe.get_all(
        DOCTYPE,
        filters={"conversation": ["in", wanted], "user": user},
        fields=["conversation"] + _fields(),
        limit_page_length=0,
    )
    return {r["conversation"]: _state(r) for r in rows}


def states_by_user(conversation) -> dict:
    """{user: {pinned, muted, marked_unread}} for every user with a row on this thread."""
    if not _ready():
        return {}
    rows = frappe.get_all(
        DOCTYPE,
        filters={"conversation": conversation},
        fields=["user"] + _fields(),
        limit_page_length=0,
    )
    return {r["user"]: _state(r) for r in rows}


def muted_users(conversation) -> set:
    return {u for u, s in states_by_user(conversation).items() if s["muted"]}


def clear_unread(conversation, user):
    """mark_read: drop the user's own unread mark (one cheap UPDATE)."""
    if not unread_ready():
        return
    frappe.db.sql(
        """UPDATE `tabWhatsApp Chat State` SET marked_unread = 0
           WHERE conversation = %(conv)s AND user = %(user)s AND marked_unread = 1""",
        {"conv": conversation, "user": user},
    )


def set_state(conversation, user, pinned=None, muted=None, marked_unread=None) -> dict:
    """Upsert the caller's row; None leaves a flag as it is."""
    values = {}
    if pinned is not None:
        values["pinned"] = 1 if cint(pinned) else 0
    if muted is not None:
        values["muted"] = 1 if cint(muted) else 0
    if marked_unread is not None and unread_ready():
        values[UNREAD] = 1 if cint(marked_unread) else 0
    name = frappe.db.get_value(DOCTYPE, {"conversation": conversation, "user": user}, "name")
    if name:
        if values:
            frappe.db.set_value(DOCTYPE, name, values)
        return state_for(conversation, user)
    if not values:
        return dict(NO_STATE)
    doc = frappe.get_doc(dict({"doctype": DOCTYPE, "conversation": conversation, "user": user}, **values))
    try:
        doc.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        # A parallel first toggle won the unique index; update its row.
        name = frappe.db.get_value(DOCTYPE, {"conversation": conversation, "user": user}, "name")
        frappe.db.set_value(DOCTYPE, name, values)
    return state_for(conversation, user)

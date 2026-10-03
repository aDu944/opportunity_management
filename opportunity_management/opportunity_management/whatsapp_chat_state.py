"""
Per-user pin / mute of WhatsApp conversations (`WhatsApp Chat State`).

Pinned and muted are the CALLING user's view of a thread, so they are not
columns on the conversation. Three consumers:

    list_conversations   LEFT JOINs the caller's row and sorts pinned first
                         (`list_sql`) — in SQL, so OFFSET paging stays exact
    publish_inbox_event  stamps each recipient's own flags into the ConvRow
                         it sends that user (`states_by_user`)
    _push_inbound        drops users who muted the thread (`muted_users`)

Counts and badges deliberately ignore both flags. Everything degrades to
"nothing pinned, nothing muted" until the doctype exists (pre-migrate).
"""

import frappe
from frappe.utils import cint

DOCTYPE = "WhatsApp Chat State"
NO_STATE = {"pinned": False, "muted": False}


def _ready() -> bool:
    try:
        return bool(frappe.db.table_exists(DOCTYPE))
    except Exception:
        return False


def list_sql(ready):
    """(select, join, order) fragments for the list query; the join reads
    the `%(state_user)s` parameter. Without the table, constant columns."""
    if not ready:
        return "0 AS pinned, 0 AS muted", "", "c.last_message_at DESC, c.modified DESC"
    return (
        "COALESCE(s.pinned, 0) AS pinned, COALESCE(s.muted, 0) AS muted",
        "LEFT JOIN `tabWhatsApp Chat State` s ON s.conversation = c.name AND s.user = %(state_user)s",
        "COALESCE(s.pinned, 0) DESC, c.last_message_at DESC, c.modified DESC",
    )


def list_fragments(user):
    select, join, order = list_sql(_ready())
    return select, join, order, {"state_user": user}


def state_for(conversation, user) -> dict:
    if not _ready():
        return dict(NO_STATE)
    row = frappe.db.get_value(
        DOCTYPE, {"conversation": conversation, "user": user}, ["pinned", "muted"], as_dict=True
    )
    if not row:
        return dict(NO_STATE)
    return {"pinned": bool(cint(row.pinned)), "muted": bool(cint(row.muted))}


def states_for(conversations, user) -> dict:
    """{conversation: {pinned, muted}} of one user for a page of threads."""
    wanted = sorted({c for c in conversations if c})
    if not wanted or not user or not _ready():
        return {}
    rows = frappe.get_all(
        DOCTYPE,
        filters={"conversation": ["in", wanted], "user": user},
        fields=["conversation", "pinned", "muted"],
        limit_page_length=0,
    )
    return {
        r["conversation"]: {"pinned": bool(cint(r["pinned"])), "muted": bool(cint(r["muted"]))}
        for r in rows
    }


def states_by_user(conversation) -> dict:
    """{user: {pinned, muted}} for every user with a row on this thread."""
    if not _ready():
        return {}
    rows = frappe.get_all(
        DOCTYPE,
        filters={"conversation": conversation},
        fields=["user", "pinned", "muted"],
        limit_page_length=0,
    )
    return {
        r["user"]: {"pinned": bool(cint(r["pinned"])), "muted": bool(cint(r["muted"]))} for r in rows
    }


def muted_users(conversation) -> set:
    return {u for u, s in states_by_user(conversation).items() if s["muted"]}


def set_state(conversation, user, pinned=None, muted=None) -> dict:
    """Upsert the caller's row; None leaves a flag as it is."""
    values = {}
    if pinned is not None:
        values["pinned"] = 1 if cint(pinned) else 0
    if muted is not None:
        values["muted"] = 1 if cint(muted) else 0
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

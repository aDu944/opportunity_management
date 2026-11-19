"""
Right-click actions of the web Team Inbox that had no endpoint yet:

* `mark_unread` — the caller's own "unread again" mark on a chat
  (WhatsApp Chat State.marked_unread). The conversation's `unread_count` is
  shared by the whole team and is left alone; the caller's ConvRow shows
  `unread_count` >= 1 and `marked_unread: true`, and their get_unread_count
  counts the chat, until they call `mark_read` on it again.
* `save_quick_reply` — a message saved as one of the caller's Personal
  quick replies.
* `rename_tag` / `delete_tag` — managers, across every conversation.

Re-exported by `whatsapp_api.py`, which is the path clients call. Pure
helpers: inbox_sidebar_pure.
"""

import frappe
from frappe import _

from opportunity_management.opportunity_management import inbox_sidebar_pure as SBP
from opportunity_management.opportunity_management import whatsapp_chat_state as CS
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _get_conv,
    _is_manager,
    _require_inbox_access,
)

TAG = "WhatsApp Tag"
CONV_TAG = "WhatsApp Conversation Tag"
QUICK_REPLY = "WhatsApp Quick Reply"
QUICK_REPLY_FIELDS = ["name", "title", "shortcut", "text_en", "text_ar", "scope", "attach", "sort_order"]


class InboxActionError(frappe.ValidationError):
    """Refused (not a manager, bad name, …) — 417, not 403: the clients
    treat a 403 as a dead session (see whatsapp_api_common.NotAssigneeError)."""


# ── read state ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def mark_unread(conversation):
    """Mark the chat unread for the caller only. Returns
    {"unread_count": n >= 1, "marked_unread": true}; the caller's other
    sessions get a `conversation` realtime event with their own row."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    if not CS.unread_ready():
        frappe.throw(_("Mark as unread is not available until the site is updated"), InboxActionError)
    me = frappe.session.user
    state = CS.set_state(conv.name, me, marked_unread=1)
    row = S.conv_row(conv, state=state)
    try:
        frappe.publish_realtime("whatsapp_inbox", {"event": "conversation", "conversation": row}, user=me)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: unread publish failed")
    return {"unread_count": row["unread_count"], "marked_unread": True}


# ── quick replies ────────────────────────────────────────────────────────────

@frappe.whitelist()
def save_quick_reply(text, title=None):
    """Insert a Personal quick reply for the caller; returns it in the
    get_quick_replies row shape."""
    _require_inbox_access()
    try:
        fields = SBP.quick_reply_fields(text, title)
    except ValueError:
        frappe.throw(_("The quick reply needs some text"), InboxActionError)
    doc = frappe.get_doc(dict(
        fields, doctype=QUICK_REPLY, scope="Personal", owner_user=frappe.session.user,
        is_active=1, sort_order=0,
    ))
    doc.insert(ignore_permissions=True)  # inbox access checked; Personal to the caller
    return {f: doc.get(f) for f in QUICK_REPLY_FIELDS}


# ── tags (managers) ──────────────────────────────────────────────────────────

def _require_tag_manager():
    if not _is_manager():
        frappe.throw(_("Only a WhatsApp or Messenger manager can change tags"), InboxActionError)


def _clean_tag(value):
    try:
        return SBP.clean_tag_name(value)
    except ValueError:
        frappe.throw(_("Invalid tag name {0}").format(value or ""), InboxActionError)


def _tag_rows(tag):
    return frappe.db.count(CONV_TAG, {"tag": tag, "parenttype": "WhatsApp Conversation"})


@frappe.whitelist()
def rename_tag(old, new):
    """Rename a tag on every conversation (and the WhatsApp Tag master,
    whose Link fields — conversation tags, auto-menu options — follow).
    Returns {"old", "tag", "conversations": rows renamed}."""
    _require_inbox_access()
    _require_tag_manager()
    old, new = _clean_tag(old), _clean_tag(new)
    has_master = frappe.db.exists(TAG, old)  # the stored spelling
    old = has_master or old
    if old == new:
        return {"old": old, "tag": new, "conversations": 0}
    count = _tag_rows(old)
    if not has_master and not count:
        frappe.throw(_("Tag {0} not found").format(old), InboxActionError)
    # A case-only change ("sales" → "Sales") is the same row to MariaDB.
    if frappe.db.exists(TAG, new) and new.lower() != old.lower():
        frappe.throw(_("A tag named {0} already exists").format(new), InboxActionError)
    if has_master:
        frappe.rename_doc(TAG, old, new, force=True, ignore_permissions=True, show_alert=False)
        frappe.db.set_value(TAG, new, "tag_name", new, update_modified=False)
    # rename_doc already moved the Link values; this covers rows whose tag
    # had no master (and is a no-op otherwise).
    frappe.db.sql(
        """UPDATE `tabWhatsApp Conversation Tag` SET tag = %(new)s
           WHERE tag = %(old)s AND parenttype = 'WhatsApp Conversation'""",
        {"old": old, "new": new},
    )
    return {"old": old, "tag": new, "conversations": count}


@frappe.whitelist()
def delete_tag(name):
    """Remove a tag from every conversation and delete its WhatsApp Tag.
    Refused while an auto-menu option still applies it. Returns
    {"tag", "conversations": rows removed}."""
    _require_inbox_access()
    _require_tag_manager()
    name = _clean_tag(name)
    has_master = frappe.db.exists(TAG, name)
    count = _tag_rows(name)
    if not has_master and not count:
        frappe.throw(_("Tag {0} not found").format(name), InboxActionError)
    if frappe.db.exists("DocType", "WhatsApp Menu Option") and frappe.db.count(
        "WhatsApp Menu Option", {"tag": name}
    ):
        frappe.throw(_("Tag {0} is applied by an auto-menu option; remove it there first").format(name),
                     InboxActionError)
    frappe.db.sql(
        """DELETE FROM `tabWhatsApp Conversation Tag`
           WHERE tag = %(tag)s AND parenttype = 'WhatsApp Conversation'""",
        {"tag": name},
    )
    if has_master:
        # No force: any other link to the tag still blocks (and rolls back).
        frappe.delete_doc(TAG, has_master, ignore_permissions=True)
    return {"tag": name, "conversations": count}

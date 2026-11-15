"""
Delete message: a team-side soft delete that leaves a tombstone.

WhatsApp's Cloud API cannot recall a message once it has been delivered, so
this only hides the content from the team inbox; the customer keeps their
copy. The row is never removed: `custom_deleted_at` / `custom_deleted_by` are
stamped on it and the serializer (`whatsapp_payloads.mark_deleted`) blanks
its content. The tombstone itself is the audit trail.

Who may delete: only team-sent (outgoing) rows. An agent may delete only
their own sends; a manager of the conversation's channel may delete any
outgoing row (`may_delete`, pure so it is tested bench-free).

Clients that already hold the message learn of the delete from
`get_messages(after=…)["deleted_updates"]` (`deleted_updates_since`) and,
on Desk, from the realtime "message" event carrying the tombstone item.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

MSG = "WhatsApp Message"
DELETE_FIELDS = ("custom_deleted_at", "custom_deleted_by")


def may_delete(direction, sender, user, is_manager) -> str:
    """"" when `user` may delete a row, else a reason key: "incoming" (only
    team-sent rows can be deleted) or "not_sender" (an agent may delete only
    their own sends; a channel manager may delete any outgoing row)."""
    if direction != "out":
        return "incoming"
    if is_manager:
        return ""
    if not sender or sender != user:
        return "not_sender"
    return ""


def _has_columns():
    try:
        return all(frappe.db.has_column(MSG, f) for f in DELETE_FIELDS)
    except Exception:
        return False


def deleted_updates_since(conversation, after):
    """`[{id, deleted_at, deleted_by, deleted_by_name}]` for rows of
    `conversation` deleted after the poll cursor `after`."""
    if not after or not _has_columns():
        return []
    from opportunity_management.opportunity_management import whatsapp_serializers as S

    rows = frappe.get_all(
        MSG,
        filters={"custom_conversation": conversation, "custom_deleted_at": [">", after]},
        fields=["name", "custom_deleted_at", "custom_deleted_by"],
        order_by="custom_deleted_at asc",
        limit_page_length=0,
    )
    names = S._full_names([r.get("custom_deleted_by") for r in rows])
    return [
        {
            "id": r["name"],
            "deleted_at": str(r["custom_deleted_at"])[:19],
            "deleted_by": r.get("custom_deleted_by") or None,
            "deleted_by_name": names.get(r.get("custom_deleted_by")) or r.get("custom_deleted_by") or "",
        }
        for r in rows
    ]


def _tombstone_item(name, conversation):
    from opportunity_management.opportunity_management import whatsapp_reactions as R
    from opportunity_management.opportunity_management import whatsapp_serializers as S
    from opportunity_management.opportunity_management.whatsapp_api_messages import message_fields

    row = frappe.get_all(MSG, filters={"name": name}, fields=message_fields(), limit_page_length=1)
    item = S.thread_items(row)[0]
    try:
        R.attach_reactions([item], conversation)
    except Exception:
        pass
    return item


@frappe.whitelist()
def delete_message(message):
    """Soft-delete one team-sent message; returns its tombstone ThreadItem."""
    from opportunity_management.opportunity_management.whatsapp_api_common import (
        _get_conv,
        _is_manager,
        _require_inbox_access,
    )

    _require_inbox_access()
    if not message or not frappe.db.exists(MSG, message):
        frappe.throw(_("Message not found."))
    if not _has_columns():
        frappe.throw(_("Deleting messages is not available yet. Please try again later."))
    row = frappe.get_doc(MSG, message)
    if not row.get("custom_conversation"):
        frappe.throw(_("Message not found."))
    conv = _get_conv(row.custom_conversation)

    user = frappe.session.user
    direction = "in" if (row.get("type") or "") == "Incoming" else "out"
    reason = may_delete(direction, row.get("custom_sent_by"), user, _is_manager(conv))
    if reason == "incoming":
        frappe.throw(_("Only messages sent by the team can be deleted."))
    if reason:
        frappe.throw(_("You can delete only messages you sent."))

    if row.get("custom_deleted_at"):
        return _tombstone_item(row.name, conv.name)  # idempotent

    # Never save(): the doctype's hooks send to Meta.
    frappe.db.set_value(
        MSG, row.name, {"custom_deleted_at": now_datetime(), "custom_deleted_by": user},
        update_modified=False,
    )
    item = _tombstone_item(row.name, conv.name)
    try:
        from opportunity_management.opportunity_management import whatsapp_hooks

        whatsapp_hooks.publish_inbox_event("message", conv, item=item)
    except Exception:
        frappe.log_error(title="WhatsApp delete: realtime publish failed")
    return item

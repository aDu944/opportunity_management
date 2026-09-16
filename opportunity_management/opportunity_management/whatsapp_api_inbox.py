"""
Conversation-level endpoints of the WhatsApp inbox API: the lists, the single
conversation, assignment, status, tags, read state and the badge count.

Re-exported by `whatsapp_api.py`, which is the path clients call. Nothing
routes here directly.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from opportunity_management.opportunity_management import whatsapp_hooks
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_utils import (
    get_inbox_settings,
    inbox_users,
)
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _crm_label,
    _get_conv,
    _is_manager,
    _note,
    _paging,
    _require_assignee,
    _require_inbox_access,
    NotAssigneeError,
)


@frappe.whitelist()
def get_inbox_meta():
    _require_inbox_access()
    settings = get_inbox_settings()
    agents = []
    for email in inbox_users():
        agents.append(
            {"user": email, "full_name": frappe.db.get_value("User", email, "full_name") or email}
        )
    agents.sort(key=lambda a: (a["full_name"] or "").lower())

    tags = frappe.get_all(
        "WhatsApp Tag",
        filters={"is_active": 1},
        fields=["name as tag", "color"],
        order_by="name asc",
        limit_page_length=0,
    )

    return {
        "is_manager": _is_manager(),
        "me": frappe.session.user,
        "agents": agents,
        "tags": tags,
        "settings": {
            "business_days": settings.get("business_days") or "",
            "business_hours_start": str(settings.get("business_hours_start") or ""),
            "business_hours_end": str(settings.get("business_hours_end") or ""),
            "timezone": settings.get("timezone") or "",
            "default_language": settings.get("default_language") or "en",
            "default_reengage_template": settings.get("default_reengage_template") or "",
            "auto_read_receipt": cint(settings.get("auto_read_receipt")),
        },
    }


@frappe.whitelist()
def list_conversations(
    scope="all", search=None, tag=None, status=None, limit_start=0, limit_page_length=None
):
    """Paged conversation list.

    scope: mine | unassigned | all | resolved. `all` hides Resolved threads —
    the resolved pile is its own tab, not noise in the working list.
    """
    _require_inbox_access()
    start, length = _paging(limit_start, limit_page_length)

    clauses = []
    params = {"limit": length + 1, "start": start}

    scope = (scope or "all").lower()
    if scope == "mine":
        clauses.append("c.assigned_to = %(me)s")
        clauses.append("c.status != 'Resolved'")
        params["me"] = frappe.session.user
    elif scope == "unassigned":
        clauses.append("(c.assigned_to IS NULL OR c.assigned_to = '')")
        clauses.append("c.status != 'Resolved'")
    elif scope == "resolved":
        clauses.append("c.status = 'Resolved'")
    else:
        clauses.append("c.status != 'Resolved'")

    if status:
        clauses.append("c.status = %(status)s")
        params["status"] = status

    if tag:
        clauses.append(
            """EXISTS (SELECT 1 FROM `tabWhatsApp Conversation Tag` t
                        WHERE t.parent = c.name
                          AND t.parenttype = 'WhatsApp Conversation'
                          AND t.tag = %(tag)s)"""
        )
        params["tag"] = tag

    search = (search or "").strip()
    if search:
        # The wildcards live in the *parameter*, never in the SQL text, so
        # there is no literal % to double here.
        params["search"] = "%" + search + "%"
        clauses.append(
            """(c.phone LIKE %(search)s
                OR c.display_name LIKE %(search)s
                OR EXISTS (SELECT 1 FROM `tabWhatsApp Message` m
                            WHERE m.custom_conversation = c.name
                              AND m.custom_body_text LIKE %(search)s))"""
        )

    where = " AND ".join(clauses) or "1 = 1"
    rows = frappe.db.sql(
        f"""
        SELECT c.name, c.phone, c.display_name, c.whatsapp_account, c.status,
               c.assigned_to, c.tags, c.last_message_at, c.last_inbound_at,
               c.last_message_preview, c.last_message_direction, c.unread_count,
               c.contact, c.lead, c.customer, c.opportunity, c.customer_language,
               c.notes_count
        FROM `tabWhatsApp Conversation` c
        WHERE {where}
        ORDER BY c.last_message_at DESC, c.modified DESC
        LIMIT %(limit)s OFFSET %(start)s
        """,
        params,
        as_dict=True,
    )

    has_more = len(rows) > length
    return {"rows": S.conv_rows(rows[:length]), "has_more": has_more}


@frappe.whitelist()
def get_conversation(name):
    _require_inbox_access()
    conv = _get_conv(name)
    row = S.conv_row(conv)
    row.update(
        {
            "window_open": conv.window_open(),
            "window_seconds_remaining": conv.window_seconds_remaining(),
            "can_assign": _is_manager(),
            "is_mine": conv.assigned_to == frappe.session.user,
            "contact_name": _crm_label("Contact", conv.contact),
            "lead_name": _crm_label("Lead", conv.lead),
            "customer_name": _crm_label("Customer", conv.customer),
            "opportunity_name": _crm_label("Opportunity", conv.opportunity),
            "first_contact_at": str(conv.first_contact_at or "") or None,
            "assigned_at": str(conv.assigned_at or "") or None,
            "resolved_at": str(conv.resolved_at or "") or None,
        }
    )
    return row


# ── assignment & status ──────────────────────────────────────────────────────

@frappe.whitelist()
def claim(conversation):
    _require_inbox_access()
    conv = _get_conv(conversation, for_update=True)
    if conv.assigned_to and conv.assigned_to != frappe.session.user:
        frappe.throw(
            _("Already claimed by {0}").format(
                frappe.db.get_value("User", conv.assigned_to, "full_name") or conv.assigned_to
            ),
            exc=NotAssigneeError,
        )
    now = now_datetime()
    values = {
        "assigned_to": frappe.session.user,
        "assigned_at": now,
        "assigned_by": frappe.session.user,
    }
    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    _note(conv.name, _("Claimed by {0}").format(frappe.session.user))
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return S.conv_row(conv)


@frappe.whitelist()
def unassign(conversation):
    _require_inbox_access()
    conv = _get_conv(conversation, for_update=True)
    _require_assignee(conv)
    values = {"assigned_to": None, "assigned_at": None, "assigned_by": None}
    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    _note(conv.name, _("Returned to the unassigned queue by {0}").format(frappe.session.user))
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return S.conv_row(conv)


@frappe.whitelist()
def assign(conversation, user):
    _require_inbox_access()
    if not _is_manager():
        frappe.throw(_("Only a WhatsApp Manager can assign conversations"), frappe.PermissionError)
    if not user or not frappe.db.exists("User", user):
        frappe.throw(_("User {0} not found").format(user))

    conv = _get_conv(conversation, for_update=True)
    now = now_datetime()
    values = {"assigned_to": user, "assigned_at": now, "assigned_by": frappe.session.user}
    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    _note(conv.name, _("Assigned to {0} by {1}").format(user, frappe.session.user))

    try:
        from opportunity_management.opportunity_management import notification_templates as T
        from opportunity_management.opportunity_management.business_hooks import _send_to_users

        if user != frappe.session.user:
            title, body, data = T.whatsapp_assigned(conv, frappe.session.user)
            _send_to_users([user], title, body, data)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: assignment push failed")

    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return S.conv_row(conv)


@frappe.whitelist()
def set_status(conversation, status):
    _require_inbox_access()
    if status not in ("Open", "Pending", "Resolved"):
        frappe.throw(_("Invalid status {0}").format(status))
    conv = _get_conv(conversation)
    _require_assignee(conv)

    values = {"status": status}
    if status == "Resolved":
        values["resolved_at"] = now_datetime()
        values["resolved_by"] = frappe.session.user
        values["awaiting_reply_since"] = None
    else:
        values["resolved_at"] = None
        values["resolved_by"] = None
    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    _note(conv.name, _("Status set to {0} by {1}").format(status, frappe.session.user))
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return S.conv_row(conv)


# ── tags ─────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def add_tag(conversation, tag):
    _require_inbox_access()
    conv = _get_conv(conversation)
    if not frappe.db.exists("WhatsApp Tag", tag):
        frappe.throw(_("Tag {0} not found").format(tag))
    if not any((row.tag or "") == tag for row in (conv.tags or [])):
        conv.append("tags", {"tag": tag})
        conv.flags.ignore_permissions = True
        conv.save(ignore_permissions=True)
    return S.conv_row(conv)["tags"]


@frappe.whitelist()
def remove_tag(conversation, tag):
    _require_inbox_access()
    conv = _get_conv(conversation)
    kept = [row for row in (conv.tags or []) if (row.tag or "") != tag]
    if len(kept) != len(conv.tags or []):
        conv.set("tags", [])
        for row in kept:
            conv.append("tags", {"tag": row.tag})
        conv.flags.ignore_permissions = True
        conv.save(ignore_permissions=True)
    return S.conv_row(conv)["tags"]


# ── read state ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def mark_read(conversation):
    """Zero the unread counter. One bulk UPDATE, not N document saves — a
    thread reopened after a weekend can carry dozens of unread rows."""
    _require_inbox_access()
    conv = _get_conv(conversation)

    newest = frappe.db.sql(
        """SELECT name FROM `tabWhatsApp Message`
           WHERE custom_conversation = %(conv)s AND type = 'Incoming'
           ORDER BY creation DESC LIMIT 1""",
        {"conv": conv.name},
        as_dict=True,
    )
    frappe.db.sql(
        """UPDATE `tabWhatsApp Message`
           SET custom_read = 1
           WHERE custom_conversation = %(conv)s
             AND type = 'Incoming'
             AND COALESCE(custom_read, 0) = 0""",
        {"conv": conv.name},
    )
    frappe.db.set_value(
        "WhatsApp Conversation", conv.name, "unread_count", 0, update_modified=False
    )
    conv.unread_count = 0

    if cint(get_inbox_settings().get("auto_read_receipt")) and newest:
        try:
            msg = frappe.get_doc("WhatsApp Message", newest[0]["name"])
            if msg.get("message_id"):
                msg.send_read_receipt()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: read receipt failed")

    try:
        whatsapp_hooks.publish_inbox_event("read", conv)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: read publish failed")

    return {"unread_count": 0}


@frappe.whitelist()
def get_unread_count():
    """Badge source: **conversations**, not messages. The unassigned queue is
    everyone's job, so it counts for every agent."""
    _require_inbox_access()
    row = frappe.db.sql(
        """
        SELECT
            SUM(CASE WHEN assigned_to = %(me)s AND COALESCE(unread_count, 0) > 0
                     THEN 1 ELSE 0 END) AS mine,
            SUM(CASE WHEN (assigned_to IS NULL OR assigned_to = '')
                      AND COALESCE(unread_count, 0) > 0
                     THEN 1 ELSE 0 END) AS unassigned
        FROM `tabWhatsApp Conversation`
        WHERE status != 'Resolved'
        """,
        {"me": frappe.session.user},
        as_dict=True,
    )
    mine = cint(row[0].get("mine")) if row else 0
    unassigned = cint(row[0].get("unassigned")) if row else 0
    return {"mine": mine, "unassigned": unassigned, "total": mine + unassigned}

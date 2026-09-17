"""
CRM-linkage and analytics endpoints of the WhatsApp inbox API.

Re-exported by `whatsapp_api.py`, which is the path clients call. Nothing
routes here directly.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, nowdate

from opportunity_management.opportunity_management import whatsapp_crm
from opportunity_management.opportunity_management import whatsapp_hooks
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _get_conv,
    _is_manager,
    _note,
    _require_inbox_access,
)
from opportunity_management.opportunity_management.whatsapp_api_inbox import (
    get_conversation,
)


@frappe.whitelist()
def link_crm(conversation, doctype, name):
    _require_inbox_access()
    conv = _get_conv(conversation)
    whatsapp_crm.link_conversation_to_crm(conv, doctype, name)
    _note(conv.name, _("Linked to {0} {1} by {2}").format(doctype, name, frappe.session.user))
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return get_conversation(conv.name)


@frappe.whitelist()
def unlink_crm(conversation, doctype=None):
    _require_inbox_access()
    conv = _get_conv(conversation)
    whatsapp_crm.unlink_conversation_from_crm(conv, doctype)
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return get_conversation(conv.name)


@frappe.whitelist()
def search_crm(query, limit=10, doctype=None):
    _require_inbox_access()
    return whatsapp_crm.search_crm(query, limit=cint(limit) or 10, doctype=doctype or None)


@frappe.whitelist()
def create_lead_from_conversation(
    conversation, lead_name=None, company_name=None, email_id=None, source=None
):
    """Turn an unknown number into a Lead without leaving the inbox."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    if conv.lead:
        frappe.throw(_("This conversation is already linked to Lead {0}").format(conv.lead))

    lead_name = (lead_name or conv.display_name or conv.phone or "").strip()
    if not lead_name:
        frappe.throw(_("Lead name is required"))

    payload = {
        "doctype": "Lead",
        "lead_name": lead_name,
        "company_name": (company_name or "").strip() or None,
        "email_id": (email_id or "").strip() or None,
        "mobile_no": conv.phone,
        "whatsapp_no": conv.phone,
    }
    if source and frappe.db.exists("Lead Source", source):
        payload["source"] = source
    lead = frappe.get_doc({k: v for k, v in payload.items() if v is not None})
    lead.flags.ignore_permissions = True
    lead.insert(ignore_permissions=True)

    whatsapp_crm.link_conversation_to_crm(conv, "Lead", lead.name)
    _note(conv.name, _("Lead {0} created by {1}").format(lead.name, frappe.session.user))
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return {"lead": lead.name, "conversation": get_conversation(conv.name)}


@frappe.whitelist()
def list_conversations_for_crm(doctype, name):
    """Rows for the Contact / Lead / Customer Desk form section."""
    _require_inbox_access()
    field = {
        "Contact": "contact",
        "Lead": "lead",
        "Customer": "customer",
        "Opportunity": "opportunity",
    }.get(doctype)
    if not field:
        frappe.throw(_("Unsupported CRM doctype: {0}").format(doctype))

    rows = frappe.get_all(
        "WhatsApp Conversation",
        filters={field: name},
        fields=[
            "name", "phone", "display_name", "whatsapp_account", "status", "assigned_to",
            "last_message_at", "last_inbound_at", "last_message_preview",
            "last_message_direction", "unread_count", "contact", "lead", "customer",
            "opportunity", "customer_language", "notes_count", "first_response_seconds",
        ],
        order_by="last_message_at desc",
        limit_page_length=20,
    )
    return S.conv_rows(rows)


# ── analytics (plan §5) ──────────────────────────────────────────────────────

def _median(values):
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return int(ordered[mid])
    return int((ordered[mid - 1] + ordered[mid]) / 2)


def _percentile(values, pct):
    if not values:
        return 0
    ordered = sorted(values)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    return int(ordered[max(0, min(idx, len(ordered) - 1))])


@frappe.whitelist()
def get_inbox_stats(from_date=None, to_date=None):
    """Manager dashboard numbers.

    Everything is read off counters the inbound hook already maintains
    (`first_contact_at`, `resolved_at`, `first_response_seconds`) — no
    per-message inbound/outbound pairing at query time, which is what makes
    this cheap enough to sit on a dashboard.
    """
    _require_inbox_access()
    if not _is_manager():
        frappe.throw(_("Only a WhatsApp Manager can view inbox analytics"), frappe.PermissionError)

    to_date = getdate(to_date or nowdate())
    from_date = getdate(from_date or add_days(to_date, -29))
    params = {"from": str(from_date), "to": str(to_date), "to_end": f"{to_date} 23:59:59"}

    opened = cint(
        frappe.db.sql(
            """SELECT COUNT(*) FROM `tabWhatsApp Conversation`
               WHERE first_contact_at BETWEEN %(from)s AND %(to_end)s""",
            params,
        )[0][0]
    )
    resolved = cint(
        frappe.db.sql(
            """SELECT COUNT(*) FROM `tabWhatsApp Conversation`
               WHERE resolved_at BETWEEN %(from)s AND %(to_end)s""",
            params,
        )[0][0]
    )
    # "Reopened" = an inbound arrived after the thread had been resolved, i.e.
    # a resolved-then-reopened thread still carries resolved_at but is Open.
    reopened = cint(
        frappe.db.sql(
            """SELECT COUNT(*) FROM `tabWhatsApp Conversation`
               WHERE status != 'Resolved'
                 AND resolved_at IS NOT NULL
                 AND last_inbound_at BETWEEN %(from)s AND %(to_end)s""",
            params,
        )[0][0]
    )
    unassigned_backlog = cint(
        frappe.db.sql(
            """SELECT COUNT(*) FROM `tabWhatsApp Conversation`
               WHERE status != 'Resolved' AND (assigned_to IS NULL OR assigned_to = '')"""
        )[0][0]
    )
    open_total = cint(
        frappe.db.sql(
            """SELECT COUNT(*) FROM `tabWhatsApp Conversation` WHERE status != 'Resolved'"""
        )[0][0]
    )

    response_rows = frappe.db.sql(
        """SELECT first_response_seconds FROM `tabWhatsApp Conversation`
           WHERE COALESCE(first_response_seconds, 0) > 0
             AND first_contact_at BETWEEN %(from)s AND %(to_end)s""",
        params,
        as_dict=True,
    )
    responses = [cint(r["first_response_seconds"]) for r in response_rows]

    per_agent = frappe.db.sql(
        """
        SELECT m.custom_sent_by AS user, COUNT(*) AS sent
        FROM `tabWhatsApp Message` m
        WHERE m.type = 'Outgoing'
          AND m.custom_sent_by IS NOT NULL AND m.custom_sent_by != ''
          AND m.creation BETWEEN %(from)s AND %(to_end)s
        GROUP BY m.custom_sent_by
        ORDER BY sent DESC
        """,
        params,
        as_dict=True,
    )
    resolved_by = {
        r["resolved_by"]: cint(r["resolved"])
        for r in frappe.db.sql(
            """SELECT resolved_by, COUNT(*) AS resolved
               FROM `tabWhatsApp Conversation`
               WHERE resolved_by IS NOT NULL
                 AND resolved_at BETWEEN %(from)s AND %(to_end)s
               GROUP BY resolved_by""",
            params,
            as_dict=True,
        )
    }
    for row in per_agent:
        row["sent"] = cint(row["sent"])
        row["resolved"] = resolved_by.get(row["user"], 0)
        row["full_name"] = frappe.db.get_value("User", row["user"], "full_name") or row["user"]

    by_day = frappe.db.sql(
        """
        SELECT DATE(first_contact_at) AS day, COUNT(*) AS opened
        FROM `tabWhatsApp Conversation`
        WHERE first_contact_at BETWEEN %(from)s AND %(to_end)s
        GROUP BY DATE(first_contact_at)
        ORDER BY day ASC
        """,
        params,
        as_dict=True,
    )
    for row in by_day:
        row["day"] = str(row["day"])
        row["opened"] = cint(row["opened"])

    by_tag = frappe.db.sql(
        """
        SELECT t.tag, COUNT(*) AS conversations
        FROM `tabWhatsApp Conversation Tag` t
        JOIN `tabWhatsApp Conversation` c ON c.name = t.parent
        WHERE t.parenttype = 'WhatsApp Conversation'
          AND c.last_message_at BETWEEN %(from)s AND %(to_end)s
        GROUP BY t.tag
        ORDER BY conversations DESC
        """,
        params,
        as_dict=True,
    )
    for row in by_tag:
        row["conversations"] = cint(row["conversations"])

    return {
        "from_date": str(from_date),
        "to_date": str(to_date),
        "opened": opened,
        "resolved": resolved,
        "reopened": reopened,
        "unassigned_backlog": unassigned_backlog,
        "open_total": open_total,
        "median_first_response_seconds": _median(responses),
        "p90_first_response_seconds": _percentile(responses, 90),
        "per_agent": per_agent,
        "by_day": by_day,
        "by_tag": by_tag,
    }

"""
The thread's "customer info" screen (WhatsApp + Messenger): one call that
returns the conversation, the customer's identity, message stats, handling
state, the ad they came from, the linked CRM records and the customer's other
conversations.

Re-exported by `whatsapp_api.py`, which is the path clients call.

CRM records are read only when the caller may read them
(`frappe.has_permission`); otherwise the block is null and
`crm.restricted` is true, so an agent without CRM roles still gets the
chat-side info. The identity matching and the count roll-up are pure
(`customer_info_pure`).
"""

import frappe
from frappe.utils import cint

from opportunity_management.opportunity_management import auto_menu as AM
from opportunity_management.opportunity_management import customer_info_pure as P
from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import whatsapp_api_opportunity as O
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _get_conv,
    _require_inbox_access,
)
from opportunity_management.opportunity_management.whatsapp_api_inbox import get_conversation

CONV = "WhatsApp Conversation"
MSG = "WhatsApp Message"
CANDIDATE_LIMIT = 50
OPPORTUNITY_LIMIT = 10

# doctype → (output key → field). The first field is the label column.
_CRM_FIELDS = {
    "Contact": {"first_name": "first_name", "last_name": "last_name", "email": "email_id",
                "mobile": "mobile_no", "phone": "phone", "company": "company_name"},
    "Lead": {"lead_name": "lead_name", "company_name": "company_name", "status": "status",
             "email": "email_id", "mobile": "mobile_no"},
    "Customer": {"customer_name": "customer_name", "customer_group": "customer_group",
                 "territory": "territory", "email": "email_id", "mobile": "mobile_no"},
}


def _iso(value):
    return S._iso(value)


def _can_read(doctype, name) -> bool:
    try:
        return bool(frappe.has_permission(doctype, "read", doc=name))
    except Exception:
        return False


def _read_fields(doctype, name, wanted):
    """{out_key: value} for the fields of `wanted` the doctype has."""
    meta = frappe.get_meta(doctype)
    fields = [f for f in wanted.values() if meta.has_field(f)]
    row = frappe.db.get_value(doctype, name, fields, as_dict=True) if fields else {}
    row = row or {}
    return {key: row.get(field) or None for key, field in wanted.items()}


def _crm_record(doctype, name, state):
    """One linked record, or None (missing, or the caller may not read it)."""
    if not name:
        return None
    if not frappe.db.exists(doctype, name):
        return None
    if not _can_read(doctype, name):
        state["restricted"] = True
        return None
    try:
        values = _read_fields(doctype, name, _CRM_FIELDS[doctype])
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Inbox customer info: CRM read failed")
        values = {key: None for key in _CRM_FIELDS[doctype]}
    out = {"name": name}
    if doctype == "Contact":
        full = " ".join(p for p in (values.pop("first_name"), values.pop("last_name")) if p)
        out["full_name"] = full or name
        out["email"] = values["email"]
        out["mobile"] = values["mobile"] or values["phone"]
        out["company"] = values["company"]
        return out
    out.update(values)
    return out


def _opportunities(conv, state):
    """Open opportunities of the linked party / contact, plus the one the
    conversation itself is linked to (whatever its status). Permission-aware
    (`get_list`), so a caller without Opportunity read gets []."""
    or_filters = []
    for value in (conv.customer, conv.lead):
        if value:
            or_filters.append(["party_name", "=", value])
    if conv.contact:
        or_filters.append(["contact_person", "=", conv.contact])
    if conv.opportunity:
        or_filters.append(["name", "=", conv.opportunity])
    if not or_filters:
        return []
    if not frappe.has_permission("Opportunity", "read"):
        state["restricted"] = True
        return []
    meta = frappe.get_meta("Opportunity")
    fields = ["name", "status"] + [
        f for f in ("title", "expected_closing", "opportunity_amount", "currency", "modified")
        if meta.has_field(f) or f == "modified"
    ]
    try:
        rows = frappe.get_list(
            "Opportunity", or_filters=or_filters, fields=fields,
            order_by="modified desc", limit_page_length=OPPORTUNITY_LIMIT * 3,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Inbox customer info: opportunities failed")
        return []
    out = []
    for row in rows:
        if row["name"] != conv.opportunity and not P.is_open_opportunity(row.get("status")):
            continue
        out.append({
            "name": row["name"],
            "title": row.get("title") or row["name"],
            "status": row.get("status") or "",
            "expected_closing": _iso(row.get("expected_closing")),
            "opportunity_amount": float(row.get("opportunity_amount") or 0),
            "currency": row.get("currency") or "",
            "is_linked": row["name"] == conv.opportunity,
        })
    out.sort(key=lambda o: not o["is_linked"])  # the linked one first
    return out[:OPPORTUNITY_LIMIT]


def _attachments_count(conv):
    try:
        return len(O.conversation_attachments(conv.name))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Inbox customer info: attachments failed")
        return 0


def _crm(conv):
    state = {"restricted": False}
    lead = _crm_record("Lead", conv.lead, state)
    return {
        "contact": _crm_record("Contact", conv.contact, state),
        "lead": lead,
        "customer": _crm_record("Customer", conv.customer, state),
        "opportunities": _opportunities(conv, state),
        # link_crm / create_lead need inbox access only (already checked).
        "can_link": True,
        "can_create_lead": not conv.lead,
        # "Create opportunity" / "Parse attachments" (whatsapp_api_opportunity).
        "can_create_opportunity": O.can_create_opportunity(),
        "opportunity_attachments_count": _attachments_count(conv),
        "restricted": state["restricted"],
    }


def _message_stats(conv):
    rows = frappe.db.sql(
        """SELECT m.type AS type, m.content_type AS content_type,
                  (m.attach IS NOT NULL AND m.attach != '') AS has_attach,
                  COUNT(*) AS n
           FROM `tabWhatsApp Message` m
           WHERE m.custom_conversation = %(conv)s
           GROUP BY m.type, m.content_type, has_attach""",
        {"conv": conv.name},
        as_dict=True,
    )
    return P.roll_up_messages(rows)


def _raw(conv):
    return {
        "name": conv.name,
        "phone": conv.phone,
        "channel": IC.conv_channel(conv),
        "wa_username": conv.get("wa_username"),
        "wa_user_id": conv.get("wa_user_id"),
        "contact": conv.contact,
        "lead": conv.lead,
        "customer": conv.customer,
    }


def _other_conversations(conv):
    """Every conversation of the same customer across the caller's channels
    (see `customer_info_pure.identity_keys`), this one excluded."""
    current = _raw(conv)
    pairs = P.candidate_filters(current)
    if not pairs:
        return [], 1
    params = {"me": conv.name, "limit": CANDIDATE_LIMIT}
    ors = []
    for i, (column, value) in enumerate(pairs):
        # Columns come from customer_info_pure's fixed list, never the caller.
        ors.append("c.`{0}` = %(v{1})s".format(column, i))
        params["v" + str(i)] = value
    clauses = ["(" + " OR ".join(ors) + ")", "c.name != %(me)s"]
    channel_clause = IC.list_channel_sql("c", IC.user_channels())
    if channel_clause:
        clauses.append(channel_clause)
    channel_col = "c.channel" if IC.has_channel_column() else "'{0}'".format(IC.WHATSAPP)
    rows = frappe.db.sql(
        """SELECT c.name, c.phone, c.wa_username, c.wa_user_id, c.contact, c.lead,
                  c.customer, c.status, c.last_message_at, c.assigned_to,
                  {0} AS channel
           FROM `tabWhatsApp Conversation` c
           WHERE {1}
           ORDER BY c.last_message_at DESC
           LIMIT %(limit)s""".format(channel_col, " AND ".join(clauses)),
        params,
        as_dict=True,
    )
    for row in rows:
        row["last_message_at"] = _iso(row.get("last_message_at"))
    related = P.related_conversations(current, rows, limit=len(rows))
    total = len(related) + 1
    names = S._full_names([r.get("assigned_to") for r in related[:P.OTHER_LIMIT]])
    out = [
        {
            "name": r["name"],
            "channel": IC.channel_of(r.get("channel")),
            "status": r.get("status") or "",
            "last_message_at": r.get("last_message_at"),
            "assigned_to_name": names.get(r.get("assigned_to"), "") if r.get("assigned_to") else "",
        }
        for r in related[:P.OTHER_LIMIT]
    ]
    return out, total


@frappe.whitelist()
def get_customer_info(conversation):
    _require_inbox_access()
    conv = _get_conv(conversation)
    row = get_conversation(conv.name)

    identity = P.identity_block(row)
    if not identity["customer_language"]:
        identity["customer_language"] = conv.get("customer_language") or ""

    counts = _message_stats(conv)
    others, conversations_count = _other_conversations(conv)
    stats = {
        "first_contact_at": _iso(conv.get("first_contact_at")),
        "last_inbound_at": _iso(conv.get("last_inbound_at")),
        "last_outbound_at": _iso(conv.get("last_outbound_at")),
        "last_message_at": _iso(conv.get("last_message_at")),
        "messages_in": counts["messages_in"],
        "messages_out": counts["messages_out"],
        "media_count": counts["media_count"],
        "notes_count": cint(conv.get("notes_count")),
        "first_response_seconds": row.get("first_response_seconds"),
        "conversations_count": conversations_count,
    }
    handling = {
        "status": row.get("status") or "Open",
        "assigned_to": row.get("assigned_to"),
        "assigned_to_name": row.get("assigned_to_name") or "",
        "assigned_at": _iso(conv.get("assigned_at")),
        "tags": row.get("tags") or [],
        "is_blocked": bool(row.get("is_blocked")),
        "resolved_at": _iso(conv.get("resolved_at")),
    }
    ad = row.get("ad")
    ad_block = None
    if ad:
        ad_block = {
            "headline": ad.get("headline") or "",
            "id": ad.get("ad_id") or "",
            "source_url": ad.get("url") or "",
            "body": ad.get("body") or "",
            "source": ad.get("source") or "",
            "image_url": ad.get("image_url") or "",
            "at": ad.get("at") or "",
        }
    return {
        "conversation": row,
        "identity": identity,
        "stats": stats,
        "handling": handling,
        "ad": ad_block,
        "crm": _crm(conv),
        "other_conversations": others,
        "menu": AM.info_block(conv),  # auto menu: state, path, language, form answers
    }

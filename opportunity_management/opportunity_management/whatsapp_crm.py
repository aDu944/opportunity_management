"""
CRM linkage for the WhatsApp team inbox.

Matching is done on the **last 10 digits** of the number rather than on the
normalized form, because ERPNext phone fields are typed by humans: the same
customer appears as `0770 123 4567`, `+964 770 123 4567` and
`00964-770-1234567` across Contact Phone, Lead and Customer. Comparing
suffixes is the only thing that survives that.

Lookup order is deliberate — Contact first (it is the richest link and
carries Dynamic Links to Customer/Lead/Supplier), then Lead, then Customer.
"""

import frappe

from opportunity_management.opportunity_management.whatsapp_utils import normalize_phone


SUFFIX_LENGTH = 10


def _suffix(phone) -> str:
    digits = normalize_phone(phone) or ""
    if not digits:
        return ""
    return digits[-SUFFIX_LENGTH:] if len(digits) >= SUFFIX_LENGTH else digits


def find_crm_by_phone(phone):
    """Return `{contact, lead, customer, display_name}` for the best match,
    or `{}` when the number is unknown. Never raises."""
    suffix = _suffix(phone)
    if not suffix or len(suffix) < 8:
        return {}

    like = "%" + suffix
    try:
        hit = _find_contact(like)
        if hit:
            return hit
        hit = _find_lead(like)
        if hit:
            return hit
        hit = _find_customer(like)
        if hit:
            return hit
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: CRM lookup failed")
    return {}


def _find_contact(like):
    # NOTE: the LIKE pattern is bound as a parameter, so no %% doubling is
    # needed here — `%` only has to be doubled when it appears as a *literal*
    # inside the SQL string alongside a values dict.
    rows = frappe.db.sql(
        """
        SELECT c.name AS contact,
               TRIM(CONCAT_WS(' ', c.first_name, c.last_name)) AS contact_name,
               dl.link_doctype, dl.link_name
        FROM `tabContact Phone` cp
        JOIN `tabContact` c ON c.name = cp.parent
        LEFT JOIN `tabDynamic Link` dl
               ON dl.parent = c.name
              AND dl.parenttype = 'Contact'
              AND dl.link_doctype IN ('Customer', 'Lead')
        WHERE REPLACE(REPLACE(REPLACE(REPLACE(cp.phone, ' ', ''), '-', ''), '(', ''), ')', '') LIKE %(like)s
        ORDER BY c.modified DESC
        LIMIT 5
        """,
        {"like": like},
        as_dict=True,
    )
    if not rows:
        return {}
    out = {"contact": rows[0]["contact"], "display_name": rows[0].get("contact_name") or ""}
    for row in rows:
        if row.get("link_doctype") == "Customer" and not out.get("customer"):
            out["customer"] = row["link_name"]
        elif row.get("link_doctype") == "Lead" and not out.get("lead"):
            out["lead"] = row["link_name"]
    if out.get("customer") and not out["display_name"]:
        out["display_name"] = (
            frappe.db.get_value("Customer", out["customer"], "customer_name") or ""
        )
    return out


def _find_lead(like):
    rows = frappe.db.sql(
        """
        SELECT name, lead_name, company_name
        FROM `tabLead`
        WHERE REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(mobile_no, ''), ' ', ''), '-', ''), '(', ''), ')', '') LIKE %(like)s
           OR REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(phone, ''), ' ', ''), '-', ''), '(', ''), ')', '') LIKE %(like)s
           OR REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(whatsapp_no, ''), ' ', ''), '-', ''), '(', ''), ')', '') LIKE %(like)s
        ORDER BY modified DESC
        LIMIT 1
        """,
        {"like": like},
        as_dict=True,
    )
    if not rows:
        return {}
    row = rows[0]
    return {
        "lead": row["name"],
        "display_name": row.get("lead_name") or row.get("company_name") or "",
    }


def _find_customer(like):
    rows = frappe.db.sql(
        """
        SELECT name, customer_name
        FROM `tabCustomer`
        WHERE REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(mobile_no, ''), ' ', ''), '-', ''), '(', ''), ')', '') LIKE %(like)s
        ORDER BY modified DESC
        LIMIT 1
        """,
        {"like": like},
        as_dict=True,
    )
    if not rows:
        return {}
    return {"customer": rows[0]["name"], "display_name": rows[0].get("customer_name") or ""}


def apply_crm_match(conv, match=None, save=True):
    """Write a `find_crm_by_phone` result onto a conversation.

    Only fills blanks — a manual `link_crm` must never be overwritten by the
    fuzzy phone match on the next inbound message.
    """
    match = match if match is not None else find_crm_by_phone(conv.phone)
    if not match:
        return False

    changed = {}
    for field in ("contact", "lead", "customer"):
        if match.get(field) and not conv.get(field):
            changed[field] = match[field]
    display = (match.get("display_name") or "").strip()
    if display and (not conv.display_name or conv.display_name == conv.phone):
        changed["display_name"] = display

    if not changed:
        return False
    for field, value in changed.items():
        conv.set(field, value)
    if save:
        frappe.db.set_value(
            "WhatsApp Conversation", conv.name, changed, update_modified=False
        )
    fill_whatsapp_profile_contact(conv)
    return True


def link_conversation_to_crm(conv, doctype, name):
    """Manual link from the inbox side panel.

    Cascades the way a human expects: linking a Contact pulls in the
    Customer / Lead it is a Dynamic Link of; linking a Customer or Lead
    picks up their primary Contact if there is one. Also refreshes
    `display_name` to the CRM party name, which is what agents recognise.
    """
    if doctype not in ("Contact", "Lead", "Customer", "Opportunity"):
        frappe.throw(frappe._("Unsupported CRM doctype: {0}").format(doctype))
    if not frappe.db.exists(doctype, name):
        frappe.throw(frappe._("{0} {1} not found").format(doctype, name))

    values = {doctype.lower(): name}
    display = ""

    if doctype == "Contact":
        values["contact"] = name
        display = _contact_display(name)
        for row in frappe.get_all(
            "Dynamic Link",
            filters={"parent": name, "parenttype": "Contact"},
            fields=["link_doctype", "link_name"],
        ):
            if row["link_doctype"] == "Customer" and not conv.customer:
                values["customer"] = row["link_name"]
            elif row["link_doctype"] == "Lead" and not conv.lead:
                values["lead"] = row["link_name"]
    elif doctype == "Customer":
        display = frappe.db.get_value("Customer", name, "customer_name") or name
        if not conv.contact:
            contact = _primary_contact("Customer", name)
            if contact:
                values["contact"] = contact
    elif doctype == "Lead":
        display = frappe.db.get_value("Lead", name, "lead_name") or name
        if not conv.contact:
            contact = _primary_contact("Lead", name)
            if contact:
                values["contact"] = contact
    elif doctype == "Opportunity":
        party = frappe.db.get_value(
            "Opportunity", name, ["opportunity_from", "party_name"], as_dict=True
        )
        if party and party.get("opportunity_from") == "Customer" and not conv.customer:
            values["customer"] = party.get("party_name")
        elif party and party.get("opportunity_from") == "Lead" and not conv.lead:
            values["lead"] = party.get("party_name")

    if display:
        values["display_name"] = display

    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    fill_whatsapp_profile_contact(conv)
    return values


def unlink_conversation_from_crm(conv, doctype=None):
    """Clear one CRM link, or all four when `doctype` is omitted."""
    fields = (
        [doctype.lower()]
        if doctype in ("Contact", "Lead", "Customer", "Opportunity")
        else ["contact", "lead", "customer", "opportunity"]
    )
    values = {f: None for f in fields}
    for field in fields:
        conv.set(field, None)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    return values


def _contact_display(contact_name) -> str:
    row = frappe.db.get_value(
        "Contact", contact_name, ["first_name", "last_name", "company_name"], as_dict=True
    )
    if not row:
        return contact_name
    full = " ".join(p for p in [row.get("first_name"), row.get("last_name")] if p).strip()
    return full or row.get("company_name") or contact_name


def _primary_contact(link_doctype, link_name):
    rows = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": link_doctype,
            "link_name": link_name,
            "parenttype": "Contact",
        },
        fields=["parent"],
        limit_page_length=1,
    )
    return rows[0]["parent"] if rows else None


def fill_whatsapp_profile_contact(conv):
    """Opportunistically stamp the resolved Contact onto frappe_whatsapp's
    `WhatsApp Profiles` row so its own Desk screens show a name too.

    Best-effort only: never let a profile write break the inbound hook.
    """
    try:
        if not conv.get("contact") or not conv.get("phone"):
            return
        profile = frappe.db.get_value(
            "WhatsApp Profiles", {"number": conv.phone}, ["name", "contact"], as_dict=True
        )
        if profile and not profile.get("contact"):
            frappe.db.set_value(
                "WhatsApp Profiles", profile["name"], "contact", conv.contact,
                update_modified=False,
            )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(), "WhatsApp inbox: WhatsApp Profiles contact fill failed"
        )


def search_crm(query, limit=10):
    """Type-ahead over Contact / Lead / Customer for the link sheet."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    like = "%" + query + "%"
    # `frappe.get_all` bypasses permissions by design. That is deliberate
    # here: agents need to find the Contact/Lead/Customer to link a chat to,
    # but they are not given CRM read roles. The endpoint itself is gated by
    # `_require_inbox_access()`, and only id + label are returned.
    hits = []
    for doctype, fields, label_field in (
        ("Contact", ["name", "first_name", "last_name", "company_name"], None),
        ("Lead", ["name", "lead_name", "company_name"], "lead_name"),
        ("Customer", ["name", "customer_name"], "customer_name"),
    ):
        try:
            rows = frappe.get_all(
                doctype,
                or_filters=[[f, "like", like] for f in fields if f != "name"]
                + [["name", "like", like]],
                fields=fields,
                limit_page_length=limit,
            )
        except Exception:
            rows = []
        for row in rows:
            label = (
                _contact_display(row["name"])
                if doctype == "Contact"
                else (row.get(label_field) or row["name"])
            )
            hits.append({"doctype": doctype, "name": row["name"], "label": label})
    return hits[: limit * 3]

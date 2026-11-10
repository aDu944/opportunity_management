"""
Tool executors of the WhatsApp AI responder (frappe side).

    run_tool(conv, name, args, live) -> (result, executed)

Read-only tools run in every mode. Write tools are VALIDATED here and their
side effects are applied afterwards as menu effects (ai_agent_pure.decide →
auto_menu._apply): save_customer_details → create_lead
(auto_menu._create_lead: insert_lead_for_conversation, custom_abr WA) + a
System note; send_location → the seeded Baghdad / Erbil cards;
tag_conversation → auto_menu.add_tag; handoff → auto_menu._handoff + the
summary as a note. So a failed or refused turn writes nothing. In Shadow /
Replay nothing is executed: write tools return {"recorded": true}.
"""

import frappe

from opportunity_management.opportunity_management import ai_agent_pure as P
from opportunity_management.opportunity_management.whatsapp_identity import has_phone


def _phone(conv):
    return conv.phone if has_phone(conv.get("phone")) else ""


def lookup_customer(conv):
    """What the CRM knows about this chat's customer (linked records first,
    then a phone match). Never raises."""
    from opportunity_management.opportunity_management import whatsapp_crm

    out = {"display_name": conv.get("display_name") or "", "lead": None, "customer": None, "known": False}
    try:
        lead, customer = conv.get("lead"), conv.get("customer")
        if not (lead or customer) and _phone(conv):
            match = whatsapp_crm.find_crm_by_phone(_phone(conv)) or {}
            lead, customer = match.get("lead"), match.get("customer")
            out["display_name"] = match.get("display_name") or out["display_name"]
        if lead and frappe.db.exists("Lead", lead):
            row = frappe.db.get_value("Lead", lead, ["lead_name", "company_name", "status", "city", "email_id"],
                                      as_dict=True) or {}
            out["lead"] = {"name": row.get("lead_name") or "", "company": row.get("company_name") or "",
                           "status": row.get("status") or "", "city": row.get("city") or "",
                           "has_email": bool(row.get("email_id"))}
        if customer and frappe.db.exists("Customer", customer):
            row = frappe.db.get_value("Customer", customer, ["customer_name", "customer_group"], as_dict=True) or {}
            out["customer"] = {"name": row.get("customer_name") or "", "group": row.get("customer_group") or ""}
        out["known"] = bool(out["lead"] or out["customer"])
    except Exception:
        frappe.log_error(title="WhatsApp AI: lookup_customer failed", message=frappe.get_traceback())
        return {"error": "lookup failed"}
    return out


def _active_group(group):
    group = str(group or "").strip()
    if group and frappe.db.exists("WhatsApp Agent Group", {"name": group, "is_active": 1}):
        return group
    return ""


def run_tool(conv, name, args, live):
    """(result for the model, executed). Unknown tools are errors."""
    args = args or {}
    if name == "lookup_customer":
        result = lookup_customer(conv)
        return result, "error" not in result
    if name not in P.WRITE_TOOLS:
        return {"error": "unknown tool " + str(name)}, False

    if name == "save_customer_details":
        ok, _form, errors = P.check_customer_details(args, _phone(conv))
        if not ok:
            return {"ok": False, "errors": errors}, False
        if not live:
            return {"recorded": True}, False
        known = bool(conv.get("lead") or conv.get("customer"))
        return {"ok": True, "saved": "noted for staff" if known else "lead created"}, True
    if not live:
        return {"recorded": True}, False
    if name == "send_location":
        if args.get("site") not in P.SITES:
            return {"ok": False, "error": "unknown site"}, False
        return {"ok": True, "sent": args["site"]}, True
    if name == "tag_conversation":
        if not frappe.db.exists("WhatsApp Tag", args.get("tag") or ""):
            return {"ok": False, "error": "unknown tag"}, False
        return {"ok": True}, True
    # handoff: an unknown / inactive group falls back to the escape group in decide()
    return {"ok": True, "group": _active_group(args.get("group"))}, True

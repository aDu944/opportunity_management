"""
WhatsApp AI responder: create the two doctypes and seed WhatsApp AI Settings
(persona, knowledge, disclosure and limits from ai_agent_seed.py).

Idempotent: only EMPTY fields are filled (0 counts as empty for the limits
whose default is not 0), so text edited in the form is never overwritten.
`ai_mode` stays Off until someone turns it on.
"""

import frappe

from opportunity_management.opportunity_management import ai_agent_seed as S

SETTINGS = "WhatsApp AI Settings"


def execute():
    frappe.reload_doc("opportunity_management", "doctype", "whatsapp_ai_turn", force=True)
    frappe.reload_doc("opportunity_management", "doctype", "whatsapp_ai_settings", force=True)
    doc = frappe.get_single(SETTINGS)
    filled = []
    for field, value in S.DEFAULTS.items():
        if not doc.get(field) and value:
            doc.set(field, value)
            filled.append(field)
    if doc.get("escape_group") and not frappe.db.exists("WhatsApp Agent Group", doc.escape_group):
        doc.escape_group = None  # the JSON default, before the menu seed created the group
    if not doc.get("escape_group") and frappe.db.exists("WhatsApp Agent Group", S.ESCAPE_GROUP):
        doc.escape_group = S.ESCAPE_GROUP
        filled.append("escape_group")
    doc.flags.ignore_permissions = True
    doc.save()
    frappe.db.commit()
    print("WhatsApp AI settings seeded — filled: {0}".format(", ".join(filled) or "nothing"))

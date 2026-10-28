"""
WhatsApp agent groups: the `WhatsApp Agent Group` doctype (+ its member
child table) and the conversation's `assigned_group`, `group_assigned_at`,
`group_notified_at` (agent_groups.py).

All of it is in the doctype JSON, so the model sync normally creates the
tables and columns before this runs; reloading here makes sure they exist even
when the sync skipped a doctype. Idempotent, writes no data.
"""

import frappe


def execute():
    if not frappe.db.table_exists("WhatsApp Agent Group Member"):
        frappe.reload_doc("opportunity_management", "doctype", "whatsapp_agent_group_member", force=True)
    if not frappe.db.table_exists("WhatsApp Agent Group"):
        frappe.reload_doc("opportunity_management", "doctype", "whatsapp_agent_group", force=True)
    if frappe.db.table_exists("WhatsApp Conversation") and not frappe.db.has_column(
        "WhatsApp Conversation", "assigned_group"
    ):
        frappe.reload_doc("opportunity_management", "doctype", "whatsapp_conversation", force=True)
    frappe.db.commit()
    print("WhatsApp agent groups: doctypes and conversation fields ensured")

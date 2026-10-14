"""
Add the shared team flag to `WhatsApp Conversation` (`is_flagged`,
`flagged_by`, `flagged_at`, `flag_note` — whatsapp_flags / set_flag).

The fields are in the doctype JSON, so the model sync normally creates the
columns before this runs; reloading here makes sure they exist even when the
sync skipped the doctype. Then any NULL `is_flagged` becomes 0 so the
`COALESCE(is_flagged, 0)` filters and the index-free Check read consistently.
Idempotent.
"""

import frappe


def execute():
    if not frappe.db.table_exists("WhatsApp Conversation"):
        return
    if not frappe.db.has_column("WhatsApp Conversation", "is_flagged"):
        frappe.reload_doc("opportunity_management", "doctype", "whatsapp_conversation", force=True)
    if frappe.db.has_column("WhatsApp Conversation", "is_flagged"):
        frappe.db.sql(
            """UPDATE `tabWhatsApp Conversation`
               SET is_flagged = 0
               WHERE is_flagged IS NULL"""
        )
    frappe.db.commit()
    print("WhatsApp flag: conversation fields ensured")

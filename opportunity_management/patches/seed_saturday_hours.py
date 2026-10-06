"""
Saturday is a short day: 9:00 AM – 3:00 PM (the rest of the week runs to
4:00 PM). Seed WhatsApp Inbox Settings `short_day` / `short_day_start` /
`short_day_end` so the out-of-hours check and the rendered
{{business_hours}} say so. Only fills empty values — a manager's own short
day is never overwritten. Idempotent.
"""

import frappe

from opportunity_management.opportunity_management.whatsapp_utils import clear_settings_cache

DOCTYPE = "WhatsApp Inbox Settings"


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return
    frappe.reload_doc("opportunity_management", "doctype", "whatsapp_inbox_settings")
    current = frappe.db.get_single_value(DOCTYPE, "short_day")
    if current:
        print(f"WhatsApp short day already set ({current}), left alone")
        return
    doc = frappe.get_single(DOCTYPE)
    doc.short_day = "Sat"
    doc.short_day_start = "09:00:00"
    doc.short_day_end = "15:00:00"
    doc.flags.ignore_mandatory = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    clear_settings_cache()
    print("WhatsApp short day seeded: Sat 9:00 AM – 3:00 PM")

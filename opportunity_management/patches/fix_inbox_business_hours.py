"""
Repair the WhatsApp inbox business hours seeded as the `nowtime()` artefact.

Frappe fills every `Time` field of a freshly instantiated Single with
`nowtime()`, and `seed_inbox_defaults()` only wrote fields that were still
empty, so live settings ended up with e.g. 17:26:35.827006 → 17:26:35.827074.
`is_business_hours()` read that as "no window" and the out-of-hours
auto-reply only ever fired on non-business days, never on weekday evenings.

Idempotent: only a start/end pair within a minute of each other is touched,
which is never a real window, so a second run (or a manager-configured
window) is left alone.
"""

import frappe

from opportunity_management.opportunity_management.whatsapp_utils import (
    business_window_unset,
    clear_settings_cache,
)

DOCTYPE = "WhatsApp Inbox Settings"
DEFAULT_START = "09:00:00"
DEFAULT_END = "17:00:00"


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    start = frappe.db.get_single_value(DOCTYPE, "business_hours_start")
    end = frappe.db.get_single_value(DOCTYPE, "business_hours_end")
    if not business_window_unset(start, end):
        return

    frappe.db.set_single_value(
        DOCTYPE,
        {"business_hours_start": DEFAULT_START, "business_hours_end": DEFAULT_END},
    )
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
    clear_settings_cache()
    frappe.db.commit()
    print(
        f"WhatsApp inbox: business hours {start!s} → {end!s} reset to "
        f"{DEFAULT_START} → {DEFAULT_END}"
    )

"""
Add `custom_deleted_at` / `custom_deleted_by` to `WhatsApp Message` (team-side
soft delete, `whatsapp_api_delete`) via
`whatsapp_setup.create_whatsapp_message_custom_fields`.

Fixtures sync only after post_model_sync patches; the thread reads these
columns only when `frappe.db.has_column` says so. Nothing to backfill.
Idempotent.
"""

import frappe


def execute():
    if not frappe.db.table_exists("WhatsApp Message"):
        return
    from opportunity_management.opportunity_management.whatsapp_setup import (
        create_whatsapp_message_custom_fields,
    )

    create_whatsapp_message_custom_fields()
    frappe.db.commit()
    print("WhatsApp delete message: custom fields ensured")

"""
Messenger channel in the team inbox (messenger_contract.md):

* the `custom_channel` field on `WhatsApp Message` (whatsapp_setup — fixtures
  sync only after post_model_sync patches, and the override / serializer read
  it as soon as the new code is live);
* the `Messenger Agent` / `Messenger Manager` roles and their read DocPerm on
  `WhatsApp Message` (private-file access);
* `channel = "WhatsApp"` on every existing conversation still empty.

Idempotent: re-running creates nothing twice and only touches empty rows.
"""

import frappe


def execute():
    from opportunity_management.opportunity_management import whatsapp_setup

    if frappe.db.table_exists("WhatsApp Message"):
        whatsapp_setup.create_whatsapp_message_custom_fields()
    whatsapp_setup.ensure_messenger_roles()
    whatsapp_setup.ensure_whatsapp_roles_and_perms()

    filled = 0
    if frappe.db.has_column("WhatsApp Conversation", "channel"):
        frappe.db.sql(
            """UPDATE `tabWhatsApp Conversation`
               SET channel = 'WhatsApp'
               WHERE channel IS NULL OR channel = ''"""
        )
        filled = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
    frappe.db.commit()
    print(f"Messenger channel: fields and roles ensured, {filled} conversation(s) set to WhatsApp")

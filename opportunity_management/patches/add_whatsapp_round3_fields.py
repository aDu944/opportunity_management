"""
Add the round-3 `WhatsApp Message` custom fields (`custom_payload`,
`custom_is_voice`, `custom_sent_at`, `custom_delivered_at`, `custom_read_at`,
`custom_error`) via `whatsapp_setup.create_whatsapp_message_custom_fields`.

Fixtures sync only after post_model_sync patches, and the serializer, the
send override and the status hook read these columns as soon as the new code
is live. Nothing to backfill: message-info times are recorded from now on.
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
    print("WhatsApp round 3: message custom fields ensured")

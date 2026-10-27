"""
"Create opportunity" from a chat (whatsapp_api_opportunity):

* `custom_abr` (Data) on `Lead` — Opportunity.custom_abr is fetched from
  `party_name.custom_abr` and the INQ naming series embeds it, so a Lead
  without it produced malformed names like `Inq. 512--0-26`. Created here
  because fixtures sync only after post_model_sync patches;
* Lead Sources "WhatsApp" and "Messenger", set on chat-created Leads.

Idempotent: `create_custom_fields(update=True)` and insert-if-missing.
"""

import frappe

LEAD_ABR_CUSTOM_FIELDS = {
    "Lead": [
        {
            "fieldname": "custom_abr",
            "fieldtype": "Data",
            "label": "Abbreviation",
            "insert_after": "company_name",
            "description": "Short code used in Opportunity names (fetched into "
                           "Opportunity.custom_abr). WhatsApp-created leads default to WA.",
        },
    ]
}

LEAD_SOURCES = ("WhatsApp", "Messenger")


def execute():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields(LEAD_ABR_CUSTOM_FIELDS, update=True)

    created = []
    if frappe.db.table_exists("Lead Source"):
        for source in LEAD_SOURCES:
            if not frappe.db.exists("Lead Source", source):
                frappe.get_doc({"doctype": "Lead Source", "source_name": source}).insert(
                    ignore_permissions=True
                )
                created.append(source)

    frappe.db.commit()
    print(
        "Lead abbreviation: field ensured"
        + (f"; Lead Source created: {', '.join(created)}" if created else "")
    )

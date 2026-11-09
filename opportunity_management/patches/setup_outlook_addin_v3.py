"""
Outlook add-in, asset version v3 (create + assign Opportunities, attachment
picker, Outlook categories):

* the OAuth Client gains the v3 sign-in redirect URI (older ones are kept);
* Communication.custom_outlook_conversation_id (in case Phase 1's patch has
  not run on this site);
* Lead Source "Email", set on Leads and Opportunities created from Outlook.

Idempotent.
"""

import frappe

LEAD_SOURCE = "Email"


def execute():
    from opportunity_management.opportunity_management.outlook_addin import (
        ensure_conversation_field,
        ensure_oauth_client,
    )

    ensure_conversation_field()
    client_id = ensure_oauth_client()
    created = False
    if frappe.db.table_exists("Lead Source") and not frappe.db.exists("Lead Source", LEAD_SOURCE):
        frappe.get_doc({"doctype": "Lead Source", "source_name": LEAD_SOURCE}).insert(
            ignore_permissions=True
        )
        created = True
    frappe.db.commit()
    print(f"Outlook add-in v3: OAuth Client {client_id} has the v3 redirect"
          + ("; Lead Source 'Email' created" if created else ""))

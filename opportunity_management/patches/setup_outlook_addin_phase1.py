"""
Outlook add-in Phase 1 (link emails to Opportunities):

* Custom Field Communication.custom_outlook_conversation_id (indexed) — the
  Outlook thread an email belongs to, so later emails in it are suggested;
* the OAuth Client gains the current sign-in redirect URI (v1 is kept so the
  Phase 0 manifest keeps working until it is removed from Outlook).

Idempotent.
"""

import frappe


def execute():
    from opportunity_management.opportunity_management.outlook_addin import (
        ensure_conversation_field,
        ensure_oauth_client,
    )

    ensure_conversation_field()
    client_id = ensure_oauth_client()
    frappe.db.commit()
    print(f"Outlook add-in Phase 1: conversation field ready; OAuth Client {client_id} has the current redirect")

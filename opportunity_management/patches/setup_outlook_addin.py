"""
Outlook add-in (Phase 0): create the trusted "Outlook Add-in" OAuth Client
the task pane signs in with (Authorization Code + PKCE). Idempotent - see
outlook_addin.ensure_oauth_client.
"""

import frappe


def execute():
    from opportunity_management.opportunity_management.outlook_addin import ensure_oauth_client

    client_id = ensure_oauth_client()
    frappe.db.commit()
    print(f"Outlook add-in: OAuth Client ready ({client_id})")

"""
Outlook add-in, asset version v4 (Responsible Party picker, parse items):
the OAuth Client gains the v4 sign-in redirect URI (older ones are kept, so
installed v1-v3 manifests keep signing in). Idempotent.
"""

import frappe


def execute():
    from opportunity_management.opportunity_management.outlook_addin import ensure_oauth_client

    client_id = ensure_oauth_client()
    frappe.db.commit()
    print(f"Outlook add-in v4: OAuth Client {client_id} has the v4 redirect")

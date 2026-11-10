"""
Outlook add-in, asset version v5 (parse the email text, add extra files):
the OAuth Client gains the v5 sign-in redirect URI (older ones are kept, so
installed v1-v4 manifests keep signing in). Idempotent.
"""

import frappe


def execute():
    from opportunity_management.opportunity_management.outlook_addin import ensure_oauth_client

    client_id = ensure_oauth_client()
    frappe.db.commit()
    print(f"Outlook add-in v5: OAuth Client {client_id} has the v5 redirect")

"""
Outlook add-in v6: the stable "app" folder (loader + sign-in callback) that
every future version is served through. The OAuth Client gains the stable
redirect URI; the v1-v5 ones stay so installed older manifests keep working.
Idempotent.
"""

import frappe


def execute():
    from opportunity_management.opportunity_management.outlook_addin import ensure_oauth_client

    client_id = ensure_oauth_client()
    frappe.db.commit()
    print(f"Outlook add-in v6: OAuth Client {client_id} has the stable app/ redirect")

"""
Outlook add-in: server side (Phase 0 - connectivity and sign-in test).

The task pane (public/outlook/<version>/) signs in with ERPNext's built-in
OAuth server - Authorization Code + PKCE with no client secret, which
frappe/oauth.py (v15) accepts: `authenticate_client` loads the client from
`client_id` alone and `validate_code` checks the S256 code verifier.

* `ensure_oauth_client()` creates/updates the "Outlook Add-in" OAuth Client
  (trusted: skip_authorization, so users see no consent screen). Called from
  after_install and the setup_outlook_addin patch; idempotent.
* `get_config()` (guest, GET) hands the task pane the client_id and endpoints.
  Every value in it is public - the client has no secret worth hiding.

Site URL: site_config `outlook_addin_site_url` if set, else get_url() forced
to https (see outlook_addin_pure.normalize_site_url).
"""

import frappe

from opportunity_management.opportunity_management import outlook_addin_pure as pure


def _site_url() -> str:
    return frappe.conf.get("outlook_addin_site_url") or frappe.utils.get_url()


def _find_client():
    return frappe.db.get_value("OAuth Client", {"app_name": pure.APP_NAME}, "name")


def ensure_oauth_client() -> str:
    """Create or update the add-in's OAuth Client; returns its client_id."""
    name = _find_client()
    doc = frappe.get_doc("OAuth Client", name) if name else frappe.new_doc("OAuth Client")
    values = pure.client_values(_site_url(), doc.get("redirect_uris") or "")
    changed = False
    for field, value in values.items():
        if doc.get(field) != value:
            doc.set(field, value)
            changed = True
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    elif changed:
        doc.save(ignore_permissions=True)
    return doc.name


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_config():
    client_id = _find_client()
    if not client_id:
        frappe.throw("The Outlook add-in is not set up on this site yet (run bench migrate).")
    return pure.public_config(_site_url(), client_id)

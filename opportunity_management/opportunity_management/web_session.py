"""
Session helpers for the web Team Inbox (same-origin browser client).

Frappe checks `X-Frappe-CSRF-Token` on cookie-authenticated POSTs once the
session holds a token, but `frappe.sessions.get_csrf_token` itself is not
whitelisted (it is meant for the Desk boot), so a browser client has no
sanctioned way to read it — every POST would fail with 400 CSRFTokenError.
This exposes it to logged-in users only.
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_csrf_token():
    if frappe.session.user == "Guest":
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    from frappe.sessions import get_csrf_token as _token

    return _token()

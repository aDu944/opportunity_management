"""
A minimal Graph API client for the calls frappe_whatsapp has no method for:
the typing indicator (`POST /<phone_id>/messages` with `typing_indicator`)
and the block list (`POST` / `DELETE /<phone_id>/block_users`).

Same URL, version and token as upstream's `WhatsAppMessage.notify`:
`{account.url}/{account.version}/{account.phone_id}/<path>` with the
account's `token` password as a Bearer token. Errors come back as
`MetaSendError` carrying Meta's own reason (`whatsapp_payloads.error_message`)
— raised plainly, NOT through `frappe.throw`, so a caller that swallows it
(the typing indicator) leaves no msgprint behind for the client to show.
"""

import json

import frappe
from frappe import _

from opportunity_management.opportunity_management.whatsapp_api_common import MetaSendError
from opportunity_management.opportunity_management.whatsapp_payloads import error_message

TIMEOUT = 15


def endpoint(account, path) -> str:
    return "{0}/{1}/{2}/{3}".format(
        str(account.url or "").rstrip("/"), account.version, account.phone_id, path.lstrip("/")
    )


def meta_request(whatsapp_account, path, body, method="POST") -> dict:
    """POST / DELETE `body` to `<phone_id>/<path>`; the parsed JSON response."""
    import requests

    if not whatsapp_account:
        raise MetaSendError(_("This conversation has no WhatsApp Account"))
    account = frappe.get_doc("WhatsApp Account", whatsapp_account)
    headers = {
        "authorization": "Bearer {0}".format(account.get_password("token")),
        "content-type": "application/json",
    }
    try:
        response = requests.request(
            method, endpoint(account, path), headers=headers, data=json.dumps(body), timeout=TIMEOUT
        )
    except requests.RequestException as exc:
        raise MetaSendError(_("Could not reach WhatsApp: {0}").format(str(exc)[:200]))
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if response.status_code >= 400 or payload.get("error"):
        raise MetaSendError(error_message(payload) or "HTTP {0}".format(response.status_code))
    return payload

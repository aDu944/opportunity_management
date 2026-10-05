"""
Meta → us for the Messenger channel:

    /api/method/opportunity_management.opportunity_management.messenger_webhook.webhook

GET  is Meta's verification handshake: `hub.mode=subscribe` and
     `hub.verify_token` equal to Messenger Settings `verify_token` → the
     `hub.challenge` echoed back as plain text; anything else → 403.
POST is a Page event delivery. `X-Hub-Signature-256` must be the
     HMAC-SHA256 of the raw body with the App Secret (Messenger Settings
     `app_secret`, else `site_config.whatsapp_app_secret` — one Meta app
     usually serves both products). With no secret configured it is logged
     once per request and accepted, like the WhatsApp wrapper.
     `object` must be "page"; entries for another Page are ignored.

Every event is handled in its own transaction (`messenger_ingest.handle`),
so one bad event never drops the rest, and the answer is always 200 for a
signed delivery — a non-200 makes Meta retry the batch for hours, and the
mid dedupe makes a retry harmless anyway. Downloads and profile fetches
are background jobs, so the request stays quick.
"""

import json

import frappe
from frappe.utils import cint

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import messenger_api as API
from opportunity_management.opportunity_management import messenger_events as EV

_SIGNATURE_HEADER = "X-Hub-Signature-256"


@frappe.whitelist(allow_guest=True)
def webhook():
    if frappe.request and frappe.request.method == "GET":
        return _verify()

    settings = IC.messenger_settings()
    if not cint(settings.get("enabled")):
        return "ok"
    raw = frappe.request.get_data() if frappe.request else b""
    if not _signature_ok(settings, raw):
        frappe.local.response["http_status_code"] = 403
        return "forbidden"
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return "ok"

    from opportunity_management.opportunity_management import messenger_ingest

    error = None
    for event in EV.parse(data, settings.get("page_id") or None):
        try:
            messenger_ingest.handle(event)
            frappe.db.commit()
        except Exception as exc:
            frappe.db.rollback()
            error = "{0}: {1}".format(event.get("kind"), str(exc)[:300])
            frappe.log_error(frappe.get_traceback(), "Messenger webhook: event failed")
    messenger_ingest.stamp_webhook(error)
    frappe.db.commit()
    return "ok"


def _verify():
    from werkzeug.wrappers import Response

    form = frappe.local.form_dict
    expected = str(IC.messenger_settings().get("verify_token") or "")
    if (
        form.get("hub.mode") == "subscribe"
        and expected
        and form.get("hub.verify_token") == expected
    ):
        return Response(str(form.get("hub.challenge") or ""), status=200, mimetype="text/plain")
    return Response("forbidden", status=403, mimetype="text/plain")


def app_secret(settings):
    secret = None
    try:
        secret = settings.get_password("app_secret", raise_exception=False)
    except Exception:
        secret = None
    return secret or frappe.conf.get("whatsapp_app_secret")


def _signature_ok(settings, raw) -> bool:
    secret = app_secret(settings)
    if not secret:
        if not getattr(frappe.local, "_messenger_missing_secret_logged", False):
            frappe.local._messenger_missing_secret_logged = True
            frappe.log_error(
                "No App Secret in Messenger Settings or site_config — Messenger "
                "webhooks are accepted without signature verification.",
                "Messenger webhook: signature verification disabled",
            )
        return True
    return API.valid_signature(secret, raw, frappe.get_request_header(_SIGNATURE_HEADER))

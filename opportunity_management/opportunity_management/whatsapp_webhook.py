"""
Guarded wrapper around `frappe_whatsapp.utils.webhook.webhook`.

Registered through `override_whitelisted_methods` in hooks.py, so Meta keeps
POSTing to the URL it already has configured
(`/api/method/frappe_whatsapp.utils.webhook.webhook`) and we get a seam
without touching the frappe_whatsapp source.

Three things the upstream handler does not do (verified on v1.0.12):

1. **No signature check.** Anyone who knows the URL can inject messages.
   We verify `X-Hub-Signature-256` against `frappe.conf.whatsapp_app_secret`.
   With no secret configured we log once and allow, so the integration keeps
   working until the Meta App Secret is available (plan assumption 1).
2. **No `message_id` dedupe.** Meta retries aggressively — a slow request or
   a 500 produces the same message twice.
3. **`location` / `contacts` / unknown inbound types raise KeyError**, which
   500s the request and makes Meta retry forever. We rewrite those entries
   into `text` before the original ever sees them.

`webhook.post()` reads `frappe.local.form_dict`, so mutating it in place is
enough — the original picks up our edits.
"""

import hashlib
import hmac
import json

import frappe

_SIGNATURE_HEADER = "X-Hub-Signature-256"
_MISSING_SECRET_FLAG = "_whatsapp_missing_secret_logged"


@frappe.whitelist(allow_guest=True)
def webhook():
    """Meta webhook entry point (GET verify handshake / POST events)."""
    try:
        if frappe.request and frappe.request.method == "GET":
            # The hub.challenge handshake — nothing to guard, nothing to
            # dedupe. Hand it straight over.
            return _original()()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: GET delegation failed")
        raise

    try:
        if not _verify_signature():
            frappe.local.response["http_status_code"] = 403
            return "forbidden"
    except frappe.PermissionError:
        raise
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: signature check failed")

    try:
        data = frappe.local.form_dict
        dropped = _dedupe_messages(data)
        _coerce_unsupported(data)
        if dropped and not _has_payload(data):
            # Everything in this delivery was a retry we already stored.
            return "ok"
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: preprocessing failed")

    try:
        return _original()()
    except Exception:
        # Return 200 regardless: the raw payload is already persisted in
        # `WhatsApp Notification Log` by the original handler, and a non-200
        # makes Meta retry the same delivery for hours.
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: delegation failed")
        return "ok"


def _original():
    """Import lazily — hooks.py is loaded on every request, and importing
    frappe_whatsapp at module scope would make this app hard-depend on it."""
    from frappe_whatsapp.utils.webhook import webhook as original_webhook

    return original_webhook


# ── signature ────────────────────────────────────────────────────────────────

def _verify_signature() -> bool:
    secret = frappe.conf.get("whatsapp_app_secret")
    if not secret:
        if not getattr(frappe.local, _MISSING_SECRET_FLAG, False):
            setattr(frappe.local, _MISSING_SECRET_FLAG, True)
            frappe.log_error(
                "whatsapp_app_secret is not set in site_config.json — inbound "
                "WhatsApp webhooks are being accepted without signature "
                "verification.",
                "WhatsApp webhook: signature verification disabled",
            )
        return True

    header = (frappe.get_request_header(_SIGNATURE_HEADER) or "").strip()
    if not header.startswith("sha256="):
        return False

    raw = frappe.request.get_data() if frappe.request else b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    expected = hmac.new(
        str(secret).encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1].strip())


# ── payload surgery ──────────────────────────────────────────────────────────

def _entries(data):
    entry = data.get("entry")
    if isinstance(entry, dict):
        entry = [entry]
    return entry if isinstance(entry, list) else []


def _values(data):
    """Yield every `changes[].value` dict in the payload."""
    for entry in _entries(data):
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if isinstance(change, dict) and isinstance(change.get("value"), dict):
                yield change["value"]


def _dedupe_messages(data) -> int:
    """Drop message entries whose `message_id` is already stored.

    Returns how many were dropped. Status callbacks are left alone — those
    are idempotent updates by design.
    """
    dropped = 0
    for value in _values(data):
        messages = value.get("messages")
        if not isinstance(messages, list) or not messages:
            continue
        kept = []
        for message in messages:
            mid = message.get("id") if isinstance(message, dict) else None
            if mid and frappe.db.exists("WhatsApp Message", {"message_id": mid}):
                dropped += 1
                continue
            kept.append(message)
        if len(kept) != len(messages):
            value["messages"] = kept
            if not kept:
                value.pop("messages", None)
    return dropped


_SUPPORTED_TYPES = {
    "text", "image", "audio", "video", "document", "button",
    "interactive", "reaction", "order",
}


def _coerce_unsupported(data):
    """Rewrite entries the upstream handler would KeyError on into `text`."""
    for value in _values(data):
        messages = value.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            mtype = message.get("type")
            if mtype in _SUPPORTED_TYPES:
                continue
            if mtype == "sticker" and isinstance(message.get("sticker"), dict):
                # Upstream has no `sticker` branch (KeyError), but its `image`
                # branch downloads any media id and attaches it. A sticker is
                # just a webp with the same {id, mime_type} shape, so present
                # it as an image and the customer's sticker is preserved
                # instead of being flattened to "[unsupported]".
                sticker = dict(message["sticker"])
                sticker.setdefault("caption", "")
                message["type"] = "image"
                message["image"] = sticker
                continue
            if mtype == "location":
                body = _location_text(message.get("location") or {})
            elif mtype == "contacts":
                body = _contacts_text(message.get("contacts") or [])
            else:
                body = f"[unsupported message type: {mtype}]"
            message["type"] = "text"
            message["text"] = {"body": body}


def _location_text(location) -> str:
    lat = location.get("latitude")
    lon = location.get("longitude")
    parts = ["\U0001F4CD Location"]
    name = (location.get("name") or "").strip()
    address = (location.get("address") or "").strip()
    if name:
        parts.append(name)
    if address:
        parts.append(address)
    if lat is not None and lon is not None:
        parts.append(f"{lat},{lon}")
        parts.append(f"https://maps.google.com/?q={lat},{lon}")
    return "\n".join(parts)


def _contacts_text(contacts) -> str:
    lines = ["\U0001F464 Contact card"]
    for contact in contacts[:5]:
        if not isinstance(contact, dict):
            continue
        name = (contact.get("name") or {}).get("formatted_name") or ""
        phones = ", ".join(
            p.get("phone", "") for p in (contact.get("phones") or []) if isinstance(p, dict)
        )
        line = " — ".join(part for part in (name, phones) if part)
        if line:
            lines.append(line)
    return "\n".join(lines) if len(lines) > 1 else "\U0001F464 Contact card"


def _has_payload(data) -> bool:
    for value in _values(data):
        if value.get("messages") or value.get("statuses"):
            return True
        # message_template_status_update and friends carry neither.
        if set(value.keys()) - {"messaging_product", "metadata", "contacts"}:
            return True
    return False


# ── local end-to-end helper ──────────────────────────────────────────────────

def simulate(fixture="text_inbound"):
    """Feed a stored Meta payload through the wrapper, for `bench execute`:

        bench --site erp.local execute \\
          opportunity_management.opportunity_management.whatsapp_webhook.simulate \\
          --kwargs "{'fixture': 'text_inbound'}"

    Fixtures live in `opportunity_management/opportunity_management/tests/fixtures/`
    as `meta_<fixture>.json`. Signature verification is skipped (there is no
    HTTP request to sign) — everything after it runs for real, so this does
    insert WhatsApp Messages and does fire the hooks.
    """
    import os

    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "tests",
        "fixtures",
        f"meta_{fixture}.json",
    )
    with open(path) as handle:
        payload = json.load(handle)

    frappe.local.form_dict = frappe._dict(payload)
    data = frappe.local.form_dict
    dropped = _dedupe_messages(data)
    _coerce_unsupported(data)
    if dropped and not _has_payload(data):
        return {"fixture": fixture, "dropped": dropped, "result": "all duplicates"}

    _original()()
    frappe.db.commit()
    return {"fixture": fixture, "dropped": dropped, "result": "delivered"}

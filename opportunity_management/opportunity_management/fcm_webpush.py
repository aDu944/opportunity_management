"""
Pure helpers for multi-device (web) push — no frappe import, so the bench-free
tests load this file straight off disk.

    build_webpush(title, body, data, site_url)  → FCM v1 `webpush` block
    inbox_link(data, site_url)                  → click-through URL
    merge_targets(primary_token, device_rows)   → deduplicated send list
    is_bad_token_response(status, text)         → FCM says the token is dead

A browser has no notification sound, so the block carries none; the Android /
APNs blocks `send_fcm` builds for phones are untouched by any of this.
"""

from urllib.parse import quote

WEB_ICON = "/assets/opportunity_management/inbox/icons/Icon-192.png"
CONVERSATION_DOCTYPE = "WhatsApp Conversation"


def _clean_base(site_url):
    return str(site_url or "").rstrip("/")


def is_conversation_push(data):
    """True when `data.name` names an inbox conversation (WhatsApp or
    Messenger — both are `WhatsApp Conversation` rows)."""
    data = data or {}
    if not data.get("name"):
        return False
    return data.get("doctype") == CONVERSATION_DOCTYPE or (
        not data.get("doctype") and data.get("screen") == "whatsapp"
    )


def inbox_link(data, site_url):
    """`<site>/inbox#/chats/<conversation>` for a conversation push, else
    `<site>/inbox`. `/inbox` redirects to the current versioned build; the
    fragment survives the redirect."""
    base = _clean_base(site_url) + "/inbox"
    if is_conversation_push(data):
        return base + "#/chats/" + quote(str(data["name"]), safe="")
    return base


def build_webpush(title, body, data, site_url):
    """The FCM v1 `webpush` block for a browser token. `data` must already be
    stripped of private keys; every value is stringified (FCM rejects
    non-string data)."""
    data = {str(k): str(v) for k, v in (data or {}).items()}
    return {
        "headers": {"Urgency": "high"},
        "notification": {"title": title, "body": body, "icon": WEB_ICON},
        "fcm_options": {"link": inbox_link(data, site_url)},
        "data": data,
    }


def merge_targets(primary_token, device_rows):
    """Ordered, token-deduplicated send list.

    The Employee's own token (if any) comes first as `{"token", "platform":
    None, "device": None}` — `device` None means "never disable anything on
    failure", so the phone's field keeps today's behaviour. Then each enabled
    `ESS Push Device` row (`{"name", "token", "platform"}`) whose token was
    not already listed."""
    out, seen = [], set()
    if primary_token:
        out.append({"token": primary_token, "platform": None, "device": None})
        seen.add(primary_token)
    for row in device_rows or []:
        token = (row or {}).get("token")
        if not token or token in seen:
            continue
        seen.add(token)
        out.append({
            "token": token,
            "platform": (row.get("platform") or None),
            "device": row.get("name"),
        })
    return out


def is_bad_token_response(status, text):
    """True when an FCM v1 error response means the token itself is dead.

    `UNREGISTERED` (404) always is. `INVALID_ARGUMENT` (400) is only when the
    message blames the registration token — the same status also covers a
    malformed payload, which must not disable every browser at once."""
    if status not in (400, 404):
        return False
    text = str(text or "")
    if "UNREGISTERED" in text:
        return True
    if "INVALID_ARGUMENT" in text and "registration token" in text.lower():
        return True
    return False

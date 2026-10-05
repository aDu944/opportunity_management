"""
Meta Messenger Platform: request bodies, error mapping and a small Graph
client for the Messenger channel of the team inbox.

Verified against Meta's documentation on 2026-10-05 (Graph v25.0 in every
current example):
  send      developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
            `{recipient: {id: PSID}, messaging_type, message: {text}}`, attachments
            `{type, payload: {url, is_reusable}}`, top-level `reply_to: {mid}`,
            response `{recipient_id, message_id}`; HUMAN_AGENT = 7 days.
  actions   …/messenger-platform/send-messages/sender-actions
            `typing_on`, `mark_seen`, `react` (`payload {message_id, reaction}`),
            `unreact` (`payload {message_id}`); an action request carries ONLY
            `recipient` + `sender_action` (+ `payload`).
  limits    text 2000 chars, ≤ 13 quick replies (title 20 chars), attachments
            8 MB for images / 25 MB otherwise (…/send-messages/saving-assets).
  errors    code 10 / subcode 2018278 = outside the allowed window; 551 =
            person unavailable (…/messenger-platform/error-codes).
  profile   GET /<PSID>?fields=first_name,last_name,profile_pic
            (…/messenger-platform/identity/user-profile).

Everything above the client is pure (no `frappe`), so
`tests/test_messenger_pure.py` asserts the exact bodies bench-free.
"""

import hashlib
import hmac
import json

GRAPH_HOST = "https://graph.facebook.com"
DEFAULT_GRAPH_VERSION = "v25.0"
TIMEOUT = 15

MAX_TEXT = 2000
MAX_QUICK_REPLIES = 13
MAX_QUICK_REPLY_TITLE = 20
MAX_IMAGE_MB = 8
MAX_ATTACHMENT_MB = 25
PSID_PREFIX = "FB."
# Marker on every message we send; Meta returns it on the echo, which is how
# the webhook tells our own sends from replies typed in Meta Business Suite.
OUR_METADATA = "alkhora_inbox"

# WhatsApp Message content_type → Messenger attachment type.
ATTACHMENT_TYPES = {"image": "image", "audio": "audio", "video": "video", "document": "file"}

WINDOW_ERRORS = ((10, 2018278),)
UNAVAILABLE_CODE = 551


class GraphError(Exception):
    """A Graph API failure; `window` is True for the closed-window errors."""

    def __init__(self, message, code=None, subcode=None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.window = is_window_error(code, subcode)


# ── identity ─────────────────────────────────────────────────────────────────

def psid_of(identifier) -> str:
    """`FB.123` → `123` (the id Meta wants in `recipient`)."""
    value = str(identifier or "").strip()
    return value[len(PSID_PREFIX):] if value.startswith(PSID_PREFIX) else value


def identifier_for(psid) -> str:
    return PSID_PREFIX + str(psid or "").strip()


def conversation_key(page_id, psid) -> str:
    return "messenger:{0}:{1}".format(page_id or "", psid or "")


# ── bodies ───────────────────────────────────────────────────────────────────

def split_text(text, limit=MAX_TEXT) -> list:
    """Cut `text` into ≤ `limit` chunks, preferring a newline, then a space."""
    text = str(text or "")
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = text.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text or not chunks:
        chunks.append(text)
    return [c for c in chunks if c] or [""]


def messaging_fields(mode) -> dict:
    """`messaging_type` (+ `tag`) for the window mode; None when closed."""
    if mode == "standard":
        return {"messaging_type": "RESPONSE"}
    if mode == "human_agent":
        return {"messaging_type": "MESSAGE_TAG", "tag": "HUMAN_AGENT"}
    return None


def _envelope(psid, mode, message, reply_to=None) -> dict:
    fields = messaging_fields(mode)
    if fields is None:
        raise ValueError("window closed")
    body = {"recipient": {"id": psid_of(psid)}}
    body.update(fields)
    body["message"] = message
    if reply_to:
        body["reply_to"] = {"mid": reply_to}
    return body


def quick_replies(titles) -> list:
    out = []
    for title in list(titles or [])[:MAX_QUICK_REPLIES]:
        title = str(title or "").strip()
        if title:
            out.append({
                "content_type": "text",
                "title": title[:MAX_QUICK_REPLY_TITLE],
                "payload": title[:1000],
            })
    return out


def text_bodies(psid, text, mode, reply_to=None, options=None) -> list:
    """One body per ≤ 2000-char chunk; `reply_to` on the first, the quick
    replies on the last (they belong under the question)."""
    chunks = split_text(text)
    bodies = []
    for i, chunk in enumerate(chunks):
        message = {"text": chunk, "metadata": OUR_METADATA}
        if options and i == len(chunks) - 1:
            message["quick_replies"] = quick_replies(options)
        bodies.append(_envelope(psid, mode, message, reply_to if i == 0 else None))
    return bodies


def attachment_body(psid, content_type, url, mode, reply_to=None) -> dict:
    kind = ATTACHMENT_TYPES.get(str(content_type or "").lower(), "file")
    message = {
        "attachment": {"type": kind, "payload": {"url": url, "is_reusable": False}},
        "metadata": OUR_METADATA,
    }
    return _envelope(psid, mode, message, reply_to)


def sender_action_body(psid, action) -> dict:
    return {"recipient": {"id": psid_of(psid)}, "sender_action": action}


def reaction_body(psid, mid, emoji) -> dict:
    """React with `emoji`, or (empty emoji) remove our reaction."""
    emoji = str(emoji or "").strip()
    body = sender_action_body(psid, "react" if emoji else "unreact")
    body["payload"] = {"message_id": mid}
    if emoji:
        body["payload"]["reaction"] = emoji
    return body


def max_bytes(content_type) -> int:
    mb = MAX_IMAGE_MB if str(content_type or "").lower() == "image" else MAX_ATTACHMENT_MB
    return mb * 1024 * 1024


# ── errors ───────────────────────────────────────────────────────────────────

def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_window_error(code, subcode) -> bool:
    code, subcode = _int(code), _int(subcode)
    return (code, subcode) in WINDOW_ERRORS or code == UNAVAILABLE_CODE


def error_info(payload):
    """`(message, code, subcode)` from a Graph error response."""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return "", None, None
    message = error.get("error_user_msg") or error.get("message") or ""
    code, subcode = _int(error.get("code")), _int(error.get("error_subcode"))
    if code is not None:
        message = "({0}) {1}".format(code, message).strip()
    return message, code, subcode


def valid_signature(secret, raw, header) -> bool:
    """`X-Hub-Signature-256: sha256=<hex HMAC-SHA256(raw body, app secret)>`."""
    header = str(header or "").strip()
    if not secret or not header.startswith("sha256="):
        return False
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    expected = hmac.new(str(secret).encode("utf-8"), raw or b"", hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1].strip())


# ── client ───────────────────────────────────────────────────────────────────

def graph_url(version, path) -> str:
    return "{0}/{1}/{2}".format(GRAPH_HOST, version or DEFAULT_GRAPH_VERSION, str(path).lstrip("/"))


def graph_request(settings, method, path, body=None, params=None) -> dict:
    """Call the Graph API with the Page token; the parsed JSON or GraphError."""
    import requests

    token = settings.get_password("page_access_token", raise_exception=False) if settings else None
    if not token:
        raise GraphError("Messenger is not configured: no Page access token")
    query = dict(params or {}, access_token=token)
    try:
        response = requests.request(
            method, graph_url(settings.get("graph_version"), path), params=query,
            data=json.dumps(body) if body is not None else None,
            headers={"content-type": "application/json"} if body is not None else None,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GraphError("Could not reach Messenger: {0}".format(str(exc)[:200]))
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if response.status_code >= 400 or payload.get("error"):
        message, code, subcode = error_info(payload)
        raise GraphError(message or "HTTP {0}".format(response.status_code), code, subcode)
    return payload


def send(settings, body) -> dict:
    return graph_request(settings, "POST", "me/messages", body=body)

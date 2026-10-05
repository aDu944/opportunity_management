"""
Pure builders and parsers for the round-3 message kinds of the WhatsApp
inbox: location / contact cards, voice notes, interactive options, typing
indicators, the block list and Meta's status-callback errors.

Nothing here touches the database or `frappe` at import time (no `frappe`
import at all), so `tests/test_whatsapp_payloads.py` loads it bench-free and
asserts the exact request bodies.

Request bodies follow Meta's Cloud API docs (verified 2026-10-03):
  typing     developers.facebook.com/docs/whatsapp/cloud-api/typing-indicators
  location   …/cloud-api/messages/location-messages
  contacts   …/cloud-api/messages/contacts-messages
  voice      …/cloud-api/messages/audio-messages  (`audio.voice`, Ogg/Opus mono)
  buttons    …/cloud-api/messages/interactive-reply-buttons-messages
  list       …/cloud-api/messages/interactive-list-messages
  block      …/cloud-api/block-users

`custom_payload` on a `WhatsApp Message` row is the JSON this module reads and
writes. Its `kind` decides how the serializer presents the row:

    {"kind": "location", "location": {latitude, longitude, name, address}}
    {"kind": "contact",  "contacts": [{name, phones, emails, org}]}
    {"kind": "voice",    "voice": true|false, "duration": int|null}

An inbound location / contacts message is still stored as upstream `text`
(the webhook wrapper coerces it — upstream KeyErrors otherwise); the marker
is what turns it back into a card.
"""

import json
import re

MAX_VIDEO_MB = 16
MAX_OPTIONS = 10
MAX_BUTTONS = 3
MAX_OPTION_CHARS = 20
# Reply-button body is capped at 1024 by Meta, a list body at 4096.
MAX_BUTTON_BODY = 1024
MAX_LIST_BODY = 4096
CARD_KINDS = ("location", "contact")

# Meta status → the column that records when it happened.
STATUS_FIELDS = {
    "sent": "custom_sent_at",
    "delivered": "custom_delivered_at",
    "read": "custom_read_at",
}


class PayloadError(ValueError):
    """Bad input for a payload; the message is shown to the agent as-is."""


# ── custom_payload ───────────────────────────────────────────────────────────

def load_payload(raw):
    """The decoded `custom_payload` dict, or {} for empty / malformed."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def dump_payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# ── location ─────────────────────────────────────────────────────────────────

def _coord(value, low, high, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PayloadError(f"{label} must be a number")
    if number != number or not low <= number <= high:
        raise PayloadError(f"{label} must be between {low} and {high}")
    return number


def location_card(latitude, longitude, name=None, address=None) -> dict:
    """Validated display/storage shape of a location."""
    return {
        "latitude": _coord(latitude, -90, 90, "Latitude"),
        "longitude": _coord(longitude, -180, 180, "Longitude"),
        "name": str(name or "").strip()[:1000],
        "address": str(address or "").strip()[:1000],
    }


def location_meta(card) -> dict:
    """Meta's `location` object. name/address are optional — sent only when set."""
    out = {"latitude": card["latitude"], "longitude": card["longitude"]}
    if card.get("name"):
        out["name"] = card["name"]
    if card.get("address"):
        out["address"] = card["address"]
    return out


def location_from_meta(location) -> dict:
    """An inbound `location` object → the card shape (tolerant, never raises)."""
    location = location if isinstance(location, dict) else {}

    def num(key):
        try:
            return float(location.get(key))
        except (TypeError, ValueError):
            return None

    return {
        "latitude": num("latitude"),
        "longitude": num("longitude"),
        "name": str(location.get("name") or ""),
        "address": str(location.get("address") or ""),
    }


def location_text(card) -> str:
    """Readable fallback stored in `message` (preview, search, push)."""
    parts = ["\U0001F4CD Location"]
    for key in ("name", "address"):
        if card.get(key):
            parts.append(card[key])
    if card.get("latitude") is not None and card.get("longitude") is not None:
        parts.append(f"{card['latitude']},{card['longitude']}")
    return "\n".join(parts)


# ── contacts ─────────────────────────────────────────────────────────────────

def contact_card(name, phone) -> dict:
    """Validated card for one contact sent by an agent."""
    name = str(name or "").strip()
    if not name:
        raise PayloadError("Contact name is required")
    raw = str(phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 6:
        raise PayloadError("A valid contact phone number is required")
    return {"name": name[:200], "phones": ["+" + digits], "emails": [], "org": ""}


def contacts_meta(cards) -> list:
    """Meta's `contacts` array. Only `name.formatted_name` is required; the
    phone's `wa_id` (digits) makes WhatsApp show "Message" on the card."""
    out = []
    for card in cards:
        entry = {"name": {"formatted_name": card["name"], "first_name": card["name"]}}
        phones = []
        for phone in card.get("phones") or []:
            digits = re.sub(r"\D", "", str(phone))
            if digits:
                phones.append({"phone": "+" + digits, "type": "CELL", "wa_id": digits})
        if phones:
            entry["phones"] = phones
        emails = [{"email": e, "type": "WORK"} for e in card.get("emails") or [] if e]
        if emails:
            entry["emails"] = emails
        if card.get("org"):
            entry["org"] = {"company": card["org"]}
        out.append(entry)
    return out


def contacts_from_meta(contacts) -> list:
    """Inbound `contacts[]` → card shape, at most 10, never raises."""
    out = []
    for contact in (contacts if isinstance(contacts, list) else [])[:10]:
        if not isinstance(contact, dict):
            continue
        name = contact.get("name") if isinstance(contact.get("name"), dict) else {}
        org = contact.get("org") if isinstance(contact.get("org"), dict) else {}
        out.append(
            {
                "name": str(name.get("formatted_name") or name.get("first_name") or ""),
                "phones": [
                    str(p.get("phone") or p.get("wa_id") or "")
                    for p in contact.get("phones") or []
                    if isinstance(p, dict) and (p.get("phone") or p.get("wa_id"))
                ],
                "emails": [
                    str(e.get("email"))
                    for e in contact.get("emails") or []
                    if isinstance(e, dict) and e.get("email")
                ],
                "org": str(org.get("company") or ""),
            }
        )
    return out


def contacts_text(cards) -> str:
    lines = ["\U0001F464 Contact card"]
    for card in cards[:5]:
        line = " — ".join(p for p in (card.get("name"), ", ".join(card.get("phones") or [])) if p)
        if line:
            lines.append(line)
    return "\n".join(lines)


# ── interactive options ──────────────────────────────────────────────────────

def parse_options(raw) -> list:
    """The `options` argument (JSON list or list) → validated titles."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raise PayloadError("Options must be a JSON list of strings")
    if not isinstance(raw, (list, tuple)):
        raise PayloadError("Options must be a list of strings")
    options = [str(o if o is not None else "").strip() for o in raw]
    if any(not o for o in options):
        raise PayloadError("Options cannot be empty")
    if not 1 <= len(options) <= MAX_OPTIONS:
        raise PayloadError(f"Send between 1 and {MAX_OPTIONS} options")
    too_long = [o for o in options if len(o) > MAX_OPTION_CHARS]
    if too_long:
        raise PayloadError(
            f"Each option must be at most {MAX_OPTION_CHARS} characters: {too_long[0]}"
        )
    if len({o.lower() for o in options}) != len(options):
        raise PayloadError("Options must be unique")
    return options


def check_options_body(text, count):
    text = str(text or "").strip()
    if not text:
        raise PayloadError("Message text is required with options")
    limit = MAX_BUTTON_BODY if count <= MAX_BUTTONS else MAX_LIST_BODY
    if len(text) > limit:
        raise PayloadError(f"Message text must be at most {limit} characters")
    return text


def option_buttons(options) -> list:
    """The `buttons` JSON upstream's `interactive` branch reads: ≤3 become
    reply buttons, more a list message (both read `id` + `title`)."""
    return [{"id": f"opt_{i + 1}", "title": title} for i, title in enumerate(options)]


def option_titles(raw):
    """Titles from a stored `buttons` field, or None."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, list):
        return None
    titles = [str(b.get("title") or "") for b in raw if isinstance(b, dict) and b.get("title")]
    return titles or None


# ── outgoing Meta bodies ─────────────────────────────────────────────────────

def custom_kind(content_type, is_voice, payload) -> str:
    """Which round-3 send path a row takes, or "" for upstream's."""
    content_type = (content_type or "").lower()
    kind = payload.get("kind") if isinstance(payload, dict) else None
    if content_type == "location" and kind == "location":
        return "location"
    if content_type == "contact" and kind == "contact":
        return "contact"
    if content_type == "audio" and is_voice and kind == "voice":
        return "voice"
    return ""


def message_body(kind, to, payload, link=None, reply_to=None) -> dict:
    """The `/messages` body for a location / contacts / voice send. `to` is
    already formatted; upstream's `apply_recipient` runs on it afterwards."""
    data = {"messaging_product": "whatsapp", "to": to}
    if kind == "location":
        data["type"] = "location"
        data["location"] = location_meta(payload["location"])
    elif kind == "contact":
        data["type"] = "contacts"
        data["contacts"] = contacts_meta(payload["contacts"])
    elif kind == "voice":
        data["type"] = "audio"
        data["audio"] = {"link": link}
        if payload.get("voice"):
            # Voice-note rendering; Meta requires Ogg/Opus mono for it.
            data["audio"]["voice"] = True
    else:
        raise PayloadError(f"Unknown message kind {kind}")
    if reply_to:
        data["context"] = {"message_id": reply_to}
    return data


def typing_body(wamid) -> dict:
    """Typing indicator — Meta couples it with a read receipt for `wamid`."""
    return {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": wamid,
        "typing_indicator": {"type": "text"},
    }


def block_user_id(identifier) -> str:
    """Meta documents `user` as a phone number ("+" + digits); a hidden-number
    customer's BSUID is passed verbatim (undocumented for this API)."""
    value = str(identifier or "").strip()
    if re.match(r"^[A-Z]{2}\.", value):
        return value
    digits = re.sub(r"\D", "", value)
    return "+" + digits if digits else ""


def block_body(identifier) -> dict:
    """Same body for POST (block) and DELETE (unblock) /block_users."""
    return {"messaging_product": "whatsapp", "block_users": [{"user": block_user_id(identifier)}]}


# ── Meta errors ──────────────────────────────────────────────────────────────

def _describe(error):
    if not isinstance(error, dict):
        return ""
    data = error.get("error_data") if isinstance(error.get("error_data"), dict) else {}
    head = error.get("title") or error.get("message") or ""
    details = data.get("details") or ""
    text = head if not details or details == head else (f"{head} — {details}" if head else details)
    code = error.get("code")
    return f"({code}) {text}".strip() if code not in (None, "") else text


def error_message(payload) -> str:
    """Best human reason in a Graph API response (incl. block_users partial
    failures, whose per-user errors are more useful than the summary)."""
    if not isinstance(payload, dict):
        return ""
    block = payload.get("block_users")
    if isinstance(block, dict):
        for failed in block.get("failed_users") or []:
            for error in (failed or {}).get("errors") or []:
                if error.get("code") in (131047, "131047"):
                    return "WhatsApp only allows blocking a customer who messaged in the last 24 hours."
                text = _describe(error)
                if text:
                    return text
    return _describe(payload.get("error"))


def status_failure(payload, wamid) -> str:
    """Meta's reason for a failed status of `wamid` in a webhook payload."""
    entries = payload.get("entry") if isinstance(payload, dict) else None
    entries = [entries] if isinstance(entries, dict) else entries
    for entry in entries if isinstance(entries, list) else []:
        for change in (entry or {}).get("changes") or [] if isinstance(entry, dict) else []:
            value = change.get("value") if isinstance(change, dict) else None
            for status in (value or {}).get("statuses") or [] if isinstance(value, dict) else []:
                if not isinstance(status, dict) or status.get("id") != wamid:
                    continue
                reasons = [_describe(e) for e in status.get("errors") or []]
                return "; ".join(r for r in reasons if r)[:1000]
    return ""


def status_field(status) -> str:
    return STATUS_FIELDS.get(str(status or "").strip().lower(), "")


# ── thread paging ────────────────────────────────────────────────────────────

def around_split(limit):
    """(older, newer) counts for a page centred on a timestamp — the anchor
    itself counts as older (`creation <= around`)."""
    limit = max(int(limit or 0), 2)
    newer = limit // 2
    return limit - newer, newer


# ── serializer decoration ────────────────────────────────────────────────────

def decorate_item(item, row_get):
    """Add the round-3 ThreadItem keys. `row_get(field)` reads the row."""
    payload = load_payload(row_get("custom_payload"))
    kind = payload.get("kind")
    item["location"] = None
    item["contacts"] = None
    if kind == "location" and isinstance(payload.get("location"), dict):
        item["content_type"] = "location"
        item["location"] = payload["location"]
    elif kind == "contact" and isinstance(payload.get("contacts"), list):
        item["content_type"] = "contact"
        item["contacts"] = payload["contacts"]
    item["is_voice"] = bool(row_get("custom_is_voice")) or kind == "voice"
    item["options"] = option_titles(row_get("buttons")) if item.get("content_type") == "interactive" else None
    for key in ("sent_at", "delivered_at", "read_at"):
        value = row_get("custom_" + key)
        item[key] = str(value)[:19] if value else None
    item["error"] = row_get("custom_error") or None
    # Sent from another app on the number (external_replies): a text-less
    # placeholder, or an echo with its text. Not a Messenger Suite echo.
    item["external"] = kind == "external" or (kind == "echo" and bool(payload.get("external")))
    item["external_category"] = str(payload.get("category") or "") if item["external"] else ""
    return item

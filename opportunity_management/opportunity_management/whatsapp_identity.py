"""
Customer identity for the WhatsApp team inbox: phone numbers vs. Meta's
business-scoped user IDs (BSUIDs) and WhatsApp usernames.

A customer who sets a WhatsApp **username** can hide their phone number. The
webhook then carries no `from` / `contacts[].wa_id`, only a BSUID such as
`IQ.1858675848823706` (two-letter country, a period, an id; parent ids look
like `US.ENT.123`). frappe_whatsapp stores that BSUID verbatim in
`WhatsApp Message.from` and, on send, moves a BSUID `to` into Meta's
`recipient` parameter. So the one thing this app must do is **not mangle
it**: `normalize_phone()` strips every non-digit, which turned the BSUID into
a 16-digit "number" Meta rejects with 131026.

Pure and import-cheap like `whatsapp_utils` — the bench-free unit tests load
it with a stubbed `frappe`. Only `contacts_by_sender` / `lookup_sender` deal
with payloads, and they never raise.
"""

import re

from opportunity_management.opportunity_management.whatsapp_utils import normalize_phone

# Same pattern frappe_whatsapp's `apply_recipient` uses to route a send.
BSUID_RE = re.compile(r"^[A-Z]{2}\.[A-Za-z0-9.]+$")

# Shown when a hidden-number customer has neither a profile name nor a
# username. Wrapped in `_()` by the caller (the serializer) for translation.
UNKNOWN_CUSTOMER_LABEL = "WhatsApp user"

# `frappe.flags` key the webhook wrapper stashes `contacts_by_sender()` under
# for `whatsapp_hooks.on_message_after_insert` (frappe_whatsapp itself does
# not persist `profile.username` / `user_id` anywhere).
SENDER_CONTACTS_FLAG = "whatsapp_sender_contacts"

# `frappe.flags` key for the wamids the webhook wrapper rewrote from
# `sticker` to `image` (a set), so the hook can flag `custom_is_sticker`.
STICKER_IDS_FLAG = "whatsapp_sticker_ids"


def is_bsuid(value) -> bool:
    """True for a business-scoped user ID (`IQ.1858675848823706`, `US.ENT.123`)."""
    if not isinstance(value, str):
        return False
    return bool(BSUID_RE.match(value.strip()))


def normalize_wa_identifier(raw, default_cc=None) -> str:
    """The thread identity for a customer address.

    A BSUID comes back unchanged (trimmed, original case) — it is what must be
    sent in `to`. Anything else is a phone and goes through `normalize_phone`
    exactly as before.
    """
    if isinstance(raw, str) and is_bsuid(raw):
        return raw.strip()
    return normalize_phone(raw, default_cc=default_cc)


def has_phone(identifier) -> bool:
    """False when the conversation's identifier is a BSUID (number hidden)."""
    return bool(identifier) and not is_bsuid(identifier)


def clean_username(value) -> str:
    """`@20_plo` / ` 20_plo ` → `20_plo`; "" for nothing."""
    return str(value or "").strip().lstrip("@").strip()


def render_handle(identifier, username=None) -> str:
    """The secondary display line under a conversation's name.

        phone + username → "+9647738524563 · @20_plo"
        phone only       → "+9647738524563"
        BSUID + username → "@20_plo"
        BSUID only       → ""        (never the raw BSUID)
    """
    user = clean_username(username)
    parts = []
    if has_phone(identifier):
        parts.append("+" + str(identifier).strip().lstrip("+"))
    if user:
        parts.append("@" + user)
    return " · ".join(parts)


def display_label(display_name, identifier, username=None, fallback=UNKNOWN_CUSTOMER_LABEL) -> str:
    """CRM / profile name → @username → the phone → `fallback`.

    A stored name that is just the identifier (or a BSUID, or the digits-only
    mangling of one) is no name at all, so it falls through.
    """
    name = str(display_name or "").strip()
    ident = str(identifier or "").strip()
    digits = re.sub(r"\D", "", ident) if is_bsuid(ident) else None
    if name and name != ident and not is_bsuid(name) and name != digits:
        return name
    user = clean_username(username)
    if user:
        return "@" + user
    if has_phone(ident):
        return ident
    return fallback


# ── webhook payload → sender details ─────────────────────────────────────────

def _iter_values(data):
    entry = data.get("entry") if isinstance(data, dict) else None
    if isinstance(entry, dict):
        entry = [entry]
    for item in entry if isinstance(entry, list) else []:
        changes = item.get("changes") if isinstance(item, dict) else None
        for change in changes if isinstance(changes, list) else []:
            if isinstance(change, dict) and isinstance(change.get("value"), dict):
                yield change["value"]


def contacts_by_sender(data) -> dict:
    """`{wa_id or user_id: {username, user_id, wa_id, name}}` from a Meta payload.

    Keyed by BOTH addresses so the lookup works whether frappe_whatsapp stored
    the phone (`from`) or the BSUID (`from_user_id`) on the message. Never
    raises — a malformed payload yields `{}`.
    """
    out = {}
    try:
        for value in _iter_values(data):
            contacts = value.get("contacts")
            for contact in contacts if isinstance(contacts, list) else []:
                if not isinstance(contact, dict):
                    continue
                profile = contact.get("profile") if isinstance(contact.get("profile"), dict) else {}
                info = {
                    "username": clean_username(profile.get("username")) or None,
                    "user_id": str(contact.get("user_id") or "").strip() or None,
                    "wa_id": str(contact.get("wa_id") or "").strip() or None,
                    "name": str(profile.get("name") or "").strip() or None,
                }
                for key in (info["wa_id"], info["user_id"]):
                    if key:
                        out[key] = info
    except Exception:
        return out
    return out


def lookup_sender(contacts, raw_from) -> dict:
    """The `contacts_by_sender` entry for a message's stored `from`, or {}."""
    if not isinstance(contacts, dict) or not contacts or not raw_from:
        return {}
    key = str(raw_from).strip()
    hit = contacts.get(key) or contacts.get(key.lstrip("+"))
    if hit:
        return hit
    if is_bsuid(key):
        return {}
    digits = re.sub(r"\D", "", key)
    for wa_id, info in contacts.items():
        if wa_id and not is_bsuid(wa_id) and re.sub(r"\D", "", wa_id) == digits:
            return info
    return {}

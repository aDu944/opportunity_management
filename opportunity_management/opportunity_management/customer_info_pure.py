"""
Pure helpers behind `whatsapp_api_customer.get_customer_info` (the thread's
"customer info" screen).

No `frappe` import: the bench-free tests (`tests/test_customer_info_pure.py`)
load this file straight off disk. The endpoint does the querying and calls in
here for the identity matching ("other conversations of this customer"), the
message-count roll-up and the identity block.
"""

import re

# Same shape `whatsapp_identity.BSUID_RE` matches (kept local so this module
# stays import-free). A Messenger identifier `FB.<psid>` matches it too, which
# is what we want: neither is a phone number.
_BSUID_RE = re.compile(r"^[A-Z]{2}\.[A-Za-z0-9.]+$")
PSID_PREFIX = "FB."
MESSENGER = "Messenger"

# `get_conversation_media` kinds, flattened: what counts towards media_count.
MEDIA_TYPES = ("image", "video", "document", "audio")
# Rows that are not messages a person would count.
NOT_A_MESSAGE = ("reaction",)
# Opportunity statuses that are finished.
CLOSED_OPPORTUNITY = ("Lost", "Closed", "Converted")

OTHER_LIMIT = 10
LINK_FIELDS = ("contact", "lead", "customer")


def _s(value) -> str:
    return str(value or "").strip()


def is_hidden_identifier(value) -> bool:
    """BSUID or Messenger PSID — an address, never a phone number."""
    return bool(_BSUID_RE.match(_s(value)))


def phone_digits(value):
    """The digits of a real phone identifier, or None."""
    value = _s(value)
    if not value or is_hidden_identifier(value):
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def psid_of(row):
    if _s(row.get("channel")) != MESSENGER:
        return None
    value = _s(row.get("phone"))
    if not value:
        return None
    return value[len(PSID_PREFIX):] if value.startswith(PSID_PREFIX) else value


def identity_keys(row) -> set:
    """Everything that identifies the customer behind a conversation row.

    Two conversations are the same customer when they share any key: the
    phone (digits), the WhatsApp BSUID, the @username (case-insensitive), the
    Messenger PSID, or a linked Contact / Lead / Customer — the CRM link is
    the only thing that can join a Messenger thread to a WhatsApp one.
    """
    keys = set()
    digits = phone_digits(row.get("phone"))
    if digits:
        keys.add(("phone", digits))
    psid = psid_of(row)
    if psid:
        keys.add(("psid", psid))
    else:
        uid = _s(row.get("wa_user_id")) or (
            _s(row.get("phone")) if is_hidden_identifier(row.get("phone")) else ""
        )
        if uid:
            keys.add(("uid", uid))
    username = _s(row.get("wa_username")).lstrip("@").strip().lower()
    if username:
        keys.add(("username", username))
    for field in LINK_FIELDS:
        value = _s(row.get(field))
        if value:
            keys.add((field, value))
    return keys


def candidate_filters(row) -> list:
    """`[(column, value)]` to OR together in the candidate query — a superset
    of what `related_conversations` keeps (phone formats are re-checked in
    Python)."""
    out = []
    phone = _s(row.get("phone"))
    if phone:
        out.append(("phone", phone))
        digits = phone_digits(phone)
        if digits and digits != phone:
            out.append(("phone", digits))
    uid = _s(row.get("wa_user_id"))
    if uid:
        out.append(("wa_user_id", uid))
        out.append(("phone", uid))
    username = _s(row.get("wa_username")).lstrip("@").strip()
    if username:
        out.append(("wa_username", username))
    for field in LINK_FIELDS:
        value = _s(row.get(field))
        if value:
            out.append((field, value))
    seen, unique = set(), []
    for pair in out:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


def related_conversations(current, candidates, limit=OTHER_LIMIT) -> list:
    """Candidates (excluding `current`) that share an identity key with it,
    newest activity first, at most `limit`."""
    mine = identity_keys(current)
    if not mine:
        return []
    me = _s(current.get("name"))
    hits = []
    for row in candidates or []:
        if _s(row.get("name")) == me:
            continue
        if identity_keys(row) & mine:
            hits.append(row)
    hits.sort(key=lambda r: _s(r.get("last_message_at")), reverse=True)
    return hits[: max(0, int(limit))]


def roll_up_messages(rows) -> dict:
    """Grouped counts `[{type, content_type, has_attach, n}]` →
    `{messages_in, messages_out, media_count}`. Reactions are not messages."""
    out = {"messages_in": 0, "messages_out": 0, "media_count": 0}
    for row in rows or []:
        try:
            n = int(row.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            continue
        content_type = _s(row.get("content_type")).lower()
        if content_type in NOT_A_MESSAGE:
            continue
        if _s(row.get("type")) == "Incoming":
            out["messages_in"] += n
        else:
            out["messages_out"] += n
        if content_type in MEDIA_TYPES and _truthy(row.get("has_attach")):
            out["media_count"] += n
    return out


def _truthy(value) -> bool:
    try:
        return bool(int(value or 0))
    except (TypeError, ValueError):
        return bool(value)


def identity_block(row) -> dict:
    """The `identity` part of the payload from a ConvRow (+ raw fields)."""
    messenger = _s(row.get("channel")) == MESSENGER
    phone = None if messenger else phone_digits(row.get("phone"))
    return {
        "channel": MESSENGER if messenger else "WhatsApp",
        "display_name": _s(row.get("display_name")),
        "phone": phone,
        "username": None if messenger else (_s(row.get("username")).lstrip("@") or None),
        "psid": psid_of(row) if messenger else None,
        "avatar_url": row.get("avatar_url") or None,
        "customer_language": _s(row.get("customer_language")),
    }


def is_open_opportunity(status) -> bool:
    return _s(status) not in CLOSED_OPPORTUNITY

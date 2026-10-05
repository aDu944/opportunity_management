"""
Replies staff send from ANOTHER Meta app on the same WhatsApp number (the
Yeastar PBX client, Linkus) — shown in the team inbox as "Replied from
another app".

Meta delivers every inbound customer message to every app subscribed to the
number, but an app's outbound message CONTENT goes to that app only. What
does reach us for such a reply is its delivery reports: `statuses[]` for a
wamid we never stored. `whatsapp_webhook._drop_foreign_statuses` used to
drop them all; it now hands the still-unknown ones (after its commit-race
wait) to `record_unknown_statuses`, which stores a text-less placeholder:

    Outgoing `WhatsApp Message`, message_id = the wamid, empty `message`,
    custom_payload {"kind": "external", "category": <pricing category>}

only when ALL of these hold (`is_staff_reply_status` + a conversation):

* the status is `sent` / `delivered` / `read` (a `failed` first status
  delivered nothing — no placeholder);
* the category (`pricing.category`, else the older
  `conversation.origin.type`) is not `authentication` — the web shop's OTP
  codes. A status with neither is treated as a staff reply: the recipient
  must also already have a conversation (a customer who wrote to us), which
  OTP-only numbers do not;
* `recipient_id` / `recipient_user_id` match an EXISTING WhatsApp
  conversation of the account (never created here);
* the wamid is not one of OUR sends whose row has not committed yet
  (`mark_own`, set by the override right after Meta accepted the send).

Later statuses for that wamid find the row and flow through upstream.

**Never sent to Meta — two independent guards.** (1) The row is written with
`db_insert()`: no controller method, no `before_insert`, no doc_events run at
all; the inbox bookkeeping is applied here by hand (`_after_insert`). (2) The
`WhatsApp Message` override short-circuits `before_insert` / `send_outgoing`
for any row whose `custom_payload` kind is `external` or `echo`
(`is_store_only`), so even a path that called `insert()` could not send.

`message_echoes` / `smb_message_echoes` webhooks (none has ever arrived —
speculative): `ingest_echoes` stores them with their text as kind `echo`
(`external: true`), or upgrades an existing placeholder of that wamid.
"""

import time
from datetime import timedelta

import frappe

MSG = "WhatsApp Message"
CONV = "WhatsApp Conversation"
EXTERNAL = "external"
ECHO = "echo"
STORE_ONLY_KINDS = (EXTERNAL, ECHO)  # whatsapp_message_override._is_store_only
# Stored in English; clients localise it (it is also the conversation preview).
PREVIEW = "Replied from another app"
AUTHENTICATION = "authentication"
REPLY_STATUSES = ("sent", "delivered", "read")
ECHO_FIELDS = ("message_echoes", "smb_message_echoes")
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
STATUS_FIELDS = {"sent": "custom_sent_at", "delivered": "custom_delivered_at", "read": "custom_read_at"}
ECHO_LABELS = {
    "image": "\U0001F4F7 Photo", "video": "\U0001F3AC Video", "audio": "\U0001F3A4 Audio",
    "document": "\U0001F4C4 Document", "sticker": "\U0001F9E9 Sticker",
    "location": "\U0001F4CD Location", "contacts": "\U0001F464 Contact card",
    "template": "Template", "interactive": "Interactive message",
}

_LOCK_TTL = 30
_LOCK_WAITS = (0.25, 0.5, 1.0)
_OWN_TTL = 600
_OWN_PREFIX = "wa_own_wamid:"
_LOCK_PREFIX = "wa_external_lock:"


# ── pure ─────────────────────────────────────────────────────────────────────

def load_payload(raw):
    from opportunity_management.opportunity_management.whatsapp_payloads import load_payload as load

    return load(raw)


def status_category(status) -> str:
    """`pricing.category`, else the older `conversation.origin.type`, else ""."""
    if not isinstance(status, dict):
        return ""
    pricing = status.get("pricing") if isinstance(status.get("pricing"), dict) else {}
    category = pricing.get("category")
    if not category:
        conversation = status.get("conversation") if isinstance(status.get("conversation"), dict) else {}
        origin = conversation.get("origin") if isinstance(conversation.get("origin"), dict) else {}
        category = origin.get("type")
    return str(category or "").strip().lower()


def is_staff_reply_status(status) -> bool:
    """A status that could stand for a staff reply sent from another app."""
    if not isinstance(status, dict) or not status.get("id"):
        return False
    if str(status.get("status") or "").strip().lower() not in REPLY_STATUSES:
        return False
    return status_category(status) != AUTHENTICATION


def should_record(status, known, conversation, own=False) -> bool:
    """The whole placeholder rule (see the module docstring)."""
    return bool(not known and not own and conversation and is_staff_reply_status(status))


def reply_time(timestamp, now_epoch, now_dt):
    """The status `timestamp` as a local datetime when sane (not in the
    future, at most 7 days old), else `now_dt`."""
    try:
        ts = int(float(timestamp))
    except (TypeError, ValueError):
        return now_dt
    age = now_epoch - ts
    if age < 0 or age > MAX_AGE_SECONDS:
        return now_dt
    return now_dt - timedelta(seconds=age)


def conversation_lookups(recipient_id, user_id, normalize) -> list:
    """Ordered `WhatsApp Conversation` filters for a status's recipient."""
    out = []
    ident = normalize(recipient_id) if recipient_id else ""
    if ident:
        out.append({"phone": ident})
    user_id = str(user_id or "").strip()
    if user_id:
        out.append({"wa_user_id": user_id})
        if user_id != ident:
            out.append({"phone": user_id})
    return out


def placeholder_fields(status, conv, created) -> dict:
    """The `WhatsApp Message` row for an external reply."""
    from opportunity_management.opportunity_management.whatsapp_payloads import dump_payload

    state = str(status.get("status") or "").strip().lower()
    fields = {
        "doctype": MSG, "type": "Outgoing", "message_id": status["id"],
        "to": conv.get("phone"), "whatsapp_account": conv.get("whatsapp_account"),
        "content_type": "text", "message_type": "Manual", "message": "",
        "custom_body_text": "", "custom_conversation": conv.get("name"), "custom_read": 1,
        "custom_payload": dump_payload({"kind": EXTERNAL, "category": status_category(status)}),
        "status": state, "creation": created, "modified": created,
    }
    if STATUS_FIELDS.get(state):
        fields[STATUS_FIELDS[state]] = created
    return fields


def conversation_values(conv, when, preview=PREVIEW) -> dict:
    """What an external reply at `when` changes on its conversation: as an
    agent reply does, minus the claim — and only if it is not older than
    what it would overwrite. `assigned_to` and Resolved are never touched."""
    from frappe.utils import cint, get_datetime

    values = {}
    last = conv.get("last_message_at")
    if not last or when >= get_datetime(last):
        values.update(last_message_at=when, last_message_preview=preview, last_message_direction="Out")
    last_out = conv.get("last_outbound_at")
    if not last_out or when > get_datetime(last_out):
        values["last_outbound_at"] = when
    awaiting = conv.get("awaiting_reply_since")
    if awaiting and when < get_datetime(awaiting):
        return values  # sent before the customer's latest unanswered message
    if awaiting:
        if not cint(conv.get("first_response_seconds")):
            values["first_response_seconds"] = int(max((when - get_datetime(awaiting)).total_seconds(), 0))
        values["awaiting_reply_since"] = None
    if conv.get("status") == "Open":
        values["status"] = "Pending"
    return values


def parse_echoes(data) -> list:
    """`{id, to, timestamp, type, text, phone_number_id}` per echo in a
    `message_echoes` / `smb_message_echoes` change. Never raises."""
    out = []
    try:
        for value, field, phone_id in _changes(data):
            if field not in ECHO_FIELDS and not isinstance(value.get("message_echoes"), list):
                continue
            for item in value.get("message_echoes") or []:
                if not isinstance(item, dict) or not item.get("id") or not item.get("to"):
                    continue
                mtype = str(item.get("type") or "text")
                out.append({"id": item["id"], "to": str(item["to"]), "timestamp": item.get("timestamp"),
                            "type": mtype, "text": echo_text(item), "phone_number_id": phone_id})
    except Exception:
        return out
    return out


def echo_text(item) -> str:
    """Text body; for media the type label + caption (no media is fetched —
    the id belongs to another app)."""
    mtype = str(item.get("type") or "text")
    block = item.get(mtype) if isinstance(item.get(mtype), dict) else {}
    if mtype == "text":
        return str(block.get("body") or "")
    caption = str(block.get("caption") or "").strip()
    label = ECHO_LABELS.get(mtype, "[{0}]".format(mtype))
    return "{0} — {1}".format(label, caption) if caption else label


def upgrade_values(existing_payload, echo):
    """Fields that turn a placeholder into an echo, or None (already an echo,
    or one of OUR rows — never touched)."""
    from opportunity_management.opportunity_management.whatsapp_payloads import dump_payload

    payload = existing_payload if isinstance(existing_payload, dict) else load_payload(existing_payload)
    if payload.get("kind") != EXTERNAL:
        return None
    marker = {"kind": ECHO, "external": True, "category": payload.get("category") or "",
              "echo_type": echo.get("type") or "text"}
    text = echo.get("text") or ""
    return {"custom_payload": dump_payload(marker), "message": text, "custom_body_text": text}


def _changes(data):
    entry = data.get("entry") if isinstance(data, dict) else None
    entry = [entry] if isinstance(entry, dict) else entry
    for item in entry if isinstance(entry, list) else []:
        changes = item.get("changes") if isinstance(item, dict) else None
        for change in changes if isinstance(changes, list) else []:
            if isinstance(change, dict) and isinstance(change.get("value"), dict):
                value = change["value"]
                meta = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
                yield value, change.get("field") or "", meta.get("phone_number_id")


# ── own sends (set by the override once Meta accepted a send) ────────────────

def mark_own(wamid):
    if wamid:
        frappe.cache().set_value(_OWN_PREFIX + str(wamid), 1, expires_in_sec=_OWN_TTL)


def _is_own(wamid) -> bool:
    try:
        return bool(frappe.cache().get_value(_OWN_PREFIX + str(wamid)))
    except Exception:
        return False


# ── statuses ─────────────────────────────────────────────────────────────────

def record_unknown_statuses(data, unknown) -> set:
    """Store placeholders for the still-unknown status ids. Returns the ids
    whose statuses should be KEPT for upstream (their row exists by now)."""
    keep = set()
    for wamid, (status, phone_id) in latest_statuses(data, unknown).items():
        try:
            if _record_status(status, phone_id):
                keep.add(wamid)
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), "WhatsApp external reply: record failed")
    return keep


def latest_statuses(data, ids) -> dict:
    """{wamid: (status, phone_number_id)} for `ids`, the furthest-along status
    (sent < delivered < read; anything else last) when a payload holds several."""
    rank = {s: i for i, s in enumerate(REPLY_STATUSES)}
    out = {}
    for value, _field, phone_id in _changes(data):
        for status in value.get("statuses") or []:
            wamid = status.get("id") if isinstance(status, dict) else None
            if not wamid or wamid not in ids:
                continue
            new = rank.get(str(status.get("status") or "").lower(), -1)
            old = out.get(wamid)
            if old is None or new > rank.get(str(old[0].get("status") or "").lower(), -1):
                out[wamid] = (status, phone_id)
    return out


def _record_status(status, phone_id) -> bool:
    if not is_staff_reply_status(status):
        return False
    wamid = status["id"]
    conv = find_conversation(status.get("recipient_id"), status.get("recipient_user_id"), phone_id)
    if not conv:
        return False

    def build(created):
        return placeholder_fields(status, conv, created)

    return _store_once(wamid, conv, status.get("timestamp"), build)


def _store_once(wamid, conv, timestamp, build) -> bool:
    """Insert under a per-wamid cache lock. True = the row now exists from
    someone else (keep the status for upstream); False = handled here."""
    if not _acquire(wamid):
        return _wait_for(wamid)  # a parallel worker is inserting it
    try:
        time.sleep(_LOCK_WAITS[0])  # last chance for our own send's commit / mark
        frappe.db.commit()
        if _exists(wamid):
            return True
        if _is_own(wamid):
            return _wait_for(wamid)  # ours, still committing: never a placeholder
        doc = _db_insert(build(_reply_time(timestamp)))
        frappe.db.commit()
    finally:
        _release(wamid)
    _after_insert(doc, conv)
    frappe.db.commit()
    return False


def _wait_for(wamid) -> bool:
    for wait in _LOCK_WAITS:
        time.sleep(wait)
        frappe.db.commit()
        if _exists(wamid):
            return True
    return False


def find_conversation(recipient_id, user_id, phone_id=None):
    """An EXISTING WhatsApp conversation for the recipient, or None."""
    from opportunity_management.opportunity_management import inbox_channels as IC
    from opportunity_management.opportunity_management.whatsapp_identity import normalize_wa_identifier

    account = frappe.db.get_value("WhatsApp Account", {"phone_id": phone_id}, "name") if phone_id else None
    for filters in conversation_lookups(recipient_id, user_id, normalize_wa_identifier):
        if account:
            filters["whatsapp_account"] = account
        for name in frappe.get_all(CONV, filters=filters, pluck="name",
                                  order_by="modified desc", limit_page_length=3):
            conv = frappe.get_doc(CONV, name)
            if IC.conv_channel(conv) == IC.WHATSAPP:
                return conv
    return None


def _reply_time(timestamp):
    from frappe.utils import now_datetime

    return reply_time(timestamp, time.time(), now_datetime())


def _exists(wamid) -> bool:
    return bool(frappe.db.exists(MSG, {"message_id": wamid}))


def _acquire(wamid) -> bool:
    """Redis SET NX. Fails closed: losing a placeholder beats a duplicate."""
    try:
        cache = frappe.cache()
        return bool(cache.set(cache.make_key(_LOCK_PREFIX + wamid), 1, nx=True, ex=_LOCK_TTL))
    except Exception:
        return False


def _release(wamid):
    try:
        cache = frappe.cache()
        cache.delete(cache.make_key(_LOCK_PREFIX + wamid))
    except Exception:
        pass


def _db_insert(fields):
    """Guard 2: `db_insert()` runs no controller method — nothing can send."""
    doc = frappe.get_doc(dict(fields))
    set_defaults = getattr(doc, "_set_defaults", None)
    if callable(set_defaults):
        set_defaults()
    doc.owner = doc.modified_by = "Administrator"
    doc.db_insert()
    return doc


def _after_insert(doc, conv):
    """The inbox bookkeeping `whatsapp_hooks.on_message_after_insert` would do
    for an agent reply, minus claim / push / auto-reply."""
    from opportunity_management.opportunity_management import whatsapp_hooks as H
    from opportunity_management.opportunity_management import whatsapp_serializers as S

    try:
        preview = (doc.get("custom_body_text") or PREVIEW)[:120]
        values = conversation_values(conv, doc.creation, preview)
        if values:
            for field, value in values.items():
                conv.set(field, value)
            frappe.db.set_value(CONV, conv.name, values, update_modified=False)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp external reply: conversation update failed")
    try:
        H.publish_inbox_event("message", conv, item=S.message_item(doc))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp external reply: realtime publish failed")


# ── echoes (speculative: Meta has never sent one for this number) ────────────

def ingest_echoes(data) -> int:
    """Store / upgrade every echo in the payload; how many were handled."""
    done = 0
    for echo in parse_echoes(data):
        try:
            done += 1 if _store_echo(echo) else 0
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), "WhatsApp external reply: echo failed")
    return done


def _store_echo(echo) -> bool:
    from opportunity_management.opportunity_management import whatsapp_hooks as H
    from opportunity_management.opportunity_management import whatsapp_serializers as S
    from opportunity_management.opportunity_management.whatsapp_payloads import dump_payload

    wamid = echo["id"]
    row = frappe.db.get_value(MSG, {"message_id": wamid}, ["name", "custom_payload"], as_dict=True)
    if row:
        values = upgrade_values(row.get("custom_payload"), echo)
        if not values:
            return False
        frappe.db.set_value(MSG, row["name"], values, update_modified=False)
        doc = frappe.get_doc(MSG, row["name"])
        conv = frappe.get_doc(CONV, doc.custom_conversation) if doc.get("custom_conversation") else None
        if conv and conv.get("last_message_preview") == PREVIEW and values["custom_body_text"]:
            # Still the latest message: show its real text in the list too.
            preview = values["custom_body_text"][:120]
            frappe.db.set_value(CONV, conv.name, "last_message_preview", preview, update_modified=False)
            conv.last_message_preview = preview
        frappe.db.commit()
        if conv:
            H.publish_inbox_event("message", conv, item=S.message_item(doc))
        return True
    conv = find_conversation(echo["to"], echo["to"], echo.get("phone_number_id"))
    if not conv:
        return False

    def build(created):
        fields = placeholder_fields({"id": wamid, "status": "sent"}, conv, created)
        fields.update(message=echo["text"], custom_body_text=echo["text"], custom_payload=dump_payload(
            {"kind": ECHO, "external": True, "category": "", "echo_type": echo["type"]}))
        return fields

    _store_once(wamid, conv, echo.get("timestamp"), build)
    return True

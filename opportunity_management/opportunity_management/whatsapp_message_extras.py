"""
Round-3 bookkeeping on `WhatsApp Message` rows, called from `whatsapp_hooks`
(kept out of it so that module stays under the size limit):

* `remember_card` / `stamp_inbound_card` — an inbound location / contacts
  message reaches upstream coerced to `text` (whatsapp_webhook). The wrapper
  stashes the structured data per wamid in `frappe.flags`; after_insert
  writes it to `custom_payload` so the serializer shows a card again.
* `record_status` — on a Meta status tick, stamp `custom_sent_at` /
  `custom_delivered_at` / `custom_read_at` (first time only) and keep Meta's
  failure reason in `custom_error`. Upstream stores no error at all; the
  reason is read from the webhook payload still on `frappe.local.form_dict`.
* `add_reply_action` — the push data for an inbound message when
  `enable_notification_reply` is on.

All writes are `frappe.db.set_value`, never `save()`, so nothing re-enters
`on_update`. Callers wrap every call in try/except.
"""

import frappe
from frappe.utils import cint, now_datetime

from opportunity_management.opportunity_management import whatsapp_payloads as P

MSG = "WhatsApp Message"
CARDS_FLAG = "whatsapp_inbound_cards"


def _has(field) -> bool:
    try:
        return bool(frappe.db.has_column(MSG, field))
    except Exception:
        return False


# ── inbound cards ────────────────────────────────────────────────────────────

def remember_card(message):
    """Webhook side: keep the structured location / contacts of one inbound
    message (before it is coerced to text). Best-effort."""
    try:
        mid = message.get("id")
        mtype = message.get("type")
        if not mid:
            return
        if mtype == "location":
            card = {"kind": "location", "location": P.location_from_meta(message.get("location"))}
        elif mtype == "contacts":
            card = {"kind": "contact", "contacts": P.contacts_from_meta(message.get("contacts"))}
        else:
            return
        cards = frappe.flags.get(CARDS_FLAG)
        if not isinstance(cards, dict):
            cards = frappe.flags[CARDS_FLAG] = {}
        cards[mid] = card
    except Exception:
        pass


def stamp_inbound_card(doc):
    """after_insert side: persist the stashed card on the new row."""
    cards = frappe.flags.get(CARDS_FLAG) or {}
    card = cards.get(doc.get("message_id")) if isinstance(cards, dict) else None
    if not card or not _has("custom_payload"):
        return
    raw = P.dump_payload(card)
    frappe.db.set_value(MSG, doc.name, "custom_payload", raw, update_modified=False)
    doc.custom_payload = raw


# ── status ticks ─────────────────────────────────────────────────────────────

def record_status(doc) -> dict:
    """Stamp the time of a new status; returns the ThreadItem keys that
    changed (merged into the realtime `status` event)."""
    status = str(doc.get("status") or "").strip().lower()
    values = {}
    field = P.status_field(status)
    if field and not doc.get(field) and _has(field):
        values[field] = now_datetime()
    if status == "failed" and _has("custom_error"):
        reason = ""
        try:
            reason = P.status_failure(frappe.local.form_dict or {}, doc.get("message_id"))
        except Exception:
            reason = ""
        values["custom_error"] = reason or "Failed"
    if not values:
        return {}
    frappe.db.set_value(MSG, doc.name, values, update_modified=False)
    out = {}
    for key, value in values.items():
        doc.set(key, value)
        out[key.replace("custom_", "", 1)] = str(value)[:19] if key != "custom_error" else value
    return out


# ── push ─────────────────────────────────────────────────────────────────────

def add_reply_action(data):
    """`data.reply = "1"` + the iOS `WA_REPLY` category when the setting is
    on. `_apns_category` is lifted into `aps.category` by `fcm_utils`."""
    try:
        from opportunity_management.opportunity_management.whatsapp_utils import setting

        if cint(setting("enable_notification_reply", 0)):
            data["reply"] = "1"
            data["_apns_category"] = "WA_REPLY"
    except Exception:
        pass
    return data

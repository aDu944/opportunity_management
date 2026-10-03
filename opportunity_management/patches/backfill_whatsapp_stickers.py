"""
Add the new `WhatsApp Message` custom fields (`custom_is_sticker`,
`custom_audio_url`, `custom_audio_duration`) and flag the stickers customers
already sent.

The fields come from `whatsapp_setup.create_whatsapp_message_custom_fields`
— fixtures sync only after post_model_sync patches, and this patch needs the
column. Until now an inbound sticker was stored as a plain image (the webhook
wrapper coerces `sticker` → `image` for upstream), so it can only be
recognised from the raw payload in `WhatsApp Notification Log.meta_data`.
That payload is logged AFTER our coercion, so a sticker shows up there as
`"type": "image"` with the original `"sticker"` object still on the message
(the wrapper copies it, it does not move it); payloads from before the
wrapper still say `"type": "sticker"`. Either marks it.

Idempotent (only rows still at 0 are touched), tolerant of malformed JSON,
one summary line.
"""

import json

import frappe

LOG = "WhatsApp Notification Log"
MSG = "WhatsApp Message"
PAGE = 500


def execute():
    if not frappe.db.table_exists(MSG):
        return
    from opportunity_management.opportunity_management.whatsapp_setup import (
        create_whatsapp_message_custom_fields,
    )

    create_whatsapp_message_custom_fields()
    if not frappe.db.table_exists(LOG) or not frappe.db.has_column(MSG, "custom_is_sticker"):
        print("WhatsApp stickers: nothing to backfill")
        return

    ids = _sticker_ids()
    flagged = _flag(ids)
    frappe.db.commit()
    print(f"WhatsApp stickers: {len(ids)} sticker id(s) in the webhook log, {flagged} message(s) flagged")


def sticker_ids_in(payload):
    """Wamids of the sticker messages in one webhook payload."""
    out = set()
    entries = payload.get("entry") if isinstance(payload, dict) else None
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries if isinstance(entries, list) else []:
        changes = entry.get("changes") if isinstance(entry, dict) else None
        for change in changes if isinstance(changes, list) else []:
            value = change.get("value") if isinstance(change, dict) else None
            messages = value.get("messages") if isinstance(value, dict) else None
            for message in messages if isinstance(messages, list) else []:
                if not isinstance(message, dict) or not message.get("id"):
                    continue
                if message.get("type") == "sticker" or isinstance(message.get("sticker"), dict):
                    out.add(message["id"])
    return out


def _sticker_ids():
    ids = set()
    start = 0
    while True:
        logs = frappe.get_all(
            LOG,
            filters={"meta_data": ["like", "%sticker%"]},
            fields=["name", "meta_data"],
            order_by="creation asc",
            limit_start=start,
            limit_page_length=PAGE,
        )
        for log in logs:
            raw = log.get("meta_data")
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
                # Upstream logs `json.dumps(data)` into a JSON field, which
                # can leave a JSON string inside a JSON string.
                if isinstance(payload, str):
                    payload = json.loads(payload)
            except (TypeError, ValueError):
                continue
            ids |= sticker_ids_in(payload)
        if len(logs) < PAGE:
            break
        start += PAGE
    return ids


def _flag(ids):
    from opportunity_management.opportunity_management.whatsapp_utils import MEDIA_LABELS

    if not ids:
        return 0
    rows = frappe.get_all(
        MSG,
        filters={"message_id": ["in", sorted(ids)], "type": "Incoming", "custom_is_sticker": 0},
        fields=["name", "custom_body_text"],
        limit_page_length=0,
    )
    for row in rows:
        values = {"custom_is_sticker": 1}
        # Stored as the photo label; a caption is impossible on a sticker.
        if (row.get("custom_body_text") or "") in ("", MEDIA_LABELS["image"]):
            values["custom_body_text"] = MEDIA_LABELS["sticker"]
        frappe.db.set_value(MSG, row["name"], values, update_modified=False)
    return len(rows)

"""
Repair conversations of customers who hide their number behind a WhatsApp
username, and backfill `wa_username` / `wa_user_id` everywhere.

Meta sends such a customer as a business-scoped user ID (BSUID), e.g.
`IQ.1858675848823706`. frappe_whatsapp stored it verbatim in
`WhatsApp Message.from`, but `normalize_phone()` stripped it to the digits
`1858675848823706`, so the thread was keyed on a fake 16-digit "phone" and
every reply went out to it and failed with Meta 131026.

1. Every conversation whose linked incoming message `from` is a BSUID while
   `phone` is that BSUID's digits gets `phone` / `wa_user_id` = the BSUID and
   a rebuilt `conversation_key` (skipped, with a print, when another row
   already owns that key).
2. `WhatsApp Notification Log.meta_data` rows mentioning "username" are
   scanned (oldest first, so the latest username wins); `contacts[].user_id`
   / `contacts[].wa_id` are matched to conversations and `wa_username` /
   `wa_user_id` filled. Malformed rows are skipped.

Idempotent and bulk-safe: direct `set_value`s (no controller, no realtime),
paged reads, one summary line, one commit at the end.
"""

import json
import re

import frappe

PAGE = 500
CONV = "WhatsApp Conversation"
LOG = "WhatsApp Notification Log"


def execute():
    if not frappe.db.exists("DocType", CONV) or not frappe.db.table_exists("WhatsApp Message"):
        return
    repaired, skipped = _repair_bsuid_phones()
    usernames, user_ids = _backfill_identity()
    frappe.db.commit()
    print(
        f"WhatsApp BSUID repair: {repaired} conversation(s) re-keyed, {skipped} skipped; "
        f"{usernames} username(s) and {user_ids} user id(s) backfilled"
    )


def _repair_bsuid_phones():
    from opportunity_management.opportunity_management.whatsapp_identity import is_bsuid
    from opportunity_management.opportunity_management.whatsapp_utils import normalize_phone

    # No `%` anywhere in this SQL and no values dict — the BSUID shape is
    # pre-filtered on the "." in third position and confirmed in Python.
    rows = frappe.db.sql(
        """
        SELECT DISTINCT m.custom_conversation AS conversation, m.`from` AS sender
        FROM `tabWhatsApp Message` m
        WHERE m.`type` = 'Incoming'
          AND COALESCE(m.custom_conversation, '') != ''
          AND SUBSTRING(m.`from`, 3, 1) = '.'
        """,
        as_dict=True,
    )
    senders = {}
    for row in rows:
        sender = (row.get("sender") or "").strip()
        if is_bsuid(sender):
            senders.setdefault(row["conversation"], set()).add(sender)
    if not senders:
        return 0, 0

    convs = frappe.get_all(
        CONV,
        filters={"name": ["in", sorted(senders)]},
        fields=["name", "phone", "whatsapp_account", "display_name"],
        limit_page_length=0,
    )
    repaired = skipped = 0
    for conv in convs:
        found = senders.get(conv["name"]) or set()
        if len(found) != 1:
            print(f"WhatsApp BSUID repair: {conv['name']} has several BSUIDs {sorted(found)} — skipped")
            skipped += 1
            continue
        bsuid = next(iter(found))
        phone = (conv.get("phone") or "").strip()
        if phone == bsuid:
            continue  # already repaired
        mangled = {re.sub(r"\D", "", bsuid), normalize_phone(bsuid)}
        if phone not in mangled:
            continue  # a real-phone thread the BSUID was merged into — leave it

        key = "{0}:{1}".format(conv.get("whatsapp_account") or "", bsuid)
        owner = frappe.db.get_value(CONV, {"conversation_key": key, "name": ["!=", conv["name"]]}, "name")
        if owner:
            print(f"WhatsApp BSUID repair: {conv['name']} → {key} already owned by {owner} — skipped")
            skipped += 1
            continue

        values = {"phone": bsuid, "wa_user_id": bsuid, "conversation_key": key}
        if (conv.get("display_name") or "").strip() in mangled:
            values["display_name"] = ""
        frappe.db.set_value(CONV, conv["name"], values, update_modified=False)
        repaired += 1
    return repaired, skipped


def _backfill_identity():
    from opportunity_management.opportunity_management.whatsapp_identity import (
        clean_username,
        contacts_by_sender,
        is_bsuid,
        normalize_wa_identifier,
    )

    if not frappe.db.table_exists(LOG):
        return 0, 0

    convs = frappe.get_all(
        CONV, fields=["name", "phone", "wa_user_id", "wa_username"], limit_page_length=0
    )
    by_phone = {c["phone"]: c for c in convs if c.get("phone")}
    by_uid = {c["wa_user_id"]: c for c in convs if c.get("wa_user_id")}
    wanted = {}  # conversation name → {"wa_username": …, "wa_user_id": …}

    start = 0
    while True:
        logs = frappe.get_all(
            LOG,
            filters={"meta_data": ["like", "%username%"]},
            fields=["name", "meta_data"],
            order_by="creation asc",
            limit_start=start,
            limit_page_length=PAGE,
        )
        for log in logs:
            try:
                payload = json.loads(log.get("meta_data") or "")
            except (TypeError, ValueError):
                continue
            seen = []
            for info in contacts_by_sender(payload).values():
                if info in seen:
                    continue
                seen.append(info)
                user_id = info.get("user_id")
                wa_id = normalize_wa_identifier(info.get("wa_id")) if info.get("wa_id") else ""
                conv = (
                    (by_phone.get(user_id) or by_uid.get(user_id) if user_id else None)
                    or (by_phone.get(wa_id) if wa_id else None)
                )
                if not conv:
                    continue
                target = wanted.setdefault(conv["name"], {})
                username = clean_username(info.get("username"))
                if username:
                    target["wa_username"] = username  # oldest first → latest wins
                if user_id and is_bsuid(user_id):
                    target["wa_user_id"] = user_id
        if len(logs) < PAGE:
            break
        start += PAGE

    current = {c["name"]: c for c in convs}
    usernames = user_ids = 0
    for name, target in wanted.items():
        row = current.get(name) or {}
        changes = {f: v for f, v in target.items() if v and row.get(f) != v}
        if not changes:
            continue
        frappe.db.set_value(CONV, name, changes, update_modified=False)
        usernames += 1 if "wa_username" in changes else 0
        user_ids += 1 if "wa_user_id" in changes else 0
    return usernames, user_ids

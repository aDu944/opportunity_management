"""
Ad referrals (ad_referral_contract.md): ensure `WhatsApp Message.custom_referral`
exists and backfill it from the raw webhook log.

Upstream frappe_whatsapp ignored `messages[].referral`, but it logs every
webhook body in `WhatsApp Notification Log.meta_data`, so the click-to-WhatsApp
ads of older messages can still be recovered. For each logged message with a
referral whose `WhatsApp Message` (matched on `message_id`) has none yet, the
referral is stored on the row; each touched conversation gets its latest one
(`ad_referral` / `ad_headline` / `ad_id`) unless it already holds a newer one.

The preview picture is not fetched: Meta's CDN links in old payloads have
expired, so `image_url` stays "". The conversation fields come from the
doctype JSON (synced before post_model_sync patches); the custom field is
created inline because fixtures sync after patches.

Idempotent (rows that already carry a referral are skipped), tolerant of
malformed / double-encoded JSON, one summary line.
"""

import frappe

from opportunity_management.opportunity_management import ad_referrals as AR

LOG = "WhatsApp Notification Log"
MSG = "WhatsApp Message"
CONV = "WhatsApp Conversation"
PAGE = 500
CHUNK = 200


def execute():
    if not frappe.db.table_exists(MSG):
        return
    from opportunity_management.opportunity_management.whatsapp_setup import (
        create_whatsapp_message_custom_fields,
    )

    create_whatsapp_message_custom_fields()
    if not frappe.db.table_exists(LOG) or not frappe.db.has_column(MSG, "custom_referral"):
        print("Ad referrals: field ensured, nothing to backfill")
        return

    found = _logged_referrals()
    stored, latest = _store(found)
    convs = _update_conversations(latest)
    frappe.db.commit()
    print(
        f"Ad referrals: {len(found)} referral(s) in the webhook log, "
        f"{stored} message(s) backfilled, {convs} conversation(s) updated"
    )


def _logged_referrals():
    """{wamid: referral} over the whole log (paged)."""
    found = {}
    start = 0
    while True:
        logs = frappe.get_all(
            LOG,
            filters={"meta_data": ["like", "%referral%"]},
            fields=["name", "meta_data"],
            order_by="creation asc",
            limit_start=start,
            limit_page_length=PAGE,
        )
        for log in logs:
            try:
                for mid, (ref, _preview) in AR.referrals_in_payload(log.get("meta_data")).items():
                    found[mid] = ref
            except Exception:
                continue
        if len(logs) < PAGE:
            break
        start += PAGE
    return found


def _store(found):
    """Write the message field; returns (count, {conversation: (creation, ref)})."""
    stored, latest = 0, {}
    mids = sorted(found)
    for i in range(0, len(mids), CHUNK):
        rows = frappe.get_all(
            MSG,
            filters={"message_id": ["in", mids[i:i + CHUNK]], "type": "Incoming"},
            fields=["name", "message_id", "creation", "custom_conversation", "custom_referral"],
            limit_page_length=0,
        )
        for row in rows:
            ref = dict(found[row["message_id"]], channel="WhatsApp")
            if not AR.public(row.get("custom_referral")):
                frappe.db.set_value(MSG, row["name"], "custom_referral", AR.dump(ref), update_modified=False)
                stored += 1
            else:
                ref = AR.decode_json(row["custom_referral"]) or ref
            conv = row.get("custom_conversation")
            if conv and (conv not in latest or str(row["creation"]) > str(latest[conv][0])):
                latest[conv] = (row["creation"], ref)
    return stored, latest


def _update_conversations(latest):
    if not latest or not frappe.db.has_column(CONV, "ad_referral"):
        return 0
    updated = 0
    for conv, (creation, ref) in latest.items():
        if not frappe.db.exists(CONV, conv):
            continue
        current = AR.decode_json(frappe.db.get_value(CONV, conv, "ad_referral"))
        at = str(creation)[:19]
        if current and str(current.get("at") or "") >= at:
            continue
        frappe.db.set_value(
            CONV,
            conv,
            {
                "ad_referral": AR.dump(AR.conv_ad(ref, at)),
                "ad_headline": (ref.get("headline") or "")[:140],
                "ad_id": (ref.get("ad_id") or "")[:140],
            },
            update_modified=False,
        )
        updated += 1
    return updated

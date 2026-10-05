"""
Guarded wrapper around `frappe_whatsapp.utils.webhook.webhook`.

Registered through `override_whitelisted_methods` in hooks.py, so Meta keeps
POSTing to the URL it already has configured
(`/api/method/frappe_whatsapp.utils.webhook.webhook`) and we get a seam
without touching the frappe_whatsapp source.

Four things the upstream handler does not do (verified on v1.0.12):

1. **No signature check.** Anyone who knows the URL can inject messages.
   We verify `X-Hub-Signature-256` against `frappe.conf.whatsapp_app_secret`.
   With no secret configured we log once and allow, so the integration keeps
   working until the Meta App Secret is available (plan assumption 1).
2. **No `message_id` dedupe.** Meta retries aggressively — a slow request or
   a 500 produces the same message twice.
3. **`location` / `contacts` / unknown inbound types raise KeyError**, which
   500s the request and makes Meta retry forever. We rewrite those entries
   into `text` before the original ever sees them.

4. **`contacts[].profile.username` / `user_id` are dropped.** We stash them
   in `frappe.flags` (`_stash_sender_contacts`) for the after_insert hook.
5. **Statuses for messages it never stored crash it** (`get_doc` with
   name None). The number is shared with other senders, so those are
   normal; `_drop_foreign_statuses` removes them first (after
   `external_replies` stored a PBX reply's placeholder).

`webhook.post()` reads `frappe.local.form_dict`, so mutating it in place is
enough — the original picks up our edits.

It also retries the delegation on write conflicts. Meta posts `sent` and
`delivered` for the same message milliseconds apart; two gunicorn workers
load the same `WhatsApp Message`, one saves, and the other's
`doc.save()` raises TimestampMismatchError — that status tick used to be
lost (and logged, hundreds of times). See `_delegate`.
"""

import hashlib
import hmac
import json
import time

import frappe

_SIGNATURE_HEADER = "X-Hub-Signature-256"
_MISSING_SECRET_FLAG = "_whatsapp_missing_secret_logged"

# One try plus this many retries when the delegated handler hits a write
# conflict (see `_delegate`).
_DELEGATION_RETRIES = 2


@frappe.whitelist(allow_guest=True)
def webhook():
    """Meta webhook entry point (GET verify handshake / POST events)."""
    try:
        if frappe.request and frappe.request.method == "GET":
            # The hub.challenge handshake — nothing to guard, nothing to
            # dedupe. Hand it straight over.
            return _original()()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: GET delegation failed")
        raise

    try:
        if not _verify_signature():
            frappe.local.response["http_status_code"] = 403
            return "forbidden"
    except frappe.PermissionError:
        raise
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: signature check failed")

    data = frappe.local.form_dict
    try:
        dropped = _dedupe_messages(data)
        _coerce_unsupported(data)
        if dropped and not _has_payload(data):
            # Everything in this delivery was a retry we already stored.
            return "ok"
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: preprocessing failed")

    try:
        # Once, before the first delegation attempt (the retry loop in
        # `_delegate` only re-runs the message dedupe).
        if _drop_foreign_statuses(data) and not _has_payload(data):
            return "ok"
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: status filter failed")
    try:  # `message_echoes` (another app's sends) — never seen so far
        _external().ingest_echoes(data)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: echo ingest failed")

    _stash_sender_contacts(data)
    _stash_referrals(data)

    try:
        return _delegate(data)
    except Exception:
        # Return 200 regardless: the raw payload is already persisted in
        # `WhatsApp Notification Log` by the original handler, and a non-200
        # makes Meta retry the same delivery for hours.
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: delegation failed")
        return "ok"


def _retryable_errors():
    """Write-conflict exceptions worth a rollback + retry. Looked up lazily
    (and defensively) so an older Frappe without one of them still imports."""
    names = ("TimestampMismatchError", "QueryDeadlockError")
    found = tuple(getattr(frappe, n, None) or getattr(frappe.exceptions, n, None) for n in names)
    return tuple(cls for cls in found if isinstance(cls, type)) or (frappe.TimestampMismatchError,)


def _delegate(data):
    """Run the upstream handler, retrying write conflicts.

    Two Meta status callbacks for one message land on two workers at once;
    the loser's `doc.save()` raises TimestampMismatchError (or the pair
    deadlocks). Rolling back and re-running reloads the doc, so the second
    save succeeds and the status tick is kept. Only the last failure
    propagates (and is logged by the caller).

    The rollback undoes whatever the failed attempt wrote, including any
    inbound `WhatsApp Message` it inserted, so `_dedupe_messages` is re-run
    against the database before every retry: a message committed meanwhile
    (by a parallel Meta retry, or by an upstream mid-request commit) is
    dropped, and one that was rolled back is inserted exactly once.
    """
    retryable = _retryable_errors()
    for attempt in range(_DELEGATION_RETRIES + 1):
        if attempt:
            frappe.db.rollback()
            time.sleep(0.05 * attempt)
            if _dedupe_messages(data) and not _has_payload(data):
                return "ok"
        try:
            return _original()()
        except retryable:
            if attempt >= _DELEGATION_RETRIES:
                raise


def _original():
    """Import lazily — hooks.py is loaded on every request, and importing
    frappe_whatsapp at module scope would make this app hard-depend on it."""
    from frappe_whatsapp.utils.webhook import webhook as original_webhook

    return original_webhook


# ── signature ────────────────────────────────────────────────────────────────

def _verify_signature() -> bool:
    secret = frappe.conf.get("whatsapp_app_secret")
    if not secret:
        if not getattr(frappe.local, _MISSING_SECRET_FLAG, False):
            setattr(frappe.local, _MISSING_SECRET_FLAG, True)
            frappe.log_error(
                "whatsapp_app_secret is not set in site_config.json — inbound "
                "WhatsApp webhooks are being accepted without signature "
                "verification.",
                "WhatsApp webhook: signature verification disabled",
            )
        return True

    header = (frappe.get_request_header(_SIGNATURE_HEADER) or "").strip()
    if not header.startswith("sha256="):
        return False

    raw = frappe.request.get_data() if frappe.request else b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    expected = hmac.new(
        str(secret).encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1].strip())


# ── payload surgery ──────────────────────────────────────────────────────────

def _entries(data):
    entry = data.get("entry")
    if isinstance(entry, dict):
        entry = [entry]
    return entry if isinstance(entry, list) else []


def _values(data):
    """Yield every `changes[].value` dict in the payload."""
    for entry in _entries(data):
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if isinstance(change, dict) and isinstance(change.get("value"), dict):
                yield change["value"]


def _dedupe_messages(data) -> int:
    """Drop message entries whose `message_id` is already stored.

    Returns how many were dropped. Status callbacks are left alone — those
    are idempotent updates by design.
    """
    dropped = 0
    for value in _values(data):
        messages = value.get("messages")
        if not isinstance(messages, list) or not messages:
            continue
        kept = []
        for message in messages:
            mid = message.get("id") if isinstance(message, dict) else None
            if mid and frappe.db.exists("WhatsApp Message", {"message_id": mid}):
                dropped += 1
                continue
            kept.append(message)
        if len(kept) != len(messages):
            value["messages"] = kept
            if not kept:
                value.pop("messages", None)
    return dropped


def status_ids(data) -> set:
    """Every `statuses[].id` in the payload."""
    ids = set()
    for value in _values(data):
        for status in value.get("statuses") or []:
            if isinstance(status, dict) and status.get("id"):
                ids.add(status["id"])
    return ids


def filter_statuses(data, known_ids) -> int:
    """Remove status entries whose `id` is not in `known_ids` (in place).

    Returns how many were removed; an emptied `statuses` key is popped. A
    payload without statuses is not touched at all.
    """
    dropped = 0
    for value in _values(data):
        statuses = value.get("statuses")
        if not isinstance(statuses, list) or not statuses:
            continue
        kept = [s for s in statuses if isinstance(s, dict) and s.get("id") in known_ids]
        if len(kept) != len(statuses):
            dropped += len(statuses) - len(kept)
            value["statuses"] = kept
            if not kept:
                value.pop("statuses", None)
    return dropped


# Waits (seconds) for a status that raced the commit of our own outgoing row.
_STATUS_WAITS = (0.15, 0.35)


def _known_message_ids(ids) -> set:
    if not ids:
        return set()
    return set(
        frappe.get_all(
            "WhatsApp Message", filters={"message_id": ["in", list(ids)]}, pluck="message_id"
        )
    )


def _drop_foreign_statuses(data) -> int:
    """Drop status callbacks for messages ERPNext has no row for.

    The number is shared with the web shop (OTP templates) and the PBX
    client; Meta sends their statuses here too, and upstream's
    `update_message_status` crashes on them (`get_doc(..., None)`). Our own
    `sent` can also beat the commit of the request that inserted the row,
    so unknown ids get `_STATUS_WAITS` before they are dropped.

    Each re-check first ends the transaction so it is not answered from
    the request's repeatable-read snapshot. That is a COMMIT, not a
    rollback: by this point the request may already have written Error
    Log rows (`_verify_signature` logs the missing secret on every request
    while it is unset; the preprocessing failure logs), which a rollback
    would silently discard. Nothing else has been written yet, so the
    commit only persists those logs early. Dropped statuses are not logged.
    """
    ids = status_ids(data)
    if not ids:
        return 0
    unknown = ids - _known_message_ids(ids)
    for wait in _STATUS_WAITS:
        if not unknown:
            break
        time.sleep(wait)
        frappe.db.commit()
        unknown -= _known_message_ids(unknown)
    if not unknown:
        return 0
    try:  # a PBX (other-app) reply → placeholder; ids whose row exists by now stay
        unknown -= _external().record_unknown_statuses(data, unknown)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: external replies failed")
    return filter_statuses(data, ids - unknown)


def _external():
    from opportunity_management.opportunity_management import external_replies

    return external_replies


_SUPPORTED_TYPES = {
    "text", "image", "audio", "video", "document", "button",
    "interactive", "reaction", "order",
}


def _coerce_unsupported(data):
    """Rewrite entries the upstream handler would KeyError on into `text`."""
    for value in _values(data):
        messages = value.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            mtype = message.get("type")
            if mtype in _SUPPORTED_TYPES:
                continue
            if mtype == "sticker" and isinstance(message.get("sticker"), dict):
                # Upstream has no `sticker` branch (KeyError), but its `image`
                # branch downloads any media id and attaches it. A sticker is
                # just a webp with the same {id, mime_type} shape, so present
                # it as an image and the customer's sticker is preserved
                # instead of being flattened to "[unsupported]".
                sticker = dict(message["sticker"])
                sticker.setdefault("caption", "")
                message["type"] = "image"
                message["image"] = sticker
                _remember_sticker(message.get("id"))
                continue
            if mtype in ("location", "contacts"):
                # Upstream still gets text, but the hook turns the row back
                # into a card from this stash (whatsapp_message_extras).
                _remember_card(message)
            if mtype == "location":
                body = _location_text(message.get("location") or {})
            elif mtype == "contacts":
                body = _contacts_text(message.get("contacts") or [])
            else:
                body = f"[unsupported message type: {mtype}]"
            message["type"] = "text"
            message["text"] = {"body": body}


def _remember_sticker(message_id):
    """Once coerced, a sticker is indistinguishable from a photo; record its
    wamid for `whatsapp_hooks` to set `custom_is_sticker`. Best-effort."""
    if not message_id:
        return
    try:
        from opportunity_management.opportunity_management.whatsapp_identity import (
            STICKER_IDS_FLAG,
        )

        ids = frappe.flags.get(STICKER_IDS_FLAG)
        if not isinstance(ids, set):
            ids = frappe.flags[STICKER_IDS_FLAG] = set()
        ids.add(message_id)
    except Exception:
        pass


def _remember_card(message):
    try:
        from opportunity_management.opportunity_management.whatsapp_message_extras import remember_card

        remember_card(message)
    except Exception:
        pass


def _location_text(location) -> str:
    lat = location.get("latitude")
    lon = location.get("longitude")
    parts = ["\U0001F4CD Location"]
    name = (location.get("name") or "").strip()
    address = (location.get("address") or "").strip()
    if name:
        parts.append(name)
    if address:
        parts.append(address)
    if lat is not None and lon is not None:
        parts.append(f"{lat},{lon}")
        parts.append(f"https://maps.google.com/?q={lat},{lon}")
    return "\n".join(parts)


def _contacts_text(contacts) -> str:
    lines = ["\U0001F464 Contact card"]
    for contact in contacts[:5]:
        if not isinstance(contact, dict):
            continue
        name = (contact.get("name") or {}).get("formatted_name") or ""
        phones = ", ".join(
            p.get("phone", "") for p in (contact.get("phones") or []) if isinstance(p, dict)
        )
        line = " — ".join(part for part in (name, phones) if part)
        if line:
            lines.append(line)
    return "\n".join(lines) if len(lines) > 1 else "\U0001F464 Contact card"


def _stash_sender_contacts(data):
    """Expose `contacts[]` (username, BSUID, wa_id) to the after_insert hook.

    frappe_whatsapp keeps only `profile.name`; the username and the
    business-scoped user ID would otherwise be lost. Keyed by both `wa_id`
    and `user_id` (see `whatsapp_identity.contacts_by_sender`). Best-effort:
    a failure here must never cost Meta a 200.
    """
    try:
        from opportunity_management.opportunity_management.whatsapp_identity import (
            SENDER_CONTACTS_FLAG,
            contacts_by_sender,
        )

        frappe.flags[SENDER_CONTACTS_FLAG] = contacts_by_sender(data)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: sender contacts stash failed")


def _stash_referrals(data):
    """`messages[].referral` (click-to-WhatsApp ad / post) by wamid, for
    the after_insert hook — upstream drops it. Never raises."""
    try:
        from opportunity_management.opportunity_management.inbox_referrals import stash_whatsapp

        stash_whatsapp(data)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp webhook: referral stash failed")


def _has_payload(data) -> bool:
    for value in _values(data):
        if value.get("messages") or value.get("statuses"):
            return True
        # message_template_status_update and friends carry neither.
        if set(value.keys()) - {"messaging_product", "metadata", "contacts"}:
            return True
    return False


# ── local end-to-end helper ──────────────────────────────────────────────────

def simulate(fixture="text_inbound"):
    """Feed a stored Meta payload through the wrapper, for `bench execute`:

        bench --site erp.local execute \\
          opportunity_management.opportunity_management.whatsapp_webhook.simulate \\
          --kwargs "{'fixture': 'text_inbound'}"

    Fixtures live in `opportunity_management/opportunity_management/tests/fixtures/`
    as `meta_<fixture>.json`. Signature verification is skipped (there is no
    HTTP request to sign) — everything after it runs for real, so this does
    insert WhatsApp Messages and does fire the hooks.
    """
    import os

    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "tests",
        "fixtures",
        f"meta_{fixture}.json",
    )
    with open(path) as handle:
        payload = json.load(handle)

    frappe.local.form_dict = frappe._dict(payload)
    data = frappe.local.form_dict
    dropped = _dedupe_messages(data)
    _coerce_unsupported(data)
    if dropped and not _has_payload(data):
        return {"fixture": fixture, "dropped": dropped, "result": "all duplicates"}

    _stash_sender_contacts(data)
    _stash_referrals(data)
    _original()()
    frappe.db.commit()
    return {"fixture": fixture, "dropped": dropped, "result": "delivered"}

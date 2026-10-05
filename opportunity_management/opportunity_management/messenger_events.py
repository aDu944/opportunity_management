"""
Messenger webhook payload → normalised events, and the delivery / read
watermark rule. Pure (no `frappe`), loaded bench-free by
`tests/test_messenger_pure.py`.

A Page webhook POST is `{"object": "page", "entry": [{"id": <page id>,
"time": …, "messaging": [<event>, …]}]}`; every event has `sender.id`,
`recipient.id`, `timestamp` and one of:

    message      {mid, text?, attachments?: [{type, payload: {url, sticker_id?}}],
                  quick_reply?: {payload}, reply_to?: {mid}, is_echo?, app_id?, metadata?}
    delivery     {mids?: [...], watermark}
    read         {watermark}
    reaction     {reaction, emoji, action: react|unreact, mid}
    postback     {mid?, title, payload, referral?}
    referral     {ref?, source, type, ad_id?, ads_context_data?, referer_uri?}
                 (`messaging_referrals`: an existing thread opened from an
                 ad / m.me link — no message comes with it)

`message.referral` and `postback.referral` ride on their event.

For an echo the Page is the sender, so the customer is `recipient.id`.
Normalised shape (every kind carries `psid`, `page_id`, `timestamp`):

    {"kind": "message", "mid", "text", "attachments": [{type, url, sticker}],
     "reply_to", "echo", "ours"}
    {"kind": "delivery", "mids", "watermark"}
    {"kind": "read", "watermark"}
    {"kind": "reaction", "mid", "emoji", "action"}
    {"kind": "postback", "mid", "text"}
    {"kind": "referral", "referral"}

A message / postback with a referral also carries `"referral": <Meta's
dict, verbatim>`; `ad_referrals.from_messenger` normalises it later.
"""

# Same marker as messenger_api.OUR_METADATA (kept import-free; a test pins it).
OUR_METADATA = "alkhora_inbox"
# Inbox content types for Messenger attachment types; "file" is a document.
CONTENT_TYPES = {"image": "image", "audio": "audio", "video": "video", "file": "document"}
# Status ranks: a tick never moves a row backwards.
_RANK = {"": 0, "success": 1, "sent": 1, "delivered": 2, "read": 3}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def _attachments(message):
    out, extra_text = [], []
    for att in _list(message.get("attachments")):
        att = _dict(att)
        kind = str(att.get("type") or "").lower()
        payload = _dict(att.get("payload"))
        url = payload.get("url") or ""
        if kind == "fallback" or (kind not in ("image", "audio", "video", "file") and not url):
            # A shared link / unsupported card: keep what can be read.
            title = att.get("title") or payload.get("title") or ""
            link = url or att.get("url") or ""
            text = " ".join(t for t in (title, link) if t)
            if text:
                extra_text.append(text)
            continue
        sticker = kind == "image" and bool(payload.get("sticker_id") or message.get("sticker_id"))
        out.append({"type": CONTENT_TYPES.get(kind, "document"), "url": url, "sticker": sticker})
    return out, extra_text


def _message(event, base):
    message = _dict(event.get("message"))
    mid = message.get("mid")
    if not mid:
        return None
    attachments, extra = _attachments(message)
    text = str(message.get("text") or "")
    if not text and _dict(message.get("quick_reply")).get("payload"):
        text = str(message["quick_reply"]["payload"])
    if extra:
        text = "\n".join([t for t in [text] + extra if t])
    return _with_referral(message, dict(
        base,
        kind="message",
        mid=mid,
        text=text,
        attachments=attachments,
        reply_to=_dict(message.get("reply_to")).get("mid") or None,
        echo=bool(message.get("is_echo")),
        ours=message.get("metadata") == OUR_METADATA,
    ))


def _with_referral(source, parsed):
    """Copy `source.referral` (a dict) onto a parsed event — only when present,
    so events without one keep their exact shape."""
    referral = source.get("referral")
    if isinstance(referral, dict) and referral:
        parsed["referral"] = referral
    return parsed


def parse(data, page_id=None) -> list:
    """Every usable event in a webhook body, in order. Entries for another
    Page (when `page_id` is set) are dropped. Never raises."""
    events = []
    if not isinstance(data, dict) or data.get("object") != "page":
        return events
    for entry in _list(data.get("entry")):
        entry = _dict(entry)
        entry_page = str(entry.get("id") or "")
        if page_id and entry_page != str(page_id):
            continue
        for event in _list(entry.get("messaging")):
            try:
                parsed = _event(_dict(event), entry_page)
            except Exception:
                parsed = None
            if parsed:
                events.append(parsed)
    return events


def _event(event, page_id):
    sender = str(_dict(event.get("sender")).get("id") or "")
    recipient = str(_dict(event.get("recipient")).get("id") or "")
    is_echo = bool(_dict(event.get("message")).get("is_echo"))
    psid = recipient if is_echo else sender
    if not psid:
        return None
    base = {"psid": psid, "page_id": page_id, "timestamp": event.get("timestamp")}
    if "message" in event:
        return _message(event, base)
    if "delivery" in event:
        delivery = _dict(event["delivery"])
        return dict(base, kind="delivery", mids=[m for m in _list(delivery.get("mids")) if m],
                    watermark=_ms(delivery.get("watermark")))
    if "read" in event:
        return dict(base, kind="read", watermark=_ms(_dict(event["read"]).get("watermark")))
    if "reaction" in event:
        reaction = _dict(event["reaction"])
        if not reaction.get("mid"):
            return None
        action = "unreact" if reaction.get("action") == "unreact" else "react"
        emoji = "" if action == "unreact" else str(reaction.get("emoji") or "")
        return dict(base, kind="reaction", mid=reaction["mid"], emoji=emoji, action=action)
    if "postback" in event:
        postback = _dict(event["postback"])
        text = str(postback.get("title") or postback.get("payload") or "")
        if not text:
            return None
        return _with_referral(postback, dict(base, kind="postback", mid=postback.get("mid") or None, text=text))
    if "referral" in event:
        referral = _dict(event["referral"])
        return dict(base, kind="referral", referral=referral) if referral else None
    return None


def _ms(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ── watermarks ───────────────────────────────────────────────────────────────

def status_rank(status) -> int:
    return _RANK.get(str(status or "").strip().lower(), -1)


def watermark_targets(rows, target, watermark_ms, mids=()) -> list:
    """Names of our outgoing rows a delivery / read event moves to `target`.

    `rows`: dicts `{name, message_id, status, sent_ms}` (`sent_ms` = epoch
    ms the row was sent). A row is hit when it was sent at or before the
    watermark, or its mid is listed (deliveries name them), and its status
    is below `target`. Failed / unknown statuses are never touched.
    """
    goal = status_rank(target)
    listed = set(mids or ())
    out = []
    for row in rows or []:
        rank = status_rank(row.get("status"))
        if rank < 0 or rank >= goal:
            continue
        sent = row.get("sent_ms")
        covered = bool(watermark_ms) and sent is not None and sent <= watermark_ms
        if covered or (row.get("message_id") and row.get("message_id") in listed):
            out.append(row["name"])
    return out

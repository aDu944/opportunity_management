"""
Ad / post / link referrals — the pure half (no `frappe`), loaded bench-free
by `tests/test_ad_referrals_pure.py`. The frappe side (stash, storage,
preview download, note) is `inbox_referrals`.

Meta tells us which advertisement a chat came from (ad_referral_contract.md):

WhatsApp Cloud API — `entry[].changes[].value.messages[].referral`:
    {source_url, source_id, source_type: "ad" | "post", headline, body,
     media_type: "image" | "video", image_url?, video_url?, thumbnail_url?,
     ctwa_clid?, welcome_message?: {text}}
Messenger Platform — `message.referral`, `postback.referral`, or a bare
`referral` event (`messaging_referrals`):
    {ref?, source: "ADS" | "SHORTLINK" | "CUSTOMER_CHAT_PLUGIN" | …,
     type: "OPEN_THREAD", ad_id?, referer_uri?,
     ads_context_data?: {ad_title, photo_url, video_url, post_id, product_id}}

Both become the contract's `referral`:
    {source: ad|post|link|other, headline, body, url, image_url, media_type,
     ad_id, ref}
`image_url` is always "" here: Meta's preview links expire, so the picture
is downloaded later (`preview_source` says from where) and the stored file
path is filled in by `inbox_referrals.download_preview`.

The stored JSON (`WhatsApp Message.custom_referral`, `WhatsApp Internal
Note.referral`) is that dict plus `channel` and, for WhatsApp, `ctwa_clid`
(Meta's click id, kept for conversion reporting; not part of the API shape).
`WhatsApp Conversation.ad_referral` is the ConvRow `ad` shape (+ `at`).
"""

import json

SOURCES = ("ad", "post", "link", "other")
MEDIA_TYPES = ("image", "video")
HEADLINE_MAX = 200
BODY_MAX = 1000
URL_MAX = 1000
ID_MAX = 140
CLID_MAX = 500

REFERRAL_KEYS = ("source", "headline", "body", "url", "image_url", "media_type", "ad_id", "ref")
AD_KEYS = ("source", "headline", "body", "url", "image_url", "ad_id", "at")

_LABELS = {"ad": "Ad", "post": "Post", "link": "Link", "other": "Link"}


# ── small helpers ────────────────────────────────────────────────────────────

def _dict(value):
    return value if isinstance(value, dict) else {}


def _s(value, cap):
    """Trimmed string, capped; numbers (Meta sends ids as both) are kept."""
    if value is None or isinstance(value, (dict, list, tuple, set, bool)):
        return ""
    text = str(value).strip()
    return text[:cap].rstrip() if len(text) > cap else text


def http_url(value) -> str:
    """`value` when it is an http(s) URL, else "" (never javascript: etc.)."""
    text = _s(value, URL_MAX)
    lower = text.lower()
    if (lower.startswith("https://") or lower.startswith("http://")) and " " not in text:
        return text
    return ""


def decode_json(raw):
    """A dict from a dict / JSON string / JSON-in-a-JSON-string; else None."""
    value = raw
    for _ in range(3):
        if isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", "replace")
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, dict) else None


def _meaningful(ref, preview="") -> bool:
    if any(ref.get(k) for k in ("headline", "body", "url", "ad_id", "ref")) or preview:
        return True
    return ref.get("source") in ("ad", "post", "link")


def _blank():
    return {k: "" for k in REFERRAL_KEYS}


# ── WhatsApp ─────────────────────────────────────────────────────────────────

def from_whatsapp(raw):
    """`messages[].referral` → contract dict (+ `ctwa_clid`), or None."""
    raw = decode_json(raw)
    if not raw:
        return None
    kind = _s(raw.get("source_type"), 20).lower()
    media = _s(raw.get("media_type"), 20).lower()
    ref = _blank()
    ref.update({
        "source": kind if kind in ("ad", "post") else "other",
        "headline": _s(raw.get("headline"), HEADLINE_MAX),
        "body": _s(raw.get("body"), BODY_MAX),
        "url": http_url(raw.get("source_url")),
        "media_type": media if media in MEDIA_TYPES else "",
        "ad_id": _s(raw.get("source_id"), ID_MAX),
    })
    if not _meaningful(ref, whatsapp_preview(raw)):
        return None
    clid = _s(raw.get("ctwa_clid"), CLID_MAX)
    if clid:
        ref["ctwa_clid"] = clid
    return ref


def whatsapp_preview(raw) -> str:
    """Where to fetch the ad's picture: the thumbnail of a video ad, the
    image of an image ad (either as a fallback)."""
    raw = _dict(raw)
    if _s(raw.get("media_type"), 20).lower() == "video":
        order = ("thumbnail_url", "image_url")
    else:
        order = ("image_url", "thumbnail_url")
    for key in order:
        url = http_url(raw.get(key))
        if url:
            return url
    return ""


# ── Messenger ────────────────────────────────────────────────────────────────

def messenger_source(source, has_ad=False) -> str:
    value = _s(source, 60).upper()
    if value == "ADS":
        return "ad"
    if value in ("SHORTLINK", "SHORT-URL", "SHORT_URL", "MESSENGER_CODE"):
        return "link"
    if "POST" in value:
        return "post"
    if not value and has_ad:
        return "ad"
    return "other"


def from_messenger(raw):
    """A Messenger `referral` → contract dict, or None. There is no ad body
    and no public ad URL in Messenger's payload; `url` is `referer_uri`
    (the site a chat plugin / link was opened from) when it is http(s)."""
    raw = decode_json(raw)
    if not raw:
        return None
    ctx = _dict(raw.get("ads_context_data"))
    ad_id = _s(raw.get("ad_id"), ID_MAX)
    media = "image" if http_url(ctx.get("photo_url")) else ("video" if http_url(ctx.get("video_url")) else "")
    ref = _blank()
    ref.update({
        "source": messenger_source(raw.get("source"), has_ad=bool(ad_id)),
        "headline": _s(ctx.get("ad_title"), HEADLINE_MAX),
        "url": http_url(raw.get("referer_uri")),
        "media_type": media,
        "ad_id": ad_id,
        "ref": _s(raw.get("ref"), ID_MAX),
    })
    if not _meaningful(ref, messenger_preview(raw)):
        return None
    return ref


def messenger_preview(raw) -> str:
    """`photo_url`, else `video_url` (Meta documents it as the video's
    thumbnail). The download refuses anything that is not an image."""
    ctx = _dict(_dict(raw).get("ads_context_data"))
    return http_url(ctx.get("photo_url")) or http_url(ctx.get("video_url"))


# ── stored JSON → API shapes ─────────────────────────────────────────────────

def dump(ref) -> str:
    return json.dumps(ref, ensure_ascii=False, separators=(",", ":"))


def public(raw):
    """Stored JSON (any garbage tolerated) → the ThreadItem `referral`."""
    data = decode_json(raw)
    if not data:
        return None
    out = {k: _s(data.get(k), BODY_MAX if k == "body" else URL_MAX) for k in REFERRAL_KEYS}
    out["headline"] = out["headline"][:HEADLINE_MAX]
    if out["source"] not in SOURCES:
        out["source"] = "other"
    if out["media_type"] not in MEDIA_TYPES:
        out["media_type"] = ""
    out["url"] = http_url(out["url"])
    if not _meaningful(out, out["image_url"]):
        return None
    return out


def conv_ad(ref, at):
    """The conversation's `ad_referral` value for a contract referral."""
    ref = _dict(ref)
    out = {k: ref.get(k) or "" for k in AD_KEYS if k != "at"}
    out["at"] = str(at or "")[:19]
    return out


def public_ad(raw):
    """Stored `ad_referral` → ConvRow `ad`, or None."""
    data = decode_json(raw)
    if not data:
        return None
    ref = public(data)
    if not ref:
        return None
    out = conv_ad(ref, data.get("at"))
    return out


def label(ref) -> str:
    return _LABELS.get(_dict(ref).get("source"), "Link")


def note_text(ref) -> str:
    """The system note for a referral that came without a message."""
    ref = _dict(ref)
    source = ref.get("source")
    if source == "ad":
        headline = ref.get("headline") or ""
        return "Opened from ad: " + headline if headline else "Opened from an ad"
    if source == "post":
        return "Opened from a post"
    return "Opened from a link"


# ── push ─────────────────────────────────────────────────────────────────────

def ad_line(ref, bilingual=False) -> str:
    """`Ad: <headline>` for the inbound push body ("" without a referral).
    `bilingual` puts the Arabic line first, the house style for two-language
    bodies."""
    ref = _dict(ref)
    if not ref:
        return ""
    headline = (ref.get("headline") or "").strip()
    if len(headline) > 80:
        headline = headline[:79].rstrip() + "…"
    if not headline:
        # No title to quote: say where it came from instead.
        en, ar = _NO_HEADLINE.get(ref.get("source"), _NO_HEADLINE["link"])
        return ar + "\n" + en if bilingual else en
    line = "Ad: " + headline
    return "إعلان: " + headline + "\n" + line if bilingual else line


_NO_HEADLINE = {
    "ad": ("From an ad", "من إعلان"),
    "post": ("From a post", "من منشور"),
    "link": ("From a link", "من رابط"),
}


def add_to_push(title, body, data, ref, bilingual=False):
    """(title, body, data) with the ad line appended and `data.ad = "1"`."""
    line = ad_line(ref, bilingual=bilingual)
    if not line:
        return title, body, data
    data = dict(data or {})
    data["ad"] = "1"
    return title, (body + "\n" + line) if body else line, data


# ── backfill: raw webhook log → {wamid: referral} ────────────────────────────

def referrals_in_payload(payload) -> dict:
    """`{wamid: (referral, preview_url)}` for every inbound message in one
    WhatsApp webhook payload that carried a usable referral."""
    out = {}
    payload = decode_json(payload)
    entries = _dict(payload).get("entry")
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries if isinstance(entries, list) else []:
        changes = _dict(entry).get("changes")
        for change in changes if isinstance(changes, list) else []:
            messages = _dict(_dict(change).get("value")).get("messages")
            for message in messages if isinstance(messages, list) else []:
                message = _dict(message)
                mid = _s(message.get("id"), 255)
                ref = from_whatsapp(message.get("referral")) if mid else None
                if ref:
                    out[mid] = (ref, whatsapp_preview(message.get("referral")))
    return out

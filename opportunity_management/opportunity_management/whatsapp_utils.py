"""
Low-level helpers for the WhatsApp team inbox.

Everything here is deliberately import-cheap and side-effect free at module
scope so `test_whatsapp_utils.py` can import it with a *stubbed* `frappe`
module and exercise the pure functions (`normalize_phone`,
`detect_language`, `is_business_hours`, `normalize_body`) without a bench.
That is the reason every `frappe.*` call below lives inside a function body
and why `from frappe.utils import …` is always a local import.

The idempotent schema bootstrap that used to live here (the
`WhatsApp Message` Custom Fields, the `WhatsApp Agent` role + DocPerms, the
seeded Inbox Settings / tags / quick replies) now lives in
`whatsapp_setup.py` — it is all writes, and keeping it here would have
dragged this module past the 500-line limit.
"""

import json
import re

import frappe

# ── Constants ────────────────────────────────────────────────────────────────

# Meta's customer-service window.
WINDOW_SECONDS = 24 * 60 * 60

# U+0600–U+06FF (Arabic) plus the Arabic Supplement / Extended-A blocks —
# enough to tell an Arabic message from a Latin one.
_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")

_DAY_TOKENS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Shortest national significant number we are willing to treat as a real
# local number worth prefixing a country code onto.
MIN_NATIONAL_DIGITS = 7

# Display labels for media messages — WhatsApp itself shows an icon + noun in
# the conversation list, and the thread preview / push body needs the same.
MEDIA_LABELS = {
    "image": "\U0001F4F7 Photo",
    "document": "\U0001F4C4 Document",
    "audio": "\U0001F3A4 Voice note",
    "video": "\U0001F3AC Video",
    "sticker": "\U0001F9E9 Sticker",
}

# Meta error code for "message outside the 24 hour window".
WINDOW_CLOSED_ERROR_CODE = "131047"


# ── Pure helpers ─────────────────────────────────────────────────────────────

def _g(obj, key, default=None):
    """Read `key` off a Document, a dict, or a plain object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(key, default)
    else:
        getter = getattr(obj, "get", None)
        if callable(getter) and not isinstance(obj, (str, bytes)):
            try:
                value = obj.get(key)
            except Exception:
                value = getattr(obj, key, default)
        else:
            value = getattr(obj, key, default)
    return default if value is None else value


def strip_html(raw) -> str:
    """HTML → plain text, preserving word boundaries.

    `WhatsApp Message.message` is an HTML Editor field, so inbound text that
    happened to contain markup and every outbound body written from Desk come
    back wrapped in tags.
    """
    from html import unescape

    text = str(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # An opening tag became a space, so a `</p><p>` pair leaves "\n " behind.
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def normalize_phone(raw, default_cc=None) -> str:
    """Reduce any phone spelling to bare international digits.

    Threads key on this, so it has to be stable across the shapes Meta,
    ERPNext Contacts and humans all use:

        0770 123 4567      → 9647701234567   (local, cc prefixed)
        +964 770 123 4567  → 9647701234567
        00964 770 123 4567 → 9647701234567
        964 0770 123 4567  → 9647701234567   (cc + trunk 0)
        +1 415 555 2671    → 14155552671     (foreign, left alone)

    Returns "" for anything shorter than 8 digits — junk we must not thread on.
    `default_cc` falls back to WhatsApp Inbox Settings when not supplied.
    """
    if raw is None:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return ""

    # International access prefix.
    if digits.startswith("00"):
        digits = digits[2:]

    cc = re.sub(r"\D", "", str(default_cc)) if default_cc is not None else _default_country_code()

    if cc and digits.startswith(cc):
        # Strip a trunk "0" that slipped in after the country code.
        rest = digits[len(cc):].lstrip("0")
        digits = cc + rest
    elif digits.startswith("0"):
        rest = digits.lstrip("0")
        digits = (cc + rest) if (cc and len(rest) >= MIN_NATIONAL_DIGITS) else rest
    elif cc and MIN_NATIONAL_DIGITS <= len(digits) <= 10:
        # Bare national number (no trunk zero) — 10 digits is the longest
        # national significant number we treat as local, and anything under
        # MIN_NATIONAL_DIGITS is junk that must not be dressed up as a real
        # number by prefixing the country code.
        digits = cc + digits

    return digits if len(digits) >= 8 else ""


def detect_language(text) -> str:
    """"ar" if the text contains Arabic script, "en" if it has letters at
    all, "" when there is nothing to judge (emoji-only, media captions)."""
    body = str(text or "")
    if not body.strip():
        return ""
    if _ARABIC_RE.search(body):
        return "ar"
    if re.search(r"[A-Za-z]", body):
        return "en"
    return ""


def _to_seconds(value):
    """Frappe Time fields come back as timedelta; Desk JSON defaults come back
    as "HH:MM:SS" strings. Normalize both to seconds-since-midnight."""
    if value is None or value == "":
        return None
    # datetime.timedelta
    total = getattr(value, "total_seconds", None)
    if callable(total):
        return int(total())
    # datetime.time
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value.hour * 3600 + value.minute * 60 + getattr(value, "second", 0)
    parts = str(value).strip().split(":")
    try:
        nums = [int(float(p)) for p in parts[:3]]
    except (TypeError, ValueError):
        return None
    while len(nums) < 3:
        nums.append(0)
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def is_business_hours(now=None, settings=None) -> bool:
    """True when `now` falls inside the configured WhatsApp business window.

    Separate from the ESS attendance windows on purpose (plan assumption 10):
    the inbox is staffed on its own schedule. `settings` is injectable so this
    stays unit-testable; it only needs `business_days`,
    `business_hours_start` and `business_hours_end`.
    """
    if settings is None:
        settings = get_inbox_settings()
    if now is None:
        from frappe.utils import now_datetime

        now = now_datetime()

    days_raw = (_g(settings, "business_days", "") or "").strip()
    if days_raw:
        allowed = {d.strip().lower()[:3] for d in days_raw.split(",") if d.strip()}
        allowed = {d for d in allowed if d in _DAY_TOKENS}
        if allowed and now.strftime("%a").lower()[:3] not in allowed:
            return False

    start = _to_seconds(_g(settings, "business_hours_start"))
    end = _to_seconds(_g(settings, "business_hours_end"))
    if start is None or end is None or start == end:
        # No window configured → treat the day as fully staffed rather than
        # spamming every customer with an out-of-hours auto-reply.
        return True

    current = now.hour * 3600 + now.minute * 60 + now.second
    if start < end:
        return start <= current < end
    # Overnight window (e.g. 18:00 → 02:00).
    return current >= start or current < end


def render_template_body(body, params) -> str:
    """Substitute Meta's positional {{1}}, {{2}}… placeholders."""
    text = str(body or "")
    values = []
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (TypeError, ValueError):
            params = None
    if isinstance(params, dict):
        values = list(params.values())
    elif isinstance(params, (list, tuple)):
        values = list(params)

    def _sub(match):
        try:
            idx = int(match.group(1)) - 1
        except (TypeError, ValueError):
            return match.group(0)
        if 0 <= idx < len(values):
            return "" if values[idx] is None else str(values[idx])
        return match.group(0)

    return re.sub(r"\{\{\s*(\d+)\s*\}\}", _sub, text)


def count_template_params(body) -> int:
    """How many distinct {{n}} placeholders a template body carries."""
    found = re.findall(r"\{\{\s*(\d+)\s*\}\}", str(body or ""))
    if not found:
        return 0
    try:
        return max(int(n) for n in found)
    except (TypeError, ValueError):
        return len(set(found))


def _looks_like_dict_repr(text) -> bool:
    """frappe_whatsapp's catch-all inbound branch stores
    `message[type].get(type)` — for several payload shapes that is a dict,
    and Frappe stringifies it into the HTML Editor field as a Python repr."""
    body = str(text or "").strip()
    return body.startswith("{") and ("':" in body or '":' in body)


def normalize_body(msg_doc, max_length: int = 1000) -> str:
    """The one display string for a `WhatsApp Message`, computed once at
    insert and stashed in `custom_body_text`.

    Without this the thread, the list preview, the push body and the search
    index would each have to re-derive the text — and three of them cannot
    (no template join, no button lookup) so they would show raw ids and
    `{'body': …}` reprs. Handles:

      * media (image/document/audio/video/sticker) → icon label + caption
      * interactive button replies → the button's title, not its Meta id
      * template sends → the template body with `body_param` substituted
      * everything else → HTML-stripped `message`
    """
    content_type = (_g(msg_doc, "content_type", "") or "").strip().lower()
    raw_message = _g(msg_doc, "message", "") or ""
    text = strip_html(raw_message)

    # ── media ────────────────────────────────────────────────────────────
    if content_type in MEDIA_LABELS and _g(msg_doc, "attach"):
        label = MEDIA_LABELS[content_type]
        return (f"{label} — {text}" if text else label)[:max_length]

    # ── interactive button / list replies ────────────────────────────────
    if content_type == "button" and text:
        return _button_title(msg_doc, text)[:max_length]

    # ── templates ────────────────────────────────────────────────────────
    template = _g(msg_doc, "template")
    use_template = _g(msg_doc, "use_template") or (
        (_g(msg_doc, "message_type", "") or "") == "Template"
    )
    if template and (use_template or not text or _looks_like_dict_repr(raw_message)):
        rendered = _render_from_template(template, _g(msg_doc, "body_param"))
        if rendered:
            return rendered[:max_length]

    if _looks_like_dict_repr(raw_message):
        # Unknown payload shape stored verbatim — better a marker than a repr.
        return "[unsupported message]"

    if not text:
        if content_type in MEDIA_LABELS:
            return MEDIA_LABELS[content_type]
        return ""

    return text[:max_length]


# ── frappe-backed lookups (never called at import time) ──────────────────────

def _default_country_code() -> str:
    try:
        settings = get_inbox_settings()
        return re.sub(r"\D", "", str(_g(settings, "default_country_code", "") or ""))
    except Exception:
        return ""


def get_inbox_settings():
    """The `WhatsApp Inbox Settings` singleton, cached for this request.

    The inbound hook consults it five or six times per message; without the
    cache every one of those is a fresh Singles round-trip.
    """
    cached = getattr(frappe.local, "_whatsapp_inbox_settings", None)
    if cached is not None:
        return cached
    try:
        settings = frappe.get_cached_doc("WhatsApp Inbox Settings")
    except Exception:
        settings = frappe._dict({})
    try:
        frappe.local._whatsapp_inbox_settings = settings
    except Exception:
        pass
    return settings


def clear_settings_cache():
    try:
        frappe.local._whatsapp_inbox_settings = None
    except Exception:
        pass


def inbox_roles():
    """Roles that grant access to the shared inbox."""
    raw = _g(get_inbox_settings(), "agent_roles", "") or "WhatsApp Agent,WhatsApp Manager"
    roles = [r.strip() for r in str(raw).split(",") if r.strip()]
    return roles or ["WhatsApp Agent", "WhatsApp Manager"]


def inbox_users():
    """Enabled Users holding any inbox role. Deduped, Administrator excluded."""
    from opportunity_management.opportunity_management.business_hooks import _users_with_role

    users = []
    seen = set()
    for role in inbox_roles():
        for email in _users_with_role(role):
            if email and email not in seen:
                seen.add(email)
                users.append(email)
    return users


def _button_title(msg_doc, fallback_id: str) -> str:
    """Map an interactive button-reply id back to the label the customer saw.

    Meta sends back the *id* of the tapped button; for template quick replies
    that id is the button's positional index, so we resolve it through the
    template the customer was replying to.
    """
    try:
        reply_to = _g(msg_doc, "reply_to_message_id")
        if not reply_to:
            return fallback_id
        template = frappe.db.get_value(
            "WhatsApp Message", {"message_id": reply_to}, "template"
        )
        if not template:
            return fallback_id
        buttons = frappe.get_all(
            "WhatsApp Button",
            filters={"parent": template, "parenttype": "WhatsApp Templates"},
            fields=["button_label", "idx"],
            order_by="idx asc",
        )
        if not buttons:
            return fallback_id
        raw = str(fallback_id).strip()
        if raw.isdigit():
            idx = int(raw)
            # Meta indexes template buttons from 0; Frappe child `idx` from 1.
            for offset in (idx, idx + 1):
                for row in buttons:
                    if row.get("idx") == offset:
                        return row.get("button_label") or fallback_id
        for row in buttons:
            if (row.get("button_label") or "").strip().lower() == raw.lower():
                return row.get("button_label")
    except Exception:
        pass
    return fallback_id


def _render_from_template(template_name, body_param) -> str:
    try:
        body = frappe.db.get_value("WhatsApp Templates", template_name, "template")
        if not body:
            return ""
        return strip_html(render_template_body(body, body_param))
    except Exception:
        return ""


def setting(field, default=None):
    """One Inbox Settings field, with a default for empty/unset.

    Lives here rather than in `whatsapp_hooks` because `whatsapp_jobs` needs
    it too and the two must not import each other.
    """
    value = get_inbox_settings().get(field)
    return default if value in (None, "") else value

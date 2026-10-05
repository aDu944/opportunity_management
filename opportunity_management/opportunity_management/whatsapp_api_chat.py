"""
Round-3 thread / conversation endpoints of the WhatsApp inbox API: the
typing indicator, search in a chat, the page around a timestamp, the media
gallery, blocking and per-user pin / mute.

Re-exported by `whatsapp_api.py`, which is the path clients call.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from opportunity_management.opportunity_management import whatsapp_chat_state as CS
from opportunity_management.opportunity_management import whatsapp_hooks
from opportunity_management.opportunity_management import whatsapp_payloads as P
from opportunity_management.opportunity_management import whatsapp_reactions as R
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _get_conv,
    _is_manager,
    _note,
    _paging,
    _require_inbox_access,
    MetaSendError,
)
from opportunity_management.opportunity_management.whatsapp_identity import display_label
from opportunity_management.opportunity_management.whatsapp_meta import meta_request
from opportunity_management.opportunity_management.whatsapp_utils import setting

MSG = "WhatsApp Message"
NOTE = "WhatsApp Internal Note"
TYPING_THROTTLE_SECONDS = 20
MIN_SEARCH_CHARS = 2
MAX_SEARCH_RESULTS = 100
MEDIA_KINDS = {"media": ["image", "video"], "docs": ["document"], "audio": ["audio"]}


def _row_for_caller(conv):
    """ConvRow — `conv_row` resolves the caller's own pin / mute flags."""
    return S.conv_row(conv)


# ── typing ───────────────────────────────────────────────────────────────────

@frappe.whitelist()
def typing(conversation):
    """Show "typing…" to the customer (and, Meta couples the two, mark their
    last message read). Never raises past the access check; never writes a
    note; at most one Meta call per conversation per 20 s."""
    _require_inbox_access()
    try:
        if not cint(setting("enable_typing_indicator", 0)):
            return {"ok": False}
        conv = _get_conv(conversation)
        if cint(conv.get("is_blocked")) or not conv.window_open():
            return {"ok": False}
        cache = frappe.cache()
        key = f"whatsapp_typing:{conv.name}"
        if cache.get_value(key):
            return {"ok": False}
        wamid = frappe.db.get_value(
            MSG,
            {"custom_conversation": conv.name, "type": "Incoming", "message_id": ["is", "set"]},
            "message_id",
            order_by="creation desc",
        )
        if not wamid:
            return {"ok": False}
        cache.set_value(key, 1, expires_in_sec=TYPING_THROTTLE_SECONDS)
        meta_request(conv.whatsapp_account, "messages", P.typing_body(wamid))
        return {"ok": True}
    except Exception:
        frappe.clear_messages()
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: typing indicator failed")
        return {"ok": False}


# ── search & around ──────────────────────────────────────────────────────────

def _like(query):
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


@frappe.whitelist()
def search_messages(conversation, query, limit=30):
    """Messages of one thread whose display text contains `query`, newest
    first. The wildcards live in the parameter — no literal % in the SQL."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    query = (query or "").strip()
    if len(query) < MIN_SEARCH_CHARS:
        frappe.throw(_("Type at least {0} characters to search").format(MIN_SEARCH_CHARS))
    limit = max(1, min(cint(limit) or 30, MAX_SEARCH_RESULTS))
    rows = frappe.db.sql(
        """SELECT name, creation, custom_body_text, type, custom_sent_by
           FROM `tabWhatsApp Message`
           WHERE custom_conversation = %(conv)s
             AND COALESCE(content_type, '') != 'reaction'
             AND custom_body_text LIKE %(q)s
           ORDER BY creation DESC
           LIMIT %(limit)s""",
        {"conv": conv.name, "q": _like(query), "limit": limit},
        as_dict=True,
    )
    names = S._full_names([r.custom_sent_by for r in rows])
    customer = display_label(conv.display_name, conv.phone, conv.get("wa_username"), _("WhatsApp user"))
    items = []
    for r in rows:
        incoming = r.type == "Incoming"
        items.append(
            {
                "id": r.name,
                "creation": S._iso(r.creation),
                "text": r.custom_body_text or "",
                "direction": "in" if incoming else "out",
                "sender_name": customer if incoming
                else (names.get(r.custom_sent_by) or r.custom_sent_by or ""),
            }
        )
    return {"items": items}


def messages_around(conversation, around, limit):
    """`get_messages(around=…)`: half the page at/before `around`, half after.
    `has_more` = older rows exist, `has_newer` = newer rows exist."""
    from opportunity_management.opportunity_management.whatsapp_api_messages import (
        NOTE_FIELDS,
        message_fields,
    )

    older_n, newer_n = P.around_split(limit)
    base = {"custom_conversation": conversation, "content_type": ["!=", R.REACTION]}

    def fetch(op, order, n):
        msgs = frappe.get_all(
            MSG, filters=dict(base, creation=[op, around]), fields=message_fields(),
            order_by=order, limit_page_length=n + 1,
        )
        notes = frappe.get_all(
            NOTE, filters={"conversation": conversation, "creation": [op, around]},
            fields=NOTE_FIELDS, order_by=order, limit_page_length=n + 1,
        )
        return msgs, notes

    old_m, old_n = fetch("<=", "creation desc", older_n)
    new_m, new_n = fetch(">", "creation asc", newer_n)
    older = S.thread_items(old_m[:older_n], old_n[:older_n])[-older_n:]
    newer = S.thread_items(new_m[:newer_n], new_n[:newer_n])[:newer_n]
    items = older + newer
    R.attach_reactions(items, conversation)
    return {
        "items": items,
        "has_more": len(old_m) > older_n or len(old_n) > older_n,
        "has_newer": len(new_m) > newer_n or len(new_n) > newer_n,
        "reaction_updates": [],
    }


# ── media gallery ────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_conversation_media(conversation, kind="media", limit_start=0, limit_page_length=30):
    """Attachments of one thread, newest first: media (photos, videos,
    stickers) | docs | audio."""
    from opportunity_management.opportunity_management.whatsapp_api_messages import message_fields

    _require_inbox_access()
    conv = _get_conv(conversation)
    if kind not in MEDIA_KINDS:
        frappe.throw(_("kind must be one of: {0}").format(", ".join(MEDIA_KINDS)))
    start, length = _paging(limit_start, limit_page_length)
    rows = frappe.get_all(
        MSG,
        filters={
            "custom_conversation": conv.name,
            "content_type": ["in", MEDIA_KINDS[kind]],
            "attach": ["is", "set"],
        },
        fields=message_fields(),
        order_by="creation desc",
        limit_start=start,
        limit_page_length=length + 1,
    )
    items = S.thread_items(rows[:length], [])
    items.reverse()
    return {"items": items, "has_more": len(rows) > length}


# ── block ────────────────────────────────────────────────────────────────────

def _set_blocked(conversation, blocked):
    _require_inbox_access()
    if not _is_manager():
        frappe.throw(_("Only a WhatsApp Manager can block or unblock contacts"), frappe.PermissionError)
    conv = _get_conv(conversation)
    if bool(cint(conv.get("is_blocked"))) == blocked:
        return _row_for_caller(conv)
    try:
        meta_request(
            conv.whatsapp_account, "block_users", P.block_body(conv.phone),
            method="POST" if blocked else "DELETE",
        )
    except MetaSendError as exc:
        frappe.throw(
            _("WhatsApp could not {0} this contact: {1}").format(
                _("block") if blocked else _("unblock"), str(exc)[:300]
            ),
            exc=MetaSendError,
        )
    values = {"is_blocked": 1 if blocked else 0}
    if blocked and conv.status != "Resolved":
        values.update(
            {
                "status": "Resolved",
                "resolved_at": now_datetime(),
                "resolved_by": frappe.session.user,
                "awaiting_reply_since": None,
            }
        )
    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    text = _("Contact blocked by {0}") if blocked else _("Contact unblocked by {0}")
    _note(conv.name, text.format(frappe.session.user))
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return _row_for_caller(conv)


@frappe.whitelist()
def block_contact(conversation):
    """Manager only. Meta allows blocking only a customer who wrote in the
    last 24 h; blocking also resolves the thread."""
    return _set_blocked(conversation, True)


@frappe.whitelist()
def unblock_contact(conversation):
    return _set_blocked(conversation, False)


# ── pin / mute ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def set_chat_state(conversation, pinned=None, muted=None):
    """The caller's pin / mute of one thread; None leaves a flag unchanged."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    if pinned in ("", "null"):
        pinned = None
    if muted in ("", "null"):
        muted = None
    CS.set_state(conv.name, frappe.session.user, pinned=pinned, muted=muted)
    return _row_for_caller(conv)

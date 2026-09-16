"""
The single place where a WhatsApp Conversation / Message / Internal Note row
becomes the JSON shape mobile, Desk and the realtime payloads all consume.

It lives outside both `whatsapp_api.py` and `whatsapp_hooks.py` because both
emit the same two shapes — the API returns them and the hook broadcasts them
over `publish_realtime` — and a second copy would drift the moment a field is
added. ConvRow / ThreadItem are the contract in plan §1.7; nothing else may
hand-roll them.
"""

import mimetypes
import os

import frappe
from frappe.utils import get_datetime, now_datetime

from opportunity_management.opportunity_management.whatsapp_utils import (
    WINDOW_SECONDS,
    MEDIA_LABELS,
    _g,
    normalize_body,
    strip_html,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _iso(value):
    if not value:
        return None
    try:
        return get_datetime(value).isoformat(sep=" ")
    except Exception:
        return str(value)


def window_seconds_remaining(last_inbound_at, now=None) -> int:
    if not last_inbound_at:
        return 0
    try:
        last = get_datetime(last_inbound_at)
    except Exception:
        return 0
    current = get_datetime(now) if now else now_datetime()
    remaining = WINDOW_SECONDS - (current - last).total_seconds()
    return int(remaining) if remaining > 0 else 0


def _full_names(users):
    """Batch User → full_name so a 30-row list is one query, not thirty."""
    wanted = sorted({u for u in users if u})
    if not wanted:
        return {}
    rows = frappe.get_all(
        "User", filters={"name": ["in", wanted]}, fields=["name", "full_name"]
    )
    return {r["name"]: (r["full_name"] or r["name"]) for r in rows}


def _tags_for(conversations):
    """{conversation: [{tag, color}]} for a page of conversations."""
    wanted = sorted({c for c in conversations if c})
    if not wanted:
        return {}
    rows = frappe.get_all(
        "WhatsApp Conversation Tag",
        filters={"parent": ["in", wanted], "parenttype": "WhatsApp Conversation"},
        fields=["parent", "tag"],
        order_by="idx asc",
        limit_page_length=0,
    )
    colors = {}
    tag_names = sorted({r["tag"] for r in rows if r.get("tag")})
    if tag_names:
        colors = {
            r["name"]: r.get("color")
            for r in frappe.get_all(
                "WhatsApp Tag",
                filters={"name": ["in", tag_names]},
                fields=["name", "color"],
            )
        }
    out = {}
    for row in rows:
        out.setdefault(row["parent"], []).append(
            {"tag": row["tag"], "color": colors.get(row["tag"]) or ""}
        )
    return out


def _guess_mime(file_url):
    if not file_url:
        return ""
    guessed = mimetypes.guess_type(os.path.basename(str(file_url).split("?")[0]))[0]
    return guessed or ""


# ── ConvRow ──────────────────────────────────────────────────────────────────

def conv_row(conv, tags=None, assignee_name=None, now=None):
    """Serialize one conversation. `tags` / `assignee_name` are injectable so
    `conv_rows()` can resolve a whole page in two queries."""
    if isinstance(conv, str):
        conv = frappe.get_doc("WhatsApp Conversation", conv)

    name = _g(conv, "name")
    assigned_to = _g(conv, "assigned_to") or None
    if tags is None:
        tags = _tags_for([name]).get(name, [])
    if assignee_name is None and assigned_to:
        assignee_name = _full_names([assigned_to]).get(assigned_to, assigned_to)

    return {
        "name": name,
        "phone": _g(conv, "phone", ""),
        "display_name": _g(conv, "display_name", "") or _g(conv, "phone", ""),
        "whatsapp_account": _g(conv, "whatsapp_account", "") or "",
        "status": _g(conv, "status", "Open"),
        "assigned_to": assigned_to,
        "assigned_to_name": assignee_name or "",
        "tags": tags or [],
        "last_message_at": _iso(_g(conv, "last_message_at")),
        "last_inbound_at": _iso(_g(conv, "last_inbound_at")),
        "last_message_preview": _g(conv, "last_message_preview", "") or "",
        "last_message_direction": _g(conv, "last_message_direction", "") or "",
        "unread_count": int(_g(conv, "unread_count", 0) or 0),
        "window_open": window_seconds_remaining(_g(conv, "last_inbound_at"), now=now) > 0,
        "window_seconds_remaining": window_seconds_remaining(
            _g(conv, "last_inbound_at"), now=now
        ),
        "contact": _g(conv, "contact") or None,
        "lead": _g(conv, "lead") or None,
        "customer": _g(conv, "customer") or None,
        "opportunity": _g(conv, "opportunity") or None,
        "customer_language": _g(conv, "customer_language", "") or "",
        "notes_count": int(_g(conv, "notes_count", 0) or 0),
    }


def conv_rows(rows):
    """Bulk ConvRow for a result page — two extra queries total."""
    rows = list(rows or [])
    if not rows:
        return []
    names = [_g(r, "name") for r in rows]
    tag_map = _tags_for(names)
    name_map = _full_names([_g(r, "assigned_to") for r in rows])
    now = now_datetime()
    return [
        conv_row(
            r,
            tags=tag_map.get(_g(r, "name"), []),
            assignee_name=name_map.get(_g(r, "assigned_to"), ""),
            now=now,
        )
        for r in rows
    ]


# ── ThreadItem ───────────────────────────────────────────────────────────────

_THREAD_ITEM_BLANK = {
    "kind": "message",
    "direction": "",
    "text": "",
    "content_type": "",
    "media_url": None,
    "media_mime": "",
    "media_private": 0,
    "caption": "",
    "status": "",
    "message_id": None,
    "reply_to_message_id": None,
    "reply_to_text": "",
    "sender_user": None,
    "sender_name": "",
    "is_auto": 0,
    "is_template": 0,
    "template_name": "",
    "note_type": "",
    "author": None,
    "author_name": "",
    "reaction": "",
    "read": 1,
}


def message_item(row, reply_texts=None, sender_names=None):
    """Serialize a `WhatsApp Message` row (dict or Document) as a ThreadItem."""
    item = dict(_THREAD_ITEM_BLANK)
    direction = "in" if (_g(row, "type", "") or "") == "Incoming" else "out"
    attach = _g(row, "attach") or None
    content_type = (_g(row, "content_type", "") or "").lower()
    text = _g(row, "custom_body_text", "") or ""
    if not text:
        text = normalize_body(row)

    sent_by = _g(row, "custom_sent_by") or None
    reply_to = _g(row, "reply_to_message_id") or None

    item.update(
        {
            "id": _g(row, "name"),
            "kind": "message",
            "direction": direction,
            "creation": _iso(_g(row, "creation")),
            "text": text,
            "content_type": content_type,
            "media_url": attach,
            "media_mime": _guess_mime(attach),
            "media_private": 1 if _g(row, "custom_media_private", 0) else 0,
            "caption": strip_html(_g(row, "message", "")) if attach else "",
            "status": _g(row, "status", "") or "",
            "message_id": _g(row, "message_id") or None,
            "reply_to_message_id": reply_to,
            "reply_to_text": (reply_texts or {}).get(reply_to, "") if reply_to else "",
            "sender_user": sent_by,
            "sender_name": (sender_names or {}).get(sent_by, "") if sent_by else "",
            "is_auto": 1 if _g(row, "custom_is_auto", 0) else 0,
            "is_template": 1 if (_g(row, "use_template", 0) or _g(row, "template")) else 0,
            "template_name": _g(row, "template", "") or "",
            "reaction": strip_html(_g(row, "message", "")) if content_type == "reaction" else "",
            "read": 1 if _g(row, "custom_read", 0) else 0,
        }
    )
    if content_type in MEDIA_LABELS and not item["text"]:
        item["text"] = MEDIA_LABELS[content_type]
    return item


def note_item(row, author_names=None):
    """Serialize a `WhatsApp Internal Note` row as a ThreadItem."""
    item = dict(_THREAD_ITEM_BLANK)
    author = _g(row, "author") or None
    attach = _g(row, "attach") or None
    item.update(
        {
            "id": _g(row, "name"),
            "kind": "note",
            "direction": "out",
            "creation": _iso(_g(row, "creation")),
            "text": _g(row, "text", "") or "",
            "note_type": _g(row, "note_type", "Note") or "Note",
            "author": author,
            "author_name": (author_names or {}).get(author, author or ""),
            "media_url": attach,
            "media_mime": _guess_mime(attach),
            "media_private": 1 if attach and "/private/" in str(attach) else 0,
        }
    )
    return item


def thread_item(row, kind="message", **kwargs):
    """Dispatch helper — `kind` is "message" or "note"."""
    if kind == "note":
        return note_item(row, author_names=kwargs.get("author_names"))
    return message_item(
        row,
        reply_texts=kwargs.get("reply_texts"),
        sender_names=kwargs.get("sender_names"),
    )


def thread_items(messages=None, notes=None):
    """Merge messages + notes into one chronological list, resolving the
    reply quotes and display names in bulk."""
    messages = list(messages or [])
    notes = list(notes or [])

    reply_ids = sorted({_g(m, "reply_to_message_id") for m in messages if _g(m, "reply_to_message_id")})
    reply_texts = {}
    if reply_ids:
        for r in frappe.get_all(
            "WhatsApp Message",
            filters={"message_id": ["in", reply_ids]},
            fields=["message_id", "custom_body_text", "message"],
            limit_page_length=0,
        ):
            reply_texts[r["message_id"]] = (
                r.get("custom_body_text") or strip_html(r.get("message"))
            )[:160]

    people = [_g(m, "custom_sent_by") for m in messages] + [_g(n, "author") for n in notes]
    names = _full_names(people)

    items = [message_item(m, reply_texts=reply_texts, sender_names=names) for m in messages]
    items += [note_item(n, author_names=names) for n in notes]
    items.sort(key=lambda i: (i.get("creation") or "", str(i.get("id") or "")))
    return items

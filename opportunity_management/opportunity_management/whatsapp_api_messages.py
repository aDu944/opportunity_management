"""
Thread-level endpoints of the WhatsApp inbox API: reading the merged
message + note thread, sending free text / media / templates, internal
notes, quick replies and the approved-template picker.

Re-exported by `whatsapp_api.py`, which is the path clients call. Nothing
routes here directly.
"""

import json
import mimetypes
import os

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from opportunity_management.opportunity_management import whatsapp_hooks
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_utils import (
    WINDOW_CLOSED_ERROR_CODE,
    count_template_params,
    get_inbox_settings,
    strip_html,
)
from opportunity_management.opportunity_management.whatsapp_api_common import (
    DEFAULT_THREAD_LIMIT,
    MAX_THREAD_LIMIT,
    _get_conv,
    _note,
    _require_assignee,
    _require_inbox_access,
    MetaSendError,
    WindowClosedError,
)


@frappe.whitelist()
def get_messages(conversation, before=None, after=None, limit=None):
    """One page of the merged message + note thread.

    `after` is what the mobile thread polls with every 5s while mounted —
    an indexed `custom_conversation, creation` range scan.
    """
    _require_inbox_access()
    _get_conv(conversation)
    limit = cint(limit) or DEFAULT_THREAD_LIMIT
    limit = max(1, min(limit, MAX_THREAD_LIMIT))

    msg_fields = [
        "name", "type", "creation", "message", "custom_body_text", "content_type",
        "attach", "custom_media_private", "status", "message_id",
        "reply_to_message_id", "custom_sent_by", "custom_is_auto", "custom_read",
        "use_template", "template",
    ]
    note_fields = ["name", "creation", "note_type", "text", "author", "attach"]

    msg_filters = {"custom_conversation": conversation}
    note_filters = {"conversation": conversation}

    if after:
        msg_filters["creation"] = [">", after]
        note_filters["creation"] = [">", after]
        order, reverse = "creation asc", False
    elif before:
        msg_filters["creation"] = ["<", before]
        note_filters["creation"] = ["<", before]
        order, reverse = "creation desc", True
    else:
        order, reverse = "creation desc", True

    messages = frappe.get_all(
        "WhatsApp Message",
        filters=msg_filters,
        fields=msg_fields,
        order_by=order,
        limit_page_length=limit + 1,
    )
    notes = frappe.get_all(
        "WhatsApp Internal Note",
        filters=note_filters,
        fields=note_fields,
        order_by=order,
        limit_page_length=limit + 1,
    )

    has_more = len(messages) > limit or len(notes) > limit
    items = S.thread_items(messages[:limit], notes[:limit])
    if reverse:
        # We fetched the newest `limit` rows; the client wants them oldest-first.
        items = items[-limit:] if len(items) > limit else items
    else:
        items = items[:limit]
    return {"items": items, "has_more": has_more}


# ── sending ──────────────────────────────────────────────────────────────────

_MIME_CONTENT_TYPE = (
    ("image/", "image"),
    ("video/", "video"),
    ("audio/", "audio"),
)


def _content_type_for(attachment):
    if not attachment:
        return "text"
    mime = mimetypes.guess_type(os.path.basename(str(attachment).split("?")[0]))[0] or ""
    for prefix, content_type in _MIME_CONTENT_TYPE:
        if mime.startswith(prefix):
            return content_type
    return "document"


def _auto_claim(conv):
    """Unassigned threads are claimed by whoever replies first — that is the
    whole point of the queue. Committed immediately so the failed-send
    rollback below cannot silently undo the claim."""
    if conv.assigned_to:
        _require_assignee(conv)
        return False
    now = now_datetime()
    values = {
        "assigned_to": frappe.session.user,
        "assigned_at": now,
        "assigned_by": frappe.session.user,
    }
    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value("WhatsApp Conversation", conv.name, values, update_modified=False)
    frappe.db.commit()
    return True


def _is_window_error(message) -> bool:
    text = str(message or "")
    return WINDOW_CLOSED_ERROR_CODE in text or "24 hour" in text.lower()


def _record_failed_send(conv_name, text, error):
    """The rollback path.

    frappe_whatsapp sends inside `before_insert`, so a Meta rejection throws
    and takes the whole transaction with it — there is no message row left to
    show the agent what happened. Roll back, then write a Failed Send note in
    a fresh transaction so the thread carries the evidence.
    """
    frappe.db.rollback()
    try:
        _note(
            conv_name,
            _("Send failed: {0}\n\n{1}").format(str(error)[:500], (text or "")[:500]),
            note_type="Failed Send",
        )
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: failed-send note not written")


@frappe.whitelist()
def send_message(conversation, text=None, reply_to=None, attachment=None):
    """Free-text (or media) reply. Only valid inside the 24h window."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    _auto_claim(conv)

    text = (text or "").strip()
    if not text and not attachment:
        frappe.throw(_("Message text or an attachment is required"))

    if not conv.window_open():
        frappe.throw(
            _(
                "The 24-hour reply window for this conversation has closed. "
                "Send an approved template instead."
            ),
            exc=WindowClosedError,
        )

    content_type = _content_type_for(attachment)
    payload = {
        "doctype": "WhatsApp Message",
        "type": "Outgoing",
        "to": conv.phone,
        "content_type": content_type,
        "message": text,
        "attach": attachment or None,
        "whatsapp_account": conv.whatsapp_account,
        "custom_conversation": conv.name,
        "custom_sent_by": frappe.session.user,
        "custom_read": 1,
    }
    if reply_to:
        payload["is_reply"] = 1
        payload["reply_to_message_id"] = reply_to

    try:
        doc = frappe.get_doc(payload)
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
    except Exception as exc:
        _record_failed_send(conv.name, text, exc)
        if _is_window_error(exc):
            frappe.throw(
                _("The 24-hour reply window has closed. Send an approved template."),
                exc=WindowClosedError,
            )
        frappe.throw(_("WhatsApp rejected the message: {0}").format(str(exc)[:300]), exc=MetaSendError)

    return S.message_item(doc)


@frappe.whitelist()
def send_template(conversation, template, params=None, header_media=None):
    """Approved-template send — the only thing Meta accepts once the window
    has closed, so this path never checks `window_open`."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    _auto_claim(conv)

    if not template or not frappe.db.exists("WhatsApp Templates", template):
        frappe.throw(_("Template {0} not found").format(template))

    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (TypeError, ValueError):
            params = [params]
    values = list(params.values()) if isinstance(params, dict) else list(params or [])

    # frappe_whatsapp reads `body_param` as a MAPPING (`.values()`), so a bare
    # JSON list would blow up in its `send_template`. Store positionally-keyed
    # objects; dict order is preserved through json round-trips.
    body_param = json.dumps({str(i + 1): ("" if v is None else str(v)) for i, v in enumerate(values)})

    header_type = (frappe.db.get_value("WhatsApp Templates", template, "header_type") or "").upper()
    content_type = "text"
    if header_media:
        content_type = "image" if header_type == "IMAGE" else "document"

    payload = {
        "doctype": "WhatsApp Message",
        "type": "Outgoing",
        "to": conv.phone,
        "use_template": 1,
        "template": template,
        "body_param": body_param,
        "content_type": content_type,
        "attach": header_media or None,
        "whatsapp_account": conv.whatsapp_account,
        "custom_conversation": conv.name,
        "custom_sent_by": frappe.session.user,
        "custom_read": 1,
    }

    try:
        doc = frappe.get_doc(payload)
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
    except Exception as exc:
        _record_failed_send(conv.name, f"[template] {template}", exc)
        frappe.throw(
            _("WhatsApp rejected the template: {0}").format(str(exc)[:300]), exc=MetaSendError
        )

    return S.message_item(doc)

# ── notes & read state ───────────────────────────────────────────────────────

@frappe.whitelist()
def add_note(conversation, text, attach=None, mentions=None):
    _require_inbox_access()
    _get_conv(conversation)
    text = (text or "").strip()
    if not text and not attach:
        frappe.throw(_("Note text is required"))

    if isinstance(mentions, str):
        try:
            mentions = json.loads(mentions)
        except (TypeError, ValueError):
            mentions = [m.strip() for m in mentions.split(",") if m.strip()]
    mentions = [m for m in (mentions or []) if m]

    doc = _note(conversation, text, note_type="Note", attach=attach, mentions=mentions)

    if mentions:
        try:
            from opportunity_management.opportunity_management.business_hooks import _send_to_users

            conv = frappe.get_doc("WhatsApp Conversation", conversation)
            who = conv.display_name or conv.phone
            _send_to_users(
                mentions,
                "📝 ملاحظة واتساب • WhatsApp Note",
                f"{who}\n{text[:200]}",
                {
                    "type": "whatsapp_note",
                    "screen": "whatsapp",
                    "doctype": "WhatsApp Conversation",
                    "name": conversation,
                },
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: note mention push failed")

    try:
        conv = frappe.get_doc("WhatsApp Conversation", conversation)
        whatsapp_hooks.publish_inbox_event("message", conv, item=S.note_item(doc))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: note publish failed")

    return S.note_item(doc)


# ── quick replies & templates ────────────────────────────────────────────────

@frappe.whitelist()
def get_quick_replies():
    _require_inbox_access()
    rows = frappe.db.sql(
        """
        SELECT name, title, shortcut, text_en, text_ar, scope, attach, sort_order
        FROM `tabWhatsApp Quick Reply`
        WHERE is_active = 1
          AND (scope = 'Team' OR owner_user = %(me)s)
        ORDER BY sort_order ASC, title ASC
        """,
        {"me": frappe.session.user},
        as_dict=True,
    )
    return rows


@frappe.whitelist()
def render_quick_reply(name, conversation=None):
    """Placeholder substitution stays server-side so mobile and Desk cannot
    render `{{customer}}` differently."""
    _require_inbox_access()
    if not frappe.db.exists("WhatsApp Quick Reply", name):
        frappe.throw(_("Quick reply {0} not found").format(name))
    reply = frappe.get_doc("WhatsApp Quick Reply", name)

    lang = (get_inbox_settings().get("default_language") or "en").lower()
    customer = ""
    if conversation and frappe.db.exists("WhatsApp Conversation", conversation):
        conv = frappe.get_doc("WhatsApp Conversation", conversation)
        customer = conv.display_name or conv.phone or ""
        if conv.customer_language:
            lang = conv.customer_language.lower()

    text = (reply.text_ar if lang == "ar" else reply.text_en) or reply.text_en or reply.text_ar or ""
    agent = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
    text = text.replace("{{customer}}", customer).replace("{{agent}}", agent)
    return {"text": text, "attach": reply.attach or None}


@frappe.whitelist()
def get_templates():
    """Approved templates only — anything else is rejected by Meta at send
    time, and offering it in the picker just produces a failed send."""
    _require_inbox_access()
    default_template = get_inbox_settings().get("default_reengage_template") or ""
    rows = frappe.get_all(
        "WhatsApp Templates",
        fields=[
            "name", "template_name", "template", "language_code", "category",
            "status", "header_type", "actual_name",
        ],
        limit_page_length=0,
        order_by="template_name asc",
    )
    out = []
    for row in rows:
        if (row.get("status") or "").strip().upper() != "APPROVED":
            continue
        body = strip_html(row.get("template"))
        out.append(
            {
                "name": row["name"],
                "template_name": row.get("template_name") or row["name"],
                "body": body,
                "language_code": row.get("language_code") or "",
                "category": row.get("category") or "",
                "header_type": (row.get("header_type") or "").upper(),
                "param_count": count_template_params(row.get("template")),
                "default": 1 if row["name"] == default_template else 0,
            }
        )
    out.sort(key=lambda t: (-t["default"], t["template_name"].lower()))
    return out

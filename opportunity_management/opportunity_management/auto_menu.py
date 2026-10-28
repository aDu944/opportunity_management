"""
WhatsApp auto-response menu — the frappe side (decisions: auto_menu_pure).

Inline, inside the webhook (whatsapp_hooks.on_message_after_insert):
    claim_inbound(conv, doc)   does the menu own this inbound? Sets
                               `conv.flags.menu_hold` (no push, no team alert,
                               no awaiting_reply_since) and, for a new / idle
                               chat, `menu_state = lang` right away
    enqueue(conv, doc, claim)  the RQ job, after commit, short queue
    reply_kind(conv, kind)     the old welcome is off while the menu is on
    agent_took_over(conv)      values for an agent's own reply: menu done

Out of process:
    run_menu(conversation, message, start)   the job: lock, engine, effects
    resolve_due()                            */5 cron: Auto-resolve options

Inbox: list_select / scope_clauses (scope `menu`), info_block (customer pane).
Everything is inert until the migrate created the doctype + columns (`ready`)
and `enable_menu` is on with a root menu. Messenger is never touched.
"""

import json

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from opportunity_management.opportunity_management import auto_menu_pure as P
from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import whatsapp_payloads as WP
from opportunity_management.opportunity_management.whatsapp_identity import has_phone
from opportunity_management.opportunity_management.whatsapp_utils import (
    business_hours_label,
    detect_language,
    get_inbox_settings,
    is_business_hours,
    reply_language,
    strip_html,
)

CONV = "WhatsApp Conversation"
MENU = "WhatsApp Menu"
OPTION = "WhatsApp Menu Option"
JOB = "opportunity_management.opportunity_management.auto_menu.run_menu"
BOT = "Administrator"
OPTION_FIELDS = [
    "name", "parent", "idx", "digit", "title_en", "title_ar", "description_en", "description_ar",
    "action", "target_menu", "reply_en", "reply_ar", "attachment", "tag", "assign_group",
    "question_en", "question_ar", "short_form", "last_handler", "location_lat", "location_lng",
    "location_name", "location_address_en", "location_address_ar", "sort_order",
]


def ready() -> bool:
    try:
        return bool(frappe.db.table_exists(MENU) and frappe.db.has_column(CONV, "menu_state"))
    except Exception:
        return False


def root_menu(settings=None):
    settings = settings if settings is not None else get_inbox_settings()
    root = settings.get("root_menu")
    if not root and ready():
        root = frappe.db.get_value(MENU, {"is_root": 1}, "name")
    return root


def enabled(settings=None) -> bool:
    settings = settings if settings is not None else get_inbox_settings()
    return bool(cint(settings.get("enable_menu")) and ready() and root_menu(settings))


def _dt(value):
    return get_datetime(value) if value else None


# ── inline (webhook) ─────────────────────────────────────────────────────────

def claim_inbound(conv, doc):
    """{"start": 0|1} when the menu owns this inbound, else None. Never raises."""
    try:
        if not enabled() or IC.conv_channel(conv) != IC.WHATSAPP or cint(conv.get("is_blocked")):
            return None
        settings = get_inbox_settings()
        now = now_datetime()
        state = conv.get("menu_state")
        start = P.should_start(
            state, _dt(conv.get("last_inbound_at")), _dt(conv.get("last_message_at")),
            conv.get("assigned_to"), conv.get("status"), now,
            cint(settings.get("menu_idle_reset_hours") or 24),
        )
        if not P.owns(state, start):
            return None
        if start:
            # Claimed now, so a burst of messages gets one greeting, not one each.
            values = {"menu_state": P.LANG, "menu_started_at": now, "menu_completed_at": None,
                      "menu_path": "", "menu_retries": 0, "menu_form_json": None, "menu_auto_resolve_at": None}
            for field, value in values.items():
                conv.set(field, value)
            frappe.db.set_value(CONV, conv.name, values, update_modified=False)
        conv.flags.menu_hold = True
        return {"start": 1 if start else 0}
    except Exception:
        frappe.log_error(title="WhatsApp auto menu: claim failed", message=frappe.get_traceback())
        return None


def enqueue(conv, doc, claim):
    try:
        frappe.enqueue(JOB, queue="short", enqueue_after_commit=True, conversation=conv.name,
                       message=doc.name, start=cint((claim or {}).get("start")))
    except Exception:
        frappe.log_error(title="WhatsApp auto menu: enqueue failed", message=frappe.get_traceback())


def reply_kind(conv, kind):
    """The canned auto-reply kind minus the welcome while the menu is on (the
    menu greets); out-of-hours still answers messages the menu does not own."""
    try:
        if kind and IC.conv_channel(conv) == IC.WHATSAPP and enabled():
            return "+".join(k for k in kind.split("+") if k != "welcome")
    except Exception:
        frappe.log_error(title="WhatsApp auto menu: reply kind failed", message=frappe.get_traceback())
    return kind


def agent_took_over(conv) -> dict:
    """An agent's own (non-auto) reply ends the menu for this chat."""
    try:
        if conv.get("menu_state") and ready():
            return P.takeover_values(conv.get("menu_state"))
    except Exception:
        pass
    return {}


# ── the job ──────────────────────────────────────────────────────────────────

def run_menu(conversation, message, start=0):
    """RQ job: one inbound through the engine, under the conversation lock."""
    try:
        conv = frappe.get_doc(CONV, conversation, for_update=True)
        settings = get_inbox_settings()
        msg = frappe.db.get_value("WhatsApp Message", message, [
            "name", "content_type", "message", "reply_to_message_id", "custom_payload", "creation",
        ], as_dict=True)
        if not msg or not enabled(settings):
            return frappe.db.commit()
        kind = P.parse_state(conv.get("menu_state"))[0]
        if not cint(start):
            if kind not in P.ACTIVE:
                return frappe.db.commit()
            if kind in (P.LANG, P.MENU) and _newer_inbound(conv.name, msg):
                return frappe.db.commit()  # a burst: the latest message answers
        tree = load_tree(root_menu(settings))
        effects = P.next_step(_ctx(conv, settings, start), _inbound(msg), tree, engine_settings(settings))
        _apply(conv, effects, msg)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="WhatsApp auto menu: run failed",
                         message="{0}\n{1}".format(conversation, frappe.get_traceback()))


def _newer_inbound(conv_name, msg) -> bool:
    return bool(frappe.db.sql(
        """SELECT name FROM `tabWhatsApp Message`
           WHERE custom_conversation = %(c)s AND type = 'Incoming' AND creation > %(t)s
             AND content_type != 'reaction' LIMIT 1""",
        {"c": conv_name, "t": msg.creation},
    ))


def _json(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ctx(conv, settings, start):
    phone = conv.phone if has_phone(conv.phone) else ""
    return {
        "start": bool(cint(start)), "state": conv.get("menu_state"), "lang": conv.get("menu_language"),
        "fallback_lang": reply_language(conv.get("customer_language"), phone, settings),
        "path": conv.get("menu_path") or "", "form": _json(conv.get("menu_form_json")),
        "retries": cint(conv.get("menu_retries")), "last_prompt_row": conv.get("menu_last_prompt_row"),
        "last_prompt_id": conv.get("menu_last_prompt_id"), "phone": phone,
        "has_crm": bool(conv.get("lead") or conv.get("customer")),
    }


def _inbound(msg):
    content_type = (msg.content_type or "").lower()
    text = strip_html(msg.message or "")
    card = WP.load_payload(msg.custom_payload).get("kind") in WP.CARD_KINDS
    kind = "tap" if content_type == "button" else ("text" if content_type == "text" and not card else "media")
    reply_to = msg.reply_to_message_id or None
    row = frappe.db.get_value("WhatsApp Message", {"message_id": reply_to, "type": "Outgoing"}, "name") if reply_to else None
    return {"kind": kind, "text": text, "reply_to_id": reply_to, "reply_to_row": row,
            "lang": detect_language(text) if kind == "text" else ""}


def engine_settings(settings):
    from opportunity_management.opportunity_management.whatsapp_jobs import BUSINESS_HOURS_PLACEHOLDER

    hours = {lang: business_hours_label(settings, lang) for lang in ("ar", "en")}
    ooh = {lang: (settings.get("out_of_hours_text_" + lang) or "").strip().replace(BUSINESS_HOURS_PLACEHOLDER, hours[lang])
           for lang in ("ar", "en")}
    return {
        "reopen_keywords": P.split_keywords(settings.get("menu_reopen_keywords") or "menu,القائمة"),
        "language_keywords": P.split_keywords(settings.get("menu_language_keywords") or "lang,اللغة"),
        "max_retries": cint(settings.get("form_max_retries")) or 3,
        "auto_resolve_hours": cint(settings.get("auto_resolve_menu_hours")) or 24,
        "in_hours": is_business_hours(settings=settings), "hours_label": hours, "ooh_text": ooh,
    }


def load_tree(root):
    """{"root", "menus": {key: {...menu, "options": [...]}}} — every menu."""
    menus = {}
    for m in frappe.get_all(MENU, fields=["name", "title_en", "title_ar", "body_en", "body_ar",
                                          "button_en", "button_ar"]):
        menus[m.name] = dict(m, key=m.name, options=[])
    for o in frappe.get_all(OPTION, filters={"parenttype": MENU}, fields=OPTION_FIELDS, order_by="idx asc"):
        if o.parent in menus:
            menus[o.parent]["options"].append(dict(o, row=o.name))
    return {"root": root, "menus": menus}


# ── effects ──────────────────────────────────────────────────────────────────

def _send(conv, fields, note_text):
    from opportunity_management.opportunity_management.whatsapp_api_send import _insert

    return _insert(conv, dict(fields, custom_is_auto=1, custom_sent_by=None), note_text)


def _send_effect(conv, e):
    do = e["do"]
    if do == "send_text":
        return _send(conv, {"content_type": "text", "message": e["text"]}, e["text"])
    if do in ("send_list", "send_buttons"):
        if do == "send_list":
            rows = e["rows"]
            interactive = WP.interactive_list(e["body"], e["button"], e["section"], rows)
        else:
            rows = e["buttons"]
            interactive = WP.interactive_buttons(e["body"], rows)
        fields = {"content_type": "interactive", "message": e["body"], "buttons": frappe.as_json(rows),
                  "custom_payload": WP.dump_payload({"kind": "menu", "interactive": interactive})}
        return _send(conv, fields, e["body"] + "\n" + " / ".join(r["title"] for r in rows))
    if do == "send_location":
        card = WP.location_card(e["latitude"], e["longitude"], e.get("name"), e.get("address"))
        text = WP.location_text(card)
        return _send(conv, {"content_type": "location", "message": text,
                            "custom_payload": WP.dump_payload({"kind": "location", "location": card})}, text)
    if do == "send_attachment":
        from opportunity_management.opportunity_management.whatsapp_api_messages import _content_type_for
        from opportunity_management.opportunity_management.whatsapp_media import public_copy

        url = public_copy(e["url"], conv.name)
        return _send(conv, {"content_type": _content_type_for(url), "attach": url, "message": ""}, url)
    return None


def _apply(conv, effects, msg):
    now = now_datetime()
    values, sending = {}, True
    for e in effects:
        try:
            if e["do"].startswith("send_"):
                item = _send_effect(conv, e) if sending else None
                if item and e.get("prompt"):
                    values.update({"menu_last_prompt_row": item.get("id"),
                                   "menu_last_prompt_id": item.get("message_id") or None})
            elif e["do"] == "set_state":
                values.update(e["values"])
            elif e["do"] == "tag":
                add_tag(conv, e["tag"])
            elif e["do"] == "note":
                _note(conv, e["text"])
            elif e["do"] == "create_lead":
                _create_lead(conv, e["fields"])
            elif e["do"] == "auto_resolve_after":
                values["menu_auto_resolve_at"] = add_to_date(now, hours=e["hours"])
            elif e["do"] == "handoff":
                values.update(_handoff(conv, e, msg, now))
        except Exception:
            sending = sending and not e["do"].startswith("send_")  # Meta refused: stop talking
            frappe.log_error(title="WhatsApp auto menu: effect {0} failed".format(e.get("do")),
                             message="{0}\n{1}".format(conv.name, frappe.get_traceback()))
    if not values:
        return
    for field, value in list(values.items()):
        if value == P.NOW:
            values[field] = now
        elif isinstance(value, dict):
            values[field] = json.dumps(value, ensure_ascii=False)
    frappe.db.set_value(CONV, conv.name, values, update_modified=False)
    if "menu_state" in values:
        from opportunity_management.opportunity_management import whatsapp_hooks

        whatsapp_hooks.publish_inbox_event("conversation", frappe.get_doc(CONV, conv.name))


def add_tag(conv, tag):
    if not tag or not frappe.db.exists("WhatsApp Tag", tag):
        return
    filters = {"parent": conv.name, "parenttype": CONV, "parentfield": "tags"}
    if frappe.db.exists("WhatsApp Conversation Tag", dict(filters, tag=tag)):
        return
    # A child row straight in: saving the locked parent would write back the
    # stale last_message_* values our own sends just updated.
    idx = frappe.db.count("WhatsApp Conversation Tag", filters) + 1
    now = now_datetime()
    frappe.get_doc(dict(filters, doctype="WhatsApp Conversation Tag", tag=tag, idx=idx,
                        creation=now, modified=now, owner=BOT, modified_by=BOT)).db_insert()


def _note(conv, text):
    from opportunity_management.opportunity_management.whatsapp_api_common import _note as note

    note(conv.name, text, author=BOT)


def _create_lead(conv, fields):
    """A Lead from the form answers, linked to the chat (skipped when the chat
    already has a Lead or Customer)."""
    if conv.get("lead") or conv.get("customer"):
        return
    from opportunity_management.opportunity_management import opportunity_pure as OP
    from opportunity_management.opportunity_management import whatsapp_crm
    from opportunity_management.opportunity_management.whatsapp_api_crm import insert_lead_for_conversation

    lead = insert_lead_for_conversation(
        conv, lead_name=fields.get("lead_name"), company_name=fields.get("company_name"),
        email_id=fields.get("email_id"), source=OP.lead_source_for_channel(IC.conv_channel(conv)),
        extra={"custom_abr": OP.WA_ABR}, mobile_no=fields.get("mobile_no"), city=fields.get("city"),
    )
    whatsapp_crm.link_conversation_to_crm(conv, "Lead", lead.name)


def _last_handler(conv):
    user = conv.get("assigned_to")
    if not user:
        rows = frappe.db.sql(
            """SELECT custom_sent_by FROM `tabWhatsApp Message`
               WHERE custom_conversation = %(c)s AND type = 'Outgoing'
                 AND COALESCE(custom_sent_by, '') != '' AND COALESCE(custom_is_auto, 0) = 0
               ORDER BY creation DESC LIMIT 1""",
            {"c": conv.name},
        )
        user = rows[0][0] if rows else None
    return user if user and cint(frappe.db.get_value("User", user, "enabled")) else None


def _handoff(conv, e, msg, now):
    """Hand the finished chat to its group (or, for a follow-up, to whoever
    handled it last). The group's own push carries the request; without a
    group the normal inbound push runs. Returns conversation values."""
    from opportunity_management.opportunity_management import agent_groups as AG
    from opportunity_management.opportunity_management import whatsapp_hooks

    handler = _last_handler(conv) if e.get("last_handler") else None
    grouped = False
    if handler:
        values = {"assigned_to": handler, "assigned_at": now, "assigned_by": BOT}
        frappe.db.set_value(CONV, conv.name, values, update_modified=False)
        for field, value in values.items():
            conv.set(field, value)
        _note(conv, "Auto menu: follow-up assigned to {0} (last handler)".format(handler))
    elif e.get("group") and AG.ready():
        try:
            AG.assign_to_group(conv, e["group"], BOT)
            grouped = True
        except Exception:
            frappe.log_error(title="WhatsApp auto menu: group assignment failed",
                             message="{0} → {1}\n{2}".format(conv.name, e.get("group"), frappe.get_traceback()))
    stamp = {} if conv.get("awaiting_reply_since") else {"awaiting_reply_since": now}
    if not grouped:
        fresh = frappe.get_doc(CONV, conv.name)
        whatsapp_hooks._push_inbound(fresh, frappe.get_doc("WhatsApp Message", msg.name))
    return stamp


# ── sweep / inbox ────────────────────────────────────────────────────────────

def resolve_due():
    """*/5 cron: resolve chats whose Auto-resolve option's wait has passed
    with no inbound since; clear the stamp when the customer wrote again."""
    if not ready():
        return
    try:
        now = now_datetime()
        rows = frappe.db.sql(
            """SELECT name, status, menu_auto_resolve_at, last_inbound_at, menu_completed_at
               FROM `tabWhatsApp Conversation`
               WHERE menu_auto_resolve_at IS NOT NULL AND menu_auto_resolve_at <= %(now)s
               LIMIT 200""",
            {"now": now}, as_dict=True,
        )
        for r in rows:
            verdict = P.resolve_verdict(_dt(r.menu_auto_resolve_at), now, _dt(r.last_inbound_at),
                                        _dt(r.menu_completed_at))
            values = {"menu_auto_resolve_at": None}
            if verdict == "resolve" and r.status != "Resolved":
                values.update({"status": "Resolved", "resolved_at": now, "resolved_by": None,
                               "awaiting_reply_since": None})
            frappe.db.set_value(CONV, r.name, values, update_modified=False)
        if rows:
            frappe.db.commit()
    except Exception:
        frappe.log_error(title="WhatsApp auto menu: resolve sweep failed", message=frappe.get_traceback())


def list_select(alias) -> str:
    """Menu columns for the list query, with the trailing comma."""
    if not ready():
        return "NULL AS menu_state, NULL AS menu_path, NULL AS menu_language, "
    return "{0}.menu_state, {0}.menu_path, {0}.menu_language, ".format(alias)


def scope_clauses(params, is_manager):
    """`menu` scope (managers): chats stuck in the menu for over 24 hours."""
    if not (is_manager and ready()):
        return ["1 = 0"]
    params["menu_cutoff"] = add_to_date(now_datetime(), hours=-24)
    return ["c.status != 'Resolved'", "COALESCE(c.menu_state, '') NOT IN ('', 'done')",
            "c.menu_started_at < %(menu_cutoff)s"]


def info_block(conv):
    """`menu` block of get_customer_info, or None before the migrate."""
    if not ready():
        return None

    def iso(value):
        return get_datetime(value).isoformat(sep=" ") if value else None

    return {"state": conv.get("menu_state") or "", "path": conv.get("menu_path") or "",
            "language": conv.get("menu_language") or "", "form": _json(conv.get("menu_form_json")),
            "started_at": iso(conv.get("menu_started_at")), "completed_at": iso(conv.get("menu_completed_at"))}

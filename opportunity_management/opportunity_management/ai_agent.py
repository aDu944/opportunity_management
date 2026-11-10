"""
WhatsApp AI responder — the frappe glue (decisions: ai_agent_pure; API:
ai_agent_client; tools: ai_agent_tools).

    engine_values(conv)        ai_mode / ai_menus for auto_menu.engine_settings
    run_turn(conv, msg, e)     the `ai_turn` effect (auto_menu._apply): build
                               the request, call the model, run / record the
                               tools, write the WhatsApp AI Turn row. Shadow
                               publishes an `ai_draft` inbox event and returns
                               []; Live returns the effects for _apply to run
    link_sent(turn, item)      the Live reply's WhatsApp Message on its Turn
    info_block(conv)           `ai` block of get_customer_info
    grade_turn / list_ai_turns whitelisted (inbox access)

Inert until the migrate created the doctypes, `ai_mode` is Shadow / Live AND
site_config has `anthropic_api_key` (the only place the key lives).
"""

import json

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime

from opportunity_management.opportunity_management import ai_agent_client as C
from opportunity_management.opportunity_management import ai_agent_pure as P
from opportunity_management.opportunity_management import ai_agent_tools as TOOLS
from opportunity_management.opportunity_management import auto_menu_texts as T
from opportunity_management.opportunity_management import whatsapp_payloads as WP
from opportunity_management.opportunity_management.whatsapp_identity import has_phone

SETTINGS = "WhatsApp AI Settings"
TURN = "WhatsApp AI Turn"
CONV = "WhatsApp Conversation"
BUDGET_TITLE = "WhatsApp AI: monthly budget reached"
GRADES = ("Pending", "Correct", "Wrong fact", "Wrong department", "Over-promise", "Bad language",
          "Should hand off", "Unnecessary handoff")
TURN_FIELDS = ["name", "creation", "message", "source", "menu", "language", "model", "effort", "stop_reason",
               "draft", "sent_message", "tools_json", "input_tokens", "cache_read_tokens",
               "cache_write_tokens", "output_tokens", "cost_usd", "latency_ms", "error", "grade",
               "grade_notes", "graded_by", "graded_on"]


def ready() -> bool:
    try:
        return bool(frappe.db.table_exists(TURN) and frappe.db.exists("DocType", SETTINGS))
    except Exception:
        return False


def get_settings():
    return frappe.get_cached_doc(SETTINGS).as_dict() if ready() else {}


def api_key():
    return frappe.conf.get("anthropic_api_key") or None


def enabled(settings=None) -> bool:
    settings = settings if settings is not None else get_settings()
    return bool(ready() and (settings.get("ai_mode") or "Off") in ("Shadow", "Live") and api_key())


def month_start():
    return now_datetime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_cost() -> float:
    rows = frappe.db.sql(
        """SELECT COALESCE(SUM(cost_usd), 0) FROM `tabWhatsApp AI Turn`
           WHERE source IN ('Live', 'Shadow') AND creation >= %(start)s""",
        {"start": month_start()},
    )
    return flt(rows[0][0]) if rows else 0.0


def _budget_reached(cost, budget):
    """One Error Log a month when the budget stops the AI."""
    if frappe.db.exists("Error Log", {"method": BUDGET_TITLE, "creation": [">=", month_start()]}):
        return
    frappe.log_error(title=BUDGET_TITLE, message="This month's AI cost ${0:.2f} reached the budget ${1:.2f}: "
                     "the AI is off until next month or a higher WhatsApp AI Settings › Monthly Budget."
                     .format(cost, budget))


def _share_key(conv):
    return conv.phone if has_phone(conv.get("phone")) else conv.name


def engine_values(conv, settings=None) -> dict:
    """{"ai_mode": "off"|"shadow"|"live", "ai_menus": {...}} for one chat. Never raises."""
    off = {"ai_mode": P.OFF, "ai_menus": set()}
    try:
        s = settings if settings is not None else get_settings()
        if not enabled(s):
            return off
        cost = month_cost()
        mode = P.mode_for(s, _share_key(conv), None, cost)
        if mode == P.OFF and cost >= flt(s.get("monthly_budget_usd")):
            _budget_reached(cost, flt(s.get("monthly_budget_usd")))
        return {"ai_mode": mode, "ai_menus": P.split_menus(s.get("ai_menus"))}
    except Exception:
        frappe.log_error(title="WhatsApp AI: mode check failed", message=frappe.get_traceback())
        return off


# ── the request ──────────────────────────────────────────────────────────────

def _history_rows(conv_name, upto, limit):
    from opportunity_management.opportunity_management.whatsapp_utils import strip_html

    rows = frappe.db.sql(
        """SELECT type, content_type, message, custom_payload FROM `tabWhatsApp Message`
           WHERE custom_conversation = %(c)s AND creation <= %(t)s
           ORDER BY creation DESC LIMIT %(n)s""",
        {"c": conv_name, "t": upto, "n": max(cint(limit), 1) * 3}, as_dict=True,
    )
    out = []
    for r in reversed(rows):
        kind = WP.load_payload(r.custom_payload).get("kind")
        out.append({"type": r.type, "content_type": r.content_type, "text": strip_html(r.message or ""),
                    "card": kind if kind in WP.CARD_KINDS else ""})
    return out


def session_turns(conv) -> int:
    """Live AI replies sent since this menu session started."""
    filters = {"conversation": conv.name, "source": "Live", "sent_message": ["is", "set"]}
    if conv.get("menu_started_at"):
        filters["creation"] = [">=", conv.get("menu_started_at")]
    return frappe.db.count(TURN, filters)


def _crm_line(conv):
    if conv.get("customer"):
        return "Customer {0}".format(conv.get("customer"))
    if conv.get("lead"):
        status = frappe.db.get_value("Lead", conv.get("lead"), "status") or ""
        return "Lead {0}{1}".format(conv.get("lead"), " ({0})".format(status) if status else "")
    return "not linked yet (use lookup_customer)"


def _escape_group(s, inbox):
    from opportunity_management.opportunity_management import auto_menu as AM

    group = (s.get("escape_group") or "").strip()
    if group and frappe.db.exists("WhatsApp Agent Group", {"name": group, "is_active": 1}):
        return group
    return AM._escape_group(inbox)


def prepare(conv, upto, menu_key, lang, at, s, turns=None):
    """(request, state) for the model at `upto` (the inbound's creation)."""
    from opportunity_management.opportunity_management import auto_menu as AM
    from opportunity_management.opportunity_management.whatsapp_utils import (
        business_hours_label, get_inbox_settings, is_business_hours)

    inbox = get_inbox_settings()
    lang = P._lang(lang)
    turns = session_turns(conv) if turns is None else turns
    in_hours = is_business_hours(now=get_datetime(at), settings=inbox)
    title = frappe.db.get_value("WhatsApp Menu", menu_key, "title_" + lang) if menu_key else ""
    dynamic = {
        "customer": conv.get("display_name") or "", "crm": _crm_line(conv),
        "language": "English" if lang == "en" else "Arabic",
        "business_hours": "{0}; hours: {1}".format("open now" if in_hours else "closed now",
                                                   business_hours_label(inbox, "en")),
        "local_time": get_datetime(at).strftime("%A %d %B %Y, %H:%M"),
        "menu": "{0} ({1})".format(menu_key, title) if title else (menu_key or ""), "ai_replies": turns,
    }
    cfg = {"model": s.get("model") or P.DEFAULT_MODEL, "effort": s.get("effort") or "low",
           "max_output_tokens": cint(s.get("max_output_tokens")) or 800, "persona": s.get("persona_" + lang)}
    history = P.history_from_rows(_history_rows(conv.name, upto, cint(s.get("history_messages")) or 12),
                                  cint(s.get("history_messages")) or 12)
    request = P.build_request(cfg, s.get("knowledge_" + lang), history, dynamic, P.tool_specs())
    engine = AM.engine_settings(inbox)
    state = {"lang": lang, "turns": turns, "max_turns": cint(s.get("max_turns")) or 6,
             "escape_group": _escape_group(s, inbox), "first_reply": turns == 0,
             "disclosure": s.get("disclosure_" + lang) or "", "phone": TOOLS._phone(conv),
             "has_crm": bool(conv.get("lead") or conv.get("customer")), "in_hours": in_hours,
             "ooh_text": engine.get("ooh_text") or {}}
    return request, state


def caller(s):
    key, model = api_key(), s.get("model") or P.DEFAULT_MODEL
    effort, max_tokens = s.get("effort") or "low", cint(s.get("max_output_tokens")) or 800
    return lambda request: C.call(request, key, model, effort, max_tokens)


def record(values, base):
    """Insert one Turn row (committed); `base` wins over empty values."""
    row = dict(base)
    row.update({k: v for k, v in (values or {}).items() if v is not None})
    row["tools_json"] = json.dumps(row.get("tools_json") or [], ensure_ascii=False, default=str)
    doc = frappe.get_doc(dict(row, doctype=TURN))
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


# ── the effect ───────────────────────────────────────────────────────────────

def run_turn(conv, msg, e):
    """Effects for `_apply` (Live) or [] (Shadow). Never raises: a failure in
    Live returns the strict menu's own effects (`e["fallback"]`)."""
    live = e.get("mode") == "live"
    fallback = list(e.get("fallback") or []) if live else []
    try:
        s = get_settings()
        if not enabled(s):
            return fallback
        from opportunity_management.opportunity_management.whatsapp_utils import strip_html

        lang = P._lang(conv.get("menu_language") or e.get("lang"))
        request, state = prepare(conv, msg.creation, e.get("menu"), lang, now_datetime(), s)
        state["last_text"] = strip_html(msg.message or "")
        if live and P.at_turn_cap(state):
            return _live(P.decide(None, state), state, {}, fallback)
        result = P.converse(request, caller(s), lambda name, args: TOOLS.run_tool(conv, name, args, live))
        base = {"conversation": conv.name, "message": msg.name, "menu": e.get("menu"), "language": lang,
                "model": s.get("model") or P.DEFAULT_MODEL, "effort": s.get("effort") or "low"}
        if live:
            return _live(P.decide(result, state), state, base, fallback)
        values = P.shadow_record(result)
        name = record(values, dict(base, source="Shadow"))
        if values.get("draft"):
            from opportunity_management.opportunity_management import whatsapp_hooks

            tools = [{"name": t["name"], "input": t.get("input") or {}} for t in values["tools_json"]]
            whatsapp_hooks.publish_inbox_event("ai_draft", frappe.get_doc(CONV, conv.name),
                                               extra={"turn": name, "text": values["draft"], "tools": tools})
        return []
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="WhatsApp AI: turn failed", message="{0}\n{1}".format(conv.name, frappe.get_traceback()))
        return fallback


def _live(effects, state, base, fallback):
    turn = None
    for x in effects:
        if x["do"] == "record_turn":
            turn = record(x["values"], dict(base, source="Live"))
    out = []
    for x in effects:
        if x["do"] == "record_turn":
            continue
        if x["do"] == "fallback":
            if x.get("escape"):
                return P.handoff_effects(state, state.get("escape_group"), "The AI declined this message.",
                                         "refusal", texts=T.ESCAPE)
            return fallback
        out.append(dict(x, turn=turn) if x.get("ai_reply") and turn else x)
    return out


def link_sent(turn, item):
    if turn and item and item.get("id"):
        frappe.db.set_value(TURN, turn, "sent_message", item["id"], update_modified=False)


# ── inbox ────────────────────────────────────────────────────────────────────

def info_block(conv):
    """Latest Shadow / Live turn of the chat, or None."""
    if not ready():
        return None
    rows = frappe.get_all(TURN, filters={"conversation": conv.name, "source": ["in", ["Shadow", "Live"]]},
                          fields=["name", "draft", "source", "creation"], order_by="creation desc", limit=1)
    if not rows:
        return None
    r = rows[0]
    return {"turn": r.name, "text": r.draft or "", "source": r.source,
            "created": get_datetime(r.creation).isoformat(sep=" ")}


@frappe.whitelist()
def grade_turn(turn, grade, notes=None):
    from opportunity_management.opportunity_management.whatsapp_api_common import _get_conv, _require_inbox_access

    _require_inbox_access()
    if grade not in GRADES:
        frappe.throw("Unknown grade")
    conversation = frappe.db.get_value(TURN, turn, "conversation") if turn else None
    if not conversation:
        frappe.throw("Turn {0} not found".format(turn), frappe.DoesNotExistError)
    _get_conv(conversation)  # channel access
    values = {"grade": grade, "grade_notes": str(notes or "")[:2000] or None,
              "graded_by": frappe.session.user, "graded_on": now_datetime()}
    frappe.db.set_value(TURN, turn, values, update_modified=False)
    return dict(values, turn=turn, graded_on=values["graded_on"].isoformat(sep=" "))


@frappe.whitelist()
def list_ai_turns(conversation):
    from opportunity_management.opportunity_management.whatsapp_api_common import _get_conv, _require_inbox_access

    _require_inbox_access()
    conv = _get_conv(conversation)
    rows = frappe.get_all(TURN, filters={"conversation": conv.name}, fields=TURN_FIELDS,
                          order_by="creation desc", limit=100)
    for r in rows:
        try:
            r["tools_json"] = json.loads(r.get("tools_json") or "[]")
        except (TypeError, ValueError):
            r["tools_json"] = []
    return rows

"""
Offline evaluation of the WhatsApp AI responder on real chats.

    bench --site <site> execute \\
        opportunity_management.opportunity_management.ai_replay.run_replay \\
        --kwargs "{'limit': 20, 'dry_run': 0}"

Picks WhatsApp conversations (not blocked, >= 2 inbound text messages, not
replayed before). Every inbound text after the first is treated as free text
in an AI menu: the history is the REAL thread up to that message, the model
is called, and a WhatsApp AI Turn (source Replay) is written. Nothing is sent
and no tool writes anything. Stops at `replay_budget_usd` or `limit x 8`
turns. `dry_run=1` (the default) only counts turns and estimates the cost.
"""

import json

import frappe
from frappe.utils import cint, flt, get_datetime

from opportunity_management.opportunity_management import ai_agent as A
from opportunity_management.opportunity_management import ai_agent_pure as P
from opportunity_management.opportunity_management import ai_agent_tools as TOOLS

TURNS_PER_CONVERSATION = 8
DRY_OUTPUT_TOKENS = 300  # a short reply plus low-effort thinking


def _conversations(limit, since):
    where = ["COALESCE(NULLIF(c.channel, ''), 'WhatsApp') = 'WhatsApp'", "COALESCE(c.is_blocked, 0) = 0"]
    params = {"limit": limit}
    if since:
        where.append("c.last_message_at >= %(since)s")
        params["since"] = get_datetime(since)
    return frappe.db.sql_list(
        """SELECT c.name FROM `tabWhatsApp Conversation` c
           WHERE {0}
             AND NOT EXISTS (SELECT 1 FROM `tabWhatsApp AI Turn` t
                             WHERE t.conversation = c.name AND t.source = 'Replay')
             AND (SELECT COUNT(*) FROM `tabWhatsApp Message` m
                  WHERE m.custom_conversation = c.name AND m.type = 'Incoming'
                    AND m.content_type = 'text') >= 2
           ORDER BY c.last_message_at DESC LIMIT %(limit)s""".format(" AND ".join(where)),
        params,
    )


def _inbound_texts(conv_name):
    return frappe.db.sql(
        """SELECT name, message, creation FROM `tabWhatsApp Message`
           WHERE custom_conversation = %(c)s AND type = 'Incoming' AND content_type = 'text'
           ORDER BY creation ASC""",
        {"c": conv_name}, as_dict=True,
    )


def _dry_cost(request, model, warm):
    """Estimate one call: tools + system cached after the run's first call."""
    prefix = P.estimate_tokens(json.dumps(request["tools"], ensure_ascii=False)
                               + json.dumps(request["system"], ensure_ascii=False))
    rest = P.estimate_tokens(json.dumps(request["messages"], ensure_ascii=False))
    return P.estimate_cost(model, input_tokens=rest, output_tokens=DRY_OUTPUT_TOKENS,
                           cache_read_tokens=prefix if warm else 0, cache_write_tokens=0 if warm else prefix)


@frappe.whitelist()
def run_replay(limit=20, menus=None, since=None, dry_run=1):
    """{conversations, turns, cost_usd, stopped_by, dry_run}."""
    frappe.only_for("System Manager")
    from opportunity_management.opportunity_management.whatsapp_utils import detect_language

    limit, dry = max(cint(limit), 1), bool(cint(dry_run))
    s = A.get_settings()
    if not s:
        frappe.throw("WhatsApp AI Settings are missing: run bench migrate first")
    if not dry and not A.api_key():
        frappe.throw("anthropic_api_key is not set in site_config")
    keys = sorted(P.split_menus(menus) or P.split_menus(s.get("ai_menus"))) or [""]
    model = s.get("model") or P.DEFAULT_MODEL
    budget, max_turns = flt(s.get("replay_budget_usd")), limit * TURNS_PER_CONVERSATION
    call = A.caller(s)
    cost, turns, touched, stopped_by = 0.0, 0, 0, "done"

    for i, name in enumerate(_conversations(limit, since)):
        conv, key = frappe.get_doc("WhatsApp Conversation", name), keys[i % len(keys)]
        touched += 1
        for n, msg in enumerate(_inbound_texts(name)[1:]):
            if cost >= budget:
                stopped_by = "budget"
            elif turns >= max_turns:
                stopped_by = "turn_limit"
            if stopped_by != "done":
                break
            lang = conv.get("menu_language") or conv.get("customer_language") or detect_language(msg.message or "")
            request, _state = A.prepare(conv, msg.creation, key, lang, msg.creation, s, turns=n)
            turns += 1
            if dry:
                cost += _dry_cost(request, model, warm=turns > 1)
                continue
            result = P.converse(request, call, lambda tool, args: TOOLS.run_tool(conv, tool, args, False))
            values = P.shadow_record(result, source="Replay")
            A.record(values, {"conversation": name, "message": msg.name, "menu": key, "source": "Replay",
                              "language": P._lang(lang), "model": model, "effort": s.get("effort") or "low"})
            cost += flt(values.get("cost_usd"))
            if result.get("error"):
                stopped_by = "error: " + str(result["error"])[:200]
                break
        if stopped_by != "done":
            break
    return {"conversations": touched, "turns": turns, "cost_usd": round(cost, 4),
            "stopped_by": stopped_by, "dry_run": int(dry)}

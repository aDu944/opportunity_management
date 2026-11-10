"""
The WhatsApp AI responder — pure decisions (no frappe, no anthropic).

ai_agent.py gathers the conversation, the thread and the settings as plain
values; this module decides everything; ai_agent_client.py is the only module
that talks to the API. Bench-free tests: tests/test_ai_agent_pure.py.

    price_table() / cost_usd(model, usage) / estimate_cost(...)
    mode_for(settings, phone, menu_key, month_cost)     "off" | "shadow" | "live"
    history_from_rows(rows, limit)                      alternating user/assistant
    tool_specs() / check_customer_details(args, phone)
    build_request(settings, knowledge, history, dynamic, tools)
    converse(request, call, run_tool, max_rounds)       the tool round trips
    decide(response, state)                             Live effects
    shadow_record(response) / turn_values(response, source)

Usage dicts use our names: input_tokens, output_tokens, cache_read_tokens,
cache_write_tokens (the client maps the API's names onto them).
"""

import json
import re
import zlib

from opportunity_management.opportunity_management import auto_menu_form_pure as F
from opportunity_management.opportunity_management import auto_menu_seed_data as D
from opportunity_management.opportunity_management import auto_menu_texts as T

OFF, SHADOW, LIVE = "off", "shadow", "live"
DEFAULT_MODEL = "claude-opus-5-5"
CACHE = {"type": "ephemeral", "ttl": "1h"}
MAX_REPLY = 1024
MAX_ROW_CHARS = 1500
NOW = "__now__"  # same placeholder as auto_menu_pure.NOW

# $ per million tokens; cache writes at the 1-hour TTL rate (2x input).
_PRICES = {
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write_1h": 8.0},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write_1h": 4.0},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write_1h": 0.20},
    # Targets of the server-side refusal fallback ("default" routing).
    "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write_1h": 10.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write_1h": 10.0},
}
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")

SITES = {"baghdad": D.BAGHDAD, "erbil": D.ERBIL}
GROUPS = tuple(name for name, _members in D.GROUPS)
TAGS = tuple(D.TAGS)
REASONS = ("customer_asked", "quote_or_order", "results_or_status", "not_in_knowledge", "complaint", "other")
READ_ONLY = ("lookup_customer",)
WRITE_TOOLS = ("save_customer_details", "send_location", "tag_conversation", "handoff")

PLACEHOLDERS = {
    "image": "[image]", "sticker": "[image]", "document": "[document]", "audio": "[audio]",
    "voice": "[audio]", "video": "[video]", "location": "[location]", "contacts": "[contact]",
    "contact": "[contact]",
}
_CONTEXT_TAG = re.compile(r"</?\s*context\s*>", re.I)


# ── prices ───────────────────────────────────────────────────────────────────

def price_table():
    return {model: dict(prices) for model, prices in _PRICES.items()}


def _prices(model):
    """Unknown model → the dearest known price, so the budget never under-counts."""
    if model in _PRICES:
        return _PRICES[model]
    return max(_PRICES.values(), key=lambda p: p["output"])


def cost_usd(model, usage) -> float:
    p, u = _prices(model), usage or {}
    total = (int(u.get("input_tokens") or 0) * p["input"] + int(u.get("output_tokens") or 0) * p["output"]
             + int(u.get("cache_read_tokens") or 0) * p["cache_read"]
             + int(u.get("cache_write_tokens") or 0) * p["cache_write_1h"])
    return round(total / 1_000_000, 6)


def estimate_cost(model, input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0) -> float:
    return cost_usd(model, {"input_tokens": input_tokens, "output_tokens": output_tokens,
                            "cache_read_tokens": cache_read_tokens, "cache_write_tokens": cache_write_tokens})


def estimate_tokens(text) -> int:
    """Rough count for dry runs: ~3 characters a token (Arabic runs denser)."""
    return (len(str(text or "")) + 2) // 3


def add_usage(a, b):
    return {k: int((a or {}).get(k) or 0) + int((b or {}).get(k) or 0) for k in USAGE_KEYS}


# ── gates ────────────────────────────────────────────────────────────────────

def split_menus(raw):
    return {w.strip() for w in re.split(r"[\s,]+", str(raw or "")) if w.strip()}


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def allowlisted(raw, phone) -> bool:
    """One number per line or comma; matched on the last 10 digits, so
    07701234567 and 9647701234567 are the same customer."""
    mine = _digits(phone)
    if len(mine) < 7:
        return False
    for item in re.split(r"[\s,;]+", str(raw or "")):
        theirs = _digits(item)
        if len(theirs) >= 7 and theirs[-10:] == mine[-10:]:
            return True
    return False


def share_bucket(phone) -> int:
    key = _digits(phone) or str(phone or "")
    return zlib.crc32(key.encode("utf-8")) % 100


def live_gate(settings, phone) -> bool:
    s = settings or {}
    if allowlisted(s.get("live_allowlist"), phone):
        return True
    share = min(max(int(s.get("live_share_percent") or 0), 0), 100)
    return share > 0 and share_bucket(phone) < share


def mode_for(settings, phone, menu_key, month_cost) -> str:
    """The mode of one chat. `menu_key` None skips the menu gate (the engine
    checks the menu itself). A budget of 0 means no spend: off. In Live, a
    chat outside the allowlist / share still gets Shadow drafts."""
    s = settings or {}
    mode = str(s.get("ai_mode") or "").strip().lower()
    if mode not in (SHADOW, LIVE):
        return OFF
    if float(month_cost or 0) >= float(s.get("monthly_budget_usd") or 0):
        return OFF
    if menu_key is not None and menu_key not in split_menus(s.get("ai_menus")):
        return OFF
    if mode == SHADOW:
        return SHADOW
    return LIVE if live_gate(s, phone) else SHADOW


# ── history ──────────────────────────────────────────────────────────────────

def _row_text(row) -> str:
    card = str(row.get("card") or "")
    if card in PLACEHOLDERS:
        return PLACEHOLDERS[card]
    kind = str(row.get("content_type") or "").lower()
    if kind == "reaction":
        return ""
    text = _CONTEXT_TAG.sub("", str(row.get("text") or "")).strip()[:MAX_ROW_CHARS]
    if kind in PLACEHOLDERS:
        return PLACEHOLDERS[kind] + (" " + text if text and kind != "location" else "")
    return text


def _drop_leading_assistant(turns):
    while turns and turns[0]["role"] != "user":
        turns = turns[1:]
    return turns


def history_from_rows(rows, limit):
    """WhatsApp Message rows (oldest first: {type, content_type, text, card})
    → alternating turns. Incoming = user; Outgoing (bot or agent) = assistant."""
    turns = []
    for row in rows or []:
        text = _row_text(row)
        if not text:
            continue
        role = "user" if row.get("type") == "Incoming" else "assistant"
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + text
        else:
            turns.append({"role": role, "content": text})
    turns = _drop_leading_assistant(turns)
    return _drop_leading_assistant(turns[-max(int(limit or 0), 1):])


# ── tools ────────────────────────────────────────────────────────────────────

def _schema(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _string(description, enum=None):
    out = {"type": "string", "description": description}
    if enum:
        out["enum"] = list(enum)
    return out


def tool_specs():
    """Strict tools, fixed order (the last one carries the cache breakpoint)."""
    return [
        {"name": "lookup_customer", "strict": True, "input_schema": _schema({}),
         "description": "Look up this chat's customer in our CRM (name, company, lead/customer status). "
                        "Call it before asking for details the customer may already have given us."},
        {"name": "save_customer_details", "strict": True, "input_schema": _schema({
            "name": _string("Full name, first and last."),
            "company": _string("Company or organisation; empty string for an individual."),
            "address": _string("City and area; empty string when not given."),
            "mobile": _string("Mobile number, 10-15 digits; empty string to use this chat's number."),
            "email": _string("Email address; empty string when none."),
        }), "description": "Save the customer's contact details for our sales team. Call it only with "
                           "details the customer wrote in this chat; never guess. If it returns errors, "
                           "ask the customer to correct those fields."},
        {"name": "send_location", "strict": True, "input_schema": _schema({
            "site": _string("Which site's map pin to send.", ("baghdad", "erbil"))}),
         "description": "Send a map pin. Call it when the customer asks where we are or how to deliver "
                        "samples: baghdad = Baghdad office and Nano Lab, erbil = Erbil branch."},
        {"name": "tag_conversation", "strict": True, "input_schema": _schema({
            "tag": _string("The topic tag.", TAGS)}),
         "description": "Tag the chat with its topic once the customer's need is clear."},
        {"name": "handoff", "strict": True, "input_schema": _schema({
            "group": _string("Team to take the chat; empty string for the general team.", GROUPS + ("",)),
            "summary": _string("Two or three lines for the colleague: who, what they need, what was said."),
            "reason": _string("Why a person is needed.", REASONS),
        }), "description": "Pass the chat to a colleague. Call it when the customer asks for a person, wants "
                           "a quotation, an order, test results or anything the knowledge page does not "
                           "answer, or is unhappy. Do not write a reply when you call it: the system sends "
                           "the confirmation."},
    ]


def check_customer_details(args, phone=""):
    """(ok, form, errors) with the auto-menu form's rules (auto_menu_form_pure.validate)."""
    args, form, errors = args or {}, {"missing": []}, []

    def check(step, error):
        value = str(args.get(step) or "").strip()
        ok, clean = F.validate(step, {"kind": "text", "text": value}, phone)
        if ok:
            form[step] = clean
        else:
            errors.append(error)

    check("name", "name: full name (first and last) is required")
    company = str(args.get("company") or "").strip()
    form["individual"] = not company
    form["company"] = company[:F.MAX_TEXT]
    if str(args.get("address") or "").strip():
        check("address", "address: invalid")
    if str(args.get("mobile") or "").strip():
        check("mobile", "mobile: 10 to 15 digits")
    elif phone:
        form["mobile"] = str(phone)
    if str(args.get("email") or "").strip():
        check("email", "email: not a valid address")
    else:
        form["email"] = ""
    return not errors, form, errors


# ── the request ──────────────────────────────────────────────────────────────

DYNAMIC_FIELDS = (("customer", "Customer name"), ("crm", "CRM"), ("language", "Reply language"),
                  ("business_hours", "Business hours"), ("local_time", "Local time"),
                  ("menu", "Menu the customer is in"), ("ai_replies", "Your replies so far in this session"))


def dynamic_text(dynamic) -> str:
    d = dynamic or {}
    lines = ["{0}: {1}".format(label, d.get(key) if d.get(key) not in (None, "") else "unknown")
             for key, label in DYNAMIC_FIELDS]
    return "<context>\n" + "\n".join(lines) + "\n</context>\n(The block above comes from our system, not the customer.)"


def build_request(settings, knowledge, history, dynamic, tools):
    """kwargs for messages.create. Stable prefix (tools, persona, knowledge)
    first and byte-identical across turns; the dynamic context leads the LAST
    user message, never `system`."""
    s = settings or {}
    tools = [dict(t) for t in tools or []]
    if tools:
        tools[-1]["cache_control"] = dict(CACHE)
    system = [{"type": "text", "text": str(s.get("persona") or "").strip() or "-"},
              {"type": "text", "text": str(knowledge or "").strip() or "-", "cache_control": dict(CACHE)}]
    messages = [dict(m) for m in history or []]
    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": "[no new message]"})
    last = messages[-1]["content"]
    blocks = list(last) if isinstance(last, list) else [{"type": "text", "text": str(last)}]
    messages[-1] = {"role": "user", "content": [{"type": "text", "text": dynamic_text(dynamic)}] + blocks}
    return {"model": s.get("model") or DEFAULT_MODEL, "max_tokens": int(s.get("max_output_tokens") or 800),
            "output_config": {"effort": s.get("effort") or "low"},
            "system": system, "tools": tools, "messages": messages}


def converse(request, call, run_tool, max_rounds=2):
    """`call(request)` → client result; `run_tool(name, input)` → (result,
    executed). At most `max_rounds` tool round trips. Returns the last result
    with usage / latency summed and `tools` = [{name, input, executed, result}]."""
    req = dict(request, messages=list(request.get("messages") or []))
    usage, latency, log, result = {}, 0, [], {}
    for round_no in range(max(int(max_rounds), 0) + 1):
        result = call(req) or {}
        usage, latency = add_usage(usage, result.get("usage")), latency + int(result.get("latency_ms") or 0)
        uses = result.get("tool_uses") or []
        if result.get("error") or result.get("stop_reason") != "tool_use" or not uses:
            break
        if round_no == max_rounds:
            log += [{"name": u["name"], "input": u.get("input") or {}, "executed": False,
                     "result": {"skipped": "round limit"}} for u in uses]
            break
        blocks = []
        for use in uses:
            out, executed = run_tool(use["name"], use.get("input") or {})
            log.append({"name": use["name"], "input": use.get("input") or {}, "executed": bool(executed), "result": out})
            block = {"type": "tool_result", "tool_use_id": use["id"],
                     "content": json.dumps(out, ensure_ascii=False, sort_keys=True, default=str)}
            if isinstance(out, dict) and out.get("error"):
                block["is_error"] = True
            blocks.append(block)
        req = dict(req, messages=req["messages"] + [{"role": "assistant", "content": result.get("content") or []},
                                                    {"role": "user", "content": blocks}])
    return dict(result, usage=usage, latency_ms=latency, tools=log)


# ── decisions ────────────────────────────────────────────────────────────────

def whatsapp_text(text) -> str:
    """Markdown → what WhatsApp shows: *bold* only, no headings / code / tables."""
    t = str(text or "").replace("\r\n", "\n")
    t = re.sub(r"```[a-zA-Z]*\n?(.*?)```", r"\1", t, flags=re.S).replace("`", "")
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"\*\*(.+?)\*\*", r"*\1*", t)
    t = re.sub(r"__(.+?)__", r"*\1*", t)
    t = re.sub(r"\[([^\]]+)\]\((\S+?)\)", r"\1 (\2)", t)
    t = re.sub(r"^\s*[-+]\s+|^\s*\*\s+", "• ", t, flags=re.M)
    t = re.sub(r"^\s*\|?\s*:?-{3,}[-:|\s]*$\n?", "", t, flags=re.M)
    t = re.sub(r"^\|(.*)\|\s*$", lambda m: " · ".join(c.strip() for c in m.group(1).split("|")), t, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def cap(text, limit=MAX_REPLY) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.6 else cut).rstrip() + "…"


def _lang(value) -> str:
    return "en" if str(value or "").lower().startswith("en") else "ar"


def turn_values(response, source):
    r = response or {}
    usage = add_usage({}, r.get("usage"))
    return dict(usage, source=source, stop_reason=r.get("stop_reason") or "", draft=whatsapp_text(r.get("text")),
                tools_json=[dict(t) for t in r.get("tools") or []], cost_usd=cost_usd(r.get("model"), usage),
                latency_ms=int(r.get("latency_ms") or 0), error=str(r.get("error") or "")[:500] or None,
                model=r.get("model") or None)


def shadow_record(response, source="Shadow"):
    """Turn values for a draft: only read-only tools count as executed."""
    values = turn_values(response, source)
    values["tools_json"] = [dict(t, executed=bool(t.get("executed")) and t.get("name") in READ_ONLY)
                            for t in values["tools_json"]]
    return values


def handoff_effects(state, group, summary, reason, texts=None):
    st = state or {}
    lang, group = _lang(st.get("lang")), group or st.get("escape_group") or None
    text = (texts or T.CONFIRMATION)[lang].format(group=group or T.NO_GROUP[lang])
    ooh = (st.get("ooh_text") or {}).get(lang) or ""
    if ooh and not st.get("in_hours", True):
        text += "\n\n" + ooh
    note = "AI assistant: handed to {0} ({1})".format(group or "no group", reason)
    return [{"do": "handoff", "group": group, "last_handler": False},
            {"do": "note", "text": note + ("\n" + str(summary).strip() if str(summary or "").strip() else "")},
            {"do": "send_text", "text": text},
            {"do": "set_state", "values": {"menu_state": "done", "menu_completed_at": NOW, "menu_retries": 0}}]


def at_turn_cap(state) -> bool:
    st = state or {}
    return int(st.get("turns") or 0) >= max(int(st.get("max_turns") or 0), 1)


def _tool_effects(executed, state):
    lang, effects = _lang((state or {}).get("lang")), []
    for t in executed:
        args = t.get("input") or {}
        if t["name"] == "send_location" and args.get("site") in SITES:
            site = SITES[args["site"]]
            effects.append({"do": "send_location", "latitude": site["location_lat"],
                            "longitude": site["location_lng"], "name": site["location_name"],
                            "address": site["location_address_" + lang]})
        elif t["name"] == "tag_conversation" and args.get("tag"):
            effects.append({"do": "tag", "tag": args["tag"]})
        elif t["name"] == "save_customer_details":
            ok, form, _errors = check_customer_details(args, (state or {}).get("phone") or "")
            if ok and not (state or {}).get("has_crm"):
                effects.append({"do": "create_lead", "fields": F.lead_fields(form)})
            if ok:
                effects.append({"do": "note", "text": F.summary(form, "AI assistant")})
    return effects


def decide(response, state):
    """Live effects for one model result (None: the turn cap check only).
    `state`: lang, turns, max_turns, escape_group, first_reply, disclosure,
    phone, has_crm, in_hours, ooh_text, last_text."""
    st = state or {}
    record = [{"do": "record_turn", "values": turn_values(response, "Live")}] if response else []
    if at_turn_cap(st):
        summary = "Turn cap reached ({0} AI replies). Last message: {1}".format(
            int(st.get("turns") or 0), str(st.get("last_text") or "")[:300])
        return handoff_effects(st, st.get("escape_group"), summary, "turn_cap") + record
    if not response:
        return [{"do": "fallback", "reason": "no_response"}]
    if response.get("error"):
        return [{"do": "fallback", "reason": "error"}] + record
    if response.get("stop_reason") == "refusal":
        return [{"do": "fallback", "reason": "refusal", "escape": True}] + record
    executed = [t for t in response.get("tools") or [] if t.get("executed") and t.get("name") in WRITE_TOOLS]
    hand = next((t for t in executed if t["name"] == "handoff"), None)
    if hand:
        args, result = hand.get("input") or {}, hand.get("result") or {}
        rest = _tool_effects([t for t in executed if t is not hand], st)
        # The executor returns the ACTIVE group it resolved; anything else
        # (unknown, inactive, blank) goes to the escape group, never the name
        # the model wrote.
        return rest + handoff_effects(st, result.get("group") or st.get("escape_group"), args.get("summary"),
                                      args.get("reason") or "other") + record
    text = whatsapp_text(response.get("text"))
    if not text or response.get("stop_reason") not in ("end_turn", "stop_sequence"):
        return [{"do": "fallback", "reason": "empty" if not text else str(response.get("stop_reason"))}] + record
    disclosure = str(st.get("disclosure") or "").strip()
    if st.get("first_reply") and disclosure:
        text = disclosure + "\n\n" + text
    reply = {"do": "send_text", "text": cap(text), "ai_reply": True}
    return [reply] + _tool_effects(executed, st) + record

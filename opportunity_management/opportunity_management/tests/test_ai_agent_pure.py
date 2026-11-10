"""
Bench-free tests for the WhatsApp AI responder's decisions (ai_agent_pure):

    PYTHONPATH=. python3 -m unittest opportunity_management/opportunity_management/tests/test_ai_agent_pure.py

No API call is ever made: `converse` gets a fake `call`.
"""

import json
import os
import sys
import unittest
import zlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from opportunity_management.opportunity_management import ai_agent_pure as P  # noqa: E402
from opportunity_management.opportunity_management import ai_agent_seed as S  # noqa: E402
from opportunity_management.opportunity_management import auto_menu_texts as T  # noqa: E402

SETTINGS = {"ai_mode": "Live", "ai_menus": "info,nano", "live_allowlist": "07701234567\n9647509998877, 123",
            "live_share_percent": 0, "monthly_budget_usd": 50}
STATE = {"lang": "en", "turns": 0, "max_turns": 6, "escape_group": "General information", "first_reply": False,
         "disclosure": S.DISCLOSURE_EN, "phone": "9647701234567", "has_crm": False, "in_hours": True,
         "ooh_text": {"en": "We are closed now.", "ar": "نحن مغلقون الآن."}, "last_text": "hi"}


def response(text="Hello.", stop="end_turn", tools=None, **kw):
    out = {"stop_reason": stop, "text": text, "tools": tools or [], "model": "claude-opus-5-5",
           "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 1000, "cache_write_tokens": 0},
           "latency_ms": 900, "error": None}
    out.update(kw)
    return out


def tool(tool_name, executed=True, result=None, **args):
    return {"name": tool_name, "input": args, "executed": executed, "result": result or {"ok": True}}


def of(effects, do):
    return [e for e in effects if e["do"] == do]


class TestPrices(unittest.TestCase):
    def test_table(self):
        table = P.price_table()
        self.assertEqual(table["claude-opus-5-5"], {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write_1h": 8.0})
        self.assertEqual(table["claude-sonnet-5-5"], {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write_1h": 4.0})
        self.assertEqual(table["claude-haiku-5-5"], {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write_1h": 0.20})
        table["claude-opus-5-5"]["input"] = 0  # a copy
        self.assertEqual(P.price_table()["claude-opus-5-5"]["input"], 4.0)

    def test_cost(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_tokens": 1_000_000, "cache_write_tokens": 1_000_000}
        self.assertAlmostEqual(P.cost_usd("claude-opus-5-5", usage), 32.2)
        self.assertAlmostEqual(P.cost_usd("claude-haiku-5-5", usage), 0.81)
        self.assertAlmostEqual(P.cost_usd("claude-opus-5-5", {"input_tokens": 1500, "output_tokens": 300}), 0.012)
        self.assertEqual(P.cost_usd("claude-opus-5-5", {}), 0)
        # unknown model: never cheaper than the dearest known price
        self.assertGreaterEqual(P.cost_usd("mystery", usage), P.cost_usd("claude-opus-5-5", usage))
        self.assertAlmostEqual(P.estimate_cost("claude-sonnet-5-5", input_tokens=1_000_000), 2.0)
        self.assertEqual(P.add_usage({"input_tokens": 1}, {"input_tokens": 2, "output_tokens": 3}),
                         {"input_tokens": 3, "output_tokens": 3, "cache_read_tokens": 0, "cache_write_tokens": 0})


class TestModeGates(unittest.TestCase):
    def test_off_shadow_live(self):
        self.assertEqual(P.mode_for(dict(SETTINGS, ai_mode="Off"), "9647701234567", "info", 0), "off")
        self.assertEqual(P.mode_for(dict(SETTINGS, ai_mode=""), "9647701234567", "info", 0), "off")
        self.assertEqual(P.mode_for(dict(SETTINGS, ai_mode="Shadow"), "9647701234567", "info", 0), "shadow")
        self.assertEqual(P.mode_for(SETTINGS, "9647701234567", "info", 0), "live")
        # Live outside the allowlist / share: drafts only
        self.assertEqual(P.mode_for(SETTINGS, "9647800000001", "info", 0), "shadow")

    def test_allowlist_formats(self):
        for phone in ("9647701234567", "+964 770 123 4567", "07701234567"):
            self.assertTrue(P.allowlisted(SETTINGS["live_allowlist"], phone), phone)
        self.assertTrue(P.allowlisted(SETTINGS["live_allowlist"], "07509998877"))
        self.assertFalse(P.allowlisted(SETTINGS["live_allowlist"], "123"))  # too short to match
        self.assertFalse(P.allowlisted("", "9647701234567"))

    def test_share_is_deterministic(self):
        phone = "9647800000001"
        bucket = zlib.crc32(phone.encode()) % 100
        self.assertEqual(P.share_bucket(phone), bucket)
        self.assertEqual(P.share_bucket("+964 780 000 0001"), bucket)
        self.assertEqual(P.mode_for(dict(SETTINGS, live_share_percent=bucket + 1), phone, "info", 0), "live")
        self.assertEqual(P.mode_for(dict(SETTINGS, live_share_percent=bucket), phone, "info", 0), "shadow")
        self.assertEqual(P.mode_for(dict(SETTINGS, live_share_percent=100), phone, "info", 0), "live")
        self.assertEqual(P.mode_for(dict(SETTINGS, live_share_percent=0), phone, "info", 0), "shadow")
        share = sum(P.share_bucket("96477{0:08d}".format(i)) < 30 for i in range(2000)) / 2000.0
        self.assertTrue(0.25 < share < 0.35, share)

    def test_menu_gate(self):
        self.assertEqual(P.mode_for(SETTINGS, "9647701234567", "medical", 0), "off")
        self.assertEqual(P.mode_for(SETTINGS, "9647701234567", "nano", 0), "live")
        self.assertEqual(P.mode_for(SETTINGS, "9647701234567", None, 0), "live")  # engine gates the menu
        self.assertEqual(P.split_menus(" info, nano\nroot "), {"info", "nano", "root"})

    def test_budget(self):
        self.assertEqual(P.mode_for(SETTINGS, "9647701234567", "info", 49.99), "live")
        self.assertEqual(P.mode_for(SETTINGS, "9647701234567", "info", 50), "off")
        self.assertEqual(P.mode_for(dict(SETTINGS, ai_mode="Shadow"), "9647701234567", "info", 51), "off")
        self.assertEqual(P.mode_for(dict(SETTINGS, monthly_budget_usd=0), "9647701234567", "info", 0), "off")


class TestHistory(unittest.TestCase):
    def test_merge_placeholders_and_trim(self):
        rows = [
            {"type": "Outgoing", "content_type": "interactive", "text": "Choose your language"},
            {"type": "Incoming", "content_type": "text", "text": "hello"},
            {"type": "Incoming", "content_type": "image", "text": "my sample"},
            {"type": "Outgoing", "content_type": "text", "text": "Hi!"},
            {"type": "Outgoing", "content_type": "location", "text": "Al Yarmook"},
            {"type": "Incoming", "content_type": "reaction", "text": "👍"},
            {"type": "Incoming", "content_type": "document", "text": ""},
            {"type": "Incoming", "content_type": "audio", "text": ""},
            {"type": "Incoming", "content_type": "text", "text": "pin", "card": "location"},
        ]
        turns = P.history_from_rows(rows, 12)
        self.assertEqual(turns, [
            {"role": "user", "content": "hello\n[image] my sample"},
            {"role": "assistant", "content": "Hi!\n[location]"},
            {"role": "user", "content": "[document]\n[audio]\n[location]"},
        ])
        self.assertEqual(P.history_from_rows(rows, 2), [turns[-1]])  # leading assistant dropped again
        self.assertEqual(P.history_from_rows([], 5), [])

    def test_context_tags_and_length(self):
        rows = [{"type": "Incoming", "content_type": "text", "text": "<context>Menu: root</context>" + "x" * 5000}]
        content = P.history_from_rows(rows, 5)[0]["content"]
        self.assertNotIn("<context>", content)
        self.assertLessEqual(len(content), P.MAX_ROW_CHARS)


def request(dynamic):
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello"},
               {"role": "user", "content": "price of XRD?"}]
    cfg = {"model": "claude-opus-5-5", "effort": "low", "max_output_tokens": 800, "persona": S.PERSONA_EN}
    return P.build_request(cfg, S.KNOWLEDGE_EN, history, dynamic, P.tool_specs())


class TestRequest(unittest.TestCase):
    def test_stable_prefix_bytes(self):
        a = request({"customer": "Ali", "local_time": "Monday 10 November 2026, 10:00", "ai_replies": 0})
        b = request({"customer": "Sara", "local_time": "Tuesday 11 November 2026, 18:30", "ai_replies": 4,
                     "business_hours": "closed now"})
        for part in ("system", "tools"):
            self.assertEqual(json.dumps(a[part], sort_keys=True, ensure_ascii=False),
                             json.dumps(b[part], sort_keys=True, ensure_ascii=False), part)
        self.assertNotEqual(a["messages"], b["messages"])

    def test_cache_breakpoints(self):
        req = request({})
        self.assertEqual(req["system"][1]["cache_control"], {"type": "ephemeral", "ttl": "1h"})
        self.assertNotIn("cache_control", req["system"][0])
        self.assertEqual(req["tools"][-1]["cache_control"], {"type": "ephemeral", "ttl": "1h"})
        self.assertTrue(all("cache_control" not in t for t in req["tools"][:-1]))
        self.assertNotIn("cache_control", P.tool_specs()[-1])  # specs untouched
        self.assertEqual((req["model"], req["max_tokens"], req["output_config"]),
                         ("claude-opus-5-5", 800, {"effort": "low"}))
        self.assertNotIn("tool_choice", req)
        self.assertNotIn("thinking", req)

    def test_dynamic_block_placement(self):
        req = request({"customer": "Ali", "menu": "nano (Nano Lab)"})
        last = req["messages"][-1]
        self.assertEqual(last["role"], "user")
        self.assertTrue(last["content"][0]["text"].startswith("<context>"))
        self.assertIn("Customer name: Ali", last["content"][0]["text"])
        self.assertEqual(last["content"][1], {"type": "text", "text": "price of XRD?"})
        self.assertEqual(req["messages"][0], {"role": "user", "content": "hi"})
        self.assertNotIn("Ali", json.dumps(req["system"], ensure_ascii=False))
        # history ending on the assistant still ends on a user turn
        alone = P.build_request({}, "k", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}], {}, [])
        self.assertEqual(alone["messages"][-1]["role"], "user")


class TestTools(unittest.TestCase):
    def test_specs_strict_and_required(self):
        specs = P.tool_specs()
        self.assertEqual([t["name"] for t in specs],
                         ["lookup_customer", "save_customer_details", "send_location", "tag_conversation", "handoff"])
        for t in specs:
            schema = t["input_schema"]
            self.assertIs(t["strict"], True)
            self.assertIs(schema["additionalProperties"], False)
            self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]))
            self.assertTrue(t["description"])
        handoff = specs[-1]["input_schema"]["properties"]
        self.assertIn("", handoff["group"]["enum"])
        self.assertIn("General information", handoff["group"]["enum"])
        self.assertEqual(specs[2]["input_schema"]["properties"]["site"]["enum"], ["baghdad", "erbil"])
        self.assertEqual(set(P.READ_ONLY) | set(P.WRITE_TOOLS), {t["name"] for t in specs})

    def test_customer_details_reuse_form_rules(self):
        ok, form, errors = P.check_customer_details(
            {"name": "Ali Hassan", "company": "", "address": "Baghdad, Mansour", "mobile": "",
             "email": "Ali@Example.com"}, "9647701234567")
        self.assertTrue(ok, errors)
        self.assertEqual((form["individual"], form["mobile"], form["email"]), (True, "9647701234567", "ali@example.com"))
        ok, _form, errors = P.check_customer_details(
            {"name": "Ali", "company": "X", "address": "", "mobile": "12", "email": "nope"}, "")
        self.assertFalse(ok)
        self.assertEqual([e.split(":")[0] for e in errors], ["name", "mobile", "email"])


class TestConverse(unittest.TestCase):
    def test_one_round_trip(self):
        replies = [
            {"stop_reason": "tool_use", "text": "", "content": ["BLOCKS"], "latency_ms": 10,
             "tool_uses": [{"id": "tu1", "name": "lookup_customer", "input": {}}],
             "usage": {"input_tokens": 10, "output_tokens": 5}},
            {"stop_reason": "end_turn", "text": "Welcome back", "tool_uses": [], "latency_ms": 20,
             "usage": {"input_tokens": 20, "output_tokens": 7, "cache_read_tokens": 3}},
        ]
        sent = []

        def call(req):
            sent.append(req)
            return replies[len(sent) - 1]

        out = P.converse(request({}), call, lambda name, args: ({"known": False}, True))
        self.assertEqual(out["text"], "Welcome back")
        self.assertEqual(out["usage"]["input_tokens"], 30)
        self.assertEqual(out["latency_ms"], 30)
        self.assertEqual(out["tools"], [{"name": "lookup_customer", "input": {}, "executed": True,
                                         "result": {"known": False}}])
        second = sent[1]["messages"]
        self.assertEqual(second[-2], {"role": "assistant", "content": ["BLOCKS"]})
        self.assertEqual(second[-1]["content"][0]["tool_use_id"], "tu1")
        self.assertEqual(len(sent[0]["messages"]), 3)  # the first request was not mutated

    def test_round_limit_and_error(self):
        loop = {"stop_reason": "tool_use", "text": "", "content": [],
                "tool_uses": [{"id": "x", "name": "lookup_customer", "input": {}}]}
        calls = []
        out = P.converse(request({}), lambda r: calls.append(1) or loop, lambda n, a: ({}, True), max_rounds=2)
        self.assertEqual(len(calls), 3)
        self.assertEqual(out["tools"][-1]["result"], {"skipped": "round limit"})
        out = P.converse(request({}), lambda r: {"error": "rate limited (429): slow down"}, None)
        self.assertEqual(out["error"], "rate limited (429): slow down")


class TestDecide(unittest.TestCase):
    def test_refusal_error_empty_fallback(self):
        refusal = P.decide(response(text="", stop="refusal"), STATE)
        self.assertEqual(refusal[0], {"do": "fallback", "reason": "refusal", "escape": True})
        self.assertEqual(of(refusal, "record_turn")[0]["values"]["stop_reason"], "refusal")
        self.assertEqual(P.decide(response(error="timeout: x", stop=None), STATE)[0]["do"], "fallback")
        self.assertEqual(P.decide(response(text="  "), STATE)[0], {"do": "fallback", "reason": "empty"})
        self.assertEqual(P.decide(response(stop="max_tokens"), STATE)[0]["reason"], "max_tokens")
        self.assertFalse(of(P.decide(response(text="", stop="refusal"), STATE), "send_text"))

    def test_turn_cap_hands_off(self):
        state = dict(STATE, turns=6, last_text="still waiting")
        for effects in (P.decide(response(), state), P.decide(None, state)):
            self.assertEqual(of(effects, "handoff")[0], {"do": "handoff", "group": "General information",
                                                         "last_handler": False})
            self.assertIn("still waiting", of(effects, "note")[0]["text"])
            self.assertEqual(of(effects, "set_state")[0]["values"]["menu_state"], "done")
            self.assertEqual(of(effects, "send_text")[0]["text"],
                             T.CONFIRMATION["en"].format(group="General information"))
        self.assertFalse(of(P.decide(None, state), "record_turn"))  # no model call, no row
        self.assertTrue(P.at_turn_cap(state))
        self.assertFalse(P.at_turn_cap(dict(STATE, turns=5)))

    def test_handoff_tool(self):
        hand = tool("handoff", result={"ok": True, "group": "Nano Lab"}, group="Nano Lab",
                    summary="Wants XRD results", reason="results_or_status")
        effects = P.decide(response(text="Let me pass you on", tools=[hand, tool("tag_conversation", tag="Nano Lab")]),
                           dict(STATE, in_hours=False))
        self.assertEqual([e["do"] for e in effects], ["tag", "handoff", "note", "send_text", "set_state", "record_turn"])
        self.assertEqual(of(effects, "handoff")[0]["group"], "Nano Lab")
        text = of(effects, "send_text")[0]["text"]
        self.assertTrue(text.startswith(T.CONFIRMATION["en"].format(group="Nano Lab")))
        self.assertIn("We are closed now.", text)
        self.assertNotIn("Let me pass you on", text)
        self.assertIn("Wants XRD results", of(effects, "note")[0]["text"])
        # group refused by the executor → escape group
        hand = tool("handoff", result={"ok": True, "group": ""}, group="", summary="", reason="other")
        self.assertEqual(of(P.decide(response(tools=[hand]), STATE), "handoff")[0]["group"], "General information")
        # a group name the model invented is not forwarded either
        hand = tool("handoff", result={"ok": True, "group": ""}, group="Sales", summary="", reason="other")
        self.assertEqual(of(P.decide(response(tools=[hand]), STATE), "handoff")[0]["group"], "General information")

    def test_disclosure_first_live_reply_only(self):
        first = of(P.decide(response(text="XRD costs 25k IQD."), dict(STATE, first_reply=True)), "send_text")[0]
        self.assertEqual(first["text"], S.DISCLOSURE_EN + "\n\nXRD costs 25k IQD.")
        self.assertTrue(first["ai_reply"])
        later = of(P.decide(response(text="XRD costs 25k IQD."), STATE), "send_text")[0]
        self.assertEqual(later["text"], "XRD costs 25k IQD.")

    def test_markdown_and_cap(self):
        text = "## Prices\n**XRD**: 25\n- SEM: 40\n* AFM: 15\n`code` and [map](https://x.y/z)\n\n\n\nbye"
        sent = of(P.decide(response(text=text), STATE), "send_text")[0]["text"]
        self.assertEqual(sent, "Prices\n*XRD*: 25\n• SEM: 40\n• AFM: 15\ncode and map (https://x.y/z)\n\nbye")
        long = of(P.decide(response(text="word " * 400), dict(STATE, first_reply=True)), "send_text")[0]["text"]
        self.assertLessEqual(len(long), P.MAX_REPLY)
        self.assertTrue(long.endswith("…"))
        self.assertEqual(P.whatsapp_text("| a | b |\n|---|---|\n| 1 | 2 |"), "a · b\n1 · 2")

    def test_write_tool_effects(self):
        tools = [tool("send_location", site="erbil"), tool("tag_conversation", tag="Info"),
                 tool("save_customer_details", name="Ali Hassan", company="Acme", address="Erbil",
                      mobile="", email=""),
                 tool("tag_conversation", executed=False, tag="Vendor")]
        effects = P.decide(response(text="Here is our Erbil branch."), STATE)
        self.assertEqual(effects[0]["do"], "send_text")
        effects = P.decide(response(text="Here is our Erbil branch.", tools=tools), STATE)
        self.assertEqual([e["do"] for e in effects],
                         ["send_text", "send_location", "tag", "create_lead", "note", "record_turn"])
        self.assertEqual(of(effects, "send_location")[0]["latitude"], 36.177067)
        self.assertEqual(of(effects, "tag"), [{"do": "tag", "tag": "Info"}])
        self.assertEqual(of(effects, "create_lead")[0]["fields"],
                         {"lead_name": "Ali Hassan", "company_name": "Acme", "city": "Erbil",
                          "mobile_no": "9647701234567"})
        known = P.decide(response(text="Saved.", tools=tools), dict(STATE, has_crm=True))
        self.assertFalse(of(known, "create_lead"))
        self.assertTrue(of(known, "note"))

    def test_record_values(self):
        values = of(P.decide(response(), STATE), "record_turn")[0]["values"]
        self.assertEqual(values["source"], "Live")
        self.assertEqual((values["input_tokens"], values["cache_read_tokens"]), (100, 1000))
        self.assertAlmostEqual(values["cost_usd"], P.cost_usd("claude-opus-5-5", response()["usage"]))
        self.assertIsNone(values["error"])


class TestShadow(unittest.TestCase):
    def test_write_tools_never_executed(self):
        tools = [tool("lookup_customer", result={"known": True}), tool("handoff", executed=True, group="Nano Lab"),
                 tool("send_location", executed=True, site="baghdad"), tool("save_customer_details", executed=False)]
        values = P.shadow_record(response(text="**Hi**", tools=tools))
        self.assertEqual(values["source"], "Shadow")
        self.assertEqual(values["draft"], "*Hi*")
        executed = {t["name"]: t["executed"] for t in values["tools_json"]}
        self.assertEqual(executed, {"lookup_customer": True, "handoff": False, "send_location": False,
                                    "save_customer_details": False})
        self.assertTrue(tools[1]["executed"])  # the input is not mutated
        self.assertEqual(P.shadow_record(response(), source="Replay")["source"], "Replay")


class TestSeed(unittest.TestCase):
    def test_seed_facts_and_defaults(self):
        for knowledge in (S.KNOWLEDGE_EN, S.KNOWLEDGE_AR):
            for fact in ("XRD: 25", "info@alkhora.com", "career@alkhora.com", "07833461529", "General information"):
                self.assertIn(fact, knowledge)
            self.assertNotIn("{{", knowledge)
        self.assertEqual(S.DEFAULTS["ai_mode"], "Off")
        self.assertEqual(S.DEFAULTS["model"], P.DEFAULT_MODEL)
        self.assertLessEqual(len(S.DISCLOSURE_EN), 140)


if __name__ == "__main__":
    unittest.main()

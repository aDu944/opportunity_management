"""
Bench-free tests for the WhatsApp auto menu engine (auto_menu_pure):

    PYTHONPATH=. python3 opportunity_management/opportunity_management/tests/test_auto_menu_pure.py

The tree is the real seed (auto_menu_seed_data) with row names "<menu>-<digit>".
"""

import datetime
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from opportunity_management.opportunity_management import auto_menu_pure as P  # noqa: E402
from opportunity_management.opportunity_management import auto_menu_seed_data as D  # noqa: E402
from opportunity_management.opportunity_management import auto_menu_texts as T  # noqa: E402

NOW = datetime.datetime(2026, 10, 28, 10, 0)
H = datetime.timedelta(hours=1)


def tree():
    menus = {}
    for m in D.MENUS:
        options = [dict(o, row="{0}-{1}".format(m["menu_key"], o["digit"])) for o in m["options"]]
        menus[m["menu_key"]] = dict(m, key=m["menu_key"], options=options)
    return {"root": D.ROOT_MENU, "menus": menus}


TREE = tree()
SETTINGS = {
    "reopen_keywords": P.split_keywords("menu,القائمة,back,رجوع"),
    "language_keywords": P.split_keywords("lang,اللغة"),
    "max_retries": 3, "auto_resolve_hours": 24, "in_hours": True,
    "hours_label": {"en": "Sat 9:00 AM – 3:00 PM", "ar": "السبت 9:00 ص – 3:00 م"},
    "ooh_text": {"en": "We are closed now.", "ar": "نحن مغلقون الآن."},
    "escape_group": "General information",
}


def ctx(state, **kw):
    base = {"state": state, "lang": "en", "path": "", "form": {}, "retries": 0,
            "last_prompt_row": "PROMPT", "last_prompt_id": "wamid.P", "phone": "9647701234567", "has_crm": False}
    base.update(kw)
    return base


def text(value, lang=""):
    return {"kind": "text", "text": value, "lang": lang}


def tap(value, row="PROMPT"):
    return {"kind": "tap", "text": value, "reply_to_row": row}


MEDIA = {"kind": "media", "text": ""}


def run(state, inbound, settings=SETTINGS, **kw):
    return P.next_step(ctx(state, **kw), inbound, TREE, settings)


def of(effects, do):
    return [e for e in effects if e["do"] == do]


def state(effects):
    found = of(effects, "set_state")
    return found[-1]["values"] if found else {}


class TestStart(unittest.TestCase):
    def test_new_conversation(self):
        self.assertTrue(P.should_start("", None, None, None, "Open", NOW, 24))

    def test_idle_reset_even_mid_menu(self):
        self.assertTrue(P.should_start("menu:nano", NOW - 25 * H, NOW - 25 * H, None, "Open", NOW, 24))
        self.assertTrue(P.should_start("done", NOW - 30 * H, NOW - 26 * H, "a@x.com", "Pending", NOW, 24))

    def test_recent_agent_reply_blocks_idle_reset(self):
        self.assertFalse(P.should_start("done", NOW - 30 * H, NOW - 1 * H, "a@x.com", "Pending", NOW, 24))

    def test_empty_state(self):
        self.assertTrue(P.should_start("", NOW - H, NOW - H, None, "Open", NOW, 24))
        self.assertFalse(P.should_start("", NOW - H, NOW - H, "a@x.com", "Open", NOW, 24))
        self.assertTrue(P.should_start("", NOW - H, NOW - H, "a@x.com", "Resolved", NOW, 24))

    def test_active_or_done_not_idle(self):
        self.assertFalse(P.should_start("menu:root", NOW - H, NOW - H, None, "Open", NOW, 24))
        self.assertFalse(P.should_start("done", NOW - H, NOW - H, None, "Open", NOW, 24))

    def test_idle_zero_is_off(self):
        self.assertFalse(P.should_start("done", NOW - 99 * H, NOW - 99 * H, None, "Open", NOW, 0))

    def test_owns(self):
        for s in ("lang", "menu:root", "form:x:name", "request:x"):
            self.assertTrue(P.owns(s, False), s)
        for s in ("", "done", "garbage"):
            self.assertFalse(P.owns(s, False), s)
        self.assertTrue(P.owns("done", True))

    def test_start_effects(self):
        effects = P.next_step(ctx("done", start=True), text("hi"), TREE, SETTINGS)
        self.assertEqual(effects[0]["do"], "send_buttons")
        self.assertEqual([b["id"] for b in effects[0]["buttons"]], ["lang:ar", "lang:en"])
        self.assertTrue(effects[0]["prompt"])
        values = state(effects)
        self.assertEqual(values["menu_state"], "lang")
        self.assertEqual(values["menu_started_at"], P.NOW)
        self.assertIsNone(values["menu_completed_at"])

    def test_done_and_empty_do_nothing(self):
        self.assertEqual(run("done", text("hello")), [])
        self.assertEqual(run("", text("hello")), [])

    def test_unconfigured_tree_hands_back(self):
        effects = P.next_step(ctx("menu:root"), text("1"), {"root": "root", "menus": {}}, SETTINGS)
        self.assertEqual(state(effects), {"menu_state": "done"})

    def test_parse_state(self):
        self.assertEqual(P.parse_state("form:abc:mobile"), ("form", "abc", "mobile"))
        self.assertEqual(P.parse_state("menu:nano"), ("menu", "nano", None))
        self.assertEqual(P.parse_state("request:r1"), ("request", "r1", None))
        self.assertEqual(P.parse_state("menu:"), ("", None, None))
        self.assertEqual(P.parse_state("form:x"), ("", None, None))


class TestLanguageStep(unittest.TestCase):
    def test_tap_sets_language_and_sends_root(self):
        effects = run("lang", tap("lang:ar"), lang="")
        lst = of(effects, "send_list")[0]
        self.assertEqual(lst["menu"], "root")
        self.assertEqual(state(effects)["menu_language"], "ar")
        self.assertEqual(state(effects)["menu_state"], "menu:root")
        self.assertEqual(state(effects)["menu_path"], "")
        self.assertIn("اختر القسم", lst["body"])

    def test_free_text_detects_language(self):
        effects = run("lang", text("مرحبا", lang="ar"), lang="")
        self.assertEqual(state(effects)["menu_language"], "ar")
        self.assertEqual(of(effects, "send_list")[0]["menu"], "root")

    def test_undetectable_and_media_resend_greeting(self):
        for inbound in (text("👍"), MEDIA, tap("opt:root-1")):
            effects = run("lang", inbound)
            self.assertEqual(len(effects), 2)  # the greeting + the strike count
            self.assertTrue(effects[0]["body"].startswith(T.PLEASE_CHOOSE_BOTH))
            self.assertEqual(state(effects), {"menu_retries": 1})

    def test_keywords(self):
        self.assertEqual(state(run("lang", text("  MENU ", lang="en")))["menu_state"], "menu:root")
        effects = run("lang", text("lang"))
        self.assertEqual(effects[0]["body"], T.GREETING)


class TestList(unittest.TestCase):
    def test_rows_prefix_fixed_rows_and_limits(self):
        lst = P.list_prompt(TREE["menus"]["root"], "en")
        titles = [r["title"] for r in lst["rows"]]
        self.assertEqual(titles[0], "1. Nano Lab tests")
        self.assertEqual(titles[-3], "0. General Information")  # sort_order puts 0 last
        self.assertEqual(titles[-2:], ["Main menu", "🌐 العربية"])
        self.assertEqual([r["id"] for r in lst["rows"]][-2:], ["menu:root", "lang:toggle"])
        self.assertEqual(lst["button"], "Choose")
        self.assertTrue(all(len(r["title"]) <= 24 and len(r["description"]) <= 72 for r in lst["rows"]))
        self.assertLessEqual(len(lst["rows"]), 10)
        ar = P.list_prompt(TREE["menus"]["root"], "ar")
        self.assertEqual(ar["rows"][-1]["title"], "🌐 English")
        self.assertEqual(ar["rows"][0]["title"], "1. فحوصات مختبر النانو")

    def test_body_cap(self):
        menu = dict(TREE["menus"]["nano"], body_en="x" * 1024)
        self.assertEqual(len(P.list_prompt(menu, "en", please=True)["body"]), 1024)

    def test_seed_menus_are_valid(self):
        for m in D.MENUS:
            self.assertEqual(P.check_menu(m), [], m["menu_key"])
        targets = {o.get("target_menu") for m in D.MENUS for o in m["options"]} - {None}
        self.assertTrue(targets <= {m["menu_key"] for m in D.MENUS})

    def test_check_menu_limits(self):
        def opt(**kw):
            return dict({"digit": "1", "title_en": "Ok", "action": "Reply"}, **kw)
        self.assertTrue(P.check_menu({"options": [opt(title_en="x" * 22)]}))  # 3 + 22 > 24
        self.assertEqual(P.check_menu({"options": [opt(title_en="x" * 21)]}), [])
        self.assertTrue(P.check_menu({"options": [opt(digit=str(i)) for i in range(9)]}))
        self.assertTrue(P.check_menu({"options": [opt(), opt()]}))
        self.assertTrue(P.check_menu({"options": [opt(digit="12")]}))
        self.assertTrue(P.check_menu({"options": [opt(description_ar="x" * 73)]}))
        self.assertTrue(P.check_menu({"options": [opt(action="Submenu")]}))
        self.assertTrue(P.check_menu({"options": [opt(action="Location", location_lat=1)]}))
        self.assertTrue(P.check_menu({"title_en": "x" * 25, "options": []}))
        self.assertTrue(P.check_menu({"body_ar": "x" * 1025, "options": []}))

    def test_stored_title(self):
        raw = json.dumps([{"id": "opt:r1", "title": "1. Nano Lab tests"}, {"id": "menu:root", "title": "Main menu"}])
        self.assertEqual(P.stored_title(raw, "opt:r1"), "1. Nano Lab tests")
        self.assertEqual(P.stored_title(raw, " menu:root "), "Main menu")
        self.assertEqual(P.stored_title(raw, "opt:zz"), "")
        self.assertEqual(P.stored_title("not json", "opt:r1"), "")
        self.assertEqual(P.stored_title(None, "0"), "")


class TestMenuState(unittest.TestCase):
    def test_digit_opens_submenu(self):
        for typed in ("3", " 3. ", "٣", "3)"):
            effects = run("menu:root", text(typed))
            self.assertEqual(state(effects)["menu_state"], "menu:oilgas", typed)
            self.assertEqual(state(effects)["menu_path"], "3")

    def test_fresh_tap_and_stale_tap(self):
        self.assertEqual(state(run("menu:root", tap("opt:root-4")))["menu_state"], "menu:festo")
        by_wamid = {"kind": "tap", "text": "opt:root-4", "reply_to_id": "wamid.P"}
        self.assertEqual(state(run("menu:root", by_wamid))["menu_state"], "menu:festo")
        # A tap on an option of the current menu counts even when the prompt
        # row is unknown (lost after Meta delivered it); one from another
        # menu's list gets the strict resend.
        stale = run("menu:root", tap("opt:root-4", row="OLD"))
        self.assertEqual(state(stale)["menu_state"], "menu:festo")
        other = run("menu:oilgas", tap("opt:root-4", row="OLD"), path="3")
        self.assertTrue(of(other, "send_list")[0]["body"].startswith(T.PLEASE_CHOOSE["en"]))
        self.assertEqual(state(other)["menu_state"], "menu:oilgas")
        # an option of another menu is not valid here
        other = run("menu:root", tap("opt:nano-1"))
        self.assertTrue(of(other, "send_list")[0]["body"].startswith(T.PLEASE_CHOOSE["en"]))

    def test_strict_resend(self):
        for inbound in (text("hello, I need prices"), MEDIA, text("7"), tap("form:keep")):
            effects = run("menu:nano", inbound, path="1")
            lst = of(effects, "send_list")[0]
            self.assertEqual(lst["menu"], "nano")
            self.assertTrue(lst["body"].startswith(T.PLEASE_CHOOSE["en"] + "\n\n"))
            self.assertEqual(state(effects)["menu_state"], "menu:nano")
            self.assertEqual(state(effects)["menu_retries"], 1)
            self.assertNotIn("menu_path", state(effects))
            self.assertFalse(of(effects, "handoff"))

    def test_strict_escape(self):
        # Second unmatched message in the same menu: no third list, the chat
        # goes to General information with the customer's words.
        effects = run("menu:root", text("do you offer ICP? price and time?"), retries=1)
        self.assertFalse(of(effects, "send_list"))
        self.assertEqual(of(effects, "handoff")[0], {"do": "handoff", "group": "General information",
                                                     "last_handler": False, "escape": True})
        self.assertIn("General information", of(effects, "send_text")[0]["text"])
        self.assertEqual(state(effects)["menu_state"], "done")
        self.assertEqual(state(effects)["menu_completed_at"], P.NOW)
        # A valid choice resets the count; a resend after a success starts at 1.
        self.assertEqual(state(run("menu:root", text("3"), retries=1))["menu_retries"], 0)
        # Limit from settings; no group configured → handoff without a group.
        custom = dict(SETTINGS, escape_after=3, escape_group=None)
        self.assertTrue(of(run("menu:root", MEDIA, retries=1, settings=custom), "send_list"))
        esc = run("menu:root", MEDIA, retries=2, settings=custom)
        self.assertIsNone(of(esc, "handoff")[0]["group"])
        self.assertIn("AL KHORA", of(esc, "send_text")[0]["text"])
        # Language step: two voice notes → same escape; a typed question moves on instead.
        self.assertEqual(state(run("lang", MEDIA))["menu_retries"], 1)
        self.assertTrue(of(run("lang", MEDIA, retries=1), "handoff"))
        self.assertEqual(state(run("lang", text("hello", lang="en")))["menu_state"], "menu:root")

    def test_fixed_rows(self):
        effects = run("menu:nano", tap("menu:root", row="OLD"), path="1")
        self.assertEqual(state(effects)["menu_state"], "menu:root")
        self.assertEqual(state(effects)["menu_path"], "")
        effects = run("menu:nano", tap("lang:toggle"), path="1")
        self.assertEqual(state(effects)["menu_language"], "ar")
        self.assertEqual(state(effects)["menu_state"], "menu:nano")
        self.assertNotIn("menu_path", state(effects))
        self.assertIn("مختبر النانو", of(effects, "send_list")[0]["body"])

    def test_keywords_case_and_whitespace(self):
        self.assertEqual(state(run("menu:nano", text("  Menu\n")))["menu_state"], "menu:root")
        self.assertEqual(state(run("menu:nano", text("القائمة")))["menu_state"], "menu:root")
        self.assertEqual(state(run("menu:nano", text("LANG")))["menu_language"], "ar")
        effects = run("menu:nano", text(" اللغة "), lang="ar")
        self.assertEqual(state(effects)["menu_language"], "en")
        self.assertEqual(state(effects)["menu_state"], "menu:nano")

    def test_reply_resends_menu(self):
        effects = run("menu:nano", text("1"), path="1")
        self.assertIn("FESEM: 40", of(effects, "send_text")[0]["text"])
        self.assertEqual(of(effects, "tag")[0]["tag"], "Nano Lab")
        lst = of(effects, "send_list")[0]
        self.assertEqual(lst["menu"], "nano")
        self.assertFalse(lst["body"].startswith(T.PLEASE_CHOOSE["en"]))
        self.assertEqual(state(effects)["menu_state"], "menu:nano")

    def test_location_then_after_location(self):
        effects = run("menu:nano", text("2"), path="1")
        loc = of(effects, "send_location")[0]
        self.assertEqual((loc["latitude"], loc["longitude"]), (33.297612, 44.340369))
        self.assertEqual(loc["address"], "Al Yarmook, four-streets intersection, Baghdad")
        self.assertIn("07833461529", of(effects, "send_text")[0]["text"])
        self.assertEqual(of(effects, "send_list")[0]["menu"], "after_location")
        self.assertEqual(state(effects)["menu_path"], "1 › 2")
        erbil = run("menu:after_location", text("1"), path="1 › 2")
        self.assertEqual(of(erbil, "send_location")[0]["latitude"], 36.177067)
        self.assertEqual(state(erbil)["menu_state"], "menu:after_location")
        self.assertNotIn("menu_path", state(erbil))

    def test_hours_placeholder(self):
        effects = run("menu:info", text("1"), path="0")
        self.assertIn("Hours: Sat 9:00 AM – 3:00 PM.", of(effects, "send_text")[0]["text"])

    def test_auto_resolve(self):
        effects = run("menu:info", text("3"), path="0")
        self.assertIn("info@alkhora.com", of(effects, "send_text")[0]["text"])
        self.assertEqual(of(effects, "tag")[0]["tag"], "Vendor")
        self.assertEqual(of(effects, "auto_resolve_after")[0]["hours"], 24)
        values = state(effects)
        self.assertEqual((values["menu_state"], values["menu_completed_at"], values["menu_path"]),
                         ("done", P.NOW, "0 › 3"))
        self.assertFalse(of(effects, "send_list"))

    def test_resolve_verdict(self):
        self.assertEqual(P.resolve_verdict(None, NOW, None, None), "wait")
        self.assertEqual(P.resolve_verdict(NOW + H, NOW, None, NOW - H), "wait")
        self.assertEqual(P.resolve_verdict(NOW - H, NOW, NOW - 25 * H, NOW - 25 * H + 1 * datetime.timedelta(seconds=5)), "resolve")
        self.assertEqual(P.resolve_verdict(NOW - H, NOW, NOW - 2 * H, NOW - 25 * H), "clear")

    def test_agent_takeover(self):
        # Running, or never started (a Resolved chat an agent follows up by
        # template): the agent's message parks the menu either way.
        for s in ("lang", "menu:root", "form:r:name", "request:r", "", None):
            self.assertEqual(P.takeover_values(s), {"menu_state": "done"})
        self.assertEqual(P.takeover_values("done"), {})

    def test_template_reply_after_takeover_gets_no_menu(self):
        # Resolved legacy chat, agent sends a template (state -> done, stamps
        # refreshed), customer answers 2h later: no menu. 25h later: idle, menu.
        self.assertFalse(P.should_start("done", NOW - 30 * H, NOW - 2 * H, "a@x", "Resolved", NOW, 24))
        self.assertTrue(P.should_start("done", NOW - 50 * H, NOW - 25 * H, "a@x", "Resolved", NOW, 24))

    def test_conv_fields(self):
        row = {"menu_state": "menu:nano", "menu_path": "1"}
        self.assertEqual(P.conv_fields(row, lambda c, f: c.get(f)),
                         {"menu_state": "menu:nano", "menu_path": "1", "menu_language": ""})


class TestPayload(unittest.TestCase):
    def test_menu_kind_bodies(self):
        from opportunity_management.opportunity_management import whatsapp_payloads as WP

        lst = P.list_prompt(TREE["menus"]["root"], "en")
        interactive = WP.interactive_list(lst["body"], lst["button"], lst["section"], lst["rows"])
        self.assertEqual(interactive["type"], "list")
        rows = interactive["action"]["sections"][0]["rows"]
        self.assertEqual(rows[0], {"id": "opt:root-1", "title": "1. Nano Lab tests",
                                   "description": "Tests and samples for the Nano Lab (SEM, XRD, FTIR...)"})
        self.assertNotIn("description", rows[-1])  # fixed rows carry none
        payload = {"kind": "menu", "interactive": interactive}
        self.assertEqual(WP.custom_kind("interactive", 0, payload), "menu")
        self.assertEqual(WP.custom_kind("interactive", 0, {}), "")
        body = WP.message_body("menu", "964770", payload)
        self.assertEqual((body["type"], body["interactive"]), ("interactive", interactive))
        buttons = WP.interactive_buttons("Body", T.LANG_BUTTONS)
        self.assertEqual(buttons["action"]["buttons"][1], {"type": "reply", "reply": {"id": "lang:en", "title": "English"}})
        self.assertEqual(WP.option_titles(json.dumps(lst["rows"]))[-1], "🌐 العربية")


if __name__ == "__main__":
    unittest.main()

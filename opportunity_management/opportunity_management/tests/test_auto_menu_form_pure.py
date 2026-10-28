"""
Bench-free tests for the auto-menu details form (auto_menu_form_pure) and
the engine's form / returning-customer / request states:

    PYTHONPATH=. python3 opportunity_management/opportunity_management/tests/test_auto_menu_form_pure.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from opportunity_management.opportunity_management import auto_menu_form_pure as F  # noqa: E402
from opportunity_management.opportunity_management import auto_menu_pure as P  # noqa: E402
from opportunity_management.opportunity_management import auto_menu_texts as T  # noqa: E402
from test_auto_menu_pure import MEDIA, SETTINGS, of, run, state, tap, text  # noqa: E402

PHONE = "9647701234567"


class TestValidate(unittest.TestCase):
    def test_name(self):
        self.assertEqual(F.validate("name", text("  Ali   Hassan ")), (True, "Ali Hassan"))
        self.assertEqual(F.validate("name", text("علي حسن")), (True, "علي حسن"))
        self.assertEqual(F.validate("name", text("Ali")), (False, None))
        self.assertEqual(F.validate("name", MEDIA), (False, None))

    def test_company(self):
        self.assertEqual(F.validate("company", text("ACME Ltd")), (True, "ACME Ltd"))
        self.assertEqual(F.validate("company", {"kind": "tap", "text": "form:individual", "fresh": True}), (True, ""))
        self.assertEqual(F.validate("company", {"kind": "tap", "text": "form:individual", "fresh": False}), (False, None))
        self.assertEqual(F.validate("company", MEDIA), (False, None))

    def test_mobile(self):
        self.assertEqual(F.validate("mobile", text("+964 770-123-4567")), (True, "9647701234567"))
        self.assertEqual(F.validate("mobile", text("٠٧٧٠١٢٣٤٥٦٧")), (True, "07701234567"))
        self.assertEqual(F.validate("mobile", text("12345")), (False, None))
        self.assertEqual(F.validate("mobile", text("1" * 16)), (False, None))
        self.assertEqual(F.validate("mobile", text("0770abc4567")), (False, None))
        same = {"kind": "tap", "text": "form:same_number", "fresh": True}
        self.assertEqual(F.validate("mobile", same, PHONE), (True, PHONE))
        self.assertEqual(F.validate("mobile", same, ""), (False, None))

    def test_email(self):
        self.assertEqual(F.validate("email", text("Ali.H@Example.com")), (True, "ali.h@example.com"))
        self.assertEqual(F.validate("email", text("ali@example")), (False, None))
        self.assertEqual(F.validate("email", {"kind": "tap", "text": "form:no_email", "fresh": True}), (True, ""))

    def test_question_buttons(self):
        main = {"id": "menu:root", "title": "Main menu"}
        q = F.question("mobile", "en", PHONE)
        self.assertEqual(q["do"], "send_buttons")
        self.assertEqual(q["buttons"], [{"id": "form:same_number", "title": "Same as this number"}, main])
        # Hidden number: no "same number" button, Main menu still there.
        self.assertEqual(F.question("mobile", "ar", "")["buttons"], [{"id": "menu:root", "title": "القائمة الرئيسية"}])
        self.assertEqual(F.question("name", "ar")["body"], T.QUESTIONS["name"]["ar"])
        self.assertEqual(F.question("name", "en")["buttons"], [main])
        hinted = F.question("email", "en", hint=True)
        self.assertTrue(hinted["body"].startswith(T.HINTS["email"]["en"]))
        self.assertTrue(F.question("address", "en", hint=True)["body"].startswith(T.TEXT_HINT["en"]))
        self.assertEqual([b["id"] for b in F.returning_prompt("en")["buttons"]], ["form:keep", "form:update", "menu:root"])
        buttons = [b for rows in T.FORM_BUTTONS.values() for b in rows] + T.RETURNING_BUTTONS + [T.MAIN_MENU_BUTTON]
        self.assertTrue(all(len(t) <= 20 for b in buttons for t in b["title"].values()))
        for step in ("name", "company", "address", "mobile", "email"):
            self.assertLessEqual(len(F.question(step, "en", PHONE)["buttons"]), 3)

    def test_summary_and_lead_fields(self):
        form = {"name": "Ali Hassan", "company": "", "individual": True, "address": "Baghdad",
                "mobile": "07701234567", "email": "", "missing": []}
        note = F.summary(form, "3 › 1")
        self.assertIn("Auto menu — 3 › 1", note)
        self.assertIn("Company: Individual", note)
        self.assertIn("Email: No email", note)
        self.assertEqual(F.lead_fields(form), {"lead_name": "Ali Hassan", "city": "Baghdad", "mobile_no": "07701234567"})
        self.assertIn("Missing: email", F.summary({"name": "A B", "email": "", "missing": ["email"]}))


class TestFormFlow(unittest.TestCase):
    def test_form_option_starts_with_name(self):
        effects = run("menu:oilgas", text("1"), path="3")
        self.assertEqual(state(effects)["menu_state"], "form:oilgas-1:name")
        self.assertEqual(state(effects)["menu_path"], "3 › 1")
        self.assertEqual(of(effects, "tag")[0]["tag"], "Oil & Gas")
        self.assertEqual(of(effects, "send_buttons")[-1]["body"], T.QUESTIONS["name"]["en"])

    def test_training_sends_reply_first(self):
        effects = run("menu:oilgas", text("2"), path="3")
        self.assertIn("VCAT II", of(effects, "send_text")[0]["text"])
        self.assertEqual(of(effects, "send_buttons")[0]["body"], T.QUESTIONS["name"]["en"])
        self.assertLess(effects.index(of(effects, "send_text")[0]), effects.index(of(effects, "send_buttons")[0]))

    def test_returning_customer(self):
        effects = run("menu:oilgas", text("1"), path="3", has_crm=True)
        self.assertEqual(state(effects)["menu_state"], "form:oilgas-1:confirm")
        self.assertEqual([b["id"] for b in effects[-2]["buttons"]], ["form:keep", "form:update", "menu:root"])
        keep = run("form:oilgas-1:confirm", tap("form:keep"), has_crm=True, path="3 › 1")
        self.assertFalse(of(keep, "create_lead"))
        self.assertIn("kept the saved details", of(keep, "note")[0]["text"])
        self.assertEqual(state(keep)["menu_state"], "request:oilgas-1")
        self.assertIn("part numbers", of(keep, "send_buttons")[0]["body"])
        update = run("form:oilgas-1:confirm", text("Update"), has_crm=True)
        self.assertEqual(state(update)["menu_state"], "form:oilgas-1:name")
        other = run("form:oilgas-1:confirm", text("what?"), has_crm=True)
        self.assertTrue(other[0]["body"].startswith(T.PLEASE_CHOOSE["en"]))
        self.assertNotIn("menu_state", state(other))

    def test_retry_then_skip(self):
        effects = run("form:oilgas-1:name", text("Ali"))
        self.assertEqual(state(effects)["menu_retries"], 1)
        self.assertEqual(state(effects)["menu_state"], "form:oilgas-1:name")
        self.assertTrue(of(effects, "send_buttons")[0]["body"].startswith(T.HINTS["name"]["en"]))
        effects = run("form:oilgas-1:name", MEDIA, retries=1)
        self.assertEqual(state(effects)["menu_retries"], 2)
        effects = run("form:oilgas-1:name", text("Ali"), retries=2)
        self.assertEqual(state(effects)["menu_state"], "form:oilgas-1:company")
        self.assertEqual(state(effects)["menu_form_json"]["missing"], ["name"])
        self.assertEqual(state(effects)["menu_retries"], 0)
        custom = dict(SETTINGS, max_retries=1)
        self.assertEqual(state(run("form:oilgas-1:email", text("x"), settings=custom))["menu_state"],
                         "request:oilgas-1")

    def test_full_form(self):
        form = {}
        steps = [
            ("name", text("Ali Hassan")), ("company", tap("form:individual")), ("address", text("Baghdad, Mansour")),
            ("mobile", tap("form:same_number")), ("email", tap("form:no_email")),
        ]
        for i, (step, answer) in enumerate(steps):
            effects = run("form:oilgas-1:" + step, answer, form=form, path="3 › 1")
            form = state(effects)["menu_form_json"]
            if i + 1 < len(steps):
                self.assertEqual(state(effects)["menu_state"], "form:oilgas-1:" + steps[i + 1][0])
        self.assertEqual(state(effects)["menu_state"], "request:oilgas-1")
        lead = of(effects, "create_lead")[0]["fields"]
        self.assertEqual(lead, {"lead_name": "Ali Hassan", "city": "Baghdad, Mansour", "mobile_no": PHONE})
        self.assertIn("Mobile: " + PHONE, of(effects, "note")[0]["text"])
        self.assertTrue(of(effects, "send_buttons")[-1]["prompt"])

    def test_short_form(self):
        effects = run("form:info-5:company", text("ACME"), form={"name": "Ali Hassan"}, path="0 › 5")
        self.assertEqual(state(effects)["menu_state"], "request:info-5")
        ask = of(effects, "send_buttons")[-1]
        self.assertEqual(ask["body"], "How can we help you?")
        self.assertEqual([b["id"] for b in ask["buttons"]], ["menu:root"])

    def test_keywords_inside_form(self):
        effects = run("form:oilgas-1:mobile", text("lang"))
        self.assertEqual(state(effects)["menu_language"], "ar")
        self.assertEqual(effects[0]["body"], T.QUESTIONS["mobile"]["ar"])  # re-asked, no hint
        self.assertNotIn("menu_retries", state(effects))
        effects = run("form:oilgas-1:mobile", text("menu"))
        self.assertEqual(state(effects)["menu_state"], "menu:root")

    def test_main_menu_button_inside_form(self):
        # Tapping the Main menu button on a question drops the half-filled
        # form and shows the root list in the customer's language.
        effects = run("form:oilgas-1:address", tap("menu:root"), form={"name": "Ali Hassan", "company": "ACME"}, lang="ar")
        self.assertEqual(state(effects)["menu_state"], "menu:root")
        self.assertEqual(state(effects)["menu_path"], "")
        self.assertEqual(of(effects, "send_list")[0]["menu"], "root")
        self.assertFalse(of(effects, "create_lead"))
        self.assertFalse(of(effects, "note"))
        # Same on the returning-customer prompt.
        effects = run("form:oilgas-1:confirm", tap("menu:root"), has_crm=True)
        self.assertEqual(state(effects)["menu_state"], "menu:root")


class TestRequest(unittest.TestCase):
    def test_request_completes(self):
        effects = run("request:oilgas-1", text("PN 1234 x 2"), path="3 › 1")
        self.assertEqual(of(effects, "handoff")[0], {"do": "handoff", "group": "Oil & Gas", "last_handler": False})
        confirm = of(effects, "send_text")[0]["text"]
        self.assertIn("The Oil & Gas team", confirm)
        self.assertNotIn("closed", confirm)
        self.assertEqual(state(effects)["menu_state"], "done")
        self.assertEqual(state(effects)["menu_completed_at"], P.NOW)
        self.assertLess(effects.index(of(effects, "handoff")[0]), effects.index(of(effects, "send_text")[0]))

    def test_media_request_and_out_of_hours(self):
        effects = run("request:nano-5", MEDIA, settings=dict(SETTINGS, in_hours=False), lang="ar")
        confirm = of(effects, "send_text")[0]["text"]
        self.assertIn("فريق Nano Lab", confirm)
        self.assertTrue(confirm.endswith("نحن مغلقون الآن."))

    def test_follow_up_prefers_last_handler(self):
        effects = run("request:info-2", text("Q-123"))
        self.assertEqual(of(effects, "handoff")[0]["last_handler"], True)
        self.assertEqual(of(effects, "handoff")[0]["group"], "General information")

    def test_keywords_in_request(self):
        self.assertEqual(state(run("request:info-2", text("menu")))["menu_state"], "menu:root")
        effects = run("request:info-2", tap("menu:root"))
        self.assertEqual(state(effects)["menu_state"], "menu:root")
        self.assertFalse(of(effects, "handoff"))
        effects = run("request:info-2", text("lang"))
        self.assertEqual(state(effects)["menu_language"], "ar")
        self.assertFalse(of(effects, "handoff"))


if __name__ == "__main__":
    unittest.main()

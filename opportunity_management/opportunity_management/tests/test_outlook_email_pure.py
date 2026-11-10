"""
Bench-free tests for `outlook_email_pure` (Outlook add-in: who the customer
is on an email, message IDs, reply headers, ranking, Communication values).

    python3 opportunity_management/opportunity_management/tests/test_outlook_email_pure.py

The module has no `frappe` import, so it is loaded straight off disk.
"""

import importlib.util
import os
import unittest
from datetime import datetime

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "outlook_email_pure.py")
    spec = importlib.util.spec_from_file_location("outlook_email_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()
ME = "as@alkhora.com"


class Addresses(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(P.normalize_email("  Ali <Ali@Customer.IQ> "), "ali@customer.iq")
        self.assertEqual(P.normalize_email("not an address"), "")
        self.assertEqual(P.normalize_email(None), "")

    def test_direction(self):
        self.assertEqual(P.direction("AS@alkhora.com", ME), "Sent")
        self.assertEqual(P.direction("ali@customer.iq", ME), "Received")

    def test_received_counterparts_drop_me_and_colleagues(self):
        got = P.counterparts("ali@customer.iq", [ME, "sara@alkhora.com"],
                             ["omar@customer.iq", "ali@customer.iq"], ME)
        self.assertEqual(got, ["ali@customer.iq", "omar@customer.iq"])

    def test_sent_counterparts_are_recipients(self):
        got = P.counterparts(ME, ["buyer@oil.com"], ["eng@oil.com", "sara@alkhora.com"], ME)
        self.assertEqual(got, ["buyer@oil.com", "eng@oil.com"])

    def test_extra_own_domains(self):
        got = P.counterparts("x@alameriya.com", [ME], [], ME, own_domains=["alameriya.com"])
        self.assertEqual(got, [])

    def test_company_domains_skip_public(self):
        self.assertEqual(P.company_domains(["a@gmail.com", "b@oil.com", "c@oil.com"]), ["oil.com"])


class MessageIds(unittest.TestCase):
    def test_brackets_stripped(self):
        self.assertEqual(P.normalize_message_id(" <abc@erp.local> "), "abc@erp.local")

    def test_reference_ids_order_and_dedupe(self):
        ids = P.reference_ids("<c@erp.local>", "<a@x> <b@y>\t<c@erp.local>")
        self.assertEqual(ids, ["c@erp.local", "b@y", "a@x"])

    def test_reference_ids_empty(self):
        self.assertEqual(P.reference_ids("", ""), [])

    def test_header_value_unfolds(self):
        raw = ("Subject: hi\r\nReferences: <a@x>\r\n <b@y>\r\nIn-Reply-To: <b@y>\r\n"
               "X-Other: z\r\n")
        self.assertEqual(P.header_value(raw, "references"), "<a@x> <b@y>")
        self.assertEqual(P.header_value(raw, "In-Reply-To"), "<b@y>")
        self.assertEqual(P.header_value(raw, "Missing"), "")
        self.assertEqual(P.header_value(None, "References"), "")


class Ranking(unittest.TestCase):
    def test_merge_keeps_strongest_first(self):
        merged = P.merge_candidates([("O1", "domain"), ("O1", "contact"), ("O2", "bogus"),
                                     ("O1", "contact"), (None, "linked")])
        self.assertEqual(merged, {"O1": ["contact", "domain"]})

    def test_rank_reason_then_open_then_recent(self):
        merged = {"A": ["domain"], "B": ["contact"], "C": ["contact"], "D": ["contact"], "X": ["thread"]}
        rows = [
            {"name": "A", "status": "Open", "modified": "2026-11-01"},
            {"name": "B", "status": "Lost", "modified": "2026-11-09"},
            {"name": "C", "status": "Open", "modified": "2026-10-01"},
            {"name": "D", "status": "Quotation", "modified": "2026-11-05"},
            {"name": "X", "status": "Closed", "modified": "2025-01-01"},
            {"name": "Z", "status": "Open", "modified": "2026-11-09"},  # not a candidate
        ]
        self.assertEqual([r["name"] for r in P.rank(rows, merged)], ["X", "D", "C", "B", "A"])

    def test_present(self):
        row = {"name": "ER-1", "status": "Converted", "customer_name": "Oil Co",
               "party_name": "CUST-1", "custom_tender_title": "Valves", "reasons": ["reply"],
               "custom_inq_number": "INQ-9"}
        p = P.present(row)
        self.assertEqual(p["status"], "Won")
        self.assertTrue(p["closed"])
        self.assertEqual(p["party"], "Oil Co")
        self.assertEqual(p["title"], "Valves")
        self.assertEqual(p["inq_no"], "INQ-9")
        self.assertEqual(p["reason_labels"], ["Reply to an email sent from ERPNext"])


class CommunicationValues(unittest.TestCase):
    EMAIL = {
        "subject": " RFQ valves ",
        "from": {"email": "Ali@Customer.iq", "name": "Ali"},
        "to": [{"email": ME, "name": "Ahmed"}, {"email": "bad"}],
        "cc": [],
        "message_id": "<m1@customer.iq>",
        "conversation_id": "AAQk==",
        "body_html": "<p>hello</p>",
    }

    def test_received(self):
        v = P.communication_values(self.EMAIL, "ER-1", ME)
        self.assertEqual(v["sent_or_received"], "Received")
        self.assertEqual(v["sender"], "ali@customer.iq")
        self.assertEqual(v["recipients"], f"Ahmed <{ME}>")
        self.assertIsNone(v["cc"])
        self.assertEqual(v["message_id"], "m1@customer.iq")
        self.assertEqual(v["subject"], "RFQ valves")
        self.assertEqual((v["reference_doctype"], v["reference_name"]), ("Opportunity", "ER-1"))
        self.assertEqual(v["custom_outlook_conversation_id"], "AAQk==")

    def test_sent(self):
        email = dict(self.EMAIL, **{"from": {"email": ME}, "to": ["buyer@oil.com"]})
        self.assertEqual(P.communication_values(email, "ER-1", ME)["sent_or_received"], "Sent")

    def test_no_sender_rejected(self):
        with self.assertRaises(ValueError):
            P.communication_values(dict(self.EMAIL, **{"from": {}}), "ER-1", ME)

    def test_huge_html_falls_back_to_text(self):
        email = dict(self.EMAIL, body_html="x" * (P.MAX_CONTENT_CHARS + 1), body_text="a <b> c")
        v = P.communication_values(email, "ER-1", ME)
        self.assertEqual(v["content"], "<pre>a &lt;b&gt; c</pre>")

    def test_empty_subject(self):
        v = P.communication_values(dict(self.EMAIL, subject="  "), "ER-1", ME)
        self.assertEqual(v["subject"], "(no subject)")


class CreateHelpers(unittest.TestCase):
    def test_valid_abr(self):
        self.assertTrue(P.valid_abr("OCB"))
        self.assertTrue(P.valid_abr("A1"))
        self.assertFalse(P.valid_abr("oc"))
        self.assertFalse(P.valid_abr("O-C"))
        self.assertFalse(P.valid_abr(""))
        self.assertFalse(P.valid_abr("ABCDEFGHIJK"))

    def test_suggest_abr(self):
        self.assertEqual(P.suggest_abr("Oil Co Basra"), "OCB")
        self.assertEqual(P.suggest_abr("basraoil"), "BASRA")
        self.assertEqual(P.suggest_abr(""), "")

    def test_company_from_domain(self):
        self.assertEqual(P.company_from_domain("mail.basra-oil.com.iq"), "Basra Oil")
        self.assertEqual(P.company_from_domain("sales.company.co.uk"), "Company")
        self.assertEqual(P.company_from_domain("oilco.iq"), "Oilco")
        self.assertEqual(P.company_from_domain("gmail.com"), "")

    def test_new_lead_suggestion(self):
        s = P.new_lead_suggestion("Ali.Hassan@basra-oil.com", "")
        self.assertEqual(s, {"lead_name": "Ali Hassan", "company_name": "Basra Oil",
                             "email_id": "ali.hassan@basra-oil.com", "abr": "BO"})
        s = P.new_lead_suggestion("x@gmail.com", "Sara K")
        self.assertEqual((s["lead_name"], s["company_name"], s["abr"]), ("Sara K", "", "SK"))

    def test_title_from_subject(self):
        self.assertEqual(P.title_from_subject("RE: Fwd: FW: RFQ valves"), "RFQ valves")
        self.assertEqual(P.title_from_subject("Re[2]: Offer"), "Offer")
        self.assertEqual(P.title_from_subject("Required: spares"), "Required: spares")
        self.assertEqual(len(P.title_from_subject("x" * 300)), 140)


class ParseHelpers(unittest.TestCase):
    def test_parse_kind(self):
        self.assertEqual(P.parse_kind("RFQ.PDF"), ("pdf", "application/pdf"))
        self.assertEqual(P.parse_kind("scan.jpeg")[0], "image")
        self.assertEqual(P.parse_kind("boq.xlsx")[0], "sheet")
        self.assertEqual(P.parse_kind("spec.docx")[0], "doc")
        self.assertIsNone(P.parse_kind("old.xls"))   # refused by the parser
        self.assertIsNone(P.parse_kind("old.doc"))
        self.assertIsNone(P.parse_kind("drawings.zip"))
        self.assertIsNone(P.parse_kind("noext"))

    def test_merge_notes(self):
        self.assertEqual(P.merge_notes("", "Delivery 8 weeks", None), "Delivery 8 weeks")
        self.assertEqual(P.merge_notes("Old", "Delivery 8 weeks", "Check P/N"),
                         "Old\n\nDelivery 8 weeks\n\nCheck P/N")
        self.assertEqual(P.merge_notes("Old\n\nDelivery 8 weeks", "Delivery 8 weeks", ""),
                         "Old\n\nDelivery 8 weeks")
        self.assertEqual(P.merge_notes(None), "")


class EmailText(unittest.TestCase):
    HTML = ("<html><head><style>p{color:red}</style></head><body>"
            "<p>Dear Sir,</p><p>Please quote:</p>"
            "<table><tr><th>Item</th><th>Qty</th></tr>"
            "<tr><td>Gate valve 6&quot; 300#</td><td>12</td></tr>"
            "<tr><td>Gasket&nbsp;6in</td><td>24</td></tr></table>"
            "<ul><li>Delivery DDP Basra</li></ul><!-- tracking --><br><br><br>Regards</body></html>")

    def test_html_to_text(self):
        text = P.html_to_text(self.HTML)
        self.assertNotIn("color:red", text)
        self.assertNotIn("tracking", text)
        self.assertIn('Gate valve 6" 300# | 12', text)
        self.assertIn("Gasket 6in | 24", text)
        self.assertIn("- Delivery DDP Basra", text)
        self.assertNotIn("\n\n\n", text)
        self.assertTrue(text.startswith("Dear Sir,"))
        self.assertTrue(text.endswith("Regards"))

    def test_email_text(self):
        t = P.email_text(subject="RFQ", sender="ali@oilco.iq", recipients="as@alkhora.com",
                         date="2026-11-09 12:15", html_body="<p>Hi</p>")
        self.assertEqual(t, "From: ali@oilco.iq\nTo: as@alkhora.com\nDate: 2026-11-09 12:15\n"
                            "Subject: RFQ\n\nHi")
        self.assertEqual(len(P.email_text(html_body="x" * 200, limit=50)), 50)
        self.assertEqual(P.email_text(), "")


class SubjectAndDomainRules(unittest.TestCase):
    def test_subject_refs_real_shapes(self):
        cases = {
            "RE: TENDER #2041 [INQ-577-IC-2041-26]": "INQ-577-IC-2041-26",
            "Fw: INQ-556-OTI-SIU -RIG-202-26 offer": "INQ-556-OTI-SIU -RIG-202-26",
            "quote ER-040-26 pls": "ER-040-26",
            "INQ-287-PNS-PCIHBV 2026 MRP 6135-26": "INQ-287-PNS-PCIHBV 2026 MRP 6135-26",
            "inq-574-MthU-3-26": "inq-574-MthU-3-26",
            "INQ-001-BGCI--24 x": "INQ-001-BGCI--24",
            "FB-001-26": "FB-001-26",
            "INQ-301-IC-0-26": "INQ-301-IC-0-26",
        }
        for subject, want in cases.items():
            self.assertIn(want, P.subject_refs(subject), subject)

    def test_subject_refs_two_numbers_and_none(self):
        refs = P.subject_refs("INQ-301-IC-0-26 / ER-039-26")
        self.assertIn("INQ-301-IC-0-26", refs)
        self.assertIn("ER-039-26", refs)
        self.assertEqual(P.subject_refs("Offer for valves 2026"), [])
        self.assertEqual(P.subject_refs(None), [])

    def test_subject_with_ref(self):
        self.assertEqual(P.subject_with_ref("RE: RFQ", "INQ-577-IC-2041-26"), "RE: RFQ [INQ-577-IC-2041-26]")
        self.assertEqual(P.subject_with_ref("RE: RFQ [inq-577-ic-2041-26]", "INQ-577-IC-2041-26"),
                         "RE: RFQ [inq-577-ic-2041-26]")
        self.assertEqual(P.subject_with_ref("", "ER-040-26"), "[ER-040-26]")

    def test_domain_rules(self):
        self.assertEqual(P.normalize_domain(" @BadraProject.com "), "badraproject.com")
        self.assertEqual(P.normalize_domain("tenders@badraproject.com"), "badraproject.com")
        self.assertTrue(P.domain_matches("badraproject.com", "badraproject.com"))
        self.assertTrue(P.domain_matches("mail.badraproject.com", "@badraproject.com"))
        self.assertFalse(P.domain_matches("notbadraproject.com", "badraproject.com"))
        self.assertFalse(P.domain_matches("", "badraproject.com"))

    def test_subject_and_rule_rank_high(self):
        merged = P.merge_candidates([("A", "contact"), ("B", "domain_rule"), ("C", "subject")])
        rows = [{"name": n, "status": "Open", "modified": "2026-11-01"} for n in "ABC"]
        self.assertEqual([r["name"] for r in P.rank(rows, merged)], ["C", "B", "A"])


class Misc(unittest.TestCase):
    def test_parse_iso_utc(self):
        self.assertEqual(P.parse_iso_utc("2026-11-09T12:30:00.000Z"), datetime(2026, 11, 9, 12, 30))
        self.assertEqual(P.parse_iso_utc("2026-11-09T15:30:00+03:00"), datetime(2026, 11, 9, 12, 30))
        self.assertIsNone(P.parse_iso_utc("yesterday"))
        self.assertIsNone(P.parse_iso_utc(""))

    def test_safe_filename(self):
        self.assertEqual(P.safe_filename('a/b:c?.pdf'), "a_b_c_.pdf")
        self.assertEqual(P.safe_filename("  ..  "), "attachment")
        self.assertEqual(len(P.safe_filename("x" * 300)), 140)


if __name__ == "__main__":
    unittest.main()

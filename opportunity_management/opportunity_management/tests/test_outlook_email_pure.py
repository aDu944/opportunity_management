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

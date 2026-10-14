"""
Bench-free tests for `customer_info_pure` (the customer info screen's
identity matching, message roll-up and identity block).

    python3 opportunity_management/opportunity_management/tests/test_customer_info_pure.py

The module has no `frappe` import, so it is loaded straight off disk.
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "customer_info_pure.py")
    spec = importlib.util.spec_from_file_location("customer_info_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()


def conv(name, **kw):
    row = {"name": name, "channel": "WhatsApp", "phone": "", "last_message_at": ""}
    row.update(kw)
    return row


class TestIdentityKeys(unittest.TestCase):
    def test_phone_digits(self):
        self.assertIn(("phone", "9647701234567"), P.identity_keys(conv("a", phone="+964 770 123 4567")))

    def test_bsuid_is_not_a_phone(self):
        keys = P.identity_keys(conv("a", phone="IQ.1858675848823706"))
        self.assertEqual(keys, {("uid", "IQ.1858675848823706")})

    def test_messenger_psid(self):
        keys = P.identity_keys(conv("a", channel="Messenger", phone="FB.123"))
        self.assertEqual(keys, {("psid", "123")})

    def test_username_case_and_at(self):
        keys = P.identity_keys(conv("a", phone="IQ.1", wa_username="@Plo_20"))
        self.assertIn(("username", "plo_20"), keys)

    def test_crm_links(self):
        keys = P.identity_keys(conv("a", contact="C-1", lead="L-1", customer="Cu"))
        self.assertTrue({("contact", "C-1"), ("lead", "L-1"), ("customer", "Cu")} <= keys)

    def test_empty(self):
        self.assertEqual(P.identity_keys(conv("a")), set())


class TestRelated(unittest.TestCase):
    def test_same_phone_other_account(self):
        me = conv("a", phone="9647701234567")
        rows = [conv("a", phone="9647701234567"), conv("b", phone="+9647701234567"),
                conv("c", phone="9647700000000")]
        self.assertEqual([r["name"] for r in P.related_conversations(me, rows)], ["b"])

    def test_cross_channel_via_contact(self):
        me = conv("a", phone="9647701234567", contact="C-1")
        rows = [conv("m", channel="Messenger", phone="FB.9", contact="C-1"),
                conv("x", channel="Messenger", phone="FB.10")]
        self.assertEqual([r["name"] for r in P.related_conversations(me, rows)], ["m"])

    def test_psid_never_matches_bsuid_digits(self):
        me = conv("a", channel="Messenger", phone="FB.123")
        rows = [conv("b", phone="123"), conv("c", channel="Messenger", phone="FB.123")]
        self.assertEqual([r["name"] for r in P.related_conversations(me, rows)], ["c"])

    def test_order_and_limit(self):
        me = conv("a", phone="1")
        rows = [conv(str(i), phone="1", last_message_at="2026-01-%02d" % (i + 1)) for i in range(15)]
        out = P.related_conversations(me, rows, limit=10)
        self.assertEqual(len(out), 10)
        self.assertEqual(out[0]["name"], "14")

    def test_no_identity_no_matches(self):
        self.assertEqual(P.related_conversations(conv("a"), [conv("b")]), [])


class TestCandidateFilters(unittest.TestCase):
    def test_pairs(self):
        pairs = P.candidate_filters(conv("a", phone="+9647", wa_user_id="IQ.1",
                                         wa_username="@u", lead="L"))
        self.assertEqual(pairs, [("phone", "+9647"), ("phone", "9647"), ("wa_user_id", "IQ.1"),
                                 ("phone", "IQ.1"), ("wa_username", "u"), ("lead", "L")])

    def test_dedup(self):
        pairs = P.candidate_filters(conv("a", phone="IQ.1", wa_user_id="IQ.1"))
        self.assertEqual(pairs.count(("phone", "IQ.1")), 1)


class TestRollUp(unittest.TestCase):
    def test_counts(self):
        rows = [
            {"type": "Incoming", "content_type": "text", "has_attach": 0, "n": 5},
            {"type": "Incoming", "content_type": "image", "has_attach": 1, "n": 2},
            {"type": "Outgoing", "content_type": "document", "has_attach": 1, "n": 1},
            {"type": "Outgoing", "content_type": "text", "has_attach": 0, "n": 7},
            {"type": "Incoming", "content_type": "reaction", "has_attach": 0, "n": 9},
            {"type": "Outgoing", "content_type": "image", "has_attach": 0, "n": 1},
        ]
        self.assertEqual(P.roll_up_messages(rows),
                         {"messages_in": 7, "messages_out": 9, "media_count": 3})

    def test_garbage(self):
        self.assertEqual(P.roll_up_messages([{"n": "x"}, {"n": None}]),
                         {"messages_in": 0, "messages_out": 0, "media_count": 0})


class TestIdentityBlock(unittest.TestCase):
    def test_whatsapp(self):
        out = P.identity_block({"channel": "WhatsApp", "phone": "9647", "username": "u",
                                "display_name": "Ali", "customer_language": "ar"})
        self.assertEqual(out["phone"], "9647")
        self.assertEqual(out["username"], "u")
        self.assertIsNone(out["psid"])

    def test_hidden_number(self):
        out = P.identity_block({"channel": "WhatsApp", "phone": "IQ.1", "username": None})
        self.assertIsNone(out["phone"])

    def test_messenger(self):
        out = P.identity_block({"channel": "Messenger", "phone": "FB.42", "username": "x"})
        self.assertEqual((out["phone"], out["username"], out["psid"]), (None, None, "42"))


class TestOpportunity(unittest.TestCase):
    def test_open(self):
        self.assertTrue(P.is_open_opportunity("Open"))
        self.assertTrue(P.is_open_opportunity("Quotation"))
        self.assertFalse(P.is_open_opportunity("Lost"))


if __name__ == "__main__":
    unittest.main()

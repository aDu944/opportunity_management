"""
Bench-free tests for the Messenger channel's pure parts:

    messenger_events.parse / watermark_targets      (webhook → events)
    messenger_api bodies, error mapping, signature  (us → Meta)

    python3 opportunity_management/opportunity_management/tests/test_messenger_pure.py

Sample payloads follow Meta's Messenger Platform webhook reference
(messages, message_echoes, message_deliveries, message_reads,
message_reactions, messaging_postbacks).
"""

import hashlib
import hmac
import importlib.util
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


API = _load("_messenger_api_under_test", "messenger_api.py")
EV = _load("_messenger_events_under_test", "messenger_events.py")

PAGE, PSID = "1111", "2222"


def delivery(*events, page=PAGE, obj="page"):
    return {"object": obj, "entry": [{"id": page, "time": 1, "messaging": list(events)}]}


def from_customer(**body):
    return dict({"sender": {"id": PSID}, "recipient": {"id": PAGE}, "timestamp": 1700000000000}, **body)


class TestParse(unittest.TestCase):
    def one(self, event, **kw):
        events = EV.parse(delivery(event), PAGE, **kw)
        self.assertEqual(len(events), 1)
        return events[0]

    def test_text(self):
        e = self.one(from_customer(message={"mid": "m1", "text": "hello"}))
        self.assertEqual(e, {
            "psid": PSID, "page_id": PAGE, "timestamp": 1700000000000, "kind": "message",
            "mid": "m1", "text": "hello", "attachments": [], "reply_to": None,
            "echo": False, "ours": False,
        })

    def test_multi_attachment_with_text(self):
        e = self.one(from_customer(message={"mid": "m2", "text": "look", "attachments": [
            {"type": "image", "payload": {"url": "https://cdn/x.jpg"}},
            {"type": "file", "payload": {"url": "https://cdn/a.pdf"}},
            {"type": "audio", "payload": {"url": "https://cdn/v.mp4"}},
            {"type": "video", "payload": {"url": "https://cdn/c.mp4"}},
        ]}))
        self.assertEqual(e["text"], "look")
        self.assertEqual([a["type"] for a in e["attachments"]], ["image", "document", "audio", "video"])
        self.assertFalse(any(a["sticker"] for a in e["attachments"]))

    def test_sticker_and_like(self):
        e = self.one(from_customer(message={"mid": "m3", "sticker_id": 369239263222822, "attachments": [
            {"type": "image", "payload": {"url": "https://cdn/like.png", "sticker_id": 369239263222822}}]}))
        self.assertEqual(e["attachments"], [{"type": "image", "url": "https://cdn/like.png", "sticker": True}])

    def test_quick_reply_and_reply_to(self):
        e = self.one(from_customer(message={
            "mid": "m4", "text": "Yes", "quick_reply": {"payload": "Yes"}, "reply_to": {"mid": "m0"}}))
        self.assertEqual((e["text"], e["reply_to"]), ("Yes", "m0"))
        e = self.one(from_customer(message={"mid": "m5", "quick_reply": {"payload": "Tomorrow"}}))
        self.assertEqual(e["text"], "Tomorrow")

    def test_fallback_link(self):
        e = self.one(from_customer(message={"mid": "m6", "attachments": [
            {"type": "fallback", "title": "Our shop", "url": "https://x.example"}]}))
        self.assertEqual((e["text"], e["attachments"]), ("Our shop https://x.example", []))

    def test_echo_is_customer_side_psid(self):
        echo = {"sender": {"id": PAGE}, "recipient": {"id": PSID}, "timestamp": 1,
                "message": {"is_echo": True, "app_id": 263902037430900, "mid": "e1", "text": "hi from MBS"}}
        e = self.one(echo)
        self.assertEqual((e["psid"], e["echo"], e["ours"]), (PSID, True, False))

    def test_echo_of_our_send(self):
        echo = {"sender": {"id": PAGE}, "recipient": {"id": PSID}, "timestamp": 1,
                "message": {"is_echo": True, "mid": "e2", "text": "x", "metadata": "alkhora_inbox"}}
        self.assertTrue(self.one(echo)["ours"])

    def test_delivery_and_read(self):
        e = self.one(from_customer(delivery={"mids": ["a", "b"], "watermark": 1700000000500}))
        self.assertEqual((e["kind"], e["mids"], e["watermark"]), ("delivery", ["a", "b"], 1700000000500))
        e = self.one(from_customer(read={"watermark": 1700000000900}))
        self.assertEqual((e["kind"], e["watermark"]), ("read", 1700000000900))

    def test_reactions(self):
        e = self.one(from_customer(reaction={"reaction": "love", "emoji": "❤️", "action": "react", "mid": "m1"}))
        self.assertEqual((e["kind"], e["mid"], e["emoji"], e["action"]), ("reaction", "m1", "❤️", "react"))
        e = self.one(from_customer(reaction={"reaction": "love", "emoji": "❤️", "action": "unreact", "mid": "m1"}))
        self.assertEqual((e["emoji"], e["action"]), ("", "unreact"))

    def test_postback(self):
        e = self.one(from_customer(postback={"mid": "p1", "title": "Get Started", "payload": "GET_STARTED"}))
        self.assertEqual((e["kind"], e["mid"], e["text"]), ("postback", "p1", "Get Started"))

    def test_other_page_and_object_dropped(self):
        self.assertEqual(EV.parse(delivery(from_customer(message={"mid": "x", "text": "t"}), page="9"), PAGE), [])
        self.assertEqual(EV.parse(delivery(from_customer(message={"mid": "x", "text": "t"}), obj="instagram"), PAGE), [])
        self.assertEqual(len(EV.parse(delivery(from_customer(message={"mid": "x", "text": "t"}), page="9"))), 1)

    def test_malformed_never_raises(self):
        for junk in (None, [], {"object": "page", "entry": "x"}, delivery("x", {"message": {}})):
            self.assertEqual(EV.parse(junk, PAGE), [])


class TestWatermark(unittest.TestCase):
    ROWS = [
        {"name": "r1", "message_id": "a", "status": "sent", "sent_ms": 100},
        {"name": "r2", "message_id": "b", "status": "delivered", "sent_ms": 200},
        {"name": "r3", "message_id": "c", "status": "sent", "sent_ms": 300},
        {"name": "r4", "message_id": "d", "status": "Failed", "sent_ms": 50},
        {"name": "r5", "message_id": "e", "status": "read", "sent_ms": 60},
    ]

    def test_read(self):
        self.assertEqual(EV.watermark_targets(self.ROWS, "read", 250), ["r1", "r2"])

    def test_delivery_never_downgrades(self):
        self.assertEqual(EV.watermark_targets(self.ROWS, "delivered", 1000), ["r1", "r3"])

    def test_delivery_by_mid(self):
        self.assertEqual(EV.watermark_targets(self.ROWS, "delivered", 0, mids=["c"]), ["r3"])


class TestBodies(unittest.TestCase):
    def test_text_standard(self):
        self.assertEqual(API.text_bodies("FB." + PSID, "hi", "standard", reply_to="m9"), [{
            "recipient": {"id": PSID},
            "messaging_type": "RESPONSE",
            "message": {"text": "hi", "metadata": "alkhora_inbox"},
            "reply_to": {"mid": "m9"},
        }])

    def test_text_human_agent(self):
        self.assertEqual(API.text_bodies(PSID, "late reply", "human_agent"), [{
            "recipient": {"id": PSID},
            "messaging_type": "MESSAGE_TAG",
            "tag": "HUMAN_AGENT",
            "message": {"text": "late reply", "metadata": "alkhora_inbox"},
        }])

    def test_closed_refuses(self):
        self.assertIsNone(API.messaging_fields("closed"))
        with self.assertRaises(ValueError):
            API.text_bodies(PSID, "x", "closed")

    def test_split(self):
        text = ("word " * 900).strip()  # 4499 chars
        bodies = API.text_bodies(PSID, text, "standard", reply_to="m1", options=["Yes", "No"])
        self.assertEqual(len(bodies), 3)
        self.assertTrue(all(len(b["message"]["text"]) <= 2000 for b in bodies))
        self.assertEqual(" ".join(b["message"]["text"] for b in bodies), text)
        self.assertIn("reply_to", bodies[0])
        self.assertNotIn("reply_to", bodies[1])
        self.assertNotIn("quick_replies", bodies[0]["message"])
        self.assertEqual(len(bodies[2]["message"]["quick_replies"]), 2)
        self.assertEqual(API.split_text("x" * 4001), ["x" * 2000, "x" * 2000, "x"])

    def test_quick_replies(self):
        self.assertEqual(API.quick_replies(["A very long option title here", " "]), [
            {"content_type": "text", "title": "A very long option t", "payload": "A very long option title here"}])
        self.assertEqual(len(API.quick_replies([str(i) for i in range(20)])), 13)

    def test_attachment(self):
        self.assertEqual(API.attachment_body(PSID, "document", "https://x/f.pdf", "standard"), {
            "recipient": {"id": PSID},
            "messaging_type": "RESPONSE",
            "message": {"attachment": {"type": "file", "payload": {"url": "https://x/f.pdf", "is_reusable": False}},
                        "metadata": "alkhora_inbox"},
        })
        self.assertEqual(API.attachment_body(PSID, "audio", "u", "standard")["message"]["attachment"]["type"], "audio")

    def test_sender_actions_and_reactions(self):
        self.assertEqual(API.sender_action_body("FB.7", "typing_on"),
                         {"recipient": {"id": "7"}, "sender_action": "typing_on"})
        self.assertEqual(API.reaction_body(PSID, "m1", "👍"), {
            "recipient": {"id": PSID}, "sender_action": "react",
            "payload": {"message_id": "m1", "reaction": "👍"}})
        self.assertEqual(API.reaction_body(PSID, "m1", ""), {
            "recipient": {"id": PSID}, "sender_action": "unreact", "payload": {"message_id": "m1"}})

    def test_identity(self):
        self.assertEqual(API.psid_of("FB.123"), "123")
        self.assertEqual(API.identifier_for("123"), "FB.123")
        self.assertEqual(API.conversation_key("p", "123"), "messenger:p:123")
        self.assertEqual(EV.OUR_METADATA, API.OUR_METADATA)

    def test_size_limits(self):
        self.assertEqual(API.max_bytes("image"), 8 * 1024 * 1024)
        self.assertEqual(API.max_bytes("video"), 25 * 1024 * 1024)


class TestErrors(unittest.TestCase):
    def test_window(self):
        payload = {"error": {"message": "(#10) This message is sent outside of allowed window.",
                             "type": "OAuthException", "code": 10, "error_subcode": 2018278}}
        message, code, sub = API.error_info(payload)
        self.assertEqual((code, sub), (10, 2018278))
        self.assertTrue(API.GraphError(message, code, sub).window)

    def test_unavailable_is_window(self):
        self.assertTrue(API.is_window_error(551, None))
        self.assertTrue(API.is_window_error("551", "1545041"))

    def test_other(self):
        self.assertFalse(API.is_window_error(10, 2018065))
        self.assertFalse(API.is_window_error(190, None))
        self.assertEqual(API.error_info({"error": {"message": "Invalid token", "code": 190}}),
                         ("(190) Invalid token", 190, None))
        self.assertEqual(API.error_info({}), ("", None, None))


class TestSignature(unittest.TestCase):
    def test_valid_and_invalid(self):
        raw = json.dumps(delivery(from_customer(message={"mid": "m", "text": "t"}))).encode()
        sig = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
        self.assertTrue(API.valid_signature("s3cret", raw, sig))
        self.assertFalse(API.valid_signature("other", raw, sig))
        self.assertFalse(API.valid_signature("s3cret", raw + b" ", sig))
        self.assertFalse(API.valid_signature("s3cret", raw, sig.replace("sha256=", "sha1=")))
        self.assertFalse(API.valid_signature("s3cret", raw, None))


if __name__ == "__main__":
    unittest.main()

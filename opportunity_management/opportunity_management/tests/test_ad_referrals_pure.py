"""
Bench-free tests for ad referrals (ad_referral_contract.md):

    ad_referrals      normalisers, stored-JSON readers, push line, backfill walker
    messenger_events  message.referral / postback.referral / bare referral event

    python3 opportunity_management/opportunity_management/tests/test_ad_referrals_pure.py

Payloads follow Meta's references: WhatsApp Cloud API messages webhook
(`referral` on an inbound message) and Messenger Platform `messages`,
`messaging_postbacks` and `messaging_referrals`.
"""

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


AR = _load("_ad_referrals_under_test", "ad_referrals.py")
EV = _load("_messenger_events_ref_under_test", "messenger_events.py")

KEYS = {"source", "headline", "body", "url", "image_url", "media_type", "ad_id", "ref"}

WA_IMAGE_AD = {
    "source_url": "https://fb.me/3cr4Wqqkv",
    "source_id": "120226305854810726",
    "source_type": "ad",
    "body": "Summer Succulents are here!",
    "headline": "Chat with us",
    "media_type": "image",
    "image_url": "https://scontent.xx.fbcdn.net/v/t45.1/abc_n.jpg?_nc_cat=1",
    "ctwa_clid": "Aff-n8ZTODiE79d22KtAwQKj9e_mIEOOj27vDVwFjN80dp4",
    "welcome_message": {"text": "Hi there! Let us know how we can help!"},
}
WA_VIDEO_AD = {
    "source_url": "https://fb.me/9xyz", "source_id": "120226305854899999", "source_type": "ad",
    "body": "Watch", "headline": "  New collection  ", "media_type": "video",
    "video_url": "https://video.xx.fbcdn.net/v.mp4", "thumbnail_url": "https://scontent.xx.fbcdn.net/t.jpg",
}
WA_POST = {
    "source_url": "https://www.facebook.com/123/posts/456", "source_id": "456", "source_type": "post",
    "body": "Our new branch is open", "headline": "", "media_type": "image",
    "image_url": "https://scontent.xx.fbcdn.net/p.jpg",
}

MS_AD = {
    "ref": "spring", "ad_id": "6045246247433", "source": "ADS", "type": "OPEN_THREAD",
    "ads_context_data": {"ad_title": "Spring sale", "photo_url": "https://scontent.xx.fbcdn.net/s.jpg",
                         "post_id": "1234_5678"},
}
MS_LINK = {"ref": "from-website", "source": "SHORTLINK", "type": "OPEN_THREAD"}
MS_PLUGIN = {"ref": "", "source": "CUSTOMER_CHAT_PLUGIN", "type": "OPEN_THREAD",
             "referer_uri": "https://alkhora.example/products"}


class TestWhatsApp(unittest.TestCase):
    def test_image_ad(self):
        ref = AR.from_whatsapp(WA_IMAGE_AD)
        self.assertEqual(set(ref) - {"ctwa_clid"}, KEYS)
        self.assertEqual(ref["source"], "ad")
        self.assertEqual(ref["headline"], "Chat with us")
        self.assertEqual(ref["body"], "Summer Succulents are here!")
        self.assertEqual(ref["url"], "https://fb.me/3cr4Wqqkv")
        self.assertEqual(ref["ad_id"], "120226305854810726")
        self.assertEqual(ref["media_type"], "image")
        self.assertEqual(ref["image_url"], "")  # never Meta's CDN link
        self.assertEqual(ref["ref"], "")
        self.assertTrue(ref["ctwa_clid"].startswith("Aff-"))
        self.assertEqual(AR.whatsapp_preview(WA_IMAGE_AD), WA_IMAGE_AD["image_url"])

    def test_video_ad_uses_thumbnail(self):
        ref = AR.from_whatsapp(WA_VIDEO_AD)
        self.assertEqual((ref["media_type"], ref["headline"]), ("video", "New collection"))
        self.assertEqual(AR.whatsapp_preview(WA_VIDEO_AD), "https://scontent.xx.fbcdn.net/t.jpg")

    def test_post(self):
        ref = AR.from_whatsapp(WA_POST)
        self.assertEqual((ref["source"], ref["headline"], ref["ad_id"]), ("post", "", "456"))

    def test_caps_and_unsafe_url(self):
        ref = AR.from_whatsapp(dict(WA_IMAGE_AD, headline="h" * 300, body="b" * 2000,
                                    source_url="javascript:alert(1)", source_type="weird"))
        self.assertEqual((len(ref["headline"]), len(ref["body"])), (200, 1000))
        self.assertEqual((ref["url"], ref["source"]), ("", "other"))

    def test_garbage(self):
        for raw in (None, "", "not json", [], 5, {}, {"foo": 1}, {"source_type": "x"},
                    {"headline": "   ", "media_type": "gif"}):
            self.assertIsNone(AR.from_whatsapp(raw), raw)

    def test_json_string_accepted(self):
        self.assertEqual(AR.from_whatsapp(json.dumps(WA_POST))["source"], "post")


class TestMessenger(unittest.TestCase):
    def test_ad(self):
        ref = AR.from_messenger(MS_AD)
        self.assertEqual(set(ref), KEYS)
        self.assertEqual((ref["source"], ref["headline"], ref["ad_id"], ref["ref"]),
                         ("ad", "Spring sale", "6045246247433", "spring"))
        self.assertEqual((ref["url"], ref["body"], ref["media_type"]), ("", "", "image"))
        self.assertEqual(AR.messenger_preview(MS_AD), "https://scontent.xx.fbcdn.net/s.jpg")

    def test_shortlink(self):
        ref = AR.from_messenger(MS_LINK)
        self.assertEqual((ref["source"], ref["ref"], ref["headline"]), ("link", "from-website", ""))

    def test_plugin_keeps_referer(self):
        ref = AR.from_messenger(MS_PLUGIN)
        self.assertEqual((ref["source"], ref["url"]), ("other", "https://alkhora.example/products"))

    def test_sources(self):
        self.assertEqual(AR.messenger_source("ADS"), "ad")
        self.assertEqual(AR.messenger_source("SHORTLINK"), "link")
        self.assertEqual(AR.messenger_source("FB_POST"), "post")
        self.assertEqual(AR.messenger_source("", has_ad=True), "ad")
        self.assertEqual(AR.messenger_source("CUSTOMER_CHAT_PLUGIN"), "other")

    def test_video_thumbnail(self):
        raw = {"source": "ADS", "ad_id": "1", "ads_context_data": {"video_url": "https://cdn/t.jpg"}}
        self.assertEqual(AR.from_messenger(raw)["media_type"], "video")
        self.assertEqual(AR.messenger_preview(raw), "https://cdn/t.jpg")

    def test_garbage(self):
        for raw in (None, "x", {}, {"type": "OPEN_THREAD"}, {"source": "SOMETHING"}, ["ADS"]):
            self.assertIsNone(AR.from_messenger(raw), raw)


def page(*events):
    return {"object": "page", "entry": [{"id": "1111", "time": 1, "messaging": list(events)}]}


def customer(**body):
    return dict({"sender": {"id": "2222"}, "recipient": {"id": "1111"}, "timestamp": 1700000000000}, **body)


class TestMessengerEvents(unittest.TestCase):
    def test_message_referral(self):
        (e,) = EV.parse(page(customer(message={"mid": "m1", "text": "Is it in stock?", "referral": MS_AD})))
        self.assertEqual((e["kind"], e["text"], e["referral"]), ("message", "Is it in stock?", MS_AD))

    def test_message_without_referral_has_no_key(self):
        (e,) = EV.parse(page(customer(message={"mid": "m2", "text": "hi"})))
        self.assertNotIn("referral", e)

    def test_postback_referral(self):
        (e,) = EV.parse(page(customer(postback={"title": "Get Started", "payload": "GET_STARTED",
                                                "referral": MS_LINK})))
        self.assertEqual((e["kind"], e["text"], e["referral"]), ("postback", "Get Started", MS_LINK))

    def test_standalone_referral(self):
        (e,) = EV.parse(page(customer(referral=MS_AD)))
        self.assertEqual(e, {"psid": "2222", "page_id": "1111", "timestamp": 1700000000000,
                             "kind": "referral", "referral": MS_AD})

    def test_empty_standalone_dropped(self):
        self.assertEqual(EV.parse(page(customer(referral={}), customer(referral="x"))), [])


class TestStored(unittest.TestCase):
    def test_public_round_trip(self):
        ref = dict(AR.from_whatsapp(WA_IMAGE_AD), channel="WhatsApp", image_url="/private/files/a.jpg")
        out = AR.public(AR.dump(ref))
        self.assertEqual(set(out), KEYS)
        self.assertEqual(out["image_url"], "/private/files/a.jpg")
        self.assertEqual(AR.public(json.dumps(AR.dump(ref)))["headline"], "Chat with us")  # double-encoded

    def test_public_garbage(self):
        for raw in (None, "", "{", "[]", "null", '"text"', 7, {"source": "ad"} and "{}"):
            self.assertIsNone(AR.public(raw), raw)
        out = AR.public({"source": "evil", "headline": "x", "url": "javascript:x", "media_type": "gif"})
        self.assertEqual((out["source"], out["url"], out["media_type"]), ("other", "", ""))

    def test_conv_ad(self):
        ref = AR.from_messenger(MS_AD)
        stored = AR.dump(AR.conv_ad(ref, "2026-10-05 09:15:42.123456"))
        ad = AR.public_ad(stored)
        self.assertEqual(set(ad), {"source", "headline", "body", "url", "image_url", "ad_id", "at"})
        self.assertEqual((ad["headline"], ad["at"]), ("Spring sale", "2026-10-05 09:15:42"))
        self.assertIsNone(AR.public_ad("garbage"))

    def test_note_text(self):
        self.assertEqual(AR.note_text(AR.from_messenger(MS_AD)), "Opened from ad: Spring sale")
        self.assertEqual(AR.note_text({"source": "ad", "headline": ""}), "Opened from an ad")
        self.assertEqual(AR.note_text(AR.from_messenger(MS_LINK)), "Opened from a link")
        self.assertEqual(AR.note_text({"source": "post"}), "Opened from a post")
        self.assertEqual(AR.note_text(AR.from_messenger(MS_PLUGIN)), "Opened from a link")


class TestPush(unittest.TestCase):
    BASE = ("💬 رسالة واتساب • WhatsApp", "Ali\nIs it in stock?", {"type": "whatsapp_message"})

    def test_line_and_flag(self):
        title, body, data = AR.add_to_push(*self.BASE, ref=AR.from_whatsapp(WA_IMAGE_AD))
        self.assertEqual(title, self.BASE[0])
        self.assertEqual(body, "Ali\nIs it in stock?\nAd: Chat with us")
        self.assertEqual(data, {"type": "whatsapp_message", "ad": "1"})
        self.assertNotIn("ad", self.BASE[2])  # input untouched

    def test_bilingual(self):
        _t, body, _d = AR.add_to_push(*self.BASE, ref={"source": "ad", "headline": "Sale"}, bilingual=True)
        self.assertTrue(body.endswith("\nإعلان: Sale\nAd: Sale"))

    def test_no_headline_and_no_ref(self):
        self.assertTrue(AR.add_to_push(*self.BASE, ref=AR.from_messenger(MS_LINK))[1].endswith("\nFrom a link"))
        self.assertEqual(AR.add_to_push(*self.BASE, ref=None), self.BASE)

    def test_long_headline_trimmed(self):
        self.assertEqual(len(AR.ad_line({"source": "ad", "headline": "x" * 300})), len("Ad: ") + 80)


def _payload(*messages):
    return {"object": "whatsapp_business_account", "entry": [{"id": "W", "changes": [
        {"field": "messages", "value": {"messaging_product": "whatsapp", "messages": list(messages)}}]}]}


class TestBackfillWalker(unittest.TestCase):
    def test_walks_and_skips(self):
        payload = _payload(
            {"id": "wamid.A", "type": "text", "text": {"body": "hi"}, "referral": WA_IMAGE_AD},
            {"id": "wamid.B", "type": "text", "text": {"body": "plain"}},
            {"id": "wamid.C", "type": "image", "referral": {"junk": True}},
            {"type": "text", "referral": WA_POST},  # no id
            "garbage",
        )
        found = AR.referrals_in_payload(payload)
        self.assertEqual(set(found), {"wamid.A"})
        ref, preview = found["wamid.A"]
        self.assertEqual((ref["headline"], preview), ("Chat with us", WA_IMAGE_AD["image_url"]))

    def test_double_encoded_and_malformed(self):
        payload = _payload({"id": "wamid.D", "referral": WA_VIDEO_AD})
        self.assertEqual(set(AR.referrals_in_payload(json.dumps(json.dumps(payload)))), {"wamid.D"})
        self.assertEqual(set(AR.referrals_in_payload(json.dumps(payload))), {"wamid.D"})
        for raw in (None, "", "{not json", "[]", {"entry": "x"}, {"entry": [{"changes": [None]}]}):
            self.assertEqual(AR.referrals_in_payload(raw), {})

    def test_entry_as_dict(self):
        payload = _payload({"id": "wamid.E", "referral": WA_POST})
        payload["entry"] = payload["entry"][0]
        self.assertEqual(set(AR.referrals_in_payload(payload)), {"wamid.E"})


if __name__ == "__main__":
    unittest.main()

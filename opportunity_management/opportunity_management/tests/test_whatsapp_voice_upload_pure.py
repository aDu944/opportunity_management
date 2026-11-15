"""
Bench-free tests for the voice-note media upload (whatsapp_voice_upload) and
the override's "upload first, link as fallback" send:

    python3 opportunity_management/opportunity_management/tests/test_whatsapp_voice_upload_pure.py
"""

import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_HERE, "tests"))
from test_whatsapp_round3_pure import P, _load, override  # noqa: E402  (installs the frappe stubs)

VU = _load("opportunity_management.opportunity_management.whatsapp_voice_upload", "whatsapp_voice_upload.py")


class TestPure(unittest.TestCase):
    def test_mime_by_extension(self):
        self.assertEqual(VU.media_mime("/files/voice_1.ogg"), "audio/ogg")
        self.assertEqual(VU.media_mime("https://x/files/a%20b.M4A?x=1"), "audio/mp4")
        self.assertEqual(VU.media_mime("/files/clip.webm"), "")
        self.assertEqual(VU.media_mime(None), "")

    def test_endpoint(self):
        self.assertEqual(
            VU.media_endpoint("https://graph.facebook.com/", "v26.0", "136520"),
            "https://graph.facebook.com/v26.0/136520/media",
        )

    def test_upload_fields_bare_mime(self):
        data, files = VU.upload_fields("voice_1.ogg", b"OggS....", "audio/ogg")
        self.assertEqual(data, {"messaging_product": "whatsapp", "type": "audio/ogg"})
        self.assertEqual(files, {"file": ("voice_1.ogg", b"OggS....", "audio/ogg")})
        with self.assertRaises(ValueError):
            VU.upload_fields("v.ogg", b"", "audio/ogg")
        with self.assertRaises(ValueError):
            VU.upload_fields("v.ogg", b"x" * (VU.MAX_BYTES + 1), "audio/ogg")

    def test_media_id_from(self):
        self.assertEqual(VU.media_id_from({"id": " 1234 "}), "1234")
        with self.assertRaises(ValueError) as ctx:
            VU.media_id_from({"error": {"message": "Media upload error", "code": 131053,
                                        "error_data": {"details": "on processing it is of type application/octet-stream"}}})
        self.assertIn("application/octet-stream", str(ctx.exception))
        with self.assertRaises(ValueError):
            VU.media_id_from(None)

    def test_upload_without_bench_falls_back(self):
        # The stub frappe has no WhatsApp Account: "" means "send the link".
        self.assertEqual(VU.upload_media("ALKHORA", "/files/v.ogg"), "")
        self.assertEqual(VU.upload_media("ALKHORA", "/files/v.webm"), "")
        self.assertEqual(VU.upload_media("", "/files/v.ogg"), "")


class TestVoiceBody(unittest.TestCase):
    def test_id_wins_over_link(self):
        body = P.message_body("voice", "964", {"voice": True}, link="https://e/v.ogg", media_id="M1")
        self.assertEqual(body["audio"], {"id": "M1", "voice": True})
        body = P.message_body("voice", "964", {"voice": True}, link="https://e/v.ogg", media_id="")
        self.assertEqual(body["audio"], {"link": "https://e/v.ogg", "voice": True})


class TestOverrideVoice(unittest.TestCase):
    def _doc(self, **fields):
        base = {"type": "Outgoing", "template": None, "message_type": "Manual", "to": "+9647701234567",
                "is_reply": 0, "reply_to_message_id": None, "attach": "/files/v.ogg", "custom_is_voice": 1,
                "whatsapp_account": "ALKHORA", "content_type": "audio",
                "custom_payload": json.dumps({"kind": "voice", "voice": True})}
        base.update(fields)
        return override.WhatsAppMessage(**base)

    def test_uploaded_voice_goes_by_id(self):
        seen = []
        original = VU.upload_media
        VU.upload_media = lambda account, url: seen.append((account, url)) or "MEDIA-1"
        try:
            doc = self._doc()
            doc.send_outgoing()
        finally:
            VU.upload_media = original
        self.assertEqual(seen, [("ALKHORA", "/files/v.ogg")])
        self.assertEqual(doc.status, "Success")
        self.assertEqual(doc.sent[0]["audio"], {"id": "MEDIA-1", "voice": True})

    def test_failed_upload_sends_the_link(self):
        original = VU.upload_media
        VU.upload_media = lambda account, url: ""
        try:
            doc = self._doc()
            doc.send_outgoing()
        finally:
            VU.upload_media = original
        self.assertEqual(doc.sent[0]["audio"], {"link": "https://erp.example/files/v.ogg", "voice": True})

    def test_upload_crash_sends_the_link(self):
        original = VU.upload_media

        def boom(account, url):
            raise RuntimeError("network")

        VU.upload_media = boom
        try:
            doc = self._doc()
            doc.send_outgoing()
        finally:
            VU.upload_media = original
        self.assertEqual(doc.sent[0]["audio"]["link"], "https://erp.example/files/v.ogg")


if __name__ == "__main__":
    unittest.main(verbosity=1)

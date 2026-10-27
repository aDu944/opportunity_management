"""
Bench-free tests for `opportunity_pure` ("Create opportunity" from a chat:
name shape, party resolution, attachment filtering, parse row mapping).

    python3 opportunity_management/opportunity_management/tests/test_opportunity_pure.py

The module has no `frappe` import, so it is loaded straight off disk.
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "opportunity_pure.py")
    spec = importlib.util.spec_from_file_location("opportunity_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()


class TestNameShape(unittest.TestCase):
    def test_good_names(self):
        for name in ("INQ-512-WA-0-26", "INQ-530-BOC-7092-26", "ER-036-26"):
            self.assertTrue(P.is_well_formed_name(name), name)

    def test_empty_abr(self):
        self.assertFalse(P.is_well_formed_name("Inq. 512--0-26"))
        self.assertFalse(P.is_well_formed_name("INQ-512--0-26"))

    def test_none_part_and_edges(self):
        self.assertFalse(P.is_well_formed_name("INQ-512-None-0-26"))
        self.assertFalse(P.is_well_formed_name("INQ-512-WA-0-"))
        self.assertFalse(P.is_well_formed_name(""))
        self.assertFalse(P.is_well_formed_name(None))

    def test_series_uses_abr(self):
        self.assertTrue(P.series_uses_abr("INQ-.###.-.{custom_abr}.-.{custom_tender_no}.-.YY."))
        self.assertFalse(P.series_uses_abr("ER-.###.-.YY."))


class TestParty(unittest.TestCase):
    def test_customer_first(self):
        self.assertEqual(P.resolve_party("Cu", "L-1"), ("Customer", "Cu"))

    def test_lead_next(self):
        self.assertEqual(P.resolve_party(None, "L-1"), ("Lead", "L-1"))
        self.assertEqual(P.resolve_party("", "L-1"), ("Lead", "L-1"))

    def test_none(self):
        self.assertEqual(P.resolve_party(None, None), (None, None))

    def test_source_by_channel(self):
        self.assertEqual(P.lead_source_for_channel("Messenger"), "Messenger")
        self.assertEqual(P.lead_source_for_channel("WhatsApp"), "WhatsApp")
        self.assertEqual(P.lead_source_for_channel(None), "WhatsApp")

    def test_title(self):
        self.assertEqual(P.title_suggestion("Ali"), "Ali — WhatsApp inquiry")
        self.assertEqual(P.title_suggestion("Ali", "Messenger"), "Ali — Messenger inquiry")
        self.assertEqual(P.title_suggestion(""), "WhatsApp inquiry")


class TestOptions(unittest.TestCase):
    SERIES = "INQ-.###.-.{custom_abr}.-.{custom_tender_no}.-.YY.\nFB-.###.-.YY.\nER-.###.-.YY."

    def test_split(self):
        self.assertEqual(P.split_options("\nALKHORA\nDAMAS\n\nALKHORA"), ["ALKHORA", "DAMAS"])

    def test_default_series_is_abr_one(self):
        opts = P.split_options(self.SERIES)
        self.assertTrue(P.default_series(opts, "ER-.###.-.YY.").startswith("INQ-"))
        self.assertEqual(P.default_series(["ER-.###.-.YY."], "ER-.###.-.YY."), "ER-.###.-.YY.")
        self.assertIsNone(P.default_series([], None))

    def test_pick_default(self):
        self.assertEqual(P.pick_default(["DAMAS", "ALKHORA"], "ALKHORA"), "ALKHORA")
        self.assertEqual(P.pick_default(["DAMAS"], "ALKHORA"), "DAMAS")

    def test_parse_list(self):
        self.assertEqual(P.parse_list('["a@x.com", "b@x.com", "a@x.com"]'), ["a@x.com", "b@x.com"])
        self.assertEqual(P.parse_list("a@x.com, b@x.com"), ["a@x.com", "b@x.com"])
        self.assertEqual(P.parse_list(["a"]), ["a"])
        self.assertEqual(P.parse_list(None), [])


class TestAttachments(unittest.TestCase):
    def test_filtering(self):
        rows = [
            {"name": "m1", "content_type": "document", "attach": "/private/files/rfq.pdf",
             "file_size": 2048},
            {"name": "m2", "content_type": "image", "attach": "/private/files/a.jpeg"},
            {"name": "m3", "content_type": "document", "attach": "/files/sheet.xlsx"},
            {"name": "m4", "content_type": "audio", "attach": "/files/v.ogg"},
            {"name": "m5", "content_type": "image", "attach": ""},
            {"name": "m6", "content_type": "document", "attach": "/files/x",
             "file_name": "Quote.PDF"},
        ]
        out = P.filter_attachments(rows)
        self.assertEqual([a["message"] for a in out], ["m1", "m2", "m6"])
        self.assertEqual(out[0], {"message": "m1", "filename": "rfq.pdf",
                                  "content_type": "application/pdf", "size": 2048})
        self.assertEqual(out[1]["content_type"], "image/jpeg")
        self.assertEqual(out[2]["filename"], "Quote.PDF")

    def test_kind(self):
        self.assertEqual(P.attachment_kind("a.webp"), "image")
        self.assertEqual(P.attachment_kind("a.pdf?x=1"), "pdf")
        self.assertIsNone(P.attachment_kind("a.docx", "document"))
        self.assertEqual(P.attachment_kind("noext", "image"), "image")


class TestRowMapping(unittest.TestCase):
    ROW = {
        "item_name": "Bearing", "description": "SKF 6038", "qty": 2, "uom": "Pcs",
        "custom_part_number": "6038", "custom_manufacturer": "SKF", "brand": None,
        "custom_duty_rate_pct": 0, "custom_hs_code": "84821000", "custom_deposit_pct": 5,
        "rate": 0, "amount": 0, "_confidence": 0.9, "_brand_match": None,
    }

    def test_maps_like_erp_button(self):
        out = P.map_parsed_row(self.ROW)
        self.assertEqual(out["item_name"], "Bearing")
        self.assertEqual(out["custom_duty_rate_pct"], 0)  # a 0% duty is kept
        self.assertNotIn("brand", out)
        self.assertNotIn("_confidence", out)
        self.assertNotIn("custom_deposit_pct", out)
        self.assertEqual((out["rate"], out["amount"]), (0, 0))

    def test_missing_fields_dropped_and_defaults(self):
        out = P.map_parsed_row({"description": "x", "qty": 0}, has_field=lambda f: f != "description")
        self.assertNotIn("description", out)
        self.assertEqual((out["qty"], out["uom"]), (1, "Nos"))

    def test_metadata(self):
        meta = P.parse_metadata({"items": [{}, {}], "notes": "n", "cached": True})
        self.assertEqual((meta["items_found"], meta["notes"], meta["cached"]), (2, "n", True))
        self.assertIsNone(meta["title"])


if __name__ == "__main__":
    unittest.main()

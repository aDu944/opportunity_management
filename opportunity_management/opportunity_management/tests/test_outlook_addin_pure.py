"""
Bench-free tests for `outlook_addin_pure` (Outlook add-in OAuth client values
and the public config the task pane reads).

    python3 opportunity_management/opportunity_management/tests/test_outlook_addin_pure.py

The module has no `frappe` import, so it is loaded straight off disk.
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "outlook_addin_pure.py")
    spec = importlib.util.spec_from_file_location("outlook_addin_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()
CB = "https://bms.alkhora.com/assets/opportunity_management/outlook/v1/auth-callback.html"


class NormalizeSiteUrl(unittest.TestCase):
    def test_http_behind_proxy_becomes_https(self):
        self.assertEqual(P.normalize_site_url("http://bms.alkhora.com"), "https://bms.alkhora.com")

    def test_trailing_slash_and_path_dropped(self):
        self.assertEqual(P.normalize_site_url("https://bms.alkhora.com/app/opportunity/"), "https://bms.alkhora.com")

    def test_bare_host(self):
        self.assertEqual(P.normalize_site_url("bms.alkhora.com"), "https://bms.alkhora.com")

    def test_localhost_keeps_http_and_port(self):
        self.assertEqual(P.normalize_site_url("http://localhost:8000"), "http://localhost:8000")

    def test_credentials_stripped(self):
        self.assertEqual(P.normalize_site_url("https://u:p@bms.alkhora.com"), "https://bms.alkhora.com")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            P.normalize_site_url("  ")


class ClientValues(unittest.TestCase):
    def test_redirect_uri(self):
        self.assertEqual(P.redirect_uri("http://bms.alkhora.com"), CB)

    def test_fresh_client(self):
        v = P.client_values("http://bms.alkhora.com")
        self.assertEqual(v["redirect_uris"], CB)
        self.assertEqual(v["default_redirect_uri"], CB)
        self.assertEqual(v["grant_type"], "Authorization Code")
        self.assertEqual(v["response_type"], "Code")
        self.assertEqual(v["skip_authorization"], 1)

    def test_existing_uris_kept_without_duplicates(self):
        old = "https://bms.alkhora.com/assets/opportunity_management/outlook/v0/auth-callback.html"
        v = P.client_values("https://bms.alkhora.com", existing_redirects=f"{old} {CB}")
        self.assertEqual(v["redirect_uris"], f"{old} {CB}")

    def test_existing_uri_appended(self):
        old = "https://x.example/cb"
        self.assertEqual(P.merge_redirect_uris(old, CB), f"{old} {CB}")


class PublicConfig(unittest.TestCase):
    def test_endpoints(self):
        c = P.public_config("http://bms.alkhora.com", "abc123")
        self.assertEqual(c["client_id"], "abc123")
        self.assertEqual(c["redirect_uri"], CB)
        self.assertEqual(c["token_url"], "https://bms.alkhora.com/api/method/frappe.integrations.oauth2.get_token")
        self.assertTrue(c["authorize_url"].startswith("https://bms.alkhora.com/"))


if __name__ == "__main__":
    unittest.main()

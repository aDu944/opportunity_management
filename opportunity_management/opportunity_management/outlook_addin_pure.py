"""
Frappe-free helpers for the Outlook add-in (see outlook_addin.py).

The add-in is a static Office.js task pane served from this app's public
folder and signs users in with ERPNext's own OAuth server (Authorization
Code + PKCE, no client secret). Everything here is plain string logic so it
can be unit-tested without a bench.

Asset layout: /assets/opportunity_management/outlook/<ASSET_VERSION>/...
Cloudflare and nginx cache /assets for a year, so a changed file needs a new
version folder (and the manifest + OAuth redirect URI move with it).
"""

from urllib.parse import urlparse

APP_NAME = "Outlook Add-in"
ASSET_VERSION = "v3"
ASSET_ROOT = "/assets/opportunity_management/outlook"
SCOPES = "all openid"
CALLBACK_FILE = "auth-callback.html"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def normalize_site_url(url: str) -> str:
    """Public https origin of the site, without a trailing slash.

    `frappe.utils.get_url()` reports http:// behind Frappe Cloud's proxy, but
    Outlook only loads https pages, so anything but a local host is forced to
    https. Paths and query strings are dropped: only the origin matters.
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("site URL is empty")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise ValueError(f"site URL has no host: {url!r}")
    scheme = "http" if host in _LOCAL_HOSTS and parsed.scheme == "http" else "https"
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    return f"{scheme}://{netloc}"


def asset_base(site_url: str, version: str = ASSET_VERSION) -> str:
    return f"{normalize_site_url(site_url)}{ASSET_ROOT}/{version}"


def redirect_uri(site_url: str, version: str = ASSET_VERSION) -> str:
    return f"{asset_base(site_url, version)}/{CALLBACK_FILE}"


def merge_redirect_uris(existing: str, wanted: str, delimiter: str = " ") -> str:
    """Add `wanted` to a delimiter-separated redirect URI list, keeping the
    order and any URIs already registered (older asset versions keep working
    while users still have the old manifest)."""
    uris = [u for u in (existing or "").split(delimiter) if u]
    if wanted not in uris:
        uris.append(wanted)
    return delimiter.join(uris)


def client_values(site_url: str, existing_redirects: str = "", delimiter: str = " ") -> dict:
    """Field values the OAuth Client record must have."""
    wanted = redirect_uri(site_url)
    return {
        "app_name": APP_NAME,
        "skip_authorization": 1,
        "scopes": SCOPES,
        "grant_type": "Authorization Code",
        "response_type": "Code",
        "default_redirect_uri": wanted,
        "redirect_uris": merge_redirect_uris(existing_redirects, wanted, delimiter),
    }


def public_config(site_url: str, client_id: str) -> dict:
    """What the task pane needs to start the sign-in (all public values)."""
    site = normalize_site_url(site_url)
    return {
        "site": site,
        "client_id": client_id,
        "redirect_uri": redirect_uri(site),
        "scopes": SCOPES,
        "authorize_url": f"{site}/api/method/frappe.integrations.oauth2.authorize",
        "token_url": f"{site}/api/method/frappe.integrations.oauth2.get_token",
        "revoke_url": f"{site}/api/method/frappe.integrations.oauth2.revoke_token",
        "asset_version": ASSET_VERSION,
    }

"""
`/inbox` → the current web Team Inbox build, resolved PER REQUEST.

The build lives in a versioned folder under public/inbox/ (everything under
/assets is cached for a year by nginx and Cloudflare, so each build needs a
new path) and public/inbox/CURRENT names the live one. Reading CURRENT here,
at request time, means deploying a new build is `git pull` only — no web
restart — unlike a `website_redirects` entry, which is fixed at import.
"""

import os

import frappe

no_cache = 1
ASSET_BASE = "/assets/opportunity_management/inbox"


def current_index():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(here, "public", "inbox", "CURRENT")) as fh:
            version = fh.read().strip()
    except OSError:
        version = ""
    if not version or "/" in version or ".." in version:
        return f"{ASSET_BASE}/index.html"
    return f"{ASSET_BASE}/{version}/index.html"


def get_context(context):
    frappe.local.flags.redirect_location = current_index()
    raise frappe.Redirect

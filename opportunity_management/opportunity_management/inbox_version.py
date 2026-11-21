"""
Which web Team Inbox build is current (`public/inbox/CURRENT`).

`www/inbox.py` redirects `/inbox` to it. The build's own index.html also
asks `current_inbox_version` at start-up and, when it is not the current
build, replaces itself with `/inbox`: everything under /assets is cached for
a year by nginx and Cloudflare, so a tab restored on an old build's URL, a
bookmark or a history entry would otherwise keep showing the old UI forever
(21 Nov 2026: the sidebar deploy was invisible for that reason).
"""

import os

import frappe

ASSET_BASE = "/assets/opportunity_management/inbox"


def read_current(path) -> str:
    """The version named in a CURRENT file, "" when missing or unsafe."""
    try:
        with open(path) as fh:
            version = fh.read().strip()
    except OSError:
        return ""
    if not version or "/" in version or ".." in version or version.startswith("."):
        return ""
    return version


def current_version() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return read_current(os.path.join(os.path.dirname(here), "public", "inbox", "CURRENT"))


def current_index() -> str:
    version = current_version()
    return f"{ASSET_BASE}/{version}/index.html" if version else f"{ASSET_BASE}/index.html"


@frappe.whitelist(allow_guest=True)
def current_inbox_version():
    """The current build's folder name; a public string, never cached."""
    frappe.local.response.headers = {"Cache-Control": "no-store"}
    return current_version()

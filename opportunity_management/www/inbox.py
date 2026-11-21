"""
`/inbox` → the current web Team Inbox build, resolved PER REQUEST.

The build lives in a versioned folder under public/inbox/ (everything under
/assets is cached for a year by nginx and Cloudflare, so each build needs a
new path) and public/inbox/CURRENT names the live one. Reading CURRENT here,
at request time, means deploying a new build is `git pull` only — no web
restart — unlike a `website_redirects` entry, which is fixed at import.
"""

from opportunity_management.opportunity_management.inbox_version import current_index  # noqa: F401

import frappe

no_cache = 1


def get_context(context):
    frappe.local.flags.redirect_location = current_index()
    raise frappe.Redirect

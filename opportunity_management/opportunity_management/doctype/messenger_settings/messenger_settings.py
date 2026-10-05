# Singleton configuration for the Messenger channel of the team inbox
# (messenger_contract.md). Read through inbox_channels.messenger_settings(),
# cached on frappe.local per request. `test_connection` is the form's
# "Test connection" button: GET /me with the Page token.

import frappe
from frappe import _
from frappe.model.document import Document


class MessengerSettings(Document):
    def validate(self):
        self.page_id = (self.page_id or "").strip()
        self.graph_version = (self.graph_version or "").strip() or "v25.0"
        if not self.graph_version.startswith("v"):
            self.graph_version = "v" + self.graph_version

    def on_update(self):
        try:
            frappe.local._messenger_settings = None
        except Exception:
            pass


@frappe.whitelist()
def test_connection():
    """Manager-only check of the stored token. `{ok, id, name, warning}` or
    `{ok: False, error}`.

    Three kinds of token get pasted here:
      * the Page's own token — what the inbox needs (`/me` is the Page);
      * a Page token without `pages_read_engagement` — `/me` fails with #100
        although messaging works, so fall back to a `pages_messaging` call;
      * a user / system-user token — `/me` is a PERSON, and `me/messages`
        would fail. Exchange it for the Page's token (`me/accounts`), which
        inherits the system user's "never expires".
    """
    roles = set(frappe.get_roles())
    if not roles & {"System Manager", "Messenger Manager"}:
        frappe.throw(_("Only a Messenger Manager can test the connection"), frappe.PermissionError)
    from opportunity_management.opportunity_management import messenger_api as API

    settings = frappe.get_single("Messenger Settings")
    try:
        # `category` exists only on a Page: a user / system-user token fails
        # here (#100 nonexisting field), which is how the two are told apart.
        # (`metadata=1` is not returned for system users, so it cannot be used.)
        me = API.graph_request(settings, "GET", "me", params={"fields": "id,name,category"})
    except API.GraphError as exc:
        try:
            person = API.graph_request(settings, "GET", "me", params={"fields": "id,name"})
        except API.GraphError:
            person = None
        if person and person.get("id"):
            # Readable as a plain node but not as a Page → a person's token.
            try:
                API.graph_request(settings, "GET", "me/messenger_profile", params={"fields": "greeting"})
            except API.GraphError:
                return _adopt_page_token(API, settings, person)
        try:
            API.graph_request(settings, "GET", "me/messenger_profile", params={"fields": "greeting"})
        except API.GraphError as exc2:
            return {"ok": False, "error": str(exc2) or str(exc)}
        return {
            "ok": True,
            "id": settings.page_id or None,
            "name": settings.page_name or None,
            "warning": _(
                "The token works for messaging. The Page name could not be read because the "
                "token lacks the pages_read_engagement permission; chats do not need it. "
                "Type the Page name yourself and make sure the Page ID is right."
            ),
        }

    if me.get("name") and me.get("name") != settings.page_name:
        frappe.db.set_single_value("Messenger Settings", "page_name", me["name"])
    warning = ""
    if settings.page_id and me.get("id") and str(me["id"]) != str(settings.page_id):
        warning = _("The token belongs to Page {0}, not the configured Page ID {1}").format(
            me["id"], settings.page_id
        )
    return {"ok": True, "id": me.get("id"), "name": me.get("name"), "warning": warning}


def _adopt_page_token(API, settings, me):
    """The stored token is a person's (user or system user). Find the Page it
    can act for and store THAT Page's token instead."""
    who = me.get("name") or me.get("id") or ""
    try:
        res = API.graph_request(
            settings, "GET", "me/accounts", params={"fields": "id,name,access_token", "limit": "100"}
        )
    except API.GraphError as exc:
        return {"ok": False, "error": _("This is the token of {0}, not of a Page, and its Pages could not be listed: {1}").format(who, str(exc))}
    pages = [p for p in (res.get("data") or []) if p.get("id") and p.get("access_token")]
    if not pages:
        return {
            "ok": False,
            "error": _(
                "This is the token of {0}, not of a Page, and it has no Pages. In Meta Business "
                "Settings, give this system user the Facebook Page as an asset (full control), "
                "then generate the token again with pages_show_list, pages_messaging and "
                "pages_manage_metadata ticked."
            ).format(who),
        }
    wanted = (settings.page_id or "").strip()
    page = next((p for p in pages if str(p["id"]) == wanted), None)
    if page is None and len(pages) == 1:
        page = pages[0]
    if page is None:
        listing = ", ".join("{0} ({1})".format(p.get("name") or "?", p["id"]) for p in pages)
        return {
            "ok": False,
            "error": _(
                "This token can act for several Pages: {0}. Put the right Page's number in "
                "Page ID, save, and test again."
            ).format(listing),
        }
    settings.page_access_token = page["access_token"]
    settings.page_id = str(page["id"])
    settings.page_name = page.get("name") or settings.page_name
    settings.save(ignore_permissions=True)
    return {
        "ok": True,
        "id": page["id"],
        "name": page.get("name"),
        "warning": _(
            "You pasted the token of {0}. It has been replaced with the token of the Page itself, "
            "which is what Messenger needs; the Page ID and name were filled in."
        ).format(who),
    }


SUBSCRIBED_FIELDS = (
    "messages", "message_echoes", "message_deliveries", "message_reads",
    "message_reactions", "messaging_postbacks", "messaging_referrals",
)


@frappe.whitelist()
def subscribe_page():
    """Manager-only: subscribe the Page to this app's Messenger webhook
    fields (the "Add subscriptions" step in the Meta dashboard). Needs the
    Page token to carry `pages_manage_metadata`. Returns what Meta now lists."""
    roles = set(frappe.get_roles())
    if not roles & {"System Manager", "Messenger Manager"}:
        frappe.throw(_("Only a Messenger Manager can subscribe the Page"), frappe.PermissionError)
    from opportunity_management.opportunity_management import messenger_api as API

    settings = frappe.get_single("Messenger Settings")
    try:
        API.graph_request(
            settings, "POST", "me/subscribed_apps",
            params={"subscribed_fields": ",".join(SUBSCRIBED_FIELDS)},
        )
        listed = API.graph_request(settings, "GET", "me/subscribed_apps")
    except API.GraphError as exc:
        return {"ok": False, "error": str(exc)}
    fields = sorted({f for app in (listed.get("data") or []) for f in (app.get("subscribed_fields") or [])})
    return {"ok": True, "fields": fields}

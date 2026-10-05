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
    """Manager-only: who does the Page token belong to? `{ok, id, name}` or
    `{ok: False, error}` with Meta's reason."""
    roles = set(frappe.get_roles())
    if not roles & {"System Manager", "Messenger Manager"}:
        frappe.throw(_("Only a Messenger Manager can test the connection"), frappe.PermissionError)
    from opportunity_management.opportunity_management import messenger_api as API

    settings = frappe.get_single("Messenger Settings")
    try:
        me = API.graph_request(settings, "GET", "me", params={"fields": "id,name"})
    except API.GraphError as exc:
        # Reading the Page node needs `pages_read_engagement`, which a token
        # generated for Messenger often lacks (#100) — and which chats do not
        # need. Fall back to a call that only needs `pages_messaging`.
        try:
            API.graph_request(settings, "GET", "me/messenger_profile", params={"fields": "greeting"})
        except API.GraphError as exc2:
            return {"ok": False, "error": str(exc2) if str(exc2) != str(exc) else str(exc)}
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

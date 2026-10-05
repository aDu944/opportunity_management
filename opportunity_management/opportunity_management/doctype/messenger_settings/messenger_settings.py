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
        return {"ok": False, "error": str(exc)}
    if me.get("name") and me.get("name") != settings.page_name:
        frappe.db.set_single_value("Messenger Settings", "page_name", me["name"])
    warning = ""
    if settings.page_id and me.get("id") and str(me["id"]) != str(settings.page_id):
        warning = _("The token belongs to Page {0}, not the configured Page ID {1}").format(
            me["id"], settings.page_id
        )
    return {"ok": True, "id": me.get("id"), "name": me.get("name"), "warning": warning}

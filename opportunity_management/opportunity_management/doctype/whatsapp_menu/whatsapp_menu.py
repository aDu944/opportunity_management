# A list the WhatsApp auto menu sends (auto_menu.py). WhatsApp's limits are
# checked here so a menu that Meta would reject can never be saved.

import frappe
from frappe.model.document import Document

from opportunity_management.opportunity_management.auto_menu_pure import check_menu


class WhatsAppMenu(Document):
    def validate(self):
        for row in self.options or []:
            row.digit = (row.digit or "").strip()
        menu = self.as_dict()
        menu["options"] = [row.as_dict() for row in self.options or []]
        errors = check_menu(menu)
        if errors:
            frappe.throw("<br>".join(errors), title="WhatsApp limits")

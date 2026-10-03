# Per-user view state of a WhatsApp Conversation: pinned / muted.
#
# One row per (conversation, user), written only through
# `whatsapp_api.set_chat_state` (whatsapp_chat_state.set_state). Uniqueness is
# checked here and backed by a unique index from `on_doctype_update`, so two
# racing first-time toggles cannot leave two rows behind.

import frappe
from frappe import _
from frappe.model.document import Document


class WhatsAppChatState(Document):
    def validate(self):
        duplicate = frappe.db.get_value(
            "WhatsApp Chat State",
            {"conversation": self.conversation, "user": self.user, "name": ["!=", self.name]},
            "name",
        )
        if duplicate:
            frappe.throw(
                _("A chat state for {0} / {1} already exists").format(self.conversation, self.user),
                frappe.DuplicateEntryError,
            )


def on_doctype_update():
    try:
        frappe.db.add_unique("WhatsApp Chat State", ["conversation", "user"])
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp Chat State: unique index not added")

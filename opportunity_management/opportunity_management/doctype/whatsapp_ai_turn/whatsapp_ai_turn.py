# One model call of the WhatsApp AI responder (ai_agent.py / ai_replay.py):
# the draft or sent reply, its tools, token usage and cost, and a grade for
# the offline evaluation. Written by the system only.

import frappe
from frappe.model.document import Document


class WhatsAppAITurn(Document):
    pass


def on_doctype_update():
    frappe.db.add_index("WhatsApp AI Turn", ["source", "grade"])
    frappe.db.add_index("WhatsApp AI Turn", ["creation"])

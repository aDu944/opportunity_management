# Canned agent reply. Rendering (language pick + {{customer}}/{{agent}}
# substitution) happens server-side in
# whatsapp_api.render_quick_reply so mobile and Desk cannot drift.

from frappe.model.document import Document


class WhatsAppQuickReply(Document):
    pass

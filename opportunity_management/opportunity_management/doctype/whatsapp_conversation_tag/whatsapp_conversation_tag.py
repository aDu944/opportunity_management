# Child row backing the `tags` Table MultiSelect on WhatsApp Conversation.
# Tag add/remove goes through whatsapp_api.add_tag / remove_tag.

from frappe.model.document import Document


class WhatsAppConversationTag(Document):
    pass

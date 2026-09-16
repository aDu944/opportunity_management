# Singleton configuration for the WhatsApp team inbox.
#
# Read through whatsapp_utils.get_inbox_settings(), which caches the doc on
# frappe.local for the life of the request — the hook path touches it several
# times per inbound message. Defaults are seeded by
# whatsapp_utils.seed_inbox_defaults() from the backfill patch and after_install.

from frappe.model.document import Document


class WhatsAppInboxSettings(Document):
    pass

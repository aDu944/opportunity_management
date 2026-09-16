# Staff-only note attached to a WhatsApp Conversation. Never leaves the
# building — nothing here is sent to Meta.
#
# It exists as its own doctype rather than riding on `WhatsApp Message`
# (any type="Outgoing" row is shipped to Meta in `before_insert`) or on
# `Comment` (which would fire the existing on_comment_after_insert FCM
# path and cannot carry System / Failed Send entries).
#
# Rows are created by whatsapp_api.add_note (Note), whatsapp_api.assign /
# set_status (System) and whatsapp_api.send_message's rollback path
# (Failed Send).

from frappe.model.document import Document


class WhatsAppInternalNote(Document):
    pass

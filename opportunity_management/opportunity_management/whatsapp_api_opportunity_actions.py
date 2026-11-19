"""
Opportunity actions from the web Team Inbox's customer drawer (the
Opportunity card): set the linked Opportunity's status, or unlink it from
the conversation. Creating one is `whatsapp_api_opportunity`.

Re-exported by `whatsapp_api.py`, which is the path clients call. Refusals
are 417s (OpportunityError), not 403 (see whatsapp_api_common.NotAssigneeError).
"""

import frappe
from frappe import _

from opportunity_management.opportunity_management import whatsapp_crm
from opportunity_management.opportunity_management import whatsapp_hooks
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _get_conv,
    _note,
    _require_inbox_access,
)
from opportunity_management.opportunity_management.whatsapp_api_inbox import get_conversation
from opportunity_management.opportunity_management.whatsapp_api_opportunity import OpportunityError

OPP = "Opportunity"
SETTABLE_STATUSES = ("Open", "Quotation", "Closed", "Lost")


def _linked(conv):
    if not conv.opportunity or not frappe.db.exists(OPP, conv.opportunity):
        frappe.throw(_("This conversation has no Opportunity linked"), OpportunityError)
    return frappe.get_doc(OPP, conv.opportunity)


@frappe.whitelist()
def set_opportunity_status(conversation, status):
    """Set the linked Opportunity's status (Open | Quotation | Closed | Lost)
    through the document, so ERPNext's validation runs. Needs Opportunity
    write on that record. Returns the conversation (get_conversation)."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    status = str(status or "").strip()
    if status not in SETTABLE_STATUSES:
        frappe.throw(_("Invalid Opportunity status {0}").format(status), OpportunityError)
    opp = _linked(conv)
    if not frappe.has_permission(OPP, "write", doc=opp):
        frappe.throw(_("You are not permitted to edit Opportunity {0}").format(opp.name),
                     OpportunityError)
    if (opp.status or "") != status:
        opp.status = status
        opp.save()  # permissions + validation enforced
        _note(conv.name, _("Opportunity {0} status set to {1} by {2}")
              .format(opp.name, status, frappe.session.user))
        whatsapp_hooks.publish_inbox_event("conversation", conv)
    return get_conversation(conv.name)


@frappe.whitelist()
def unlink_opportunity(conversation):
    """Clear the conversation's Opportunity link (Lead / Customer / Contact
    stay). The Opportunity itself is untouched. Returns the conversation."""
    _require_inbox_access()
    conv = _get_conv(conversation)
    previous = conv.opportunity
    if previous:
        whatsapp_crm.unlink_conversation_from_crm(conv, OPP)
        _note(conv.name, _("Opportunity {0} unlinked by {1}").format(previous, frappe.session.user))
        whatsapp_hooks.publish_inbox_event("conversation", conv)
    return get_conversation(conv.name)

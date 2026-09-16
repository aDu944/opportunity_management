"""
The whitelisted contract for the WhatsApp team inbox (plan §1.7).

**This module is a facade.** Clients call
`/api/method/opportunity_management.opportunity_management.whatsapp_api.<name>`
and must keep doing so; the implementations live in
`whatsapp_api_inbox`, `whatsapp_api_messages` and `whatsapp_api_crm`, with
shared access checks and helpers in `whatsapp_api_common`.

Re-exporting is safe with Frappe's dispatcher: `frappe.handler.execute_cmd`
resolves the dotted path with `frappe.get_attr`, which is a plain `getattr`
on *this* module, and `is_whitelisted` then inspects the **function object**
— unchanged by the import, since `@frappe.whitelist()` registered the very
same object when its defining module was first imported. So the endpoint
paths below are stable regardless of which file a function lives in.

Deliberately kept out of the 3000-line `api.py`: nothing here is about ESS,
the permission model is its own, and mobile + Desk both bind to these names.
"""

# Typed errors — re-exported so callers (and tests) can keep importing them
# from `whatsapp_api`. Clients branch on Frappe's `exc_type`, which is the
# class __name__ and is likewise unaffected by the move.
from opportunity_management.opportunity_management.whatsapp_api_common import (  # noqa: F401
    DEFAULT_PAGE_LENGTH,
    DEFAULT_THREAD_LIMIT,
    MAX_PAGE_LENGTH,
    MAX_THREAD_LIMIT,
    MetaSendError,
    NotAssigneeError,
    WindowClosedError,
)

from opportunity_management.opportunity_management.whatsapp_api_inbox import (  # noqa: F401
    add_tag,
    assign,
    claim,
    get_conversation,
    get_inbox_meta,
    get_or_create_conversation,
    get_unread_count,
    list_conversations,
    mark_read,
    remove_tag,
    set_status,
    unassign,
)

from opportunity_management.opportunity_management.whatsapp_api_messages import (  # noqa: F401
    add_note,
    get_messages,
    get_quick_replies,
    get_templates,
    render_quick_reply,
    send_message,
    send_template,
)

from opportunity_management.opportunity_management.whatsapp_api_crm import (  # noqa: F401
    create_lead_from_conversation,
    get_inbox_stats,
    link_crm,
    list_conversations_for_crm,
    search_crm,
    unlink_crm,
)

# The 25 endpoint names of plan §1.7 + §5. Anything not listed here is not
# part of the contract.
__all__ = [
    # conversations
    "get_inbox_meta",
    "list_conversations",
    "get_conversation",
    "get_or_create_conversation",
    "get_unread_count",
    # assignment & status
    "claim",
    "unassign",
    "assign",
    "set_status",
    "add_tag",
    "remove_tag",
    "mark_read",
    # thread
    "get_messages",
    "send_message",
    "send_template",
    "add_note",
    "get_quick_replies",
    "render_quick_reply",
    "get_templates",
    # CRM
    "link_crm",
    "unlink_crm",
    "search_crm",
    "create_lead_from_conversation",
    "list_conversations_for_crm",
    # analytics
    "get_inbox_stats",
]

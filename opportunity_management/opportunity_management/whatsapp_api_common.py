"""
Shared plumbing for the WhatsApp inbox API modules.

`whatsapp_api.py` is a thin facade; the endpoint bodies live in
`whatsapp_api_inbox`, `whatsapp_api_messages` and `whatsapp_api_crm`. Access
checks, the typed exceptions, pagination and the internal-note writer are
here so all three share one implementation and none of them has to import
another sibling just to check a role.

Nothing in this module is whitelisted.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from opportunity_management.opportunity_management.whatsapp_utils import inbox_roles

DEFAULT_PAGE_LENGTH = 30
MAX_PAGE_LENGTH = 100
DEFAULT_THREAD_LIMIT = 40
MAX_THREAD_LIMIT = 200

# ── typed errors ─────────────────────────────────────────────────────────────
# Surface as `exc_type` in Frappe's JSON error envelope, so the mobile client
# can show "send a template" vs "someone else owns this chat" without string
# matching on a translated message.

class WindowClosedError(frappe.ValidationError):
    """The 24h customer-service window has expired; only templates go out."""


class MetaSendError(frappe.ValidationError):
    """Meta rejected the send; nothing was persisted."""


class NotAssigneeError(frappe.ValidationError):
    """The caller is not the assignee (and is not a manager).

    Deliberately NOT a `frappe.PermissionError`: that maps to HTTP 403, and the
    mobile client's auth interceptor treats any 401/403 as a dead session and
    re-logs in before the typed error ever reaches the caller. 417 keeps this a
    normal "someone else owns this chat" the UI can render inline. Clients
    branch on `exc_type`, which is the class name — unchanged.
    """


# ── access ───────────────────────────────────────────────────────────────────

def _roles():
    return set(frappe.get_roles(frappe.session.user))


def _is_manager() -> bool:
    roles = _roles()
    return "System Manager" in roles or "WhatsApp Manager" in roles


def _require_inbox_access():
    """Every endpoint's first line. Inbox roles come from Inbox Settings so
    the role set can be widened without a deploy."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    roles = _roles()
    if "System Manager" in roles:
        return
    if roles & set(inbox_roles()):
        return
    frappe.throw(_("You do not have access to the WhatsApp inbox"), frappe.PermissionError)


def _get_conv(name, for_update=False):
    if not name:
        frappe.throw(_("Conversation is required"))
    if not frappe.db.exists("WhatsApp Conversation", name):
        frappe.throw(_("Conversation {0} not found").format(name), frappe.DoesNotExistError)
    return frappe.get_doc("WhatsApp Conversation", name, for_update=for_update)


def _require_assignee(conv):
    """Write actions on a thread belong to its assignee, or to a manager."""
    if _is_manager():
        return
    if conv.assigned_to and conv.assigned_to != frappe.session.user:
        frappe.throw(
            _("This conversation is assigned to {0}").format(conv.assigned_to),
            exc=NotAssigneeError,
        )


def _refuse_blocked(conv):
    """Nothing goes out to a contact the team blocked (see block_contact)."""
    if cint(conv.get("is_blocked")):
        frappe.throw(_("This contact is blocked. Unblock them before sending a message."))


def _paging(limit_start=0, limit_page_length=None):
    start = max(cint(limit_start), 0)
    length = cint(limit_page_length) or DEFAULT_PAGE_LENGTH
    length = max(1, min(length, MAX_PAGE_LENGTH))
    return start, length


def _note(conversation, text, note_type="System", author=None, attach=None, mentions=None):
    """Insert an internal note and keep `notes_count` honest."""
    doc = frappe.get_doc(
        {
            "doctype": "WhatsApp Internal Note",
            "conversation": conversation,
            "note_type": note_type,
            "text": text,
            "author": author if author is not None else frappe.session.user,
            "attach": attach,
            "mentions": ",".join(mentions) if isinstance(mentions, (list, tuple)) else mentions,
        }
    )
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    frappe.db.sql(
        """UPDATE `tabWhatsApp Conversation`
           SET notes_count = COALESCE(notes_count, 0) + 1
           WHERE name = %(name)s""",
        {"name": conversation},
    )
    return doc


def _crm_label(doctype, name):
    """Human label for a linked CRM record, falling back to its id."""
    if not name:
        return ""
    field = {
        "Contact": "name",
        "Lead": "lead_name",
        "Customer": "customer_name",
        "Opportunity": "title",
    }.get(doctype, "name")
    try:
        return frappe.db.get_value(doctype, name, field) or name
    except Exception:
        return name


def _tag_list(raw):
    """Normalize the `tags` argument into a deduped list of tag names.

    Desk sends a JSON array (`frappe.call` stringifies arrays); a comma string
    is accepted too so the endpoint is usable from the API console.
    """
    if not raw:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                raw = json.loads(text)
            except (TypeError, ValueError):
                raw = text
        if isinstance(raw, str):
            raw = text.split(",")
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw:
        item = str(item if item is not None else "").strip()
        if item and item not in out:
            out.append(item)
    return out


def _resolve_account(whatsapp_account=None):
    """Which WhatsApp Account an agent-initiated thread belongs to.

    Explicit argument wins; otherwise the default outgoing account; otherwise
    the single Active one. With several accounts and no default configured we
    refuse rather than guess — the account decides which number the customer
    sees the message from.
    """
    if whatsapp_account:
        if not frappe.db.exists("WhatsApp Account", whatsapp_account):
            frappe.throw(_("WhatsApp Account {0} not found").format(whatsapp_account))
        return whatsapp_account

    default = frappe.db.get_value("WhatsApp Account", {"is_default_outgoing": 1}, "name")
    if default:
        return default

    try:
        active = frappe.get_all(
            "WhatsApp Account", filters={"status": "Active"}, pluck="name", limit_page_length=2
        )
    except Exception:
        # Older frappe_whatsapp builds have no `status` field on the account.
        active = frappe.get_all("WhatsApp Account", pluck="name", limit_page_length=2)
    if len(active) == 1:
        return active[0]

    frappe.throw(
        _("No WhatsApp Account is set as the default outgoing account — pick one in WhatsApp Account.")
    )

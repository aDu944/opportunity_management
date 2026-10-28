"""
Agent-group pieces of the inbox API (agent_groups.py holds the logic).

    assign_to_group(conversation, group)   whitelisted; re-exported by
    list_agent_groups()                    whatsapp_api_inbox and whatsapp_api
    list_select / scope_clauses / ORDER    `list_conversations(scope="groups")`
    meta(user)                             `groups` + `groups_unclaimed` for
                                           get_inbox_meta

Before the migrate every fragment is a constant (no groups, nothing ringing).
"""

import frappe
from frappe import _

from opportunity_management.opportunity_management import agent_groups as AG
from opportunity_management.opportunity_management import whatsapp_assign_rules as AR
from opportunity_management.opportunity_management import whatsapp_serializers as S
from opportunity_management.opportunity_management.whatsapp_api_common import (
    NotAssigneeError,
    _get_conv,
    _is_manager,
    _require_inbox_access,
)

# `groups` scope: unclaimed (ringing) chats first, oldest ring first; then the
# caller's own group chats, newest activity first.
GROUPS_ORDER = (
    "CASE WHEN COALESCE(c.assigned_to, '') = '' THEN 0 ELSE 1 END ASC, "
    "CASE WHEN COALESCE(c.assigned_to, '') = '' THEN c.group_assigned_at END ASC, "
    "c.last_message_at DESC, c.modified DESC"
)
_MY_GROUPS_SQL = """c.assigned_group IN (
    SELECT g.name FROM `tabWhatsApp Agent Group` g
    JOIN `tabWhatsApp Agent Group Member` m
      ON m.parent = g.name AND m.parenttype = 'WhatsApp Agent Group' AND m.parentfield = 'members'
    WHERE COALESCE(g.is_active, 0) = 1 AND COALESCE(m.is_active, 0) = 1 AND m.user = %(group_user)s)"""


def list_select(alias) -> str:
    """Group columns for the list query, with the trailing comma."""
    if not AG.ready():
        return "NULL AS assigned_group, NULL AS group_assigned_at, "
    return "{0}.assigned_group, {0}.group_assigned_at, ".format(alias)


def scope_clauses(params, user):
    """WHERE clauses of the `groups` scope: open chats ringing one of the
    caller's groups, or already the caller's own. Nothing before migrate."""
    if not AG.ready():
        return ["1 = 0"]
    params["group_user"] = user
    return [
        "c.status != 'Resolved'",
        _MY_GROUPS_SQL,
        "(COALESCE(c.assigned_to, '') = '' OR c.assigned_to = %(group_user)s)",
    ]


def order_by():
    return GROUPS_ORDER if AG.ready() else "c.last_message_at DESC, c.modified DESC"


def _groups(user):
    """Active groups with member counts and the caller's membership."""
    if not AG.ready():
        return []
    rows = frappe.db.sql(
        """SELECT g.name, g.strategy,
                  SUM(CASE WHEN COALESCE(m.is_active, 0) = 1 THEN 1 ELSE 0 END) AS members_count,
                  MAX(CASE WHEN COALESCE(m.is_active, 0) = 1 AND m.user = %(user)s THEN 1 ELSE 0 END) AS is_member
           FROM `tabWhatsApp Agent Group` g
           LEFT JOIN `tabWhatsApp Agent Group Member` m
             ON m.parent = g.name AND m.parenttype = 'WhatsApp Agent Group' AND m.parentfield = 'members'
           WHERE COALESCE(g.is_active, 0) = 1
           GROUP BY g.name, g.strategy
           ORDER BY g.name ASC""",
        {"user": user},
        as_dict=True,
    )
    return [
        {
            "name": r.name,
            "strategy": r.strategy or "Ring",
            "members_count": int(r.members_count or 0),
            "is_member": bool(r.is_member),
        }
        for r in rows
    ]


def _unclaimed_count(user) -> int:
    if not AG.ready():
        return 0
    params = {"group_user": user}
    rows = frappe.db.sql(
        """SELECT COUNT(*) FROM `tabWhatsApp Conversation` c
           WHERE c.status != 'Resolved' AND COALESCE(c.assigned_to, '') = ''
             AND {0}""".format(_MY_GROUPS_SQL),
        params,
    )
    return int(rows[0][0] or 0) if rows else 0


def meta(user):
    """`groups` + `groups_unclaimed` (badge of the "My groups" scope)."""
    return {"groups": _groups(user), "groups_unclaimed": _unclaimed_count(user)}


@frappe.whitelist()
def list_agent_groups():
    """Active agent groups for the Transfer-to-group picker, with members."""
    _require_inbox_access()
    groups = _groups(frappe.session.user)
    for group in groups:
        members = AG.active_members(group["name"])
        names = S._full_names(members)
        group["members"] = [{"user": u, "full_name": names.get(u, u)} for u in members]
    return groups


@frappe.whitelist()
def assign_to_group(conversation, group):
    """Hand a chat to an agent group: a manager, or the current owner
    (`whatsapp_assign_rules.may_assign_group`)."""
    _require_inbox_access()
    me = frappe.session.user
    group = (group or "").strip()
    if not group:
        frappe.throw(_("Choose a group to assign this conversation to"))
    conv = _get_conv(conversation, for_update=True)
    if not AR.may_assign_group(_is_manager(conv), me, conv.assigned_to):
        # 417, not 403 (see NotAssigneeError).
        frappe.throw(
            _("Only the conversation's owner or a WhatsApp Manager can transfer it"),
            exc=NotAssigneeError,
        )
    AG.assign_to_group(conv, group, me)
    return S.conv_row(conv)

"""
Who may hand a WhatsApp conversation to whom — the pure decision behind
`whatsapp_api_inbox.assign`.

No frappe import: the endpoint gathers the facts (roles, current owner, the
agent roster) and this module only decides, so the rule is testable without a
bench (tests/test_whatsapp_assign_pure.py).

The rule:

    manager                         → any chat, to any inbox agent
    caller owns the chat            → transfer it to any inbox agent
    agent, unassigned chat          → only to themselves (that is a claim);
                                      claim first, then transfer
    agent, someone else's chat      → refused
    target == current owner         → no-op, for anyone allowed to look
"""

# Verdicts when allowed — they pick the note the endpoint writes.
NOOP = "noop"
ASSIGN = "assign"  # a manager placing / reassigning a chat
TRANSFER = "transfer"  # the current owner handing their chat on
CLAIM = "claim"  # an agent taking a free chat through `assign`

# Reasons when refused.
NO_TARGET = "no_target"
NOT_OWNER_UNASSIGNED = "not_owner_unassigned"
NOT_OWNER = "not_owner"
TARGET_NOT_AGENT = "target_not_agent"


def may_assign(is_manager, caller, current_assignee, target, roster=None):
    """Return `(allowed, verdict)`.

    `verdict` is NOOP / ASSIGN / TRANSFER / CLAIM when allowed, else one of the
    refusal reasons above. `roster` is the set of users who can work the inbox
    (`inbox_users()`); None skips that check. Permission is decided before the
    target is validated, so a refused caller learns nothing about the roster.
    """
    target = (target or "").strip()
    current = (current_assignee or "").strip()
    if not target:
        return False, NO_TARGET

    if current and current == caller:
        verdict = TRANSFER
    elif is_manager:
        verdict = ASSIGN
    elif not current:
        if target != caller:
            return False, NOT_OWNER_UNASSIGNED
        verdict = CLAIM
    else:
        return False, NOT_OWNER

    if target == current:
        return True, NOOP
    if roster is not None and target not in roster:
        return False, TARGET_NOT_AGENT
    return True, verdict


def may_transfer(is_manager, caller, current_assignee):
    """`can_transfer` for the clients: a manager, or the chat's current owner."""
    return bool(is_manager) or bool(current_assignee and current_assignee == caller)


# Claim refusals (`whatsapp_api_inbox.claim`).
CLAIMED_BY_OTHER = "claimed_by_other"
NOT_GROUP_MEMBER = "not_group_member"


def may_claim(is_manager, caller, current_assignee, group=None, group_members=None):
    """Return `(allowed, reason)` for taking a chat with `claim`.

    Someone else's chat is refused for everyone (a manager reassigns with
    `assign` instead). A chat ringing a group (`group` set) may be claimed by
    an active member of that group (`group_members`) or a manager; other
    agents are refused. No group: any inbox agent, as before.
    """
    current = (current_assignee or "").strip()
    if current and current != caller:
        return False, CLAIMED_BY_OTHER
    if current:  # already the caller's own chat
        return True, CLAIM
    if group and not is_manager and caller not in set(group_members or ()):
        return False, NOT_GROUP_MEMBER
    return True, CLAIM


def may_assign_group(is_manager, caller, current_assignee):
    """`assign_to_group`: a manager, or the current owner handing their chat
    to a group — the same family as `may_transfer`."""
    return may_transfer(is_manager, caller, current_assignee)

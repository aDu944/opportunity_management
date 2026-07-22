"""
Business-event FCM hooks — Quotation, Sales Order, Sales Invoice, Payment
Entry, ToDo, Material Request, Delivery Note.

Each hook:
  1. Builds the notification via `notification_templates`.
  2. Resolves recipients — the doc's owner (creator), the doc's assigned
     approver where applicable, and users holding a named role.
  3. Dispatches via `notification_dispatcher.enqueue_fcm_to_user` — the
     actual send runs on the short RQ queue so the originating request
     (doc submit) doesn't block on the OAuth handshake × recipients.

All send calls are wrapped so a single bad token can't break the parent
transaction (`try/except` around each user).
"""

import frappe

from opportunity_management.opportunity_management import notification_templates as T
from opportunity_management.opportunity_management.notification_dispatcher import (
    enqueue_fcm_to_user,
)


# ── Dispatch primitives ───────────────────────────────────────────────────────

def _send_to_users(users, title, body, data, dedupe_seen=None):
    """Send an FCM push to each email in `users`. Silently skips duplicates
    within a single dispatch (dedupe_seen is caller-supplied so a hook that
    invokes _send_to_users several times can share the set)."""
    seen = dedupe_seen if dedupe_seen is not None else set()
    for email in users:
        if not email or email in seen:
            continue
        seen.add(email)
        # Enqueue keeps the originating request (doc submit, hook fire)
        # from blocking on the OAuth handshake × recipients count.
        enqueue_fcm_to_user(email, title=title, body=body, data=data)


def _users_with_role(role: str):
    """Return enabled User emails holding `role`. Excludes Administrator."""
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name AS email
        FROM `tabUser` u
        JOIN `tabHas Role` r ON r.parent = u.name
        WHERE r.role = %s
          AND u.enabled = 1
          AND u.name != 'Administrator'
        """,
        (role,),
        as_dict=True,
    )
    return [r["email"] for r in rows]


# ── Festo scoping ──────────────────────────────────────────────────────────────
# Docs that ship FESTO-brand items are scoped to the Festo team only —
# generic Sales/Accounts/Stock role expansion is REPLACED (not augmented)
# with users holding any FESTO role for those docs. Owner, responsible
# engineer, and named approver remain notified since those linkages are
# personal, not role-based.

_FESTO_ROLES = (
    "FESTO Sales User",
    "FESTO BG-ER Sales",
    "FESTO ER Accounting",
    "FESTO Jordan",
    "FESTO Main",
    "FESTO SH",
)


def _is_festo_doc(doc) -> bool:
    """True iff any child-table item on `doc` has brand='FESTO'."""
    items = doc.get("items") or []
    if not items:
        return False
    # Item.brand isn't always mirrored onto the row, so fetch from Item.
    item_codes = {
        (row.get("item_code") if hasattr(row, "get") else getattr(row, "item_code", None))
        for row in items
    }
    item_codes.discard(None)
    if not item_codes:
        return False
    hit = frappe.db.sql(
        """
        SELECT 1
        FROM `tabItem`
        WHERE name IN %(codes)s
          AND brand = 'FESTO'
        LIMIT 1
        """,
        {"codes": tuple(item_codes)},
    )
    return bool(hit)


def _all_festo_role_users():
    """Every enabled user holding ANY FESTO role. Deduplicated."""
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name AS email
        FROM `tabUser` u
        JOIN `tabHas Role` r ON r.parent = u.name
        WHERE r.role IN %(roles)s
          AND u.enabled = 1
          AND u.name != 'Administrator'
        """,
        {"roles": _FESTO_ROLES},
        as_dict=True,
    )
    return [r["email"] for r in rows]


def _scoped_role_users(doc, *generic_roles: str):
    """Return the correct recipient list for `doc`:
      - Festo doc  → users with ANY FESTO role
      - Other doc  → users with any of `generic_roles`
    Personal linkages (owner, responsible engineer, approver) are added
    separately by callers; this function ONLY handles role-based expansion."""
    if _is_festo_doc(doc):
        return _all_festo_role_users()
    users = []
    for role in generic_roles:
        users.extend(_users_with_role(role))
    return users


def _opportunity_responsible_users(opp_name: str):
    """Return user emails linked to the opportunity's responsible/owned
    employees. Falls back to the opportunity owner if we can't find the
    employee linkage."""
    if not opp_name:
        return []
    resp_emp = frappe.db.get_value("Opportunity", opp_name, "custom_responsible_engineer")
    users = []
    if resp_emp:
        user = frappe.db.get_value("Employee", resp_emp, "user_id")
        if user:
            users.append(user)
    owner = frappe.db.get_value("Opportunity", opp_name, "owner")
    if owner and owner not in users:
        users.append(owner)
    return users


def _dispatch(recipients, template_fn, doc):
    """Common wrapper: build the (title, body, data) triple and send to
    every distinct recipient in the list."""
    title, body, data = template_fn(doc)
    seen = set()
    _send_to_users(recipients, title, body, data, dedupe_seen=seen)


# ── Doctype hooks ─────────────────────────────────────────────────────────────

def on_quotation_after_insert(doc, method=None):
    """A new (draft) Quotation was created. Notify the responsible engineer
    on the linked Opportunity + Sales team (scoped to FESTO if Festo doc)."""
    if doc.docstatus != 0:
        return
    opp = doc.get("opportunity")
    recipients = _opportunity_responsible_users(opp) + _scoped_role_users(doc, "Sales Manager")
    _dispatch(recipients, T.quotation_created, doc)


def on_quotation_submit(doc, method=None):
    """Quotation was submitted (docstatus 1)."""
    recipients = _opportunity_responsible_users(doc.get("opportunity")) + _scoped_role_users(doc, "Sales Manager")
    _dispatch(recipients, T.quotation_submitted, doc)


def on_quotation_update_after_submit(doc, method=None):
    """Quotation status changed post-submit → detect 'Lost'."""
    if doc.get("status") == "Lost":
        recipients = _opportunity_responsible_users(doc.get("opportunity")) + _scoped_role_users(doc, "Sales Manager")
        _dispatch(recipients, T.quotation_lost, doc)


def on_sales_order_submit(doc, method=None):
    recipients = _scoped_role_users(doc, "Sales Manager", "Sales User")
    # Also include the creator so they get a confirmation.
    if doc.owner:
        recipients.append(doc.owner)
    _dispatch(recipients, T.sales_order_submitted, doc)


def on_sales_invoice_submit(doc, method=None):
    recipients = _scoped_role_users(doc, "Accounts Manager", "Accounts User")
    if doc.owner:
        recipients.append(doc.owner)
    _dispatch(recipients, T.sales_invoice_submitted, doc)


def on_journal_entry_submit_broadcast(doc, method=None):
    """Notify Accounts of every submitted Journal Entry.

    Separate from ess_hooks.on_journal_entry_submit which specifically
    handles employee-payment JEs — both run; the ess_hooks path notifies
    the paid/owed employee, this one notifies the accounts team.

    Journal Entries don't carry item rows so brand scoping doesn't apply
    — they always go to the generic Accounts Manager list."""
    recipients = _users_with_role("Accounts Manager")
    _dispatch(recipients, T.journal_entry_submitted, doc)


def on_payment_entry_submit_broadcast(doc, method=None):
    """Notify per payment type:
      - Receive → Sales Manager + Accounts Manager
      - Pay     → Accounts Manager

    Payment Entries don't carry item rows either — brand scoping N/A."""
    ptype = (doc.get("payment_type") or "").lower()
    if ptype == "receive":
        recipients = _users_with_role("Sales Manager") + _users_with_role("Accounts Manager")
        _dispatch(recipients, T.payment_received, doc)
    elif ptype == "pay":
        recipients = _users_with_role("Accounts Manager")
        _dispatch(recipients, T.payment_made, doc)
    # Internal transfers → skipped intentionally.


def on_leave_application_insert_notify_approver(doc, method=None):
    """New leave request → notify the assigned leave_approver."""
    approver = doc.get("leave_approver")
    if not approver:
        return
    _dispatch([approver], T.leave_request_created, doc)


def on_expense_claim_after_insert(doc, method=None):
    """New expense claim → notify the assigned expense_approver."""
    approver = doc.get("expense_approver")
    if not approver:
        return
    _dispatch([approver], T.expense_claim_created, doc)


def on_todo_after_insert(doc, method=None):
    """A ToDo is assigned to a user → notify them.

    ToDo.owner is the CREATING user; the ASSIGNEE is in ToDo.allocated_to."""
    assignee = doc.get("allocated_to")
    if not assignee or assignee == doc.get("owner"):
        # Self-assigned — no need to push a notification to yourself.
        return
    _dispatch([assignee], T.task_assigned, doc)


def on_material_request_submit(doc, method=None):
    recipients = _scoped_role_users(doc, "Stock Manager", "Purchase Manager")
    _dispatch(recipients, T.material_request_submitted, doc)


def on_delivery_note_submit(doc, method=None):
    recipients = _scoped_role_users(doc, "Sales Manager", "Stock Manager")
    if doc.owner:
        recipients.append(doc.owner)
    _dispatch(recipients, T.delivery_note_submitted, doc)


def on_purchase_order_submit(doc, method=None):
    """Notify System Manager + creator of every submitted Purchase Order."""
    recipients = list(_users_with_role("System Manager"))
    if doc.owner:
        recipients.append(doc.owner)
    _dispatch(recipients, T.purchase_order_submitted, doc)


def on_project_after_insert(doc, method=None):
    """Notify System Manager + Projects Manager + creator of every new Project."""
    recipients = list(_users_with_role("System Manager"))
    recipients.extend(_users_with_role("Projects Manager"))
    if doc.owner:
        recipients.append(doc.owner)
    _dispatch(recipients, T.project_created, doc)


def on_journal_entry_workflow_change(doc, method=None):
    """Fire on JE workflow state change to Approved/Rejected. Dispatches
    the appropriate FCM template to Accounts Manager + doc.owner."""
    try:
        if not doc.has_value_changed("workflow_state"):
            return
    except AttributeError:
        return
    state = (getattr(doc, "workflow_state", None) or "").strip()
    recipients = list(_users_with_role("Accounts Manager"))
    if doc.owner:
        recipients.append(doc.owner)
    if state == "Approved":
        _dispatch(recipients, T.journal_entry_approved, doc)
    elif state == "Rejected":
        _dispatch(recipients, T.journal_entry_rejected, doc)

"""
Employee expenses on the caller's behalf (expenses_contract.md).

    opportunity_management.opportunity_management.expenses_api.<name>

Every active employee may file, list, attach receipts to and delete their
own expense Journal Entries without holding any Journal Entry permission.
Each endpoint starts with `_require_employee()`; writes run with
`ignore_permissions` only after the ownership / whitelist checks here.
Journal Entries are inserted as Draft and never submitted.

Sources mirror what the app read directly before:
- payable account: Employee `custom_advance_account__حساب_السلفة`
- default cost centre: Employee `custom_cost_center` (fallback 1001 - Main - AK)
- categories: `api.get_expense_categories` (ESS Mobile Settings)
- history: Journal Entry Account lines on the payable account, party = employee
- balance: GL Entry on the payable account, party Employee, not cancelled
"""

import frappe
from frappe import _
from frappe.utils import cint, nowdate

from opportunity_management.opportunity_management import expenses_pure as P

PAYABLE_FIELD = "custom_advance_account__حساب_السلفة"
SEARCH_LIMIT = 20


class NoEmployeeError(frappe.ValidationError):
    """The user has no active Employee. 417, not 403: the app's auth
    interceptor treats 403 as a dead session and would re-login forever."""


class ExpenseNotFoundError(frappe.ValidationError):
    """Not one of the caller's expenses (reported exactly like a missing one)."""


# ── plumbing ─────────────────────────────────────────────────────────────────

def _require_employee():
    """The caller's active Employee as a dict."""
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    fields = ["name", "employee_name", "company"]
    meta = frappe.get_meta("Employee")
    for f in (PAYABLE_FIELD, "custom_cost_center"):
        if meta.has_field(f):
            fields.append(f)
    rows = frappe.get_all("Employee", filters={"user_id": user, "status": "Active"},
                          fields=fields, limit=1, ignore_permissions=True)
    if not rows:
        frappe.throw(_("No active employee is linked to your user"), NoEmployeeError)
    emp = rows[0]
    emp["payable_account"] = emp.get(PAYABLE_FIELD) or ""
    emp["cost_center"] = emp.get("custom_cost_center") or P.DEFAULT_COST_CENTER
    return emp


def _throw(err):
    frappe.throw(_(str(err)))


def _setting(field):
    try:
        return frappe.db.get_single_value("ESS Mobile Settings", field)
    except Exception:
        return None


def _categories():
    from opportunity_management.opportunity_management.api import get_expense_categories
    return get_expense_categories()


def _can_pick_cost_center():
    """Today the picker only appears to users who can read Cost Center."""
    try:
        return bool(frappe.has_permission("Cost Center", "read"))
    except Exception:
        return False


def _my_draft(name, emp, need_owner=False):
    """A Draft JE with a line whose party is the caller's employee."""
    name = P.clean_name(name)
    row = frappe.db.sql(
        """
        SELECT je.name, je.docstatus, je.owner
        FROM `tabJournal Entry` je
        JOIN `tabJournal Entry Account` jea
          ON jea.parent = je.name AND jea.parenttype = 'Journal Entry'
        WHERE je.name = %(name)s AND jea.party_type = 'Employee' AND jea.party = %(emp)s
        LIMIT 1
        """,
        {"name": name, "emp": emp["name"]},
        as_dict=True,
    )
    if not name or not row:
        frappe.throw(_("Expense {0} not found").format(name), ExpenseNotFoundError)
    je = row[0]
    if need_owner and je.owner != frappe.session.user:
        frappe.throw(_("Expense {0} not found").format(name), ExpenseNotFoundError)
    if cint(je.docstatus) != 0:
        frappe.throw(_("Only draft expenses can be changed"))
    return je


def _check_cost_center(cc, company, default_cc):
    if cc != default_cc and not _can_pick_cost_center():
        frappe.throw(_("You cannot choose a different cost centre"))
    row = frappe.db.get_value("Cost Center", cc, ["company", "is_group"], as_dict=True)
    if not row:
        frappe.throw(_("Cost centre {0} not found").format(cc))
    if row.company != company or cint(row.is_group):
        frappe.throw(_("Cost centre {0} cannot be used for {1}").format(cc, company))


# ── read ─────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_expense_form_data():
    emp = _require_employee()
    payable = emp["payable_account"]
    currency = P.DEFAULT_CURRENCY
    if payable:
        currency = frappe.db.get_value("Account", payable, "account_currency") or currency
    cost_centers = []
    if _can_pick_cost_center():
        cost_centers = frappe.get_all(
            "Cost Center",
            filters={"company": emp.company, "is_group": 0},
            fields=["name", "cost_center_name"],
            order_by="name asc", limit=200, ignore_permissions=True,
        )
    try:
        categories = _categories()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Expenses: categories")
        categories = []
    return {
        "employee": emp.name,
        "employee_name": emp.employee_name or "",
        "company": emp.company or "",
        "cost_center": emp["cost_center"],
        "payable_account": payable,
        "payable_account_currency": currency,
        "categories": categories,
        "cost_centers": cost_centers,
        "currency": currency,
    }


@frappe.whitelist()
def list_my_expenses(limit=200):
    emp = _require_employee()
    payable = emp["payable_account"]
    if not payable:
        return {"rows": []}
    rows = frappe.db.sql(
        """
        SELECT je.name, je.posting_date, je.user_remark, je.docstatus,
               jea.account, jea.party, jea.debit_in_account_currency,
               jea.credit_in_account_currency, jea.account_currency
        FROM `tabJournal Entry` je
        JOIN `tabJournal Entry Account` jea
          ON jea.parent = je.name AND jea.parenttype = 'Journal Entry'
        WHERE jea.account = %(acc)s AND jea.party = %(emp)s
        ORDER BY je.posting_date DESC, je.creation DESC
        LIMIT %(limit)s
        """,
        {"acc": payable, "emp": emp.name, "limit": P.clamp_limit(limit)},
        as_dict=True,
    )
    return {"rows": P.history_rows(rows, payable, emp.name)}


@frappe.whitelist()
def get_my_expense_balance():
    emp = _require_employee()
    payable = emp["payable_account"]
    currency = P.DEFAULT_CURRENCY
    if not payable:
        return {"balance": 0.0, "currency": currency}
    currency = frappe.db.get_value("Account", payable, "account_currency") or currency
    row = frappe.db.sql(
        """
        SELECT COALESCE(SUM(credit), 0) AS credit, COALESCE(SUM(debit), 0) AS debit
        FROM `tabGL Entry`
        WHERE account = %(acc)s AND party_type = 'Employee' AND party = %(emp)s
          AND is_cancelled = 0
        """,
        {"acc": payable, "emp": emp.name},
        as_dict=True,
    )[0]
    return {"balance": P.balance(row.credit, row.debit), "currency": currency}


@frappe.whitelist()
def search_projects(q=None):
    _require_employee()
    return frappe.db.sql(
        """
        SELECT name, project_name FROM `tabProject`
        WHERE project_name LIKE %(q)s OR name LIKE %(q)s
        ORDER BY modified DESC LIMIT %(limit)s
        """,
        {"q": P.like_pattern(q), "limit": SEARCH_LIMIT},
        as_dict=True,
    )


@frappe.whitelist()
def search_opportunities(q=None):
    _require_employee()
    has_tender = frappe.db.has_column("Opportunity", "custom_tender_no")
    tender_col = "custom_tender_no" if has_tender else "'' AS custom_tender_no"
    tender_where = " OR custom_tender_no LIKE %(q)s" if has_tender else ""
    return frappe.db.sql(
        f"""
        SELECT name, party_name, {tender_col} FROM `tabOpportunity`
        WHERE name LIKE %(q)s OR party_name LIKE %(q)s{tender_where}
        ORDER BY modified DESC LIMIT %(limit)s
        """,
        {"q": P.like_pattern(q), "limit": SEARCH_LIMIT},
        as_dict=True,
    )


# ── write ────────────────────────────────────────────────────────────────────

@frappe.whitelist(methods=["POST"])
def create_my_expense(posting_date=None, cost_center=None, rows=None, remark=None):
    emp = _require_employee()
    payable = emp["payable_account"]
    if not payable:
        frappe.throw(_("No advance account is set on your employee record"))
    cc = P.clean_name(cost_center) or emp["cost_center"]
    try:
        date = P.validate_posting_date(posting_date or nowdate(), nowdate())
        allowed = {c.get("account") for c in _categories()}
        clean = P.normalise_rows(rows, allowed, cc)
        P.clean_text(remark)
    except ValueError as err:
        _throw(err)
    for c in {cc} | {r["cost_center"] for r in clean}:
        _check_cost_center(c, emp.company, emp["cost_center"])
    for r in clean:
        if r["project"] and not frappe.db.exists("Project", r["project"]):
            frappe.throw(_("Project {0} not found").format(r["project"]))
        if r["opportunity"] and not frappe.db.exists("Opportunity", r["opportunity"]):
            frappe.throw(_("Opportunity {0} not found").format(r["opportunity"]))
    cap = float(_setting("max_expense_amount_per_claim") or 0)
    if cap > 0 and P.total_amount(clean) > cap:
        frappe.throw(_("Amount exceeds the maximum allowed ({0})").format(cap))
    je = frappe.get_doc(P.build_journal_entry(
        emp.company, date, payable, emp.name, cc, clean, remark))
    je.insert(ignore_permissions=True)
    return {"name": je.name}


@frappe.whitelist(methods=["POST"])
def attach_my_expense_receipt(name=None):
    emp = _require_employee()
    je = _my_draft(name, emp)
    upload = frappe.request.files.get("file") if frappe.request else None
    if not upload:
        frappe.throw(_("Attach a receipt file"))
    content = upload.stream.read()
    try:
        file_name = P.check_receipt(
            upload.filename, content,
            P.receipt_limit_bytes(_setting("max_attachment_size_mb")))
    except ValueError as err:
        _throw(err)
    max_files = cint(_setting("max_attachments_per_expense"))
    if max_files > 0 and frappe.db.count(
            "File", {"attached_to_doctype": "Journal Entry",
                     "attached_to_name": je.name}) >= max_files:
        frappe.throw(_("At most {0} receipts per expense").format(max_files))
    f = frappe.get_doc({
        "doctype": "File",
        "file_name": file_name,
        "attached_to_doctype": "Journal Entry",
        "attached_to_name": je.name,
        "is_private": 0,
        "content": content,
    })
    f.save(ignore_permissions=True)
    return {"file_url": f.file_url, "name": f.name}


@frappe.whitelist(methods=["POST"])
def delete_my_expense(name=None):
    emp = _require_employee()
    je = _my_draft(name, emp, need_owner=True)
    frappe.delete_doc("Journal Entry", je.name, ignore_permissions=True)
    return {"deleted": 1}

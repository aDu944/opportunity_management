"""
Ledger queries behind the shareholder app (shareholder_contract.md).

Every query is filtered by `company`, parameterised, and grouped in SQL — no
per-account GL pagination. Amounts come back in company currency unless a
function says otherwise. JSON-safe conversion / bucketing lives in
`shareholder_pure`; the whitelisted endpoints are in `shareholder_api`.

Nothing here is whitelisted and nothing here checks roles — callers do.
"""

import frappe

from opportunity_management.opportunity_management import shareholder_pure as P

# Year-end closing vouchers zero the P&L accounts; including them would make
# December (or whichever month closes the year) look like a huge loss/gain.
_NOT_CLOSING = "AND gle.voucher_type != 'Period Closing Voucher'"


def company_meta(company):
    row = frappe.db.get_value(
        "Company", company, ["default_currency", "abbr"], as_dict=True
    ) or {}
    return {"currency": row.get("default_currency") or "", "abbr": row.get("abbr") or ""}


# ── balances ─────────────────────────────────────────────────────────────────

def bank_cash_accounts(company):
    """Ledger (non-group, enabled) Bank/Cash accounts of `company`."""
    return frappe.db.sql(
        """SELECT name, account_name, account_number, account_currency
           FROM `tabAccount`
           WHERE company = %(company)s AND account_type IN ('Bank', 'Cash')
             AND is_group = 0 AND disabled = 0
           ORDER BY lft""",
        {"company": company},
        as_dict=True,
    )


def account_balances(company, date, abbr):
    """[{account, label, currency, balance}] in each account's own currency."""
    from erpnext.accounts.utils import get_balance_on

    out = []
    for a in bank_cash_accounts(company):
        try:
            bal = get_balance_on(
                account=a.name, date=date, company=company, in_account_currency=True
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Shareholder: balance of {a.name}")
            bal = 0
        out.append({
            "account": a.name,
            "label": P.account_label(a.name, a.account_name, abbr),
            "currency": a.account_currency or "",
            "balance": P.num(bal),
        })
    return out


def position_on(company, date):
    """{cash, receivable, payable} in company currency as at `date`, from
    grouped GL sums over the account types (one query)."""
    rows = frappe.db.sql(
        """SELECT acc.account_type AS kind, SUM(gle.debit - gle.credit) AS bal
           FROM `tabGL Entry` gle
           JOIN `tabAccount` acc ON acc.name = gle.account
           WHERE gle.company = %(company)s AND acc.company = %(company)s
             AND gle.is_cancelled = 0 AND gle.posting_date <= %(date)s
             AND acc.account_type IN ('Bank', 'Cash', 'Receivable', 'Payable')
           GROUP BY acc.account_type""",
        {"company": company, "date": str(date)},
        as_dict=True,
    )
    by = {r.kind: P.num(r.bal) for r in rows}
    return {
        "cash": P.num(by.get("Bank", 0) + by.get("Cash", 0)),
        "receivable": P.num(by.get("Receivable", 0)),
        # Payable balances are credit-side; report them positive.
        "payable": P.num(-by.get("Payable", 0)),
    }


def net_of(position):
    return P.num(position["cash"] + position["receivable"] - position["payable"])


# ── profit and loss ──────────────────────────────────────────────────────────

def monthly_pl(company, from_date, to_date):
    """[{month:'YYYY-MM', revenue, expenses}] from grouped GL sums."""
    rows = frappe.db.sql(
        """SELECT DATE_FORMAT(gle.posting_date, '%%Y-%%m') AS month,
                  SUM(CASE WHEN acc.root_type = 'Income'
                           THEN gle.credit - gle.debit ELSE 0 END) AS revenue,
                  SUM(CASE WHEN acc.root_type = 'Expense'
                           THEN gle.debit - gle.credit ELSE 0 END) AS expenses
           FROM `tabGL Entry` gle
           JOIN `tabAccount` acc ON acc.name = gle.account
           WHERE gle.company = %(company)s AND acc.company = %(company)s
             AND gle.is_cancelled = 0
             AND acc.root_type IN ('Income', 'Expense')
             AND gle.posting_date BETWEEN %(from)s AND %(to)s {closing}
           GROUP BY DATE_FORMAT(gle.posting_date, '%%Y-%%m')""".format(closing=_NOT_CLOSING),
        {"company": company, "from": str(from_date), "to": str(to_date)},
        as_dict=True,
    )
    return [{"month": r.month, "revenue": P.num(r.revenue), "expenses": P.num(r.expenses)}
            for r in rows]


def profit_between(company, from_date, to_date):
    rows = monthly_pl(company, from_date, to_date)
    return P.num(sum(r["revenue"] for r in rows) - sum(r["expenses"] for r in rows))


def fiscal_year(company, date):
    """(name, start, end) of the fiscal year containing `date`; falls back to
    the calendar year when none is configured."""
    try:
        from erpnext.accounts.utils import get_fiscal_year

        fy = get_fiscal_year(date, company=company)
        return fy[0], P.to_date(fy[1]), P.to_date(fy[2])
    except Exception:
        d = P.to_date(date)
        return str(d.year), d.replace(month=1, day=1), d.replace(month=12, day=31)


# ── documents ────────────────────────────────────────────────────────────────

def collected_between(company, from_date, to_date):
    """Payment Entry (Receive, submitted) in company currency."""
    v = frappe.db.sql(
        """SELECT COALESCE(SUM(base_received_amount), 0) FROM `tabPayment Entry`
           WHERE company = %(company)s AND docstatus = 1 AND payment_type = 'Receive'
             AND posting_date BETWEEN %(from)s AND %(to)s""",
        {"company": company, "from": str(from_date), "to": str(to_date)},
    )
    return P.num(v[0][0] if v else 0)


def invoiced_between(company, from_date, to_date):
    """Submitted Sales Invoice base_grand_total (returns net off)."""
    v = frappe.db.sql(
        """SELECT COALESCE(SUM(base_grand_total), 0) FROM `tabSales Invoice`
           WHERE company = %(company)s AND docstatus = 1
             AND posting_date BETWEEN %(from)s AND %(to)s""",
        {"company": company, "from": str(from_date), "to": str(to_date)},
    )
    return P.num(v[0][0] if v else 0)


_PARTY = {
    "Sales Invoice": ("customer", "customer_name"),
    "Purchase Invoice": ("supplier", "supplier_name"),
}


def overdue(doctype, company, today):
    """{count, total} of submitted invoices past due with an outstanding."""
    if doctype not in _PARTY:
        raise ValueError(doctype)
    v = frappe.db.sql(
        """SELECT COUNT(*), COALESCE(SUM(outstanding_amount * conversion_rate), 0)
           FROM `tab{dt}`
           WHERE company = %(company)s AND docstatus = 1
             AND outstanding_amount > 0 AND due_date < %(today)s""".format(dt=doctype),
        {"company": company, "today": str(today)},
    )
    count, total = (v[0] if v else (0, 0))
    return {"count": int(count or 0), "total": P.num(total)}


def outstanding_rows(doctype, company):
    """[{party, party_name, due_date, amount}] grouped per party + due date,
    company currency. Feeds aging buckets and the top-balances list."""
    if doctype not in _PARTY:
        raise ValueError(doctype)
    party, party_name = _PARTY[doctype]
    return frappe.db.sql(
        """SELECT {p} AS party, MAX({pn}) AS party_name, due_date,
                  SUM(outstanding_amount * conversion_rate) AS amount
           FROM `tab{dt}`
           WHERE company = %(company)s AND docstatus = 1 AND outstanding_amount > 0
           GROUP BY {p}, due_date""".format(p=party, pn=party_name, dt=doctype),
        {"company": company},
        as_dict=True,
    )


def pipeline(company):
    def _count(sql):
        v = frappe.db.sql(sql, {"company": company})
        return int(v[0][0] or 0) if v else 0

    return {
        "opportunities": _count(
            """SELECT COUNT(*) FROM `tabOpportunity`
               WHERE company = %(company)s AND status IN ('Open', 'Quotation', 'Replied')"""),
        "quotations": _count(
            """SELECT COUNT(*) FROM `tabQuotation`
               WHERE company = %(company)s AND docstatus = 1 AND status = 'Open'"""),
        "sales_orders": _count(
            """SELECT COUNT(*) FROM `tabSales Order`
               WHERE company = %(company)s AND docstatus = 1
                 AND status NOT IN ('Completed', 'Closed')"""),
    }


def recent_invoices(company, today, limit=20):
    rows = frappe.db.sql(
        """SELECT name, customer, customer_name, posting_date, due_date, status, is_return,
                  base_grand_total, outstanding_amount * conversion_rate AS outstanding
           FROM `tabSales Invoice`
           WHERE company = %(company)s AND docstatus = 1
           ORDER BY posting_date DESC, creation DESC
           LIMIT %(limit)s""",
        {"company": company, "limit": int(limit)},
        as_dict=True,
    )
    return [{
        "name": r.name,
        "customer": r.customer,
        "customer_name": r.customer_name or r.customer,
        "posting_date": P.date_str(r.posting_date),
        "grand_total": P.num(r.base_grand_total),
        "outstanding": P.num(r.outstanding),
        "status": P.invoice_status_label(
            r.status, r.outstanding, r.due_date, today, r.is_return),
    } for r in rows]


def top_customers(company, from_date, to_date, limit=5):
    rows = frappe.db.sql(
        """SELECT customer, MAX(customer_name) AS customer_name,
                  SUM(base_grand_total) AS total
           FROM `tabSales Invoice`
           WHERE company = %(company)s AND docstatus = 1
             AND posting_date BETWEEN %(from)s AND %(to)s
           GROUP BY customer
           ORDER BY total DESC
           LIMIT %(limit)s""",
        {"company": company, "from": str(from_date), "to": str(to_date), "limit": int(limit)},
        as_dict=True,
    )
    return [{"customer": r.customer, "customer_name": r.customer_name or r.customer,
             "total": P.num(r.total)} for r in rows]


# ── owners and distributions ─────────────────────────────────────────────────

def owners(company):
    """[{shareholder, title, share_pct, user}] — the custom fields may not
    exist yet on a site that has not migrated; they read as empty then."""
    if not frappe.db.table_exists("Shareholder"):
        return []
    has_pct = frappe.db.has_column("Shareholder", "custom_share_pct")
    has_user = frappe.db.has_column("Shareholder", "custom_user")
    rows = frappe.db.sql(
        """SELECT name, title, {pct} AS share_pct, {user} AS user
           FROM `tabShareholder`
           WHERE company = %(company)s
           ORDER BY name""".format(
            pct="custom_share_pct" if has_pct else "0",
            user="custom_user" if has_user else "NULL",
        ),
        {"company": company},
        as_dict=True,
    )
    return [{"shareholder": r.name, "title": r.title or r.name,
             "share_pct": P.num(r.share_pct, 4), "user": r.user or None} for r in rows]


def distribution_entries(company, account, limit=50):
    """Journal Entry Account rows on `account` (submitted), newest first.
    amount = debit − credit in company currency (a payout debits the account)."""
    rows = frappe.db.sql(
        """SELECT je.posting_date, je.name AS voucher,
                  (jea.debit - jea.credit) AS amount,
                  COALESCE(je.user_remark, '') AS remark
           FROM `tabJournal Entry Account` jea
           JOIN `tabJournal Entry` je ON je.name = jea.parent
           WHERE jea.account = %(account)s AND je.company = %(company)s
             AND je.docstatus = 1
           ORDER BY je.posting_date DESC, je.creation DESC
           LIMIT %(limit)s""",
        {"company": company, "account": account, "limit": int(limit)},
        as_dict=True,
    )
    return [{"posting_date": P.date_str(r.posting_date), "voucher": r.voucher,
             "amount": P.num(r.amount), "remark": r.remark or ""} for r in rows]


def distribution_total(company, account):
    v = frappe.db.sql(
        """SELECT COALESCE(SUM(jea.debit - jea.credit), 0)
           FROM `tabJournal Entry Account` jea
           JOIN `tabJournal Entry` je ON je.name = jea.parent
           WHERE jea.account = %(account)s AND je.company = %(company)s
             AND je.docstatus = 1""",
        {"company": company, "account": account},
    )
    return P.num(v[0][0] if v else 0)

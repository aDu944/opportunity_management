"""
Endpoints of the shareholder app (shareholder_contract.md).

    opportunity_management.opportunity_management.shareholder_api.<name>

Every endpoint starts with `_require_shareholder()` (Shareholder or System
Manager). The company is fixed by ESS Mobile Settings `shareholder_company`.
Company-level figures are cached for five minutes per (endpoint, company);
`refresh=1` (pull-to-refresh) bypasses and rewrites the cache. Per-caller
bits (chats waiting, approvals) are never cached.

Each independent block is wrapped so one failing query logs an Error Log and
returns zeros/empties for that block instead of blanking the whole screen.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, now_datetime, nowdate

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import shareholder_finance as F
from opportunity_management.opportunity_management import shareholder_pure as P

CACHE_TTL = 300
SHAREHOLDER_ROLES = {"Shareholder", "System Manager"}
DEFAULT_COMPANY = "AL KHORA"


# ── plumbing ─────────────────────────────────────────────────────────────────

def _require_shareholder():
    if frappe.session.user == "Guest":
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    if not SHAREHOLDER_ROLES & set(frappe.get_roles(frappe.session.user)):
        frappe.throw(_("Only shareholders can open this screen"), frappe.PermissionError)


def _settings_value(field):
    try:
        return frappe.db.get_single_value("ESS Mobile Settings", field)
    except Exception:
        return None


def _company():
    company = _settings_value("shareholder_company") or DEFAULT_COMPANY
    if not frappe.db.exists("Company", company):
        frappe.throw(_("Shareholder company {0} not found").format(company))
    return company


def _cached(endpoint, company, refresh, build):
    key = f"shareholder:{endpoint}:{company}"
    cache = frappe.cache()
    if not cint(refresh):
        try:
            hit = cache.get_value(key)
            if hit:
                return hit
        except Exception:
            pass
    data = build()
    try:
        cache.set_value(key, data, expires_in_sec=CACHE_TTL)
    except Exception:
        pass
    return data


def _safe(title, fn, default):
    """Run one block; on failure log it and return `default`."""
    try:
        return fn()
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Shareholder: {title}")
        return default


def _today():
    return P.to_date(nowdate())


def _series(company, today):
    labels = P.six_month_labels(today)
    rows = F.monthly_pl(company, P.series_start(today), today)
    return P.build_series(rows, labels)


def _zero_series(today):
    return P.build_series([], P.six_month_labels(today))


# ── per-caller blocks (never cached) ─────────────────────────────────────────

def _chats_waiting():
    from opportunity_management.opportunity_management.whatsapp_api_common import (
        _require_inbox_access,
    )

    try:
        _require_inbox_access()
    except frappe.PermissionError:
        return None
    where = IC.list_channel_sql("", IC.user_channels())
    row = frappe.db.sql(
        """SELECT COUNT(*) AS waiting,
                  SUM(CASE WHEN assigned_to IS NULL OR assigned_to = ''
                           THEN 1 ELSE 0 END) AS unassigned,
                  MIN(awaiting_reply_since) AS oldest
           FROM `tabWhatsApp Conversation`
           WHERE status != 'Resolved' AND awaiting_reply_since IS NOT NULL
             AND COALESCE(is_blocked, 0) = 0 {0}""".format("AND " + where if where else ""),
        as_dict=True,
    )
    r = row[0] if row else {}
    longest = 0
    if r.get("oldest"):
        longest = max(0, int((now_datetime() - get_datetime(r["oldest"])).total_seconds()))
    return {"count": cint(r.get("waiting")), "unassigned": cint(r.get("unassigned")),
            "longest_wait_seconds": longest}


def _approvals():
    """Pending leave approvals for the caller — the same rule as the staff
    app's ApprovalsPage (`approvals_page.dart`): System Managers see every
    Open draft, everyone else the ones where they are `leave_approver`."""
    if not frappe.db.table_exists("Leave Application"):
        return None
    user = frappe.session.user
    if "System Manager" in frappe.get_roles(user):
        filters = {"status": "Open", "docstatus": 0}
    else:
        filters = {"status": "Open", "leave_approver": user}
    return {"count": cint(frappe.db.count("Leave Application", filters))}


# ── endpoints ────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_overview(refresh=0):
    _require_shareholder()
    company = _company()
    data = dict(_cached("overview", company, refresh, lambda: _overview(company)))
    attention = dict(data.get("attention") or {})
    attention["chats_waiting"] = _safe("chats waiting", _chats_waiting, None)
    attention["approvals"] = _safe("approvals", _approvals, None)
    data["attention"] = attention
    return data


def _overview(company):
    today = _today()
    meta = F.company_meta(company)
    m_start = P.month_start(today)
    zero_pos = {"cash": 0.0, "receivable": 0.0, "payable": 0.0}

    pos = _safe("position", lambda: F.position_on(company, today), zero_pos)
    prev = _safe("previous position",
                 lambda: F.position_on(company, P.previous_month_end(today)), zero_pos)
    value, previous = F.net_of(pos), F.net_of(prev)

    def _month():
        rows = F.monthly_pl(company, m_start, today)
        revenue = P.num(sum(r["revenue"] for r in rows))
        expenses = P.num(sum(r["expenses"] for r in rows))
        return {"revenue": revenue, "expenses": expenses, "net": P.num(revenue - expenses)}

    month = {"label": P.month_label(today)}
    month.update(_safe("month", _month, {"revenue": 0.0, "expenses": 0.0, "net": 0.0}))
    month["collected"] = _safe(
        "month collected", lambda: F.collected_between(company, m_start, today), 0.0)

    new_chats = _safe("new chats", lambda: cint(frappe.db.sql(
        """SELECT COUNT(*) FROM `tabWhatsApp Conversation`
           WHERE first_contact_at >= %(start)s""",
        {"start": f"{today} 00:00:00"})[0][0]), 0)
    zero = {"count": 0, "total": 0.0}
    return {
        "company": company,
        "currency": meta["currency"],
        "as_of": str(now_datetime()),
        "net_position": {"value": value, "previous": previous,
                         "delta_pct": P.delta_pct(value, previous)},
        "cash": pos["cash"],
        "receivable": pos["receivable"],
        "payable": pos["payable"],
        "month": month,
        "series": _safe("series", lambda: _series(company, today), _zero_series(today)),
        "today": {
            "invoiced": _safe("today invoiced",
                              lambda: F.invoiced_between(company, today, today), 0.0),
            "collected": _safe("today collected",
                               lambda: F.collected_between(company, today, today), 0.0),
            "new_chats": new_chats,
        },
        "attention": {
            "overdue_invoices": _safe("overdue invoices",
                                      lambda: F.overdue("Sales Invoice", company, today), zero),
            "overdue_bills": _safe("overdue bills",
                                   lambda: F.overdue("Purchase Invoice", company, today), zero),
            "chats_waiting": None,
            "approvals": None,
        },
    }


@frappe.whitelist()
def get_money(refresh=0):
    _require_shareholder()
    company = _company()
    return _cached("money", company, refresh, lambda: _money(company))


def _money(company):
    today = _today()
    meta = F.company_meta(company)
    accounts = _safe("bank balances",
                     lambda: F.account_balances(company, today, meta["abbr"]), [])
    pos = _safe("position", lambda: F.position_on(company, today),
                {"receivable": 0.0, "payable": 0.0})

    def _side(doctype, total):
        rows = _safe(f"{doctype} outstanding",
                     lambda: F.outstanding_rows(doctype, company), [])
        return {"total": total, "aging": P.aging_summary(rows, today),
                "top": P.top_parties(rows, 5)}

    return {
        "currency": meta["currency"],
        "totals_by_currency": P.totals_by_currency(accounts),
        "accounts": accounts,
        "receivable": _side("Sales Invoice", pos["receivable"]),
        "payable": _side("Purchase Invoice", pos["payable"]),
    }


@frappe.whitelist()
def get_sales(refresh=0):
    _require_shareholder()
    company = _company()
    return _cached("sales", company, refresh, lambda: _sales(company))


def _sales(company):
    today = _today()
    meta = F.company_meta(company)
    last = P.same_day_last_month(today)

    def _mtd():
        cur = F.invoiced_between(company, P.month_start(today), today)
        prev = F.invoiced_between(company, P.month_start(last), last)
        return {"invoiced": cur, "previous_same_day": prev, "delta_pct": P.delta_pct(cur, prev)}

    _, fy_start, _ = F.fiscal_year(company, today)
    return {
        "currency": meta["currency"],
        "mtd": _safe("mtd", _mtd, {"invoiced": 0.0, "previous_same_day": 0.0, "delta_pct": None}),
        "series": _safe("series", lambda: _series(company, today), _zero_series(today)),
        "pipeline": _safe("pipeline", lambda: F.pipeline(company),
                          {"opportunities": 0, "quotations": 0, "sales_orders": 0}),
        "recent": _safe("recent invoices", lambda: F.recent_invoices(company, today, 20), []),
        "top_customers": _safe("top customers",
                               lambda: F.top_customers(company, fy_start, today, 5), []),
    }


@frappe.whitelist()
def get_distributions(refresh=0):
    _require_shareholder()
    company = _company()
    return _cached("distributions", company, refresh, lambda: _distributions(company))


def _distribution_account(company):
    account = _settings_value("distribution_account")
    if not account:
        return None
    if frappe.db.get_value("Account", account, "company") != company:
        return None
    return account


def _distributions(company):
    today = _today()
    meta = F.company_meta(company)
    fy_name, fy_start, _ = F.fiscal_year(company, today)
    profit = _safe("profit ytd", lambda: F.profit_between(company, fy_start, today), 0.0)
    owners = _safe("owners", lambda: F.owners(company), [])
    account = _safe("distribution account", lambda: _distribution_account(company), None)
    entries, total = [], 0.0
    if account:
        entries = _safe("distribution entries",
                        lambda: F.distribution_entries(company, account, 50), [])
        total = _safe("distribution total", lambda: F.distribution_total(company, account), 0.0)
    return {
        "currency": meta["currency"],
        "fiscal_year": fy_name,
        "profit_ytd": profit,
        "owners": P.indicative_split(profit, owners),
        "account": account,
        "entries": entries,
        "total_distributed": total,
    }


@frappe.whitelist()
def get_chat_oversight():
    """Live (never cached): who is waiting and who is handling it."""
    _require_shareholder()
    from opportunity_management.opportunity_management.whatsapp_api_common import (
        _require_inbox_access,
    )
    from opportunity_management.opportunity_management.whatsapp_api_crm import _median

    _require_inbox_access()
    channels = IC.user_channels()
    where = IC.list_channel_sql("", channels)
    ch = " AND " + where if where else ""

    def _counts():
        r = frappe.db.sql(
            """SELECT
                 SUM(CASE WHEN awaiting_reply_since IS NOT NULL
                           AND COALESCE(is_blocked, 0) = 0 THEN 1 ELSE 0 END) AS waiting,
                 SUM(CASE WHEN assigned_to IS NULL OR assigned_to = ''
                          THEN 1 ELSE 0 END) AS unassigned
               FROM `tabWhatsApp Conversation`
               WHERE status != 'Resolved'""" + ch,
            as_dict=True,
        )
        r = r[0] if r else {}
        return cint(r.get("waiting")), cint(r.get("unassigned"))

    def _median_reply():
        since = f"{add_days(nowdate(), -7)} 00:00:00"
        rows = frappe.db.sql(
            """SELECT first_response_seconds FROM `tabWhatsApp Conversation`
               WHERE COALESCE(first_response_seconds, 0) > 0
                 AND first_contact_at >= %(since)s""" + ch,
            {"since": since},
        )
        return _median([cint(r[0]) for r in rows])

    def _agents():
        open_by = dict(frappe.db.sql(
            """SELECT assigned_to, COUNT(*) FROM `tabWhatsApp Conversation`
               WHERE status != 'Resolved' AND assigned_to IS NOT NULL
                 AND assigned_to != ''""" + ch + """
               GROUP BY assigned_to"""))
        users = [u for u, _chs in IC.roster(channels)]
        users += [u for u in open_by if u not in users]
        names = dict(frappe.db.sql(
            """SELECT name, full_name FROM `tabUser` WHERE name IN %(users)s""",
            {"users": tuple(users)})) if users else {}
        out = [{"user": u, "full_name": names.get(u) or u, "open_count": cint(open_by.get(u))}
               for u in users]
        out.sort(key=lambda a: (-a["open_count"], str(a["full_name"]).lower()))
        return out

    waiting, unassigned = _safe("oversight counts", _counts, (0, 0))
    return {
        "waiting": waiting,
        "unassigned": unassigned,
        "median_first_response_seconds": _safe("median first reply", _median_reply, 0),
        "agents": _safe("agents", _agents, []),
    }

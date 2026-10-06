"""
"Team today" card on the staff Home for check-in-exempt managers.

`get_team_today` rolls up today's attendance of every active, non-exempt
employee (present / late / on leave / not in yet / checked out), plus the
caller's pending leave approvals and waiting WhatsApp chats. Each block is
isolated: a failure is logged and that block returns zeros / null.

`get_team_attendance` backs the Team attendance page behind the card: the
same population, one row per employee for a chosen day (SQL in
`team_today_rows`, shaping in `team_today_pure`).
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

from opportunity_management.opportunity_management import team_today_pure as P
from opportunity_management.opportunity_management import team_today_rows as R
from opportunity_management.opportunity_management.checkin_exempt import exempt_filter_sql

ALLOWED_ROLES = {"System Manager", "HR Manager", "HR User"}


def _require_manager():
    user = frappe.session.user
    if user == "Guest" or not ALLOWED_ROLES & set(frappe.get_roles(user)):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _safe(title, fn, default):
    try:
        return fn()
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Team Today: {title}")
        return default


def _cutoff():
    try:
        s = frappe.get_cached_doc("ESS Mobile Settings")
        return P.late_cutoff(s.get("expected_checkin_hour"),
                             s.get("late_checkin_threshold_minutes"))
    except Exception:
        return P.late_cutoff(None, None)


def _rows(day):
    """One row per active, non-exempt employee with today's IN/OUT bounds
    and whether an approved, submitted leave covers today."""
    return frappe.db.sql(
        """
        SELECT e.name, e.employee_name,
               (SELECT MIN(c.time) FROM `tabEmployee Checkin` c
                 WHERE c.employee = e.name AND c.log_type = 'IN'
                   AND DATE(c.time) = %(day)s) AS first_in,
               (SELECT MAX(c.time) FROM `tabEmployee Checkin` c
                 WHERE c.employee = e.name AND c.log_type = 'IN'
                   AND DATE(c.time) = %(day)s) AS last_in,
               (SELECT MAX(c.time) FROM `tabEmployee Checkin` c
                 WHERE c.employee = e.name AND c.log_type = 'OUT'
                   AND DATE(c.time) = %(day)s) AS last_out,
               EXISTS (SELECT 1 FROM `tabLeave Application` la
                        WHERE la.employee = e.name AND la.docstatus = 1
                          AND la.status = 'Approved'
                          AND %(day)s BETWEEN la.from_date AND la.to_date) AS on_leave
        FROM `tabEmployee` e
        WHERE e.status = 'Active'
        """ + exempt_filter_sql(),
        {"day": day},
        as_dict=True,
    )


def _approvals_count():
    from opportunity_management.opportunity_management.shareholder_api import _approvals
    res = _approvals()
    return int((res or {}).get("count") or 0)


def _chats_count():
    from opportunity_management.opportunity_management.shareholder_api import _chats_waiting
    res = _chats_waiting()
    return None if res is None else int(res.get("count") or 0)


@frappe.whitelist()
def get_team_today():
    _require_manager()
    day = str(getdate(today()))  # site timezone (Asia/Baghdad), as the reminders use
    out = {"date": day}
    cutoff = _cutoff()
    out.update(_safe("attendance", lambda: P.summarize(_rows(day), cutoff),
                     P.empty_summary()))
    out["approvals_pending"] = _safe("approvals", _approvals_count, 0)
    out["chats_waiting"] = _safe("chats waiting", _chats_count, None)
    return out


def _resolve_day(date):
    """Requested date as a date; garbage / missing / future → today."""
    today_ = getdate(today())
    try:
        requested = getdate(date) if date else None
    except Exception:
        requested = None
    return P.clamp_day(requested, today_)


def _working_day(day):
    try:
        s = frappe.get_cached_doc("ESS Mobile Settings")
        working = s.get("working_days")
    except Exception:
        working = None
    off = _safe("holidays", lambda: R.holidays(day), set())
    return P.is_working_day(day, working, off)


@frappe.whitelist()
def get_team_attendance(date=None):
    """Per-employee attendance for one day (Team attendance page).

    Same audience and population as `get_team_today`; the summary is the
    card's roll-up of the same rows so the two always agree."""
    _require_manager()
    day = _resolve_day(date)
    cutoff = _cutoff()
    raw = R.attendance_rows(day)
    leaves = _safe("attendance leaves", lambda: R.leave_types(day), {})
    summary, rows = P.build_attendance(raw, leaves, cutoff)
    return {
        "date": str(day),
        "summary": summary,
        "is_working_day": _working_day(day),
        "rows": rows,
    }

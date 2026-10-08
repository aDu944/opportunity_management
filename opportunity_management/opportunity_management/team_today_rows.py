"""
SQL for `team_today.get_team_attendance` — one grouped query over active,
non-exempt, non-review-account employees with the day's check-in bounds and the first IN's
outside-zone flag, plus one leave query. Pure shaping lives in
`team_today_pure` (bench-free tests).
"""

import datetime as _dt

import frappe

from opportunity_management.opportunity_management import team_today_pure as P
from opportunity_management.opportunity_management.checkin_exempt import team_filter_sql


def _zone_expr():
    """GROUP_CONCAT of "<flag>|<reason>" per IN ordered by time, or NULL when
    the outside-zone custom fields are not installed."""
    try:
        has = frappe.db.has_column("Employee Checkin", "custom_outside_zone")
        has_reason = frappe.db.has_column("Employee Checkin", "custom_outside_zone_reason")
    except Exception:
        has = has_reason = False
    if not has:
        return "NULL"
    reason = "COALESCE(c.custom_outside_zone_reason, '')" if has_reason else "''"
    return (
        "GROUP_CONCAT(CASE WHEN c.log_type = 'IN' THEN CONCAT("
        f"COALESCE(c.custom_outside_zone, 0), '{P.ZONE_FIELD_SEP}', {reason}) END "
        # SEPARATOR must be a string literal in MariaDB (CHAR(30) is a syntax
        # error there); embed the record separator itself.
        f"ORDER BY c.time SEPARATOR '{P.ZONE_SEP}')"
    )


def attendance_rows(day):
    """Per-employee rows: employee, employee_name, branch, department,
    designation, image, first_in, last_in, last_out, zone. The checkin join is a time range
    (index-friendly) instead of DATE(c.time)."""
    start = _dt.datetime.combine(day, _dt.time.min)
    end = start + _dt.timedelta(days=1)
    return frappe.db.sql(
        f"""
        SELECT e.name AS employee, e.employee_name, e.branch, e.department,
               e.designation, e.image,
               MIN(CASE WHEN c.log_type = 'IN' THEN c.time END) AS first_in,
               MAX(CASE WHEN c.log_type = 'IN' THEN c.time END) AS last_in,
               MAX(CASE WHEN c.log_type = 'OUT' THEN c.time END) AS last_out,
               {_zone_expr()} AS zone
        FROM `tabEmployee` e
        LEFT JOIN `tabEmployee Checkin` c
               ON c.employee = e.name
              AND c.time >= %(start)s AND c.time < %(end)s
        WHERE e.status = 'Active'{team_filter_sql()}
        GROUP BY e.name, e.employee_name, e.branch, e.department, e.designation, e.image
        """,
        {"start": start, "end": end},
        as_dict=True,
    )


def leave_types(day):
    """{employee: leave_type} for approved, submitted leave covering `day`
    (same rule as the Home card's on-leave count)."""
    rows = frappe.db.sql(
        """
        SELECT employee, leave_type FROM `tabLeave Application`
        WHERE docstatus = 1 AND status = 'Approved'
          AND %(day)s BETWEEN from_date AND to_date
        ORDER BY from_date
        """,
        {"day": day},
        as_dict=True,
    )
    return {r.employee: r.leave_type for r in rows}


def holidays(day):
    """{day} when it is a holiday in any company's default holiday list
    (company-agnostic: a holiday anywhere counts), else an empty set."""
    rows = frappe.db.sql(
        """
        SELECT DISTINCT h.holiday_date FROM `tabHoliday` h
        JOIN `tabCompany` co ON co.default_holiday_list = h.parent
        WHERE h.holiday_date = %(day)s
        """,
        {"day": day},
    )
    return {r[0] for r in rows}


def caller_branch(user):
    """Employee.branch of `user` ("" when none / no Employee). An Active
    Employee wins over a left one with the same login."""
    rows = frappe.db.sql(
        """
        SELECT e.branch FROM `tabEmployee` e
        WHERE e.user_id = %(user)s
        ORDER BY (e.status = 'Active') DESC, e.modified DESC
        LIMIT 1
        """,
        {"user": user},
    )
    return P.norm_branch(rows[0][0]) if rows else ""

"""Daily Attendance — Baghdad

One row per active Baghdad-Branch employee for the selected date. Pulls the
real check-in/out times directly from Employee Checkin (the authoritative
source the mobile app writes to), determines status, and shows the reason if
the check-in was made outside the approved zone.

Designed to be printed: HR opens the report, picks the date (defaults to
today), hits Print, gets a single-page PDF roll-up for the morning briefing.
"""

import frappe
from frappe import _
from frappe.utils import getdate, get_time, time_diff_in_hours, format_time


# Default cutoff used when ESS Mobile Settings is missing values.
_DEFAULT_EXPECTED_HOUR = 9
_DEFAULT_THRESHOLD_MIN = 15


def execute(filters=None):
	filters = filters or {}
	date = getdate(filters.get("date") or frappe.utils.today())

	expected_hour, threshold_min = _get_late_cutoff()
	cutoff_minutes = expected_hour * 60 + threshold_min  # e.g. 9*60+15 = 555

	employees = _get_baghdad_employees()
	if not employees:
		return _columns(), []

	emp_ids = [e["name"] for e in employees]

	checkins = _get_checkins(emp_ids, date)
	leaves = _get_leaves(emp_ids, date)

	rows = []
	for emp in employees:
		emp_id = emp["name"]
		emp_checkins = checkins.get(emp_id, [])
		on_leave = emp_id in leaves

		in_time = None
		out_time = None
		outside_zone = 0
		outside_zone_reason = ""
		for c in emp_checkins:
			if c["log_type"] == "IN" and in_time is None:
				in_time = c["time"]
				outside_zone = max(outside_zone, c.get("custom_outside_zone") or 0)
				if c.get("custom_outside_zone_reason"):
					outside_zone_reason = c["custom_outside_zone_reason"]
			elif c["log_type"] == "OUT":
				out_time = c["time"]  # use latest OUT

		# Status
		if on_leave:
			status, indicator = _("On Leave"), "blue"
		elif in_time is None:
			status, indicator = _("Absent"), "red"
		else:
			actual_minutes = in_time.hour * 60 + in_time.minute + (1 if in_time.second > 0 else 0)
			if actual_minutes <= cutoff_minutes:
				status, indicator = _("On Time"), "green"
			else:
				status, indicator = _("Late"), "orange"
			if outside_zone:
				status = f"{status} • {_('Outside Zone')}"
				indicator = "orange"

		hours = 0.0
		if in_time and out_time and out_time > in_time:
			hours = round(time_diff_in_hours(out_time, in_time), 2)

		rows.append({
			"employee": emp_id,
			"employee_name": emp["employee_name"],
			"department": emp.get("department") or "",
			"in_time": _fmt_time(in_time),
			"out_time": _fmt_time(out_time),
			"hours": hours if hours else None,
			"status": status,
			"reason": outside_zone_reason,
			"indicator": indicator,
		})

	# Sort: Absent first (so HR sees them at the top), then Late, then On Time, then On Leave.
	priority = {"red": 0, "orange": 1, "green": 2, "blue": 3}
	rows.sort(key=lambda r: (priority.get(r["indicator"], 9), r["employee_name"]))

	# Strip the indicator key from final rows (used only for sort + cell colour).
	for r in rows:
		r.pop("indicator", None)

	return _columns(), rows


def _columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link",
		 "options": "Employee", "width": 110},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 200},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link",
		 "options": "Department", "width": 140},
		{"label": _("Check In"), "fieldname": "in_time", "fieldtype": "Data", "width": 90},
		{"label": _("Check Out"), "fieldname": "out_time", "fieldtype": "Data", "width": 90},
		{"label": _("Hours"), "fieldname": "hours", "fieldtype": "Float",
		 "precision": 2, "width": 70},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 160},
		{"label": _("Reason (if outside zone)"), "fieldname": "reason",
		 "fieldtype": "Small Text", "width": 250},
	]


def _get_baghdad_employees():
	return frappe.db.sql("""
		SELECT name, employee_name, department
		FROM `tabEmployee`
		WHERE status = 'Active' AND branch = 'Baghdad'
		ORDER BY employee_name
	""", as_dict=True)


def _get_checkins(emp_ids, date):
	if not emp_ids:
		return {}
	rows = frappe.db.sql("""
		SELECT employee, log_type, time, custom_outside_zone, custom_outside_zone_reason
		FROM `tabEmployee Checkin`
		WHERE employee IN %(emps)s AND DATE(time) = %(date)s
		ORDER BY time
	""", {"emps": tuple(emp_ids), "date": date}, as_dict=True)
	grouped = {}
	for r in rows:
		grouped.setdefault(r["employee"], []).append(r)
	return grouped


def _get_leaves(emp_ids, date):
	"""Employees on submitted leave (full day) for the given date."""
	if not emp_ids:
		return set()
	rows = frappe.db.sql("""
		SELECT DISTINCT employee FROM `tabLeave Application`
		WHERE employee IN %(emps)s
		  AND docstatus = 1
		  AND %(date)s BETWEEN from_date AND to_date
		  AND (half_day = 0 OR half_day IS NULL)
	""", {"emps": tuple(emp_ids), "date": date}, as_dict=True)
	return {r["employee"] for r in rows}


def _get_late_cutoff():
	try:
		s = frappe.get_single("ESS Mobile Settings")
		h = int(s.get("expected_checkin_hour") or _DEFAULT_EXPECTED_HOUR)
		m = int(s.get("late_checkin_threshold_minutes") or _DEFAULT_THRESHOLD_MIN)
		return h, m
	except Exception:
		return _DEFAULT_EXPECTED_HOUR, _DEFAULT_THRESHOLD_MIN


def _fmt_time(t):
	if not t:
		return ""
	try:
		return format_time(get_time(t.strftime("%H:%M:%S")), "HH:mm")
	except Exception:
		return str(t)

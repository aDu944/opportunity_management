"""
ESS Control Panel — server-side methods.
"""

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def get_dashboard_stats():
    """Return summary stats for the ESS dashboard."""
    total_employees = frappe.db.count("Employee", {"status": "Active"})
    with_token = frappe.db.count("Employee", {"status": "Active", "custom_fcm_token": ["!=", ""]})
    without_token = total_employees - with_token

    today = frappe.utils.today()
    checkins_today = frappe.db.count("Employee Checkin", {"time": ["like", f"{today}%"]})

    pending_leaves = frappe.db.count("Leave Application", {"status": "Open"})
    pending_expenses = frappe.db.count("Expense Claim", {"approval_status": "Draft"})

    return {
        "total_employees": total_employees,
        "with_fcm_token": with_token,
        "without_fcm_token": without_token,
        "checkins_today": checkins_today,
        "pending_leaves": pending_leaves,
        "pending_expenses": pending_expenses,
    }


@frappe.whitelist()
def get_employees_fcm_status():
    """Return list of active employees with their FCM token status."""
    employees = frappe.db.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name", "department", "designation", "custom_fcm_token"],
        order_by="employee_name asc",
    )
    for emp in employees:
        emp["has_token"] = bool(emp.get("custom_fcm_token"))
        emp["custom_fcm_token"] = "••••••••" + emp["custom_fcm_token"][-8:] if emp.get("custom_fcm_token") else ""
    return employees


@frappe.whitelist()
def send_test_notification(employee_id, title, body):
    """Send a test FCM notification to a specific employee."""
    from opportunity_management.opportunity_management.fcm_utils import send_fcm_to_employee
    success = send_fcm_to_employee(employee_id, title=title, body=body, data={"type": "test"})
    return {"status": "sent" if success else "failed"}


@frappe.whitelist()
def broadcast_notification(title, body):
    """Send an FCM notification to all active employees with a token."""
    from opportunity_management.opportunity_management.fcm_utils import send_fcm
    employees = frappe.db.get_all(
        "Employee",
        filters={"status": "Active", "custom_fcm_token": ["!=", ""]},
        fields=["name", "custom_fcm_token"],
    )
    sent = 0
    failed = 0
    for emp in employees:
        ok = send_fcm(emp["custom_fcm_token"], title=title, body=body, data={"type": "broadcast"})
        if ok:
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed}


@frappe.whitelist()
def get_recent_checkins(limit=50):
    """Return recent employee check-ins."""
    checkins = frappe.db.sql("""
        SELECT
            ec.name,
            ec.employee,
            e.employee_name,
            ec.log_type,
            ec.time,
            ec.custom_outside_zone,
            ec.latitude,
            ec.longitude
        FROM `tabEmployee Checkin` ec
        LEFT JOIN `tabEmployee` e ON e.name = ec.employee
        ORDER BY ec.time DESC
        LIMIT %(limit)s
    """, {"limit": int(limit)}, as_dict=True)
    return checkins


@frappe.whitelist()
def get_punch_locations():
    """Return all configured punch geolocations."""
    locations = frappe.db.get_all(
        "Punch Geolocation",
        fields=["name", "location_name", "custom_location_name_ar", "latitude", "longitude", "radius"],
        order_by="location_name asc",
    )
    return locations


@frappe.whitelist()
def get_ess_settings():
    """Return current ESS app settings from site config."""
    return {
        "checkin_start_hour": frappe.conf.get("ess_checkin_start_hour", 9),
        "checkin_end_hour": frappe.conf.get("ess_checkin_end_hour", 10),
        "firebase_configured": bool(frappe.conf.get("firebase_service_account")),
    }


@frappe.whitelist()
def get_notification_log(limit=30):
    """Return recent ESS-related error logs."""
    logs = frappe.db.get_all(
        "Error Log",
        filters={"method": ["like", "%FCM%"]},
        fields=["name", "method", "error", "creation"],
        order_by="creation desc",
        limit=int(limit),
    )
    return logs

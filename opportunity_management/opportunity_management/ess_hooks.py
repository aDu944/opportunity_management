"""
ESS (Employee Self Service) document event hooks.
Handles email alerts and FCM push notifications triggered by HR document events.
"""

import frappe
from frappe.utils import format_datetime
from opportunity_management.opportunity_management.fcm_utils import send_fcm_to_employee, send_fcm_to_user


# ---------------------------------------------------------------------------
# Leave Application
# ---------------------------------------------------------------------------

def on_leave_application_update(doc, method=None):
    """Notify employee when their leave is approved or rejected."""
    status = doc.status
    if status not in ("Approved", "Rejected"):
        return

    employee_id = doc.employee
    employee_name = frappe.db.get_value("Employee", employee_id, "employee_name") or employee_id

    if status == "Approved":
        title = "إجازتك تمت الموافقة عليها ✓"
        body = f"تمت الموافقة على طلب إجازتك من {doc.from_date} إلى {doc.to_date}."
    else:
        title = "طلب الإجازة مرفوض"
        body = f"تم رفض طلب إجازتك من {doc.from_date} إلى {doc.to_date}."

    send_fcm_to_employee(employee_id, title=title, body=body, data={"doctype": "Leave Application", "name": doc.name})


# ---------------------------------------------------------------------------
# Salary Slip
# ---------------------------------------------------------------------------

def on_salary_slip_submit(doc, method=None):
    """Notify employee when their payslip is ready."""
    employee_id = doc.employee

    title = "قسيمة الراتب جاهزة 💰"
    body = f"قسيمة راتبك لشهر {doc.month_name or doc.start_date} أصبحت متاحة."

    send_fcm_to_employee(employee_id, title=title, body=body, data={"doctype": "Salary Slip", "name": doc.name})


# ---------------------------------------------------------------------------
# Expense Claim
# ---------------------------------------------------------------------------

def on_expense_claim_update(doc, method=None):
    """Notify employee when their expense claim is approved or rejected."""
    status = doc.approval_status
    if status not in ("Approved", "Rejected"):
        return

    employee_id = doc.employee

    if status == "Approved":
        title = "تمت الموافقة على المصروف ✓"
        body = f"تمت الموافقة على مطالبة المصروف بمبلغ {doc.total_claimed_amount} {doc.currency or ''}."
    else:
        title = "مطالبة المصروف مرفوضة"
        body = f"تم رفض مطالبة المصروف بمبلغ {doc.total_claimed_amount} {doc.currency or ''}."

    send_fcm_to_employee(employee_id, title=title, body=body, data={"doctype": "Expense Claim", "name": doc.name})


# ---------------------------------------------------------------------------
# HR Notice / Announcement (custom doctype or Notice Board)
# ---------------------------------------------------------------------------

def on_announcement_insert(doc, method=None):
    """Broadcast a notification to all active employees when an announcement is published."""
    if doc.get("status") and doc.status != "Active":
        return

    title = doc.get("title") or doc.get("subject") or "إعلان جديد"
    body = doc.get("description") or doc.get("content") or ""
    # Truncate long body
    if len(body) > 100:
        body = body[:97] + "…"

    employees = frappe.db.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "custom_fcm_token"],
    )
    for emp in employees:
        if emp.get("custom_fcm_token"):
            from opportunity_management.opportunity_management.fcm_utils import send_fcm
            send_fcm(emp["custom_fcm_token"], title=title, body=body, data={"doctype": "Announcement", "name": doc.name})


def on_checkin_insert(doc, method=None):
    """Notify System Managers when an employee checks in from outside an allowed zone."""
    if not doc.get("custom_outside_zone"):
        return

    employee_name = doc.employee
    # Try to get a friendly display name
    display_name = frappe.db.get_value("Employee", employee_name, "employee_name") or employee_name
    log_type = doc.log_type  # IN or OUT
    checkin_time = format_datetime(doc.time)

    # Get all System Manager emails
    system_managers = frappe.db.sql(
        """
        SELECT DISTINCT u.email
        FROM `tabUser` u
        JOIN `tabHas Role` r ON r.parent = u.name
        WHERE r.role = 'System Manager'
          AND u.enabled = 1
          AND u.email != 'Administrator'
          AND u.email IS NOT NULL
          AND u.email != ''
        """,
        as_dict=True,
    )

    if not system_managers:
        return

    recipients = [row["email"] for row in system_managers]
    log_type_label = "Check-In" if log_type == "IN" else "Check-Out"

    subject = f"⚠ Outside Zone {log_type_label} — {display_name}"

    message = f"""
<p>An employee has performed a <strong>{log_type_label}</strong> from outside an approved location.</p>

<table style="border-collapse:collapse;width:100%;max-width:500px">
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">Employee</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{display_name} ({employee_name})</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">Type</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{log_type_label}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">Time</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{checkin_time}</td>
  </tr>
  {"<tr><td style='padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold'>Latitude</td><td style='padding:8px 12px;border:1px solid #ddd'>" + str(doc.latitude) + "</td></tr>" if doc.get("latitude") else ""}
  {"<tr><td style='padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold'>Longitude</td><td style='padding:8px 12px;border:1px solid #ddd'>" + str(doc.longitude) + "</td></tr>" if doc.get("longitude") else ""}
</table>

<p style="margin-top:16px">
  <a href="{frappe.utils.get_url()}/app/employee-checkin/{doc.name}"
     style="background:#1565C0;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold">
    View Checkin Record
  </a>
</p>

<p style="color:#888;font-size:12px;margin-top:24px">
  This notification was sent automatically by the ALKHORA ESS mobile app.<br>
  The employee confirmed they are aware they are outside an approved zone.
</p>
"""

    frappe.sendmail(
        recipients=recipients,
        subject=subject,
        message=message,
        now=True,
    )

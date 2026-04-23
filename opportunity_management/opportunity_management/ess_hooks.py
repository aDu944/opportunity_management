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

def _get_hr_manager_emails():
    """Return emails of all System Manager users (HR)."""
    rows = frappe.db.sql(
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
    return [r["email"] for r in rows]


def on_leave_application_insert(doc, method=None):
    """Email HR/managers when an employee submits a new leave request."""
    employee_name = frappe.db.get_value("Employee", doc.employee, "employee_name") or doc.employee
    recipients = _get_hr_manager_emails()
    if not recipients:
        return

    subject = f"طلب إجازة جديد — {employee_name} | New Leave Request — {employee_name}"
    link = f"{frappe.utils.get_url()}/app/leave-application/{doc.name}"

    message = f"""
<p>A new leave application has been submitted and requires your review.</p>

<table style="border-collapse:collapse;width:100%;max-width:500px">
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">Employee</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{employee_name} ({doc.employee})</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">Leave Type</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{doc.leave_type}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">From</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{doc.from_date}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">To</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{doc.to_date}</td>
  </tr>
  {"<tr><td style='padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold'>Half Day</td><td style='padding:8px 12px;border:1px solid #ddd'>Yes</td></tr>" if doc.get("half_day") else ""}
  {"<tr><td style='padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold'>Reason</td><td style='padding:8px 12px;border:1px solid #ddd'>" + (doc.description or "") + "</td></tr>" if doc.get("description") else ""}
</table>

<p style="margin-top:16px">
  <a href="{link}"
     style="background:#1565C0;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold">
    Review Leave Request
  </a>
</p>

<p style="color:#888;font-size:12px;margin-top:24px">
  This notification was sent automatically by the ALKHORA ESS system.
</p>
"""
    frappe.sendmail(recipients=recipients, subject=subject, message=message, now=True)


def on_leave_application_update(doc, method=None):
    """Notify employee (FCM + email) when their leave is approved or rejected."""
    status = doc.status
    if status not in ("Approved", "Rejected"):
        return

    employee_id = doc.employee
    employee_name = frappe.db.get_value("Employee", employee_id, "employee_name") or employee_id
    employee_user = frappe.db.get_value("Employee", employee_id, "user_id")

    if status == "Approved":
        fcm_title = "إجازتك تمت الموافقة عليها ✓"
        fcm_body = f"تمت الموافقة على طلب إجازتك من {doc.from_date} إلى {doc.to_date}."
        email_subject = f"Leave Approved — {employee_name}"
        status_html = "<span style='color:#2e7d32;font-weight:bold'>Approved ✓</span>"
    else:
        fcm_title = "طلب الإجازة مرفوض"
        fcm_body = f"تم رفض طلب إجازتك من {doc.from_date} إلى {doc.to_date}."
        email_subject = f"Leave Rejected — {employee_name}"
        status_html = "<span style='color:#c62828;font-weight:bold'>Rejected ✗</span>"

    # FCM push notification
    send_fcm_to_employee(employee_id, title=fcm_title, body=fcm_body,
                         data={"doctype": "Leave Application", "name": doc.name, "screen": "leave"})

    # Email to employee
    if not employee_user:
        return
    employee_email = frappe.db.get_value("User", employee_user, "email")
    if not employee_email:
        return

    link = f"{frappe.utils.get_url()}/app/leave-application/{doc.name}"
    message = f"""
<p>Your leave application status has been updated.</p>

<table style="border-collapse:collapse;width:100%;max-width:500px">
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">Status</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{status_html}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">Leave Type</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{doc.leave_type}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">From</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{doc.from_date}</td>
  </tr>
  <tr>
    <td style="padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold">To</td>
    <td style="padding:8px 12px;border:1px solid #ddd">{doc.to_date}</td>
  </tr>
</table>

<p style="margin-top:16px">
  <a href="{link}"
     style="background:#1565C0;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold">
    View Leave Application
  </a>
</p>

<p style="color:#888;font-size:12px;margin-top:24px">
  This notification was sent automatically by the ALKHORA ESS system.
</p>
"""
    frappe.sendmail(recipients=[employee_email], subject=email_subject, message=message, now=True)


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


def on_notification_log_insert(doc, method=None):
    """Send a push notification to the user's device when a Notification Log entry is created.

    ERPNext writes to Notification Log directly when a Notification rule fires
    (e.g. 'Journal Entry Submitted'). This hook bridges that to FCM so users
    get a push notification on their phone.
    """
    try:
        # Avoid recursion: skip when this very Log was created by our FCM helper
        if doc.get('flags', {}).get('from_fcm_send'):
            return

        user = doc.get('for_user')
        if not user or user == 'Administrator':
            return

        # Find the Employee linked to this user (must have an FCM token)
        token = frappe.db.get_value('Employee', {'user_id': user}, 'custom_fcm_token')
        if not token:
            return

        title = doc.get('subject') or 'Notification'
        body = doc.get('email_content') or ''
        # Strip HTML tags from body
        import re
        body = re.sub(r'<[^>]+>', '', body or '').strip()
        if len(body) > 200:
            body = body[:197] + '…'

        from opportunity_management.opportunity_management.fcm_utils import send_fcm
        send_fcm(
            token,
            title=title,
            body=body,
            data={
                'type': 'notification_log',
                'name': doc.name,
                'document_type': doc.get('document_type') or '',
                'document_name': doc.get('document_name') or '',
            },
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), 'on_notification_log_insert error')


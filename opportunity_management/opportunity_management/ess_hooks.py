"""
ESS (Employee Self Service) document event hooks.
"""

import frappe
from frappe.utils import format_datetime


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

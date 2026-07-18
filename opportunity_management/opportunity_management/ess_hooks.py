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
    """Email HR/managers when an employee submits a new leave request.

    Each recipient gets a *personal* copy with signed one-click Approve /
    Reject buttons plus a View button. The signed URL includes the
    recipient's email so the audit log records who acted, and the token
    expires after 14 days.
    """
    employee_name = frappe.db.get_value("Employee", doc.employee, "employee_name") or doc.employee
    recipients = _get_hr_manager_emails()
    if not recipients:
        return

    is_late_checkin = (doc.description or "").startswith("Auto-submitted: late check-in")
    late_block = ""
    if is_late_checkin and doc.get("custom_to_time"):
        checkin_t = str(doc.get("custom_to_time"))[:8]
        late_block = (
            "<tr>"
            "<td style='padding:8px 12px;border:1px solid #ddd;background:#FFF4E5;"
            "font-weight:bold;color:#E65100'>Actual Check-in Time</td>"
            "<td style='padding:8px 12px;border:1px solid #ddd;background:#FFF4E5;"
            f"font-weight:bold;font-size:15px;color:#E65100'>{checkin_t}</td>"
            "</tr>"
        )
        subject = f"تأخير في الحضور — {employee_name} ({checkin_t}) | Late Check-in — {employee_name} ({checkin_t})"
    else:
        subject = f"طلب إجازة جديد — {employee_name} | New Leave Request — {employee_name}"

    view_link = f"{frappe.utils.get_url()}/app/leave-application/{doc.name}"

    from datetime import timedelta
    exp = int((frappe.utils.now_datetime() + timedelta(days=14)).timestamp())

    for recipient in recipients:
        if is_late_checkin:
            # Late check-ins are auto-processed against the balance — no HR
            # decision needed. Show only the View button for record-keeping.
            action_buttons = (
                "<p style='margin-top:20px'>"
                f"  <a href='{view_link}' "
                "     style='background:#1565C0;color:white;padding:11px 22px;"
                "     border-radius:6px;text-decoration:none;font-weight:bold;"
                "     display:inline-block'>View Details</a>"
                "</p>"
            )
        else:
            approve_url = _leave_action_url(doc.name, "approve", recipient, exp)
            reject_url = _leave_action_url(doc.name, "reject", recipient, exp)
            action_buttons = (
                "<p style='margin-top:20px'>"
                f"  <a href='{approve_url}' "
                "     style='background:#2E7D32;color:white;padding:11px 22px;"
                "     border-radius:6px;text-decoration:none;font-weight:bold;"
                "     margin-right:8px;display:inline-block'>✓ Approve</a>"
                f"  <a href='{reject_url}' "
                "     style='background:#C62828;color:white;padding:11px 22px;"
                "     border-radius:6px;text-decoration:none;font-weight:bold;"
                "     margin-right:8px;display:inline-block'>✗ Reject</a>"
                f"  <a href='{view_link}' "
                "     style='background:#1565C0;color:white;padding:11px 22px;"
                "     border-radius:6px;text-decoration:none;font-weight:bold;"
                "     display:inline-block'>View Details</a>"
                "</p>"
            )

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
  {late_block}
  {"<tr><td style='padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold'>Half Day</td><td style='padding:8px 12px;border:1px solid #ddd'>Yes</td></tr>" if doc.get("half_day") else ""}
  {"<tr><td style='padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold'>Reason</td><td style='padding:8px 12px;border:1px solid #ddd'>" + (doc.description or "") + "</td></tr>" if doc.get("description") else ""}
</table>

{action_buttons}

<p style="color:#888;font-size:12px;margin-top:24px">
  {"This notification was sent automatically by the ALKHORA ESS system." if is_late_checkin else "Approve / Reject buttons work in one click and expire in 14 days.<br>This notification was sent automatically by the ALKHORA ESS system."}
</p>
"""
        frappe.sendmail(recipients=[recipient], subject=subject, message=message, now=True)


def _leave_action_url(leave_name, action, user_email, exp_ts):
    """Build a signed one-click approve/reject URL for a leave application."""
    from urllib.parse import quote
    token = _sign_leave_action(leave_name, action, user_email, exp_ts)
    base = frappe.utils.get_url()
    return (
        f"{base}/api/method/opportunity_management.opportunity_management.api.approve_leave_via_email"
        f"?name={quote(leave_name)}&action={action}&user={quote(user_email)}"
        f"&exp={exp_ts}&token={token}"
    )


def _sign_leave_action(leave_name, action, user_email, exp_ts):
    """HMAC-SHA256 the (leave, action, user, expiry) tuple with the site secret."""
    import hmac, hashlib
    secret = str(
        frappe.conf.get("encryption_key")
        or frappe.local.conf.get("secret", "")
        or frappe.local.site
    ).encode()
    msg = f"{leave_name}|{action}|{user_email}|{exp_ts}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


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
    """Notify employee when their payslip is ready (gated by config)."""
    if not _ess_setting_enabled("enable_payslip_notification", default=True):
        return

    employee_id = doc.employee

    title = "قسيمة الراتب جاهزة 💰"
    body = f"قسيمة راتبك لشهر {doc.month_name or doc.start_date} أصبحت متاحة."

    send_fcm_to_employee(employee_id, title=title, body=body, data={"doctype": "Salary Slip", "name": doc.name})


def _ess_setting_enabled(key: str, default: bool = True) -> bool:
    """Read a Check field from ESS Mobile Settings; defaults to [default] on
    any error (e.g. doctype missing or single not yet created)."""
    try:
        v = frappe.db.get_single_value("ESS Mobile Settings", key)
        return bool(int(v)) if v not in (None, "") else default
    except Exception:
        return default


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
    if not _ess_setting_enabled("enable_announcement_push", default=True):
        return
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


def before_checkin_insert(doc, method=None):
    """Reject an Employee Checkin whose time falls outside the configured
    check-in window. Only IN records are guarded — OUT is always allowed.

    Bypass: Administrator, System Manager, HR Manager, and HR User can still
    create manual corrections (e.g. fixing a forgotten punch).
    """
    if (doc.log_type or "").upper() != "IN":
        return

    # Allow back-office roles to insert manual corrections.
    user_roles = set(frappe.get_roles(frappe.session.user) or [])
    bypass_roles = {"Administrator", "System Manager", "HR Manager", "HR User"}
    if frappe.session.user == "Administrator" or (user_roles & bypass_roles):
        return

    try:
        settings = frappe.get_single("ESS Mobile Settings")
    except Exception:
        return  # Doctype missing → don't block.

    start_h = int(settings.get("checkin_window_start_hour") or 0)
    end_h = int(settings.get("checkin_window_end_hour") or 0)
    if start_h <= 0 or end_h <= 0 or end_h <= start_h:
        return  # Misconfigured → don't block.

    # Working-days check: silently allow on non-working days so this hook
    # never traps an HR-initiated retroactive entry on a holiday.
    from frappe.utils import get_datetime
    t = get_datetime(doc.time)
    if not t:
        return
    h = t.hour
    if start_h <= h < end_h:
        return

    # Out-of-window → reject.
    def _fmt(h_):
        ampm = "AM" if h_ < 12 else "PM"
        h12 = h_ % 12 or 12
        return f"{h12}:00 {ampm}"

    frappe.throw(
        f"Check-in is only allowed between {_fmt(start_h)} and {_fmt(end_h)}. "
        f"Your time: {t.strftime('%H:%M')}.",
        title="Outside Check-in Window",
    )


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
  {(
    "<tr><td style='padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold'>Location</td>"
    "<td style='padding:8px 12px;border:1px solid #ddd'>"
    f"<a href='https://www.google.com/maps?q={doc.latitude},{doc.longitude}' "
    "style='color:#1565C0;text-decoration:none;font-weight:bold'>"
    f"View on Map ({doc.latitude:.6f}, {doc.longitude:.6f})</a>"
    "</td></tr>"
  ) if doc.get("latitude") and doc.get("longitude") else ""}
  {"<tr><td style='padding:8px 12px;border:1px solid #ddd;background:#f5f5f5;font-weight:bold;vertical-align:top'>Employee's Reason</td><td style='padding:8px 12px;border:1px solid #ddd;white-space:pre-wrap'>" + frappe.utils.escape_html(str(doc.get('custom_outside_zone_reason') or '')) + "</td></tr>" if doc.get("custom_outside_zone_reason") else ""}
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
        # Avoid recursion: skip when this Log was created by our FCM helper.
        # `doc.flags` is an attribute on the Document, NOT a regular field —
        # `doc.get('flags')` returns None on a Document, so we must read the
        # attribute directly.
        if getattr(getattr(doc, 'flags', None), 'from_fcm_send', False):
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


# ---------------------------------------------------------------------------
# Payment notifications — push to the affected Employee whenever a Journal
# Entry or Payment Entry references them as the party.
# ---------------------------------------------------------------------------

def _fmt_money(amount, currency):
    try:
        a = float(amount or 0)
    except (TypeError, ValueError):
        a = 0.0
    cur = (currency or "").strip()
    return f"{a:,.2f} {cur}".strip()


def _notify_employee_payment(employee_id, amount, currency, doc_type, doc_name, kind):
    """Send a single FCM push to one employee about a money movement.

    kind: 'paid' → company paid the employee (debit to payable)
          'owed' → company recognized a new amount owed to the employee (credit)
    """
    if not employee_id:
        return
    money = _fmt_money(amount, currency)
    if kind == "paid":
        title = "💸 تم تحويل مبلغ لحسابك • You got paid"
        body = money
        data_type = "payment"
    else:
        title = "💰 تم اضافة مصروف جديد لحسابك • Expenses added to your account"
        body = money
        data_type = "payable_registered"
    try:
        send_fcm_to_employee(
            employee_id,
            title=title,
            body=body,
            data={
                "type": data_type,
                "doctype": doc_type,
                "name": doc_name,
            },
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "notify_employee_payment")


def on_journal_entry_submit(doc, method=None):
    """Fire one push per unique Employee party referenced in the JE rows.

    Distinguishes between a payment (net DEBIT > 0 on the party row = company
    paid the employee, liability settled) and an accrual (net CREDIT > 0 =
    company now owes the employee more).
    """
    if not doc or not doc.get("accounts"):
        return
    # System Manager override — silent submit.
    if doc.get("custom_skip_employee_notification"):
        return
    # totals[employee] = (paid_amount, owed_amount, currency)
    totals = {}
    for row in doc.accounts:
        if (row.get("party_type") or "") != "Employee":
            continue
        emp = row.get("party")
        if not emp:
            continue
        credit = float(row.get("credit_in_account_currency") or row.get("credit") or 0)
        debit = float(row.get("debit_in_account_currency") or row.get("debit") or 0)
        currency = row.get("account_currency") or ""
        prev_paid, prev_owed, prev_cur = totals.get(emp, (0.0, 0.0, currency))
        totals[emp] = (
            prev_paid + max(debit - credit, 0),
            prev_owed + max(credit - debit, 0),
            prev_cur or currency,
        )

    for emp, (paid, owed, currency) in totals.items():
        if paid > 0:
            _notify_employee_payment(emp, paid, currency, "Journal Entry", doc.name, "paid")
        elif owed > 0:
            _notify_employee_payment(emp, owed, currency, "Journal Entry", doc.name, "owed")


def on_payment_entry_submit(doc, method=None):
    """Fire a push when a Payment Entry pays or accrues to an Employee.

    payment_type='Pay'     → company paying the employee (paid)
    payment_type='Receive' → employee paying back to the company (owed-back)
    """
    if not doc:
        return
    if (doc.get("party_type") or "") != "Employee":
        return
    # System Manager override — silent submit.
    if doc.get("custom_skip_employee_notification"):
        return
    emp = doc.get("party")
    if not emp:
        return
    amount = doc.get("paid_amount") or doc.get("base_paid_amount") or 0
    currency = doc.get("paid_to_account_currency") or doc.get("paid_from_account_currency") or ""
    kind = "paid" if (doc.get("payment_type") or "Pay") == "Pay" else "owed"
    _notify_employee_payment(emp, amount, currency, "Payment Entry", doc.name, kind)


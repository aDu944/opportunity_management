"""
Utility functions for notifications
Helps determine who should receive opportunity notifications
"""

import frappe
from frappe import _


def get_department_managers(user_email):
    """
    Get all managers/system managers from the department of the given user.

    Args:
        user_email: Email of the user whose department we want to check

    Returns:
        List of user emails of managers/system managers in that department
    """
    if not user_email:
        return []

    try:
        # Get the employee record for this user
        employee = frappe.db.get_value(
            "Employee",
            {"user_id": user_email, "status": "Active"},
            ["name", "department"],
            as_dict=True
        )

        if not employee or not employee.department:
            frappe.log_error(
                f"No active employee or department found for user: {user_email}",
                "Get Department Managers"
            )
            return []

        department = employee.department

        # Get users with Management role in the same department
        managers = []
        management_role = frappe.db.sql("""
            SELECT DISTINCT e.user_id
            FROM `tabEmployee` e
            INNER JOIN `tabHas Role` hr ON hr.parent = e.user_id
            WHERE e.department = %(department)s
                AND e.status = 'Active'
                AND e.user_id IS NOT NULL
                AND e.user_id != ''
                AND hr.role = 'Management'
                AND hr.parenttype = 'User'
        """, {"department": department}, as_dict=True)

        for mgr in management_role:
            if mgr.user_id and mgr.user_id not in managers:
                managers.append(mgr.user_id)

        frappe.logger().info(
            f"Found {len(managers)} managers for department '{department}': {managers}"
        )

        return managers

    except Exception as e:
        frappe.log_error(
            f"Error getting department managers for {user_email}: {str(e)}",
            "Get Department Managers Error"
        )
        return []


def get_opportunity_notification_recipients(opportunity_name):
    """
    Get all recipients for opportunity notifications:
    1. Responsible engineers assigned to the opportunity
    2. Managers/System Managers from the department of the user who created/assigned

    Args:
        opportunity_name: Name of the Opportunity document

    Returns:
        List of unique user emails who should receive notifications
    """
    recipients = set()

    try:
        # Get the opportunity document
        opportunity = frappe.get_doc("Opportunity", opportunity_name)

        # 1. Get responsible parties/users
        for party in _get_opportunity_party_rows(opportunity):
            info = _get_responsible_party_info(party)
            if info.get("user_id"):
                recipients.add(info.get("user_id"))
            elif info.get("email"):
                recipients.add(info.get("email"))

        # 2. Get managers from the department of the user who owns/modified the opportunity
        # Try owner first (creator), then modified_by (last person who edited)
        assigner_email = opportunity.owner or opportunity.modified_by

        if assigner_email:
            dept_managers = get_department_managers(assigner_email)
            for mgr in dept_managers:
                recipients.add(mgr)

        frappe.logger().info(
            f"Opportunity {opportunity_name} recipients: {list(recipients)}"
        )

        return list(recipients)

    except Exception as e:
        frappe.log_error(
            f"Error getting notification recipients for {opportunity_name}: {str(e)}",
            "Get Notification Recipients Error"
        )
        return []


def get_opportunity_recipients_for_notification(doc, method=None):
    """
    Hook function to be called by notifications to get custom recipients.

    This can be used as a Server Script or in notification conditions.

    Args:
        doc: The document (Opportunity)
        method: The method name (optional)

    Returns:
        List of user emails
    """
    return get_opportunity_notification_recipients(doc.name)


def _get_responsible_party_info(party_name):
    """Resolve a Responsible Party/Employee/Shareholder to user_id/email."""
    info = {"user_id": None, "email": None}

    if not party_name:
        return info

    # Preferred: Responsible Party doctype (standalone)
    if frappe.db.exists("DocType", "Responsible Party") and frappe.db.exists("Responsible Party", party_name):
        party = frappe.get_doc("Responsible Party", party_name)

        user_id = getattr(party, "user_id", None)
        employee = getattr(party, "employee", None)
        shareholder = getattr(party, "shareholder", None)
        email = getattr(party, "email", None)

        if user_id:
            info["user_id"] = user_id
        if email:
            info["email"] = email

        if not info["user_id"] and employee:
            emp = frappe.db.get_value("Employee", employee, ["user_id", "prefered_email", "company_email", "personal_email"], as_dict=True)
            if emp:
                info["user_id"] = emp.user_id
                info["email"] = info["email"] or emp.prefered_email or emp.company_email or emp.personal_email

        if shareholder and not info["email"]:
            contact = frappe.db.get_value(
                "Dynamic Link",
                {"link_doctype": "Shareholder", "link_name": shareholder, "parenttype": "Contact"},
                "parent"
            )
            if contact:
                info["email"] = frappe.db.get_value("Contact", contact, "email_id")

        if info["user_id"] and not info["email"]:
            info["email"] = frappe.db.get_value("User", info["user_id"], "email")

        if not info["user_id"] and info["email"]:
            user_from_email = frappe.db.get_value("User", {"email": info["email"]}, "name")
            if user_from_email:
                info["user_id"] = user_from_email

        return info

    # Fallback: Employee ID directly
    if frappe.db.exists("Employee", party_name):
        emp = frappe.db.get_value("Employee", party_name, ["user_id", "prefered_email", "company_email", "personal_email"], as_dict=True)
        if emp:
            info["user_id"] = emp.user_id
            info["email"] = emp.prefered_email or emp.company_email or emp.personal_email
        return info

    # Fallback: Shareholder ID directly
    if frappe.db.exists("Shareholder", party_name):
        contact = frappe.db.get_value(
            "Dynamic Link",
            {"link_doctype": "Shareholder", "link_name": party_name, "parenttype": "Contact"},
            "parent"
        )
        if contact:
            info["email"] = frappe.db.get_value("Contact", contact, "email_id")
        return info

    # Legacy: Responsible Engineer as child table entry
    if frappe.db.exists("Responsible Engineer", party_name):
        engineer = frappe.get_doc("Responsible Engineer", party_name)
        employee = getattr(engineer, "employee", None)
        if employee:
            emp = frappe.db.get_value("Employee", employee, ["user_id", "prefered_email", "company_email", "personal_email"], as_dict=True)
            if emp:
                info["user_id"] = emp.user_id
                info["email"] = emp.prefered_email or emp.company_email or emp.personal_email
        return info

    return info


def _get_user_from_responsible_engineer(engineer_name):
    """Resolve to user_id for assignment logic."""
    return _get_responsible_party_info(engineer_name).get("user_id")


def _get_opportunity_party_rows(doc):
    """Return list of party identifiers from Responsible Party only."""
    parties = []
    if not doc:
        return parties

    if doc.get("custom_responsible_party"):
        for row in doc.custom_responsible_party:
            party = getattr(row, "responsible_party", None) or row.get("responsible_party")
            if party:
                parties.append(party)

    return parties


def get_opportunity_assigned_users(doc):
    """Return all assigned users for an Opportunity."""
    assigned_users = set()

    if not doc:
        return assigned_users

    for party in _get_opportunity_party_rows(doc):
        user_id = _get_user_from_responsible_engineer(party)
        if user_id:
            assigned_users.add(user_id)

    return assigned_users


def get_opportunity_assignee_recipients_for_notification(doc, method=None):
    """
    Hook function for Opportunity notifications (assignees + their managers).

    Recipients:
    1. All assigned users (custom_responsible_party or custom_resp_eng)
    2. Department managers/system managers of each assigned user
    3. Opportunity creator (owner)

    Args:
        doc: The Opportunity document
        method: The method name (optional)

    Returns:
        List of user emails
    """
    recipients = set()
    assigned_users = get_opportunity_assigned_users(doc)
    assigned_emails = set()

    if not doc:
        return []

    # Add assigned users and their department managers
    for user_id in assigned_users:
        recipients.add(user_id)
        dept_managers = get_department_managers(user_id)
        for mgr in dept_managers:
            recipients.add(mgr)

    # Add assignees with no user_id (e.g., shareholders)
    for party in _get_opportunity_party_rows(doc):
        info = _get_responsible_party_info(party)
        if info.get("email") and not info.get("user_id"):
            assigned_emails.add(info.get("email"))

    # Include the creator (assigner) explicitly
    if doc.owner:
        recipients.add(doc.owner)
        # Include owner's department managers as well
        owner_managers = get_department_managers(doc.owner)
        for mgr in owner_managers:
            recipients.add(mgr)

    for email in assigned_emails:
        recipients.add(email)

    recipients_list = list(recipients)
    frappe.logger().info(
        f"Opportunity {doc.name} notification recipients (assignees+managers): {recipients_list}"
    )
    return recipients_list


def set_opportunity_notification_recipients(doc, method=None):
    """
    Populate a custom field with notification recipients for ERPNext v15.

    Requires a custom field on Opportunity, e.g.:
    - fieldname: custom_notification_recipients
    - fieldtype: Small Text

    Stores a comma-separated list of emails for Notification "Receiver By Document Field".
    """
    if not doc:
        return

    fieldname = "custom_notification_recipients"

    # Only attempt if the field exists on the doc
    if not hasattr(doc, fieldname):
        return

    recipients = get_opportunity_assignee_recipients_for_notification(doc, method)
    doc.set(fieldname, ", ".join(recipients))


def send_closing_date_extended_notification(doc, method=None):
    """
    Send a dedicated notification when the Opportunity closing date is extended.

    Sends only when expected_closing increases compared to the previous value.
    """
    if not doc or not getattr(doc, "expected_closing", None):
        return

    try:
        # If user has set up a Notification, avoid sending duplicate emails
        if frappe.db.exists("Notification", {"document_type": "Opportunity", "enabled": 1, "name": "Opportunity Closing Date Extended"}):
            return

        if frappe.db.exists("Notification", {"document_type": "Opportunity", "enabled": 1, "email_template": "Opportunity Closing Date Extended"}):
            return

        previous = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
        if not previous or not getattr(previous, "expected_closing", None):
            return

        old_date = frappe.utils.getdate(previous.expected_closing)
        new_date = frappe.utils.getdate(doc.expected_closing)

        if not old_date or not new_date or new_date <= old_date:
            return

        recipients = set()
        custom_recipients = getattr(doc, "custom_notification_recipients", None)
        if custom_recipients:
            recipients.update([r.strip() for r in custom_recipients.split(",") if r.strip()])

        if not recipients:
            recipients.update(get_opportunity_assignee_recipients_for_notification(doc))

        # Ensure department managers for responsible parties and owner are included
        for party in _get_opportunity_party_rows(doc):
            info = _get_responsible_party_info(party)
            user_id = info.get("user_id")
            if user_id:
                recipients.update(get_department_managers(user_id))

        if doc.owner:
            recipients.update(get_department_managers(doc.owner))

        recipients = [r for r in recipients if r]
        if not recipients:
            return

        template_name = "Opportunity Closing Date Extended"
        if not frappe.db.exists("Email Template", template_name):
            frappe.log_error(
                f"Email Template '{template_name}' not found. Skipping plain email.",
                "Closing Date Extended Notification Error"
            )
            return

        template = frappe.get_doc("Email Template", template_name)
        message_html = template.response_html or template.response or ""
        subject = frappe.render_template(template.subject or "", {"doc": doc})
        message = frappe.render_template(message_html, {"doc": doc})

        frappe.sendmail(
            recipients=list(recipients),
            subject=subject,
            message=message,
            now=True
        )
    except Exception as e:
        frappe.log_error(
            f"Error sending closing date extended notification for {getattr(doc, 'name', '')}: {str(e)}",
            "Closing Date Extended Notification Error"
        )



def log_opportunity_notification_from_email_queue(doc, method=None):
    """Log notifications sent for Opportunities via Email Queue."""
    if not doc:
        return

    reference_doctype = getattr(doc, "reference_doctype", None)
    reference_name = getattr(doc, "reference_name", None)

    if reference_doctype != "Opportunity" or not reference_name:
        return

    recipients = getattr(doc, "recipients", None) or getattr(doc, "recipient", None) or ""
    subject = getattr(doc, "subject", None) or ""
    status = getattr(doc, "status", None) or "Queued"
    sent_at = getattr(doc, "send_after", None) or getattr(doc, "creation", None)
    message_id = getattr(doc, "message_id", None) or ""

    recipients = _normalize_recipients(recipients)
    subject = _truncate_value(subject, 140)
    status = _normalize_email_status(status)

    try:
        log = frappe.get_doc({
            "doctype": "Opportunity Notification Log",
            "opportunity": reference_name,
            "recipients": recipients,
            "subject": subject,
            "status": status,
            "email_queue": doc.name,
            "sent_at": sent_at,
            "message_id": message_id,
        })
        log.insert(ignore_permissions=True)

        update_opportunity_last_notification_fields(
            reference_name,
            recipients,
            subject,
            status,
            sent_at
        )
    except Exception as e:
        frappe.log_error(
            message=f"Error logging notification for Opportunity {reference_name}: {str(e)}",
            title="Opportunity Notification Log Error"
        )


def update_opportunity_notification_log_status(doc, method=None):
    """Update notification log status when Email Queue status changes."""
    if not doc:
        return

    reference_doctype = getattr(doc, "reference_doctype", None)
    reference_name = getattr(doc, "reference_name", None)
    if reference_doctype != "Opportunity" or not reference_name:
        return

    status = _normalize_email_status(getattr(doc, "status", None) or "Queued")
    try:
        frappe.db.set_value(
            "Opportunity Notification Log",
            {"email_queue": doc.name},
            "status",
            status,
            update_modified=False
        )
        update_opportunity_last_notification_fields(
            reference_name,
            _normalize_recipients(getattr(doc, "recipients", None) or getattr(doc, "recipient", None) or ""),
            _truncate_value(getattr(doc, "subject", None) or "", 140),
            status,
            getattr(doc, "send_after", None) or getattr(doc, "modified", None)
        )
    except Exception as e:
        frappe.log_error(
            message=f"Error updating notification log status for {doc.name}: {str(e)}",
            title="Opportunity Notification Log Status Error"
        )


def update_opportunity_last_notification_fields(opportunity_name, recipients, subject, status, sent_at):
    """Update last notification fields on Opportunity if they exist."""
    if not opportunity_name:
        return

    fields = {}
    meta = frappe.get_meta("Opportunity")

    if meta.has_field("custom_last_notification_sent"):
        fields["custom_last_notification_sent"] = sent_at
    if meta.has_field("custom_last_notification_recipients"):
        field = meta.get_field("custom_last_notification_recipients")
        fields["custom_last_notification_recipients"] = _truncate_for_field(_normalize_recipients(recipients), field)
    if meta.has_field("custom_last_notification_subject"):
        field = meta.get_field("custom_last_notification_subject")
        fields["custom_last_notification_subject"] = _truncate_for_field(subject, field)
    if meta.has_field("custom_last_notification_status"):
        field = meta.get_field("custom_last_notification_status")
        fields["custom_last_notification_status"] = _truncate_for_field(status, field)

    if fields:
        frappe.db.set_value(
            "Opportunity",
            opportunity_name,
            fields,
            update_modified=False
        )


def _normalize_email_status(status):
    if not status:
        return "Queued"

    normalized = str(status).strip()
    mapping = {
        "Not Sent": "Queued",
        "Open": "Queued",
        "Queued": "Queued",
        "Sent": "Sent",
        "Delivered": "Sent",
        "Failed": "Failed",
        "Error": "Failed"
    }
    return mapping.get(normalized, "Queued")


def _normalize_recipients(recipients):
    if recipients is None:
        return ""
    if isinstance(recipients, (list, tuple, set)):
        return ", ".join([str(r) for r in recipients if r])
    return str(recipients)


def _truncate_value(value, limit):
    if value is None:
        return ""
    text = str(value)
    if limit and len(text) > limit:
        return text[:limit]
    return text


def _truncate_for_field(value, field):
    if value is None:
        return ""
    text = str(value)

    if not field:
        return text

    if field.fieldtype == "Data":
        return _truncate_value(text, 140)
    if field.fieldtype in ("Small Text", "Text"):
        return _truncate_value(text, 1000)
    if field.fieldtype == "Select":
        return _truncate_value(text, 140)
    return text

@frappe.whitelist()
def notify_new_message(
    opportunity_name,
    tender_no,
    tender_title,
    tender_url,
    closing_date_text,
    erpnext_url,
    buyer_name,
    messages_json,
):
    """Send the 'new message on tender' email to the opportunity's responsible
    parties + their department managers. `messages_json` is a JSON string of a
    list of dicts: [{msg_id, subject, from_org, from_who, sent, body_preview}, ...].
    Called from Tender Hub when its Ariba/Maximo runner detects new messages.
    """
    import json
    from frappe.utils import escape_html

    if isinstance(messages_json, str):
        try:
            messages = json.loads(messages_json)
        except Exception:
            messages = []
    else:
        messages = messages_json or []

    if not messages:
        return {"ok": False, "reason": "no messages"}

    # Base set: responsible parties + dept managers (per existing helper).
    recipients = list(get_opportunity_notification_recipients(opportunity_name) or [])
    # Plus: every enabled User with the O&G Manager role (Tender Hub policy:
    # all O&G managers should be aware of every message on a tender, regardless
    # of doc.owner — particularly important for opps created via the API user).
    try:
        og_managers = frappe.db.sql_list('''
            SELECT DISTINCT u.name FROM `tabUser` u
            INNER JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
            WHERE u.enabled = 1 AND hr.role = 'O&G Manager'
              AND u.name NOT IN ('Guest', 'Administrator')
        ''')
        for m in (og_managers or []):
            if m and m not in recipients:
                recipients.append(m)
    except Exception as e:
        frappe.logger().warning(f'notify_new_message O&G role lookup failed: {e}')
    recipients = [r for r in (recipients or []) if r]
    if not recipients:
        frappe.logger().warning(
            f"notify_new_message {opportunity_name}: no recipients resolved"
        )
        return {"ok": False, "reason": "no recipients"}

    # Build subject — single message uses its subject; multi-message digest
    # falls back to a count summary.
    if len(messages) == 1:
        subj = f"New message on tender {tender_no} — {messages[0].get('subject') or tender_title}"
    else:
        subj = f"{len(messages)} new messages on tender {tender_no} — {tender_title}"

    # Build the message-card HTML for each new message.
    msg_cards = []
    for m in messages:
        body_prev = escape_html((m.get("body_preview") or "")[:280])
        if not body_prev:
            body_prev = '<span style="color:#9ca3af;">[no preview available — see full thread on Tender Hub]</span>'
        else:
            body_prev = body_prev + ' <span style="color:#9ca3af;">[preview, see full thread on Tender Hub]</span>'
        msg_cards.append(f"""
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="width:100%;font-size:13px;color:#374151;margin-top:14px;">
  <tr><td style="padding:2px 12px 2px 0;color:#6b7280;width:84px;">Subject</td><td style="font-weight:600;">{escape_html(m.get('subject') or '(no subject)')}</td></tr>
  <tr><td style="padding:2px 12px 2px 0;color:#6b7280;">From</td><td>{escape_html(m.get('from_who') or '')} {f"&middot; {escape_html(m.get('from_org'))}" if m.get('from_org') else ''}</td></tr>
  <tr><td style="padding:2px 12px 2px 0;color:#6b7280;">Sent</td><td>{escape_html(m.get('sent') or '')}</td></tr>
  <tr><td style="padding:2px 12px 2px 0;color:#6b7280;">ID</td><td style="font-family:ui-monospace,Menlo,monospace;font-size:12px;">{escape_html(m.get('msg_id') or '')}</td></tr>
</table>
<div style="margin-top:8px;padding:12px 14px;background:#f9fafb;border-left:3px solid #0070f2;border-radius:4px;font-size:13px;color:#374151;line-height:1.55;">{body_prev}</div>
""")

    erp_link = (
        f'<tr><td style="padding:2px 12px 2px 0;color:#6b7280;">ERPNext</td>'
        f'<td><a style="color:#0070f2;text-decoration:none;" href="{escape_html(erpnext_url)}">{escape_html(opportunity_name)}</a></td></tr>'
    ) if erpnext_url else ""

    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#111827;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f3f4f6;padding:24px 0;">
  <tr><td align="center"><table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="background:#ffffff;border-radius:10px;overflow:hidden;">
    <tr><td style="background:#0070f2;padding:16px 24px;color:#ffffff;font-size:14px;font-weight:600;letter-spacing:0.5px;">📬 NEW MESSAGE — TENDER HUB</td></tr>
    <tr><td style="padding:24px 24px 8px;">
      <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Tender</div>
      <div style="font-size:18px;font-weight:600;color:#111827;line-height:1.35;">{escape_html(tender_title or '')}</div>
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin-top:10px;font-size:13px;color:#374151;">
        <tr><td style="padding:2px 12px 2px 0;color:#6b7280;">No.</td><td style="font-family:ui-monospace,Menlo,monospace;">{escape_html(tender_no or '')}</td></tr>
        <tr><td style="padding:2px 12px 2px 0;color:#6b7280;">Buyer</td><td>{escape_html(buyer_name or '')}</td></tr>
        <tr><td style="padding:2px 12px 2px 0;color:#6b7280;">Closes</td><td>{escape_html(closing_date_text or '')}</td></tr>
        {erp_link}
      </table>
    </td></tr>
    <tr><td style="padding:0 24px;"><hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0 0;"></td></tr>
    <tr><td style="padding:16px 24px 8px;">
      <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">{('Message' if len(messages) == 1 else f'{len(messages)} new messages')}</div>
      {''.join(msg_cards)}
    </td></tr>
    <tr><td align="center" style="padding:20px 24px 28px;">
      <a href="{escape_html(tender_url)}" style="display:inline-block;padding:10px 22px;background:#0070f2;color:#ffffff;text-decoration:none;font-weight:600;font-size:14px;border-radius:6px;">View thread on Tender Hub →</a>
    </td></tr>
    <tr><td style="padding:14px 24px 18px;background:#f9fafb;font-size:12px;color:#6b7280;line-height:1.5;border-top:1px solid #e5e7eb;">
      You're receiving this because you're listed as <strong>Responsible Party</strong> on the linked ERPNext Opportunity, or as a <strong>Department Manager</strong> in Opportunity Management.<br>
      <span style="color:#9ca3af;">— ALKHORA Tender Hub · sent from <a href="https://tender.alkhora.com" style="color:#6b7280;">tender.alkhora.com</a></span>
    </td></tr>
  </table></td></tr>
</table>
</body></html>"""

    try:
        frappe.sendmail(
            recipients=recipients,
            subject=subj,
            message=html,
            reference_doctype="Opportunity",
            reference_name=opportunity_name,
            now=False,
        )
        return {"ok": True, "recipients": recipients, "messages": len(messages)}
    except Exception as e:
        frappe.log_error(
            f"notify_new_message {opportunity_name} failed: {e}",
            "Tender Hub New Message Notify",
        )
        return {"ok": False, "error": str(e)[:300]}


@frappe.whitelist()
def notify_new_tenders(
    role_name,
    source_label,
    brand_color,
    header_emoji,
    audience_explainer,
    dashboard_url,
    tenders_json,
):
    """Send a 'new tender(s) available' alert to every enabled User who has
    the given role. Used by Tender Hub to fan out alerts to O&G Managers
    (PetroChina/Ariba publish) or System Managers (ITP-university publish).

    Args:
      role_name: 'O&G Manager' or 'System Manager' (or any role).
      source_label: shown in the header (e.g. 'PETROCHINA WQ1').
      brand_color: hex string, e.g. '#b8362e'.
      header_emoji: '🆕' or '🎓'.
      audience_explainer: footer line — 'you have the X role in ERPNext'.
      dashboard_url: where the bottom CTA jumps to.
      tenders_json: JSON string, list of dicts: {number, title, buyer,
                    parent, published, closes, type, tender_url, source_url,
                    pdf_url}. parent/published/type/source_url/pdf_url are
                    all optional.
    """
    import json
    from frappe.utils import escape_html

    if isinstance(tenders_json, str):
        try:
            tenders = json.loads(tenders_json)
        except Exception:
            tenders = []
    else:
        tenders = tenders_json or []
    if not tenders:
        return {"ok": False, "reason": "no tenders"}

    # Recipient query: enabled users with this role.
    recipients = frappe.db.sql_list("""
        SELECT DISTINCT u.name
        FROM `tabUser` u
        INNER JOIN `tabHas Role` hr
                ON hr.parent = u.name AND hr.parenttype = 'User'
        WHERE u.enabled = 1
          AND hr.role = %(role)s
          AND u.name NOT IN ('Guest', 'Administrator')
    """, {"role": role_name})
    recipients = [r for r in (recipients or []) if r]
    if not recipients:
        frappe.logger().warning(
            f"notify_new_tenders: no enabled users with role {role_name!r}"
        )
        return {"ok": False, "reason": f"no users with role {role_name}"}

    color = brand_color or "#0070f2"
    is_digest = len(tenders) >= 2

    if is_digest:
        subj = f"{header_emoji} {len(tenders)} new tenders from {source_label}"
    else:
        t = tenders[0]
        subj = f"{header_emoji} New tender — {t.get('number') or ''} — {(t.get('title') or '')[:80]}"

    def _render_single(t):
        rows = []
        rows.append(f'<tr><td style="padding:2px 12px 2px 0;color:#6b7280;width:84px;">No.</td><td style="font-family:ui-monospace,Menlo,monospace;">{escape_html(t.get("number") or "")}</td></tr>')
        buyer = (t.get("buyer") or "")
        if t.get("parent"):
            buyer += f' · {t.get("parent")}'
        rows.append(f'<tr><td style="padding:2px 12px 2px 0;color:#6b7280;">Buyer</td><td>{escape_html(buyer)}</td></tr>')
        if t.get("published"):
            rows.append(f'<tr><td style="padding:2px 12px 2px 0;color:#6b7280;">Published</td><td>{escape_html(t.get("published") or "")}</td></tr>')
        if t.get("closes"):
            rows.append(f'<tr><td style="padding:2px 12px 2px 0;color:#6b7280;">Closes</td><td>{escape_html(t.get("closes") or "")}</td></tr>')
        if t.get("type"):
            rows.append(f'<tr><td style="padding:2px 12px 2px 0;color:#6b7280;">Type</td><td>{escape_html(t.get("type") or "")}</td></tr>')
        cta = f'<a href="{escape_html(t.get("tender_url") or dashboard_url)}" style="display:inline-block;padding:10px 22px;background:{color};color:#ffffff;text-decoration:none;font-weight:600;font-size:14px;border-radius:6px;">View on Tender Hub →</a>'
        if t.get("source_url"):
            cta += f'<a href="{escape_html(t.get("source_url"))}" style="display:inline-block;margin-left:8px;padding:10px 18px;border:1px solid #d1d5db;color:#374151;text-decoration:none;font-weight:500;font-size:14px;border-radius:6px;">Open in source ↗</a>'
        if t.get("pdf_url"):
            cta += f'<a href="{escape_html(t.get("pdf_url"))}" style="display:inline-block;margin-left:8px;padding:10px 18px;border:1px solid #d1d5db;color:#374151;text-decoration:none;font-weight:500;font-size:14px;border-radius:6px;">📄 Download PDF</a>'
        return f"""
<tr><td style="padding:24px 24px 8px;">
  <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Tender</div>
  <div style="font-size:18px;font-weight:600;color:#111827;line-height:1.35;">{escape_html(t.get('title') or '')}</div>
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin-top:10px;font-size:13px;color:#374151;">
    {''.join(rows)}
  </table>
</td></tr>
<tr><td align="center" style="padding:20px 24px 28px;">{cta}</td></tr>"""

    def _render_card(t):
        sub = (t.get("buyer") or "")
        if t.get("parent"):
            sub = f'{escape_html(t.get("parent"))} &nbsp;·&nbsp; {escape_html(t.get("buyer") or "")}'
        else:
            sub = escape_html(sub)
        rtl = ' dir="rtl"' if any(c in (t.get("title") or "") for c in "آأإابتثجحخدذرزسشصضطظعغفقكلمنهويةى") else ""
        meta = f'{escape_html(t.get("number") or "")}' + (f' &nbsp;·&nbsp; closes {escape_html(t.get("closes"))}' if t.get("closes") else '')
        actions = f'<a href="{escape_html(t.get("tender_url") or dashboard_url)}" style="display:inline-block;padding:6px 14px;background:{color};color:#ffffff;text-decoration:none;font-weight:500;font-size:12px;border-radius:5px;">View →</a>'
        if t.get("pdf_url"):
            actions += f'<a href="{escape_html(t.get("pdf_url"))}" style="display:inline-block;margin-left:6px;padding:6px 14px;border:1px solid #d1d5db;color:#374151;text-decoration:none;font-weight:500;font-size:12px;border-radius:5px;">📄 PDF</a>'
        return f"""
<tr><td style="padding:14px 24px 0;">
  <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;"{rtl}>{sub}</div>
  <div style="font-size:15px;font-weight:600;color:#111827;line-height:1.35;"{rtl}>{escape_html(t.get('title') or '')}</div>
  <div style="margin-top:4px;font-size:12px;color:#6b7280;font-family:ui-monospace,Menlo,monospace;">{meta}</div>
  <div style="margin-top:8px;">{actions}</div>
</td></tr>
<tr><td style="padding:0 24px;"><hr style="border:none;border-top:1px solid #e5e7eb;margin:14px 0;"></td></tr>"""

    if is_digest:
        body_blocks = "".join(_render_card(t) for t in tenders[:25])
        # remove trailing hr
        body_blocks = body_blocks.rstrip()
        if body_blocks.endswith("<hr></td></tr>"):
            body_blocks = body_blocks
        bottom_cta = f'<tr><td align="center" style="padding:8px 24px 22px;"><a href="{escape_html(dashboard_url)}" style="display:inline-block;padding:10px 22px;background:{color};color:#ffffff;text-decoration:none;font-weight:600;font-size:14px;border-radius:6px;">Open dashboard →</a></td></tr>'
        body_html = body_blocks + bottom_cta
    else:
        body_html = _render_single(tenders[0])

    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#111827;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f3f4f6;padding:24px 0;">
  <tr><td align="center"><table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="background:#ffffff;border-radius:10px;overflow:hidden;">
    <tr><td style="background:{color};padding:16px 24px;color:#ffffff;font-size:14px;font-weight:600;letter-spacing:0.5px;">{header_emoji} {('NEW TENDER' if not is_digest else f'{len(tenders)} NEW TENDERS')} — {escape_html(source_label).upper()}</td></tr>
    {body_html}
    <tr><td style="padding:14px 24px 18px;background:#f9fafb;font-size:12px;color:#6b7280;line-height:1.5;border-top:1px solid #e5e7eb;">
      You're receiving this because {audience_explainer}<br>
      <span style="color:#9ca3af;">— ALKHORA Tender Hub · sent from <a href="https://tender.alkhora.com" style="color:#6b7280;">tender.alkhora.com</a></span>
    </td></tr>
  </table></td></tr>
</table>
</body></html>"""

    try:
        frappe.sendmail(
            recipients=recipients,
            subject=subj,
            message=html,
            now=False,
        )
        return {"ok": True, "recipients": recipients, "tenders": len(tenders)}
    except Exception as e:
        frappe.log_error(
            f"notify_new_tenders ({role_name}, {source_label}) failed: {e}",
            "Tender Hub New Tender Notify",
        )
        return {"ok": False, "error": str(e)[:300]}


# ---------------------------------------------------------------------------
# Strip undeliverable recipients (e.g. *.local placeholder addresses) before
# the SMTP server gets them — otherwise a single bad address fails the whole
# batch with SMTPRecipientsRefused and clogs the queue.
# ---------------------------------------------------------------------------
import re

_INVALID_TLDS = (".local", ".invalid", ".test", ".example")

# Hard blocklist — bot/review accounts that should never receive notifications.
# Add or remove addresses here as needed (lowercase). The filter runs before
# every Email Queue insert, so changes take effect on the next email.
_EMAIL_BLOCKLIST = {
    "admin-erp@alkhora.com",
    "applereview@alkhora.com",
    "tender-bot@alkhora.com",
    "apple@alkhora.com",
    "googlereview@alkhora.com",
}


def _is_invalid_email(addr: str) -> bool:
    if not addr:
        return True
    addr = addr.strip().lower()
    if addr in _EMAIL_BLOCKLIST:
        return True
    if "@" not in addr:
        return True
    domain = addr.rsplit("@", 1)[1]
    return any(domain.endswith(tld) for tld in _INVALID_TLDS) or domain in ("localhost", "")


def _strip_addrs_from_to_header(message, blocked_addrs):
    """Remove specific email addresses from the visible 'To:' header in a MIME message."""
    import re
    blocked_lower = {a.lower() for a in blocked_addrs}

    def _replace(match):
        addrs_part = match.group(1)
        addrs = [a.strip() for a in addrs_part.split(",")]
        kept = []
        for a in addrs:
            email_m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", a)
            if email_m and email_m.group(0).lower() in blocked_lower:
                continue
            if a:
                kept.append(a)
        return "To: " + ", ".join(kept) if kept else "To: undisclosed-recipients:;"

    # Match "To: ..." header (handles multi-line folding via leading whitespace)
    return re.sub(
        r"^To:\s*([^\r\n]+(?:\r?\n[ \t]+[^\r\n]+)*)",
        _replace,
        message,
        count=1,
        flags=re.MULTILINE,
    )


def filter_invalid_email_recipients(doc, method=None):
    """Email Queue before_insert hook — remove undeliverable recipients
    AND strip them from the visible 'To:' header so other recipients don't
    see internal/bot addresses."""
    import frappe
    if not getattr(doc, "recipients", None):
        return
    keep = []
    dropped = []
    for r in doc.recipients:
        if _is_invalid_email(r.recipient):
            dropped.append(r.recipient)
        else:
            keep.append(r)
    if not dropped:
        return
    doc.recipients = keep
    if not keep:
        doc.status = "Cancelled"
        doc.error = (doc.error or "") + f"\nAll recipients filtered as undeliverable: {', '.join(dropped)}"
    else:
        # Also strip from the visible "To:" header
        if getattr(doc, "message", None):
            try:
                doc.message = _strip_addrs_from_to_header(doc.message, dropped)
            except Exception as e:
                frappe.logger().warning(f"to-header rewrite failed for {doc.name or '(new)'}: {e}")
        frappe.logger().info(
            f"Email Queue {doc.name or '(new)'}: dropped {len(dropped)} undeliverable recipient(s): {dropped}"
        )

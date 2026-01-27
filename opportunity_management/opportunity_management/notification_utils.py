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

        # Get all active employees in the same department who are managers
        # or have System Manager role
        managers = []

        # Method 1: Get employees marked as managers in the department
        dept_managers = frappe.db.sql("""
            SELECT DISTINCT e.user_id
            FROM `tabEmployee` e
            INNER JOIN `tabDepartment` d ON d.name = e.department
            WHERE e.department = %(department)s
                AND e.status = 'Active'
                AND e.user_id IS NOT NULL
                AND e.user_id != ''
                AND (
                    e.name = d.department_head
                    OR e.reports_to IS NULL
                    OR e.designation LIKE '%%Manager%%'
                    OR e.designation LIKE '%%Head%%'
                    OR e.designation LIKE '%%Director%%'
                )
        """, {"department": department}, as_dict=True)

        for mgr in dept_managers:
            if mgr.user_id and mgr.user_id not in managers:
                managers.append(mgr.user_id)

        # Method 2: Get users with System Manager role in the same department
        system_managers = frappe.db.sql("""
            SELECT DISTINCT e.user_id
            FROM `tabEmployee` e
            INNER JOIN `tabHas Role` hr ON hr.parent = e.user_id
            WHERE e.department = %(department)s
                AND e.status = 'Active'
                AND e.user_id IS NOT NULL
                AND e.user_id != ''
                AND hr.role = 'System Manager'
                AND hr.parenttype = 'User'
        """, {"department": department}, as_dict=True)

        for mgr in system_managers:
            if mgr.user_id and mgr.user_id not in managers:
                managers.append(mgr.user_id)

        # Method 3: Get users with Management role in the same department
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
    """Return list of party identifiers from new or legacy field."""
    parties = []
    if not doc:
        return parties

    if doc.get("custom_responsible_party"):
        for row in doc.custom_responsible_party:
            party = getattr(row, "responsible_party", None) or row.get("responsible_party")
            if party:
                parties.append(party)
        return parties

    if doc.get("custom_resp_eng"):
        for row in doc.custom_resp_eng:
            party = getattr(row, "responsible_engineer", None) or row.get("responsible_engineer")
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

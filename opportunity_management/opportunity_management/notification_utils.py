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

        # 1. Get responsible engineers
        if opportunity.get("custom_resp_eng"):
            for row in opportunity.custom_resp_eng:
                if row.responsible_engineer:
                    # Get user_id from Responsible Engineer
                    emp = frappe.db.get_value(
                        "Employee",
                        row.responsible_engineer,
                        "user_id"
                    )
                    if emp:
                        recipients.add(emp)

        # 2. Get managers from the department of the user who owns/modified the opportunity
        # Try owner first (creator), then modified_by (last person who edited)
        assigner_email = opportunity.owner or opportunity.modified_by

        if assigner_email:
            dept_managers = get_department_managers(assigner_email)
            for mgr in dept_managers:
                recipients.add(mgr)

        # Also check ToDos to see who assigned them
        todos = frappe.get_all(
            "ToDo",
            filters={
                "reference_type": "Opportunity",
                "reference_name": opportunity_name,
                "status": "Open"
            },
            fields=["assigned_by"]
        )

        for todo in todos:
            if todo.assigned_by:
                dept_managers = get_department_managers(todo.assigned_by)
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


def _get_user_from_responsible_engineer(engineer_name):
    """Resolve Responsible Engineer -> user id/email."""
    if not engineer_name:
        return None

    try:
        engineer = frappe.get_doc("Responsible Engineer", engineer_name)

        if hasattr(engineer, "employee") and engineer.employee:
            employee = frappe.get_doc("Employee", engineer.employee)
            return employee.user_id

        if hasattr(engineer, "user") and engineer.user:
            return engineer.user

        if hasattr(engineer, "email") and engineer.email:
            return frappe.db.get_value("User", {"email": engineer.email}, "name")

    except Exception:
        # Fallback: engineer_name might be an Employee record
        employee = frappe.db.get_value("Employee", engineer_name, ["user_id"], as_dict=True)
        if employee and employee.user_id:
            return employee.user_id

    return None


def get_opportunity_assignee_recipients_for_notification(doc, method=None):
    """
    Hook function for Opportunity notifications (assignees + their managers).

    Recipients:
    1. All assigned users (custom_resp_eng + open ToDos allocated_to)
    2. Department managers/system managers of each assigned user

    Args:
        doc: The Opportunity document
        method: The method name (optional)

    Returns:
        List of user emails
    """
    recipients = set()
    assigned_users = set()

    if not doc:
        return []

    # From custom_resp_eng child table
    if doc.get("custom_resp_eng"):
        for row in doc.custom_resp_eng:
            user_id = _get_user_from_responsible_engineer(row.responsible_engineer)
            if user_id:
                assigned_users.add(user_id)

    # From open ToDos linked to this opportunity
    todos = frappe.get_all(
        "ToDo",
        filters={
            "reference_type": "Opportunity",
            "reference_name": doc.name,
            "status": "Open"
        },
        fields=["allocated_to"]
    )

    for todo in todos:
        if todo.allocated_to:
            assigned_users.add(todo.allocated_to)

    # Add assigned users and their department managers
    for user_id in assigned_users:
        recipients.add(user_id)
        dept_managers = get_department_managers(user_id)
        for mgr in dept_managers:
            recipients.add(mgr)

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


def get_todo_recipients_for_notification(doc, method=None):
    """
    Hook function for ToDo notifications.

    Recipients:
    1. The allocated user (allocated_to)
    2. Department managers/system managers of the allocated user

    Args:
        doc: The ToDo document
        method: The method name (optional)

    Returns:
        List of user emails
    """
    recipients = set()

    if doc and doc.allocated_to:
        recipients.add(doc.allocated_to)

        dept_managers = get_department_managers(doc.allocated_to)
        for mgr in dept_managers:
            recipients.add(mgr)

    return list(recipients)

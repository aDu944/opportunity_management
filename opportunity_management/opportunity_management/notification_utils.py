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

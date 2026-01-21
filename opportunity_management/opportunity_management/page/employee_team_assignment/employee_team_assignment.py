import frappe
from frappe import _


@frappe.whitelist()
def get_employees_with_teams():
    """
    Get all employees with their current team/department assignments.
    Also includes employees linked to users.
    """
    employees = frappe.db.sql("""
        SELECT
            e.name,
            e.employee_name,
            e.user_id,
            e.department,
            e.designation,
            e.status,
            u.full_name as user_full_name
        FROM
            `tabEmployee` e
        LEFT JOIN
            `tabUser` u ON e.user_id = u.name
        WHERE
            e.status = 'Active'
        ORDER BY
            e.employee_name
    """, as_dict=True)

    return employees


@frappe.whitelist()
def get_all_departments():
    """Get list of all departments in the system."""
    departments = frappe.get_all(
        "Department",
        fields=["name", "department_name"],
        order_by="department_name"
    )
    return departments


@frappe.whitelist()
def assign_employee_to_team(employee, department):
    """
    Assign an employee to a team/department.

    Args:
        employee: Employee ID
        department: Department name
    """
    try:
        emp_doc = frappe.get_doc("Employee", employee)
        emp_doc.department = department
        emp_doc.save(ignore_permissions=True)

        frappe.db.commit()

        return {
            "status": "success",
            "message": f"Employee {emp_doc.employee_name} assigned to {department}"
        }
    except Exception as e:
        frappe.log_error(f"Failed to assign employee to team: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def bulk_assign_employees(assignments):
    """
    Bulk assign employees to teams.

    Args:
        assignments: JSON string of list of {employee: dept} mappings
    """
    import json

    if isinstance(assignments, str):
        assignments = json.loads(assignments)

    success_count = 0
    error_count = 0
    errors = []

    for assignment in assignments:
        employee = assignment.get("employee")
        department = assignment.get("department")

        if not employee or not department:
            continue

        try:
            emp_doc = frappe.get_doc("Employee", employee)
            emp_doc.department = department
            emp_doc.save(ignore_permissions=True)
            success_count += 1
        except Exception as e:
            error_count += 1
            errors.append(f"{employee}: {str(e)}")
            frappe.log_error(f"Bulk assign error for {employee}: {str(e)}")

    frappe.db.commit()

    return {
        "status": "success" if error_count == 0 else "partial",
        "success_count": success_count,
        "error_count": error_count,
        "errors": errors,
        "message": f"Assigned {success_count} employees. {error_count} errors."
    }


@frappe.whitelist()
def create_department(department_name):
    """
    Create a new department if it doesn't exist.

    Args:
        department_name: Name of the department to create
    """
    try:
        if frappe.db.exists("Department", department_name):
            return {
                "status": "exists",
                "message": f"Department '{department_name}' already exists"
            }

        dept = frappe.get_doc({
            "doctype": "Department",
            "department_name": department_name
        })
        dept.insert(ignore_permissions=True)
        frappe.db.commit()

        return {
            "status": "success",
            "message": f"Department '{department_name}' created successfully"
        }
    except Exception as e:
        frappe.log_error(f"Failed to create department: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def get_employee_stats():
    """Get statistics about employee team assignments."""
    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total_employees,
            COUNT(CASE WHEN department IS NOT NULL THEN 1 END) as assigned,
            COUNT(CASE WHEN department IS NULL THEN 1 END) as unassigned,
            COUNT(CASE WHEN user_id IS NOT NULL THEN 1 END) as linked_to_user
        FROM
            `tabEmployee`
        WHERE
            status = 'Active'
    """, as_dict=True)

    # Get department breakdown
    dept_breakdown = frappe.db.sql("""
        SELECT
            department,
            COUNT(*) as count
        FROM
            `tabEmployee`
        WHERE
            status = 'Active'
            AND department IS NOT NULL
        GROUP BY
            department
        ORDER BY
            count DESC
    """, as_dict=True)

    return {
        "stats": stats[0] if stats else {},
        "department_breakdown": dept_breakdown
    }

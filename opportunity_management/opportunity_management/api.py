"""
API Endpoints for Opportunity Management

Provides data for:
1. My Opportunities page - employee's open tasks
2. KPI Dashboard - completion rate metrics
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, date_diff, flt
from datetime import datetime
from opportunity_management.opportunity_management import notification_utils


def _get_party_display_name(party_name):
    """Resolve display name for Responsible Party/Employee/Shareholder."""
    if not party_name:
        return ""

    if frappe.db.exists("DocType", "Responsible Party") and frappe.db.exists("Responsible Party", party_name):
        return frappe.db.get_value("Responsible Party", party_name, "display_name") or party_name

    if frappe.db.exists("Employee", party_name):
        return frappe.db.get_value("Employee", party_name, "employee_name") or party_name

    if frappe.db.exists("Shareholder", party_name):
        return frappe.db.get_value("Shareholder", party_name, "title") or party_name

    return party_name


def _get_assigned_user_ids(doc):
    users = set()
    if not doc:
        return users

    parties = notification_utils._get_opportunity_party_rows(doc)
    for party in parties:
        info = notification_utils._get_responsible_party_info(party)
        if info.get("user_id"):
            users.add(info.get("user_id"))
    return users


def _is_user_assigned(user, doc):
    if not doc:
        return False
    if doc.owner == user:
        return True
    return user in _get_assigned_user_ids(doc)


@frappe.whitelist()
def get_my_opportunities(user=None, include_completed=False):
    """
    Get opportunity tasks for the current user.

    Args:
        user: Optional - user email (defaults to current user)
        include_completed: Boolean - if True, show only completed opportunities (Closed/Lost/Converted)
                                     if False, show only open opportunities

    Returns a list of opportunities with their assignments and closing dates.
    """
    if not user:
        user = frappe.session.user

    # Debug: Log current user
    frappe.logger().info(f"get_my_opportunities called for user: {user}")

    # Check if user has Sales Manager role
    user_roles = frappe.get_roles(user)
    is_sales_manager = "Sales Manager" in user_roles

    if is_sales_manager:
        # For sales managers, show team opportunities
        return get_team_opportunities_for_user(user, include_completed)
    else:
        # For regular users, show personal opportunities
        return get_personal_opportunities(user, include_completed)


def get_personal_opportunities(user, include_completed=False):
    """
    Get personal opportunity tasks for a user.
    """
    status_filter = ["in", ["Closed", "Lost", "Converted"]] if include_completed else ["not in", ["Closed", "Lost", "Converted"]]
    opps = frappe.get_all(
        "Opportunity",
        filters={"status": status_filter},
        fields=["name"]
    )

    opportunities = []
    today = getdate(nowdate())

    for row in opps:
        opp = frappe.get_doc("Opportunity", row.name)

        if not _is_user_assigned(user, opp):
            continue

        has_quotation = frappe.db.exists("Quotation", {
            "opportunity": opp.name,
            "docstatus": ["!=", 2]
        })

        closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
        days_remaining = date_diff(closing_date, today) if closing_date else None

        if include_completed:
            urgency = "completed"
        elif has_quotation:
            urgency = "low"
        elif days_remaining is None:
            urgency = "unknown"
        elif days_remaining < 0:
            urgency = "overdue"
        elif days_remaining == 0:
            urgency = "due_today"
        elif days_remaining == 1:
            urgency = "critical"
        elif days_remaining <= 3:
            urgency = "high"
        elif days_remaining <= 7:
            urgency = "medium"
        else:
            urgency = "low"

        items = []
        if opp.get("items"):
            for item in opp.items:
                items.append({
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "qty": item.qty,
                    "uom": item.uom,
                    "description": item.description
                })

        opportunities.append({
            "todo_name": None,
            "opportunity": opp.name,
            "opportunity_name": opp.name,
            "customer": opp.party_name,
            "party_name": opp.party_name,
            "closing_date": opp.expected_closing,
            "expected_closing": opp.expected_closing,
            "days_remaining": days_remaining,
            "urgency": urgency,
            "items": items,
            "status": opp.status,
            "status_color": "gray" if days_remaining is None else ("red" if days_remaining < 0 else ("red" if days_remaining == 0 else ("orange" if days_remaining <= 3 else ("yellow" if days_remaining <= 7 else "green")))),
            "status_label": "No closing date" if days_remaining is None else (f"Overdue by {abs(days_remaining)} days" if days_remaining < 0 else ("Due today" if days_remaining == 0 else f"{days_remaining} days remaining")),
            "opportunity_status": opp.status,
            "priority": None,
            "assigned_by": opp.owner,
            "assigned_date": opp.creation,
            "source": opp.source,
            "opportunity_type": opp.opportunity_type,
        })

    opportunities.sort(key=lambda x: (x["days_remaining"] is None, x["days_remaining"] or 9999))

    return opportunities


def get_team_opportunities_for_user(user, include_completed=False):
    """
    Get team opportunities for a manager user.
    """
    # Get user's department
    employee_dept = frappe.db.get_value(
        "Employee",
        {"user_id": user, "status": "Active"},
        "department"
    )

    if not employee_dept:
        # If no department, fall back to personal opportunities
        return get_personal_opportunities(user, include_completed)

    # Group by opportunity and filter by department
    opp_map = {}
    today = getdate(nowdate())

    status_filter = ["in", ["Closed", "Lost", "Converted"]] if include_completed else ["not in", ["Closed", "Lost", "Converted"]]
    opps = frappe.get_all(
        "Opportunity",
        filters={"status": status_filter},
        fields=["name"]
    )

    for row in opps:
        opp = frappe.get_doc("Opportunity", row.name)

        assigned_in_dept = False
        assigned_users = _get_assigned_user_ids(opp)
        for assigned_user in assigned_users:
            engineer_dept = frappe.db.get_value(
                "Employee",
                {"user_id": assigned_user, "status": "Active"},
                "department"
            )
            if engineer_dept == employee_dept:
                assigned_in_dept = True
                break

        # Also include if owner is in the same department
        if not assigned_in_dept and opp.owner:
            owner_dept = frappe.db.get_value(
                "Employee",
                {"user_id": opp.owner, "status": "Active"},
                "department"
            )
            if owner_dept == employee_dept:
                assigned_in_dept = True

        if not assigned_in_dept:
            continue

        has_quotation = frappe.db.exists("Quotation", {
            "opportunity": opp.name,
            "docstatus": ["!=", 2]
        })

        closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
        days_remaining = date_diff(closing_date, today) if closing_date else None

        if include_completed:
            urgency = "completed"
        elif has_quotation:
            urgency = "low"
        elif days_remaining is None:
            urgency = "unknown"
        elif days_remaining < 0:
            urgency = "overdue"
        elif days_remaining == 0:
            urgency = "due_today"
        elif days_remaining == 1:
            urgency = "critical"
        elif days_remaining <= 3:
            urgency = "high"
        elif days_remaining <= 7:
            urgency = "medium"
        else:
            urgency = "low"

        items = []
        if opp.get("items"):
            for item in opp.items:
                items.append({
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "qty": item.qty,
                    "uom": item.uom,
                    "description": item.description
                })

        opp_map[opp.name] = {
            "opportunity": opp.name,
            "customer": opp.party_name,
            "closing_date": opp.expected_closing,
            "days_remaining": days_remaining,
            "urgency": urgency,
            "items": items,
            "status": opp.status,
            "status_color": "gray" if days_remaining is None else ("red" if days_remaining < 0 else ("red" if days_remaining == 0 else ("orange" if days_remaining <= 3 else ("yellow" if days_remaining <= 7 else "green")))),
            "status_label": "No closing date" if days_remaining is None else (f"Overdue by {abs(days_remaining)} days" if days_remaining < 0 else ("Due today" if days_remaining == 0 else f"{days_remaining} days remaining")),
            "opportunity_status": opp.status,
            "source": opp.source,
            "opportunity_type": opp.opportunity_type,
            "assigned_users": list(assigned_users),
            "todo_names": []
        }

    # Convert to list and sort
    opportunities = list(opp_map.values())
    opportunities.sort(key=lambda x: (x["days_remaining"] is None, x["days_remaining"] or 9999))

    return opportunities


@frappe.whitelist()
def get_opportunity_kpi(user=None, date_range="all", from_date=None, to_date=None):
    """
    Get KPI metrics for opportunity completion.
    
    Args:
        user: Optional - filter by specific user, otherwise shows all
        date_range: 'all', 'month', 'quarter', 'year' (deprecated, use from_date/to_date)
        from_date: Optional - start date for filtering
        to_date: Optional - end date for filtering
    
    Returns:
        Dictionary with KPI metrics including on-time completion rate
    """
    filters = {
        "status": ["in", ["Converted", "Closed", "Lost"]]
    }
    
    # Apply date filter - prioritize from_date/to_date over date_range
    if from_date and to_date:
        filters["modified"] = ["between", [getdate(from_date), getdate(to_date)]]
    elif date_range and date_range != "all":
        today = getdate(nowdate())
        if date_range == "month":
            filters["modified"] = [">=", frappe.utils.add_months(today, -1)]
        elif date_range == "quarter":
            filters["modified"] = [">=", frappe.utils.add_months(today, -3)]
        elif date_range == "year":
            filters["modified"] = [">=", frappe.utils.add_months(today, -12)]
    
    # Get closed opportunities
    opportunities = frappe.get_all(
        "Opportunity",
        filters=filters,
        fields=["name", "expected_closing", "modified", "creation", "status", "party_name"]
    )
    
    # Get all open opportunities (for still_open count)
    open_filters = {
        "status": ["not in", ["Converted", "Closed", "Lost"]]
    }
    if from_date and to_date:
        # For open opportunities, check if they have expected_closing in range
        open_filters["expected_closing"] = ["between", [getdate(from_date), getdate(to_date)]]
    
    open_opportunities = frappe.get_all(
        "Opportunity",
        filters=open_filters,
        fields=["name", "expected_closing"]
    )
    
    # Calculate metrics
    total_closed = len(opportunities)
    completed_on_time = 0
    completed_late = 0
    
    completion_days = []
    for opp in opportunities:
        if opp.expected_closing and opp.modified:
            closing_date = getdate(opp.expected_closing)
            completed_date = getdate(opp.modified)
            
            if completed_date <= closing_date:
                completed_on_time += 1
            else:
                completed_late += 1

        if opp.creation and opp.modified:
            completion_days.append(date_diff(getdate(opp.modified), getdate(opp.creation)))
    
    # Calculate total assigned (closed + open)
    total_assigned = total_closed + len(open_opportunities)
    completed = total_closed
    still_open = len(open_opportunities)

    overdue_open = 0
    for opp in open_opportunities:
        if opp.expected_closing and getdate(opp.expected_closing) < getdate(nowdate()):
            overdue_open += 1

    overdue_rate = (overdue_open / still_open * 100) if still_open > 0 else 0

    median_close_days = 0
    if completion_days:
        completion_days.sort()
        mid = len(completion_days) // 2
        if len(completion_days) % 2 == 0:
            median_close_days = (completion_days[mid - 1] + completion_days[mid]) / 2
        else:
            median_close_days = completion_days[mid]
    
    # Calculate per-user metrics if needed
    user_metrics = {}
    if not user:
        user_metrics = calculate_user_metrics(date_range, from_date, to_date)
    
    on_time_rate = (completed_on_time / total_closed * 100) if total_closed > 0 else 0
    
    return {
        "total": total_assigned,  # Frontend expects 'total'
        "completed": completed,  # Frontend expects 'completed'
        "still_open": still_open,  # Frontend expects 'still_open'
        "total_closed": total_closed,  # Keep for backward compatibility
        "completed_on_time": completed_on_time,
        "completed_late": completed_late,
        "on_time_rate": round(on_time_rate, 1),
        "overdue_open": overdue_open,
        "overdue_rate": round(overdue_rate, 1),
        "median_close_days": round(median_close_days, 1),
        "user_metrics": user_metrics,
        "date_range": date_range,
    }


@frappe.whitelist()
def get_kpi_by_employee(from_date=None, to_date=None):
    """
    Get KPI metrics broken down by employee.
    
    Args:
        from_date: Optional - start date for filtering
        to_date: Optional - end date for filtering
    
    Returns:
        List of employee metrics
    """
    return get_kpi_breakdown("employee", from_date, to_date)


@frappe.whitelist()
def get_kpi_by_team(from_date=None, to_date=None):
    """
    Get KPI metrics broken down by team.
    
    Args:
        from_date: Optional - start date for filtering
        to_date: Optional - end date for filtering
    
    Returns:
        List of team metrics
    """
    return get_kpi_breakdown("team", from_date, to_date)


def get_kpi_breakdown(breakdown_type="employee", from_date=None, to_date=None):
    """
    Calculate KPI breakdown by employee or team.
    
    Args:
        breakdown_type: 'employee' or 'team'
        from_date: Optional - start date for filtering
        to_date: Optional - end date for filtering
    """
    breakdown_data = {}

    def _get_key_and_name(user_id):
        user_doc = frappe.get_doc("User", user_id)
        employee_name = user_doc.full_name or user_id

        if breakdown_type == "team":
            employee = frappe.db.get_value("Employee", {"user_id": user_id}, "name")
            if employee:
                emp_doc = frappe.get_doc("Employee", employee)
                team = getattr(emp_doc, "department", None) or getattr(emp_doc, "designation", None) or "Unassigned"
            else:
                team = "Unassigned"
            return team, "team", team

        return user_id, "employee_name", employee_name

    closed_filters = {"status": ["in", ["Converted", "Closed", "Lost"]]}
    if from_date and to_date:
        closed_filters["modified"] = ["between", [getdate(from_date), getdate(to_date)]]

    closed_opps = frappe.get_all(
        "Opportunity",
        filters=closed_filters,
        fields=["name", "expected_closing", "modified"]
    )

    for opp_row in closed_opps:
        opp = frappe.get_doc("Opportunity", opp_row.name)
        assigned_users = _get_assigned_user_ids(opp)
        if not assigned_users and opp.owner:
            assigned_users = {opp.owner}

        for user_id in assigned_users:
            key, name_field, name_value = _get_key_and_name(user_id)
            if key not in breakdown_data:
                breakdown_data[key] = {
                    name_field: name_value,
                    "total": 0,
                    "completed": 0,
                    "completed_on_time": 0,
                    "completed_late": 0,
                    "still_open": 0,
                    "on_time_rate": 0
                }

            breakdown_data[key]["total"] += 1
            breakdown_data[key]["completed"] += 1

            if opp_row.expected_closing and opp_row.modified:
                closing_date = getdate(opp_row.expected_closing)
                completed_date = getdate(opp_row.modified)
                if completed_date <= closing_date:
                    breakdown_data[key]["completed_on_time"] += 1
                else:
                    breakdown_data[key]["completed_late"] += 1

    open_opps = frappe.get_all(
        "Opportunity",
        filters={"status": ["not in", ["Converted", "Closed", "Lost"]]},
        fields=["name"]
    )

    for opp_row in open_opps:
        opp = frappe.get_doc("Opportunity", opp_row.name)
        assigned_users = _get_assigned_user_ids(opp)
        if not assigned_users and opp.owner:
            assigned_users = {opp.owner}

        for user_id in assigned_users:
            key, name_field, name_value = _get_key_and_name(user_id)
            if key not in breakdown_data:
                breakdown_data[key] = {
                    name_field: name_value,
                    "total": 0,
                    "completed": 0,
                    "completed_on_time": 0,
                    "completed_late": 0,
                    "still_open": 0,
                    "on_time_rate": 0
                }
            breakdown_data[key]["total"] += 1
            breakdown_data[key]["still_open"] += 1
    
    # Calculate percentages and prepare result
    result = []
    for key, data in breakdown_data.items():
        if data["completed"] > 0:
            data["on_time_rate"] = round(data["completed_on_time"] / data["completed"] * 100, 1)
        else:
            data["on_time_rate"] = 0
        
        result.append(data)
    
    # Sort by on-time rate descending
    result.sort(key=lambda x: x["on_time_rate"], reverse=True)
    
    return result


def calculate_user_metrics(date_range="all", from_date=None, to_date=None):
    """Calculate KPI metrics per user."""
    closed_filters = {"status": ["in", ["Converted", "Closed", "Lost"]]}
    if from_date and to_date:
        closed_filters["modified"] = ["between", [getdate(from_date), getdate(to_date)]]

    closed_opps = frappe.get_all(
        "Opportunity",
        filters=closed_filters,
        fields=["name", "expected_closing", "modified"]
    )

    user_data = {}

    for opp_row in closed_opps:
        opp = frappe.get_doc("Opportunity", opp_row.name)
        assigned_users = _get_assigned_user_ids(opp)
        if not assigned_users and opp.owner:
            assigned_users = {opp.owner}

        for user in assigned_users:
            if user not in user_data:
                user_data[user] = {
                    "user": user,
                    "user_name": frappe.db.get_value("User", user, "full_name") or user,
                    "total": 0,
                    "on_time": 0,
                    "late": 0
                }

            user_data[user]["total"] += 1
            if opp_row.expected_closing and opp_row.modified:
                closing_date = getdate(opp_row.expected_closing)
                completed_date = getdate(opp_row.modified)
                if completed_date <= closing_date:
                    user_data[user]["on_time"] += 1
                else:
                    user_data[user]["late"] += 1
    
    # Calculate percentages
    for user, data in user_data.items():
        if data["total"] > 0:
            data["on_time_rate"] = round(data["on_time"] / data["total"] * 100, 1)
        else:
            data["on_time_rate"] = 0
    
    # Sort by on-time rate descending
    sorted_users = sorted(user_data.values(), key=lambda x: x["on_time_rate"], reverse=True)
    
    return sorted_users


@frappe.whitelist()
def close_opportunity_todo(todo_name):
    """Deprecated: ToDo-based tasks are no longer used."""
    frappe.throw(_("ToDo-based tasks are disabled. Please update the Opportunity directly."))


@frappe.whitelist()
def get_opportunity_details(opportunity_name):
    """Get detailed information about an opportunity for the dashboard."""
    opp = frappe.get_doc("Opportunity", opportunity_name)

    # Get items
    items = []
    if opp.get("items"):
        for item in opp.items:
            items.append({
                "item_code": item.item_code,
                "item_name": item.item_name,
                "qty": item.qty,
                "uom": item.uom,
                "description": item.description
            })

    # Get assigned parties
    engineers = []
    parties = notification_utils._get_opportunity_party_rows(opp)
    for party in parties:
        engineers.append({
            "engineer": party,
            "name": _get_party_display_name(party)
        })

    return {
        "name": opp.name,
        "party_name": opp.party_name,
        "status": opp.status,
        "expected_closing": opp.expected_closing,
        "source": opp.source,
        "opportunity_type": opp.opportunity_type,
        "items": items,
        "engineers": engineers,
        "contact_person": opp.contact_person,
        "contact_email": opp.contact_email,
    }


@frappe.whitelist()
def get_team_opportunities(team=None, include_completed=False):
    """
    Get opportunities for a team with their assignees.

    Args:
        team: Optional - filter by specific team (department)
              If not provided, defaults to current user's department
        include_completed: Boolean - if True, show only completed opportunities (Closed/Lost/Converted)
                                     if False, show only open opportunities

    Returns:
        List of opportunities with assignee details
    """
    # If no team specified, get current user's department
    if not team:
        current_user = frappe.session.user
        employee_dept = frappe.db.get_value(
            "Employee",
            {"user_id": current_user, "status": "Active"},
            "department"
        )
        if employee_dept:
            team = employee_dept

    # Group by opportunity
    opp_map = {}
    today = getdate(nowdate())

    status_filter = ["in", ["Closed", "Lost", "Converted"]] if include_completed else ["not in", ["Closed", "Lost", "Converted"]]
    opps = frappe.get_all(
        "Opportunity",
        filters={"status": status_filter},
        fields=["name", "party_name", "expected_closing", "status"]
    )

    for row in opps:
        opp = frappe.get_doc("Opportunity", row.name)

        assigned_users = _get_assigned_user_ids(opp)
        if not assigned_users and opp.owner:
            assigned_users = {opp.owner}

        # Build assignee list with departments
        assignees = []
        assigned_departments = set()
        for user in assigned_users:
            user_doc = frappe.get_doc("User", user)
            employee_name = user_doc.full_name or user

            department = None
            employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
            if employee:
                emp_doc = frappe.get_doc("Employee", employee)
                department = getattr(emp_doc, "department", None)
                if department:
                    assigned_departments.add(department)

            assignees.append({
                "user": user,
                "employee": employee_name,
                "department": department
            })

        # Filter by team if specified (skip filtering for "All Teams")
        if team and team != "All Teams":
            if team not in assigned_departments:
                # Also include if owner is in team
                owner_dept = None
                if opp.owner:
                    owner_dept = frappe.db.get_value("Employee", {"user_id": opp.owner, "status": "Active"}, "department")
                if owner_dept != team:
                    continue

        has_quotation = frappe.db.exists("Quotation", {
            "opportunity": opp.name,
            "docstatus": ["!=", 2]
        })

        closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
        days_remaining = date_diff(closing_date, today) if closing_date else None

        if include_completed:
            urgency = "completed"
        elif has_quotation:
            urgency = "low"
        elif days_remaining is None:
            urgency = "unknown"
        elif days_remaining < 0:
            urgency = "overdue"
        elif days_remaining == 0:
            urgency = "due_today"
        elif days_remaining == 1:
            urgency = "critical"
        elif days_remaining <= 3:
            urgency = "high"
        elif days_remaining <= 7:
            urgency = "medium"
        else:
            urgency = "low"

        opp_map[opp.name] = {
            "opportunity": opp.name,
            "customer": opp.party_name,
            "closing_date": str(opp.expected_closing) if opp.expected_closing else None,
            "days_remaining": days_remaining,
            "urgency": urgency,
            "status": opp.status,
            "has_quotation": has_quotation,
            "assignees": assignees
        }

    # Convert to list and sort by urgency
    opportunities = list(opp_map.values())

    # Sort by urgency (most urgent first)
    urgency_order = {"overdue": 0, "due_today": 1, "critical": 2, "high": 3, "medium": 4, "low": 5, "unknown": 6}
    opportunities.sort(key=lambda x: (urgency_order.get(x["urgency"], 99), x["days_remaining"] or 9999))

    # Get employee statistics for the selected team
    employee_stats = get_employee_opportunity_stats(team)

    return {
        "opportunities": opportunities,
        "employee_stats": employee_stats
    }


def get_employee_opportunity_stats(team=None):
    """
    Get statistics for employees in a team showing their open opportunity counts.

    Args:
        team: Optional - filter by specific team (department)
              If "All Teams" or None, show all employees with opportunities

    Returns:
        List of employees with their opportunity counts
    """
    # Count non-overdue opportunities per user
    user_counts = {}
    today = getdate(nowdate())

    opps = frappe.get_all(
        "Opportunity",
        filters={"status": ["not in", ["Closed", "Lost", "Converted"]]},
        fields=["name", "expected_closing", "status", "owner"]
    )

    for opp in opps:
        if opp.expected_closing and getdate(opp.expected_closing) < today:
            continue

        opp_doc = frappe.get_doc("Opportunity", opp.name)
        assigned_users = _get_assigned_user_ids(opp_doc)
        if not assigned_users and opp.owner:
            assigned_users = {opp.owner}

        for user in assigned_users:
            user_counts[user] = user_counts.get(user, 0) + 1

    # Get employee details and filter by team if specified
    employees = []
    for user_email, count in user_counts.items():
        # Get user details
        user_doc = frappe.get_doc("User", user_email)
        employee_name = user_doc.full_name or user_email

        # Get employee department
        department = None
        employee = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
        if employee:
            emp_doc = frappe.get_doc("Employee", employee)
            department = getattr(emp_doc, "department", None)

        # Filter by team if specified (skip for "All Teams")
        if team and team != "All Teams" and department != team:
            continue

        employees.append({
            "user": user_email,
            "employee_name": employee_name,
            "department": department,
            "open_opportunities": count
        })

    # Sort by opportunity count (highest first)
    employees.sort(key=lambda x: x["open_opportunities"], reverse=True)

    return employees


@frappe.whitelist()
def get_available_teams():
    """
    Get list of all available teams (departments) that have opportunities assigned.

    Returns:
        List of team/department names
    """
    departments = set()

    opps = frappe.get_all(
        "Opportunity",
        filters={"status": ["not in", ["Closed", "Lost", "Converted"]]},
        fields=["name", "owner"]
    )

    for opp_row in opps:
        opp = frappe.get_doc("Opportunity", opp_row.name)
        assigned_users = _get_assigned_user_ids(opp)
        if not assigned_users and opp.owner:
            assigned_users = {opp.owner}

        for user in assigned_users:
            department = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "department")
            if department:
                departments.add(department)

    return sorted(departments)

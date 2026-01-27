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
from opportunity_management.utils.assignment import get_user_from_engineer


@frappe.whitelist()
def get_my_opportunities(user=None, include_completed=False):
    """
    Get opportunity tasks for the current user.

    Args:
        user: Optional - user email (defaults to current user)
        include_completed: Boolean - if True, show only completed opportunities (Closed/Lost/Converted)
                                     if False, show only open opportunities

    Returns a list of opportunities with their ToDos and closing dates.
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
    # Get ToDos for this user linked to Opportunities
    todo_filters = {
        "allocated_to": user,
        "reference_type": "Opportunity"
    }

    # For completed opportunities, we don't filter by ToDo status
    # For open opportunities, we only want open ToDos
    if not include_completed:
        todo_filters["status"] = "Open"

    todos = frappe.get_all(
        "ToDo",
        filters=todo_filters,
        fields=["name", "reference_name", "date", "description", "priority", "assigned_by", "creation"]
    )

    # Debug: Log number of todos found
    frappe.logger().info(f"Found {len(todos)} todos for user {user}")

    opportunities = []
    today = getdate(nowdate())
    
    for todo in todos:
        # Get opportunity details
        opp = frappe.get_doc("Opportunity", todo.reference_name)

        # Filter based on include_completed flag
        if include_completed:
            # Only show completed opportunities
            if opp.status not in ["Closed", "Lost", "Converted"]:
                continue
        else:
            # Skip closed/lost/converted opportunities
            if opp.status in ["Closed", "Lost", "Converted"]:
                continue

        # Check if quotation exists for this opportunity
        has_quotation = frappe.db.exists("Quotation", {
            "opportunity": opp.name,
            "docstatus": ["!=", 2]  # Not cancelled
        })

        closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
        days_remaining = date_diff(closing_date, today) if closing_date else None

        # Determine urgency level - for completed opportunities, urgency is based on final status
        if include_completed:
            # For completed opportunities, urgency doesn't matter - we just need a value
            urgency = "completed"
        elif has_quotation:
            # Has quotation, so not urgent even if past closing date
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
        
        # Get items for this opportunity
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
            "todo_name": todo.name,
            "opportunity": opp.name,  # Frontend expects 'opportunity'
            "opportunity_name": opp.name,  # Keep for backward compatibility
            "customer": opp.party_name,  # Frontend expects 'customer'
            "party_name": opp.party_name,  # Keep for backward compatibility
            "closing_date": opp.expected_closing,  # Frontend expects 'closing_date'
            "expected_closing": opp.expected_closing,  # Keep for backward compatibility
            "days_remaining": days_remaining,
            "urgency": urgency,  # Frontend expects 'urgency'
            "items": items,  # Frontend expects 'items'
            "status": opp.status,  # Frontend expects 'status' for completed tab
            "status_color": "gray" if days_remaining is None else ("red" if days_remaining < 0 else ("red" if days_remaining == 0 else ("orange" if days_remaining <= 3 else ("yellow" if days_remaining <= 7 else "green")))),
            "status_label": "No closing date" if days_remaining is None else (f"Overdue by {abs(days_remaining)} days" if days_remaining < 0 else ("Due today" if days_remaining == 0 else f"{days_remaining} days remaining")),
            "opportunity_status": opp.status,
            "priority": todo.priority,
            "assigned_by": todo.assigned_by,
            "assigned_date": todo.creation,
            "source": opp.source,
            "opportunity_type": opp.opportunity_type,
        })
    
    # Sort by days remaining (most urgent first)
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

    # Get ToDos for opportunities in the user's department
    todo_filters = {
        "reference_type": "Opportunity"
    }

    # For completed opportunities, we don't filter by ToDo status
    # For open opportunities, we only want open ToDos
    if not include_completed:
        todo_filters["status"] = "Open"

    todos = frappe.get_all(
        "ToDo",
        filters=todo_filters,
        fields=["name", "reference_name", "allocated_to", "creation", "priority"]
    )

    # Group by opportunity and filter by department
    opp_map = {}
    today = getdate(nowdate())

    for todo in todos:
        opp_name = todo.reference_name

        if opp_name not in opp_map:
            # Get opportunity details
            opp = frappe.get_doc("Opportunity", opp_name)

            # Filter based on include_completed flag
            if include_completed:
                # Only show completed opportunities
                if opp.status not in ["Closed", "Lost", "Converted"]:
                    continue
            else:
                # Skip if opportunity is closed/lost/converted
                if opp.status in ["Closed", "Lost", "Converted"]:
                    continue

            # Check if any assigned engineer is in the user's department
            assigned_in_dept = False
            if opp.get("custom_resp_eng"):
                for row in opp.custom_resp_eng:
                    engineer_user = get_user_from_engineer(row.responsible_engineer)
                    if engineer_user:
                        engineer_dept = frappe.db.get_value(
                            "Employee",
                            {"user_id": engineer_user, "status": "Active"},
                            "department"
                        )
                        if engineer_dept == employee_dept:
                            assigned_in_dept = True
                            break

            if not assigned_in_dept:
                continue

            # Check if quotation exists for this opportunity
            has_quotation = frappe.db.exists("Quotation", {
                "opportunity": opp.name,
                "docstatus": ["!=", 2]  # Not cancelled
            })

            closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
            days_remaining = date_diff(closing_date, today) if closing_date else None

            # Determine urgency level
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

            # Get items for this opportunity
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

            opp_map[opp_name] = {
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
                "assigned_users": [],  # Will collect assigned users
                "todo_names": []  # Will collect todo names
            }

        # Add assigned user and todo
        if opp_name in opp_map:
            opp_map[opp_name]["assigned_users"].append(todo.allocated_to)
            opp_map[opp_name]["todo_names"].append(todo.name)

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
    # Get all closed ToDos for opportunities
    todo_filters = {
        "reference_type": "Opportunity",
        "status": "Closed"
    }
    
    todos = frappe.get_all(
        "ToDo",
        filters=todo_filters,
        fields=["name", "allocated_to", "reference_name", "modified"],
        group_by="allocated_to, reference_name"
    )
    
    # Get all open ToDos for opportunities
    open_todos = frappe.get_all(
        "ToDo",
        filters={
            "reference_type": "Opportunity",
            "status": "Open"
        },
        fields=["name", "allocated_to", "reference_name"]
    )
    
    # Group by employee or team
    breakdown_data = {}
    
    # Process closed todos
    for todo in todos:
        # Apply date filter if provided
        if from_date and to_date:
            todo_date = getdate(todo.modified)
            if not (getdate(from_date) <= todo_date <= getdate(to_date)):
                continue
        
        user = todo.allocated_to
        if not user:
            continue
        
        # Get user details
        user_doc = frappe.get_doc("User", user)
        employee_name = user_doc.full_name or user
        
        # For team breakdown, get team from employee
        if breakdown_type == "team":
            # Try to get team from Employee doctype
            employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
            if employee:
                emp_doc = frappe.get_doc("Employee", employee)
                team = getattr(emp_doc, "department", None) or getattr(emp_doc, "designation", None) or "Unassigned"
            else:
                team = "Unassigned"
            key = team
            name_field = "team"
        else:
            key = user
            name_field = "employee_name"
        
        if key not in breakdown_data:
            breakdown_data[key] = {
                name_field: employee_name if breakdown_type == "employee" else team,
                "total": 0,
                "completed": 0,
                "completed_on_time": 0,
                "completed_late": 0,
                "still_open": 0,
                "on_time_rate": 0
            }
        
        # Get opportunity details
        opp = frappe.db.get_value(
            "Opportunity",
            todo.reference_name,
            ["expected_closing", "status"],
            as_dict=True
        )
        
        if opp and opp.status in ["Converted", "Closed", "Lost"]:
            breakdown_data[key]["total"] += 1
            breakdown_data[key]["completed"] += 1
            
            if opp.expected_closing:
                closing_date = getdate(opp.expected_closing)
                completed_date = getdate(todo.modified)
                
                if completed_date <= closing_date:
                    breakdown_data[key]["completed_on_time"] += 1
                else:
                    breakdown_data[key]["completed_late"] += 1
    
    # Process open todos
    for todo in open_todos:
        user = todo.allocated_to
        if not user:
            continue
        
        # Get user details
        user_doc = frappe.get_doc("User", user)
        employee_name = user_doc.full_name or user
        
        # For team breakdown, get team from employee
        if breakdown_type == "team":
            employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
            if employee:
                emp_doc = frappe.get_doc("Employee", employee)
                team = getattr(emp_doc, "department", None) or getattr(emp_doc, "designation", None) or "Unassigned"
            else:
                team = "Unassigned"
            key = team
        else:
            key = user
        
        if key not in breakdown_data:
            breakdown_data[key] = {
                name_field: employee_name if breakdown_type == "employee" else team,
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
    # Get all users who have been assigned opportunities
    filters = {
        "reference_type": "Opportunity",
        "status": "Closed"
    }
    
    if from_date and to_date:
        filters["modified"] = ["between", [getdate(from_date), getdate(to_date)]]
    
    todos = frappe.get_all(
        "ToDo",
        filters=filters,
        fields=["allocated_to", "reference_name", "modified"],
        group_by="allocated_to, reference_name"
    )
    
    # Group by user
    user_data = {}
    
    for todo in todos:
        user = todo.allocated_to
        if not user:
            continue
        
        if user not in user_data:
            user_data[user] = {
                "user": user,
                "user_name": frappe.db.get_value("User", user, "full_name") or user,
                "total": 0,
                "on_time": 0,
                "late": 0
            }
        
        # Get opportunity details
        opp = frappe.db.get_value(
            "Opportunity",
            todo.reference_name,
            ["expected_closing", "status"],
            as_dict=True
        )
        
        if opp and opp.status in ["Converted", "Closed", "Lost"]:
            user_data[user]["total"] += 1
            
            if opp.expected_closing:
                closing_date = getdate(opp.expected_closing)
                completed_date = getdate(todo.modified)
                
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
    """Mark a ToDo as closed."""
    todo = frappe.get_doc("ToDo", todo_name)
    
    # Check permission
    if todo.allocated_to != frappe.session.user and not frappe.has_permission("ToDo", "write", todo):
        frappe.throw(_("You don't have permission to close this task"))
    
    todo.status = "Closed"
    todo.save(ignore_permissions=True)
    
    return {"status": "success", "message": "Task closed successfully"}


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

    # Get assigned engineers
    engineers = []
    if opp.get("custom_resp_eng"):
        for row in opp.custom_resp_eng:
            engineers.append({
                "engineer": row.responsible_engineer,
                "name": frappe.db.get_value("Responsible Engineer", row.responsible_engineer, "eng_name") or row.responsible_engineer
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

    # Get ToDos for opportunities based on whether we want completed or open
    todo_filters = {
        "reference_type": "Opportunity"
    }

    # For completed opportunities, we don't filter by ToDo status
    # For open opportunities, we only want open ToDos
    if not include_completed:
        todo_filters["status"] = "Open"

    todos = frappe.get_all(
        "ToDo",
        filters=todo_filters,
        fields=["name", "reference_name", "allocated_to", "creation", "priority"]
    )

    # Group by opportunity
    opp_map = {}
    today = getdate(nowdate())

    for todo in todos:
        opp_name = todo.reference_name

        if opp_name not in opp_map:
            # Get opportunity details
            opp = frappe.get_doc("Opportunity", opp_name)

            # Filter based on include_completed flag
            if include_completed:
                # Only show completed opportunities
                if opp.status not in ["Closed", "Lost", "Converted"]:
                    continue
            else:
                # Skip if opportunity is closed/lost/converted
                if opp.status in ["Closed", "Lost", "Converted"]:
                    continue

            # Check if quotation exists for this opportunity
            has_quotation = frappe.db.exists("Quotation", {
                "opportunity": opp.name,
                "docstatus": ["!=", 2]  # Not cancelled
            })

            closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
            days_remaining = date_diff(closing_date, today) if closing_date else None

            # Determine urgency - for completed opportunities, urgency is based on final status
            if include_completed:
                # For completed opportunities, urgency doesn't matter - we just need a value
                urgency = "completed"
            elif has_quotation:
                # Has quotation, so not urgent even if past closing date
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

            opp_map[opp_name] = {
                "opportunity": opp.name,
                "customer": opp.party_name,
                "closing_date": str(opp.expected_closing) if opp.expected_closing else None,
                "days_remaining": days_remaining,
                "urgency": urgency,
                "status": opp.status,
                "has_quotation": has_quotation,
                "assignees": []
            }

        # Get user details
        user = todo.allocated_to
        if user:
            user_doc = frappe.get_doc("User", user)
            employee_name = user_doc.full_name or user

            # Get employee department
            department = None
            employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
            if employee:
                emp_doc = frappe.get_doc("Employee", employee)
                department = getattr(emp_doc, "department", None)

            # Add assignee to opportunity
            opp_map[opp_name]["assignees"].append({
                "user": user,
                "employee": employee_name,
                "department": department
            })

    # Filter by team if specified (skip filtering for "All Teams")
    if team and team != "All Teams":
        filtered_map = {}
        for opp_name, opp_data in opp_map.items():
            # Check if any assignee is in the specified team
            for assignee in opp_data["assignees"]:
                if assignee["department"] == team:
                    filtered_map[opp_name] = opp_data
                    break
        opp_map = filtered_map

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
    # Get all open ToDos linked to opportunities
    todos = frappe.get_all(
        "ToDo",
        filters={
            "reference_type": "Opportunity",
            "status": "Open"
        },
        fields=["allocated_to", "reference_name"]
    )

    # Count non-overdue opportunities per user
    user_counts = {}
    today = getdate(nowdate())
    
    for todo in todos:
        user = todo.allocated_to
        opp_name = todo.reference_name
        
        if user and opp_name:
            # Check if opportunity is not overdue
            opp = frappe.db.get_value("Opportunity", opp_name, ["expected_closing", "status"], as_dict=True)
            
            if opp and opp.status not in ["Closed", "Lost", "Converted"]:
                # Check if not overdue
                is_overdue = False
                if opp.expected_closing:
                    closing_date = getdate(opp.expected_closing)
                    if closing_date < today:
                        is_overdue = True
                
                if not is_overdue:
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
    # Get all departments from employees who are assigned to opportunities
    departments = frappe.db.sql("""
        SELECT DISTINCT e.department
        FROM `tabEmployee` e
        INNER JOIN `tabUser` u ON e.user_id = u.name
        INNER JOIN `tabToDo` t ON t.allocated_to = u.name
        WHERE t.reference_type = 'Opportunity'
        AND t.status = 'Open'
        AND e.department IS NOT NULL
        ORDER BY e.department
    """, as_dict=True)

    return [d.department for d in departments if d.department]

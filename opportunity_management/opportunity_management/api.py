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


def _get_assignment_map(opportunity_names):
    """Bulk resolve assigned users for opportunities without loading full docs."""
    assignment_map = {name: set() for name in opportunity_names}
    if not opportunity_names:
        return assignment_map

    meta = frappe.get_meta("Opportunity")

    # Cache responsible party resolution
    party_cache = {}

    def _resolve_user_id(party_name):
        if not party_name:
            return None
        if party_name in party_cache:
            return party_cache[party_name]
        info = notification_utils._get_responsible_party_info(party_name)
        user_id = info.get("user_id")
        party_cache[party_name] = user_id
        return user_id

    resp_party_field = meta.get_field("custom_responsible_party")
    if resp_party_field and resp_party_field.options:
        rows = frappe.get_all(
            resp_party_field.options,
            filters={
                "parenttype": "Opportunity",
                "parentfield": "custom_responsible_party",
                "parent": ["in", opportunity_names],
            },
            fields=["parent", "responsible_party"],
        )
        for row in rows:
            user_id = _resolve_user_id(row.responsible_party)
            if user_id:
                assignment_map[row.parent].add(user_id)

    return assignment_map


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
    status_filter = None if include_completed else ["not in", ["Closed", "Lost", "Converted"]]
    opp_filters = {"status": status_filter} if status_filter else {}
    opps = frappe.get_all(
        "Opportunity",
        filters=opp_filters,
        fields=["name", "custom_tender_no", "custom_tender_title"]
    )

    opportunities = []
    today = getdate(nowdate())

    for row in opps:
        opp = frappe.get_doc("Opportunity", row.name)

        assigned_users = _get_assigned_user_ids(opp)
        if not assigned_users:
            continue
        if user not in assigned_users and opp.owner != user:
            continue

        has_quotation = frappe.db.exists("Quotation", {
            "opportunity": opp.name,
            "docstatus": ["!=", 2]
        })
        has_draft_quotation = frappe.db.exists("Quotation", {
            "opportunity": opp.name,
            "docstatus": 0
        })

        if include_completed:
            if opp.status not in ["Closed", "Lost", "Converted"] and not has_quotation:
                continue
        else:
            if has_quotation:
                continue

        closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
        days_remaining = date_diff(closing_date, today) if closing_date else None

        if include_completed:
            urgency = "completed"
        elif days_remaining is None:
            urgency = "overdue"
        elif has_quotation:
            urgency = "low"
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

        status_color = "gray" if days_remaining is None else ("red" if days_remaining < 0 else ("red" if days_remaining == 0 else ("orange" if days_remaining <= 3 else ("yellow" if days_remaining <= 7 else "green"))))
        status_label = "Overdue (no closing date)" if days_remaining is None else (f"Overdue by {abs(days_remaining)} days" if days_remaining < 0 else ("Due today" if days_remaining == 0 else f"{days_remaining} days remaining"))

        opportunities.append({
            "todo_name": None,
            "opportunity": opp.name,
            "opportunity_name": opp.name,
            "customer": opp.party_name,
            "party_name": opp.party_name,
            "tender_no": opp.custom_tender_no,
            "tender_title": opp.custom_tender_title,
            "closing_date": opp.expected_closing,
            "expected_closing": opp.expected_closing,
            "days_remaining": days_remaining,
            "urgency": urgency,
            "items": items,
            "status": opp.status,
            "has_quotation": bool(has_quotation),
            "has_draft_quotation": bool(has_draft_quotation),
            "status_color": status_color,
            "status_label": status_label,
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
        if not assigned_users:
            continue
        for assigned_user in assigned_users:
            engineer_dept = frappe.db.get_value(
                "Employee",
                {"user_id": assigned_user, "status": "Active"},
                "department"
            )
            if engineer_dept == employee_dept:
                assigned_in_dept = True
                break

        if not assigned_in_dept:
            continue

        has_quotation = frappe.db.exists("Quotation", {
            "opportunity": opp.name,
            "docstatus": ["!=", 2]
        })
        has_draft_quotation = frappe.db.exists("Quotation", {
            "opportunity": opp.name,
            "docstatus": 0
        })

        closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
        days_remaining = date_diff(closing_date, today) if closing_date else None

        if include_completed:
            urgency = "completed"
        elif days_remaining is None:
            urgency = "overdue"
        elif has_quotation:
            urgency = "low"
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
            "has_quotation": bool(has_quotation),
            "has_draft_quotation": bool(has_draft_quotation),
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
        if not assigned_users:
            continue

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
        if not assigned_users:
            continue

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
        if not assigned_users:
            continue

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

    status_filter = None if include_completed else ["not in", ["Closed", "Lost", "Converted"]]
    opp_filters = {"status": status_filter} if status_filter else {}
    opps = frappe.get_all(
        "Opportunity",
        filters=opp_filters,
        fields=["name", "party_name", "expected_closing", "status", "owner", "custom_tender_no", "custom_tender_title"]
    )

    if not opps:
        return {"opportunities": [], "employee_stats": []}

    opp_names = [o.name for o in opps]
    assignment_map = _get_assignment_map(opp_names)

    assigned_users_set = set()
    for row in opps:
        assigned_users = assignment_map.get(row.name) or set()
        if not assigned_users:
            continue
        assigned_users_set.update(assigned_users)

    user_map = {u.name: (u.full_name or u.name) for u in frappe.get_all(
        "User",
        filters={"name": ["in", list(assigned_users_set)]} if assigned_users_set else {},
        fields=["name", "full_name"]
    )}

    employee_dept_map = {e.user_id: e.department for e in frappe.get_all(
        "Employee",
        filters={"user_id": ["in", list(assigned_users_set)], "status": "Active"} if assigned_users_set else {},
        fields=["user_id", "department"]
    )}

    quotations = frappe.get_all(
        "Quotation",
        filters={"opportunity": ["in", opp_names], "docstatus": ["!=", 2]},
        fields=["name", "opportunity", "docstatus", "modified"]
    )
    quotation_opps = {q.opportunity for q in quotations}
    draft_quotation_opps = {q.opportunity for q in quotations if q.docstatus == 0}
    quotation_name_map = {}
    for q in quotations:
        current = quotation_name_map.get(q.opportunity)
        if not current or (q.modified and q.modified > current["modified"]):
            quotation_name_map[q.opportunity] = {"name": q.name, "modified": q.modified}

    for row in opps:
        assigned_users = assignment_map.get(row.name) or set()
        if not assigned_users:
            continue

        # Build assignee list with departments
        assignees = []
        assigned_departments = set()
        for user in assigned_users:
            employee_name = user_map.get(user, user)
            department = employee_dept_map.get(user)
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
                continue

        has_quotation = row.name in quotation_opps
        has_draft_quotation = row.name in draft_quotation_opps

        if include_completed:
            if row.status not in ["Closed", "Lost", "Converted"] and not has_quotation:
                continue
        else:
            if has_quotation:
                continue

        closing_date = getdate(row.expected_closing) if row.expected_closing else None
        days_remaining = date_diff(closing_date, today) if closing_date else None

        if include_completed:
            urgency = "completed"
        elif days_remaining is None:
            urgency = "overdue"
        elif has_quotation:
            urgency = "low"
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

        opp_map[row.name] = {
            "opportunity": row.name,
            "customer": row.party_name,
            "tender_no": row.custom_tender_no,
            "tender_title": row.custom_tender_title,
            "closing_date": str(row.expected_closing) if row.expected_closing else None,
            "days_remaining": days_remaining,
            "urgency": urgency,
            "status": row.status,
            "has_quotation": has_quotation,
            "has_draft_quotation": has_draft_quotation,
            "quotation_name": quotation_name_map.get(row.name, {}).get("name"),
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
        fields=["name", "expected_closing", "owner"]
    )

    if not opps:
        return []

    opp_names = [o.name for o in opps]
    assignment_map = _get_assignment_map(opp_names)

    for opp in opps:
        if not opp.expected_closing:
            continue
        if getdate(opp.expected_closing) < today:
            continue

        assigned_users = assignment_map.get(opp.name) or set()
        if not assigned_users:
            continue

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

    if not opps:
        return []

    opp_names = [o.name for o in opps]
    assignment_map = _get_assignment_map(opp_names)

    assigned_users_set = set()
    for opp in opps:
        assigned_users = assignment_map.get(opp.name) or set()
        if not assigned_users:
            continue
        assigned_users_set.update(assigned_users)

    if not assigned_users_set:
        return []

    employee_depts = frappe.get_all(
        "Employee",
        filters={"user_id": ["in", list(assigned_users_set)], "status": "Active"},
        fields=["department"]
    )

    for row in employee_depts:
        if row.department:
            departments.add(row.department)

    return sorted(departments)


@frappe.whitelist()
def get_my_fcm_token():
    """Return the FCM token currently stored for the logged-in user."""
    user = frappe.session.user
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        return {"token": None}
    token = frappe.db.get_value("Employee", employee, "custom_fcm_token")
    return {"token": token}


@frappe.whitelist()
def register_fcm_token(token):
    """Store the FCM token on the Employee record for the logged-in user.
    If a different token is already stored (another device), sends a force_logout
    FCM message to that device before replacing the token.
    """
    try:
        from opportunity_management.opportunity_management.fcm_utils import send_fcm
        user = frappe.session.user
        employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if not employee:
            return {"status": "no_employee", "user": user}

        # Evict previously registered device if it's a different token
        old_token = frappe.db.get_value("Employee", employee, "custom_fcm_token")
        if old_token and old_token != token:
            send_fcm(old_token, title="Session Ended", body="You have been logged in on another device.",
                     data={"type": "force_logout"})

        frappe.db.sql(
            "UPDATE `tabEmployee` SET `custom_fcm_token` = %s WHERE `name` = %s",
            (token, employee),
        )
        frappe.db.commit()
        return {"status": "ok", "employee": employee}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "register_fcm_token error")
        frappe.throw(str(e))


@frappe.whitelist()
def submit_late_checkin_leave(employee, checkin_time=None):
    """Auto-submit a Time-Off Leave for a late check-in (9:15:01–9:59:59).
    Records the time range: from 09:00:00 to the actual check-in time.
    If the employee has remaining balance, uses Time-Off Leave type.
    If balance is exhausted, submits the same type — ERPNext will mark it as LWP.
    """
    today = frappe.utils.today()
    leave_type = "Time-Off Leave - زمنية"

    # Avoid duplicate: if a leave already exists for today, skip
    existing = frappe.db.exists("Leave Application", {
        "employee": employee,
        "from_date": today,
        "to_date": today,
        "leave_type": leave_type,
        "docstatus": ["!=", 2],
    })
    if existing:
        return {"status": "already_exists", "leave": existing}

    # Check remaining balance
    try:
        from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
        balance = get_leave_balance_on(employee, leave_type, today)
    except Exception:
        # Fallback balance calculation
        allocated = frappe.db.get_value(
            "Leave Allocation",
            {"employee": employee, "leave_type": leave_type, "docstatus": 1},
            "total_leaves_allocated",
        ) or 0
        used = frappe.db.count(
            "Leave Application",
            {"employee": employee, "leave_type": leave_type, "docstatus": 1},
        )
        balance = float(allocated) - float(used)

    description = (
        "Auto-submitted: late check-in"
        if balance > 0
        else "Auto-submitted: late check-in (balance exhausted — half-day deduction)"
    )

    to_time = checkin_time or frappe.utils.now_datetime().strftime("%H:%M:%S")

    doc = frappe.get_doc({
        "doctype": "Leave Application",
        "employee": employee,
        "leave_type": leave_type,
        "from_date": today,
        "to_date": today,
        "half_day": 1,
        "half_day_date": today,
        "custom_from_time": "09:00:00",
        "custom_to_time": to_time,
        "description": description,
        "status": "Open",
    })
    doc.insert(ignore_permissions=True)
    doc.submit()
    frappe.db.commit()

    status = "time_off_leave" if balance > 0 else "half_day_deduction"
    return {"status": status, "leave": doc.name, "balance_before": balance}


@frappe.whitelist()
def mark_notifications_as_read():
    """Mark all Notification Log entries for the current user as read."""
    frappe.db.sql("""
        UPDATE `tabNotification Log`
        SET `read` = 1
        WHERE `for_user` = %s AND `read` = 0
    """, frappe.session.user)
    frappe.db.commit()
    return {"status": "ok"}


@frappe.whitelist()
def notify_outside_zone_checkin(employee, location_name=None, checkin_time=None):
    """
    Called by the mobile app when an employee checks in outside any approved zone.
    Sends an FCM push notification to all System Manager users.
    """
    from opportunity_management.opportunity_management.fcm_utils import send_fcm_to_user

    emp_name = frappe.db.get_value("Employee", employee, "employee_name") or employee
    loc_label = location_name or "Unknown Location"
    time_label = checkin_time or frappe.utils.now_datetime().strftime("%H:%M")

    title = "Check-in Outside Zone"
    body = f"{emp_name} checked in outside approved zone ({loc_label}) at {time_label}."

    # Find all active System Manager users
    system_managers = frappe.db.sql("""
        SELECT DISTINCT ur.parent AS user
        FROM `tabHas Role` ur
        INNER JOIN `tabUser` u ON u.name = ur.parent
        WHERE ur.role = 'System Manager'
          AND u.enabled = 1
          AND u.user_type = 'System User'
    """, as_dict=True)

    sent = 0
    for row in system_managers:
        try:
            ok = send_fcm_to_user(row["user"], title, body, data={"type": "outside_zone", "employee": employee})
            if ok:
                sent += 1
        except Exception:
            frappe.log_error(frappe.get_traceback(), "notify_outside_zone_checkin FCM error")

    return {"status": "ok", "notified": sent}


@frappe.whitelist()
def get_bank_balances(company=None):
    """
    Return all GL accounts of type 'Bank' for the given company along with
    their current balance. Restricted to System Manager or Accounts Manager.
    """
    try:
        roles = set(frappe.get_roles(frappe.session.user))
        if not ({"System Manager", "Accounts Manager"} & roles):
            return {
                "error": "permission_denied",
                "message": "You need the System Manager or Accounts Manager role to view bank balances.",
                "company": None,
                "accounts": [],
            }

        if not company:
            company = frappe.defaults.get_user_default("Company") or frappe.db.get_value(
                "Company", {}, "name"
            )

        accounts = frappe.db.get_all(
            "Account",
            filters={
                "company": company,
                "account_type": "Bank",
                "is_group": 0,
                "disabled": 0,
            },
            fields=["name", "account_name", "account_currency"],
            order_by="account_name asc",
        )

        from erpnext.accounts.utils import get_balance_on
        today = frappe.utils.nowdate()
        results = []
        for acc in accounts:
            try:
                balance = get_balance_on(account=acc["name"], date=today)
            except Exception:
                balance = 0
            results.append({
                "name": acc["name"],
                "account_name": acc["account_name"],
                "account_currency": acc.get("account_currency") or "IQD",
                "balance": flt(balance),
            })
        return {"company": company, "accounts": results}
    except Exception:
        frappe.log_error(frappe.get_traceback(), "get_bank_balances error")
        return {
            "error": "server_error",
            "message": "Failed to load bank balances.",
            "company": None,
            "accounts": [],
        }


def _is_system_manager() -> bool:
    return "System Manager" in set(frappe.get_roles(frappe.session.user))


@frappe.whitelist(allow_guest=True)
def get_mobile_config():
    """
    Return the runtime configuration for the mobile app.

    Allows administrators to control feature visibility, force-update
    minimum version, maintenance mode, banners, business rules, and
    branding without shipping a new build.

    Marked allow_guest so the app can fetch this BEFORE login (to know
    whether to show the maintenance / update screen).
    """
    try:
        s = frappe.get_single("ESS Mobile Settings")
    except Exception:
        # Doctype not migrated yet — return safe defaults so the app behaves normally.
        return _default_mobile_config()

    def _i(k, default=0):
        v = s.get(k)
        try:
            return int(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _f(k, default=0.0):
        v = s.get(k)
        try:
            return float(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    return {
        "app": {
            "min_app_version": s.get("min_app_version") or "1.0.0",
            "force_update_message_en": s.get("force_update_message_en") or "Please update ALKHORA ESS to the latest version to continue.",
            "force_update_message_ar": s.get("force_update_message_ar") or "يرجى تحديث تطبيق ألخورة لأحدث إصدار للمتابعة.",
            "maintenance_mode": _i("maintenance_mode"),
            "maintenance_message_en": s.get("maintenance_message_en") or "",
            "maintenance_message_ar": s.get("maintenance_message_ar") or "",
            "announcement_banner_en": s.get("announcement_banner_en") or "",
            "announcement_banner_ar": s.get("announcement_banner_ar") or "",
            "welcome_message_en": s.get("welcome_message_en") or "",
            "welcome_message_ar": s.get("welcome_message_ar") or "",
        },

        # Backwards-compatible top-level mirrors (older app versions read here)
        "min_app_version": s.get("min_app_version") or "1.0.0",
        "force_update_message_en": s.get("force_update_message_en") or "",
        "force_update_message_ar": s.get("force_update_message_ar") or "",
        "maintenance_mode": _i("maintenance_mode"),
        "maintenance_message_en": s.get("maintenance_message_en") or "",
        "maintenance_message_ar": s.get("maintenance_message_ar") or "",
        "announcement_banner_en": s.get("announcement_banner_en") or "",
        "announcement_banner_ar": s.get("announcement_banner_ar") or "",

        "modules": {
            "bank_balances": _i("enable_bank_balances", 1),
            "send_notification": _i("enable_send_notification", 1),
            "expenses": _i("enable_expenses", 1),
            "holidays": _i("enable_holidays", 1),
            "announcements": _i("enable_announcements", 1),
            "notifications": _i("enable_notifications", 1),
            "approvals": _i("enable_approvals", 1),
            "geofence_reminders": _i("enable_geofence_reminders", 1),
            "attendance_history_view": _i("enable_attendance_history_view", 1),
        },

        "security": {
            "allow_biometric_login": _i("allow_biometric_login", 1),
            "allow_remember_me": _i("allow_remember_me", 1),
            "session_timeout_minutes": _i("session_timeout_minutes", 0),
            "min_password_length": _i("min_password_length", 8),
            "block_jailbroken_devices": _i("block_jailbroken_devices", 0),
            "screenshot_blur": _i("screenshot_blur", 1),
        },

        "rules": {
            "checkin_window_start_hour": _i("checkin_window_start_hour", 9),
            "checkin_window_end_hour": _i("checkin_window_end_hour", 10),
            "late_checkin_threshold_minutes": _i("late_checkin_threshold_minutes", 15),
            "default_leave_type_for_late_checkin": s.get("default_leave_type_for_late_checkin") or "",
            "auto_checkout_hour": _i("auto_checkout_hour", 0),
            "working_days": s.get("working_days") or "Sun,Mon,Tue,Wed,Thu",
            "min_break_minutes_between_in_out": _i("min_break_minutes_between_in_out", 1),
            "outside_zone_allowed": _i("outside_zone_allowed", 1),
            "require_geofence": _i("require_geofence", 0),
            "default_geofence_radius_m": _i("default_geofence_radius_m", 100),
        },

        "leave": {
            "allowed_leave_types": s.get("allowed_leave_types") or "",
            "min_notice_days_for_annual_leave": _i("min_notice_days_for_annual_leave", 0),
            "max_consecutive_leave_days": _i("max_consecutive_leave_days", 0),
            "allow_self_cancel_leave": _i("allow_self_cancel_leave", 1),
            "allow_attach_medical_certificate": _i("allow_attach_medical_certificate", 1),
        },

        "expenses": {
            "max_expense_amount_per_claim": _f("max_expense_amount_per_claim", 0),
            "max_attachments_per_expense": _i("max_attachments_per_expense", 5),
            "max_attachment_size_mb": _i("max_attachment_size_mb", 10),
            "require_receipt_for_amounts_above": _f("require_receipt_for_amounts_above", 0),
            "default_currency": s.get("default_currency") or "IQD",
        },

        "notifications": {
            "quiet_hours_start": s.get("notif_quiet_hours_start") or "",
            "quiet_hours_end": s.get("notif_quiet_hours_end") or "",
            "sound_override": s.get("notif_sound_override") or "",
            "daily_checkin_reminder_time": s.get("daily_checkin_reminder_time") or "",
            "enable_payslip_notification": _i("enable_payslip_notification", 1),
            "enable_announcement_push": _i("enable_announcement_push", 1),
        },

        "branding": {
            "primary_color_hex": s.get("primary_color_hex") or "#1565C0",
            "support_email": s.get("support_email") or "hr@alkhora.com",
            "support_phone_number": s.get("support_phone_number") or "",
            "support_whatsapp_number": s.get("support_whatsapp_number") or "",
            "feedback_url": s.get("feedback_url") or "",
            "home_quick_links": s.get("home_quick_links") or "",
        },

        "layout": {
            "default_tab": s.get("default_tab") or "home",
            "bottom_nav_layout": s.get("bottom_nav_layout") or "home,attendance,more",
            "default_language": s.get("default_language") or "",
            "allowed_languages": s.get("allowed_languages") or "en,ar",
            "date_format_override": s.get("date_format_override") or "",
            "clock_format_24h": _i("clock_format_24h", 0),
        },

        "telemetry": {
            "enable_crash_reporting": _i("enable_crash_reporting", 1),
            "enable_analytics": _i("enable_analytics", 0),
            "verbose_logging_for_user_ids": s.get("verbose_logging_for_user_ids") or "",
        },
    }


def _default_mobile_config():
    return {
        "min_app_version": "1.0.0",
        "force_update_message_en": "",
        "force_update_message_ar": "",
        "maintenance_mode": 0,
        "maintenance_message_en": "",
        "maintenance_message_ar": "",
        "announcement_banner_en": "",
        "announcement_banner_ar": "",
        "app": {
            "min_app_version": "1.0.0",
            "force_update_message_en": "",
            "force_update_message_ar": "",
            "maintenance_mode": 0,
            "maintenance_message_en": "",
            "maintenance_message_ar": "",
            "announcement_banner_en": "",
            "announcement_banner_ar": "",
            "welcome_message_en": "",
            "welcome_message_ar": "",
        },
        "modules": {
            "bank_balances": 1, "send_notification": 1, "expenses": 1,
            "holidays": 1, "announcements": 1, "notifications": 1,
            "approvals": 1, "geofence_reminders": 1,
            "attendance_history_view": 1,
        },
        "security": {
            "allow_biometric_login": 1, "allow_remember_me": 1,
            "session_timeout_minutes": 0, "min_password_length": 8,
            "block_jailbroken_devices": 0, "screenshot_blur": 1,
        },
        "rules": {
            "checkin_window_start_hour": 9,
            "checkin_window_end_hour": 10,
            "late_checkin_threshold_minutes": 15,
            "default_leave_type_for_late_checkin": "",
            "auto_checkout_hour": 0,
            "working_days": "Sun,Mon,Tue,Wed,Thu",
            "min_break_minutes_between_in_out": 1,
            "outside_zone_allowed": 1,
            "require_geofence": 0,
            "default_geofence_radius_m": 100,
        },
        "leave": {
            "allowed_leave_types": "",
            "min_notice_days_for_annual_leave": 0,
            "max_consecutive_leave_days": 0,
            "allow_self_cancel_leave": 1,
            "allow_attach_medical_certificate": 1,
        },
        "expenses": {
            "max_expense_amount_per_claim": 0.0,
            "max_attachments_per_expense": 5,
            "max_attachment_size_mb": 10,
            "require_receipt_for_amounts_above": 0.0,
            "default_currency": "IQD",
        },
        "notifications": {
            "quiet_hours_start": "",
            "quiet_hours_end": "",
            "sound_override": "",
            "daily_checkin_reminder_time": "",
            "enable_payslip_notification": 1,
            "enable_announcement_push": 1,
        },
        "branding": {
            "primary_color_hex": "#1565C0",
            "support_email": "hr@alkhora.com",
            "support_phone_number": "",
            "support_whatsapp_number": "",
            "feedback_url": "",
            "home_quick_links": "",
        },
        "layout": {
            "default_tab": "home",
            "bottom_nav_layout": "home,attendance,more",
            "default_language": "",
            "allowed_languages": "en,ar",
            "date_format_override": "",
            "clock_format_24h": 0,
        },
        "telemetry": {
            "enable_crash_reporting": 1,
            "enable_analytics": 0,
            "verbose_logging_for_user_ids": "",
        },
    }


@frappe.whitelist()
def get_my_roles():
    """
    Return the list of roles assigned to the currently authenticated user.

    Frappe's built-in `frappe.get_roles` is not whitelisted for the HTTP API
    when the caller is a non-admin (System Manager / Desk User), so the
    mobile app needs this thin wrapper. Only returns the calling user's
    own roles — never anyone else's.
    """
    if frappe.session.user == "Guest":
        return []
    return frappe.get_roles(frappe.session.user)


def _resolve_recipient_employees(mode: str, departments=None, roles=None, employees=None):
    """Resolve a recipients_mode + filters into a list of Employee IDs with FCM tokens."""
    base_filters = {"status": "Active"}
    if mode == "all":
        rows = frappe.db.get_all(
            "Employee",
            filters=base_filters,
            fields=["name"],
        )
    elif mode == "department":
        dept_names = [d.strip() for d in (departments or "").split(",") if d.strip()]
        if not dept_names:
            return []
        # Department is company-scoped — resolve display names to all matching
        # Department records across companies, then filter employees.
        dept_records = frappe.db.get_all(
            "Department",
            filters={"department_name": ["in", dept_names]},
            fields=["name"],
        )
        dept_ids = [d["name"] for d in dept_records]
        if not dept_ids:
            return []
        rows = frappe.db.get_all(
            "Employee",
            filters={**base_filters, "department": ["in", dept_ids]},
            fields=["name"],
        )
    elif mode == "role":
        roles_list = [r.strip() for r in (roles or "").split(",") if r.strip()]
        if not roles_list:
            return []
        # Find users with any of the roles, then map to employees
        user_rows = frappe.db.sql(
            """
            SELECT DISTINCT u.name
            FROM `tabUser` u
            INNER JOIN `tabHas Role` r ON r.parent = u.name
            WHERE u.enabled = 1 AND r.role IN %(roles)s
            """,
            {"roles": tuple(roles_list)},
            as_dict=True,
        )
        users = [u["name"] for u in user_rows]
        if not users:
            return []
        rows = frappe.db.get_all(
            "Employee",
            filters={**base_filters, "user_id": ["in", users]},
            fields=["name"],
        )
    elif mode == "specific":
        emp_list = [e.strip() for e in (employees or "").split(",") if e.strip()]
        if not emp_list:
            return []
        rows = frappe.db.get_all(
            "Employee",
            filters={**base_filters, "name": ["in", emp_list]},
            fields=["name"],
        )
    else:
        return []
    return [r["name"] for r in rows]


@frappe.whitelist()
def get_notification_picker_meta():
    """Return departments, roles, and active employees for the broadcast picker UI."""
    if not _is_system_manager():
        return {"error": "permission_denied", "message": "Only System Managers can broadcast notifications."}

    # Department is company-scoped: the same display name can appear once per
    # company. Deduplicate by department_name so the user sees each name once;
    # the resolver fans the selection back out to all matching records.
    raw_depts = frappe.db.get_all(
        "Department",
        filters={"is_group": 0},
        fields=["department_name"],
        order_by="department_name asc",
    )
    seen = set()
    departments = []
    for d in raw_depts:
        name = d.get("department_name")
        if not name or name in seen:
            continue
        seen.add(name)
        # Use department_name as both the picker value and display label.
        departments.append({"name": name, "department_name": name})
    # Common roles users typically broadcast to (filter out system roles)
    excluded = {"Administrator", "All", "Guest", "System Manager", "Desk User"}
    role_rows = frappe.db.get_all(
        "Role",
        filters={"disabled": 0},
        fields=["name"],
        order_by="name asc",
    )
    roles = [r["name"] for r in role_rows if r["name"] not in excluded]

    employees = frappe.db.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name", "department"],
        order_by="employee_name asc",
        limit_page_length=2000,
    )
    return {
        "departments": departments,
        "roles": roles,
        "employees": employees,
    }


@frappe.whitelist()
def send_admin_notification(title, body, recipients_mode="all",
                             departments=None, roles=None, employees=None,
                             scheduled_at=None):
    """
    Send an FCM notification (or schedule one) to a set of employees.
    Restricted to System Manager. Logs the action as an ESS Broadcast doc.
    """
    if not _is_system_manager():
        return {"error": "permission_denied", "message": "Only System Managers can broadcast notifications."}

    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        return {"error": "invalid", "message": "Title and body are required."}

    # Create the broadcast record (audit log)
    broadcast = frappe.get_doc({
        "doctype": "ESS Broadcast",
        "title": title,
        "body": body,
        "recipients_mode": recipients_mode,
        "departments": departments or "",
        "roles": roles or "",
        "employees": employees or "",
        "status": "Scheduled" if scheduled_at else "Draft",
        "scheduled_at": scheduled_at or None,
    })
    broadcast.insert(ignore_permissions=True)
    frappe.db.commit()

    if scheduled_at:
        return {"status": "scheduled", "broadcast": broadcast.name, "scheduled_at": scheduled_at}

    # Send immediately
    result = _execute_broadcast(broadcast.name)
    return {"status": "sent", "broadcast": broadcast.name, **result}


def _execute_broadcast(broadcast_name: str) -> dict:
    """Execute a broadcast: resolve recipients, send FCM to each, update the record."""
    from opportunity_management.opportunity_management.fcm_utils import send_fcm_to_employee

    doc = frappe.get_doc("ESS Broadcast", broadcast_name)
    employees = _resolve_recipient_employees(
        doc.recipients_mode, doc.departments, doc.roles, doc.employees
    )

    sent = 0
    failed = 0
    errors = []
    for emp_id in employees:
        try:
            ok = send_fcm_to_employee(
                emp_id,
                doc.title,
                doc.body,
                data={"type": "admin_broadcast", "broadcast": doc.name},
            )
            if ok:
                sent += 1
            else:
                failed += 1
                errors.append(f"{emp_id}: no token or send failed")
        except Exception as e:
            failed += 1
            errors.append(f"{emp_id}: {e}")

    doc.db_set("sent_count", sent)
    doc.db_set("failed_count", failed)
    doc.db_set("sent_at", frappe.utils.now_datetime())
    doc.db_set("status", "Sent" if sent > 0 else "Failed")
    if errors:
        doc.db_set("error_log", "\n".join(errors[:50]))
    frappe.db.commit()
    return {"sent": sent, "failed": failed, "total": len(employees)}


def send_daily_checkin_reminders():
    """
    Scheduler hook (every 5 minutes) — sends a check-in reminder push to all
    active employees who haven't checked in yet today.

    Reads `daily_checkin_reminder_time` and `working_days` from
    ESS Mobile Settings. Only fires once per day, only on working days, and
    only within a 5-minute window after the configured time.
    """
    try:
        s = frappe.get_single("ESS Mobile Settings")
    except Exception:
        return

    reminder_time = (s.get("daily_checkin_reminder_time") or "").strip()
    if not reminder_time or ":" not in reminder_time:
        return

    # Working days check (Frappe weekday: Mon=0..Sun=6)
    working_days = {d.strip() for d in (s.get("working_days") or "Sun,Mon,Tue,Wed,Thu").split(",") if d.strip()}
    day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    now = frappe.utils.now_datetime()
    if day_map[now.weekday()] not in working_days:
        return

    # Parse target HH:MM and require we're 0–5 minutes past it
    try:
        target_h, target_m = (int(x) for x in reminder_time.split(":"))
    except (TypeError, ValueError):
        return
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    delta = (now - target).total_seconds()
    if delta < 0 or delta > 300:
        return

    # Idempotency — only one dispatch per day
    today_str = now.strftime("%Y-%m-%d")
    last_sent = frappe.db.get_global("ess_last_daily_reminder_date")
    if last_sent == today_str:
        return

    # Mark sent BEFORE the work so a slow run can't double-fire
    frappe.db.set_global("ess_last_daily_reminder_date", today_str)
    frappe.db.commit()

    today = frappe.utils.today()
    rows = frappe.db.sql(
        """
        SELECT e.name AS employee, e.employee_name, e.user_id, e.custom_fcm_token AS token
        FROM `tabEmployee` e
        WHERE e.status = 'Active'
          AND e.custom_fcm_token IS NOT NULL
          AND e.custom_fcm_token != ''
          AND NOT EXISTS (
              SELECT 1 FROM `tabEmployee Checkin` c
              WHERE c.employee = e.name
                AND DATE(c.time) = %s
                AND c.log_type = 'IN'
          )
        """,
        (today,),
        as_dict=True,
    )

    title = "Check-in Reminder"
    body = "Don't forget to check in for today. تذكّر تسجيل دخولك اليوم."

    from opportunity_management.opportunity_management.fcm_utils import send_fcm
    sent = 0
    for r in rows:
        try:
            ok = send_fcm(
                r["token"],
                title=title,
                body=body,
                data={"type": "daily_reminder"},
            )
            if ok:
                sent += 1
        except Exception:
            frappe.log_error(frappe.get_traceback(), "send_daily_checkin_reminders")

    return {"sent": sent, "skipped_already_in": "ok", "candidates": len(rows)}


def process_scheduled_broadcasts():
    """Scheduler hook — fire any Scheduled broadcasts whose time has come."""
    now = frappe.utils.now_datetime()
    pending = frappe.db.get_all(
        "ESS Broadcast",
        filters={"status": "Scheduled", "scheduled_at": ["<=", now]},
        fields=["name"],
    )
    for row in pending:
        try:
            _execute_broadcast(row["name"])
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"process_scheduled_broadcasts: {row['name']}")


@frappe.whitelist()
def get_expense_categories():
    """Return active ESS Expense Categories with their mapped accounts."""
    try:
        categories = frappe.db.get_all(
            "ESS Expense Category",
            filters={"is_active": 1},
            fields=["name", "category_name", "category_name_ar", "account"],
            order_by="category_name asc",
        )
        # Fetch account currency for each account
        for cat in categories:
            if cat.get("account"):
                currency = frappe.db.get_value(
                    "Account", cat["account"], "account_currency"
                ) or "IQD"
                cat["account_currency"] = currency
        return categories
    except Exception:
        # DocType may not exist yet — return empty so app doesn't crash
        return []


# ---------------------------------------------------------------------------
# Sales Order — items Excel export / import (procurement schedule)
# ---------------------------------------------------------------------------
import frappe
from frappe import _

_SO_ITEM_HEADERS = [
    "row_name",        # opaque key — DO NOT EDIT
    "idx",
    "description",
    "qty",
    "delivery_date",
    "lead_time_weeks",
    "incoterm",
    "origin",
    "transit_days",
    "po_number",
]


@frappe.whitelist()
def so_items_xlsx_export(sales_order: str):
    """Stream the Sales Order's items as an .xlsx download."""
    so = frappe.get_doc("Sales Order", sales_order)
    so.check_permission("read")

    rows = [_SO_ITEM_HEADERS]
    import re as _re
    def _plain(html):
        if not html: return ""
        text = _re.sub(r"<[^>]+>", " ", html)
        text = _re.sub(r"\s+", " ", text)
        return text.strip()

    for it in so.items:
        rows.append([
            it.name,
            it.idx,
            _plain(it.description) or it.item_name or it.item_code,
            it.qty,
            it.delivery_date,
            it.get("custom_lead_time_weeks") or 0,
            it.get("custom_incoterm") or "",
            it.get("custom_origin") or "",
            it.get("custom_transit_days") or 0,
            it.get("custom_po_number") or "",
        ])

    from frappe.utils.xlsxutils import make_xlsx
    xlsx_io = make_xlsx(rows, sheet_name="Items")

    frappe.response["filename"] = f"{sales_order}_items.xlsx"
    frappe.response["filecontent"] = xlsx_io.getvalue()
    frappe.response["type"] = "binary"


@frappe.whitelist()
def so_items_xlsx_import(sales_order: str, file_url: str):
    """Apply updates from an edited xlsx (matched by row_name) and recompute schedule."""
    so = frappe.get_doc("Sales Order", sales_order)
    so.check_permission("write")

    file_doc = frappe.get_doc("File", {"file_url": file_url})
    fpath = file_doc.get_full_path()

    import openpyxl
    wb = openpyxl.load_workbook(fpath, data_only=True)
    ws = wb.active
    raw_rows = list(ws.iter_rows(values_only=True))
    if not raw_rows:
        frappe.throw(_("Empty workbook."))

    header = [str(c).strip() if c is not None else "" for c in raw_rows[0]]
    col = {h: i for i, h in enumerate(header)}
    if "row_name" not in col:
        frappe.throw(_("First row must include the 'row_name' column from the exported template."))

    by_name = {it.name: it for it in so.items}
    updated = 0
    skipped = 0

    from datetime import timedelta, datetime, date as date_cls
    from frappe.utils import getdate, cint

    def _val(row, key):
        i = col.get(key)
        return row[i] if i is not None and i < len(row) else None

    def _to_date(v):
        if v is None or v == "":
            return None
        if isinstance(v, (datetime, date_cls)):
            return v if isinstance(v, date_cls) else v.date()
        return getdate(str(v))

    for row in raw_rows[1:]:
        if not row or all(c is None or c == "" for c in row):
            continue
        rn = _val(row, "row_name")
        if not rn or rn not in by_name:
            skipped += 1
            continue
        item = by_name[rn]

        if "qty" in col and _val(row, "qty") is not None:
            try: item.qty = float(_val(row, "qty"))
            except Exception: pass
        if "delivery_date" in col:
            d = _to_date(_val(row, "delivery_date"))
            if d: item.delivery_date = d
        if "lead_time_weeks" in col:
            item.custom_lead_time_weeks = cint(_val(row, "lead_time_weeks") or 0)
        if "incoterm" in col:
            v = _val(row, "incoterm")
            item.custom_incoterm = (str(v).strip() if v else "")
        if "origin" in col:
            v = _val(row, "origin")
            item.custom_origin = (str(v).strip() if v else "")
        if "transit_days" in col:
            item.custom_transit_days = cint(_val(row, "transit_days") or 0)
        if "po_number" in col:
            v = _val(row, "po_number")
            item.custom_po_number = (str(v).strip() if v else "")

        # Recompute planned order date
        if item.delivery_date:
            wk = cint(item.custom_lead_time_weeks)
            tr = cint(item.custom_transit_days)
            item.custom_planned_order_date = getdate(item.delivery_date) - timedelta(days=wk * 7 + tr)

        updated += 1

    so.save()
    frappe.db.commit()
    return {"updated": updated, "skipped": skipped, "total": len(so.items)}


# ---------------------------------------------------------------------------
# Sales Order — full-page procurement schedule (HTML served via API)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def schedule_html(sales_order: str):
    """Render a full-page Gantt schedule for the given Sales Order.

    Served as raw HTML so it bypasses the website chrome and Jinja sandbox.
    URL: /api/method/opportunity_management.opportunity_management.api.schedule_html?sales_order=<NAME>
    """
    import json as _json
    import re as _re
    so = frappe.get_doc("Sales Order", sales_order)
    so.check_permission("read")

    safety = int(so.get("custom_safety_days") or 0)

    def _plain(html):
        if not html: return ""
        return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", html)).strip()

    items_data = []
    for it in so.items:
        wk = int(it.get("custom_lead_time_weeks") or 0)
        tr = int(it.get("custom_transit_days") or 0)
        # bar_count: how many gantt rows this item will produce
        bar_count = (1 if wk > 0 else 0) + (1 if tr > 0 else 0) + (1 if safety > 0 else 0)
        if bar_count == 0: bar_count = 1  # stock marker
        items_data.append({
            "row_name": it.name,
            "idx": it.idx,
            "description": _plain(it.description) or it.item_name or it.item_code,
            "manufacturer": it.get("custom_manufacturer") or "",
            "bar_count": bar_count,
            "qty": float(it.qty or 0),
            "delivery_date": str(it.delivery_date) if it.delivery_date else None,
            "lead_time_weeks": wk,
            "transit_days":   tr,
            "incoterm":       it.get("custom_incoterm") or "",
            "origin":         it.get("custom_origin") or "",
            "planned_order_date": str(it.get("custom_planned_order_date")) if it.get("custom_planned_order_date") else None,
            "po_number":      it.get("custom_po_number") or "",
        })

    # ---- Build display_rows: groups (shared PO) + individual items ----
    display_rows = []
    seen_groups = set()
    for item in items_data:
        po = item.get("po_number") or ""
        if po and po not in seen_groups:
            seen_groups.add(po)
            group_items = [i for i in items_data if (i.get("po_number") or "") == po]
            planned_dates = [i["planned_order_date"] for i in group_items if i.get("planned_order_date")]
            delivery_dates = [i["delivery_date"] for i in group_items if i.get("delivery_date")]
            mfgs = list({i["manufacturer"] for i in group_items if i.get("manufacturer")})
            display_rows.append({
                "type": "group",
                "po_number": po,
                "manufacturer": " / ".join(mfgs) if mfgs else "",
                "indices": [i["idx"] for i in group_items],
                "items_count": len(group_items),
                "planned_order_date": min(planned_dates) if planned_dates else None,
                "delivery_date": max(delivery_dates) if delivery_dates else None,
                "row_name": "group_" + po,
            })
        elif not po:
            display_rows.append({"type": "item", **item})

    items_json = _json.dumps(items_data)
    rows_json  = _json.dumps(display_rows)
    delivery_fmt = frappe.format(so.delivery_date, {"fieldtype": "Date"}) if so.delivery_date else "—"
    so_date = str(so.transaction_date) if so.transaction_date else ""
    customer = frappe.utils.escape_html(so.customer or so.party_name or "")
    so_name_esc = frappe.utils.escape_html(so.name)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Schedule — {so_name_esc}</title>
<link rel="icon" href="/assets/frappe/images/favicon.png">
<link rel="stylesheet" href="/assets/frappe/node_modules/frappe-gantt/dist/frappe-gantt.css">
<style>
  body {{ font-family: 'Inter', system-ui, -apple-system, sans-serif; background: #f8fafc; margin: 0; padding: 20px; color: #222; }}
  .so-sched {{ max-width: 1400px; margin: 0 auto; }}
  .so-sched header {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:16px 22px; margin-bottom:14px; }}
  .so-sched header h1 {{ margin:6px 0 4px; font-size:22px; color:#296ACC; }}
  .so-sched .meta {{ color:#64748b; font-size:12px; }}
  .back {{ color:#296ACC; text-decoration:none; font-size:13px; }}
  .back:hover {{ text-decoration:underline; }}
  .toolbar {{ display:flex; gap:8px; align-items:center; margin:10px 0; flex-wrap:wrap; }}
  .toolbar button {{ background:#fff; border:1px solid #cbd5e1; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:13px; }}
  .toolbar button:hover {{ border-color:#296ACC; color:#296ACC; }}
  .toolbar button.active {{ background:#296ACC; color:#fff; border-color:#296ACC; }}
  .banner {{ display:flex; gap:18px; flex-wrap:wrap; padding:12px 16px; background:#fff; border:1px solid #e2e8f0; border-radius:10px; font-size:13px; margin-bottom:12px; }}
  .banner b {{ font-size:15px; }}
  .gantt-wrap {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:14px; }}
  .gantt-row {{ display:flex; align-items:stretch; gap:0; }}
  .gantt-left {{ flex:0 0 220px; padding-top:0; font-size:11px; }}
  .gantt-left .row {{ display:flex; align-items:center; padding:0 10px 0 4px; border-right:1px solid #e2e8f0; box-sizing:border-box; overflow:hidden; }}
  .gantt-left .row .num {{ font-weight:700; color:#296ACC; margin-right:6px; min-width:24px; }}
  .gantt-left .row .mfg {{ color:#475569; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .gantt-chart-area {{ flex:1 1 0; min-width:0; overflow-x:scroll; overflow-y:hidden; }}
  .gantt-chart-area::-webkit-scrollbar {{ height:12px; }}
  .gantt-chart-area::-webkit-scrollbar-track {{ background:#f1f5f9; border-radius:6px; }}
  .gantt-chart-area::-webkit-scrollbar-thumb {{ background:#94a3b8; border-radius:6px; }}
  .gantt-chart-area::-webkit-scrollbar-thumb:hover {{ background:#64748b; }}
  .gantt-wrap svg {{ display:block; width:100%; height:auto; }}
  .legend {{ font-size:11px; color:#666; margin-top:10px; }}
  .legend span.sw {{ display:inline-block; width:10px; height:10px; margin-right:4px; border-radius:2px; vertical-align:middle; }}
  .urgent-table {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:0; margin-top:14px; overflow:hidden; }}
  .urgent-table h3 {{ margin:0; padding:12px 16px; font-size:14px; background:#f8fafc; border-bottom:1px solid #e2e8f0; }}
  .urgent-table table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  .urgent-table th, .urgent-table td {{ padding:8px 12px; border-bottom:1px solid #f1f5f9; text-align:left; }}
  .urgent-table th {{ background:#fafbfc; font-weight:600; color:#475569; font-size:11px; text-transform:uppercase; letter-spacing:0.3px; }}
  .urgent-table tr:hover td {{ background:#f8fafc; }}
  .urgent-table input.ed, .urgent-table select.ed {{ border:1px solid #e2e8f0; border-radius:4px; padding:3px 6px; font-size:11px; transition:background 0.3s; }}
  .urgent-table input.ed:focus, .urgent-table select.ed:focus {{ outline:none; border-color:#296ACC; }}
  .bar-mfg.bar-long .bar {{ fill:#dc2626 !important; }}
  .bar-mfg.bar-long .bar-progress {{ fill:#b91c1c !important; }}
  .bar-mfg.bar-med  .bar {{ fill:#f59e0b !important; }}
  .bar-mfg.bar-med  .bar-progress {{ fill:#d97706 !important; }}
  .bar-mfg.bar-short .bar {{ fill:#10b981 !important; }}
  .bar-mfg.bar-short .bar-progress {{ fill:#059669 !important; }}
  .bar-transit .bar {{ fill:#7c3aed !important; }}
  .bar-transit .bar-progress {{ fill:#6d28d9 !important; }}
  .bar-stock .bar {{ fill:#64748b !important; }}
  .bar-stock .bar-progress {{ fill:#475569 !important; }}
  .bar-placed .bar {{ fill:#16a34a !important; }}
  .bar-placed .bar-progress {{ fill:#15803d !important; }}
  .bar-safety .bar {{ fill:#cbd5e1 !important; stroke:#94a3b8; stroke-width:1; stroke-dasharray:3,2; }}
  .bar-safety .bar-progress {{ fill:#94a3b8 !important; }}
  /* Hide in-bar labels and frappe-gantt's narrow click popup — use our own hover tooltip */
  #schedule-gantt .bar-label {{ display:none !important; }}
  .popup-wrapper, .gantt-container .popup-wrapper, .gantt .popup-wrapper {{ display:none !important; }}
  @media print {{
    body {{ background:#fff; padding:5mm; }}
    .toolbar, .back {{ display:none !important; }}
    header, .gantt-wrap, .banner, .urgent-table {{ box-shadow:none; }}
  }}
</style>
</head>
<body>
<div class="so-sched">
  <a class="back" href="/app/sales-order/{so_name_esc}">← Back to Sales Order</a>
  <header>
    <h1>{so_name_esc} — Procurement Schedule</h1>
    <div class="meta">
      Customer: <strong>{customer}</strong> &nbsp;·&nbsp;
      Delivery date: <strong>{delivery_fmt}</strong> &nbsp;·&nbsp;
      Safety buffer: <input id="safety-input" type="number" min="0" value="{safety}" style="width:50px;padding:2px 4px;border:1px solid #cbd5e1;border-radius:4px;">d &nbsp;·&nbsp;
      <span id="item-count">{len(items_data)}</span> item(s)
    </div>
  </header>

  <div id="summary-banner" class="banner"></div>

  <div class="toolbar">
    <span style="color:#475569;font-size:12px;margin-right:6px;">View:</span>
    <button class="vm" data-mode="Day">Day</button>
    <button class="vm active" data-mode="Week">Week</button>
    <button class="vm" data-mode="Month">Month</button>
    <span style="flex:1;"></span>
    <button onclick="window.print()">🖨 Print</button>
  </div>

  <div class="gantt-wrap">
    <div class="gantt-row">
      <div id="gantt-left-panel" class="gantt-left"></div>
      <div class="gantt-chart-area"><svg id="schedule-gantt" style="width:100%;"></svg></div>
    </div>
    <div class="legend">
      <span class="sw" style="background:#16a34a;"></span>✅ PO Placed &nbsp;
      <span class="sw" style="background:#10b981;"></span>&lt; 4 weeks &nbsp;
      <span class="sw" style="background:#f59e0b;"></span>4–8 weeks &nbsp;
      <span class="sw" style="background:#dc2626;"></span>≥ 8 weeks (long-lead) &nbsp;
      <span class="sw" style="background:#64748b;"></span>In stock &nbsp;
      <span class="sw" style="background:#ef4444;"></span>Today &nbsp;
      <span style="color:#888;font-style:italic;margin-left:6px;">Hover a bar for Mfg / Transit / Safety breakdown</span>
    </div>
  </div>

  <div class="urgent-table">
    <h3>Items by Planned Order Date</h3>
    <table>
      <thead><tr>
        <th>#</th><th>Description</th>
        <th>Manufacturer</th>
        <th>Wk</th>
        <th>Transit</th>
        <th>Incoterm</th>
        <th>Origin</th>
        <th>Deliver by</th>
        <th>Order by</th>
        <th>Urgency</th>
        <th>PO #</th>
      </tr></thead>
      <tbody id="urgent-tbody"></tbody>
    </table>
  </div>
</div>

<script src="/assets/frappe/node_modules/frappe-gantt/dist/frappe-gantt.min.js">
</script>
<script>
const SO_NAME     = "{so_name_esc}";
const ITEMS       = {items_json};
const ROWS        = {rows_json};
const SAFETY_DAYS = {safety};
const SO_DATE     = "{so_date}";

function _addDays(d, n) {{
    if (!d) return null;
    const dt = new Date(d);
    dt.setDate(dt.getDate() + n);
    return dt.toISOString().slice(0,10);
}}
function _urgency(planned) {{
    if (!planned) return "";
    const today = new Date(); today.setHours(0,0,0,0);
    const p = new Date(planned); p.setHours(0,0,0,0);
    const days = Math.floor((p - today) / 86400000);
    if (days < 0)   return "🔴 OVERDUE (" + (-days) + "d)";
    if (days <= 7)  return "🟠 NOW (" + days + "d)";
    if (days <= 14) return "🟡 SOON (" + days + "d)";
    return "🟢 OK (" + days + "d)";
}}
function _esc(s) {{ const d=document.createElement("div"); d.textContent=s||""; return d.innerHTML; }}

let CURRENT_VIEW = "Week";
let GANTT = null;

function build_tasks() {{
    const tasks = [];
    ROWS.forEach(function(r) {{
        if (!r.delivery_date || !r.planned_order_date) return;
        if (r.type === "group") {{
            tasks.push({{
                id: r.row_name,
                name: "PO " + r.po_number + " · " + r.manufacturer + " — " + r.items_count + " items (#" + r.indices.join(", #") + ")",
                start: r.planned_order_date,
                end: r.delivery_date,
                progress: 100,
                custom_class: "bar-placed",
                _po: r.po_number,
                _indices: r.indices,
                _count: r.items_count,
                _placed: true,
            }});
        }} else {{
            const wk = r.lead_time_weeks || 0;
            const tr = r.transit_days || 0;
            const order   = r.planned_order_date;
            const ready   = _addDays(order, wk * 7);
            const arrival = _addDays(r.delivery_date, -SAFETY_DAYS);
            const total_days = wk*7 + tr + SAFETY_DAYS;
            let cls;
            if (total_days === 0) cls = "bar-stock";
            else cls = total_days >= 56 ? "bar-mfg bar-long" : (total_days >= 28 ? "bar-mfg bar-med" : "bar-mfg bar-short");
            const breakdown = [];
            if (wk > 0)          breakdown.push("Mfg " + wk + "w");
            if (tr > 0)          breakdown.push("Transit " + tr + "d");
            if (SAFETY_DAYS > 0) breakdown.push("Safety " + SAFETY_DAYS + "d");
            if (!breakdown.length) breakdown.push("In stock");
            const item_label = "#" + r.idx;
            const tag = [r.incoterm, r.origin].filter(Boolean).join(" ");
            const mfg = r.manufacturer ? " · " + r.manufacturer : "";
            tasks.push({{
                id: r.row_name,
                name: item_label + mfg + (tag ? " ("+tag+")" : "") + " — " + breakdown.join(" + "),
                start: total_days === 0 ? _addDays(r.delivery_date, -1) : order,
                end:   r.delivery_date,
                progress: 0,
                custom_class: cls,
                _ready: ready,
                _arrival: arrival,
                _wk: wk, _tr: tr, _safety: SAFETY_DAYS,
            }});
        }}
    }});
    return tasks;
}}

function render_summary() {{
    let n_over=0, n_now=0, n_soon=0, n_ok=0;
    ITEMS.forEach(r => {{
        const u = _urgency(r.planned_order_date);
        if (u.indexOf("OVERDUE") >= 0) n_over++;
        else if (u.indexOf("NOW") >= 0) n_now++;
        else if (u.indexOf("SOON") >= 0) n_soon++;
        else if (r.planned_order_date) n_ok++;
    }});
    document.getElementById("summary-banner").innerHTML =
        '<div><b style="color:#dc2626;">' + n_over + '</b> overdue</div>' +
        '<div><b style="color:#ea580c;">' + n_now + '</b> within 7d</div>' +
        '<div><b style="color:#ca8a04;">' + n_soon + '</b> within 14d</div>' +
        '<div><b style="color:#16a34a;">' + n_ok + '</b> on track</div>';
}}

function render_table() {{
    const tb = document.getElementById("urgent-tbody");
    if (!tb) return;
    const sorted = ITEMS.slice().filter(r => r.planned_order_date)
        .sort((a,b) => new Date(a.planned_order_date) - new Date(b.planned_order_date));
    const incoterms = ["","EXW","FCA","FAS","FOB","CFR","CIF","CPT","CIP","DAP","DPU","DDP"];
    tb.innerHTML = sorted.map(r => {{
        const u = _urgency(r.planned_order_date);
        return '<tr data-row="' + r.row_name + '">' +
            '<td>' + r.idx + '</td>' +
            '<td style="max-width:280px;">' + _esc(r.description ? r.description.substring(0,160) : "") + '</td>' +
            '<td><input class="ed" data-field="manufacturer" value="' + _esc(r.manufacturer || "") + '" style="width:110px;"></td>' +
            '<td><input class="ed" data-field="lead_time_weeks" type="number" min="0" value="' + (r.lead_time_weeks || 0) + '" style="width:50px;"></td>' +
            '<td><input class="ed" data-field="transit_days" type="number" min="0" value="' + (r.transit_days || 0) + '" style="width:55px;"></td>' +
            '<td><select class="ed" data-field="incoterm" style="width:80px;">' +
                incoterms.map(i => '<option value="' + i + '"' + (r.incoterm===i?" selected":"") + '>' + (i||"—") + '</option>').join("") +
                '</select></td>' +
            '<td><input class="ed" data-field="origin" value="' + _esc(r.origin || "") + '" style="width:110px;"></td>' +
            '<td><input class="ed" data-field="delivery_date" type="date" value="' + (r.delivery_date || "") + '" style="width:130px;"></td>' +
            '<td><strong class="po-date">' + (r.planned_order_date || "") + '</strong></td>' +
            '<td><span class="urg">' + u + '</span></td>' +
            '<td><input class="ed" data-field="po_number" placeholder="—" value="' + _esc(r.po_number || "") + '" style="width:110px;"></td>' +
        '</tr>';
    }}).join("");
    bind_inline_editors();
}}

function bind_inline_editors() {{
    document.querySelectorAll(".ed").forEach(function(el) {{
        const handler = function() {{
            const row = el.closest("tr");
            const row_name = row.getAttribute("data-row");
            const field = el.getAttribute("data-field");
            const val = el.value;
            el.style.background = "#fef9c3";
            const params = new URLSearchParams({{ sales_order: SO_NAME, row_name: row_name, field: field, value: val }});
            const url = "/api/method/opportunity_management.opportunity_management.api.update_so_item?" + params.toString();

            function attempt(retries) {{
                return fetch(url, {{ credentials: "same-origin" }})
                    .then(function(r) {{
                        if (!r.ok) {{
                            // Retry once on doc-lock / 5xx (Frappe TimestampMismatchError surfaces as 417/500)
                            if (retries > 0 && (r.status === 417 || r.status >= 500)) {{
                                return new Promise(function(res) {{ setTimeout(function() {{ res(attempt(retries - 1)); }}, 250); }});
                            }}
                            throw new Error("HTTP " + r.status);
                        }}
                        return r.json();
                    }});
            }}

            // Serialize saves through window._so_save_chain so concurrent edits don't fight each other
            window._so_save_chain = (window._so_save_chain || Promise.resolve()).then(function() {{
                return attempt(1).then(function(j) {{
                    if (!j || !j.message) throw new Error("empty response");
                    el.style.background = "#dcfce7";
                    setTimeout(function() {{ el.style.background = ""; }}, 1000);
                    const item = ITEMS.find(function(i) {{ return i.row_name === row_name; }});
                    if (item) {{
                        const fmap = {{ lead_time_weeks: "lead_time_weeks", transit_days: "transit_days", incoterm: "incoterm", origin: "origin", manufacturer: "manufacturer", po_number: "po_number", delivery_date: "delivery_date" }};
                        const target = fmap[field];
                        if (target) item[target] = (el.tagName === "INPUT" && el.type === "number") ? parseInt(val||0,10) : val;
                        item.planned_order_date = j.message.planned_order_date;
                        item.urgency = j.message.urgency;
                        const po_cell = row.querySelector(".po-date");
                        if (po_cell) po_cell.textContent = j.message.planned_order_date || "";
                        const u_cell = row.querySelector(".urg");
                        if (u_cell) u_cell.textContent = j.message.urgency || "";
                    }}
                    rebuild_rows_and_redraw();
                }}).catch(function(err) {{
                    console.error("save failed for", row_name, field, "=", val, ":", err);
                    el.style.background = "#fee2e2";
                    el.title = "Save failed: " + (err.message || "unknown error") + ". Edit again to retry.";
                }});
            }});
        }};
        el.addEventListener("change", handler);
        if (el.tagName === "INPUT" && el.type !== "date" && el.type !== "number") {{
            el.addEventListener("blur", handler);
        }}
    }});

    const safetyEl = document.getElementById("safety-input");
    if (safetyEl && !safetyEl._wired) {{
        safetyEl._wired = true;
        safetyEl.addEventListener("change", function() {{
            safetyEl.style.background = "#fef9c3";
            const sp = new URLSearchParams({{ sales_order: SO_NAME, value: safetyEl.value }});
            fetch("/api/method/opportunity_management.opportunity_management.api.update_so_safety?" + sp.toString(), {{ credentials: "same-origin" }})
                .then(function(r) {{ return r.json(); }})
                .then(function() {{
                    safetyEl.style.background = "#dcfce7";
                    setTimeout(function() {{ safetyEl.style.background = ""; }}, 1000);
                    location.reload();
                }})
                .catch(function() {{ safetyEl.style.background = "#fee2e2"; }});
        }});
    }}
}}

function rebuild_rows_and_redraw() {{
    // Rebuild ROWS from ITEMS (re-grouping by PO)
    const seen = new Set();
    const next_rows = [];
    ITEMS.forEach(function(it) {{
        const po = it.po_number || "";
        if (po && !seen.has(po)) {{
            seen.add(po);
            const grp = ITEMS.filter(i => (i.po_number || "") === po);
            const planned_dates = grp.map(g => g.planned_order_date).filter(Boolean);
            const delivery_dates = grp.map(g => g.delivery_date).filter(Boolean);
            const mfgs = [...new Set(grp.map(g => g.manufacturer).filter(Boolean))];
            next_rows.push({{
                type: "group",
                po_number: po,
                manufacturer: mfgs.join(" / "),
                indices: grp.map(g => g.idx),
                items_count: grp.length,
                planned_order_date: planned_dates.length ? planned_dates.sort()[0] : null,
                delivery_date:      delivery_dates.length ? delivery_dates.sort().slice(-1)[0] : null,
                row_name: "group_" + po,
            }});
        }} else if (!po) {{
            next_rows.push({{ type: "item", ...it }});
        }}
    }});
    ROWS.length = 0;
    next_rows.forEach(r => ROWS.push(r));
    AUTO_PICKED = false;  // re-pick view
    render_summary();
    render_gantt();
}}

function add_today_line(gantt) {{
    try {{
        if (!gantt) return;
        const svg = gantt.$svg || document.querySelector("#schedule-gantt");
        if (!svg) return;
        const start = gantt.gantt_start || (gantt.dates && gantt.dates[0]);
        if (!start) return;
        const today = new Date(); today.setHours(0,0,0,0);
        const start0 = new Date(start); start0.setHours(0,0,0,0);
        const days = (today - start0) / 86400000;
        const opts = gantt.options || {{}};
        const cw = opts.column_width || 38;
        const view = opts.view_mode || "Week";
        let px_per_day = cw;
        if (view === "Half Day") px_per_day = cw * 2;
        else if (view === "Quarter Day") px_per_day = cw * 4;
        else if (view === "Week") px_per_day = cw / 7;
        else if (view === "Month") px_per_day = cw / 30;
        else if (view === "Year") px_per_day = cw / 365;
        const x = days * px_per_day;
        if (!isFinite(x) || x < 0) return;
        const header_h = opts.header_height || 50;
        let total_h = 600;
        try {{ total_h = svg.getBBox().height || 600; }} catch(e) {{}}
        const ns = "http://www.w3.org/2000/svg";
        svg.querySelectorAll(".so-today-marker").forEach(n => n.remove());
        const line = document.createElementNS(ns, "line");
        line.setAttribute("class","so-today-marker");
        line.setAttribute("x1",x); line.setAttribute("x2",x);
        line.setAttribute("y1", header_h - 12); line.setAttribute("y2", total_h);
        line.setAttribute("stroke","#ef4444"); line.setAttribute("stroke-width","1.5");
        line.setAttribute("stroke-dasharray","5,4"); line.setAttribute("opacity","0.85");
        svg.appendChild(line);
        const t = document.createElementNS(ns,"text");
        t.setAttribute("class","so-today-marker");
        t.setAttribute("x", x + 4); t.setAttribute("y", header_h - 16);
        t.setAttribute("fill","#ef4444"); t.setAttribute("font-size","11"); t.setAttribute("font-weight","600");
        t.textContent = "Today"; svg.appendChild(t);
    }} catch(e) {{ console.warn("today-line:", e); }}
}}

function _span_days(tasks) {{
    let mn = null, mx = null;
    tasks.forEach(function(t) {{
        const s = new Date(t.start), e = new Date(t.end);
        if (!mn || s < mn) mn = s;
        if (!mx || e > mx) mx = e;
    }});
    return mn && mx ? Math.ceil((mx - mn) / 86400000) + 7 : 30;
}}

function _auto_pick_view(span) {{
    if (span <= 21) return "Day";
    if (span <= 90) return "Week";
    return "Month";
}}

function _fit_column_width(span_days, view, container_px) {{
    // Fixed-size columns per view. Chart renders at natural width; the .gantt-chart-area
    // wrapper has overflow-x:auto so longer timelines scroll horizontally.
    if (view === "Day")  return 50;
    if (view === "Week") return 120;
    return 380;  // Month
}}

let AUTO_PICKED = false;
function render_gantt() {{
    const tasks = build_tasks();
    const host = document.getElementById("schedule-gantt");
    if (!tasks.length) {{
        host.outerHTML = "<div style='padding:30px;text-align:center;color:#888;'>No items have a Planned Order Date set.</div>";
        return;
    }}
    const span = _span_days(tasks);
    if (!AUTO_PICKED) {{
        CURRENT_VIEW = _auto_pick_view(span);
        AUTO_PICKED = true;

document.querySelectorAll(".vm").forEach(function(b) {{
            b.classList.toggle("active", b.dataset.mode === CURRENT_VIEW);
        }});
    }}
    const wrap = document.querySelector(".gantt-wrap");
    const wrap_w = (wrap && wrap.clientWidth) ? wrap.clientWidth : 1200;
    const col_w = _fit_column_width(span, CURRENT_VIEW, wrap_w);

    GANTT = new Gantt("#schedule-gantt", tasks, {{
        view_mode: CURRENT_VIEW,
        language: "en",
        bar_height: 16,
        padding: 6,
        column_width: col_w,
        custom_popup_html: function(t) {{
            let phases = "";
            if (t._wk !== undefined) {{
                phases = "<div style='font-size:10px;color:#666;margin-top:6px;border-top:1px solid #e2e8f0;padding-top:6px;'>";
                if (t._wk > 0)    phases += "Mfg: <b>" + t._wk + "w</b> &nbsp;→ ready " + t._ready + "<br>";
                if (t._tr > 0)    phases += "Transit: <b>" + t._tr + "d</b> &nbsp;→ arrives " + t._arrival + "<br>";
                if (t._safety > 0) phases += "Safety: <b>" + t._safety + "d</b> &nbsp;→ deliver " + t.end;
                phases += "</div>";
            }}
            return "<div style='padding:8px 12px;'><div style='font-weight:600;'>" + _esc(t.name) +
                   "</div><div style='font-size:11px;color:#666;margin-top:4px;'>Order by: <b>" + t.start +
                   "</b><br>Deliver by: <b>" + t.end + "</b></div>" + phases + "</div>";
        }},
    }});
    setTimeout(function() {{
        add_today_line(GANTT);
        const svg = GANTT && GANTT.$svg ? GANTT.$svg : document.querySelector("#schedule-gantt");
        if (!svg || !GANTT) return;
        try {{
            // Find tightest data range across all tasks
            let mn = null, mx = null;
            (GANTT.tasks || []).forEach(function(t) {{
                if (!mn || t._start < mn) mn = t._start;
                if (!mx || t._end   > mx) mx = t._end;
            }});
            if (!mn || !mx) return;

            const opts = GANTT.options || {{}};
            const cw = opts.column_width || 38;
            const view = opts.view_mode || "Week";
            let px_per_day = cw;
            if (view === "Half Day") px_per_day = cw * 2;
            else if (view === "Quarter Day") px_per_day = cw * 4;
            else if (view === "Week")  px_per_day = cw / 7;
            else if (view === "Month") px_per_day = cw / 30;
            else if (view === "Year")  px_per_day = cw / 365;

            const start = GANTT.gantt_start;
            // Pixel positions inside frappe-gantt's full canvas
            const x_min_data = ((mn - start) / 86400000) * px_per_day;
            const x_max_data = ((mx - start) / 86400000) * px_per_day;
            // Add a little left/right padding for breathing room
            const left_pad  = Math.min(60, x_min_data);
            const right_pad = 30;
            const view_x      = Math.max(0, x_min_data - left_pad);
            const view_width  = (x_max_data - x_min_data) + left_pad + right_pad;

            const bb = svg.getBBox();
            const natural_h = Math.ceil(bb.height);
            const data_w    = Math.ceil(view_width);
            // ViewBox clips year-padding columns by starting at view_x and showing only
            // the data range. SVG dimensions match viewBox 1:1 (no scaling) so bars,
            // text, and the left panel all stay at natural pixel heights.
            svg.setAttribute("viewBox", view_x + " 0 " + data_w + " " + natural_h);
            svg.setAttribute("preserveAspectRatio", "xMinYMin meet");
            svg.style.width  = data_w + "px";
            svg.style.height = natural_h + "px";
            svg.removeAttribute("width");
            svg.removeAttribute("height");

            const HEADER_VB = 50;
            const total_bars = (GANTT.tasks || []).length || 1;
            const real_row = (natural_h - HEADER_VB) / total_bars;
            render_left_panel(real_row, HEADER_VB);
            attach_hover_tooltips(GANTT);
        }} catch(e) {{ console.warn("svg fit:", e); }}
    }}, 80);
}}

// Re-render on window resize for proper fit
window.addEventListener("resize", function() {{
    clearTimeout(window._resize_t);
    window._resize_t = setTimeout(render_gantt, 200);
}});


document.querySelectorAll(".vm").forEach(function(b) {{
    b.addEventListener("click", function() {{
        CURRENT_VIEW = b.dataset.mode;
        document.querySelectorAll(".vm").forEach(function(x) {{ x.classList.remove("active"); }});
        b.classList.add("active");
        render_gantt();
    }});
}});

render_summary();
render_table();
render_gantt();


function attach_hover_tooltips(gantt) {{
    if (!gantt) return;
    const svg = gantt.$svg || document.querySelector("#schedule-gantt");
    if (!svg) return;

    let tooltip = null;
    function _hide() {{
        if (tooltip) {{ tooltip.remove(); tooltip = null; }}
    }}
    function _findTaskFor(el) {{
        let n = el;
        while (n && n !== svg) {{
            const id = n.getAttribute && (n.getAttribute("data-id") || n.id);
            if (id) {{
                const t = (gantt.tasks || []).find(function(t) {{ return t.id === id; }});
                if (t) return t;
            }}
            n = n.parentNode;
        }}
        const wrap = el.closest && (el.closest(".bar-wrapper") || el.closest("[data-id]"));
        if (wrap) {{
            const id = wrap.getAttribute("data-id") || wrap.id;
            return (gantt.tasks || []).find(function(t) {{ return t.id === id; }});
        }}
        return null;
    }}
    function _build(task) {{
        if (task._placed) {{
            return "<div style='font-weight:600;color:#15803d;'>✅ PO Placed: " + _esc(task._po) + "</div>" +
                   "<div style='font-size:11px;color:#666;margin-top:4px;'>" + _esc(task.name) + "</div>" +
                   "<div style='font-size:11px;color:#666;margin-top:4px;border-top:1px solid #e2e8f0;padding-top:6px;'>" +
                     "Earliest order: <b>" + task.start + "</b><br>" +
                     "Latest delivery: <b>" + task.end + "</b><br>" +
                     "Items in PO: <b>" + task._count + "</b>" +
                   "</div>";
        }}
        let phases = "";
        if (task._wk !== undefined) {{
            phases = "<div style='font-size:10px;color:#666;margin-top:6px;border-top:1px solid #e2e8f0;padding-top:6px;'>";
            if (task._wk > 0)     phases += "Mfg: <b>" + task._wk + "w</b> &nbsp;→ ready " + task._ready + "<br>";
            if (task._tr > 0)     phases += "Transit: <b>" + task._tr + "d</b> &nbsp;→ arrives " + task._arrival + "<br>";
            if (task._safety > 0) phases += "Safety: <b>" + task._safety + "d</b> &nbsp;→ deliver " + task.end;
            phases += "</div>";
        }}
        return "<div style='font-weight:600;'>" + _esc(task.name) +
               "</div><div style='font-size:11px;color:#666;margin-top:4px;'>Order by: <b>" + task.start +
               "</b><br>Deliver by: <b>" + task.end + "</b></div>" + phases;
    }}
    function _show(task, anchor_rect) {{
        _hide();
        tooltip = document.createElement("div");
        tooltip.style.cssText =
            "position:absolute;background:white;border:1px solid #cbd5e1;padding:8px 12px;" +
            "border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,0.12);font-size:12px;" +
            "z-index:10000;pointer-events:none;max-width:340px;line-height:1.45;color:#222;";
        tooltip.innerHTML = _build(task);
        document.body.appendChild(tooltip);
        const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
        const vw = window.innerWidth,   vh = window.innerHeight;
        let left = anchor_rect.left + window.scrollX;
        let top  = anchor_rect.bottom + window.scrollY + 8;
        if (left + tw + 10 > vw + window.scrollX) left = vw + window.scrollX - tw - 10;
        if (top + th > window.scrollY + vh)       top  = anchor_rect.top + window.scrollY - th - 8;
        tooltip.style.left = Math.max(8, left) + "px";
        tooltip.style.top  = top + "px";
    }}

    svg.addEventListener("mouseover", function(e) {{
        const task = _findTaskFor(e.target);
        if (!task) return;
        const wrap = (e.target.closest && (e.target.closest(".bar-wrapper, [data-id]"))) || e.target;
        _show(task, wrap.getBoundingClientRect());
    }});
    svg.addEventListener("mouseout", function(e) {{
        const next = e.relatedTarget;
        if (next && svg.contains(next) && _findTaskFor(next)) return;
        _hide();
    }});
    svg.addEventListener("click", function(e) {{
        const task = _findTaskFor(e.target);
        if (!task) {{ _hide(); return; }}
        const wrap = (e.target.closest && (e.target.closest(".bar-wrapper, [data-id]"))) || e.target;
        _show(task, wrap.getBoundingClientRect());
    }});
    window.addEventListener("scroll", _hide, true);
}}


function render_left_panel(row_h, header_h) {{
    const panel = document.getElementById("gantt-left-panel");
    if (!panel) return;
    if (!row_h) {{ row_h = 22; header_h = 50; }}
    panel.style.paddingTop = (header_h || 0) + "px";
    let html = "";
    ROWS.forEach(function(r) {{
        const h = row_h;
        if (r.type === "group") {{
            const mfg = (r.manufacturer || "").replace(/[<>]/g, "");
            html += '<div class="row" style="height:' + h + 'px;background:#f0fdf4;">' +
                      '<span class="num" style="color:#15803d;">PO</span>' +
                      '<span class="mfg" title="PO ' + r.po_number + ' (#' + r.indices.join(", #") + ')" style="font-size:10px;">' +
                        '<b>' + r.po_number + '</b> · ' + (mfg || "—") + ' (' + r.items_count + ')' +
                      '</span>' +
                    '</div>';
        }} else {{
            const _label = (r.manufacturer && r.manufacturer.trim()) ? r.manufacturer : (r.origin || "");
            const mfg = _label.replace(/[<>]/g, "");
            html += '<div class="row" style="height:' + h + 'px;">' +
                      '<span class="num">#' + r.idx + '</span>' +
                      '<span class="mfg" title="' + mfg + '">' + (mfg || '<span style="color:#94a3b8;">—</span>') + '</span>' +
                    '</div>';
        }}
    }});
    panel.innerHTML = html;
}}

</script>
</body>
</html>"""

    from werkzeug.wrappers import Response as _Resp
    return _Resp(html, mimetype="text/html; charset=utf-8")


# ---------------------------------------------------------------------------
# Sales Order — inline edit endpoints (used by the schedule HTML page)
# ---------------------------------------------------------------------------
_SO_ITEM_FIELD_MAP = {
    "lead_time_weeks": "custom_lead_time_weeks",
    "transit_days":    "custom_transit_days",
    "incoterm":        "custom_incoterm",
    "origin":          "custom_origin",
    "manufacturer":    "custom_manufacturer",
    "po_number":       "custom_po_number",
    "delivery_date":   "delivery_date",
}


@frappe.whitelist()
def update_so_item(sales_order, row_name, field, value):
    """Set a single field on a Sales Order Item, recompute planned_order_date, save."""
    target = _SO_ITEM_FIELD_MAP.get(field)
    if not target:
        frappe.throw(f"Field {field} is not editable.")
    so = frappe.get_doc("Sales Order", sales_order)
    so.check_permission("write")
    row = next((it for it in so.items if it.name == row_name), None)
    if not row:
        frappe.throw("Row not found in this Sales Order.")

    from frappe.utils import cint
    if field in ("lead_time_weeks", "transit_days"):
        row.set(target, cint(value or 0))
    elif field == "delivery_date":
        from frappe.utils import getdate
        row.set(target, getdate(value) if value else None)
    else:
        row.set(target, str(value).strip() if value else "")

    # Recompute planned_order_date + urgency
    if row.delivery_date:
        from datetime import timedelta, date
        from frappe.utils import getdate, cint
        wk = cint(row.custom_lead_time_weeks)
        tr = cint(row.custom_transit_days)
        sd = cint(so.get("custom_safety_days") or 0)
        row.custom_planned_order_date = getdate(row.delivery_date) - timedelta(days=wk * 7 + tr + sd)

        # urgency
        days = (row.custom_planned_order_date - date.today()).days
        if days < 0:    row.custom_order_urgency = f"🔴 OVERDUE ({-days}d)"
        elif days <= 7: row.custom_order_urgency = f"🟠 NOW ({days}d)"
        elif days <= 14: row.custom_order_urgency = f"🟡 SOON ({days}d)"
        else:           row.custom_order_urgency = f"🟢 OK ({days}d)"

    so.save()
    frappe.db.commit()
    return {
        "ok": True,
        "planned_order_date": str(row.custom_planned_order_date) if row.custom_planned_order_date else None,
        "urgency":            row.custom_order_urgency,
    }


@frappe.whitelist()
def update_so_safety(sales_order, value):
    """Set Sales Order safety_days; recompute planned_order_date for every item."""
    from frappe.utils import cint, getdate
    from datetime import timedelta, date
    so = frappe.get_doc("Sales Order", sales_order)
    so.check_permission("write")
    so.custom_safety_days = cint(value or 0)
    sd = so.custom_safety_days
    for row in so.items:
        if row.delivery_date:
            wk = cint(row.custom_lead_time_weeks)
            tr = cint(row.custom_transit_days)
            row.custom_planned_order_date = getdate(row.delivery_date) - timedelta(days=wk * 7 + tr + sd)
            days = (row.custom_planned_order_date - date.today()).days
            if days < 0:    row.custom_order_urgency = f"🔴 OVERDUE ({-days}d)"
            elif days <= 7: row.custom_order_urgency = f"🟠 NOW ({days}d)"
            elif days <= 14: row.custom_order_urgency = f"🟡 SOON ({days}d)"
            else:           row.custom_order_urgency = f"🟢 OK ({days}d)"
    so.save()
    frappe.db.commit()
    return {"ok": True, "safety_days": sd}

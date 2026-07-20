"""
API Endpoints for Opportunity Management

Provides data for:
1. My Opportunities page - employee's open tasks
2. KPI Dashboard - completion rate metrics
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, date_diff, flt, cint
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
    # HTTP query params arrive as strings — "0" is truthy in Python, so coerce
    # to int before any truthiness check. Without this, /Open/ tab always
    # shows completed opportunities because "0" evaluates as True.
    include_completed = bool(cint(include_completed))
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
    # HTTP query params come through as strings; coerce so "0" is False.
    include_completed = bool(cint(include_completed))
    # "Quotation" status = a Quotation has been raised → work is done from the
    # opportunity holder's perspective; treated as completed alongside the
    # explicit terminal statuses.
    completed_statuses = ["Closed", "Lost", "Converted", "Quotation"]
    status_filter = None if include_completed else ["not in", completed_statuses]
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
            if opp.status not in completed_statuses and not has_quotation:
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
    include_completed = bool(cint(include_completed))
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

    # "Quotation" status counts as completed alongside Closed / Lost / Converted.
    completed_statuses = ["Closed", "Lost", "Converted", "Quotation"]
    status_filter = ["in", completed_statuses] if include_completed else ["not in", completed_statuses]
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
    # HTTP query params come through as strings; coerce so "0" is False.
    include_completed = bool(cint(include_completed))
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

    # "Quotation" status counts as completed alongside Closed / Lost / Converted.
    completed_statuses = ["Closed", "Lost", "Converted", "Quotation"]
    status_filter = None if include_completed else ["not in", completed_statuses]
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
            if row.status not in completed_statuses and not has_quotation:
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
def get_my_punch_locations():
    """Return the allowed check-in geolocations for the logged-in user.

    Uses `frappe.session.user` to resolve the Employee, then reads the
    Employee.custom_allowed_punch_location child table and hydrates each
    row with its Punch Geolocation coords/radius/names.

    Rationale: hitting /api/resource/Employee/<id> as a regular Employee
    strips the `custom_allowed_punch_location` child rows (v15+ REST
    filters children by child-DocType read perm), and hitting
    /api/resource/Employee Punch Location?filters=[["parent","=",X]] throws
    frappe.PermissionError via check_parent_permission. This endpoint
    sidesteps both by scoping to the caller and joining directly.
    """
    user = frappe.session.user
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    # TEMP diagnostic: log every call so we can prove the mobile app is
    # actually hitting this endpoint (remove after 2026-07-21).
    frappe.log_error(
        title="punch_locations debug",
        message=f"user={user!r} employee={employee!r}",
    )
    if not employee:
        return {"locations": []}

    child_rows = frappe.get_all(
        "Employee Punch Location",
        filters={"parent": employee, "parenttype": "Employee"},
        fields=["punch_geolocation"],
        limit_page_length=200,
        ignore_permissions=True,
    )
    geo_ids = [r["punch_geolocation"] for r in child_rows if r.get("punch_geolocation")]
    if not geo_ids:
        return {"locations": []}

    geo_docs = frappe.get_all(
        "Punch Geolocation",
        filters={"name": ["in", geo_ids]},
        fields=[
            "name",
            "location_name",
            "custom_location_name_ar",
            "latitude",
            "longitude",
            "radius",
        ],
        ignore_permissions=True,
    )
    return {"locations": geo_docs}


@frappe.whitelist()
def get_employee_directory(search=None, branch=None, department=None, limit=200):
    """Return a lightweight, searchable list of active employees for the
    mobile Employee Directory feature.

    Only exposes non-sensitive fields (name, designation, department, branch,
    cell number, company email, image). No salary / DOB / personal_email /
    home address.

    Filters (all optional):
      search     — case-insensitive substring match against name/designation/department/cell/email
      branch     — exact branch match
      department — exact department match
      limit      — cap the result count (default 200; hard max 1000)
    """
    limit = min(int(limit or 200), 1000)

    conditions = ["e.status = 'Active'"]
    values = {}
    if branch:
        conditions.append("e.branch = %(branch)s")
        values["branch"] = branch
    if department:
        conditions.append("e.department = %(department)s")
        values["department"] = department
    if search:
        conditions.append(
            "(e.employee_name LIKE %(q)s OR e.designation LIKE %(q)s OR "
            "e.department LIKE %(q)s OR e.cell_number LIKE %(q)s OR "
            "e.company_email LIKE %(q)s OR e.name LIKE %(q)s)"
        )
        values["q"] = f"%{search}%"

    rows = frappe.db.sql(
        f"""
        SELECT
          e.name,
          e.employee_name,
          e.designation,
          e.department,
          e.branch,
          e.cell_number,
          e.company_email,
          e.image,
          e.user_id
        FROM `tabEmployee` e
        WHERE {' AND '.join(conditions)}
        ORDER BY e.employee_name
        LIMIT {limit}
        """,
        values,
        as_dict=True,
    )
    return rows


@frappe.whitelist(allow_guest=True)
def approve_leave_via_email(name=None, action=None, user=None, exp=None, token=None):
    """One-click leave approve / reject from a signed URL in the notification
    email. Validates: HMAC signature (site secret) + expiry (14 days) +
    recipient has an HR role. On success, updates the leave status + sets
    leave_approver for attribution, then shows a small confirmation page.
    """
    from opportunity_management.opportunity_management.ess_hooks import (
        _sign_leave_action,
    )

    def _page(title, msg, ok):
        color = "green" if ok else "red"
        html = (
            f"<div style='max-width:420px;margin:40px auto;text-align:center;"
            f"font-family:-apple-system,Segoe UI,sans-serif'>"
            f"<div style='width:72px;height:72px;margin:0 auto 16px;"
            f"background:{'#2E7D32' if ok else '#C62828'};color:white;"
            f"font-size:36px;border-radius:50%;display:flex;align-items:center;"
            f"justify-content:center'>{'✓' if ok else '✗'}</div>"
            f"<h2 style='color:{'#2E7D32' if ok else '#C62828'};margin:0 0 8px'>"
            f"{title}</h2><p style='color:#555;font-size:15px'>{msg}</p></div>"
        )
        frappe.respond_as_web_page(title, html, indicator_color=color)

    if not (name and action and user and exp and token):
        return _page("Invalid Link", "Missing required parameters.", ok=False)

    action = action.lower()
    if action not in ("approve", "reject"):
        return _page("Invalid Link", "Unknown action.", ok=False)

    if _sign_leave_action(name, action, user, exp) != token:
        return _page("Invalid Link", "This link has been tampered with or "
                     "is invalid.", ok=False)

    try:
        if int(exp) < int(frappe.utils.now_datetime().timestamp()):
            return _page("Link Expired",
                         "This action link has expired. Please open the leave "
                         "application in ERPNext to review it.", ok=False)
    except (TypeError, ValueError):
        return _page("Invalid Link", "Malformed expiry.", ok=False)

    roles = set(frappe.get_roles(user) or [])
    if not (roles & {"HR Manager", "HR User", "System Manager"}):
        return _page("Not Authorized",
                     f"{user} does not have permission to approve leave.",
                     ok=False)

    if not frappe.db.exists("Leave Application", name):
        return _page("Not Found", "This leave application no longer exists.",
                     ok=False)

    current_status = frappe.db.get_value("Leave Application", name, "status")
    new_status = "Approved" if action == "approve" else "Rejected"
    emp_name = frappe.db.get_value("Leave Application", name, "employee_name") or name

    if current_status == new_status:
        return _page(f"Already {new_status}",
                     f"This leave request for {emp_name} was already "
                     f"{new_status.lower()}.", ok=True)

    # Idempotent update — bypasses workflow so it works regardless of
    # docstatus (0 = draft, 1 = submitted). Cancelled leaves are blocked.
    docstatus = frappe.db.get_value("Leave Application", name, "docstatus")
    if docstatus == 2:
        return _page("Cancelled", "This leave was cancelled and cannot be "
                     "modified.", ok=False)

    frappe.db.set_value("Leave Application", name, {
        "status": new_status,
        "leave_approver": user,
    })
    frappe.db.commit()

    # frappe.db.set_value bypasses doc events, so on_leave_application_update
    # (which sends the FCM push + confirmation email to the employee) never
    # fires. Reload the doc and call the notifier manually.
    try:
        from opportunity_management.opportunity_management.ess_hooks import (
            on_leave_application_update,
        )
        updated = frappe.get_doc("Leave Application", name)
        on_leave_application_update(updated)
    except Exception:
        frappe.log_error(frappe.get_traceback(),
                         "approve_leave_via_email — notify failed")

    return _page(
        f"Leave {new_status}",
        f"You have <b>{new_status.lower()}</b> the leave request for "
        f"<b>{emp_name}</b>. The employee has been notified.",
        ok=True,
    )


@frappe.whitelist()
def register_fcm_token(token, app_version=None, platform=None):
    """Store the FCM token on the Employee record for the logged-in user.
    Also records the reported app version + platform so HR can target
    re-login pushes / migration notices to specific older clients.

    If a different token is already stored (another device), sends a
    force_logout FCM message to that device before replacing the token.
    """
    try:
        from opportunity_management.opportunity_management.fcm_utils import send_fcm
        user = frappe.session.user
        employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if not employee:
            return {"status": "no_employee", "user": user}

        old_token = frappe.db.get_value("Employee", employee, "custom_fcm_token")
        if old_token and old_token != token:
            send_fcm(old_token, title="Session Ended", body="You have been logged in on another device.",
                     data={"type": "force_logout"})

        # Normalise the version string ("1.0.8+15" → "1.0.8+15"; truncate).
        ver = (str(app_version) if app_version else "").strip()[:20] or None
        plat = (str(platform) if platform else "").strip()
        if plat not in ("iOS", "Android"):
            plat = None

        frappe.db.sql(
            """
            UPDATE `tabEmployee`
            SET `custom_fcm_token` = %s,
                `custom_app_version` = COALESCE(%s, `custom_app_version`),
                `custom_app_version_updated` = NOW(),
                `custom_app_platform` = COALESCE(%s, `custom_app_platform`)
            WHERE `name` = %s
            """,
            (token, ver, plat, employee),
        )
        frappe.db.commit()
        return {"status": "ok", "employee": employee,
                "app_version": ver, "platform": plat}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "register_fcm_token error")
        frappe.throw(str(e))


@frappe.whitelist()
def create_offline_checkin(employee, log_type, time, latitude=None, longitude=None,
                          accuracy=None, punch_geolocation=None, outside_zone=0,
                          outside_zone_reason=None):
    """Create an Employee Checkin while preserving the supplied [time].

    The default Employee Checkin `time` field has permlevel=1 in HRMS, which
    means the generic /api/resource/Employee Checkin endpoint silently drops
    the value sent by regular employees and replaces it with "Now" — breaking
    offline-sync timestamps. This endpoint uses ignore_permissions=True so the
    supplied time is honored.

    Guards:
    - The supplied time must be in the past and within the last 48 hours.
    - The caller must own the Employee record (Employee.user_id == session
      user), unless they have an HR role.
    - All existing doc_events (notably before_insert window guard) still run.
    """
    from frappe.utils import get_datetime, now_datetime

    # --- Ownership / role check ------------------------------------------------
    owner_user = frappe.db.get_value("Employee", employee, "user_id")
    bypass_roles = {"Administrator", "System Manager", "HR Manager", "HR User"}
    user_roles = set(frappe.get_roles(frappe.session.user) or [])
    if owner_user != frappe.session.user and not (user_roles & bypass_roles):
        frappe.throw("You can only create check-ins for your own employee record.",
                     frappe.PermissionError)

    # --- Time guards -----------------------------------------------------------
    try:
        t = get_datetime(time)
    except Exception:
        frappe.throw("Invalid time format.")
    if not t:
        frappe.throw("Invalid time.")

    now = now_datetime()
    if t > now:
        frappe.throw("Check-in time cannot be in the future.")
    if (now - t).total_seconds() > 48 * 3600:
        frappe.throw("Offline check-in is too old (older than 48 hours).")

    log_type = (log_type or "").upper()
    if log_type not in ("IN", "OUT"):
        frappe.throw("log_type must be IN or OUT.")

    # --- Build geolocation GeoJSON for the doctype's geolocation field ---------
    geolocation = None
    if latitude is not None and longitude is not None:
        try:
            lat_f = float(latitude)
            lon_f = float(longitude)
            import json as _json
            geolocation = _json.dumps({
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [lon_f, lat_f]},
                }],
            })
        except (TypeError, ValueError):
            pass

    payload = {
        "doctype": "Employee Checkin",
        "employee": employee,
        "log_type": log_type,
        "time": t.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if latitude is not None:
        try: payload["latitude"] = float(latitude)
        except (TypeError, ValueError): pass
    if longitude is not None:
        try: payload["longitude"] = float(longitude)
        except (TypeError, ValueError): pass
    if geolocation:
        payload["geolocation"] = geolocation
    if punch_geolocation:
        payload["custom_punch_geolocation"] = punch_geolocation
    if outside_zone:
        try:
            payload["custom_outside_zone"] = 1 if int(outside_zone) else 0
        except (TypeError, ValueError):
            payload["custom_outside_zone"] = 0
    if outside_zone and outside_zone_reason and str(outside_zone_reason).strip():
        payload["custom_outside_zone_reason"] = str(outside_zone_reason).strip()

    doc = frappe.get_doc(payload)
    # ignore_permissions=True is essential: without it, the permlevel=1
    # restriction on `time` strips the value and Frappe falls back to "Now".
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {
        "name": doc.name,
        "time": str(doc.time),
        "log_type": doc.log_type,
    }


@frappe.whitelist()
def submit_late_checkin_leave(employee, checkin_time=None):
    """Auto-submit a Time-Off Leave for a late check-in (9:15:01–9:59:59).
    Records the time range: from 09:00:00 to the actual check-in time.
    If the employee has remaining balance, uses Time-Off Leave type.
    If balance is exhausted, submits the same type — ERPNext will mark it as LWP.
    """
    today = frappe.utils.today()
    # Default leave type can be overridden via ESS Mobile Settings → Attendance.
    leave_type = "Time-Off Leave - زمنية"
    try:
        s = frappe.get_single("ESS Mobile Settings")
        configured = (s.get("default_leave_type_for_late_checkin") or "").strip()
        if configured:
            leave_type = configured
    except Exception:
        s = None

    # Server-side guard: refuse to create a leave for a check-in that isn't
    # actually late. Older app versions (pre-1.0.6+13) used the wrong anchor
    # (checkin_window_start_hour instead of expected_checkin_hour) and call
    # this endpoint at any check-in past 9:00. We re-validate here so the
    # leave only gets created when the time really is past the cutoff.
    if s is not None:
        try:
            expected_h = int(s.get("expected_checkin_hour") or 9)
            threshold_m = int(s.get("late_checkin_threshold_minutes") or 15)
        except (TypeError, ValueError):
            expected_h, threshold_m = 9, 15

        from frappe.utils import get_datetime
        try:
            t = get_datetime(checkin_time) if checkin_time else frappe.utils.now_datetime()
        except Exception:
            t = frappe.utils.now_datetime()

        # Cutoff = today at expected_h:threshold_m (e.g. 09:15:00).
        # Anything at or before this is on-time; only after is "late".
        on_time_minutes = expected_h * 60 + threshold_m
        actual_minutes = t.hour * 60 + t.minute + (1 if t.second > 0 else 0)
        if actual_minutes <= on_time_minutes:
            return {"status": "on_time", "cutoff": f"{expected_h:02d}:{threshold_m:02d}"}

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
def get_account_ledger(account, limit=100):
    """
    Return the last [limit] posted GL Entry rows for the given account, with
    a running balance.

    Restricted to System Manager / Accounts Manager — same gate as the
    Bank Balances tile.
    """
    try:
        limit = int(limit or 100)
    except (TypeError, ValueError):
        limit = 100

    roles = set(frappe.get_roles(frappe.session.user))
    if not ({"System Manager", "Accounts Manager"} & roles):
        return {"error": "permission_denied",
                "message": "Not permitted.",
                "entries": []}

    rows = frappe.db.sql(
        """
        SELECT
            name, posting_date, voucher_type, voucher_no,
            against, debit, credit, against_voucher_type,
            against_voucher, account_currency
        FROM `tabGL Entry`
        WHERE account = %(account)s AND is_cancelled = 0
        ORDER BY posting_date DESC, creation DESC
        LIMIT %(limit)s
        """,
        {"account": account, "limit": limit},
        as_dict=True,
    )

    # Compute the running balance *forward* (oldest → newest) then reverse.
    rows.reverse()
    running = 0.0
    for r in rows:
        debit = float(r.get("debit") or 0)
        credit = float(r.get("credit") or 0)
        running += debit - credit
        r["balance"] = running
        # Frappe Date / Datetime → ISO string for JSON
        pd = r.get("posting_date")
        r["posting_date"] = pd.isoformat() if hasattr(pd, "isoformat") else (pd or "")
    rows.reverse()

    return {
        "account": account,
        "account_currency": frappe.db.get_value(
            "Account", account, "account_currency") or "IQD",
        "entries": rows,
        "count": len(rows),
    }


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
            "ios_update_url": (s.get("ios_update_url") or "").strip(),
            "android_update_url": (s.get("android_update_url") or "").strip(),
            "force_update_message_en": s.get("force_update_message_en") or "Please update ALKHORA ESS to the latest version to continue.",
            "force_update_message_ar": s.get("force_update_message_ar") or "يرجى تحديث تطبيق الخورة لأحدث إصدار للمتابعة.",
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
            "expected_checkin_hour": _i("expected_checkin_hour", 9),
            "late_checkin_threshold_minutes": _i("late_checkin_threshold_minutes", 15),
            "default_leave_type_for_late_checkin": s.get("default_leave_type_for_late_checkin") or "",
            "auto_checkout_hour": _i("auto_checkout_hour", 0),
            "early_checkout_warning_hour": _i("early_checkout_warning_hour", 0),
            "early_checkout_warning_before_time": (s.get("early_checkout_warning_before_time") or "").strip(),
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
            "ios_update_url": "",
            "android_update_url": "",
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
            "expected_checkin_hour": 9,
            "late_checkin_threshold_minutes": 15,
            "default_leave_type_for_late_checkin": "",
            "auto_checkout_hour": 0,
            "early_checkout_warning_hour": 0,
            "early_checkout_warning_before_time": "",
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


def auto_checkout_pending_employees():
    """
    Scheduler hook (every 5 minutes) — at the configured auto_checkout_hour
    on a working day, force-create an OUT Employee Checkin for every employee
    who has an open IN today but no matching OUT.

    Uses a date-stamped global flag to fire at most once per day.
    """
    try:
        s = frappe.get_single("ESS Mobile Settings")
    except Exception:
        return

    hour = int(s.get("auto_checkout_hour") or 0)
    if hour <= 0:
        return  # disabled

    # Working-day filter
    working_days = {d.strip() for d in (s.get("working_days") or "Sun,Mon,Tue,Wed,Thu").split(",") if d.strip()}
    day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    now = frappe.utils.now_datetime()
    if day_map[now.weekday()] not in working_days:
        return

    # Fire only within 5 min after the configured hour
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    delta = (now - target).total_seconds()
    if delta < 0 or delta > 300:
        return

    today_str = now.strftime("%Y-%m-%d")
    last = frappe.db.get_global("ess_last_auto_checkout_date")
    if last == today_str:
        return
    frappe.db.set_global("ess_last_auto_checkout_date", today_str)
    frappe.db.commit()

    today = frappe.utils.today()
    rows = frappe.db.sql(
        """
        SELECT DISTINCT e.name AS employee
        FROM `tabEmployee` e
        WHERE e.status = 'Active'
          AND EXISTS (
              SELECT 1 FROM `tabEmployee Checkin` c
              WHERE c.employee = e.name
                AND DATE(c.time) = %s
                AND c.log_type = 'IN'
          )
          AND NOT EXISTS (
              SELECT 1 FROM `tabEmployee Checkin` c
              WHERE c.employee = e.name
                AND DATE(c.time) = %s
                AND c.log_type = 'OUT'
                AND c.time > (
                    SELECT MAX(c2.time) FROM `tabEmployee Checkin` c2
                    WHERE c2.employee = e.name
                      AND DATE(c2.time) = %s
                      AND c2.log_type = 'IN'
                )
          )
        """,
        (today, today, today),
        as_dict=True,
    )

    created = 0
    for r in rows:
        try:
            doc = frappe.get_doc({
                "doctype": "Employee Checkin",
                "employee": r["employee"],
                "log_type": "OUT",
                "time": frappe.utils.now_datetime(),
                "custom_outside_zone": 0,
            })
            doc.insert(ignore_permissions=True)
            created += 1
        except Exception:
            frappe.log_error(frappe.get_traceback(), "auto_checkout_pending_employees")
    frappe.db.commit()
    return {"force_checked_out": created}


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
